"""GreatWall v0.3 logistics_coordinator（后勤调度总管）4 个单一职责窄工具。

v0.3 变更：
- 裁决 6：彻底删除原 `dispatch_stagnation_five_lanes` 五车道工具（停滞与重构由宏观大外环承接）；
- 裁决 2：中观常规分诊交由控制面直落，`logistics_coordinator` 仅在建首批学派、聚拢告警、LEVEL_3 反常保护、孤儿返工续接与未归类疑难节点按需唤起；
- `fork_branch` 默认赋予 `protection_generations_left = 2` 成长保护期与确定性 `companion_session_id = gw-comp-<node_id>`。
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .control_plane_service import (
    check_branch_requires_satisfied,
    compute_family_concentration_alerts,
    compute_topology_and_revision_health,
    get_question_order_status,
    get_subproblem_active_spec_revision,
    restore_retained_candidate_snapshot,
    sync_approved_public_inputs,
    sync_public_instruments_and_skills_to_worktree,
)
from .db_schema import (
    ALLOWED_FORK_MODES,
    ERR_CONFLICT,
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
    load_runtime_config,
)
from .triage_core import execute_triage_core


def _validate_deterministic_requires(requires: list[str] | None) -> list[str]:
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
                f"非法 requires 条目 {req!r}：仅支持 'L3-###' 或 'OBS:<instrument_id>:PASS'",
            )
    return out


def tool_get_logistics_dashboard(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """纯查 SQLite (<50ms) 返回全卷或指定子题的方法族谱、分支占比、待分诊页、OPEN 悬赏缺口与聚拢告警。"""
    enforce_role_tool_permission(conn, caller_role, "get_logistics_dashboard", session_id=session_id)
    qf = str(question_id or "ALL").strip()

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    order_status = get_question_order_status(conn)
    conc_alerts = compute_family_concentration_alerts(conn)
    if qf.upper() != "ALL":
        conc_alerts = [a for a in conc_alerts if a["question_id"] == qf]

    where_q = "" if qf.upper() == "ALL" else "WHERE question_id = ?"
    where_q_and = "" if qf.upper() == "ALL" else "AND question_id = ?"
    params_q: tuple[Any, ...] = () if qf.upper() == "ALL" else (qf,)

    families = [dict(r) for r in conn.execute(f"SELECT * FROM method_families {where_q} ORDER BY question_id, family_id", params_q).fetchall()]
    triage_nodes = [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT node_id, question_id, branch_id, family_id, generation, spec_revision, mechanism_summary,
                   evidence_grade, candidate_rel_path, bound_obs_ids_json, revise_count,
                   inplace_repair_count, premise_revoked, column_a_facts_md, will_md
            FROM lineage_nodes
            WHERE node_status = 'AWAITING_TRIAGE' {where_q_and}
            ORDER BY updated_at ASC
            """,
            params_q,
        ).fetchall()
    ]
    ready_queue = [
        dict(r)
        for r in conn.execute(
            f"SELECT node_id, question_id, branch_id, family_id, spec_revision, reopen_condition, requires_json FROM lineage_nodes WHERE node_status = 'BLOCKED_L4B' {where_q_and} ORDER BY updated_at ASC",
            params_q,
        ).fetchall()
    ]
    open_gaps = [
        dict(r)
        for r in conn.execute(
            f"SELECT gap_id, question_id, blocked_node_id, formal_statement_md, verification_spec_md FROM open_lemma_gaps WHERE status = 'OPEN' {where_q_and} ORDER BY created_at ASC",
            params_q,
        ).fetchall()
    ]
    active_branches = [
        dict(r)
        for r in conn.execute(
            f"""
            SELECT DISTINCT question_id, branch_id, family_id, spec_revision, node_status,
                            branch_kind, protection_generations_left
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW') {where_q_and}
            """,
            params_q,
        ).fetchall()
    ]
    subproblem_states = [
        dict(r)
        for r in conn.execute(
            f"SELECT question_id, desired_state, dispatch_state, active_spec_revision, completed_nodes_since_last_conference FROM subproblem_runtime_state {where_q} ORDER BY question_id",
            params_q,
        ).fetchall()
    ]

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

    guidance_parts: list[str] = []
    if conc_alerts:
        guidance_parts.append(f"发现 {len(conc_alerts)} 条无豁免学派聚拢告警 (>50%)，请执行 fork_branch(fork_mode='orthogonal') 正交分流！")
    if orphaned_revs:
        guidance_parts.append(
            f"发现 {len(orphaned_revs)} 条孤儿盲审返工单（{[r['review_id'] for r in orphaned_revs]}），请调用 fork_branch(parent_node_id=source_node_id, fork_mode='lateral') 续接！"
        )
    if understaffed_qs:
        guidance_parts.append(
            f"子题 {[u['question_id'] for u in understaffed_qs]} 存在正交学派断代缺编，请按空闲槽位补齐多路 Worktree！"
        )
    if not guidance_parts:
        guidance_parts.append(
            f"当前待分诊 {len(triage_nodes)} 节点、活跃分支 {len(active_branches)} 条、OPEN 悬赏缺口 {len(open_gaps)} 条、已登记学派 {len(families)} 个。"
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="get_logistics_dashboard",
        question_id=qf,
        next_step_guidance=" ".join(guidance_parts),
        data={
            "parse0_goal_md": str(p0["goal_and_completion_md"]) if p0 else "",
            "latest_spec_revision": int(p0["latest_spec_revision"] or 0) if p0 else 0,
            "latest_ruling_summary_md": str(p0["latest_ruling_summary_md"] or "") if p0 else "",
            "required_questions": json.loads(p0["subquestions_json"]) if p0 else [],
            "subproblem_states": subproblem_states,
            "question_order_status": order_status,
            "slot_utilization": slot_util,
            "method_families": families,
            "active_branches": active_branches,
            "stalled_or_aborted_branches": stalled_branches,
            "orphaned_blind_review_revisions": orphaned_revs,
            "understaffed_questions": understaffed_qs,
            "family_concentration_alerts": conc_alerts,
            "awaiting_triage": triage_nodes,
            "ready_queue": ready_queue,
            "open_lemma_gaps": open_gaps,
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
    """登记底层数学/物理正交思想学派。"""
    enforce_role_tool_permission(conn, caller_role, "register_method_family", session_id=session_id)
    fid = str(family_id or "").strip()
    sig = str(mechanism_signature or "").strip()
    contrast = str(orthogonal_contrast or "").strip()
    if not fid or not sig or not contrast:
        raise FailClosedError(ERR_INVALID_INPUT, "family_id、mechanism_signature 与 orthogonal_contrast 均不能为空")

    if conn.execute("SELECT 1 FROM method_families WHERE family_id = ?", (fid,)).fetchone() is not None:
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
    blocking_gap_formal_statement: str | None = None,
) -> dict[str, Any]:
    """后勤疑难节点中观分诊工具（委托给确定性核心 execute_triage_core）。"""
    enforce_role_tool_permission(conn, caller_role, "triage_node", session_id=session_id, node_id=node_id)
    res = execute_triage_core(
        conn,
        workspace_root=workspace_root,
        session_id=session_id,
        node_id=node_id,
        assigned_family_id=assigned_family_id,
        triage_level=triage_level,
        action=action,
        rationale=rationale,
        barrier_proof_md=barrier_proof_md,
        reopen_condition=reopen_condition,
        blocking_gap_formal_statement=blocking_gap_formal_statement,
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="triage_node",
        question_id=res["question_id"],
        node_id=res["node_id"],
        next_step_guidance=res["guidance"],
        data=res["data"],
    )


from .control_plane.operator_policy import check_question_branch_quota


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
    """开启新探索分支（默认 2 班岗成长保护期、确定性 requires、WHERE branch_id != :self 查重、断代/返工快照继承）。"""
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

    check_question_branch_quota(conn, question_id, family_id=fid)

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
        if str(pnode["question_id"]) != str(question_id):
            raise FailClosedError(ERR_INVALID_INPUT, f"禁止跨题分叉：父节点属于 {pnode['question_id']!r} != {question_id!r}")
        parent_branch_id = str(pnode["branch_id"])
        parent_family_id = str(pnode["family_id"] or "")

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

    p0_row = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    shared_rels = json.loads(p0_row["shared_inputs_json"] or "[]") if p0_row else []
    active_spec_rev = get_subproblem_active_spec_revision(conn, question_id)
    mounted_inputs = sync_approved_public_inputs(
        workspace_root,
        wt_dir,
        shared_rels,
        spec_revision=active_spec_rev,
        question_id=question_id,
    )
    mounted_inputs.extend(sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir))

    cfg = load_runtime_config()
    default_prot = int(cfg.get("default_protection_generations", 2))
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        check_question_branch_quota(conn, question_id, family_id=fid)
        if str(fam["family_status"]) == "BLOCKED" and str(new_mechanism_note or "").strip():
            conn.execute("UPDATE method_families SET family_status = 'ACTIVE' WHERE family_id = ?", (fid,))
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, parent_node_id, generation, node_status,
                worktree_abs_path, retained_snapshot_abs_path, mechanism_summary, requires_json,
                revise_count, last_revision_requests_json, spec_revision,
                branch_kind, protection_generations_left, companion_session_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'PURE', ?, ?, ?, ?)
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
                active_spec_rev,
                default_prot,
                f"gw-comp-{new_nid}",
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
            f"新分支 {new_bid} ({new_nid}) 已建立（前置 requires 未满足项 {unmet}，暂锁本分支不影响同题兄弟分支）。"
            if not sat
            else f"新分支 {new_bid} ({new_nid}, status={initial_status}, 成长保护期 {default_prot} 代) 已就绪，将由伴随助手写行前看板并启动探索。"
        ),
        data={
            "question_id": question_id,
            "branch_id": new_bid,
            "node_id": new_nid,
            "family_id": fid,
            "fork_mode": mode_l,
            "node_status": initial_status,
            "protection_generations_left": default_prot,
            "companion_session_id": f"gw-comp-{new_nid}",
            "inherited_revision_requests": json.loads(inherited_rev_reqs_json),
            "worktree_abs_path": str(wt_dir),
            "mounted_public_inputs": mounted_inputs,
            "requires": clean_reqs,
            "requires_satisfied": sat,
            "unmet_requires": unmet,
        },
    )
