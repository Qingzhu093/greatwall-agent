"""Chief's human-authorized operator and paged reading tools."""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from .control_plane.effects_outbox import enqueue_runtime_effect
from .control_plane.node_interventions import _insert_intervention
from .control_plane.operator_ops import _active_node, operator_command, read_receipt
from .control_plane.operator_policy import epoch_id
from .db_schema import ERR_AUTH, ERR_INVALID_INPUT, ERR_NOT_FOUND, FailClosedError, rw_immediate_tx, utc_now_iso
from .mcp_core_helpers import enforce_role_tool_permission


def _mandate(conn, name, role, sid, rpc_id, handback_id=None):
    enforce_role_tool_permission(conn, role, name, session_id=sid)
    if not rpc_id and not handback_id:
        raise FailClosedError(ERR_AUTH, "请由人在科研总控会话直接下令，或提供待核销的分支转办单")


def tool_chief_operate(
    conn, caller_role, session_id, workspace_root, operation,
    arrangement=None, node_action=None, handback_id=None, details=None, arrangements=None, *, human_rpc_id="",
):
    _mandate(conn, "chief_operate", caller_role, session_id, human_rpc_id, handback_id)
    res = operator_command(
        conn, operation=operation, actor_source="branch_handback" if handback_id else "gw_chief_human",
        arrangement=arrangement, arrangements=arrangements, node_action=node_action, handback_id=handback_id,
        details=details, workspace_root=workspace_root,
    )
    return {"ok": True, "data": res}


def tool_chief_send_branch_note(conn, caller_role, session_id, node_id, note_md, *, human_rpc_id=""):
    _mandate(conn, "chief_send_branch_note", caller_role, session_id, human_rpc_id)
    note_md = str(note_md).strip()
    if not 1 <= len(note_md) <= 1500:
        raise FailClosedError(ERR_INVALID_INPUT, "导师便签须为 1–1500 字")
    now = utc_now_iso()
    note_id = f"note_{uuid4().hex}"
    with rw_immediate_tx(conn):
        node = _active_node(conn, node_id)
        enqueue_runtime_effect(
            conn, effect_key=note_id, kind="DELIVER_BRANCH_NOTE", target_type="NODE", target_id=node_id,
            target_generation=node["control_generation"], payload={"message": note_md, "note_id": note_id, "op_id": note_id},
        )
        _insert_intervention(conn, node_id=node_id, question_id=node["question_id"], action="ADVISOR_NOTE_SENT",
                             actor_source="chief_direct", details={"note_id": note_id, "note_md": note_md}, now=now)
        conn.execute(
            """INSERT INTO operation_receipts(op_id,epoch_id,actor_source,command_kind,summary_md,status,
               pending_targets_json,created_at,updated_at)
               VALUES(?,?,'gw_chief_human','SEND_BRANCH_NOTE',?,'DRAINING',?,?,?)""",
            (note_id, epoch_id(conn), f"导师便签 → {node_id}", json.dumps([node_id]), now, now),
        )
    return {"ok": True, "data": {"op_id": note_id, "note_id": note_id, "node_id": node_id, "status": "DRAINING",
                                  "pending_targets": [node_id], "failed_items": []}}


def tool_chief_seed_branch(
    conn, caller_role, session_id, workspace_root, question_id, family_signature,
    blueprint_md, orthogonal_contrast, *, human_rpc_id="",
):
    _mandate(conn, "chief_seed_branch", caller_role, session_id, human_rpc_id)
    from .control_plane.proposals import _execute_seed_human_branch
    blueprint = str(blueprint_md).strip()
    if not 10 <= len(blueprint) <= 8000 or not str(family_signature).strip() or not str(orthogonal_contrast).strip():
        raise FailClosedError(ERR_INVALID_INPUT, "需要学派签名、正交差异与 10–8000 字蓝图")
    now = utc_now_iso()
    op_id = f"op_{uuid4().hex}"
    with rw_immediate_tx(conn):
        result = _execute_seed_human_branch(
            conn, workspace_root=workspace_root, target_id=question_id,
            payload={"seed_idea_md": blueprint, "mechanism_signature": family_signature,
                     "orthogonal_contrast": orthogonal_contrast},
        )
        conn.execute(
            """INSERT INTO operation_receipts(op_id,epoch_id,actor_source,command_kind,summary_md,status,created_at,updated_at,settled_at)
               VALUES(?,?,'gw_chief_human','SEED_BRANCH',?,'SETTLED',?,?,?)""",
            (op_id, epoch_id(conn), f"{question_id} 已登记人类种子 {result['node_id']}", now, now, now),
        )
    return {"ok": True, "data": {**result, "op_id": op_id, "status": "SETTLED"}}


_TEXT_QUERIES = {
    ("question", "survey"): "SELECT sec1_baseline_and_instruments_md || char(10) || sec2_l3_lemma_tree_md || char(10) || sec3_avoidance_radar_md || char(10) || sec4_explicit_gaps_md AS content FROM subproblem_living_surveys WHERE question_id=? ORDER BY revision DESC LIMIT 1",
    ("node", "manuscript"): """SELECT COALESCE(column_a_facts_md,'') || char(10) || COALESCE(column_b_hypothesis_md,'')
                                || char(10) || COALESCE(will_md,'') AS content FROM lineage_nodes WHERE node_id=?""",
    ("node", "briefing"): "SELECT sec1_mechanism || char(10) || sec2_verified_baseline || char(10) || sec3_bottleneck || char(10) || sec4_dead_ends || char(10) || sec5_immediate_will AS content FROM lineage_briefings WHERE node_id=? ORDER BY created_at DESC LIMIT 1",
    ("conference", "minutes"): "SELECT minutes_md AS content FROM wave_conferences WHERE conference_id=?",
}


def tool_chief_read(conn: sqlite3.Connection, caller_role: str, session_id: str, resource: str, offset=0, limit=4000):
    enforce_role_tool_permission(conn, caller_role, "chief_read", session_id=session_id)
    parts = resource.strip("/").split("/")
    if len(parts) > 3 and parts[0] == "archive" and parts[1].isdigit():
        archive = conn.execute("SELECT archive_abs_path FROM epoch_archives WHERE epoch_id=?", (int(parts[1]),)).fetchone()
        if archive is None:
            raise FailClosedError(ERR_NOT_FOUND, f"没有纪元 {parts[1]} 的归档")
        from contextlib import closing
        from .db_schema import open_ro_connection
        with closing(open_ro_connection(archive["archive_abs_path"])) as prior:
            result = tool_chief_read(prior, caller_role, session_id, "/".join(parts[2:]), offset, limit)
            result["data"]["resource"] = resource
            return result
    text = None
    if len(parts) == 3 and parts[0] == "node" and parts[2] == "transcript":
        node = _active_node(conn, parts[1])
        return {"ok": True, "data": {"resource": resource, "session_id": f"gw-exp-{node['node_id']}"}}
    if len(parts) == 3 and (parts[0], parts[2]) in _TEXT_QUERIES:
        row = conn.execute(_TEXT_QUERIES[parts[0], parts[2]], (parts[1],)).fetchone()
        text = str(row["content"] or "") if row else None
    elif len(parts) == 3 and parts[0] == "review" and parts[2] == "ledger":
        row = conn.execute("SELECT * FROM review_queue WHERE review_id=?", (parts[1],)).fetchone()
        if row:
            text = json.dumps({k: row[k] for k in row.keys() if k.endswith(("_md","_json","_verdict"))}, ensure_ascii=False, indent=2)
    elif len(parts) == 2 and parts[0] == "entry":
        row = conn.execute("SELECT * FROM internal_research_ledger WHERE entry_id=?", (parts[1],)).fetchone()
        if row:
            text = json.dumps({k: row[k] for k in row.keys() if k.endswith(("_md","_json"))}, ensure_ascii=False, indent=2)
    elif len(parts) == 2 and parts[0] == "receipt":
        row = conn.execute("SELECT * FROM operation_receipts WHERE op_id=?", (parts[1],)).fetchone()
        if row:
            text = json.dumps(read_receipt(row), ensure_ascii=False, indent=2)
    if text is None:
        raise FailClosedError(ERR_NOT_FOUND, f"未知或尚无内容的资源 {resource}")
    return {"ok": True, "data": page_text(resource, text, offset, limit)}


def page_text(resource: str, text: str, offset: int, limit: int) -> dict:
    encoded = text.encode("utf-16-le")
    total = len(encoded) // 2
    start = min(total, max(0, int(offset)))
    end = min(total, start + min(6000, max(2, int(limit))))
    if start and start < total and 0xDC00 <= int.from_bytes(encoded[2*start:2*start+2], "little") <= 0xDFFF:
        start += 1
    if end < total and 0xDC00 <= int.from_bytes(encoded[2*end:2*end+2], "little") <= 0xDFFF:
        end -= 1
    return {"resource": resource, "offset": start, "total_chars": total, "next_offset": end if end < total else None,
            "text": encoded[2*start:2*end].decode("utf-16-le")}

