"""End-to-end SQLite operator contracts without a model provider."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core_python.mcp_server.control_plane.effects_outbox import claim_runtime_effects, complete_runtime_effect
from core_python.mcp_server.control_plane.lifecycle_ops import init_parse0_contract
from core_python.mcp_server.control_plane.operator_ops import admit_runtime_slot, operator_command, release_runtime_slot
from core_python.mcp_server.control_plane.proposals import approve_control_proposal, create_control_proposal
from core_python.mcp_server.control_plane.scheduler_rules import schedule_control_plane_snapshot
from core_python.mcp_server.control_plane_dispatch import dispatch_control_call
from core_python.mcp_server.db_schema import open_ro_connection, open_rw_connection, resolve_storage_paths
from core_python.mcp_server.greatwall_core_mcp import dispatch_tool_call
from core_python.mcp_server.tools_explorer_pull import tool_handback_to_chief


def _init(conn):
    init_parse0_contract(conn, goal_and_completion_md="Study ordinary arithmetic sequences.",
                         subquestions=["Q1", "Q2"], stage="STAGE2_EVOLVE")


def _node(conn, workspace, nid, qid="Q1"):
    worktree = workspace / nid
    worktree.mkdir()
    conn.execute(
        """INSERT INTO lineage_nodes(node_id,question_id,branch_id,worktree_abs_path,created_at,updated_at)
           VALUES(?,?,?,?,datetime('now'),datetime('now'))""", (nid, qid, nid, str(worktree)),
    )


def _command(conn, **args):
    return operator_command(conn, actor_source="human_ui", **args)


def test_fewer_branches_wait_for_real_retirement_without_new_dispatch(tmp_path):
    with closing(open_rw_connection(tmp_path / "gw.sqlite")) as conn:
        _init(conn)
        nodes = ["N1", "N2", "N3", "N4"]
        for nid in nodes:
            _node(conn, tmp_path, nid)
        conn.execute("UPDATE subproblem_runtime_state SET max_active_branches=4 WHERE question_id='Q1'")
        for nid in nodes:
            assert admit_runtime_slot(conn, nid, "host", nid, 1)["admitted"]
        result = _command(
            conn, operation="apply_arrangement",
            arrangements=[
                {"scope_type": "QUESTION", "target_id": "Q1", "max_active_branches": 2,
                 "dispatch_policy": "NO_NEW_DISPATCH", "inflight_drain_mode": "FINISH_CURRENT_TURN"},
                {"scope_type": "QUESTION", "target_id": "Q2", "priority_weight": 200},
            ],
            node_action={"node_ids": ["N3", "N4"], "mode": "retire", "archive_family": True},
        )
        assert result["status"] == "DRAINING"
        assert result["pending_targets"] == nodes
        snap = schedule_control_plane_snapshot(conn)
        assert snap["subproblem_states"]["Q2"]["priority_weight"] == 200
        assert snap["subproblem_states"]["Q1"]["max_active_branches"] == 2
        assert len(snap["operator_slot_ledger"]["draining"]) == 4
        assert not snap["explorers_ready_to_run"]
        assert not admit_runtime_slot(conn, "N1", "host", "duplicate", 1)["admitted"]
        effects = claim_runtime_effects(conn, owner_instance_id="host", kinds=["CANCEL_NODE_SESSION"])["claimed"]
        for effect in effects:
            complete_runtime_effect(
                conn, seq=effect["seq"], owner_instance_id="host", effect_key=effect["effect_key"],
                target_generation=effect["target_generation"], claim_attempt=effect["attempts"],
            )
        for nid in nodes:
            release_runtime_slot(conn, nid, "host", nid)
        final = schedule_control_plane_snapshot(conn)
        assert final["operation_receipts"][0]["status"] == "SETTLED"
        assert final["operator_slot_ledger"]["draining"] == []
        assert {r[0] for r in conn.execute("SELECT node_id FROM lineage_nodes WHERE node_status='RETIRED'")} == {"N3", "N4"}


def test_replacement_and_timed_arrangements_preserve_other_keys(tmp_path):
    with closing(open_rw_connection(tmp_path / "gw.sqlite")) as conn:
        _init(conn)
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        base = {"scope_type": "QUESTION", "target_id": "Q1"}
        first = _command(conn, operation="apply_arrangement", arrangement={
            **base, "dispatch_policy": "NO_NEW_DISPATCH", "max_active_branches": 2, "ends_on_kind": "AT_TIME", "expires_at": until,
        })
        second = _command(conn, operation="apply_arrangement", arrangement={**base, "dispatch_policy": "NO_NEW_DISPATCH"})
        conn.execute("UPDATE run_arrangements SET expires_at='2000-01-01T00:00:00Z' WHERE arrangement_id=?", (first["arrangement_id"],))
        state = schedule_control_plane_snapshot(conn)["subproblem_states"]["Q1"]
        assert state["dispatch_policy"] == "NO_NEW_DISPATCH"
        assert state["max_active_branches"] == 3
        assert conn.execute("SELECT patch_json FROM run_arrangements WHERE arrangement_id=?", (first["arrangement_id"],)).fetchone()[0] == '{"max_active_branches": 2}'
        _command(conn, operation="revoke_arrangement", details={"arrangement_id": second["arrangement_id"]})
        assert schedule_control_plane_snapshot(conn)["subproblem_states"]["Q1"]["dispatch_policy"] == "NORMAL"


def test_revoking_handoff_drain_restores_the_node_and_supersedes_the_receipt(tmp_path):
    with closing(open_rw_connection(tmp_path / "gw.sqlite")) as conn:
        _init(conn)
        _node(conn, tmp_path, "N1")
        assert admit_runtime_slot(conn, "N1", "host", "first", 1)["admitted"]
        drain = _command(conn, operation="apply_arrangement", arrangement={
            "scope_type": "QUESTION", "target_id": "Q1", "dispatch_policy": "NO_NEW_DISPATCH",
            "inflight_drain_mode": "FINISH_CURRENT_HANDOFF",
        })
        assert drain["status"] == "DRAINING"
        assert schedule_control_plane_snapshot(conn)["operator_slot_ledger"]["draining"][0]["node_id"] == "N1"
        revoked = _command(conn, operation="revoke_arrangement", details={"arrangement_id": drain["arrangement_id"]})
        snap = schedule_control_plane_snapshot(conn)
        assert snap["operator_slot_ledger"]["working"][0]["control_state"] == "AUTO_RUNNING"
        receipt = next(op for op in snap["operation_receipts"] if op["op_id"] == drain["op_id"])
        assert receipt["status"] == "SUPERSEDED" and receipt["superseded_by_op_id"] == revoked["op_id"]


def test_note_receipt_settles_while_worker_is_still_running(tmp_path, monkeypatch):
    monkeypatch.setenv("GREATWALL_DATA_DIR", str(tmp_path / "data"))
    db = resolve_storage_paths(str(tmp_path))["db_path"]
    with closing(open_rw_connection(db)) as conn:
        _init(conn)
        _node(conn, tmp_path, "N1")
        assert admit_runtime_slot(conn, "N1", "host", "first", 1)["admitted"]
        result = dispatch_tool_call("chief_send_branch_note", {"node_id": "N1", "note_md": "Try the base case first."},
                                    workspace_root=str(tmp_path), caller_role="gw_chief", session_id="gw-chief",
                                    host_meta={"session_epoch_id": 1, "human_rpc_id": "rpc-1"})
        assert result["ok"] and result["data"]["status"] == "DRAINING", result
        effect = claim_runtime_effects(conn, owner_instance_id="host", kinds=["DELIVER_BRANCH_NOTE"])["claimed"][0]
        delivered = dispatch_control_call("control_plane/complete_runtime_effect", {
            "workspace_root": str(tmp_path),
            "seq": effect["seq"], "owner_instance_id": "host", "effect_key": effect["effect_key"],
            "target_generation": effect["target_generation"], "claim_attempt": effect["attempts"],
        })
        assert delivered["ok"], delivered
        snap = schedule_control_plane_snapshot(conn)
        assert snap["operation_receipts"][0]["status"] == "SETTLED"
        assert snap["operator_slot_ledger"]["working"][0]["node_id"] == "N1"


def test_handback_can_be_redeemed_once_and_untrusted_meta_does_not_grant_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("GREATWALL_DATA_DIR", str(tmp_path / "data"))
    path = resolve_storage_paths(str(tmp_path))["db_path"]
    with closing(open_rw_connection(path)) as conn:
        _init(conn)
        _node(conn, tmp_path, "N1")
        handback = tool_handback_to_chief(
            conn, "explorer", "gw-exp-N1", "N1", "Q1", "please pause Q1", "operator scope",
            human_rpc_id="rpc-1", human_message="please pause Q1",
        )["data"]["handback_id"]
        args = {"operation": "apply_arrangement", "arrangement": {
            "scope_type": "QUESTION", "target_id": "Q1", "dispatch_policy": "NO_NEW_DISPATCH",
        }}
        denied = dispatch_tool_call("chief_operate", {**args, "_meta": {"human_rpc_id": "model"}},
                                    workspace_root=str(tmp_path), caller_role="gw_chief", session_id="gw-chief", host_meta={})
        assert denied["error_code"] == "ERR_AUTH"
        trusted = dict(workspace_root=str(tmp_path), caller_role="gw_chief", session_id="gw-chief", host_meta={"session_epoch_id": 1})
        applied = dispatch_tool_call("chief_operate", {**args, "handback_id": handback}, **trusted)
        assert applied["ok"], applied
        again = dispatch_tool_call("chief_operate", {**args, "handback_id": handback}, **trusted)
        assert again["error_code"] == "ERR_AUTH"
        assert conn.execute("SELECT status FROM handback_records").fetchone()[0] == "EXECUTED"


def test_epoch_advance_archives_before_reset_and_fences_old_session(tmp_path, monkeypatch):
    monkeypatch.setenv("GREATWALL_DATA_DIR", str(tmp_path / "data"))
    path = resolve_storage_paths(str(tmp_path))["db_path"]
    with closing(open_rw_connection(path)) as conn:
        _init(conn)
        _node(conn, tmp_path, "N1")
        conn.execute("UPDATE subproblem_runtime_state SET spent_tokens=44000 WHERE question_id='Q1'")
        _command(conn, operation="apply_arrangement", arrangement={
            "scope_type": "QUESTION", "target_id": "Q1", "priority_weight": 400,
        })
        proposal = create_control_proposal(
            conn, proposed_by="gw_chief", action_type="ADVANCE_EPOCH", target_id="ALL",
            payload={"expected_epoch_id": 1, "new_contract": {"subquestions": ["Q3"]}},
            rationale_md="新课题设置已获研究者签署。",
        )
        result = approve_control_proposal(conn, workspace_root=str(tmp_path), proposal_id=proposal["proposal_id"])
        archived = Path(result["execution"]["archive_path"])
        assert archived.is_file()
        with closing(open_ro_connection(archived)) as prior:
            assert prior.execute("SELECT spent_tokens FROM subproblem_runtime_state WHERE question_id='Q1'").fetchone()[0] == 44000
            assert prior.execute("SELECT node_id FROM lineage_nodes").fetchone()[0] == "N1"
            assert prior.execute("SELECT COUNT(*) FROM run_arrangements").fetchone()[0] == 1
        active = schedule_control_plane_snapshot(conn)
        assert active["epoch_id"] == 2 and active["required_questions"] == ["Q3"]
        assert active["stage"] == "STAGE1_PARSE0" and not active["active_arrangements"]
        _node(conn, tmp_path, "N2", "Q3")
        assert conn.execute("SELECT session_epoch_id FROM lineage_nodes").fetchone()[0] == 2
        stale = dispatch_tool_call("chief_operate", {"operation": "recover_queue"}, workspace_root=str(tmp_path),
                                   caller_role="gw_chief", host_meta={"session_epoch_id": 1, "human_rpc_id": "rpc-1"})
        assert stale["error_code"] == "ERR_STALE_EPOCH"
        read = dispatch_tool_call("chief_read", {"resource": "archive/1/node/N1/manuscript"},
                                  workspace_root=str(tmp_path), caller_role="gw_chief", host_meta={"session_epoch_id": 1})
        assert read["ok"], read


def test_operator_migration_preserves_existing_rows_foreign_keys_and_handoff_trigger(tmp_path):
    import sqlite3
    from core_python.mcp_server.db.schema_base import BASE_SCHEMA_SQL
    from core_python.mcp_server.db.schema_v03 import V03_SCHEMA_SQL, SEALED_HANDOFF_TRIGGER_SQL

    db = tmp_path / "legacy.sqlite"
    base_before = BASE_SCHEMA_SQL.replace(",'RETIRED'", "").replace(",'ARCHIVED'", "")
    v03_before = (V03_SCHEMA_SQL.replace(", 'ADVANCE_EPOCH'", "")
                  .replace(", 'ADVISOR_NOTE_SENT', 'NODE_HIBERNATED', 'NODE_RETIRED', 'NODE_REACTIVATED'", "")
                  .replace(", 'chief_direct'", "").replace(", 'DELIVER_BRANCH_NOTE', 'DELIVER_HANDBACK_RECEIPT'", ""))
    with closing(sqlite3.connect(db, isolation_level=None)) as raw:
        raw.row_factory = sqlite3.Row
        raw.executescript(base_before + v03_before + SEALED_HANDOFF_TRIGGER_SQL)
        _init(raw)
        _node(raw, tmp_path, "N1")
        raw.execute("UPDATE lineage_nodes SET briefing_sealed_at='yesterday', node_status='SEALED' WHERE node_id='N1'")
        raw.execute(
            """INSERT INTO node_interventions(intervention_id,node_id,question_id,action,actor_source,created_at)
               VALUES('old','N1','Q1','PAUSE_REQUESTED','human_ui','yesterday')"""
        )
    with closing(open_rw_connection(db, force_init=True)) as upgraded:
        assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
        assert upgraded.execute("SELECT node_id FROM node_interventions").fetchone()[0] == "N1"
        assert upgraded.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name='trg_nodes_lock_sealed_handoff'").fetchone()[0] == 1
        assert upgraded.execute("SELECT max_active_branches FROM subproblem_runtime_state WHERE question_id='Q1'").fetchone()[0] == 3


def test_named_seed_keeps_full_blueprint_and_single_use_bypass(tmp_path, monkeypatch):
    monkeypatch.setenv("GREATWALL_DATA_DIR", str(tmp_path / "data"))
    database = resolve_storage_paths(str(tmp_path))["db_path"]
    with closing(open_rw_connection(database)) as conn:
        _init(conn)
        _node(conn, tmp_path, "busy", "Q2")
        assert admit_runtime_slot(conn, "busy", "host", "ordinary", 1, slot_cap=1)["admitted"]
        _command(conn, operation="apply_arrangement", arrangement={
            "scope_type": "QUESTION", "target_id": "Q1", "dispatch_policy": "NO_NEW_DISPATCH",
        })
        markdown = "## 推导\n" + "按递推关系验证十二个边界条件。\n" * 200
        seed = dispatch_tool_call("chief_seed_branch", {"question_id": "Q1", "family_signature": "按递推式展开",
            "blueprint_md": markdown, "orthogonal_contrast": "与生成函数路径互补"}, workspace_root=str(tmp_path),
            caller_role="gw_chief", session_id="gw-chief", host_meta={"session_epoch_id": 1, "human_rpc_id": "rpc-1"})
        assert seed["ok"], seed
        node = seed["data"]["node_id"]
        worktree = Path(seed["data"]["worktree_abs_path"])
        assert (worktree / "inputs" / "human_seed_blueprint.md").read_text(encoding="utf-8").strip() == markdown.strip()
        assert (worktree / ".git" / "HEAD").is_file()
        ready = schedule_control_plane_snapshot(conn, max_concurrent_workers=1)["explorers_ready_to_run"]
        assert [(n["node_id"], n["slot_tier"]) for n in ready] == [(node, "human_reserve")]
        assert admit_runtime_slot(conn, node, "host", "first", 1, slot_tier="human_reserve", slot_cap=1)["admitted"]
        assert release_runtime_slot(conn, node, "host", "first")["released"]
        assert not admit_runtime_slot(conn, node, "host", "again", 1)["admitted"]
        _command(conn, operation="node_intervene", node_action={"node_ids": [node], "mode": "retire", "archive_family": True})
        family = seed["data"]["family_id"]
        assert conn.execute("SELECT family_status FROM method_families WHERE family_id=?", (family,)).fetchone()[0] == "ARCHIVED"
        revived = _command(conn, operation="node_intervene", node_action={"node_ids": [node], "mode": "reactivate"})
        assert revived["status"] == "SETTLED"
        assert conn.execute("SELECT family_status FROM method_families WHERE family_id=?", (family,)).fetchone()[0] == "ACTIVE"


def test_retiring_waits_for_host_completion_even_after_worker_exit(tmp_path):
    from core_python.mcp_server.control_plane.operator_ops import _expire_and_settle
    from core_python.mcp_server.db_schema import rw_immediate_tx

    with closing(open_rw_connection(tmp_path / "gw.sqlite")) as conn:
        _init(conn)
        _node(conn, tmp_path, "N1")
        _node(conn, tmp_path, "N2", "Q2")
        assert admit_runtime_slot(conn, "N1", "host", "first", 1, slot_cap=1)["admitted"]
        operation = _command(conn, operation="node_intervene", node_action={"node_ids": ["N1"], "mode": "retire"})
        assert operation["status"] == "DRAINING"
        assert release_runtime_slot(conn, "N1", "host", "first")["pending_quiescence"]
        assert not admit_runtime_slot(conn, "N2", "host", "second", 1, slot_cap=1)["admitted"]
        claim = claim_runtime_effects(conn, owner_instance_id="host")["claimed"][0]
        stale = complete_runtime_effect(conn, seq=claim["seq"], owner_instance_id="host", effect_key=claim["effect_key"],
                                        target_generation=claim["target_generation"], claim_attempt=claim["attempts"] - 1)
        assert not stale["updated"]
        complete_runtime_effect(conn, seq=claim["seq"], owner_instance_id="host", effect_key=claim["effect_key"],
                                target_generation=claim["target_generation"], claim_attempt=claim["attempts"])
        with rw_immediate_tx(conn):
            _expire_and_settle(conn)
        assert admit_runtime_slot(conn, "N2", "host", "second", 1, slot_cap=1)["admitted"]
        assert schedule_control_plane_snapshot(conn)["operation_receipts"][0]["status"] == "SETTLED"


def test_mcp_schema_docs_preserves_v031_chief_enums_and_uninitialized_snapshot():
    from core_python.mcp_server.control_plane.scheduler_rules import uninitialized_schedule_snapshot
    from core_python.mcp_server.mcp_schema_docs import enrich_tool_definitions
    from core_python.mcp_server.tool_registry import TOOL_DEFINITIONS

    chief_tools = {t["name"]: t for t in enrich_tool_definitions(TOOL_DEFINITIONS)}
    preview_enum = chief_tools["chief_preview_impact"]["inputSchema"]["properties"]["preview_kind"]["enum"]
    assert "run_arrangement" in preview_enum
    propose_enum = chief_tools["chief_propose_control_action"]["inputSchema"]["properties"]["action_type"]["enum"]
    assert propose_enum == ["AMEND_RULING_DRAFT", "AUTHORIZE_PARTIAL_DELIVERY", "ADVANCE_EPOCH", "APPROVE_WAVE_VERDICT"]
    assert "archive/<epoch_id>" in chief_tools["chief_read"]["inputSchema"]["properties"]["resource"]["description"]

    uninit = uninitialized_schedule_snapshot()
    assert uninit["epoch_id"] == 1
    assert uninit["operator_plane"] is False
    assert uninit["max_worker_slots"] >= 1
    assert set(uninit["operator_slot_ledger"].keys()) == {"working", "draining", "hibernated_or_human"}


def test_works_ticket_flood_guards_cancel_and_chief_request_survey():
    import json
    import tempfile
    from core_python.mcp_server.control_plane.lifecycle_ops import submit_works_ticket
    from core_python.mcp_server.db_schema import FailClosedError

    with tempfile.TemporaryDirectory() as tmp:
        with closing(open_rw_connection(Path(tmp) / "gw.sqlite")) as conn:
            _init(conn)
            # 1) 同键 OPEN 工单幂等合并，不刷出多行
            t1 = submit_works_ticket(conn, question_id="Q1", ticket_type="PAIN_POINT", instrument_id="geo_kernel",
                                     description="首次反馈缺少凸包精度护栏", source="role:explorer", reporter_session_id="exp-1")
            t2 = submit_works_ticket(conn, question_id="Q1", ticket_type="PAIN_POINT", instrument_id="geo_kernel",
                                     description="第二分支重复反馈", source="role:explorer", reporter_session_id="exp-2")
            assert t1["ticket_id"] == t2["ticket_id"] and t2["deduplicated"] is True and t2["report_count"] == 2

            # 2) 单非特权会话最多同时 2 张在途 OPEN 工单；结案后自动释放额度
            submit_works_ticket(conn, question_id="Q2", ticket_type="PAIN_POINT", instrument_id="tool_b",
                                description="第二张不同工单", source="role:explorer", reporter_session_id="exp-1")
            try:
                submit_works_ticket(conn, question_id="Q2", ticket_type="DUPLICATE_TOOL", instrument_id="tool_c",
                                    description="第三张在途单应提示耐心等待", source="role:explorer", reporter_session_id="exp-1")
                raise AssertionError("应触发在途 2 张背压提示")
            except FailClosedError as exc:
                assert "正在由工造司处理中" in str(exc)

            # 3) chief_operate 撤单 cancel_ticket 释放名额，随后 exp-1 可正常再开新单；并验证直派外藏 request_survey
            cancelled = _command(conn, operation="cancel_ticket", details={"ticket_id": t1["ticket_id"], "reason": "误派撤回"})
            assert cancelled["status"] == "SETTLED"
            assert conn.execute("SELECT status FROM works_engineering_queue WHERE ticket_id=?", (t1["ticket_id"],)).fetchone()[0] == "RESOLVED"
            t3 = submit_works_ticket(conn, question_id="Q2", ticket_type="DUPLICATE_TOOL", instrument_id="tool_c",
                                     description="旧单结案释放名额后可正常提交", source="role:explorer", reporter_session_id="exp-1")
            assert t3["status"] == "OPEN" and t3["deduplicated"] is False

            srv = _command(conn, operation="request_survey", details={"question_id": "Q3", "topic_query": "CPP 覆盖路径规划综述全文", "reason": "补充 Q3 外藏全文"})
            assert srv["status"] == "SETTLED" and srv["req_id"].startswith("srv_")
            row = conn.execute("SELECT node_id, status FROM survey_requests WHERE req_id=?", (srv["req_id"],)).fetchone()
            assert row["node_id"] == "gw_chief" and row["status"] == "PENDING"

            # 4) chief_operate 人工主动召开圆桌 open_wave_conference + 防并发重开保护
            wc = _command(conn, operation="open_wave_conference", details={"question_id": "Q1", "reason": "人类要求提前收束并刷新综述"})
            assert wc["status"] == "SETTLED" and wc["conference_id"].startswith("wc_q1_w")
            try:
                _command(conn, operation="open_wave_conference", details={"question_id": "Q1"})
                raise AssertionError("同子题已有进行中圆桌时应拒绝重复召开")
            except FailClosedError as exc:
                assert "已有进行中的圆桌" in str(exc)


def test_round3_five_fixes_regression():
    """回归覆盖第三轮实测 5 项流程修复：交班引理Schema/报错、圆桌动作传参、后勤满额不催开枝、总控early_handoff授权、工单合并保留全文。"""
    import json
    import tempfile
    from core_python.mcp_server.control_plane.lifecycle_ops import submit_works_ticket
    from core_python.mcp_server.control_plane.wave_engine import execute_approved_wave_verdict
    from core_python.mcp_server.db_schema import FailClosedError
    from core_python.mcp_server.mcp_schema_docs import enrich_tool_definitions
    from core_python.mcp_server.tool_registry import TOOL_DEFINITIONS
    from core_python.mcp_server.tools_logistics import tool_get_logistics_dashboard

    tools_map = {t["name"]: t for t in enrich_tool_definitions(TOOL_DEFINITIONS)}
    # 1) Schema 同时保留旧投稿入口和新版圆桌的专属字段
    lemma_schema = tools_map["submit_node_handoff"]["inputSchema"]["properties"]["local_lemma_submissions"]
    assert "column_a_self_contained_proof_md" in lemma_schema["items"]["properties"]
    assert set(lemma_schema["items"]["required"]) == {"title", "column_a_self_contained_proof_md"}
    verdict_act_props = tools_map["submit_conference_verdict"]["inputSchema"]["properties"]["actions"]["items"]["properties"]
    for key in ("action_type", "synthesis_goal_md", "probe_requirement_md", "primary_node_id", "secondary_node_id"):
        assert key in verdict_act_props

    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        with closing(open_rw_connection(Path(tmp) / "gw.sqlite")) as conn:
            _init(conn)
            # 创建 Q1 下 3 条同 fam1 活跃分支（达到默认 max_active_branches=3 上限）
            for idx in range(1, 4):
                wt = ws / "worktrees" / f"b{idx}"
                wt.mkdir(parents=True, exist_ok=True)
                (wt / "candidate.py").write_text(f"x = {idx}\n", encoding="utf-8")
                conn.execute(
                    """INSERT INTO lineage_nodes(
                        node_id, question_id, branch_id, family_id, generation,
                        node_status, worktree_abs_path, created_at, updated_at
                    ) VALUES (?,?,?,?,1,'EXPLORING',?,?,?)""",
                    (f"n_q1_{idx}", "Q1", f"b{idx}", "fam1", str(wt), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                )
            conn.commit()

            # 3) 后勤仪表盘：Q1 已满 3/3，聚拢告警标 can_fork_now=False，且引导不再催开枝
            dash = tool_get_logistics_dashboard(conn, caller_role="logistics_coordinator", session_id="log-1", question_id="Q1")
            dash_data = dash["data"]
            q1_state = [s for s in dash_data["subproblem_states"] if s["question_id"] == "Q1"][0]
            assert q1_state["max_active_branches"] == 3
            assert q1_state["active_branch_count"] == 3
            assert q1_state["available_branch_slots"] == 0
            assert q1_state["can_open_new_branch"] is False
            assert dash_data["family_concentration_alerts"][0]["can_fork_now"] is False
            assert "名额已满" in dash["next_step_guidance"]

            # 4) 总控下令提前交班：actor_source="gw_chief_human" -> chief_direct 授权直通，不再被 authorize_early_handoff 误拒
            eh = operator_command(
                conn,
                operation="node_intervene",
                actor_source="gw_chief_human",
                node_action={"node_ids": ["n_q1_1"], "mode": "early_handoff", "reason": "人类通过总控下令提前交班"},
            )
            assert eh["status"] == "SETTLED" and not eh.get("failed_targets")
            assert conn.execute("SELECT control_state FROM lineage_nodes WHERE node_id='n_q1_1'").fetchone()[0] == "EARLY_HANDOFF_READY"

            # 5) 工单合并：1137 字报修正文完整保留，绝不截断为 400 字
            long_desc = "故障复现步骤：" + ("A" * 1130)
            assert len(long_desc) == 1137
            t1 = submit_works_ticket(conn, question_id="Q1", ticket_type="INSTRUMENT_ERROR", instrument_id="inst_geo",
                                     description="初次简短报错", source="role:explorer", reporter_session_id="exp-1")
            t2 = submit_works_ticket(conn, question_id="Q1", ticket_type="INSTRUMENT_ERROR", instrument_id="inst_geo",
                                     description=long_desc, source="role:explorer", reporter_session_id="exp-2")
            assert t1["ticket_id"] == t2["ticket_id"] and t2["deduplicated"] is True
            raw_payload = json.loads(
                conn.execute("SELECT payload_json FROM works_engineering_queue WHERE ticket_id=?", (t1["ticket_id"],)).fetchone()[0]
            )
            assert len(raw_payload["additional_reports"][0]["description"]) == 1137
            assert raw_payload["additional_reports"][0]["description"] == long_desc

            # 2) 验证两个动作按各自的专属字段透传，并使用两条不同学派的供体。
            conn.execute("UPDATE lineage_nodes SET node_status='SEALED' WHERE node_id='n_q1_3'")
            conn.execute("UPDATE lineage_nodes SET family_id='fam2' WHERE node_id='n_q1_2'")
            conn.execute(
                """
                INSERT INTO method_families(family_id, question_id, mechanism_signature, orthogonal_contrast, created_at)
                VALUES ('fam_synthesis', 'Q1', '连续优化融合边界剪枝', '互补供体', '2026-01-01T00:00:00Z')
                """
            )
            verdict_obj = {
                "actions": [
                    {
                        "action_type": "SPAWN_SYNTHESIS",
                        "primary_node_id": "n_q1_1",
                        "secondary_node_id": "n_q1_2",
                        "target_family_id": "fam_synthesis",
                        "synthesis_goal_md": "将 n_q1_1 的连续优化与 n_q1_2 的边界剪枝融合并验证误差 < 1e-6",
                    },
                    {
                        "action_type": "DISCRIMINATOR",
                        "instrument_id": "inst_geo",
                        "probe_requirement_md": "编写双曲线边界对拍探针，区分两派在高曲率拐点处的误差来源",
                    },
                ],
                "rationale_md": "测试圆桌动作具体任务透传",
            }
            conn.execute(
                """INSERT INTO wave_conferences(
                    conference_id, question_id, wave_no, status, participant_nodes_json, verdict_json, created_at
                ) VALUES ('wc_q1_w9_test', 'Q1', 9, 'ADJUDICATING', '["n_q1_1","n_q1_2"]', ?, '2026-01-01T00:00:00Z')""",
                (json.dumps(verdict_obj, ensure_ascii=False),),
            )
            conn.commit()
            res = execute_approved_wave_verdict(conn, workspace_root=str(ws), conference_id="wc_q1_w9_test")
            syn_act = [x for x in res["executed"] if x["action"] == "SPAWN_SYNTHESIS"][0]
            disc_act = [x for x in res["executed"] if x["action"] == "DISCRIMINATOR"][0]
            syn_will = conn.execute("SELECT will_md FROM lineage_nodes WHERE node_id=?", (syn_act["node_id"],)).fetchone()[0]
            assert "误差 < 1e-6" in syn_will and "旁路双供体融合验证" not in syn_will
            disc_payload = json.loads(
                conn.execute("SELECT payload_json FROM works_engineering_queue WHERE ticket_id=?", (disc_act["ticket_id"],)).fetchone()[0]
            )
            assert "高曲率拐点" in disc_payload["description"]
