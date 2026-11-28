"""GreatWall v0.3 lineage_companion（一对一分身伴随助手）4 个阶段工具。

v0.3 核心升级：
- `get_companion_context` 支持 `CONFERENCE_PARTICIPANT` 封存参会态，且 `PRE_SPAWN` 附带双供体只读路径与子题生效口径；
- `submit_node_handoff` 落盘 `briefing_sealed_at` 激活数据库不可逆封存触发器；
- 裁决 2：支持可选 `local_lemma_submissions` 挂冻结快照独立拆交一次性盲审（绝不锁死原分支），以及 `recommended_triage` 确定性控制面直落；
- 自动递增波次进度并触发 `check_and_open_wave_conference` 与 `evaluate_subproblem_locks`。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..evaluators.isolated_runner import sha256_file
from .db.enums import ALLOWED_HOLIDAY_OUTCOMES
from .control_plane_service import (
    backup_retained_candidate_snapshot,
    check_and_open_wave_conference,
    evaluate_subproblem_locks,
    extract_sanitized_code_diff_md,
    get_subproblem_active_spec_revision,
    safe_resolve_in_worktree,
)
from .db_schema import (
    ALLOWED_COMPANION_MODES,
    ALLOWED_DEAD_END_CATEGORIES,
    ALLOWED_EVIDENCE_GRADES,
    ALLOWED_VERDICT_3STATE,
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
    load_meta_reflection_categories,
    load_runtime_config,
    next_prefixed_id,
    record_fact_edge,
    resolve_effective_context_window,
)
from .triage_core import evaluate_auto_triage_eligibility, execute_triage_core
from .control_plane.wave_verdict_actions import enqueue_salvage_review


def tool_get_companion_context(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    branch_id: str,
    node_id: str,
    mode: str,
) -> dict[str, Any]:
    """按阶段严格隔离返回伴随上下文：PRE_SPAWN / REFLECT_37 / HANDOFF_70 / CRASH_RECOVERY / CONFERENCE_PARTICIPANT。"""
    enforce_role_tool_permission(conn, caller_role, "get_companion_context", session_id=session_id, node_id=node_id)
    mode_u = str(mode or "").strip().upper()
    if mode_u not in ALLOWED_COMPANION_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法伴随模式 {mode!r}，仅限 {sorted(ALLOWED_COMPANION_MODES)}")

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")

    qid = str(node["question_id"])
    active_spec_rev = get_subproblem_active_spec_revision(conn, qid)

    if mode_u == "CONFERENCE_PARTICIPANT":
        if not str(node["briefing_sealed_at"] or "").strip():
            raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 尚未完成 70% 封存，禁止进入圆桌参会态")
        conf = conn.execute(
            """
            SELECT conference_id, question_id, wave_no, status, critiques_ledger_json, agenda_json, created_at
            FROM wave_conferences
            WHERE question_id = ? AND status IN ('ROUND_1_CRITIQUE', 'ROUND_2_REBUTTAL', 'SURVEY_REFRESHING')
            ORDER BY wave_no DESC LIMIT 1
            """,
            (qid,),
        ).fetchone()
        return build_tool_receipt(
            conn=conn,
            tool_name="get_companion_context",
            question_id=qid,
            node_id=node_id,
            next_step_guidance="你当前处于已封存圆桌参会态（零档案写权），请基于本脉代码事实与硬账本调用 submit_conference_statement 发言。",
            data={
                "mode": "CONFERENCE_PARTICIPANT",
                "node_id": node_id,
                "branch_id": branch_id,
                "question_id": qid,
                "briefing_sealed_at": str(node["briefing_sealed_at"]),
                "mechanism_summary": str(node["mechanism_summary"] or ""),
                "column_a_facts_md": str(node["column_a_facts_md"] or ""),
                "bound_obs_ids": json.loads(node["bound_obs_ids_json"] or "[]"),
                "active_conference": (
                    {
                        "conference_id": str(conf["conference_id"]),
                        "wave_no": int(conf["wave_no"]),
                        "status": str(conf["status"]),
                        "critiques_ledger": json.loads(conf["critiques_ledger_json"]),
                        "agenda": json.loads(conf["agenda_json"]),
                    }
                    if conf
                    else None
                ),
            },
        )

    prev_briefing = conn.execute(
        "SELECT * FROM lineage_briefings WHERE branch_id = ? ORDER BY created_at DESC LIMIT 1",
        (branch_id,),
    ).fetchone()
    parent_node = (
        conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node["parent_node_id"],)).fetchone()
        if node["parent_node_id"]
        else None
    )
    dead_ends_total = int(
        conn.execute("SELECT COUNT(*) AS cnt FROM lineage_dead_ends WHERE branch_id = ?", (branch_id,)).fetchone()["cnt"] or 0
    )

    if mode_u == "PRE_SPAWN":
        active_instruments = [
            {
                "instrument_id": str(r["instrument_id"]),
                "version": int(r["version"]),
                "question_id": str(r["question_id"]),
                "instrument_role": str(r["instrument_role"]),
                "artifact_schema": str(r["artifact_schema"] or "python_run"),
                "health_status": str(r["health_status"]),
            }
            for r in conn.execute(
                """
                SELECT instrument_id, version, question_id, instrument_role, artifact_schema, health_status
                FROM instruments
                WHERE is_active = 1 AND health_status = 'HEALTHY' AND (question_id = ? OR question_id = 'ALL')
                ORDER BY instrument_id, version
                """,
                (qid,),
            ).fetchall()
        ]
        # 仅返回最新《子题全局总览》版本号元数据，严禁在 0% PRE_SPAWN 泄露内藏正文
        sv_row = conn.execute(
            "SELECT revision FROM subproblem_living_surveys WHERE question_id = ? ORDER BY revision DESC LIMIT 1",
            (qid,),
        ).fetchone()
        donors_dir = Path(str(node["worktree_abs_path"])) / ".greatwall_donors"
        donor_mounts = sorted(p.name for p in donors_dir.iterdir() if p.is_dir()) if donors_dir.is_dir() else []

        wave = conn.execute(
            """
            SELECT c.conference_id, c.minutes_md, c.peer_takeaways_json, s.*
            FROM wave_conferences c LEFT JOIN subproblem_living_surveys s ON s.survey_id = c.linked_survey_id
            WHERE c.question_id = ? AND c.status = 'COMPLETED' ORDER BY c.wave_no DESC LIMIT 1
            """,
            (qid,),
        ).fetchone()
        wave_takeaways = None
        if wave is not None:
            packed = json.loads(wave["peer_takeaways_json"])
            wave_takeaways = {
                "conference_id": wave["conference_id"], "minutes_md": wave["minutes_md"],
                "peer_takeaways": packed.get(branch_id, []),
                "living_survey": {key: wave[key] for key in wave.keys() if key.startswith("sec") or key == "marginal_notes_md"},
            }
        feedback = [
            item for ancestor in (parent_node, node) if ancestor is not None
            for item in json.loads(ancestor["pending_review_feedback_json"])
        ]
        reports = [dict(row) for row in conn.execute(
            """
            SELECT r.survey_req_id, r.question_id, r.report_md, r.cited_entry_ids_json, r.cited_obs_ids_json
            FROM internal_survey_requests r JOIN lineage_nodes n ON n.node_id = r.requester_node_id
            WHERE n.branch_id = ? AND r.status = 'FULFILLED'
            ORDER BY r.fulfilled_at DESC LIMIT 2
            """,
            (branch_id,),
        )]

        payload: dict[str, Any] = {
            "mode": "PRE_SPAWN",
            "node_id": node_id,
            "branch_id": branch_id,
            "question_id": qid,
            "generation": int(node["generation"]),
            "branch_kind": str(node["branch_kind"] or "PURE"),
            "active_spec_revision": active_spec_rev,
            "node_status": str(node["node_status"]),
            "donor_mount_dirs": donor_mounts,
            "latest_wave_takeaways": wave_takeaways,
            "pending_review_feedback": feedback,
            "internal_survey_reports": reports,
            "latest_living_survey_revision": int(sv_row["revision"]) if sv_row else 0,
            "active_instruments": active_instruments,
            "previous_briefing": dict(prev_briefing) if prev_briefing else None,
            "latest_parent_handoff": (
                {
                    "node_id": str(parent_node["node_id"]),
                    "mechanism_summary": str(parent_node["mechanism_summary"] or ""),
                    "evidence_grade": str(parent_node["evidence_grade"]),
                    "column_a_facts_md": str(parent_node["column_a_facts_md"] or ""),
                    "will_md": str(parent_node["will_md"] or ""),
                }
                if parent_node
                else None
            ),
            "active_revision_requests": json.loads(node["last_revision_requests_json"] or "[]"),
            "retained_snapshot_abs_path": node["retained_snapshot_abs_path"],
            "lineage_dead_ends_count": dead_ends_total,
        }
        return build_tool_receipt(
            conn=conn,
            tool_name="get_companion_context",
            question_id=qid,
            node_id=node_id,
            next_step_guidance="请执行定额滚动重写 Rewrite_<=5000(旧看板, 上代最新手记) 并调 save_lineage_briefing（总长 <= 5000 字，段 5 整体替换最新遗嘱）。",
            data=payload,
        )

    if mode_u == "REFLECT_37":
        cfg = load_runtime_config()
        win = resolve_effective_context_window(conn, node_window=node["effective_context_window"], cfg=cfg)
        reflect_pct = float(cfg.get("context_reflect_hint_pct", 0.37))
        cur_tokens = int(node["pressure_tokens"] or 0)
        if cur_tokens / float(win) < reflect_pct:
            raise FailClosedError(
                ERR_LOCKED,
                f"当前上下文水位 {cur_tokens}/{win} ({cur_tokens / win:.1%}) 未达到 {reflect_pct:.0%} 阈值，严禁提前拉取 REFLECT_37 专属馆藏目录与死胡同摘要！",
            )

        dead_ends_summary = [
            {
                "dead_end_id": str(r["dead_end_id"]),
                "category": str(r["category"]),
                "scope_condition_md": str(r["scope_condition_md"])[:200],
                "failure_mechanism_md": str(r["failure_mechanism_md"])[:240],
            }
            for r in conn.execute(
                "SELECT dead_end_id, category, scope_condition_md, failure_mechanism_md FROM lineage_dead_ends WHERE branch_id = ? ORDER BY created_at DESC LIMIT 12",
                (branch_id,),
            ).fetchall()
        ]
        library_catalog_preview = [
            {
                "entry_id": str(r["entry_id"]),
                "ledger_type": str(r["ledger_type"]),
                "l3_entry_kind": r["l3_entry_kind"],
                "l2_category": r["l2_category"],
                "title": str(r["title"]),
                "abstract_preview": str(r["abstract_md"])[:240],
            }
            for r in conn.execute(
                """
                SELECT entry_id, ledger_type, l3_entry_kind, l2_category, title, abstract_md
                FROM internal_research_ledger
                WHERE is_active = 1 AND question_id = ?
                ORDER BY created_at DESC LIMIT 20
                """,
                (qid,),
            ).fetchall()
        ]
        obs_rows = [
            {
                "obs_id": str(r["obs_id"]),
                "instrument_id": str(r["instrument_id"]),
                "instrument_version": int(r["instrument_version"]),
                "obs_status": str(r["obs_status"]),
                "tracks": json.loads(r["tracks_json"] or "{}"),
            }
            for r in conn.execute(
                "SELECT obs_id, instrument_id, instrument_version, obs_status, tracks_json FROM observations WHERE node_id = ? ORDER BY created_at ASC",
                (node_id,),
            ).fetchall()
        ]

        return build_tool_receipt(
            conn=conn,
            tool_name="get_companion_context",
            question_id=qid,
            node_id=node_id,
            next_step_guidance="请切换外部严苛专家视角（临床诊断师 + 情报员），从 C01–C11 对症选 1–2 类，给盲区诊断与最多 2 条相关证据编号，完成不超过两轮后调 record_reflection_and_unlock_pull。",
            data={
                "mode": "REFLECT_37",
                "node_id": node_id,
                "branch_id": branch_id,
                "question_id": qid,
                "pressure_tokens": int(node["pressure_tokens"] or 0),
                "observations": obs_rows,
                "lineage_dead_ends_summary": dead_ends_summary,
                "central_library_l3_l2_catalog_preview": library_catalog_preview,
                "meta_reflection_categories": load_meta_reflection_categories(),
            },
        )

    # HANDOFF_70 / CRASH_RECOVERY
    obs_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT obs_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text, created_at FROM observations WHERE node_id = ? ORDER BY created_at ASC",
            (node_id,),
        ).fetchall()
    ]
    probes = [
        dict(r)
        for r in conn.execute(
            "SELECT probe_id, instrument_id, status, tracks_json, details_text, created_at FROM probe_diagnostic_logs WHERE node_id = ? ORDER BY created_at DESC LIMIT 15",
            (node_id,),
        ).fetchall()
    ]
    return build_tool_receipt(
        conn=conn,
        tool_name="get_companion_context",
        question_id=qid,
        node_id=node_id,
        next_step_guidance=(
            "请对照探索者亲笔遗嘱、Worktree Diff 与客观 [Obs###] 写 <=5000 字 A/B 双栏手记与 <100 字纯 mechanism_summary；"
            "可附带 recommended_triage 加速常规直落，或对独立局部引理附带 local_lemma_submissions 拆交一次性盲审，调用 submit_node_handoff 落库封存。"
        ),
        data={
            "mode": mode_u,
            "node_id": node_id,
            "holiday_bet": json.loads(node["holiday_bet_json"]),
            "branch_id": branch_id,
            "question_id": qid,
            "family_id": node["family_id"],
            "inplace_repair_count": int(node["inplace_repair_count"] or 0),
            "worktree_abs_path": str(node["worktree_abs_path"]),
            "retained_snapshot_abs_path": node["retained_snapshot_abs_path"],
            "explorer_will_md": str(node["will_md"] or node["explorer_will_md"] or ""),
            "pending_handoff_mode": node["pending_handoff_mode"],
            "pending_handoff_reason": str(node["pending_handoff_reason"] or ""),
            "observations": obs_rows,
            "probe_diagnostic_logs": probes,
            "reflections": json.loads(node["reflections_json"] or "[]"),
        },
    )


def tool_save_lineage_briefing(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    branch_id: str,
    node_id: str,
    sec1_mechanism: str,
    sec2_verified_baseline: str,
    sec3_bottleneck: str,
    sec4_dead_ends: str,
    sec5_immediate_will: str,
) -> dict[str, Any]:
    """定额滚动重压缩看板：唯一硬限制为五段非空且总长 <= 5000 字。"""
    enforce_role_tool_permission(conn, caller_role, "save_lineage_briefing", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, branch_id, briefing_sealed_at FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")
    if str(node["briefing_sealed_at"] or "").strip():
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 已封存，严禁再写行前看板")

    sections = {
        "sec1_mechanism": str(sec1_mechanism or "").strip(),
        "sec2_verified_baseline": str(sec2_verified_baseline or "").strip(),
        "sec3_bottleneck": str(sec3_bottleneck or "").strip(),
        "sec4_dead_ends": str(sec4_dead_ends or "").strip(),
        "sec5_immediate_will": str(sec5_immediate_will or "").strip(),
    }
    for name, text in sections.items():
        if not text or len(text) < 2:
            raise FailClosedError(ERR_INVALID_INPUT, f"看板段落 {name!r} 不可为空或仅标点占位")

    cfg = load_runtime_config()
    max_total = int(cfg.get("max_briefing_chars", 5000))
    total_chars = sum(len(v) for v in sections.values())
    if total_chars > max_total:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"定额滚动重写看板总字数超限：{total_chars} > {max_total} 字！严禁静默切片，请精简后重写。",
        )

    bid = f"brf_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO lineage_briefings(
                briefing_id, branch_id, node_id,
                sec1_mechanism, sec2_verified_baseline, sec3_bottleneck, sec4_dead_ends, sec5_immediate_will,
                total_chars, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bid,
                branch_id,
                node_id,
                sections["sec1_mechanism"],
                sections["sec2_verified_baseline"],
                sections["sec3_bottleneck"],
                sections["sec4_dead_ends"],
                sections["sec5_immediate_will"],
                total_chars,
                now,
            ),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="save_lineage_briefing",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance=f"看板 {bid} 已落库（总长 {total_chars}/{max_total} 字），伴随暂停挂起，探索者现已就绪启动。",
        data={"briefing_id": bid, "total_chars": total_chars, "max_briefing_chars": max_total},
    )


def tool_record_reflection_and_unlock_pull(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    selected_categories: list[str],
    turns: list[dict[str, Any]],
    verdict_3state: str,
    holiday_prompt_id: int | None = None,
) -> dict[str, Any]:
    """记录 37% 元反思并当场置位 first_reflection_unlocked = 1（绝不设 eval_count 门槛）。"""
    enforce_role_tool_permission(conn, caller_role, "record_reflection_and_unlock_pull", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["briefing_sealed_at"] or "").strip():
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 已封存，禁止补记元反思")

    cfg = load_runtime_config()
    window = resolve_effective_context_window(conn, node_window=node["effective_context_window"], cfg=cfg)
    reflect_pct = float(cfg.get("context_reflect_hint_pct", 0.37))
    pressure = int(node["pressure_tokens"] or 0)
    if pressure / float(max(1, window)) < reflect_pct:
        raise FailClosedError(
            ERR_LOCKED,
            f"当前上下文水位 {pressure}/{window} ({pressure / window:.1%}) 未达到 {reflect_pct:.0%} 反思阈值，严禁提前解锁内藏！",
        )

    categories = load_meta_reflection_categories()
    if (
        not isinstance(selected_categories, list) or len(selected_categories) not in (1, 2)
        or any(not isinstance(category, str) or category not in categories for category in selected_categories)
        or len(set(selected_categories)) != len(selected_categories)
    ):
        raise FailClosedError(ERR_INVALID_INPUT, "selected_categories 须从 C01–C11 选择 1–2 个不同类别")
    if holiday_prompt_id is not None and (type(holiday_prompt_id) is not int or not 1 <= holiday_prompt_id <= 28):
        raise FailClosedError(ERR_INVALID_INPUT, "兼容字段 holiday_prompt_id 仅允许 1–28 或 null")

    max_turns = int(cfg.get("reflection_max_turns", 2))
    max_chars_turn = int(cfg.get("reflection_max_chars_per_turn", 500))
    if not isinstance(turns, list) or len(turns) == 0 or len(turns) > max_turns:
        raise FailClosedError(ERR_INVALID_INPUT, f"turns 必须包含 1 到 {max_turns} 轮精简问答")
    for idx, t in enumerate(turns):
        if not isinstance(t, dict) or not str(t.get("question", "")).strip() or not str(t.get("answer", "")).strip():
            raise FailClosedError(ERR_INVALID_INPUT, f"turns[{idx}] 必须同时包含非空 question 与 answer")
        if len(str(t["question"]).strip()) > max_chars_turn or len(str(t["answer"]).strip()) > max_chars_turn:
            actual = max(len(str(t["question"]).strip()), len(str(t["answer"]).strip()))
            raise FailClosedError(ERR_INVALID_INPUT, f"第 {idx + 1} 轮当前 {actual} 字，上限 {max_chars_turn} 字，请精简后重交")

    verdict_u = str(verdict_3state or "").strip().upper()
    if verdict_u not in ALLOWED_VERDICT_3STATE:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 verdict_3state={verdict_3state!r}，仅允许 {sorted(ALLOWED_VERDICT_3STATE)}")

    existing = json.loads(node["reflections_json"] or "[]")
    now = utc_now_iso()
    existing.append(
        {
            "at": now,
            "selected_categories": [str(c) for c in selected_categories],
            "turns": turns,
            "verdict_3state": verdict_u,
        }
    )

    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE lineage_nodes SET first_reflection_unlocked = 1, reflections_json = ?, updated_at = ? WHERE node_id = ?",
            (json.dumps(existing, ensure_ascii=False), now, node_id),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="record_reflection_and_unlock_pull",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance="37% 元反思已落库并当场置位 first_reflection_unlocked = 1！探索者已解锁全馆 L3/L2、《子题全局总览》与本脉 DAG/dead_ends。",
        data={"node_id": node_id, "first_reflection_unlocked": 1, "verdict_3state": verdict_u},
    )


def _enqueue_pain_point(conn: sqlite3.Connection, question_id: str, node_id: str, text: str, now: str) -> None:
    tid = f"tkt_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO works_engineering_queue(ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at)
        VALUES (?, ?, 'PAIN_POINT', NULL, ?, 'OPEN', ?, ?)
        """,
        (tid, question_id, json.dumps({"node_id": node_id, "description": text}, ensure_ascii=False), now, now),
    )


_VALID_FORMAL_OBSERVATIONS = frozenset({"VALID_PASS", "MEASURED_REJECTION", "VALID_UNDECIDED"})


def _handoff_observations(
    conn: sqlite3.Connection, node_id: str, obs_ids: list[str],
) -> list[sqlite3.Row]:
    return [
        _find_handoff_observation(conn, node_id, obs_id)
        for obs_id in obs_ids
    ]


def _find_handoff_observation(conn: sqlite3.Connection, node_id: str, obs_id: str) -> sqlite3.Row:
    obs = conn.execute(
        """
        WITH RECURSIVE ancestry(node_id, parent_node_id) AS (
            SELECT node_id, parent_node_id FROM lineage_nodes WHERE node_id = ?
            UNION
            SELECT n.node_id, n.parent_node_id
            FROM lineage_nodes n JOIN ancestry a ON n.node_id = a.parent_node_id
        )
        SELECT o.* FROM observations o JOIN ancestry a ON a.node_id = o.node_id
        WHERE o.obs_id = ? AND o.tier IN ('official', 'heavy')
          AND o.question_id = (SELECT question_id FROM lineage_nodes WHERE node_id = ?)
        """,
        (node_id, obs_id, node_id),
    ).fetchone()
    if obs is None:
        raise FailClosedError(ERR_NOT_FOUND, f"正式观测 {obs_id!r} 不属于节点 {node_id!r} 的本题谱系")
    return obs


def _prepare_manuscripts(
    conn: sqlite3.Connection, node: sqlite3.Row, workspace_root: str, candidate_rel_path: str | None,
    manuscripts: list[dict[str, Any]], legacy_submissions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared = []
    seen_titles: set[str] = set()
    for entries, legacy in ((manuscripts, False), (legacy_submissions, True)):
        for entry in entries:
            proof_key = "column_a_self_contained_proof_md" if legacy else "claim_and_proof_md"
            scope_key = "column_b_scope_notes_md" if legacy else "exact_scope_md"
            required = ("title", proof_key) if legacy else (
                "title", "abstract_md", proof_key, scope_key, "bound_obs_ids", "declared_citations", "tags",
            )
            if not isinstance(entry, dict) or any(key not in entry for key in required):
                raise FailClosedError(ERR_INVALID_INPUT, f"投稿必须提供 {', '.join(required)}")
            title, proof = entry["title"].strip(), entry[proof_key].strip()
            scope = entry.get(scope_key, "").strip()
            abstract = "" if legacy else entry["abstract_md"].strip()
            if not title or (legacy and len(proof) < 20) or (not legacy and not (abstract and proof and scope)):
                raise FailClosedError(ERR_INVALID_INPUT, "投稿须有标题和自包含证明，新稿还需提供摘要与精确成立域")
            norm_title = " ".join(title.lower().split())
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)
            obs_ids = entry.get("bound_obs_ids", [])
            rows = _handoff_observations(conn, node["node_id"], obs_ids)
            if any(row["obs_status"] not in _VALID_FORMAL_OBSERVATIONS for row in rows):
                raise FailClosedError(ERR_INVALID_INPUT, "投稿只允许绑定有效正式观测")
            artifact = entry.get("artifact_rel_path", candidate_rel_path) if legacy else candidate_rel_path
            citations = [] if legacy else entry["declared_citations"]
            tags = [] if legacy else entry["tags"]
            background = scope if legacy else (
                f"摘要：{abstract}\n\n精确成立域：{scope}\n\n标签：{', '.join(tags)}"
            )
            prepared.append({
                "title": title, "proof": proof, "scope": background, "bound_obs_ids": obs_ids,
                "declared_citations": citations, "artifact_rel_path": artifact,
                "non_blocking": entry.get("non_blocking", True),
                "source_type": "LOCAL_LEMMA_SUBMISSION" if legacy else "SNAPSHOT_MANUSCRIPT",
            })
    if sum(not item["non_blocking"] for item in prepared) > 1:
        raise FailClosedError(ERR_INVALID_INPUT, "一次交班只能提交一份阻塞终稿")
    for item in prepared:
        item["snapshot_abs_path"] = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=f"lemma_{node['node_id']}_{uuid.uuid4().hex[:10]}",
            worktree_abs_path=node["worktree_abs_path"],
            candidate_rel_path=item["artifact_rel_path"],
        )
    return prepared


def tool_submit_node_handoff(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    question_id: str,
    mechanism_summary: str,
    evidence_grade: str,
    column_a_facts_md: str,
    column_b_hypothesis_md: str,
    will_md: str,
    obs_ids: list[str] | None = None,
    dead_ends: list[dict[str, Any]] | None = None,
    candidate_rel_path: str | None = None,
    is_empty_crash: bool = False,
    tool_pain_point: str | None = None,
    recommended_triage: dict[str, Any] | None = None,
    local_lemma_submissions: list[dict[str, Any]] | None = None,
    manuscript_submissions: list[dict[str, Any]] | None = None,
    holiday_bet_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """70% 交班独占写 DAG 页、落封存锁、支持独立局部引理拆交与常规确定性直落。"""
    enforce_role_tool_permission(conn, caller_role, "submit_node_handoff", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id) or str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_AUTH, "branch_id 或 question_id 与节点注册记录不一致")

    cur_status = str(node["node_status"])
    already_sealed = bool(str(node["briefing_sealed_at"] or "").strip())
    if cur_status in ("AWAITING_TRIAGE", "PENDING_REVIEW", "BLOCKED_L4B", "SEALED", "CLOSED") or (
        already_sealed and cur_status != "ACTIVE_REVISING"
    ):
        norm_obs = json.dumps([str(o).strip() for o in (obs_ids or []) if str(o).strip()], ensure_ascii=False)
        same_content = (
            str(node["mechanism_summary"] or "").strip() == str(mechanism_summary or "").strip()
            and str(node["evidence_grade"] or "").strip().upper() == str(evidence_grade or "").strip().upper()
            and str(node["column_a_facts_md"] or "").strip() == str(column_a_facts_md or "").strip()
            and str(node["column_b_hypothesis_md"] or "").strip() == str(column_b_hypothesis_md or "").strip()
            and str(node["will_md"] or "").strip() == str(will_md or "").strip()
            and str(node["candidate_rel_path"] or "").strip() == str(candidate_rel_path or "").strip()
            and str(node["bound_obs_ids_json"] or "[]") == norm_obs
        )
        if same_content:
            return build_tool_receipt(
                conn=conn,
                tool_name="submit_node_handoff",
                question_id=question_id,
                node_id=node_id,
                next_step_guidance=f"节点 {node_id} 已于此前提交相同交接内容（当前状态 {cur_status}），幂等跳过重复写入。",
                data={"node_id": node_id, "node_status": cur_status, "idempotent_skip": True},
            )
        raise FailClosedError(
            ERR_LOCKED,
            f"节点 {node_id!r} 已封存或处于终态 ({cur_status})，拒绝篡改已封存交接记录。",
        )

    now = utc_now_iso()

    if bool(is_empty_crash):
        scratch = json.loads(node["scratch_log_json"] or "[]")
        scratch.append({"at": now, "reason": "empty_crash", "summary": str(column_a_facts_md or will_md or "empty crash")[:400]})
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE lineage_nodes
                SET node_status = 'CLOSED', evidence_grade = 'NONE', pending_handoff_mode = NULL,
                    pending_handoff_reason = '', scratch_log_json = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (json.dumps(scratch, ensure_ascii=False), now, node_id),
            )
            if tool_pain_point and str(tool_pain_point).strip():
                _enqueue_pain_point(conn, question_id, node_id, str(tool_pain_point).strip(), now)
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_node_handoff",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance="一字未产空崩溃已记入 scratch_log 并关闭该代节点，未污染谱系 DAG。",
            data={"node_id": node_id, "node_status": "CLOSED", "is_empty_crash": True},
        )

    mech = str(mechanism_summary or "").strip()
    if not mech or len(mech) >= 100:
        raise FailClosedError(ERR_INVALID_INPUT, f"mechanism_summary 必填且必须 < 100 字纯核心机制（实收 {len(mech)} 字）")

    grade = str(evidence_grade or "").strip().upper()
    if grade not in ALLOWED_EVIDENCE_GRADES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 evidence_grade={evidence_grade!r}，仅允许 {sorted(ALLOWED_EVIDENCE_GRADES)}")

    col_a = str(column_a_facts_md or "").strip()
    col_b = str(column_b_hypothesis_md or "").strip()
    will = str(will_md or "").strip()
    if not col_a or not col_b or not will:
        raise FailClosedError(ERR_INVALID_INPUT, "column_a_facts_md、column_b_hypothesis_md 与 will_md 必须非空")

    cfg = load_runtime_config()
    max_handoff = int(cfg.get("max_handoff_chars", 5000))
    if len(col_a) + len(col_b) + len(will) > max_handoff:
        raise FailClosedError(ERR_INVALID_INPUT, f"交接手记总字数超限：{len(col_a) + len(col_b) + len(will)} > {max_handoff} 字")

    clean_obs_ids = [str(o).strip() for o in (obs_ids or []) if str(o).strip()]
    bound_obs_rows = _handoff_observations(conn, node_id, clean_obs_ids)
    if grade == "MEASURED":
        valid_rows = [row for row in bound_obs_rows if row["obs_status"] in _VALID_FORMAL_OBSERVATIONS]
        if not valid_rows:
            raise FailClosedError(ERR_INVALID_INPUT, "MEASURED 交班必须绑定至少一条有效正式观测")
        if node["artifact_dirty_since_last_obs"] and candidate_rel_path:
            current = safe_resolve_in_worktree(node["worktree_abs_path"], candidate_rel_path)
            if current.is_file() and sha256_file(current) not in {row["candidate_entry_sha256"] for row in valid_rows}:
                raise FailClosedError(ERR_LOCKED, "人工修改后的候选尚无对应实测，旧观测仍可作为历史证据绑定")

    clean_dead_ends: list[dict[str, Any]] = []
    for idx, de in enumerate(dead_ends or []):
        if not isinstance(de, dict):
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}] 必须为对象")
        cat = str(de.get("category") or "").strip().upper()
        if cat not in ALLOWED_DEAD_END_CATEGORIES:
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}].category={cat!r} 非法")
        scope_md = str(de.get("scope_condition_md") or "").strip()
        fail_md = str(de.get("failure_mechanism_md") or "").strip()
        if not scope_md or not fail_md:
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}] 必须包含非空 scope_condition_md 与 failure_mechanism_md")
        clean_dead_ends.append(
            {
                "category": cat,
                "scope_condition_md": scope_md,
                "failure_mechanism_md": fail_md,
                "bound_obs_id": str(de["bound_obs_id"]).strip() if de.get("bound_obs_id") else None,
            }
        )

    bet = json.loads(node["holiday_bet_json"])
    if "testable_hypothesis_md" in bet:
        if holiday_bet_outcome is None or holiday_bet_outcome.get("outcome") not in ALLOWED_HOLIDAY_OUTCOMES:
            raise FailClosedError(ERR_INVALID_INPUT, "已登记夜科学赌注，须填写 holiday_bet_outcome")
        note = holiday_bet_outcome.get("note_md", "").strip()
        if not note:
            raise FailClosedError(ERR_INVALID_INPUT, "夜科学赌注核销必须说明 note_md")
        outcome = holiday_bet_outcome["outcome"]
        bet.update(outcome=outcome, note_md=note)
        if outcome == "FALSIFIED":
            tested = next((row for row in bound_obs_rows if row["obs_status"] in _VALID_FORMAL_OBSERVATIONS), None)
            clean_dead_ends.append({
                "category": "SCIENTIFIC_REFUTATION", "scope_condition_md": bet["testable_hypothesis_md"],
                "failure_mechanism_md": note, "bound_obs_id": tested["obs_id"] if tested else None,
            })
    elif holiday_bet_outcome is not None:
        raise FailClosedError(ERR_INVALID_INPUT, "本节点没有待核销的夜科学赌注")

    clean_lemmas = _prepare_manuscripts(
        conn, node, workspace_root, candidate_rel_path, manuscript_submissions or [], local_lemma_submissions or [],
    )
    blocking = any(not item["non_blocking"] for item in clean_lemmas)
    wave_hibernation = node["pending_handoff_reason"].startswith("HIBERNATED_BY_WAVE_CONFERENCE")
    sanitized_diff = extract_sanitized_code_diff_md(
        worktree_abs_path=node["worktree_abs_path"],
        candidate_rel_path=candidate_rel_path,
        previous_snapshot_abs_path=node["retained_snapshot_abs_path"],
    )

    inserted_dead_end_ids: list[str] = []
    created_lemma_review_ids: list[str] = []
    node_spec_rev = int(node["spec_revision"] or 0)

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = ?,
                control_state = CASE WHEN ? THEN 'HIBERNATED' ELSE control_state END,
                mechanism_summary = ?,
                evidence_grade = ?,
                column_a_facts_md = ?,
                column_b_hypothesis_md = ?,
                will_md = ?,
                sanitized_code_diff_md = ?,
                candidate_rel_path = ?,
                bound_obs_ids_json = ?,
                pending_handoff_mode = NULL,
                pending_handoff_reason = '',
                briefing_sealed_at = ?,
                holiday_bet_json = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                "SEALED" if wave_hibernation else ("PENDING_REVIEW" if blocking else "AWAITING_TRIAGE"),
                wave_hibernation,
                mech,
                grade,
                col_a,
                col_b,
                will,
                sanitized_diff,
                candidate_rel_path,
                json.dumps(clean_obs_ids, ensure_ascii=False),
                now,
                json.dumps(bet, ensure_ascii=False),
                now,
                node_id,
            ),
        )
        conn.execute(
            """
            UPDATE subproblem_runtime_state
            SET completed_nodes_since_last_conference = completed_nodes_since_last_conference + 1,
                completed_nodes_since_last_l3 = completed_nodes_since_last_l3 + 1,
                updated_at = ?
            WHERE question_id = ?
            """,
            (now, question_id),
        )
        for de in clean_dead_ends:
            de_id = f"de_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO lineage_dead_ends(
                    dead_end_id, question_id, branch_id, node_id, category,
                    scope_condition_md, failure_mechanism_md, bound_obs_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (de_id, question_id, branch_id, node_id, de["category"], de["scope_condition_md"], de["failure_mechanism_md"], de["bound_obs_id"], now),
            )
            inserted_dead_end_ids.append(de_id)

        for lm in clean_lemmas:
            lrev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, question_id, source_node_id, source_type, proposer_session_id,
                    review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                    bound_obs_ids_json, artifact_rel_path, artifact_snapshot_abs_path, sanitized_code_diff_md,
                    non_blocking, declared_citations_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lrev_id,
                    question_id,
                    node_id,
                    lm["source_type"],
                    session_id or f"comp_{node_id}",
                    lm["title"],
                    node_spec_rev,
                    lm["proof"],
                    lm["scope"],
                    json.dumps(lm["bound_obs_ids"], ensure_ascii=False),
                    lm["artifact_rel_path"],
                    lm["snapshot_abs_path"],
                    sanitized_diff,
                    int(lm["non_blocking"]),
                    json.dumps(lm["declared_citations"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            created_lemma_review_ids.append(lrev_id)

        if wave_hibernation and node["pending_handoff_reason"].endswith(":SALVAGE"):
            sealed = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
            salvage_id = enqueue_salvage_review(conn, sealed, now)
            if salvage_id:
                created_lemma_review_ids.append(salvage_id)

        if tool_pain_point and str(tool_pain_point).strip():
            _enqueue_pain_point(conn, question_id, node_id, str(tool_pain_point).strip(), now)
        record_fact_edge(
            conn,
            source_id=node_id,
            target_id="submit_node_handoff",
            edge_type="USED_TOOL",
            session_id=session_id,
            metadata={"role": caller_role, "evidence_grade": grade},
        )

    # 裁决 2：判定是否满足确定性直落边界（防一稿两投：已提交非阻塞快照稿时严禁再叠加阻塞 LEVEL_1 重复送审并误杀分支）
    updated_node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    deduped_blocking_level1 = False
    if clean_lemmas and not blocking and node["family_id"]:
        if recommended_triage is None:
            recommended_triage = {
                "assigned_family_id": node["family_id"],
                "triage_level": "ROUTINE_CONTINUATION",
                "action": "CONTINUE",
                "rationale": "阶段稿已快照异步送审，原分支按谱系续班",
            }
        elif isinstance(recommended_triage, dict):
            rec_lvl = str(recommended_triage.get("triage_level") or "").strip().upper()
            rec_act = str(recommended_triage.get("action") or "").strip().upper()
            if rec_lvl == "LEVEL_1" or rec_act == "SUBMIT_BLIND_REVIEW":
                deduped_blocking_level1 = True
                recommended_triage = {
                    **recommended_triage,
                    "assigned_family_id": recommended_triage.get("assigned_family_id") or node["family_id"],
                    "triage_level": "ROUTINE_CONTINUATION",
                    "action": "CONTINUE",
                    "rationale": (
                        f"{str(recommended_triage.get('rationale') or '').strip()}（已通过非阻塞快照送审，避免重复走阻塞 LEVEL_1 冻结分支，原分支继续接班）"
                    ).strip(),
                }
    can_auto, auto_reason, auto_params = (False, "已安排休眠或终稿盲审", {}) if blocking or wave_hibernation else evaluate_auto_triage_eligibility(
        conn, node=updated_node, recommended_triage=recommended_triage,
    )
    auto_triage_result: dict[str, Any] | None = None
    if can_auto:
        auto_triage_result = execute_triage_core(
            conn,
            workspace_root=workspace_root,
            session_id=session_id,
            node_id=node_id,
            **auto_params,
        )

    # 触发大外环波次检查与停工锁检查
    opened_conf = check_and_open_wave_conference(conn, question_id=question_id)
    evaluate_subproblem_locks(conn, question_id=question_id)

    final_node = conn.execute("SELECT node_status FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    final_status = str(final_node["node_status"]) if final_node else "AWAITING_TRIAGE"

    parts = [f"节点 {node_id} 已封存落库（状态 {final_status}，追加 {len(inserted_dead_end_ids)} 条 dead_ends）"]
    if created_lemma_review_ids:
        parts.append(f"已提交 {len(created_lemma_review_ids)} 份快照盲审稿 {created_lemma_review_ids}")
    if auto_triage_result is not None:
        parts.append(f"确定性控制面已直落分诊：{auto_triage_result['guidance']}")
    elif not blocking and not wave_hibernation:
        parts.append(f"保留 AWAITING_TRIAGE 等待按需拉起 logistics_coordinator（原因：{auto_reason}）")
    if opened_conf is not None:
        parts.append(f"子题 {question_id} 已达波次阈值，自动开启圆桌 {opened_conf['conference_id']} (Wave {opened_conf['wave_no']})")

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_node_handoff",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance="；".join(parts) + "。",
        data={
            "node_id": node_id,
            "node_status": final_status,
            "briefing_sealed_at": now,
            "evidence_grade": grade,
            "inserted_dead_end_ids": inserted_dead_end_ids,
            "created_lemma_review_ids": created_lemma_review_ids,
            "deduped_blocking_level1": deduped_blocking_level1,
            "auto_triaged": auto_triage_result is not None,
            "auto_triage_fallback_reason": None if auto_triage_result is not None else auto_reason,
            "auto_triage_data": auto_triage_result["data"] if auto_triage_result is not None else None,
            "opened_wave_conference": opened_conf,
            "has_sanitized_diff": bool(sanitized_diff),
        },
    )
