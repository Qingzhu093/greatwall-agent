"""长城 V6-Up (v3.0) logistics_coordinator（后勤调度总管）5 个单一职责窄工具。"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .control_plane_service import (
    backup_retained_candidate_snapshot,
    check_branch_requires_satisfied,
    compute_family_concentration_alerts,
    compute_topology_and_revision_health,
    get_question_order_status,
    restore_retained_candidate_snapshot,
    sync_public_inputs_to_worktree,
    sync_public_instruments_and_skills_to_worktree,
)
from .db_schema import (
    ALLOWED_FORK_MODES,
    ALLOWED_STAGNATION_LANES,
    ALLOWED_TRIAGE_ACTIONS,
    ALLOWED_TRIAGE_LEVELS,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
    load_runtime_config,
    next_prefixed_id,
)


def _validate_deterministic_requires(requires: list[str] | None) -> list[str]:
    """分支级确定性 requires 校验：仅允许 `L3-###` 或 `OBS:<instrument_id>:PASS`。"""
    out: list[str] = []
    for raw in requires or []:
        req = str(raw or "").strip()
        if not req:
            continue
        if req.startswith("L3-") or (req.startswith("OBS:") and req.endswith(":PASS") and len(req) > len("OBS::PASS")):
            out.append(req)
        else:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"非法 requires 条目 {req!r}：仅支持系统可确定性查库的 'L3-###' 或 'OBS:<instrument_id>:PASS'",
            )
    return out


def tool_get_logistics_dashboard(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """纯查 SQLite (<50ms) 返回全卷或指定子题的方法族谱、分支占比、待分诊页、Ready Queue 与聚拢告警。"""
    enforce_role_tool_permission(conn, caller_role, "get_logistics_dashboard", session_id=session_id)
    qf = str(question_id or "ALL").strip()

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    order_status = get_question_order_status(conn)
    conc_alerts = compute_family_concentration_alerts(conn)
    if qf.upper() != "ALL":
        conc_alerts = [a for a in conc_alerts if a["question_id"] == qf]

    if qf.upper() == "ALL":
        families = [dict(r) for r in conn.execute("SELECT * FROM method_families ORDER BY question_id, family_id").fetchall()]
        triage_nodes = [
            dict(r)
            for r in conn.execute(
                """
                SELECT node_id, question_id, branch_id, family_id, generation, spec_revision, mechanism_summary,
                       evidence_grade, candidate_rel_path, bound_obs_ids_json, revise_count,
                       inplace_repair_count, premise_revoked, column_a_facts_md, will_md
                FROM lineage_nodes
                WHERE node_status = 'AWAITING_TRIAGE'
                ORDER BY updated_at ASC
                """
            ).fetchall()
        ]
        ready_queue = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, spec_revision, reopen_condition, requires_json FROM lineage_nodes WHERE node_status = 'BLOCKED_L4B' ORDER BY updated_at ASC"
            ).fetchall()
        ]
        active_branches = [
            dict(r)
            for r in conn.execute(
                "SELECT DISTINCT question_id, branch_id, family_id, spec_revision, node_status, lane_assignment FROM lineage_nodes WHERE node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')"
            ).fetchall()
        ]
    else:
        families = [dict(r) for r in conn.execute("SELECT * FROM method_families WHERE question_id = ? ORDER BY family_id", (qf,)).fetchall()]
        triage_nodes = [
            dict(r)
            for r in conn.execute(
                """
                SELECT node_id, question_id, branch_id, family_id, generation, spec_revision, mechanism_summary,
                       evidence_grade, candidate_rel_path, bound_obs_ids_json, revise_count,
                       inplace_repair_count, premise_revoked, column_a_facts_md, will_md
                FROM lineage_nodes
                WHERE node_status = 'AWAITING_TRIAGE' AND question_id = ?
                ORDER BY updated_at ASC
                """,
                (qf,),
            ).fetchall()
        ]
        ready_queue = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, spec_revision, reopen_condition, requires_json FROM lineage_nodes WHERE node_status = 'BLOCKED_L4B' AND question_id = ? ORDER BY updated_at ASC",
                (qf,),
            ).fetchall()
        ]
        active_branches = [
            dict(r)
            for r in conn.execute(
                "SELECT DISTINCT question_id, branch_id, family_id, spec_revision, node_status, lane_assignment FROM lineage_nodes WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')",
                (qf,),
            ).fetchall()
        ]

    # 附加每个待分诊节点的关联观测摘要，方便后勤辨别 CANDIDATE_ERROR vs 科学否定（并忽略 INSTRUMENT_ERROR）
    for tn in triage_nodes:
        obs_rows = conn.execute(
            "SELECT obs_id, instrument_id, instrument_version, obs_status, tracks_json FROM observations WHERE node_id = ? ORDER BY created_at ASC",
            (tn["node_id"],),
        ).fetchall()
        tn["observations"] = [
            {
                "obs_id": str(o["obs_id"]),
                "instrument_id": str(o["instrument_id"]),
                "instrument_version": int(o["instrument_version"]),
                "obs_status": str(o["obs_status"]),
                "tracks": json.loads(o["tracks_json"] or "{}"),
            }
            for o in obs_rows
        ]

    topo = compute_topology_and_revision_health(conn, question_filter=qf)
    orphaned_revs = topo.get("orphaned_blind_review_revisions") or []
    understaffed_qs = topo.get("understaffed_questions") or []
    stalled_branches = topo.get("stalled_or_aborted_branches") or []
    slot_util = topo.get("slot_utilization") or {}

    latest_hb = conn.execute(
        """
        SELECT alert_id, stage, status, blocking_questions_json, notes, created_at
        FROM compliance_alerts
        WHERE stage = 'STAGE2_HEARTBEAT'
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    supervisory_alert = dict(latest_hb) if (latest_hb and str(latest_hb["status"]).upper() == "ALERT") else None

    guidance_parts: list[str] = []
    if conc_alerts:
        guidance_parts.append(f"发现 {len(conc_alerts)} 条无豁免学派聚拢告警 (>50%)，请立即执行 fork_branch(fork_mode='orthogonal') 正交分流！")
    if orphaned_revs:
        guidance_parts.append(
            f"发现 {len(orphaned_revs)} 条孤儿盲审返工单（{[r['review_id'] for r in orphaned_revs]}：原分支被中止或断代），"
            f"请立即调用 fork_branch(parent_node_id=source_node_id, fork_mode='lateral', target_family_id=...) 继承快照与返工单继续冲刺二审！"
        )
    if understaffed_qs:
        guidance_parts.append(
            f"子题 {[u['question_id'] for u in understaffed_qs]} 存在正交学派断代缺编（单线独苗退化，空闲槽位 {slot_util.get('free_slots', 0)} 个），"
            f"请对 missing_active_family_ids 调用 fork_branch 恢复多 Worktree 并行探索！"
        )
    if not guidance_parts:
        guidance_parts.append(
            f"当前待分诊 {len(triage_nodes)} 节点、活跃分支 {len(active_branches)} 条（空闲槽位 {slot_util.get('free_slots', 0)}）、"
            f"断代分支 {len(stalled_branches)} 条、Ready Queue {len(ready_queue)} 条、已登记学派 {len(families)} 个。"
        )
    guidance = " ".join(guidance_parts)

    latest_spec_rev = int(p0["latest_spec_revision"] or 0) if (p0 and "latest_spec_revision" in p0.keys()) else 0
    latest_ruling_summary = str(p0["latest_ruling_summary_md"] or "") if (p0 and "latest_ruling_summary_md" in p0.keys()) else ""
    return build_tool_receipt(
        conn=conn,
        tool_name="get_logistics_dashboard",
        question_id=qf,
        next_step_guidance=guidance,
        data={
            "parse0_goal_md": str(p0["goal_and_completion_md"]) if p0 else "",
            "latest_spec_revision": latest_spec_rev,
            "latest_ruling_summary_md": latest_ruling_summary,
            "required_questions": json.loads(p0["subquestions_json"]) if p0 else [],
            "question_order_status": order_status,
            "consecutive_non_l1_handoffs": int(p0["consecutive_non_l1_handoffs"] or 0) if p0 else 0,
            "slot_utilization": slot_util,
            "method_families": families,
            "active_branches": active_branches,
            "stalled_or_aborted_branches": stalled_branches,
            "orphaned_blind_review_revisions": orphaned_revs,
            "understaffed_questions": understaffed_qs,
            "active_supervisory_alert": supervisory_alert,
            "family_concentration_alerts": conc_alerts,
            "awaiting_triage": triage_nodes,
            "ready_queue": ready_queue,
        },
    )


def tool_register_method_family(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    family_id: str,
    mechanism_signature: str,
    orthogonal_contrast: str,
) -> dict[str, Any]:
    """登记底层数学/物理思想学派（按需登记，不强卡固定条数）。"""
    enforce_role_tool_permission(conn, caller_role, "register_method_family", session_id=session_id)
    fid = str(family_id or "").strip()
    sig = str(mechanism_signature or "").strip()
    contrast = str(orthogonal_contrast or "").strip()
    if not fid or not sig or not contrast:
        raise FailClosedError(ERR_INVALID_INPUT, "family_id、mechanism_signature 与 orthogonal_contrast 均不能为空")

    exists = conn.execute("SELECT 1 FROM method_families WHERE family_id = ?", (fid,)).fetchone()
    if exists is not None:
        raise FailClosedError(ERR_CONFLICT, f"方法学派 {fid!r} 已存在")

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO method_families(family_id, question_id, mechanism_signature, orthogonal_contrast, family_status, created_at)
            VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (fid, question_id, sig, contrast, now),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="register_method_family",
        question_id=question_id,
        next_step_guidance=f"方法学派 {fid} 已建档，可调用 fork_branch 开启探索分支。",
        data={"question_id": question_id, "family_id": fid, "family_status": "ACTIVE"},
    )


def _has_verifiable_carrier(conn: sqlite3.Connection, node: sqlite3.Row) -> tuple[bool, str]:
    """按科学主张形态核验可核验载体完整性（数值 Obs / 形式化凭证 / 反例脚本 / >=60字自包含推导四轨并行，废除单一 passed=1 死锁！）。"""
    obs_ids = json.loads(node["bound_obs_ids_json"] or "[]")
    if obs_ids:
        ph = ",".join("?" for _ in obs_ids)
        valid_obs = conn.execute(
            f"""
            SELECT obs_id, obs_status FROM observations
            WHERE obs_id IN ({ph}) AND obs_status IN ('VALID_PASS', 'VALID_UNDECIDED', 'MEASURED_REJECTION')
            """,
            tuple(obs_ids),
        ).fetchall()
        if valid_obs:
            return True, f"绑定有效观测收据 {len(valid_obs)} 条"

    cand_rel = str(node["candidate_rel_path"] or "").strip()
    wt_abs = str(node["worktree_abs_path"] or "").strip()
    if cand_rel and wt_abs and (Path(wt_abs) / cand_rel).is_file():
        return True, f"具备实体可核验产物文件 {cand_rel}"

    col_a = str(node["column_a_facts_md"] or "").strip()
    if len(col_a) >= 60:
        return True, f"具备自包含解析推导 A 栏正文 ({len(col_a)} 字)"

    return False, "缺少可核验载体（需至少齐备其一：有效 official/heavy [Obs###]、实体脚本/反例/证明文件、或 >=60 字自包含 A 栏推导）"


def tool_triage_node(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    assigned_family_id: str,
    triage_level: str,
    action: str,
    rationale: str,
    barrier_proof_md: str | None = None,
    reopen_condition: str | None = None,
) -> dict[str, Any]:
    """后勤四级认知分诊（强制归类 assigned_family_id、按主张核验载体、快照托管与工程错误绝不污染 L2）。"""
    enforce_role_tool_permission(conn, caller_role, "triage_node", session_id=session_id, node_id=node_id)

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) != "AWAITING_TRIAGE":
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，仅 AWAITING_TRIAGE 可调 triage_node")

    lvl = str(triage_level or "").strip().upper()
    act = str(action or "").strip().upper()
    if lvl not in ALLOWED_TRIAGE_LEVELS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 triage_level={triage_level!r}，仅允许 {sorted(ALLOWED_TRIAGE_LEVELS)}")
    if act not in ALLOWED_TRIAGE_ACTIONS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 action={action!r}，仅允许 {sorted(ALLOWED_TRIAGE_ACTIONS)}")
    if not str(rationale or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "triage_node 必须提供清晰的 rationale")

    qid = str(node["question_id"])
    bid = str(node["branch_id"])
    fid = str(assigned_family_id or node["family_id"] or "").strip()
    if not fid:
        raise FailClosedError(ERR_INVALID_INPUT, "assigned_family_id 不能为空（后勤须依据 mechanism_summary 确定性归类）")
    fam = conn.execute("SELECT 1 FROM method_families WHERE family_id = ? AND question_id = ?", (fid, qid)).fetchone()
    if fam is None:
        raise FailClosedError(ERR_NOT_FOUND, f"方法学派 {fid!r} 尚未在子题 {qid} 登记，请先调 register_method_family")

    cfg = load_runtime_config()
    max_repairs = int(cfg.get("level2_max_inplace_repairs", 3))
    now = utc_now_iso()
    node_spec_rev = int(node["spec_revision"] or 0) if "spec_revision" in node.keys() else 0
    p0_rev = conn.execute(
        "SELECT latest_spec_revision, shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    latest_spec_rev = int(p0_rev["latest_spec_revision"] or 0) if (p0_rev and "latest_spec_revision" in p0_rev.keys()) else 0
    shared_rels = json.loads(p0_rev["shared_inputs_json"] or "[]") if (p0_rev and "shared_inputs_json" in p0_rev.keys()) else []

    # 若运行中分支前置 L3 已被撤回 (premise_revoked == 1)，自然交接时转 LEVEL_4B 暂停
    if int(node["premise_revoked"] or 0) == 1 and lvl not in ("LEVEL_4A", "LEVEL_4B"):
        lvl = "LEVEL_4B"
        act = "PAUSE_TO_READY_QUEUE"
        reopen_condition = reopen_condition or "前置依赖 L3 已被撤回重审，待上游 L3 恢复或切换新前提后重启"

    if lvl == "LEVEL_1" or act == "SUBMIT_BLIND_REVIEW":
        ok_carrier, carrier_note = _has_verifiable_carrier(conn, node)
        if not ok_carrier:
            raise FailClosedError(ERR_INVARIANT, f"LEVEL_1 送审准入拦截：{carrier_note}")
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE lineage_nodes
                SET family_id = ?, node_status = 'PENDING_REVIEW', retained_snapshot_abs_path = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, question_id, source_node_id, source_type, proposer_session_id,
                    review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                    bound_obs_ids_json, artifact_rel_path, sanitized_code_diff_md, created_at, updated_at
                ) VALUES (?, ?, ?, 'LEVEL1_MANUSCRIPT', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev_id,
                    qid,
                    node_id,
                    session_id or f"logistics_{node_id}",
                    str(node["mechanism_summary"] or f"{qid} Candidate Manuscript"),
                    node_spec_rev,
                    str(node["column_a_facts_md"] or ""),
                    str(node["column_b_hypothesis_md"] or ""),
                    str(node["bound_obs_ids_json"] or "[]"),
                    node["candidate_rel_path"],
                    str(node["sanitized_code_diff_md"] or ""),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = 0, updated_at = ? WHERE contract_id = 'active'", (now,))
        return build_tool_receipt(
            conn=conn,
            tool_name="triage_node",
            question_id=qid,
            node_id=node_id,
            next_step_guidance=f"已备份物理快照并冻结分支为 PENDING_REVIEW，生成盲审单 {rev_id}（{carrier_note}）。",
            data={"node_id": node_id, "triage_level": "LEVEL_1", "created_review_id": rev_id, "spec_revision": node_spec_rev, "retained_snapshot_abs_path": snap_path},
        )

    if lvl == "LEVEL_4A" or act == "SEAL_BARRIER":
        bp = str(barrier_proof_md or "").strip()
        if len(bp) < 15:
            raise FailClosedError(ERR_INVALID_INPUT, "LEVEL_4A 严密证伪/结构阻碍证明必须提供 >= 15 字的 barrier_proof_md")
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        rev_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
        col_a_combined = (str(node["column_a_facts_md"] or "") + "\n\n### 结构阻碍 / 反例证明\n" + bp).strip()
        with rw_immediate_tx(conn):
            conn.execute(
                """
                UPDATE lineage_nodes
                SET family_id = ?, node_status = 'PENDING_REVIEW', retained_snapshot_abs_path = ?, updated_at = ?
                WHERE node_id = ?
                """,
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, question_id, source_node_id, source_type, proposer_session_id,
                    review_status, manuscript_title, spec_revision, column_a_snapshot_md, column_b_snapshot_md,
                    bound_obs_ids_json, artifact_rel_path, sanitized_code_diff_md, created_at, updated_at
                ) VALUES (?, ?, ?, 'LEVEL4A_BARRIER', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rev_id,
                    qid,
                    node_id,
                    session_id or f"logistics_{node_id}",
                    f"[Barrier/Counterexample] {node['mechanism_summary'] or qid}",
                    node_spec_rev,
                    col_a_combined,
                    str(node["column_b_hypothesis_md"] or ""),
                    str(node["bound_obs_ids_json"] or "[]"),
                    node["candidate_rel_path"],
                    str(node["sanitized_code_diff_md"] or ""),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return build_tool_receipt(
            conn=conn,
            tool_name="triage_node",
            question_id=qid,
            node_id=node_id,
            next_step_guidance=f"LEVEL_4A 阻碍/反例证明已冻结为 PENDING_REVIEW 并送盲审 {rev_id}（判 REVISE 可返工，终判确证后才 SEALED）。",
            data={"node_id": node_id, "triage_level": "LEVEL_4A", "created_review_id": rev_id, "node_status": "PENDING_REVIEW"},
        )

    if lvl == "LEVEL_4B" or act == "PAUSE_TO_READY_QUEUE":
        rc = str(reopen_condition or "").strip()
        if not rc:
            raise FailClosedError(ERR_INVALID_INPUT, "LEVEL_4B 条件阻塞必须填写 reopen_condition 以供 Ready Queue 唤醒")
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'BLOCKED_L4B', reopen_condition = ?, updated_at = ? WHERE node_id = ?",
                (fid, rc, now, node_id),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return build_tool_receipt(
            conn=conn,
            tool_name="triage_node",
            question_id=qid,
            node_id=node_id,
            next_step_guidance=f"分支 {bid} 已挂入 Ready Queue (BLOCKED_L4B)，已允许 Auditor 按需打捞残骸局部引理。",
            data={"node_id": node_id, "triage_level": "LEVEL_4B", "node_status": "BLOCKED_L4B", "reopen_condition": rc},
        )

    if lvl == "LEVEL_2" or act == "INPLACE_REPAIR":
        cur_repairs = int(node["inplace_repair_count"] or 0)
        # 防跨学派吞并：原地修补（INPLACE_REPAIR）属于同一路线的代码缺陷修复，若原节点所属学派为子题内该学派唯一分支，保持原学派不消灭正交学派
        orig_fid = str(node["family_id"] or "").strip()
        eff_repair_fid = fid
        if orig_fid and orig_fid != fid:
            rem_in_orig = conn.execute(
                """
                SELECT COUNT(DISTINCT branch_id) AS cnt FROM lineage_nodes
                WHERE question_id = ? AND family_id = ? AND branch_id != ?
                  AND node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
                """,
                (qid, orig_fid, bid),
            ).fetchone()
            if int(rem_in_orig["cnt"] or 0) == 0:
                eff_repair_fid = orig_fid

        # 若此前有物理快照先恢复工作区，并同步最新公开 inputs/ 与 PROBE/ENV 仪器镜像供新代节点使用
        if node["retained_snapshot_abs_path"]:
            restore_retained_candidate_snapshot(str(node["retained_snapshot_abs_path"]), str(node["worktree_abs_path"]))
        sync_public_inputs_to_worktree(workspace_root, str(node["worktree_abs_path"]), shared_rels)
        sync_public_instruments_and_skills_to_worktree(conn, workspace_root, str(node["worktree_abs_path"]))

        next_node_id = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
        exhausted = cur_repairs >= max_repairs
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', updated_at = ? WHERE node_id = ?",
                (eff_repair_fid, now, node_id),
            )
            if exhausted:
                # 满 3 次原地修补失败：仅记入本脉 lineage_dead_ends(IMPL_FAILURE)，绝对严禁污染中央图书馆 L2！
                de_id = f"de_{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO lineage_dead_ends(dead_end_id, question_id, branch_id, node_id, category, scope_condition_md, failure_mechanism_md, bound_obs_id, created_at)
                    VALUES (?, ?, ?, ?, 'IMPL_FAILURE', ?, ?, NULL, ?)
                    """,
                    (de_id, qid, bid, node_id, f"LEVEL_2 原地修补满 {max_repairs} 次失败", str(rationale).strip(), now),
                )
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                    worktree_abs_path, retained_snapshot_abs_path, requires_json, revise_count,
                    inplace_repair_count, last_revision_requests_json, spec_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_node_id,
                    qid,
                    bid,
                    eff_repair_fid,
                    node_id,
                    int(node["generation"]) + 1,
                    str(node["worktree_abs_path"]),
                    node["retained_snapshot_abs_path"],
                    str(node["requires_json"] or "[]"),
                    int(node["revise_count"] or 0),
                    0 if exhausted else cur_repairs + 1,
                    str(node["last_revision_requests_json"] or "[]"),
                    latest_spec_rev,
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))
        return build_tool_receipt(
            conn=conn,
            tool_name="triage_node",
            question_id=qid,
            node_id=next_node_id,
            next_step_guidance=(
                f"原地修补满 {max_repairs} 次已写入本脉 lineage_dead_ends(IMPL_FAILURE)（未污染图书馆 L2）并回退重启 {next_node_id}。"
                if exhausted
                else f"已启动第 {cur_repairs + 1}/{max_repairs} 次 LEVEL_2 原地修补节点 {next_node_id}（学派锁定为 {eff_repair_fid}）。"
            ),
            data={"closed_node_id": node_id, "next_node_id": next_node_id, "assigned_family_id": eff_repair_fid, "repair_exhausted": exhausted},
        )

    if lvl == "LEVEL_3" or act == "SPAWN_PROTECTED":
        prot_bid = f"b_{qid.lower()}_prot_{uuid.uuid4().hex[:6]}"
        prot_wt = Path(os.path.realpath(workspace_root)) / "worktrees" / prot_bid
        prot_wt.mkdir(parents=True, exist_ok=True)
        snap_path = backup_retained_candidate_snapshot(
            workspace_root=workspace_root,
            branch_id=bid,
            worktree_abs_path=str(node["worktree_abs_path"]),
            candidate_rel_path=node["candidate_rel_path"],
        )
        restore_retained_candidate_snapshot(snap_path, str(prot_wt))
        sync_public_inputs_to_worktree(workspace_root, prot_wt, shared_rels)
        sync_public_instruments_and_skills_to_worktree(conn, workspace_root, prot_wt)
        prot_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', retained_snapshot_abs_path = ?, updated_at = ? WHERE node_id = ?",
                (fid, snap_path, now, node_id),
            )
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                    worktree_abs_path, retained_snapshot_abs_path, requires_json, spec_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 'EXPLORING', ?, ?, ?, ?, ?, ?)
                """,
                (prot_nid, qid, prot_bid, fid, node_id, str(prot_wt), snap_path, str(node["requires_json"] or "[]"), latest_spec_rev, now, now),
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="triage_node",
            question_id=qid,
            node_id=prot_nid,
            next_step_guidance=f"已为反常/特异突破单开受保护支线 {prot_bid} ({prot_nid})。",
            data={"closed_node_id": node_id, "protected_branch_id": prot_bid, "next_node_id": prot_nid},
        )

    # ROUTINE_CONTINUATION / CONTINUE
    snap_path = backup_retained_candidate_snapshot(
        workspace_root=workspace_root,
        branch_id=bid,
        worktree_abs_path=str(node["worktree_abs_path"]),
        candidate_rel_path=node["candidate_rel_path"],
    )
    sync_public_inputs_to_worktree(workspace_root, str(node["worktree_abs_path"]), shared_rels)
    sync_public_instruments_and_skills_to_worktree(conn, workspace_root, str(node["worktree_abs_path"]))
    next_node_id = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE lineage_nodes SET family_id = ?, node_status = 'CLOSED', retained_snapshot_abs_path = ?, updated_at = ? WHERE node_id = ?",
            (fid, snap_path, now, node_id),
        )
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                worktree_abs_path, retained_snapshot_abs_path, requires_json, revise_count,
                inplace_repair_count, last_revision_requests_json, spec_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                next_node_id,
                qid,
                bid,
                fid,
                node_id,
                int(node["generation"]) + 1,
                str(node["worktree_abs_path"]),
                snap_path,
                str(node["requires_json"] or "[]"),
                int(node["revise_count"] or 0),
                str(node["last_revision_requests_json"] or "[]"),
                latest_spec_rev,
                now,
                now,
            ),
        )
        conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE contract_id = 'active'", (now,))

    return build_tool_receipt(
        conn=conn,
        tool_name="triage_node",
        question_id=qid,
        node_id=next_node_id,
        next_step_guidance=f"已刷新物理快照并创建下一代节点 {next_node_id}（等待伴随重写行前看板）。",
        data={"closed_node_id": node_id, "next_node_id": next_node_id, "retained_snapshot_abs_path": snap_path},
    )


def tool_fork_branch(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    question_id: str,
    parent_node_id: str | None = None,
    fork_mode: str = "orthogonal",
    target_family_id: str = "",
    requires: list[str] | None = None,
    new_mechanism_note: str | None = None,
    source_l3_id: str | None = None,
) -> dict[str, Any]:
    """开启新探索分支（分支级确定性 requires、WHERE branch_id != :self 查重、跨脉授粉双 L3 门槛、断代/盲审返工快照无损继承）。"""
    enforce_role_tool_permission(conn, caller_role, "fork_branch", session_id=session_id)
    mode_l = str(fork_mode or "").strip().lower()
    if mode_l not in ALLOWED_FORK_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 fork_mode={fork_mode!r}，仅允许 {sorted(ALLOWED_FORK_MODES)}")

    fid = str(target_family_id or "").strip()
    if not fid:
        raise FailClosedError(ERR_INVALID_INPUT, "target_family_id 不能为空")
    fam = conn.execute("SELECT * FROM method_families WHERE family_id = ? AND question_id = ?", (fid, question_id)).fetchone()
    if fam is None:
        raise FailClosedError(ERR_NOT_FOUND, f"方法学派 {fid!r} 尚未在子题 {question_id} 登记")

    if str(fam["family_status"]) == "BLOCKED" and not str(new_mechanism_note or "").strip():
        raise FailClosedError(
            ERR_LOCKED,
            f"学派 {fid!r} 当前处于 BLOCKED 状态（阻塞引理：{fam['blocking_lemma']}），重开必须提供实质绕开方案 new_mechanism_note",
        )

    parent_branch_id = ""
    parent_family_id = ""
    pnode: sqlite3.Row | None = None
    if parent_node_id:
        pnode = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (parent_node_id,)).fetchone()
        if pnode is None:
            raise FailClosedError(ERR_NOT_FOUND, f"父节点 {parent_node_id!r} 不存在")
        parent_branch_id = str(pnode["branch_id"])
        parent_family_id = str(pnode["family_id"] or "")

    # orthogonal 查重：强加 WHERE branch_id != :self（绝不因自身分支而误报重复）
    if mode_l == "orthogonal" and parent_branch_id and parent_family_id == fid:
        siblings = conn.execute(
            """
            SELECT DISTINCT branch_id FROM lineage_nodes
            WHERE question_id = ? AND family_id = ? AND branch_id != ?
              AND node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
            """,
            (question_id, fid, parent_branch_id),
        ).fetchall()
        if siblings:
            raise FailClosedError(
                ERR_CONFLICT,
                f"orthogonal 分流必须切向不同或欠探索学派：学派 {fid!r} 已有活跃兄弟分支 {[r['branch_id'] for r in siblings]}",
            )

    if mode_l == "cross_pollinate":
        if not str(source_l3_id or "").strip():
            raise FailClosedError(ERR_INVALID_INPUT, "cross_pollinate 分叉必须指定已证实的 source_l3_id")
        src_l3 = conn.execute(
            "SELECT entry_id, question_id FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1",
            (source_l3_id,),
        ).fetchone()
        if src_l3 is None:
            raise FailClosedError(ERR_NOT_FOUND, f"交叉授粉引理 {source_l3_id!r} 不存在或非活跃 L3")
        # 延迟交叉授粉双 L3 门槛：双方学派各自至少已有 >= 1 条 L3
        target_fam_l3 = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM internal_research_ledger l
            JOIN review_queue r ON r.review_id = l.verified_review_id
            JOIN lineage_nodes n ON n.node_id = r.source_node_id
            WHERE l.ledger_type = 'L3_VERIFIED' AND l.is_active = 1 AND n.family_id = ?
            """,
            (fid,),
        ).fetchone()["cnt"]
        if int(target_fam_l3 or 0) < 1:
            raise FailClosedError(
                ERR_LOCKED,
                f"延迟交叉授粉门禁：目标学派 {fid!r} 尚未拥有 >= 1 条独立已审 L3（须双方学派各有 >=1 L3 后方可嫁接）",
            )

    clean_reqs = _validate_deterministic_requires(requires)
    sat, unmet = check_branch_requires_satisfied(conn, clean_reqs)

    new_bid = f"b_{question_id.lower()}_{fid[:12]}_{uuid.uuid4().hex[:5]}"
    new_nid = f"node_{question_id.lower()}_{uuid.uuid4().hex[:8]}"
    wt_dir = Path(os.path.realpath(workspace_root)) / "worktrees" / new_bid
    wt_dir.mkdir(parents=True, exist_ok=True)

    # 若指定了 parent_node_id，自动继承父节点快照或父 Worktree 中的代码/工具资产，以及未结清的 REVISE 盲审返工意见！
    inherited_snap_path: str | None = None
    inherited_revise_count = 0
    inherited_rev_reqs_json = "[]"
    initial_status = "EXPLORING"

    if pnode is not None:
        p_snap = str(pnode["retained_snapshot_abs_path"] or "").strip()
        p_wt = str(pnode["worktree_abs_path"] or "").strip()
        if p_snap and Path(p_snap).is_dir():
            restore_retained_candidate_snapshot(p_snap, str(wt_dir))
            inherited_snap_path = p_snap
        elif p_wt and Path(p_wt).is_dir():
            restore_retained_candidate_snapshot(p_wt, str(wt_dir))

        raw_reqs = str(pnode["last_revision_requests_json"] or "[]")
        if raw_reqs in ("", "[]", "null"):
            rev_row = conn.execute(
                "SELECT revision_requests_json FROM review_queue WHERE source_node_id = ? AND review_status = 'CLOSED_REVISE' ORDER BY updated_at DESC LIMIT 1",
                (str(pnode["node_id"]),),
            ).fetchone()
            if rev_row and rev_row["revision_requests_json"]:
                raw_reqs = str(rev_row["revision_requests_json"])
        try:
            parsed_reqs = json.loads(raw_reqs)
            if isinstance(parsed_reqs, list) and len(parsed_reqs) > 0 and parent_family_id == fid:
                inherited_rev_reqs_json = json.dumps(parsed_reqs, ensure_ascii=False)
                inherited_revise_count = int(pnode["revise_count"] or 1)
                initial_status = "ACTIVE_REVISING"
        except Exception:
            pass

    try:
        p0_row = conn.execute(
            "SELECT shared_inputs_json, latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'"
        ).fetchone()
        shared_rels = json.loads(p0_row["shared_inputs_json"] or "[]") if p0_row else []
        latest_spec_rev = int(p0_row["latest_spec_revision"] or 0) if (p0_row and "latest_spec_revision" in p0_row.keys()) else 0
    except Exception:
        shared_rels = []
        latest_spec_rev = 0
    mounted_inputs = sync_public_inputs_to_worktree(workspace_root, wt_dir, shared_rels)
    synced_insts = sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir)
    mounted_inputs.extend(synced_insts)
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        if str(fam["family_status"]) == "BLOCKED" and str(new_mechanism_note or "").strip():
            conn.execute("UPDATE method_families SET family_status = 'ACTIVE' WHERE family_id = ?", (fid,))
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                worktree_abs_path, retained_snapshot_abs_path, mechanism_summary, requires_json,
                revise_count, last_revision_requests_json, spec_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_nid,
                question_id,
                new_bid,
                fid,
                parent_node_id,
                initial_status,
                str(wt_dir),
                inherited_snap_path,
                str(new_mechanism_note or (pnode["mechanism_summary"] if pnode else "") or "")[:99],
                json.dumps(clean_reqs, ensure_ascii=False),
                inherited_revise_count,
                inherited_rev_reqs_json,
                latest_spec_rev,
                now,
                now,
            ),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="fork_branch",
        question_id=question_id,
        node_id=new_nid,
        next_step_guidance=(
            f"新分支 {new_bid} ({new_nid}) 已建立（前置 requires 未满足项 {unmet}，仅暂锁本分支不影响同题兄弟分支）。"
            if not sat
            else f"新分支 {new_bid} ({new_nid}, status={initial_status}) 已就绪，将由伴随助手写行前看板并立即启动探索。"
        ),
        data={
            "question_id": question_id,
            "branch_id": new_bid,
            "node_id": new_nid,
            "family_id": fid,
            "fork_mode": mode_l,
            "node_status": initial_status,
            "inherited_revision_requests": json.loads(inherited_rev_reqs_json),
            "worktree_abs_path": str(wt_dir),
            "mounted_public_inputs": mounted_inputs,
            "requires": clean_reqs,
            "requires_satisfied": sat,
            "unmet_requires": unmet,
        },
    )


def tool_dispatch_stagnation_five_lanes(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    lane_assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """全局停滞或 >50% 聚拢告警时将活跃分支打散编入五互斥车道并重置停滞计数。"""
    enforce_role_tool_permission(conn, caller_role, "dispatch_stagnation_five_lanes", session_id=session_id)
    if not isinstance(lane_assignments, list) or not lane_assignments:
        raise FailClosedError(ERR_INVALID_INPUT, "lane_assignments 不能为空")

    seen_branches: set[str] = set()
    applied: list[dict[str, str]] = []
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        for item in lane_assignments:
            if not isinstance(item, dict):
                raise FailClosedError(ERR_INVALID_INPUT, "lane_assignments 元素必须为对象")
            bid = str(item.get("branch_id") or "").strip()
            lane = str(item.get("lane") or "").strip().upper()
            directive = str(item.get("directive") or "").strip()
            if not bid or lane not in ALLOWED_STAGNATION_LANES:
                raise FailClosedError(
                    ERR_INVALID_INPUT,
                    f"非法车道分配 branch_id={bid!r}, lane={lane!r}（仅允许 {sorted(ALLOWED_STAGNATION_LANES)}）",
                )
            if bid in seen_branches:
                raise FailClosedError(ERR_CONFLICT, f"同一分支 {bid!r} 不可重复分配车道")
            seen_branches.add(bid)

            exists = conn.execute(
                "SELECT 1 FROM lineage_nodes WHERE question_id = ? AND branch_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','BLOCKED_L4B','AWAITING_TRIAGE') LIMIT 1",
                (question_id, bid),
            ).fetchone()
            if exists is None:
                raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id} 下无活跃或阻塞分支 {bid!r}")

            conn.execute(
                "UPDATE lineage_nodes SET lane_assignment = ?, updated_at = ? WHERE question_id = ? AND branch_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','BLOCKED_L4B','AWAITING_TRIAGE')",
                (f"{lane}: {directive}" if directive else lane, now, question_id, bid),
            )
            applied.append({"branch_id": bid, "lane": lane, "directive": directive})

        conn.execute("UPDATE parse0_contract SET consecutive_non_l1_handoffs = 0, updated_at = ? WHERE contract_id = 'active'", (now,))

    return build_tool_receipt(
        conn=conn,
        tool_name="dispatch_stagnation_five_lanes",
        question_id=question_id,
        next_step_guidance=f"已将 {len(applied)} 条分支编入五车道并重置停滞计数。",
        data={"question_id": question_id, "applied_lanes": applied},
    )
