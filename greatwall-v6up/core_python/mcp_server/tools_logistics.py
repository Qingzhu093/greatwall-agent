"""V6-Up (v2.2) logistics_coordinator（后勤调度总管）5 个窄工具实现。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from evaluators.isolated_runner import (
    run_stage_b_revaluation,
    sha256_file,
)
from .control_plane_service import (
    backup_retained_candidate_snapshot,
    check_stage2_closure_gate_data,
    export_stage3_deliverables,
    get_question_dependency_status,
    restore_retained_candidate_snapshot,
)
from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    propagate_dependency_recheck,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    VALID_FORK_MODES,
    VALID_STAGNATION_LANES,
    build_tool_receipt,
    check_mechanism_similarity,
    compute_adversarial_qp,
    compute_bb_epsilon,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    record_fact_edge,
    validate_baseline_isolation_ast,
)
from .governance_common import (
    _SQL_WRITE_FORBIDDEN_RE,
    _audit_node_unread_citations,
    _collect_proposer_sessions,
    _extract_referenced_cards_for_blind_review,
    _next_id,
    _next_ledger_id,
    _parse_proposer_sessions,
    _require_reviewer_session,
)

# ==============================================================================
# 角色 3：logistics_coordinator（5 个窄工具）
# ==============================================================================


def tool_get_logistics_dashboard(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_logistics_dashboard", session_id=session_id)
    cfg = load_runtime_config()
    q_filter = (question_id or "ALL").strip()
    ep = conn.execute("SELECT * FROM epoch_config WHERE config_id = 'active'").fetchone()
    non_l1 = int(ep["consecutive_non_l1_handoffs"]) if ep else 0
    stag_thresh = int(cfg.get("stagnation_consecutive_non_l1_handoffs", 8))

    if q_filter.upper() == "ALL":
        fams = [dict(r) for r in conn.execute("SELECT * FROM method_families ORDER BY question_id, created_at").fetchall()]
        triage_nodes = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lineage_nodes WHERE node_status = 'AWAITING_TRIAGE' ORDER BY updated_at ASC"
            ).fetchall()
        ]
        ready_queue = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, reopen_condition, will_md, updated_at FROM lineage_nodes WHERE node_status = 'BLOCKED_L4B' ORDER BY updated_at ASC"
            ).fetchall()
        ]
        exploring = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, pressure_tokens, eval_count FROM lineage_nodes WHERE node_status = 'EXPLORING'"
            ).fetchall()
        ]
    else:
        fams = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM method_families WHERE question_id = ? ORDER BY created_at", (q_filter,)
            ).fetchall()
        ]
        triage_nodes = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lineage_nodes WHERE question_id = ? AND node_status = 'AWAITING_TRIAGE' ORDER BY updated_at ASC",
                (q_filter,),
            ).fetchall()
        ]
        ready_queue = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, reopen_condition, will_md, updated_at FROM lineage_nodes WHERE question_id = ? AND node_status = 'BLOCKED_L4B' ORDER BY updated_at ASC",
                (q_filter,),
            ).fetchall()
        ]
        exploring = [
            dict(r)
            for r in conn.execute(
                "SELECT node_id, question_id, branch_id, family_id, pressure_tokens, eval_count FROM lineage_nodes WHERE question_id = ? AND node_status = 'EXPLORING'",
                (q_filter,),
            ).fetchall()
        ]

    for tn in triage_nodes:
        obs = conn.execute(
            "SELECT obs_id, obs_status, passed, comparable_rank_score, metrics_json, details_text FROM observations WHERE node_id = ?",
            (tn["node_id"],),
        ).fetchall()
        tn["observations"] = [dict(o) for o in obs]

    req_qs = json.loads(ep["required_questions_json"]) if ep and ep["required_questions_json"] else []
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    dep_status = get_question_dependency_status(conn, contracts=contracts, required_questions=req_qs)
    for rq in ready_queue:
        rq_dep = dep_status.get(str(rq["question_id"]), {})
        rq["depends_on_questions"] = rq_dep.get("depends_on_questions", [])
        rq["unmet_dependencies"] = rq_dep.get("unmet_dependencies", [])
        rq["dependency_unlocked"] = rq_dep.get("unlocked", True)

    recent_l3 = [
        dict(r)
        for r in conn.execute(
            "SELECT entry_id, question_id, title, exact_verified_scope_md, created_at FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active' ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
    ]
    hooks = [
        dict(r)
        for r in conn.execute(
            "SELECT question_id, eval_epoch_version, fidelity_max_error_pct, public_input_sample_json, updated_at FROM domain_hooks_by_question"
        ).fetchall()
    ]

    all_blocked = (len(exploring) == 0 and len(triage_nodes) == 0 and len(ready_queue) > 0)
    stag_triggered = non_l1 >= stag_thresh or all_blocked

    guidance = (
        f"当前有 {len(triage_nodes)} 个 AWAITING_TRIAGE 节点待调 triage_node；"
        + ("停滞看门狗已触发，请调 dispatch_stagnation_five_lanes 分配 5 互斥车道！" if stag_triggered else "可对照 goal_md、question_dependencies、Ready Queue 与最新 L3/钩子决定是否 fork_branch。")
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="get_logistics_dashboard",
        question_id=q_filter,
        next_step_guidance=guidance,
        data={
            "epoch_config": {
                "epoch_id": int(ep["epoch_id"]) if ep else 1,
                "stage": str(ep["stage"]) if ep else "STAGE1_PARSE0",
                "goal_md": str(ep["goal_md"] or "") if ep else "",
                "required_questions": req_qs,
                "contracts_json": contracts,
            },
            "question_dependencies": dep_status,
            "method_families": fams,
            "awaiting_triage_nodes": triage_nodes,
            "active_exploring_nodes": exploring,
            "ready_queue_blocked_l4b": ready_queue,
            "recent_verified_l3_unlocks": recent_l3,
            "domain_hooks": hooks,
            "stagnation": {
                "consecutive_non_l1_handoffs": non_l1,
                "threshold": stag_thresh,
                "triggered": stag_triggered,
            },
            "slot_budget": {
                "configured_max": int(cfg.get("max_concurrent_workers", 6)),
                "hard_cap": int(cfg.get("max_concurrent_workers_hard_cap", 10)),
                "currently_running": len(exploring),
            },
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
    depends_on_questions: list[str] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "register_method_family", session_id=session_id)
    if not family_id.strip() or not mechanism_signature.strip():
        raise FailClosedError(ERR_INVALID_INPUT, "family_id 与 mechanism_signature 不能为空")

    ep = conn.execute("SELECT epoch_id, contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    epoch_id = int(ep["epoch_id"]) if ep else 1
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    q_c = contracts.get(question_id, {}) if isinstance(contracts, dict) else {}
    c_deps = q_c.get("depends_on_questions") if isinstance(q_c, dict) else []
    merged_deps = sorted({
        *(str(d).strip() for d in (depends_on_questions or []) if str(d).strip() and str(d).strip() != question_id),
        *(str(d).strip() for d in (c_deps or []) if str(d).strip() and str(d).strip() != question_id),
    })

    existing = conn.execute(
        "SELECT family_id, mechanism_signature FROM method_families WHERE epoch_id = ? AND question_id = ?",
        (epoch_id, question_id),
    ).fetchall()
    for ex in existing:
        if str(ex["family_id"]) == family_id:
            raise FailClosedError(ERR_CONFLICT, f"方法学派 {family_id!r} 在 {question_id} 已存在")
        sim = check_mechanism_similarity(mechanism_signature, str(ex["mechanism_signature"]))
        if sim >= 0.88:
            raise FailClosedError(
                ERR_CONFLICT,
                f"学派机制撞车：与既有学派 {ex['family_id']!r} 高度相似 (sim={sim:.2f})，请登记正交机理",
            )

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO method_families(epoch_id, question_id, family_id, mechanism_signature, orthogonal_contrast, family_status, depends_on_questions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?)
            """,
            (
                epoch_id,
                question_id,
                family_id.strip(),
                mechanism_signature.strip(),
                (orthogonal_contrast or "").strip(),
                json.dumps(merged_deps, ensure_ascii=False),
                now,
                now,
            ),
        )
    count = len(existing) + 1
    cfg = load_runtime_config()
    min_fam = int(cfg.get("min_initial_method_families_per_question", 2))
    guidance = (
        f"子题 {question_id} 已登记 {count} 个学派（开局最低要求 {min_fam} 个）。"
        + ("请再登记至少 1 个互斥学派后调 fork_branch 并发派单。" if count < min_fam else "已达多学派互斥条件，可调 fork_branch 派发并发分支。")
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="register_method_family",
        question_id=question_id,
        next_step_guidance=guidance,
        data={
            "question_id": question_id,
            "family_id": family_id,
            "depends_on_questions": merged_deps,
            "total_families_for_question": count,
        },
    )


def tool_triage_node(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    triage_level: str,
    action: str,
    rationale: str,
    barrier_proof_md: str | None = None,
    reopen_condition: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "triage_node", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) != "AWAITING_TRIAGE":
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 状态为 {node['node_status']}，仅 AWAITING_TRIAGE 可调 triage_node")

    tl = (triage_level or "").strip().upper()
    act = (action or "").strip().upper()
    valid_pairs = {
        ("ROUTINE_CONTINUATION", "CONTINUE"),
        ("LEVEL_1", "SUBMIT_BLIND_REVIEW"),
        ("LEVEL_2", "INPLACE_REPAIR"),
        ("LEVEL_3", "SPAWN_PROTECTED"),
        ("LEVEL_4A", "SEAL_BARRIER"),
        ("LEVEL_4B", "PAUSE_TO_READY_QUEUE"),
    }
    if (tl, act) not in valid_pairs:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法的 (triage_level, action) 组合: ({triage_level!r}, {action!r})，仅允许 {sorted(valid_pairs)}",
        )
    if not (rationale or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "triage_node 必须提供清晰的 rationale")

    qid = str(node["question_id"])
    bid = str(node["branch_id"])
    fid = str(node["family_id"])
    wt_abs = str(node["worktree_abs_path"])
    now = utc_now_iso()
    cfg = load_runtime_config()
    max_repairs = int(cfg.get("level2_max_inplace_repairs", 3))

    obs_rows = conn.execute(
        "SELECT * FROM observations WHERE node_id = ? ORDER BY created_at DESC",
        (node_id,),
    ).fetchall()
    valid_passed = [r for r in obs_rows if str(r["obs_status"]) == "VALID" and int(r["passed"]) == 1]

    created_review_id: str | None = None
    created_l2_id: str | None = None
    spawned_node_id: str | None = None
    restored_files: list[str] = []

    with rw_immediate_tx(conn):
        if tl == "LEVEL_1":
            if not valid_passed:
                raise FailClosedError(
                    ERR_INVARIANT,
                    f"LEVEL_1 送审拦截：节点 {node_id!r} 不存在任何 VALID 且 passed=1 的观测收据",
                )
            snap_path = str(node["retained_snapshot_abs_path"] or "")
            if not snap_path:
                # 兜底尝试从最新 passed candidate_rel 或工作树备份
                paths = resolve_storage_paths(workspace_root)
                py_files = [
                    p for p in Path(wt_abs).rglob("*.py")
                    if "__pycache__" not in p.parts and "tools" not in p.relative_to(Path(wt_abs)).parts
                ] if Path(wt_abs).is_dir() else []
                if py_files:
                    snap_path = backup_retained_candidate_snapshot(
                        paths, bid, node_id, wt_abs, py_files[0].relative_to(Path(wt_abs)).as_posix()
                    )

            created_review_id = _next_id(conn, "review_queue", "review_id", "rev_", 3)
            bound_obs_ids = [str(r["obs_id"]) for r in obs_rows]
            proposer_sessions_val = _collect_proposer_sessions(conn, node_id, session_id or bid)
            conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, source_node_id, question_id, source_type, proposer_session_id,
                    review_status, manuscript_title, column_a_snapshot_md, column_b_snapshot_md,
                    sanitized_code_diff_md, bound_obs_ids_json, created_at
                ) VALUES (?, ?, ?, 'LEVEL1_MANUSCRIPT', ?, 'STAGE1_BLIND', ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_review_id,
                    node_id,
                    qid,
                    proposer_sessions_val,
                    f"{qid} {fid} 突破手稿",
                    str(node["column_a_facts_md"]),
                    str(node["column_b_hypothesis_md"]),
                    str(node["sanitized_code_diff_md"]),
                    json.dumps(bound_obs_ids, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'CLOSED', triage_level = ?, retained_snapshot_abs_path = ?, updated_at = ? WHERE node_id = ?",
                (tl, snap_path, now, node_id),
            )

        elif tl == "LEVEL_2":
            restored_files = restore_retained_candidate_snapshot(wt_abs, str(node["retained_snapshot_abs_path"] or ""))
            rep_count = int(node["inplace_repair_count"] or 0) + 1
            conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE config_id = 'active'", (now,))
            if rep_count >= max_repairs:
                # 满 3 次自动写内藏 L2_FAILURE_RECORD 并结束本代，退回祖先
                created_l2_id = _next_ledger_id(conn, "L2_FAILURE_RECORD")
                hook_sha = str(obs_rows[0]["domain_hook_sha256"]) if obs_rows else ""
                conn.execute(
                    """
                    INSERT INTO internal_research_ledger(
                        entry_id, question_id, ledger_type, source_type, method_family_id,
                        title, abstract_md, exact_refuted_scope_md, body_proof_or_code_md,
                        bound_obs_ids_json, domain_hook_sha256, created_at
                    ) VALUES (?, ?, 'L2_FAILURE_RECORD', 'L2_REPAIR_EXHAUSTED', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        created_l2_id,
                        qid,
                        fid,
                        f"[{qid}] {fid} 环境/运行修补超限 ({rep_count} 次)",
                        f"分支 {bid} 在 {qid} 连续触发 EXECUTION_ERROR 且原地修补达 {rep_count} 次上限，已由事务自动沉淀至 L2 失败雷达警示后来者。",
                        str(rationale).strip(),
                        str(node["column_a_facts_md"]),
                        json.dumps([str(r["obs_id"]) for r in obs_rows], ensure_ascii=False),
                        hook_sha,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE lineage_nodes SET node_status = 'CLOSED', triage_level = ?, inplace_repair_count = ?, updated_at = ? WHERE node_id = ?",
                    (tl, rep_count, now, node_id),
                )
            else:
                # 回滚快照后允许下代继续同向修补
                conn.execute(
                    "UPDATE lineage_nodes SET node_status = 'CLOSED', triage_level = ?, inplace_repair_count = ?, updated_at = ? WHERE node_id = ?",
                    (tl, rep_count, now, node_id),
                )
                spawned_node_id = _next_id(conn, "lineage_nodes", "node_id", f"node_{qid.lower()}_", 3)
                conn.execute(
                    """
                    INSERT INTO lineage_nodes(
                        node_id, epoch_id, question_id, branch_id, family_id, parent_node_id,
                        generation, node_status, triage_level, worktree_abs_path,
                        retained_candidate_id, retained_snapshot_abs_path, inplace_repair_count,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXPLORING', 'LEVEL_2_REPAIR', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        spawned_node_id,
                        int(node["epoch_id"]),
                        qid,
                        bid,
                        fid,
                        node_id,
                        int(node["generation"]) + 1,
                        wt_abs,
                        str(node["retained_candidate_id"] or ""),
                        str(node["retained_snapshot_abs_path"] or ""),
                        rep_count,
                        now,
                        now,
                    ),
                )

        elif tl == "LEVEL_4A":
            if not (barrier_proof_md or "").strip() or len(barrier_proof_md.strip()) < 15:
                raise FailClosedError(
                    ERR_INVARIANT,
                    "LEVEL_4A 必须提交硬反例与结构阻碍证明 barrier_proof_md（无严密反证禁止轻言放弃）",
                )
            if not obs_rows:
                raise FailClosedError(ERR_INVARIANT, "LEVEL_4A 阻碍证明必须绑定至少 1 条实测 [Obs###]")
            created_l2_id = _next_ledger_id(conn, "L2_FAILURE_RECORD")
            hook_sha = str(obs_rows[0]["domain_hook_sha256"])
            conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, method_family_id,
                    title, abstract_md, exact_refuted_scope_md, body_proof_or_code_md,
                    bound_obs_ids_json, domain_hook_sha256, created_at
                ) VALUES (?, ?, 'L2_FAILURE_RECORD', 'L4A_BARRIER_PROOF', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_l2_id,
                    qid,
                    fid,
                    f"[{qid}] {fid} 结构阻碍证明 (Level 4a)",
                    f"分支 {bid} 在 {qid} 证实路径不可行边界：{barrier_proof_md.strip()}",
                    barrier_proof_md.strip(),
                    str(node["column_a_facts_md"]),
                    json.dumps([str(r["obs_id"]) for r in obs_rows], ensure_ascii=False),
                    hook_sha,
                    now,
                ),
            )
            conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE config_id = 'active'", (now,))
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'CLOSED', triage_level = ?, updated_at = ? WHERE node_id = ?",
                (tl, now, node_id),
            )

        elif tl == "LEVEL_4B":
            if not (reopen_condition or "").strip():
                raise FailClosedError(ERR_INVALID_INPUT, "LEVEL_4B 条件阻塞必须明确填写 reopen_condition 以供 Ready Queue 唤醒")
            conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE config_id = 'active'", (now,))
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'BLOCKED_L4B', triage_level = ?, reopen_condition = ?, updated_at = ? WHERE node_id = ?",
                (tl, reopen_condition.strip(), now, node_id),
            )

        else:
            # ROUTINE_CONTINUATION 或 LEVEL_3 特异保护
            conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = consecutive_non_l1_handoffs + 1, updated_at = ? WHERE config_id = 'active'", (now,))
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'CLOSED', triage_level = ?, updated_at = ? WHERE node_id = ?",
                (tl, now, node_id),
            )
            spawned_node_id = _next_id(conn, "lineage_nodes", "node_id", f"node_{qid.lower()}_", 3)
            conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, epoch_id, question_id, branch_id, family_id, parent_node_id,
                    generation, node_status, triage_level, stagnation_lane, worktree_abs_path,
                    retained_candidate_id, retained_snapshot_abs_path, inplace_repair_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    spawned_node_id,
                    int(node["epoch_id"]),
                    qid,
                    bid,
                    fid,
                    node_id,
                    int(node["generation"]) + 1,
                    "LEVEL_3_PROTECTED" if tl == "LEVEL_3" else "",
                    str(node["stagnation_lane"] or ""),
                    wt_abs,
                    str(node["retained_candidate_id"] or ""),
                    str(node["retained_snapshot_abs_path"] or ""),
                    now,
                    now,
                ),
            )

        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id=f"triage:{tl}:{act}",
            edge_type="USED_TOOL",
            metadata={"review_id": created_review_id, "l2_id": created_l2_id, "spawned_node_id": spawned_node_id},
        )

    guidance = (
        f"分诊 {tl}/{act} 已原子落库。"
        + (f" 已创建盲审单 {created_review_id}，等待 library_verifier 审理。" if created_review_id else "")
        + (f" 已自动生成内藏失败雷达 {created_l2_id}。" if created_l2_id else "")
        + (f" 已派生下代探索节点 {spawned_node_id}，待伴随助手合成看板后启动。" if spawned_node_id else "")
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="triage_node",
        node_id=spawned_node_id or node_id,
        question_id=qid,
        next_step_guidance=guidance,
        data={
            "triaged_node_id": node_id,
            "triage_level": tl,
            "action": act,
            "created_review_id": created_review_id,
            "created_l2_id": created_l2_id,
            "spawned_node_id": spawned_node_id,
            "restored_snapshot_files": restored_files,
        },
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
    source_l3_id: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "fork_branch", session_id=session_id)
    if fork_mode not in VALID_FORK_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 fork_mode={fork_mode!r}，仅允许 {sorted(VALID_FORK_MODES)}")
    if not target_family_id.strip():
        raise FailClosedError(ERR_INVALID_INPUT, "target_family_id 不能为空")

    ep = conn.execute("SELECT epoch_id, contracts_json, required_questions_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    epoch_id = int(ep["epoch_id"]) if ep else 1
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    req_qs = json.loads(ep["required_questions_json"]) if ep and ep["required_questions_json"] else []

    dep_status = get_question_dependency_status(conn, contracts=contracts, required_questions=req_qs)
    q_dep = dep_status.get(question_id, {})
    if not q_dep.get("unlocked", True):
        raise FailClosedError(
            ERR_LOCKED,
            f"子题前置依赖未满足 (depends_on_questions={q_dep.get('depends_on_questions')}): 尚缺前置子题 {q_dep.get('unmet_dependencies')} 的 active L3_VERIFIED 结论，暂缓派发！",
        )

    fam = conn.execute(
        "SELECT * FROM method_families WHERE epoch_id = ? AND question_id = ? AND family_id = ?",
        (epoch_id, question_id, target_family_id),
    ).fetchone()
    if fam is None:
        raise FailClosedError(ERR_NOT_FOUND, f"方法学派 {target_family_id!r} 尚未在子题 {question_id} 登记")

    parent_row = None
    self_branch_id = ""
    if parent_node_id:
        parent_row = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (parent_node_id,)).fetchone()
        if parent_row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"父节点 {parent_node_id!r} 不存在")
        self_branch_id = str(parent_row["branch_id"])

    # 根治 P19：查重强加 WHERE branch_id != :self（绝不把当前分支自身当成兄弟撞车）
    sibling_nodes = conn.execute(
        """
        SELECT DISTINCT branch_id, family_id FROM lineage_nodes
        WHERE question_id = ? AND branch_id != ? AND node_status IN ('EXPLORING', 'AWAITING_TRIAGE')
        """,
        (question_id, self_branch_id),
    ).fetchall()
    if fork_mode == "orthogonal" and any(str(s["family_id"]) == target_family_id for s in sibling_nodes):
        raise FailClosedError(
            ERR_CONFLICT,
            f"正交派生撞车拦截：已有其他活跃分支正在探索 {target_family_id!r}（已排除自身分支 {self_branch_id!r}）",
        )

    if fork_mode == "cross_pollinate":
        if not source_l3_id:
            raise FailClosedError(ERR_INVALID_INPUT, "cross_pollinate 分叉必须指定已证实的 source_l3_id")
        l3 = conn.execute(
            "SELECT entry_id FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND ledger_status = 'active'",
            (source_l3_id,),
        ).fetchone()
        if l3 is None:
            raise FailClosedError(ERR_NOT_FOUND, f"交叉授粉引理 {source_l3_id!r} 不存在或未通过盲审 L3")

    branch_idx = int(
        conn.execute("SELECT COUNT(DISTINCT branch_id) AS cnt FROM lineage_nodes WHERE question_id = ?", (question_id,)).fetchone()["cnt"]
        or 0
    ) + 1
    new_branch_id = f"b_{question_id.lower()}_{re.sub(r'[^a-zA-Z0-9]+', '_', target_family_id)[:18]}_{branch_idx}"

    ws = Path(os.path.realpath(workspace_root))
    wt_dir = ws / "worktrees" / new_branch_id
    (wt_dir / "src").mkdir(parents=True, exist_ok=True)
    (wt_dir / "tools").mkdir(parents=True, exist_ok=True)

    # lateral 继承父快照物理代码，orthogonal 净室起跑（排除敏感文件）
    if fork_mode in ("lateral", "cross_pollinate") and parent_row is not None:
        src_snap = str(parent_row["retained_snapshot_abs_path"] or parent_row["worktree_abs_path"] or "")
        if src_snap and Path(src_snap).is_dir():
            for item in Path(src_snap).rglob("*"):
                if item.is_file() and item.name != "_snapshot_meta.json" and "__pycache__" not in item.parts:
                    rel = item.relative_to(Path(src_snap))
                    dest = wt_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

    now = utc_now_iso()
    parent_brief = ""
    if fork_mode == "cross_pollinate" and source_l3_id:
        parent_brief = f"### 交叉授粉嫁接提示\n来自 Stage 2 横向提名：引入已验证原语 {source_l3_id} 解决瓶颈。\n"

    with rw_immediate_tx(conn):
        new_node_id = _next_id(conn, "lineage_nodes", "node_id", f"node_{question_id.lower()}_", 3)
        if parent_row is not None and str(parent_row["node_status"]) == "BLOCKED_L4B":
            conn.execute("UPDATE lineage_nodes SET node_status = 'CLOSED', updated_at = ? WHERE node_id = ?", (now, parent_node_id))
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, epoch_id, question_id, branch_id, family_id, parent_node_id,
                generation, node_status, worktree_abs_path, will_md, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?)
            """,
            (
                new_node_id,
                epoch_id,
                question_id,
                new_branch_id,
                target_family_id,
                parent_node_id,
                1 if parent_row is None else int(parent_row["generation"]) + 1,
                str(wt_dir),
                parent_brief,
                now,
                now,
            ),
        )
        record_fact_edge(
            conn,
            src_id=new_node_id,
            dst_id=f"fork:{fork_mode}:{target_family_id}",
            edge_type="USED_TOOL",
            metadata={"parent_node_id": parent_node_id, "source_l3_id": source_l3_id},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="fork_branch",
        node_id=new_node_id,
        question_id=question_id,
        next_step_guidance=f"已开辟新分支 {new_branch_id}（工作树 {wt_dir}）与探索节点 {new_node_id}，伴随助手可调 save_lineage_briefing 准备看板。",
        data={
            "node_id": new_node_id,
            "branch_id": new_branch_id,
            "question_id": question_id,
            "family_id": target_family_id,
            "fork_mode": fork_mode,
            "worktree_abs_path": str(wt_dir),
        },
    )


def tool_dispatch_stagnation_five_lanes(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str,
    lane_assignments: list[dict[str, str]],
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "dispatch_stagnation_five_lanes", session_id=session_id)
    if not isinstance(lane_assignments, list) or not lane_assignments:
        raise FailClosedError(ERR_INVALID_INPUT, "lane_assignments 不能为空")

    seen_branches: set[str] = set()
    now = utc_now_iso()
    updated: list[dict[str, str]] = []
    with rw_immediate_tx(conn):
        for item in lane_assignments:
            bid = str(item.get("branch_id") or "").strip()
            lane = str(item.get("lane") or "").strip().upper()
            directive = str(item.get("directive") or "").strip()
            if not bid or lane not in VALID_STAGNATION_LANES or not directive:
                raise FailClosedError(
                    ERR_INVALID_INPUT,
                    f"车道分配项格式非法: {item!r}（lane 仅限 {sorted(VALID_STAGNATION_LANES)}）",
                )
            if bid in seen_branches:
                raise FailClosedError(ERR_CONFLICT, f"同一分支 {bid!r} 不可重复分配车道")
            seen_branches.add(bid)
            cur = conn.execute(
                """
                UPDATE lineage_nodes
                SET stagnation_lane = ?, will_md = CASE WHEN will_md = '' THEN ? ELSE will_md || char(10) || ? END, updated_at = ?
                WHERE branch_id = ? AND question_id = ? AND node_status IN ('EXPLORING', 'BLOCKED_L4B')
                """,
                (lane, f"[Stagnation-{lane}] {directive}", f"[Stagnation-{lane}] {directive}", now, bid, question_id),
            )
            if cur.rowcount == 0:
                raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id} 下无活跃或阻塞分支 {bid!r}")
            updated.append({"branch_id": bid, "lane": lane, "directive": directive})
        conn.execute("UPDATE epoch_config SET consecutive_non_l1_handoffs = 0, updated_at = ? WHERE config_id = 'active'", (now,))

    return build_tool_receipt(
        conn=conn,
        tool_name="dispatch_stagnation_five_lanes",
        question_id=question_id,
        next_step_guidance="五车道重编已落库并重置停滞计数，控制面将按新方向唤醒对应探索双人组。",
        data={"question_id": question_id, "assigned": updated},
    )


