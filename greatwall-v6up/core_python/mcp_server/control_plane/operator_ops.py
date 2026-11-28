"""Single-writer operator actions and physical slot settlement."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from ..db_schema import ERR_AUTH, ERR_CONFLICT, ERR_INVALID_INPUT, ERR_LOCKED, ERR_NOT_FOUND, FailClosedError
from ..db_schema import rw_immediate_tx, utc_now_iso
from .effects_outbox import cancel_stale_effects_for_target, enqueue_runtime_effect
from .node_interventions import _insert_intervention, authorize_early_handoff, pause_node, resume_node
from .operator_policy import (
    active_arrangements, check_question_branch_quota, drain_arrangement, effective_policy,
    epoch_id, runtime_slots, scoped_to, validate_arrangement,
)

DRAIN_STATES = ("DRAIN_AFTER_TURN", "DRAIN_AFTER_HANDOFF")
ACTIVE = ("EXPLORING", "ACTIVE_REVISING")


def _id(kind: str) -> str:
    return f"{kind}_{uuid4().hex}"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def read_receipt(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["pending_targets"] = json.loads(result.pop("pending_targets_json"))
    result["failed_items"] = json.loads(result.pop("failed_items_json"))
    return result


def recent_receipts(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return [read_receipt(row) for row in conn.execute(
        "SELECT * FROM operation_receipts WHERE epoch_id=? ORDER BY created_at DESC LIMIT ?", (epoch_id(conn), limit),
    )]


def _active_node(conn: sqlite3.Connection, node_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM lineage_nodes WHERE node_id=?", (node_id,)).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id} 不存在")
    return row


def _drain_node(conn: sqlite3.Connection, node: sqlite3.Row, mode: str, op_id: str, actor: str, *, retire=False, arrangement_id=None) -> bool:
    nid = node["node_id"]
    is_live = conn.execute("SELECT 1 FROM operator_runtime_slots WHERE node_id=?", (nid,)).fetchone() is not None
    gen = node["control_generation"] + 1
    now = utc_now_iso()
    immediate = retire or mode == "IMMEDIATE_YIELD"
    new_state = "DRAIN_AFTER_HANDOFF" if mode == "FINISH_CURRENT_HANDOFF" else "DRAIN_AFTER_TURN"
    if not is_live:
        new_state = "HIBERNATED"
    conn.execute(
        "UPDATE lineage_nodes SET node_status=?, control_state=?, control_generation=?, updated_at=?,operator_arrangement_id=? WHERE node_id=?",
        ("RETIRED" if retire else node["node_status"], new_state, gen, now, arrangement_id, nid),
    )
    cancel_stale_effects_for_target(conn, target_type="NODE", target_id=nid, below_generation=gen,
                                    kinds=("SPAWN_PAIR", "DRAIN_AND_STOP_NODE", "CANCEL_NODE_SESSION"))
    if immediate and (is_live or retire):
        enqueue_runtime_effect(
            conn, effect_key=f"operator:{nid}:g{gen}", kind="CANCEL_NODE_SESSION" if retire else "DRAIN_AND_STOP_NODE",
            target_type="NODE", target_id=nid, target_generation=gen,
            payload={"op_id": op_id, "reason": "OPERATOR_RETIRE" if retire else "OPERATOR_HIBERNATE",
                     "grace_sec": 0 if retire else 3, "keep_session_for_human": False},
        )
    _insert_intervention(conn, node_id=nid, question_id=node["question_id"], actor_source=actor,
                         action="NODE_RETIRED" if retire else "NODE_HIBERNATED",
                         details={"op_id": op_id, "drain_mode": mode, "pending_retirement": is_live}, now=now)
    return is_live


def _settle_receipts(conn: sqlite3.Connection) -> None:
    current = {row["node_id"] for row in runtime_slots(conn)}
    now = utc_now_iso()
    for row in conn.execute("SELECT * FROM operation_receipts WHERE status='DRAINING'").fetchall():
        receipt = read_receipt(row)
        op_id = receipt["op_id"]
        failed = receipt["failed_items"]
        remaining = []
        for nid in receipt["pending_targets"]:
            effect = conn.execute(
                """SELECT status,last_error FROM runtime_effects
                   WHERE target_type='NODE' AND target_id=? AND json_extract(payload_json,'$.op_id')=?
                   ORDER BY seq DESC LIMIT 1""", (nid, op_id),
            ).fetchone()
            if effect and effect["status"] == "FAILED":
                failed.append({"target_id": nid, "error": effect["last_error"], "retry_hint": "重新发起该节点的操作"})
            elif effect and effect["status"] in ("PENDING", "RUNNING"):
                remaining.append(nid)
            elif receipt["command_kind"] == "SEND_BRANCH_NOTE":
                continue
            elif nid in current or conn.execute(
                """SELECT 1 FROM lineage_nodes WHERE node_id=? AND control_state='DRAIN_AFTER_HANDOFF'
                     AND node_status IN ('AWAITING_TRIAGE','EXPLORING','ACTIVE_REVISING')""", (nid,),
            ).fetchone():
                remaining.append(nid)
        status = "DRAINING" if remaining else ("PARTIAL_FAILED" if failed else "SETTLED")
        if remaining != receipt["pending_targets"] or status != receipt["status"]:
            conn.execute(
                """UPDATE operation_receipts SET status=?, pending_targets_json=?, failed_items_json=?,
                   updated_at=?, settled_at=? WHERE op_id=?""",
                (status, _dump(remaining), _dump(failed), now, None if remaining else now, op_id),
            )


def _finish_exited_slots(conn: sqlite3.Connection) -> int:
    eligible = conn.execute(
        """SELECT s.node_id FROM operator_runtime_slots s JOIN lineage_nodes n ON n.node_id=s.node_id
           WHERE s.worker_exited=1 AND NOT EXISTS (
             SELECT 1 FROM runtime_effects e WHERE e.target_type='NODE' AND e.target_id=s.node_id
               AND e.target_generation=n.control_generation AND e.status IN ('PENDING','RUNNING')
               AND e.kind IN ('CANCEL_NODE_SESSION','DRAIN_AND_STOP_NODE')
           ) AND NOT EXISTS (
             SELECT 1 FROM async_eval_jobs j WHERE j.node_id=s.node_id AND j.status='RUNNING'
           ) AND NOT (n.control_state='DRAIN_AFTER_TURN' AND EXISTS (
             SELECT 1 FROM async_eval_jobs j WHERE j.node_id=s.node_id AND j.status='QUEUED'
           ) AND NOT EXISTS (
             SELECT 1 FROM runtime_effects e WHERE e.target_type='NODE' AND e.target_id=s.node_id
               AND e.target_generation=n.control_generation AND e.kind IN ('CANCEL_NODE_SESSION','DRAIN_AND_STOP_NODE')
           ))"""
    ).fetchall()
    now = utc_now_iso()
    for row in eligible:
        conn.execute("DELETE FROM operator_runtime_slots WHERE node_id=?", (row["node_id"],))
        conn.execute(
            """UPDATE lineage_nodes SET control_state='HIBERNATED',updated_at=? WHERE node_id=?
               AND control_state='DRAIN_AFTER_TURN'""", (now, row["node_id"]),
        )
    return len(eligible)


def _expire_and_settle(conn: sqlite3.Connection, replacing_op_id: str | None = None) -> None:
    _finish_exited_slots(conn)
    rows = active_arrangements(conn, persist_expiry=True)
    restored = set()
    now = utc_now_iso()
    for node in conn.execute(
        """SELECT * FROM lineage_nodes WHERE operator_arrangement_id IS NOT NULL
           AND control_state IN ('DRAIN_AFTER_TURN','DRAIN_AFTER_HANDOFF','HIBERNATED')
           AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE')"""
    ).fetchall():
        nid = node["node_id"]
        arrangement, mode = drain_arrangement(rows, node["question_id"], nid)
        if mode:
            if node["operator_arrangement_id"] != arrangement["arrangement_id"]:
                if node["control_state"] == "HIBERNATED" or node["node_status"] == "AWAITING_TRIAGE":
                    conn.execute("UPDATE lineage_nodes SET operator_arrangement_id=? WHERE node_id=?",
                                 (arrangement["arrangement_id"], nid))
                else:
                    _drain_node(conn, node, mode, arrangement["op_id"], "chief_direct",
                                arrangement_id=arrangement["arrangement_id"])
            continue
        generation = node["control_generation"] + 1
        conn.execute(
            """UPDATE lineage_nodes SET control_state='AUTO_RUNNING',operator_arrangement_id=NULL,
               control_generation=?,updated_at=? WHERE node_id=?""", (generation, now, nid),
        )
        cancel_stale_effects_for_target(conn, target_type="NODE", target_id=nid, below_generation=generation,
                                        kinds=("DRAIN_AND_STOP_NODE",))
        if node["control_state"] in DRAIN_STATES:
            restored.add(nid)
    if restored:
        _supersede_receipts(conn, restored, replacing_op_id, command_kind="APPLY_ARRANGEMENT")
    _settle_receipts(conn)


def _supersede_receipts(conn: sqlite3.Connection, node_ids: set[str], op_id: str | None, *, command_kind: str | None = None) -> None:
    now = utc_now_iso()
    for row in conn.execute(
        """SELECT * FROM operation_receipts WHERE status='DRAINING'
           AND command_kind IN ('APPLY_ARRANGEMENT','NODE_INTERVENE') AND (? IS NULL OR command_kind=?)""",
        (command_kind, command_kind),
    ).fetchall():
        receipt = read_receipt(row)
        pending = set(receipt["pending_targets"])
        if pending & node_ids:
            left = sorted(pending - node_ids)
            conn.execute(
                "UPDATE operation_receipts SET status=?, pending_targets_json=?, superseded_by_op_id=?, updated_at=?, settled_at=? WHERE op_id=?",
                ("DRAINING" if left else "SUPERSEDED", _dump(left), op_id, now, None if left else now, row["op_id"]),
            )


def _apply_arrangement(conn: sqlite3.Connection, params: dict[str, Any], op_id: str, actor: str) -> tuple[dict, list]:
    scope, target, patch, ends, expires = validate_arrangement(params)
    if scope == "NODE":
        _active_node(conn, target)
    if scope == "QUESTION" and conn.execute("SELECT 1 FROM subproblem_runtime_state WHERE question_id=?", (target,)).fetchone() is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {target} 不存在")
    now = utc_now_iso()
    aid = _id("arr")
    scope_row = {"scope_type": scope, "target_id": target}
    slots = runtime_slots(conn)
    watched = [r["node_id"] for r in slots if scoped_to(scope_row, r["question_id"], r["node_id"])]
    batch_scope = params.get("watch_batch_scope")
    if ends == "AFTER_INFLIGHT_BATCH" and batch_scope:
        if batch_scope.get("scope_type") not in ("PROJECT", "QUESTION", "NODE") or not batch_scope.get("target_id"):
            raise FailClosedError(ERR_INVALID_INPUT, "批次观察需要有效的 scope_type 与 target_id")
        if batch_scope["scope_type"] == "QUESTION" and not conn.execute(
            "SELECT 1 FROM subproblem_runtime_state WHERE question_id=?", (batch_scope["target_id"],),
        ).fetchone():
            raise FailClosedError(ERR_NOT_FOUND, "批次观察的子题不存在")
        if batch_scope["scope_type"] == "NODE":
            _active_node(conn, batch_scope["target_id"])
    batch_ids = [
        r["node_id"] for r in slots
        if scoped_to(batch_scope or scope_row, r["question_id"], r["node_id"])
    ]
    version = conn.execute("SELECT COALESCE(MAX(arrangement_version), 0) + 1 FROM run_arrangements").fetchone()[0]
    status = "EXPIRED" if ends == "AFTER_INFLIGHT_BATCH" and not batch_ids else "ACTIVE"
    if status == "ACTIVE":
        for old in active_arrangements(conn, persist_expiry=True):
            if old["scope_type"] != scope or old["target_id"] != target or not old["patch"].keys() & patch.keys():
                continue
            retained = {key: value for key, value in old["patch"].items() if key not in patch}
            if retained:
                conn.execute("UPDATE run_arrangements SET patch_json=?, updated_at=? WHERE arrangement_id=?",
                             (_dump(retained), now, old["arrangement_id"]))
            else:
                conn.execute(
                    "UPDATE run_arrangements SET status='SUPERSEDED', superseded_by_id=?, resolved_at=?, updated_at=? WHERE arrangement_id=?",
                    (aid, now, now, old["arrangement_id"]),
                )
                conn.execute(
                    """UPDATE operation_receipts SET status='SUPERSEDED', pending_targets_json='[]',
                       superseded_by_op_id=?, settled_at=?, updated_at=? WHERE op_id=? AND command_kind='APPLY_ARRANGEMENT'
                       AND status='SETTLED' AND op_id<>?
                       AND NOT EXISTS (SELECT 1 FROM run_arrangements WHERE op_id=? AND status='ACTIVE')""",
                    (op_id, now, now, old["op_id"], op_id, old["op_id"]),
                )
    conn.execute(
        """INSERT INTO run_arrangements(
            arrangement_id,arrangement_version,epoch_id,scope_type,target_id,patch_json,summary_md,ends_on_kind,
            expires_at,watch_node_ids_json,status,actor_source,op_id,created_at,updated_at,resolved_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (aid, version, epoch_id(conn), scope, target, _dump(patch), str(params.get("summary_md") or ""),
         ends, expires, _dump(batch_ids if ends == "AFTER_INFLIGHT_BATCH" else []), status,
         actor, op_id, now, now, now if status == "EXPIRED" else None),
    )
    return {"arrangement_id": aid, "arrangement_version": version, "arrangement_status": status}, watched if status == "ACTIVE" else []


def _archive_family(conn: sqlite3.Connection, fid: str) -> None:
    if conn.execute(
        """SELECT 1 FROM lineage_nodes WHERE family_id=?
           AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B')""",
        (fid,),
    ).fetchone():
        raise FailClosedError(ERR_CONFLICT, f"学派 {fid} 仍有保留分支")
    conn.execute("UPDATE method_families SET family_status='ARCHIVED' WHERE family_id=?", (fid,))


def _intervene(conn: sqlite3.Connection, *, action: dict, actor: str, op_id: str) -> tuple[set, list]:
    mode = action.get("mode")
    targets = list(dict.fromkeys(action.get("node_ids") or []))
    if not targets or mode not in ("retire", "hibernate", "pause_takeover", "resume", "early_handoff", "reactivate"):
        raise FailClosedError(ERR_INVALID_INPUT, "节点操作需要 node_ids 和有效 mode")
    pending = set()
    failures = []
    family_ids = set()
    for nid in targets:
        try:
            node = _active_node(conn, nid)
            if mode == "reactivate":
                if node["node_status"] != "RETIRED":
                    raise FailClosedError(ERR_LOCKED, f"{nid} 不是已撤编分支")
                check_question_branch_quota(conn, node["question_id"],
                                            replacing_branch_id=node["branch_id"], human_named=True)
                if conn.execute(
                    """SELECT 1 FROM lineage_nodes WHERE branch_id=? AND node_id<>?
                       AND (generation>? OR node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW'))""",
                    (node["branch_id"], nid, node["generation"]),
                ).fetchone():
                    raise FailClosedError(ERR_CONFLICT, "分支已有更新代次或其他活跃节点")
                conn.execute("UPDATE method_families SET family_status='ACTIVE' WHERE family_id=? AND family_status='ARCHIVED'",
                             (node["family_id"],))
                conn.execute("UPDATE lineage_nodes SET node_status='EXPLORING' WHERE node_id=?", (nid,))
                resume_node(conn, node_id=nid, actor_source=actor, operator_named=True)
                _insert_intervention(conn, node_id=nid, question_id=node["question_id"], actor_source=actor,
                                     action="NODE_REACTIVATED", details={"op_id": op_id}, now=utc_now_iso())
            elif mode == "resume":
                check_question_branch_quota(conn, node["question_id"], family_id=node["family_id"],
                                            replacing_branch_id=node["branch_id"], human_named=True)
                resume_node(conn, node_id=nid, actor_source=actor, operator_named=True,
                            cross_branch_note=str(action.get("cross_branch_note") or action.get("reason") or ""))
            elif mode == "pause_takeover":
                res = pause_node(conn, node_id=nid, actor_source=actor, reason=str(action.get("reason") or "OPERATOR_PAUSE"))
                conn.execute(
                    """UPDATE runtime_effects SET payload_json=json_set(payload_json,'$.op_id',?)
                       WHERE effect_key=?""", (op_id, f"drain:{nid}:pause:g{res['control_generation']}"),
                )
                pending.add(nid)
            elif mode == "early_handoff":
                authorize_early_handoff(conn, node_id=nid, actor_source=actor,
                                        reason=str(action.get("reason") or "OPERATOR_HANDOFF"),
                                        cross_branch_note=str(action.get("cross_branch_note") or ""))
            else:
                if node["node_status"] not in ACTIVE and not (mode == "retire" and node["node_status"] == "BLOCKED_L4B"):
                    raise FailClosedError(ERR_LOCKED, f"{nid} 当前状态 {node['node_status']} 不接受 {mode}")
                if _drain_node(conn, node, "IMMEDIATE_YIELD", op_id, actor, retire=mode == "retire") or mode == "retire":
                    pending.add(nid)
                if mode == "retire" and node["family_id"]:
                    family_ids.add(node["family_id"])
            _supersede_receipts(conn, {nid}, op_id)
        except FailClosedError as exc:
            failures.append({"target_id": nid, "error": exc.message, "retry_hint": "调整操作目标或条件后重试"})
    if action.get("archive_family"):
        for family in sorted(family_ids):
            try:
                _archive_family(conn, family)
            except FailClosedError as exc:
                failures.append({"target_id": family, "error": exc.message, "retry_hint": "保留其余分支或再确认归档"})
    return pending, failures


def operator_command(
    conn: sqlite3.Connection, *, operation: str, actor_source: str,
    arrangement: dict | None = None, arrangements: list[dict] | None = None, node_action: dict | None = None,
    handback_id: str | None = None, details: dict | None = None, workspace_root: str = "",
) -> dict[str, Any]:
    op_id = _id("op")
    actor = "chief_direct" if actor_source != "human_ui" else actor_source
    now = utc_now_iso()
    details = details or {}
    summary = str((arrangement or {}).get("summary_md") or details.get("summary_md") or (node_action or {}).get("reason") or operation)
    pending: set[str] = set()
    failed: list[dict] = []
    data: dict[str, Any] = {}
    from .proposals import pending_wave_proposal_target
    from .wave_verdict_actions import prepare_wave_growth

    wave_target = pending_wave_proposal_target(conn, details["proposal_id"]) if operation == "approve_wave_verdict" and details.get("proposal_id") else None
    with prepare_wave_growth(conn, workspace_root, wave_target) as prepared_growth, rw_immediate_tx(conn):
        if not conn.execute("SELECT 1 FROM parse0_contract WHERE contract_id='active'").fetchone():
            raise FailClosedError(ERR_LOCKED, "请先签署 Parse 0，再修改运行安排")
        if handback_id:
            mandate = conn.execute(
                """SELECT * FROM handback_records WHERE handback_id=? AND epoch_id=? AND status='PENDING_CHIEF'
                   AND origin_human_mandate=1 AND origin_human_rpc_id<>''""", (handback_id, epoch_id(conn)),
            ).fetchone()
            if mandate is None:
                raise FailClosedError(ERR_AUTH, "转办授权已失效或已核销")
        if operation == "apply_arrangement":
            patches = (arrangements or []) + ([arrangement] if arrangement else [])
            if not patches:
                raise FailClosedError(ERR_INVALID_INPUT, "缺少运行安排")
            applied = [_apply_arrangement(conn, patch, op_id, actor_source) for patch in patches]
            data.update(applied[-1][0])
            data["arrangements"] = [record for record, _ in applied]
            if node_action:
                pending, failed = _intervene(conn, action=node_action, actor=actor, op_id=op_id)
            explicit = set((node_action or {}).get("node_ids") or [])
            active = active_arrangements(conn)
            for nid in sorted({nid for _, watched in applied for nid in watched} - explicit):
                n = _active_node(conn, nid)
                source, mode = drain_arrangement(active, n["question_id"], nid)
                if mode and source["op_id"] == op_id and n["node_status"] in ACTIVE and n["control_state"] in ("AUTO_RUNNING", *DRAIN_STATES):
                    _supersede_receipts(conn, {nid}, op_id)
                    if _drain_node(conn, n, mode, op_id, actor, arrangement_id=source["arrangement_id"]):
                        pending.add(nid)
        elif operation == "node_intervene":
            pending, failed = _intervene(conn, action=node_action or {}, actor=actor, op_id=op_id)
        elif operation == "revoke_arrangement":
            aid = str(details.get("arrangement_id") or "")
            cur = conn.execute(
                """UPDATE run_arrangements SET status='REVOKED',updated_at=?,resolved_at=?
                   WHERE arrangement_id=? AND epoch_id=? AND status='ACTIVE'""", (now, now, aid, epoch_id(conn)),
            )
            if cur.rowcount != 1:
                raise FailClosedError(ERR_NOT_FOUND, f"没有活动运行安排 {aid}")
            data["arrangement_id"] = aid
        elif operation == "family_manage":
            fid = str(details.get("family_id") or "")
            if not conn.execute("SELECT 1 FROM method_families WHERE family_id=?", (fid,)).fetchone():
                raise FailClosedError(ERR_NOT_FOUND, f"未知学派 {fid}")
            if details.get("mode") == "archive":
                _archive_family(conn, fid)
            elif details.get("mode") == "reactivate":
                conn.execute("UPDATE method_families SET family_status='ACTIVE' WHERE family_id=? AND family_status='ARCHIVED'", (fid,))
            else:
                raise FailClosedError(ERR_INVALID_INPUT, "学派操作仅接受 archive 或 reactivate")
            data["family_id"] = fid
        elif operation == "pin_note":
            data.update(_pin_note(conn, details))
        elif operation == "submit_ticket":
            from .lifecycle_ops import submit_works_ticket
            data.update(submit_works_ticket(
                conn, question_id=str(details.get("question_id") or "ALL"),
                ticket_type=str(details.get("ticket_type") or "PAIN_POINT"), instrument_id=details.get("instrument_id"),
                description=str(details.get("description") or ""), source=actor_source,
            ))
        elif operation == "cancel_ticket":
            from .lifecycle_ops import cancel_works_ticket
            res_cancel = cancel_works_ticket(
                conn, ticket_id=str(details.get("ticket_id") or ""),
                reason=str(details.get("reason") or details.get("summary_md") or ""), actor=actor_source,
            )
            data.update({
                "ticket_id": res_cancel["ticket_id"],
                "ticket_status": res_cancel["status"],
                "resolution": res_cancel["resolution"],
                "cancel_reason": res_cancel["cancel_reason"],
            })
        elif operation == "request_survey":
            qid = str(details.get("question_id") or "ALL").strip() or "ALL"
            topic = str(details.get("topic_query") or "").strip()
            reason = str(details.get("reason") or details.get("summary_md") or "科研总控按人类指示定向补采外藏文献").strip()
            if not topic:
                raise FailClosedError(ERR_INVALID_INPUT, "request_survey 必填 details.topic_query（检索主题）")
            req_id = f"srv_{uuid4().hex[:10]}"
            conn.execute(
                """INSERT INTO survey_requests(req_id, question_id, node_id, topic_query, reason, status, created_at, updated_at)
                   VALUES(?, ?, 'gw_chief', ?, ?, 'PENDING', ?, ?)""",
                (req_id, qid, topic, reason, now, now),
            )
            data.update({"req_id": req_id, "question_id": qid, "topic_query": topic, "survey_status": "PENDING"})
        elif operation == "open_wave_conference":
            from .wave_engine import check_and_open_wave_conference
            qid = str(details.get("question_id") or "").strip()
            if not qid or qid.upper() == "ALL":
                raise FailClosedError(ERR_INVALID_INPUT, "open_wave_conference 必须指定单个子题 details.question_id（如 Q1）")
            qrow = conn.execute("SELECT dispatch_state FROM subproblem_runtime_state WHERE question_id=?", (qid,)).fetchone()
            if qrow is None:
                raise FailClosedError(ERR_NOT_FOUND, f"子题 {qid!r} 不存在")
            if str(qrow["dispatch_state"]) in ("CLOSED", "STOPPED_SOLVED"):
                raise FailClosedError(ERR_CONFLICT, f"子题 {qid!r} 已结题 ({qrow['dispatch_state']})，无需再开圆桌")
            existing_conf = conn.execute(
                "SELECT conference_id, status FROM wave_conferences WHERE question_id=? AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED') LIMIT 1",
                (qid,),
            ).fetchone()
            if existing_conf is not None:
                raise FailClosedError(ERR_CONFLICT, f"子题 {qid!r} 已有进行中的圆桌 {existing_conf['conference_id']}（{existing_conf['status']}）")
            opened = check_and_open_wave_conference(
                conn,
                question_id=qid,
                force=True,
                human_agenda_md=details.get("human_agenda_md", ""),
                discussion_rounds=details.get("discussion_rounds"),
            )
            if not opened:
                raise FailClosedError(ERR_CONFLICT, f"子题 {qid!r} 当前无法召开圆桌会议")
            data.update({
                "conference_id": opened["conference_id"],
                "question_id": qid,
                "wave_no": opened["wave_no"],
                "conference_status": opened["status"],
                "participant_count": opened["participant_count"],
                "discussion_rounds": opened["discussion_rounds"],
                "chair_session_id": opened["chair_session_id"],
            })
        elif operation == "approve_wave_verdict":
            from .proposals import approve_control_proposal
            proposal_id = str(details.get("proposal_id") or "")
            row = conn.execute("SELECT action_type FROM control_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
            if row is None or row["action_type"] != "APPROVE_WAVE_VERDICT":
                raise FailClosedError(ERR_INVALID_INPUT, "请提供待签批的圆桌裁决提案")
            data.update(approve_control_proposal(conn, workspace_root=workspace_root, proposal_id=proposal_id,
                                                 decision="APPROVE", approved_by_source=actor_source,
                                                 prepared_growth=prepared_growth))
        elif operation == "recover_queue":
            res = conn.execute(
                """UPDATE runtime_effects SET status='PENDING',owner_instance_id='',lease_expires_at=NULL,
                   due_at=?, updated_at=?, attempts=0, completed_at=NULL
                   WHERE status='FAILED' AND kind IN ('SPAWN_PAIR','WAKE_BLOCKED_BRANCH','REFRESH_LIVING_SURVEY','RUN_WAVE_CONFERENCE')""",
                (now, now),
            )
            data["requeued_effects"] = res.rowcount
        else:
            raise FailClosedError(ERR_INVALID_INPUT, f"未知运行操作 {operation!r}")
        status = "DRAINING" if pending else ("PARTIAL_FAILED" if failed else "SETTLED")
        conn.execute(
            """INSERT INTO operation_receipts(op_id,epoch_id,actor_source,command_kind,summary_md,status,
               pending_targets_json,failed_items_json,origin_handback_id,created_at,updated_at,settled_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (op_id, epoch_id(conn), actor_source, operation.upper(), summary, status, _dump(sorted(pending)),
             _dump(failed), handback_id, now, now, None if pending else now),
        )
        if handback_id and (status != "PARTIAL_FAILED" or len(failed) < len((node_action or {}).get("node_ids") or [])):
            conn.execute(
                """UPDATE handback_records SET status='EXECUTED',resolved_op_id=?,resolution_summary_md=?,resolved_at=?
                   WHERE handback_id=?""", (op_id, summary, now, handback_id),
            )
            enqueue_runtime_effect(
                conn, effect_key=f"handback:{handback_id}:receipt", kind="DELIVER_HANDBACK_RECEIPT",
                target_type="NODE", target_id=mandate["source_node_id"],
                payload={"message": f"转办 {handback_id} 已受理，回执 {op_id}（{status}）。{summary}"},
            )
        _expire_and_settle(conn, op_id)
        receipt = read_receipt(conn.execute("SELECT * FROM operation_receipts WHERE op_id=?", (op_id,)).fetchone())
    return {**receipt, **data}


def _pin_note(conn: sqlite3.Connection, details: dict) -> dict:
    nid = str(details.get("note_id") or _id("note"))
    now = utc_now_iso()
    if details.get("mode") == "unpin":
        conn.execute("UPDATE chief_pinned_notes SET is_active=0,updated_at=? WHERE note_id=? AND epoch_id=?", (now, nid, epoch_id(conn)))
        return {"note_id": nid}
    note = str(details.get("content_md") or "").strip()
    used = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(content_md)),0) FROM chief_pinned_notes WHERE epoch_id=? AND is_active=1 AND note_id<>?",
        (epoch_id(conn), nid),
    ).fetchone()[0]
    if not 1 <= len(note) <= 200 or used + len(note) > 400:
        raise FailClosedError(ERR_INVALID_INPUT, "每条置顶备忘限 200 字，全院合计限 400 字")
    conn.execute(
        """INSERT INTO chief_pinned_notes(note_id,epoch_id,question_id,content_md,is_active,created_at,updated_at)
           VALUES(?,?,?,?,1,?,?) ON CONFLICT(note_id) DO UPDATE SET
           question_id=excluded.question_id,content_md=excluded.content_md,is_active=1,updated_at=excluded.updated_at
           WHERE chief_pinned_notes.epoch_id=excluded.epoch_id""",
        (nid, epoch_id(conn), str(details.get("question_id") or "ALL"), note, now, now),
    )
    return {"note_id": nid}


def branch_notes(conn: sqlite3.Connection, node_id: str, action: str, note: dict | None) -> dict:
    with rw_immediate_tx(conn):
        row = _active_node(conn, node_id)
        notes = json.loads(row["pending_advisor_notes_json"])
        if action == "queue_note" and not any(item["id"] == note["id"] for item in notes):
            notes.append(note)
        elif action == "ack_note":
            notes = [item for item in notes if item["id"] != note["id"]]
        if action != "notes":
            conn.execute("UPDATE lineage_nodes SET pending_advisor_notes_json=? WHERE node_id=?",
                         (_dump(notes), node_id))
        return {"notes": notes}


def admit_runtime_slot(
    conn: sqlite3.Connection, node_id: str, owner_id: str, launch_id: str, generation: int,
    slot_tier: str = "normal", slot_cap: int = 6,
) -> dict:
    with rw_immediate_tx(conn):
        node = _active_node(conn, node_id)
        if node["control_state"] != "AUTO_RUNNING" or node["control_generation"] != generation or node["node_status"] not in ACTIVE:
            return {"admitted": False}
        rows = active_arrangements(conn, persist_expiry=True)
        state = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id=?", (node["question_id"],)).fetchone()
        policy = effective_policy(rows, node["question_id"], node_id, base=dict(state) if state else None)
        explicit = conn.execute(
            "SELECT 1 FROM runtime_effects WHERE kind='SPAWN_PAIR' AND target_id=? AND target_generation=? AND status NOT IN ('CANCELLED','FAILED') AND json_extract(payload_json,'$.operator_named')=1",
            (node_id, generation),
        ).fetchone() is not None
        close = conn.execute("SELECT status,human_stop_requested_at FROM project_closure_state WHERE id=1").fetchone()
        if (state and state["dispatch_state"] != "DISPATCHING") or (close and (close["human_stop_requested_at"] or close["status"] != "OPEN")):
            return {"admitted": False}
        if node["personal_turn_active"]:
            return {"admitted": False}
        if policy["dispatch_policy"] != "NORMAL" and not (explicit and policy["dispatch_policy"] == "NO_NEW_DISPATCH"):
            return {"admitted": False}
        n_live = conn.execute(
            """SELECT COUNT(*) FROM operator_runtime_slots s JOIN lineage_nodes n ON n.node_id=s.node_id
               WHERE n.question_id=?""", (node["question_id"],),
        ).fetchone()[0]
        if n_live >= policy["max_active_branches"]:
            return {"admitted": False}
        if slot_tier == "human_reserve":
            if not explicit or conn.execute("SELECT 1 FROM operator_runtime_slots WHERE slot_tier='human_reserve'").fetchone():
                return {"admitted": False}
        elif conn.execute("SELECT COUNT(*) FROM operator_runtime_slots WHERE slot_tier='normal'").fetchone()[0] >= slot_cap:
            return {"admitted": False}
        cur = conn.execute(
            "INSERT OR IGNORE INTO operator_runtime_slots(node_id,owner_id,launch_id,slot_tier,started_at) VALUES(?,?,?,?,?)",
            (node_id, owner_id, launch_id, slot_tier, utc_now_iso()),
        )
        if cur.rowcount and explicit:
            conn.execute(
                """UPDATE runtime_effects SET payload_json=json_set(payload_json,'$.operator_named',0)
                   WHERE kind='SPAWN_PAIR' AND target_id=? AND target_generation=?""", (node_id, generation),
            )
        return {"admitted": cur.rowcount == 1}


def release_runtime_slot(conn: sqlite3.Connection, node_id: str, owner_id: str, launch_id: str) -> dict:
    with rw_immediate_tx(conn):
        cur = conn.execute(
            "UPDATE operator_runtime_slots SET worker_exited=1 WHERE node_id=? AND owner_id=? AND launch_id=?",
            (node_id, owner_id, launch_id),
        )
        if cur.rowcount:
            _expire_and_settle(conn)
        held = conn.execute("SELECT 1 FROM operator_runtime_slots WHERE node_id=?", (node_id,)).fetchone()
        return {"released": cur.rowcount == 1 and held is None, "pending_quiescence": held is not None}


def recover_runtime_slots(conn: sqlite3.Connection, owner_id: str, live_node_ids: list[str] | None = None) -> dict:
    live_json = _dump(live_node_ids or [])
    stale = """owner_id<>? OR (worker_exited=0 AND node_id NOT IN (SELECT value FROM json_each(?)))"""
    with rw_immediate_tx(conn):
        conn.execute(
            f"""UPDATE lineage_nodes SET control_state='HIBERNATED',updated_at=?
                WHERE control_state IN ('DRAIN_AFTER_TURN','DRAIN_AFTER_HANDOFF')
                  AND node_id IN (SELECT node_id FROM operator_runtime_slots WHERE {stale})""",
            (utc_now_iso(), owner_id, live_json),
        )
        cur = conn.execute(f"DELETE FROM operator_runtime_slots WHERE {stale}", (owner_id, live_json))
        _expire_and_settle(conn)
        return {"recovered_slots": cur.rowcount}
