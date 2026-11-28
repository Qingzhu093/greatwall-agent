"""设施控制面子域：8 类宪章正门确认提案（control_proposals）、自主档位切换与单入口口径升版。

严格落实顶层裁决 1 & 4：
1. 落签采用乐观锁 `WHERE proposal_id = ? AND status = 'PENDING_HUMAN'`，双端点击 100% 幂等；
2. 仅允许 `human_ui` 或宿主真实确认来源落签，严禁任何大模型 MCP 工具自签；
3. `AMEND_RULING_DRAFT` 仅递增受影响子题的 `active_spec_revision`，改 Q1 不连坐 Q2；若受影响子题旧解不再满足新口径，同事务自动切回 `DISPATCHING` 重启攻关（保留 `PAUSED_HUMAN`）。
"""

from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ..db_schema import (
    ALLOWED_AUTONOMY_MODES,
    ALLOWED_PROPOSAL_ACTIONS,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .effects_outbox import enqueue_runtime_effect
from .lifecycle_ops import record_human_stop, submit_works_ticket
from .node_interventions import authorize_early_handoff
from .subproblem_locks import find_latest_spec_full_goal_l3, set_subproblem_state
from .wave_verdict_actions import PreparedBranch, prepare_wave_growth
from .workspace_sync import (
    sync_approved_public_inputs,
    sync_public_instruments_and_skills_to_worktree,
)


def set_autonomy_mode(
    conn: sqlite3.Connection,
    *,
    autonomy_mode: str,
    actor_source: str = "human_ui",
) -> dict[str, Any]:
    if actor_source not in ("human_ui", "chief_approved"):
        raise FailClosedError(ERR_AUTH, "切换自主档位仅限真实人类确认来源")
    mode_u = str(autonomy_mode or "").strip().upper()
    if mode_u not in ALLOWED_AUTONOMY_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 autonomy_mode={autonomy_mode!r}，仅允许 {sorted(ALLOWED_AUTONOMY_MODES)}")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        cur = conn.execute(
            "UPDATE parse0_contract SET autonomy_mode = ?, updated_at = ? WHERE contract_id = 'active'",
            (mode_u, now),
        )
        if cur.rowcount != 1:
            raise FailClosedError(ERR_NOT_FOUND, "尚未初始化 Parse 0 契约，无法切换自主档位")
    return {"autonomy_mode": mode_u, "updated_at": now, "actor_source": actor_source}


def create_control_proposal(
    conn: sqlite3.Connection,
    *,
    proposed_by: str,
    action_type: str,
    target_id: str,
    payload: dict[str, Any] | None,
    rationale_md: str,
) -> dict[str, Any]:
    """提交 8 类结构化提案单，并自动将同 (action_type, target_id) 旧待办置为 SUPERSEDED。"""
    act = str(action_type or "").strip().upper()
    if act not in ALLOWED_PROPOSAL_ACTIONS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法提案 action_type={action_type!r}，仅允许 {sorted(ALLOWED_PROPOSAL_ACTIONS)}")
    tid = str(target_id or "").strip()
    rat = str(rationale_md or "").strip()
    if not tid or len(rat) < 5:
        raise FailClosedError(ERR_INVALID_INPUT, "target_id 与 rationale_md（>=5 字）不能为空")

    pid = f"prop_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    payload_str = json.dumps(payload or {}, ensure_ascii=False)

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE control_proposals
            SET status = 'SUPERSEDED', resolved_at = ?
            WHERE action_type = ? AND target_id = ? AND status = 'PENDING_HUMAN'
            """,
            (now, act, tid),
        )
        conn.execute(
            """
            INSERT INTO control_proposals(
                proposal_id, proposed_by, action_type, target_id,
                payload_json, rationale_md, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PENDING_HUMAN', ?)
            """,
            (pid, str(proposed_by or "gw_chief"), act, tid, payload_str, rat, now),
        )

    return {
        "proposal_id": pid,
        "proposed_by": str(proposed_by or "gw_chief"),
        "action_type": act,
        "target_id": tid,
        "payload": payload or {},
        "rationale_md": rat,
        "status": "PENDING_HUMAN",
        "created_at": now,
    }


def apply_approved_ruling_amendment(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    affected_question_ids: list[str],
    ruling_markdown: str,
    summary_md: str = "",
) -> dict[str, Any]:
    """单入口口径修订落签（裁决 4）：
    - 全局 latest_spec_revision + 1 并冻结 ruling_revisions/v{N+1}/ 与工作区 rulings/ruling_v{N+1}.md；
    - 仅递增 affected_question_ids 对应子题的 active_spec_revision（改 Q1 绝对不连坐 Q2）；
    - 若受影响子题原本 STOPPED_SOLVED 且不再满足新口径，同事务自动切回 DISPATCHING；
    - 向受影响子题在途分支投递 NOTIFY_POLICY_CHANGED 温和热通知（绝不强杀在途旧口径分支）。
    """
    p0 = conn.execute(
        "SELECT subquestions_json, latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    if p0 is None:
        raise FailClosedError(ERR_NOT_FOUND, "尚未初始化 Parse 0 契约")

    all_qs = json.loads(p0["subquestions_json"] or "[]")
    target_qs = [str(q).strip() for q in (affected_question_ids or []) if str(q).strip()]
    if not target_qs or "ALL" in [q.upper() for q in target_qs]:
        target_qs = list(all_qs)
    else:
        invalid = [q for q in target_qs if all_qs and q not in all_qs]
        if invalid:
            raise FailClosedError(ERR_INVALID_INPUT, f"affected_question_ids 包含未登记子题: {invalid}")

    clean_md = str(ruling_markdown or "").strip()
    if not clean_md:
        raise FailClosedError(ERR_INVALID_INPUT, "ruling_markdown 不能为空")

    current_rev = int(p0["latest_spec_revision"] or 0)
    archived_rev = int(conn.execute("SELECT COALESCE(MAX(last_spec_revision),0) FROM epoch_archives").fetchone()[0])
    new_rev = max(current_rev, archived_rev) + 1
    now = utc_now_iso()
    ws = Path(os.path.realpath(workspace_root or os.getcwd()))
    rulings_dir = ws / "rulings"
    rulings_dir.mkdir(parents=True, exist_ok=True)
    ruling_filename = f"ruling_v{new_rev}_{'_'.join(target_qs)[:32]}.md"
    ruling_file = rulings_dir / ruling_filename
    header = f"# 补充裁决 v{new_rev}（受影响子题：{', '.join(target_qs)}）\n\n生效时间：{now}\n\n"
    ruling_file.write_text(header + clean_md + "\n", encoding="utf-8")

    # 冻结受控版本目录（仅继承上一受控已批准版本 + 本次新批准裁决，严禁扫入工作区未批准草稿）
    paths = resolve_storage_paths(workspace_root)
    rev_snap_dir = paths["ruling_revisions_dir"] / f"v{new_rev}"
    if rev_snap_dir.exists():
        shutil.rmtree(rev_snap_dir, ignore_errors=True)
    rev_snap_dir.mkdir(parents=True, exist_ok=True)

    manifest_files: dict[str, Any] = {}
    if current_rev > 0:
        prev_snap_dir = paths["ruling_revisions_dir"] / f"v{current_rev}"
        if prev_snap_dir.is_dir():
            prev_manifest_fp = prev_snap_dir / "_manifest.json"
            if prev_manifest_fp.is_file():
                try:
                    pm = json.loads(prev_manifest_fp.read_text(encoding="utf-8"))
                    if isinstance(pm, dict) and isinstance(pm.get("files"), dict):
                        manifest_files.update(pm["files"])
                except Exception:
                    pass
            for fp in sorted(p for p in prev_snap_dir.rglob("*") if p.is_file() and p.name != "_manifest.json"):
                rel = fp.relative_to(prev_snap_dir)
                dst = rev_snap_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fp, dst)

    dst_new_ruling = rev_snap_dir / ruling_filename
    dst_new_ruling.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ruling_file, dst_new_ruling)
    manifest_files[ruling_filename] = {
        "spec_revision": new_rev,
        "affected_question_ids": list(target_qs),
        "created_at": now,
    }
    (rev_snap_dir / "_manifest.json").write_text(
        json.dumps(
            {"spec_revision": new_rev, "affected_question_ids": list(target_qs), "files": manifest_files},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    h = hashlib.sha256()
    for fp in sorted(p for p in rev_snap_dir.rglob("*") if p.is_file() and p.name != "_manifest.json"):
        rel = fp.relative_to(rev_snap_dir)
        h.update(f"{rel.as_posix()}:{hashlib.sha256(fp.read_bytes()).hexdigest()}\n".encode("utf-8"))
    new_fp = h.hexdigest()
    eff_summary = (str(summary_md or "").strip() or clean_md[:360])[:1200]

    reopened_qs: list[str] = []
    notified_nodes: list[str] = []
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE parse0_contract
            SET latest_spec_revision = ?, latest_ruling_summary_md = ?,
                ruling_fingerprint_sha256 = ?, updated_at = ?
            WHERE contract_id = 'active'
            """,
            (new_rev, eff_summary, new_fp, now),
        )
        for qid in target_qs:
            qrow = conn.execute(
                "SELECT * FROM subproblem_runtime_state WHERE question_id = ?",
                (qid,),
            ).fetchone()
            if qrow is None:
                continue
            cur_dispatch = str(qrow["dispatch_state"])
            cur_desired = str(qrow["desired_state"])
            new_dispatch = cur_dispatch
            solved_id = qrow["solved_entry_id"]
            solved_rev = qrow["solved_at_spec_revision"]
            if cur_dispatch == "STOPPED_SOLVED" and cur_desired == "ACTIVE":
                still_solved = find_latest_spec_full_goal_l3(conn, qid, required_spec_revision=new_rev)
                if still_solved is None:
                    new_dispatch = "DISPATCHING"
                    solved_id = None
                    solved_rev = None
                    reopened_qs.append(qid)
            conn.execute(
                """
                UPDATE subproblem_runtime_state
                SET active_spec_revision = ?,
                    dispatch_state = ?,
                    solved_entry_id = ?,
                    solved_at_spec_revision = ?,
                    dispatch_generation = dispatch_generation + 1,
                    updated_at = ?
                WHERE question_id = ?
                """,
                (new_rev, new_dispatch, solved_id, solved_rev, now, qid),
            )
            # 对受影响子题在途探索分支投递 NOTIFY_POLICY_CHANGED 温和热通知
            live_nodes = conn.execute(
                "SELECT node_id, control_generation FROM lineage_nodes WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING')",
                (qid,),
            ).fetchall()
            for n in live_nodes:
                nid = str(n["node_id"])
                enqueue_runtime_effect(
                    conn,
                    effect_key=f"policy:{nid}:v{new_rev}",
                    kind="NOTIFY_POLICY_CHANGED",
                    target_type="NODE",
                    target_id=nid,
                    target_generation=int(n["control_generation"] or 1),
                    payload={
                        "question_id": qid,
                        "new_spec_revision": new_rev,
                        "summary_md": eff_summary,
                        "ruling_file": f"rulings/{ruling_filename}",
                    },
                )
                notified_nodes.append(nid)

    return {
        "latest_spec_revision": new_rev,
        "affected_question_ids": target_qs,
        "reopened_questions": reopened_qs,
        "notified_nodes": notified_nodes,
        "ruling_file": f"rulings/{ruling_filename}",
    }


def _execute_seed_human_branch(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    target_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """新开一条带 2 班岗成长保护期的人类种子分支（HUMAN_SEEDED，绝不污染现有纯血分支）。"""
    qid = str(payload.get("question_id") or target_id or "").strip()
    if not qid:
        raise FailClosedError(ERR_INVALID_INPUT, "SEED_HUMAN_BRANCH 缺少 question_id")
    seed_idea = str(payload.get("seed_idea_md") or payload.get("mechanism_signature") or "").strip()
    if not 10 <= len(seed_idea) <= 8000:
        raise FailClosedError(ERR_INVALID_INPUT, "SEED_HUMAN_BRANCH 必须提供 10–8000 字的 seed_idea_md")

    fid = str(payload.get("family_id") or f"fam_{qid.lower()}_human_{uuid.uuid4().hex[:5]}").strip()
    now = utc_now_iso()
    p0 = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    shared_rels = json.loads(p0["shared_inputs_json"] or "[]") if p0 else []
    q_rev_row = conn.execute(
        "SELECT active_spec_revision FROM subproblem_runtime_state WHERE question_id = ?",
        (qid,),
    ).fetchone()
    if q_rev_row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"未登记子题 {qid}")
    from .operator_policy import check_question_branch_quota, epoch_id
    check_question_branch_quota(conn, qid, family_id=fid, human_named=True)
    spec_rev = int(q_rev_row["active_spec_revision"] or 0)

    new_bid = f"b_{qid.lower()}_hseed_{uuid.uuid4().hex[:5]}"
    new_nid = f"node_{qid.lower()}_{uuid.uuid4().hex[:8]}"
    wt_dir = Path(os.path.realpath(workspace_root)) / "worktrees" / new_bid
    wt_dir.mkdir(parents=True)
    # 独立仓库的 Git 元数据与工作树在同一沙箱内。
    subprocess.run(
        ["git", f"--git-dir={wt_dir / '.git'}", f"--work-tree={wt_dir}", "init", "--quiet", "--template="],
        check=True, timeout=5, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    sync_approved_public_inputs(workspace_root, wt_dir, shared_rels, spec_revision=spec_rev, question_id=qid)
    sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt_dir)

    blueprints = wt_dir / "inputs"
    blueprints.mkdir(exist_ok=True)
    (blueprints / "human_seed_blueprint.md").write_text(seed_idea + "\n", encoding="utf-8")
    signature = str(payload.get("mechanism_signature") or seed_idea).strip()

    with rw_immediate_tx(conn):
        check_question_branch_quota(conn, qid, family_id=fid, human_named=True)
        conn.execute(
            """
            INSERT OR IGNORE INTO method_families(family_id, question_id, mechanism_signature, orthogonal_contrast, family_status, created_at)
            VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (fid, qid, signature[:240], str(payload.get("orthogonal_contrast") or "人类研究者注入的新先验思路"), now),
        )
        conn.execute(
            """
            INSERT INTO lineage_nodes(
                node_id, question_id, branch_id, family_id, parent_node_id, generation,
                branch_kind, protection_generations_left, companion_session_id,
                node_status, worktree_abs_path, mechanism_summary, will_md, spec_revision,
                created_at, updated_at, session_epoch_id
            ) VALUES (?, ?, ?, ?, NULL, 1, 'HUMAN_SEEDED', 2, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_nid,
                qid,
                new_bid,
                fid,
                f"gw-comp-{new_nid}",
                str(wt_dir),
                seed_idea[:99],
                "[Human-Seeded Prior] 完整蓝图见 inputs/human_seed_blueprint.md",
                spec_rev,
                now,
                now,
                epoch_id(conn),
            ),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"spawn:{new_nid}:g1",
            kind="SPAWN_PAIR",
            target_type="NODE",
            target_id=new_nid,
            target_generation=1,
            external_handle_id=f"gw-exp-{new_nid}",
            payload={"question_id": qid, "branch_kind": "HUMAN_SEEDED", "operator_named": True},
        )
    return {"question_id": qid, "branch_id": new_bid, "node_id": new_nid, "family_id": fid, "branch_kind": "HUMAN_SEEDED", "worktree_abs_path": str(wt_dir)}


def pending_wave_proposal_target(conn: sqlite3.Connection, proposal_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT target_id FROM control_proposals
        WHERE proposal_id = ? AND action_type = 'APPROVE_WAVE_VERDICT' AND status = 'PENDING_HUMAN'
        """,
        (proposal_id,),
    ).fetchone()
    return row["target_id"] if row else None


def approve_control_proposal(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    proposal_id: str,
    decision: str = "APPROVE",
    approved_by_source: str = "human_ui",
    prepared_growth: dict[int, PreparedBranch] | None = None,
) -> dict[str, Any]:
    """人类落签批准或驳回 control_proposals（乐观锁防双端重复点击）。"""
    if approved_by_source not in ("human_ui", "action_card_human", "gw_chief_human", "branch_handback"):
        raise FailClosedError(ERR_AUTH, f"非法确认来源 {approved_by_source!r}，仅允许真实人类交互落签")
    dec = str(decision or "APPROVE").strip().upper()
    if dec not in ("APPROVE", "REJECT"):
        raise FailClosedError(ERR_INVALID_INPUT, f"decision 仅允许 APPROVE / REJECT，实收 {decision!r}")

    now = utc_now_iso()
    target = pending_wave_proposal_target(conn, proposal_id) if dec == "APPROVE" else None
    staging = prepare_wave_growth(conn, workspace_root, target) if prepared_growth is None else nullcontext(prepared_growth)
    with staging as prepared, rw_immediate_tx(conn):
        row = conn.execute("SELECT * FROM control_proposals WHERE proposal_id = ?", (str(proposal_id),)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"提案 {proposal_id!r} 不存在")
        if approved_by_source in ("gw_chief_human", "branch_handback") and row["action_type"] != "APPROVE_WAVE_VERDICT":
            raise FailClosedError(ERR_AUTH, "此提案需要人类确认界面签署")
        cur_status = str(row["status"])
        if cur_status != "PENDING_HUMAN":
            return {
                "proposal_id": str(proposal_id),
                "status": cur_status,
                "already_resolved": True,
                "message": f"提案已于此前处理（当前状态 {cur_status}），已幂等跳过。",
            }

        act = str(row["action_type"])
        tid = str(row["target_id"])
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}

        if dec == "REJECT":
            cur = conn.execute(
                """
                UPDATE control_proposals
                SET status = 'REJECTED', approved_by_source = ?, resolved_at = ?
                WHERE proposal_id = ? AND status = 'PENDING_HUMAN'
                """,
                (approved_by_source, now, str(proposal_id)),
            )
            if cur.rowcount != 1:
                raise FailClosedError(ERR_CONFLICT, f"提案 {proposal_id!r} 并发冲突")
            if act == "APPROVE_WAVE_VERDICT":
                conn.execute(
                    "UPDATE wave_conferences SET status = 'CANCELLED', completed_at = ? WHERE conference_id = ? AND status = 'PENDING_HUMAN_APPROVAL'",
                    (now, tid),
                )
            return {"proposal_id": str(proposal_id), "action_type": act, "status": "REJECTED", "already_resolved": False}

        # 原子抢占落签资格（乐观锁）
        cur = conn.execute(
            """
            UPDATE control_proposals
            SET status = 'APPROVED_EXECUTED', approved_by_source = ?, resolved_at = ?
            WHERE proposal_id = ? AND status = 'PENDING_HUMAN'
            """,
            (approved_by_source, now, str(proposal_id)),
        )
        if cur.rowcount != 1:
            return {
                "proposal_id": str(proposal_id),
                "status": "APPROVED_EXECUTED",
                "already_resolved": True,
            }

        exec_result: dict[str, Any] = {}
        if act == "SET_SUBPROBLEM_STATE":
            exec_result = set_subproblem_state(
                conn,
                question_id=str(payload.get("question_id") or tid),
                desired_state=str(payload.get("desired_state") or "PAUSED"),
                actor_source="chief_approved",
                reason=str(row["rationale_md"] or ""),
            )
        elif act == "AUTHORIZE_EARLY_HANDOFF":
            exec_result = authorize_early_handoff(
                conn,
                node_id=str(payload.get("node_id") or tid),
                actor_source="chief_approved",
                reason=str(row["rationale_md"] or "CHIEF_APPROVED_EARLY_HANDOFF"),
                cross_branch_note=str(payload.get("cross_branch_note") or ""),
            )
        elif act == "AMEND_RULING_DRAFT":
            exec_result = apply_approved_ruling_amendment(
                conn,
                workspace_root=workspace_root,
                affected_question_ids=list(payload.get("affected_question_ids") or ([tid] if tid != "ALL" else [])),
                ruling_markdown=str(payload.get("ruling_markdown") or row["rationale_md"]),
                summary_md=str(payload.get("summary_md") or ""),
            )
        elif act == "AUTHORIZE_PARTIAL_DELIVERY":
            exec_result = record_human_stop(conn, note=str(payload.get("note") or row["rationale_md"] or "HUMAN_PARTIAL_DELIVERY"))
        elif act == "APPROVE_WAVE_VERDICT":
            from .wave_engine import execute_approved_wave_verdict

            exec_result = execute_approved_wave_verdict(
                conn,
                workspace_root=workspace_root,
                conference_id=tid,
                prepared_growth=prepared,
            )
        elif act == "SEED_HUMAN_BRANCH":
            exec_result = _execute_seed_human_branch(
                conn,
                workspace_root=workspace_root,
                target_id=tid,
                payload=payload,
            )
        elif act == "SUBMIT_WORKS_OR_SURVEY_TICKET":
            kind_t = str(payload.get("ticket_kind") or "WORKS").strip().upper()
            if kind_t == "SURVEY":
                req_id = f"srq_{uuid.uuid4().hex[:10]}"
                conn.execute(
                    """
                    INSERT INTO survey_requests(req_id, question_id, node_id, topic_query, reason, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                    """,
                    (
                        req_id,
                        str(payload.get("question_id") or tid or "Q1"),
                        str(payload.get("node_id") or "gw_chief"),
                        str(payload.get("topic_query") or row["rationale_md"]),
                        str(payload.get("reason") or row["rationale_md"]),
                        now,
                        now,
                    ),
                )
                exec_result = {"ticket_kind": "SURVEY", "req_id": req_id}
            else:
                exec_result = submit_works_ticket(
                    conn,
                    question_id=str(payload.get("question_id") or tid or "ALL"),
                    ticket_type=str(payload.get("ticket_type") or "DISCRIMINATOR"),
                    instrument_id=payload.get("instrument_id"),
                    description=str(payload.get("description") or row["rationale_md"]),
                    source="chief_approved",
                )
        elif act == "ADVANCE_EPOCH":
            from .epochs import advance_epoch
            exec_result = advance_epoch(conn, proposal_id=str(proposal_id), payload=payload)
        elif act == "SET_AUTONOMY_MODE":
            exec_result = set_autonomy_mode(
                conn,
                autonomy_mode=str(payload.get("autonomy_mode") or tid),
                actor_source="chief_approved",
            )

    return {
        "proposal_id": str(proposal_id),
        "action_type": act,
        "target_id": tid,
        "status": "APPROVED_EXECUTED",
        "already_resolved": False,
        "execution": exec_result,
    }
