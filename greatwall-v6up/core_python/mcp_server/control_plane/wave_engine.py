"""图书馆宏观大外环引擎（第 1 拍代码硬对账 -> 第 2 拍圆桌对抗 -> 第 3 拍总览 -> 第 4 拍树结构调整落地）。

严格落实顶层裁决 5：
- 波次节拍：`completed_nodes_since_last_conference >= max(2, active_branches * 2)`；
- 已封存参会助手 < 2 名时跳过第 2 拍红蓝互辩，直入 `SURVEY_REFRESHING`；
- 旁路双供体合体（`SPAWN_SYNTHESIS`）绝不污染原纯血分支，次供体快照只读挂载至 `.greatwall_donors/<node_id>/`；
- 冷静裁剪（`HIBERNATE`）严守 2 班岗成长保护期与时间线单调复核（刚过审新 L3 的分支自动跳过不误裁）。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..db_schema import (
    ALLOWED_WAVE_VERDICT_ACTIONS,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from ..mcp_core_helpers import load_runtime_config
from .effects_outbox import enqueue_runtime_effect
from .lifecycle_ops import submit_works_ticket
from .proposals import create_control_proposal
from .subproblem_locks import evaluate_subproblem_locks, get_subproblem_active_spec_revision
from .workspace_sync import (
    restore_retained_candidate_snapshot,
    sync_approved_public_inputs,
    sync_public_instruments_and_skills_to_worktree,
)


def build_wave_hard_ledger(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    """第 1 拍：纯 Python 代码拉取铁面《本波硬账本》（所有未过空白沙箱宣称零权重）。"""
    qid = str(question_id)
    qrow = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    active_rev = int(qrow["active_spec_revision"] or 0) if qrow else 0

    active_branches = [
        dict(r)
        for r in conn.execute(
            """
            SELECT branch_id, family_id, branch_kind, MAX(generation) AS latest_gen,
                   MIN(protection_generations_left) AS protection_left
            FROM lineage_nodes
            WHERE question_id = ?
              AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
            GROUP BY branch_id
            """,
            (qid,),
        ).fetchall()
    ]
    l3_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, l3_entry_kind, goal_coverage, publish_tier, verified_spec_revision, title, created_at
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
            ORDER BY created_at DESC
            """,
            (qid,),
        ).fetchall()
    ]
    l2_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, l2_category, title, exact_refuted_scope_md, created_at
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L2_FAILURE_RECORD' AND is_active = 1
            ORDER BY created_at DESC
            """,
            (qid,),
        ).fetchall()
    ]
    open_gaps = [
        dict(r)
        for r in conn.execute(
            "SELECT gap_id, blocked_node_id, formal_statement_md, created_at FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN' ORDER BY created_at ASC",
            (qid,),
        ).fetchall()
    ]
    instruments = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, instrument_role, health_status FROM instruments WHERE is_active = 1 AND (question_id = ? OR question_id = 'ALL')",
            (qid,),
        ).fetchall()
    ]

    return {
        "question_id": qid,
        "active_spec_revision": active_rev,
        "completed_waves": int(qrow["completed_waves"] or 0) if qrow else 0,
        "completed_nodes_since_last_conference": int(qrow["completed_nodes_since_last_conference"] or 0) if qrow else 0,
        "completed_nodes_since_last_l3": int(qrow["completed_nodes_since_last_l3"] or 0) if qrow else 0,
        "spent_tokens": int(qrow["spent_tokens"] or 0) if qrow else 0,
        "question_token_budget": int(qrow["question_token_budget"] or 0) if qrow else 0,
        "active_branches": active_branches,
        "verified_l3_count": len(l3_rows),
        "verified_l3": l3_rows,
        "refuted_l2_count": len(l2_rows),
        "refuted_l2": l2_rows,
        "open_lemma_gaps": open_gaps,
        "active_instruments": instruments,
    }


def _collect_sealed_conference_participants(conn: sqlite3.Connection, question_id: str) -> list[dict[str, Any]]:
    """收集各活跃分支最近一代已封存交班记录的伴随助手（不打断在跑慢分支）。"""
    qid = str(question_id)
    branch_rows = conn.execute(
        """
        SELECT DISTINCT branch_id
        FROM lineage_nodes
        WHERE question_id = ?
          AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B')
        """,
        (qid,),
    ).fetchall()
    participants: list[dict[str, Any]] = []
    for br in branch_rows:
        bid = str(br["branch_id"])
        sealed = conn.execute(
            """
            SELECT node_id, branch_id, family_id, generation, branch_kind, companion_session_id,
                   briefing_sealed_at, mechanism_summary, evidence_grade, column_a_facts_md
            FROM lineage_nodes
            WHERE question_id = ? AND branch_id = ? AND briefing_sealed_at IS NOT NULL
            ORDER BY generation DESC, created_at DESC LIMIT 1
            """,
            (qid, bid),
        ).fetchone()
        if sealed is None:
            continue
        live_in_flight = conn.execute(
            "SELECT node_id, generation FROM lineage_nodes WHERE branch_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING') ORDER BY generation DESC LIMIT 1",
            (bid,),
        ).fetchone()
        participants.append(
            {
                "branch_id": bid,
                "node_id": str(sealed["node_id"]),
                "family_id": str(sealed["family_id"] or ""),
                "generation": int(sealed["generation"] or 1),
                "branch_kind": str(sealed["branch_kind"] or "PURE"),
                "companion_session_id": str(sealed["companion_session_id"] or f"gw-comp-{sealed['node_id']}"),
                "mechanism_summary": str(sealed["mechanism_summary"] or ""),
                "evidence_grade": str(sealed["evidence_grade"] or "NONE"),
                "slow_branch_snapshot": bool(live_in_flight and str(live_in_flight["node_id"]) != str(sealed["node_id"])),
                "in_flight_generation": int(live_in_flight["generation"]) if live_in_flight else None,
            }
        )
    return participants


def check_and_open_wave_conference(conn: sqlite3.Connection, *, question_id: str, force: bool = False) -> dict[str, Any] | None:
    """检查子题是否达到宏观大外环触发节拍；达标则原子建会并决定进 ROUND_1_CRITIQUE 或跳过互辩直入 SURVEY_REFRESHING。"""
    qid = str(question_id)
    qrow = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    if qrow is None or str(qrow["dispatch_state"]) != "DISPATCHING":
        return None

    # 已有进行中的会议时不重复开会
    in_flight = conn.execute(
        """
        SELECT conference_id, status FROM wave_conferences
        WHERE question_id = ? AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')
        LIMIT 1
        """,
        (qid,),
    ).fetchone()
    if in_flight is not None:
        return None

    cfg = load_runtime_config()
    mult = int(cfg.get("wave_conference_branch_multiplier", 2))
    min_nodes = int(cfg.get("wave_conference_min_completed_nodes", 2))

    active_branch_cnt = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT branch_id) AS cnt FROM lineage_nodes
            WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
            """,
            (qid,),
        ).fetchone()["cnt"]
        or 0
    )
    threshold = max(min_nodes, active_branch_cnt * max(1, mult))
    completed_since = int(qrow["completed_nodes_since_last_conference"] or 0)
    if not force and completed_since < threshold:
        return None

    participants = _collect_sealed_conference_participants(conn, qid)
    # 裁决 5：已封存参会助手 < 2 名时跳过第 2 拍红蓝互辩，直入 SURVEY_REFRESHING
    init_status = "ROUND_1_CRITIQUE" if len(participants) >= 2 else "SURVEY_REFRESHING"
    # 独立递增会议序号（与成功完成波次 completed_waves 解耦，驳回 CANCELLED/失败 FAILED 后再开会绝不撞 UNIQUE(question_id, wave_no)）
    max_seq_row = conn.execute(
        "SELECT COALESCE(MAX(wave_no), 0) AS max_no FROM wave_conferences WHERE question_id = ?",
        (qid,),
    ).fetchone()
    wave_no = max(int(qrow["completed_waves"] or 0), int(max_seq_row["max_no"] or 0)) + 1
    conf_id = f"wc_{qid.lower()}_w{wave_no}_{uuid.uuid4().hex[:6]}"
    chair_sid = f"gw-chair-{conf_id}"
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO wave_conferences(
                conference_id, question_id, wave_no, status, participant_nodes_json,
                critiques_ledger_json, minutes_md, chair_session_id, created_at
            ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?)
            """,
            (
                conf_id,
                qid,
                wave_no,
                init_status,
                json.dumps(participants, ensure_ascii=False),
                "" if init_status == "ROUND_1_CRITIQUE" else "（本波已封存分支不足 2 条，跳过多方互辩直入总览刷新与宏观开拓）",
                chair_sid,
                now,
            ),
        )
        conn.execute(
            "UPDATE subproblem_runtime_state SET completed_nodes_since_last_conference = 0, updated_at = ? WHERE question_id = ?",
            (now, qid),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"wave:{conf_id}",
            kind="RUN_WAVE_CONFERENCE" if init_status == "ROUND_1_CRITIQUE" else "REFRESH_LIVING_SURVEY",
            target_type="QUESTION",
            target_id=qid,
            target_generation=int(qrow["dispatch_generation"] or 1),
            external_handle_id=chair_sid,
            payload={"conference_id": conf_id, "wave_no": wave_no, "initial_status": init_status},
        )

    return {
        "opened": True,
        "conference_id": conf_id,
        "question_id": qid,
        "wave_no": wave_no,
        "status": init_status,
        "participant_count": len(participants),
        "chair_session_id": chair_sid,
    }


def append_conference_statement(
    conn: sqlite3.Connection,
    *,
    conference_id: str,
    node_id: str,
    round_no: int,
    statement_md: str,
    target_node_ids: list[str] | None = None,
) -> dict[str, Any]:
    """已封存伴随助手在圆桌第 1/2 轮提交点对点红蓝交锋发言。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    st = str(conf["status"])
    rno = int(round_no)
    if rno == 1 and st != "ROUND_1_CRITIQUE":
        raise FailClosedError(ERR_LOCKED, f"会议 {conference_id!r} 当前为 {st}，不接受第 1 轮发言")
    if rno == 2 and st != "ROUND_2_REBUTTAL":
        raise FailClosedError(ERR_LOCKED, f"会议 {conference_id!r} 当前为 {st}，不接受第 2 轮辩护")
    if rno not in (1, 2):
        raise FailClosedError(ERR_INVALID_INPUT, "圆桌仅允许第 1 轮或第 2 轮发言")

    clean_stmt = str(statement_md or "").strip()
    if len(clean_stmt) < 20:
        raise FailClosedError(ERR_INVALID_INPUT, "圆桌发言至少 20 字，须直指实质冲突或互补点")

    participants = json.loads(conf["participant_nodes_json"] or "[]")
    valid_nids = {str(p["node_id"]) for p in participants}
    if str(node_id) not in valid_nids:
        raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 不在本次圆桌参会名单中")

    ledger = json.loads(conf["critiques_ledger_json"] or "[]")
    now = utc_now_iso()
    ledger.append(
        {
            "round": rno,
            "node_id": str(node_id),
            "target_node_ids": [str(x).strip() for x in (target_node_ids or []) if str(x).strip()],
            "statement_md": clean_stmt[:1800],
            "at": now,
        }
    )

    # 若第 1 轮全员发言完毕，自动推进至 ROUND_2_REBUTTAL
    next_status = st
    if rno == 1:
        r1_speakers = {str(item["node_id"]) for item in ledger if int(item.get("round", 0)) == 1}
        if valid_nids.issubset(r1_speakers):
            next_status = "ROUND_2_REBUTTAL"

    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE wave_conferences SET critiques_ledger_json = ?, status = ? WHERE conference_id = ?",
            (json.dumps(ledger, ensure_ascii=False), next_status, str(conference_id)),
        )

    return {
        "conference_id": str(conference_id),
        "round": rno,
        "status": next_status,
        "total_statements": len(ledger),
    }


def _mount_secondary_donor_readonly(
    conn: sqlite3.Connection,
    *,
    secondary_node_id: str,
    target_worktree: Path,
) -> str:
    """将次供体节点快照只读拷贝挂载到 `.greatwall_donors/<secondary_node_id>/`（绝不涂改原纯血分支）。"""
    sec = conn.execute(
        "SELECT node_id, retained_snapshot_abs_path, worktree_abs_path FROM lineage_nodes WHERE node_id = ?",
        (secondary_node_id,),
    ).fetchone()
    if sec is None:
        raise FailClosedError(ERR_NOT_FOUND, f"次供体节点 {secondary_node_id!r} 不存在")
    snap_raw = str(sec["retained_snapshot_abs_path"] or "").strip()
    wt_raw = str(sec["worktree_abs_path"] or "").strip()
    src = Path(snap_raw) if (snap_raw and Path(snap_raw).is_dir()) else (Path(wt_raw) if (wt_raw and Path(wt_raw).is_dir()) else None)
    donor_dir = target_worktree / ".greatwall_donors" / secondary_node_id
    donor_dir.mkdir(parents=True, exist_ok=True)
    if src is not None:
        for item in src.iterdir():
            if item.name in (".git", "__pycache__", ".venv", "inputs", ".greatwall_donors"):
                continue
            dst = donor_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"), dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item, dst)
        for fp in donor_dir.rglob("*"):
            if fp.is_file():
                try:
                    os.chmod(fp, 0o444)
                except OSError:
                    pass
    return donor_dir.relative_to(target_worktree).as_posix()


def execute_approved_wave_verdict(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    conference_id: str,
) -> dict[str, Any]:
    """按时间线单调铁律与成长保护期护栏，落地执行宏观大外环 6 类树结构调整单。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    if str(conf["status"]) not in ("ADJUDICATING", "PENDING_HUMAN_APPROVAL"):
        raise FailClosedError(ERR_CONFLICT, f"会议 {conference_id!r} 当前状态为 {conf['status']}，无法执行裁决落地")

    qid = str(conf["question_id"])
    verdict = json.loads(conf["verdict_json"] or "{}")
    actions = verdict.get("actions") if isinstance(verdict, dict) else []
    if not isinstance(actions, list):
        actions = []

    p0 = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    shared_rels = json.loads(p0["shared_inputs_json"] or "[]") if p0 else []
    active_rev = get_subproblem_active_spec_revision(conn, qid)
    now = utc_now_iso()

    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    with rw_immediate_tx(conn):
        for act_obj in actions:
            if not isinstance(act_obj, dict):
                continue
            kind = str(act_obj.get("action") or "").strip().upper()
            if kind not in ALLOWED_WAVE_VERDICT_ACTIONS:
                skipped.append({"action": kind, "reason": "unknown_action"})
                continue

            if kind == "OPEN_NEW_BRANCH":
                fid = str(act_obj.get("family_id") or f"fam_{qid.lower()}_{uuid.uuid4().hex[:6]}").strip()
                sig = str(act_obj.get("mechanism_signature") or act_obj.get("rationale") or "大外环定向开拓新学派").strip()
                contrast = str(act_obj.get("orthogonal_contrast") or "针对全局总览明确缺口正交开拓").strip()
                new_bid = f"b_{qid.lower()}_{fid[:10]}_{uuid.uuid4().hex[:5]}"
                new_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
                wt_dir = Path(os.path.realpath(workspace_root)) / "worktrees" / new_bid
                wt_dir.mkdir(parents=True, exist_ok=True)
                sync_approved_public_inputs(workspace_root, wt_dir, shared_rels, spec_revision=active_rev, question_id=qid)
                sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO method_families(family_id, question_id, mechanism_signature, orthogonal_contrast, family_status, created_at)
                    VALUES (?, ?, ?, ?, 'ACTIVE', ?)
                    """,
                    (fid, qid, sig[:240], contrast[:240], now),
                )
                conn.execute(
                    """
                    INSERT INTO lineage_nodes(
                        node_id, question_id, branch_id, family_id, generation,
                        branch_kind, protection_generations_left, companion_session_id,
                        node_status, worktree_abs_path, mechanism_summary, will_md, spec_revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, 'PURE', 2, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?)
                    """,
                    (new_nid, qid, new_bid, fid, f"gw-comp-{new_nid}", str(wt_dir), sig[:99], str(act_obj.get("gap_directive_md") or sig), active_rev, now, now),
                )
                executed.append({"action": kind, "branch_id": new_bid, "node_id": new_nid, "family_id": fid, "worktree_abs_path": str(wt_dir)})

            elif kind == "PROTECT":
                src_nid = str(act_obj.get("source_node_id") or "").strip()
                src = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ? AND question_id = ?", (src_nid, qid)).fetchone()
                if src is None:
                    skipped.append({"action": kind, "source_node_id": src_nid, "reason": "node_not_found"})
                    continue
                new_bid = f"b_{qid.lower()}_prot_{uuid.uuid4().hex[:5]}"
                new_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
                wt_dir = Path(os.path.realpath(workspace_root)) / "worktrees" / new_bid
                wt_dir.mkdir(parents=True, exist_ok=True)
                snap_raw = str(src["retained_snapshot_abs_path"] or "").strip()
                if snap_raw and Path(snap_raw).is_dir():
                    restore_retained_candidate_snapshot(snap_raw, str(wt_dir))
                sync_approved_public_inputs(workspace_root, wt_dir, shared_rels, spec_revision=active_rev, question_id=qid)
                sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir)
                conn.execute(
                    """
                    INSERT INTO lineage_nodes(
                        node_id, question_id, branch_id, family_id, parent_node_id, generation,
                        branch_kind, protection_generations_left, companion_session_id,
                        node_status, worktree_abs_path, retained_snapshot_abs_path,
                        mechanism_summary, will_md, spec_revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, 'PROTECTED', 2, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_nid,
                        qid,
                        new_bid,
                        str(src["family_id"] or ""),
                        src_nid,
                        f"gw-comp-{new_nid}",
                        str(wt_dir),
                        snap_raw or None,
                        str(act_obj.get("rationale") or src["mechanism_summary"] or "反常保护分叉")[:99],
                        str(act_obj.get("rationale") or ""),
                        active_rev,
                        now,
                        now,
                    ),
                )
                executed.append({"action": kind, "branch_id": new_bid, "node_id": new_nid, "source_node_id": src_nid})

            elif kind == "SPAWN_SYNTHESIS":
                pri_nid = str(act_obj.get("primary_donor_node_id") or "").strip()
                sec_nid = str(act_obj.get("secondary_donor_node_id") or "").strip()
                pri = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ? AND question_id = ?", (pri_nid, qid)).fetchone()
                sec = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ? AND question_id = ?", (sec_nid, qid)).fetchone()
                if pri is None or sec is None:
                    skipped.append({"action": kind, "reason": "donor_not_found"})
                    continue
                budget = max(1, int(act_obj.get("budget_nodes") or conf["synthesis_budget_nodes"] or 2))
                new_bid = f"b_{qid.lower()}_syn_{uuid.uuid4().hex[:5]}"
                new_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
                wt_dir = Path(os.path.realpath(workspace_root)) / "worktrees" / new_bid
                wt_dir.mkdir(parents=True, exist_ok=True)
                pri_snap = str(pri["retained_snapshot_abs_path"] or "").strip()
                if pri_snap and Path(pri_snap).is_dir():
                    restore_retained_candidate_snapshot(pri_snap, str(wt_dir))
                donor_rel = _mount_secondary_donor_readonly(conn, secondary_node_id=sec_nid, target_worktree=wt_dir)
                sync_approved_public_inputs(workspace_root, wt_dir, shared_rels, spec_revision=active_rev, question_id=qid)
                sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir)
                goal_txt = str(act_obj.get("synthesis_goal_md") or act_obj.get("rationale") or "旁路双供体融合验证")
                conn.execute(
                    """
                    INSERT INTO lineage_nodes(
                        node_id, question_id, branch_id, family_id, parent_node_id, generation,
                        branch_kind, protection_generations_left, branch_budget_nodes_left,
                        companion_session_id, secondary_donor_node_id,
                        node_status, worktree_abs_path, retained_snapshot_abs_path,
                        mechanism_summary, will_md, spec_revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, 'SYNTHESIS', 2, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_nid,
                        qid,
                        new_bid,
                        str(pri["family_id"] or ""),
                        pri_nid,
                        budget,
                        f"gw-comp-{new_nid}",
                        sec_nid,
                        str(wt_dir),
                        pri_snap or None,
                        goal_txt[:99],
                        f"[Synthesis Target] 主供体={pri_nid}, 次供体只读挂载={donor_rel}。目标：{goal_txt}",
                        active_rev,
                        now,
                        now,
                    ),
                )
                executed.append(
                    {
                        "action": kind,
                        "branch_id": new_bid,
                        "node_id": new_nid,
                        "primary_donor_node_id": pri_nid,
                        "secondary_donor_node_id": sec_nid,
                        "donor_mount_rel": donor_rel,
                    }
                )

            elif kind == "HIBERNATE":
                target_bid = str(act_obj.get("branch_id") or "").strip()
                live_node = conn.execute(
                    """
                    SELECT * FROM lineage_nodes
                    WHERE question_id = ? AND branch_id = ?
                      AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE')
                    ORDER BY generation DESC LIMIT 1
                    """,
                    (qid, target_bid),
                ).fetchone()
                if live_node is None:
                    skipped.append({"action": kind, "branch_id": target_bid, "reason": "no_live_node"})
                    continue
                # 成长保护期护栏：保护期内严禁裁撤
                if int(live_node["protection_generations_left"] or 0) > 0:
                    skipped.append({"action": kind, "branch_id": target_bid, "reason": "protected_by_growth_window"})
                    continue
                # 时间线单调防误裁：若该分支自会议开始后刚新过审了 L3，自动跳过不误裁
                fresh_l3 = conn.execute(
                    """
                    SELECT 1 FROM internal_research_ledger l
                    JOIN review_queue r ON r.review_id = l.verified_review_id
                    JOIN lineage_nodes n ON n.node_id = r.source_node_id
                    WHERE l.ledger_type = 'L3_VERIFIED' AND l.is_active = 1
                      AND n.branch_id = ? AND l.created_at >= ?
                    LIMIT 1
                    """,
                    (target_bid, str(conf["created_at"])),
                ).fetchone()
                if fresh_l3 is not None:
                    skipped.append({"action": kind, "branch_id": target_bid, "reason": "fresh_l3_verified_during_wave"})
                    continue
                conn.execute(
                    "UPDATE lineage_nodes SET node_status = 'SEALED', pending_handoff_reason = 'HIBERNATED_BY_WAVE_CONFERENCE', updated_at = ? WHERE node_id = ?",
                    (now, str(live_node["node_id"])),
                )
                enqueue_runtime_effect(
                    conn,
                    effect_key=f"drain:{live_node['node_id']}:hibernate:{conference_id}",
                    kind="DRAIN_AND_STOP_NODE",
                    target_type="NODE",
                    target_id=str(live_node["node_id"]),
                    target_generation=int(live_node["control_generation"] or 1),
                    payload={"reason": "HIBERNATED_BY_WAVE_CONFERENCE", "salvage_audit": bool(act_obj.get("salvage_audit", False))},
                    supersede_older_kinds=("SPAWN_PAIR",),
                )
                executed.append(
                    {
                        "action": kind,
                        "branch_id": target_bid,
                        "sealed_node_id": str(live_node["node_id"]),
                        "salvage_audit": bool(act_obj.get("salvage_audit", False)),
                    }
                )

            elif kind == "DISCRIMINATOR":
                tkt = submit_works_ticket(
                    conn,
                    question_id=qid,
                    ticket_type="DISCRIMINATOR",
                    instrument_id=act_obj.get("instrument_id"),
                    description=str(act_obj.get("description") or act_obj.get("rationale") or "圆桌定向鉴别探针需求"),
                    source=f"wave_conference:{conference_id}",
                )
                executed.append({"action": kind, "ticket_id": tkt["ticket_id"]})

            elif kind == "PAUSE_FOR_HUMAN":
                lock_res = evaluate_subproblem_locks(
                    conn,
                    question_id=qid,
                    semantic_saturation_requested=True,
                    saturation_reason_md=str(act_obj.get("rationale") or "宏观大外环确认明确缺口已穷尽"),
                )
                q_eval = (lock_res.get("evaluated") or [{}])[0]
                if q_eval.get("dispatch_state") == "PAUSED_SATURATED":
                    executed.append({"action": kind, "dispatch_state": "PAUSED_SATURATED"})
                else:
                    skipped.append({"action": kind, "reason": "min_commitment_window_not_met"})

        conn.execute(
            "UPDATE wave_conferences SET status = 'COMPLETED', completed_at = ? WHERE conference_id = ?",
            (now, str(conference_id)),
        )
        conn.execute(
            "UPDATE subproblem_runtime_state SET completed_waves = completed_waves + 1, updated_at = ? WHERE question_id = ?",
            (now, qid),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"chief:wave_done:{conference_id}",
            kind="NOTIFY_CHIEF",
            target_type="QUESTION",
            target_id=qid,
            payload={
                "event_category": "MILESTONE",
                "conference_id": str(conference_id),
                "question_id": qid,
                "executed_count": len(executed),
                "skipped_count": len(skipped),
            },
        )

    # 递增 completed_waves 后立即结算停工锁（锁三 max_waves 保险丝）
    lock_eval = evaluate_subproblem_locks(conn, question_id=qid)
    return {
        "conference_id": str(conference_id),
        "question_id": qid,
        "status": "COMPLETED",
        "executed": executed,
        "skipped": skipped,
        "subproblem_lock_eval": lock_eval,
    }


def mark_wave_conference_failed(
    conn: sqlite3.Connection,
    *,
    conference_id: str,
    reason: str = "CIRCUIT_BREAKER_STALLED",
) -> dict[str, Any]:
    """将无进展/熔断的圆桌会议落库标记为 FAILED 并释放子题开会锁，同时通知 gw-chief。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    cur_status = str(conf["status"])
    if cur_status in ("COMPLETED", "CANCELLED", "EXPIRED", "FAILED"):
        return {"conference_id": str(conference_id), "status": cur_status, "already_terminal": True}
    now = utc_now_iso()
    qid = str(conf["question_id"])
    note = str(reason or "CIRCUIT_BREAKER_STALLED")[:500]
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE wave_conferences
            SET status = 'FAILED',
                minutes_md = CASE WHEN minutes_md = '' THEN ? ELSE minutes_md || char(10) || ? END,
                completed_at = ?
            WHERE conference_id = ? AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')
            """,
            (f"[FAILED] {note}", f"[FAILED] {note}", now, str(conference_id)),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"chief:wave_fail:{conference_id}",
            kind="NOTIFY_CHIEF",
            target_type="QUESTION",
            target_id=qid,
            payload={
                "event_category": "BLOCK_ALERT",
                "conference_id": str(conference_id),
                "question_id": qid,
                "reason": "WAVE_CONFERENCE_FAILED",
                "detail": note,
            },
        )
    return {"conference_id": str(conference_id), "question_id": qid, "status": "FAILED", "reason": note}


def submit_wave_verdict_decision(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    conference_id: str,
    verdict_payload: dict[str, Any],
    rationale_md: str,
) -> dict[str, Any]:
    """第 4 拍裁决落地分流：WAVE_CONFIRM 或含 PAUSE_FOR_HUMAN 强制挂待人类拍板；AUTOPILOT 低风险动作自动落地。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    if str(conf["status"]) != "ADJUDICATING":
        raise FailClosedError(ERR_LOCKED, f"会议 {conference_id!r} 状态为 {conf['status']}，仅 ADJUDICATING 可提交裁决")

    actions = verdict_payload.get("actions") if isinstance(verdict_payload, dict) else None
    if not isinstance(actions, list):
        raise FailClosedError(ERR_INVALID_INPUT, "verdict_payload.actions 必须为动作数组")

    p0 = conn.execute("SELECT autonomy_mode FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    autonomy = str(p0["autonomy_mode"] or "WAVE_CONFIRM") if p0 else "WAVE_CONFIRM"
    has_high_risk_pause = any(str(a.get("action") or "").upper() == "PAUSE_FOR_HUMAN" for a in actions if isinstance(a, dict))
    need_human = autonomy != "AUTOPILOT" or has_high_risk_pause

    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE wave_conferences SET verdict_json = ? WHERE conference_id = ?",
            (json.dumps(verdict_payload, ensure_ascii=False), str(conference_id)),
        )
        if need_human:
            conn.execute(
                "UPDATE wave_conferences SET status = 'PENDING_HUMAN_APPROVAL' WHERE conference_id = ?",
                (str(conference_id),),
            )
            prop = create_control_proposal(
                conn,
                proposed_by="conference_chair",
                action_type="APPROVE_WAVE_VERDICT",
                target_id=str(conference_id),
                payload={"conference_id": str(conference_id), "question_id": str(conf["question_id"]), "actions": actions},
                rationale_md=rationale_md or f"子题 {conf['question_id']} 第 {conf['wave_no']} 波宏观大外环调整建议",
            )
            enqueue_runtime_effect(
                conn,
                effect_key=f"chief:wave_approval:{conference_id}",
                kind="NOTIFY_CHIEF",
                target_type="QUESTION",
                target_id=str(conf["question_id"]),
                payload={
                    "event_category": "MILESTONE",
                    "conference_id": str(conference_id),
                    "proposal_id": prop["proposal_id"],
                    "requires_human_approval": True,
                },
            )
            return {
                "conference_id": str(conference_id),
                "status": "PENDING_HUMAN_APPROVAL",
                "proposal_id": prop["proposal_id"],
                "autonomy_mode": autonomy,
            }

    return execute_approved_wave_verdict(conn, workspace_root=workspace_root, conference_id=str(conference_id))
