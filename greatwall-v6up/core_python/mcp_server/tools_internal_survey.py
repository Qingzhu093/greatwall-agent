"""院内专题综述的请求、证据包和报告结案。"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from .control_plane.effects_outbox import enqueue_runtime_effect
from .control_plane.operator_policy import epoch_id
from .db.enums import ALLOWED_INTERNAL_SURVEY_SCOPES
from .db_schema import (
    ERR_INVALID_INPUT, ERR_LOCKED, ERR_NOT_FOUND,
    FailClosedError, rw_immediate_tx, utc_now_iso,
)
from .mcp_core_helpers import build_tool_receipt, enforce_role_tool_permission
from .tools_verifier_helpers import validate_library_citations


_CITATION = re.compile(r"\[((?:L[23]-|R)\d+|Obs-?\d+|obs_[A-Za-z0-9_]+)\]")
_DIRECTIVE = re.compile(
    r"(?:建议你|你应该|你必须|下一步请|请(?:立即|采用|放弃|改用|尝试)|\[(?:UNVERIFIED|DIRECTIVE)\])",
    re.IGNORECASE,
)
_MD_TABLE_SEP = re.compile(r"^\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?$")


def _extract_factual_paragraphs(report: str) -> list[str]:
    """按空行切分实质叙述段落（跳过纯标题、代码围栏与 Markdown 表格分隔行）。"""
    paragraphs: list[str] = []
    buf: list[str] = []
    in_code_fence = False
    for raw in report.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not line:
            if buf:
                paragraphs.append("\n".join(buf))
                buf = []
            continue
        if line.startswith("#") or _MD_TABLE_SEP.match(line):
            continue
        buf.append(line)
    if buf:
        paragraphs.append("\n".join(buf))
    return paragraphs


def _survey_request(conn: sqlite3.Connection, survey_req_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM internal_survey_requests WHERE survey_req_id = ? AND epoch_id = ?",
        (survey_req_id, epoch_id(conn)),
    ).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"专题综述 {survey_req_id!r} 不存在")
    return row


def _check_survey_explorer(conn: sqlite3.Connection, session_id: str, node_id: str | None) -> None:
    if node_id is None and session_id.startswith("gw-exp-"):
        node_id = session_id.removeprefix("gw-exp-")
    if session_id.startswith("gw-exp-") and session_id != f"gw-exp-{node_id}":
        raise FailClosedError(ERR_INVALID_INPUT, "专题综述调用节点必须与探索会话绑定一致")
    row = conn.execute("SELECT first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if row is None or not row["first_reflection_unlocked"]:
        raise FailClosedError(ERR_LOCKED, "探索节点完成 37% 元反思后方可请求或读取院内专题综述")


def tool_request_internal_survey(
    conn: sqlite3.Connection, caller_role: str, session_id: str, question_id: str, query_md: str,
    focus_scope: str = "QUESTION_ONLY", node_id: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "request_internal_survey", session_id=session_id, node_id=node_id)
    query = query_md.strip()
    if not 10 <= len(query) <= 1500:
        raise FailClosedError(ERR_INVALID_INPUT, f"专题查询当前 {len(query)} 字，须为 10–1500 字")
    if focus_scope not in ALLOWED_INTERNAL_SURVEY_SCOPES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 focus_scope {focus_scope!r}")
    if caller_role == "explorer" and node_id is None and session_id.startswith("gw-exp-"):
        node_id = session_id.removeprefix("gw-exp-")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        if caller_role == "explorer":
            _check_survey_explorer(conn, session_id, node_id)
        if conn.execute("SELECT 1 FROM subproblem_runtime_state WHERE question_id = ?", (question_id,)).fetchone() is None:
            raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id!r} 不存在")
        if node_id and conn.execute("SELECT 1 FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone() is None:
            raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
        epoch = epoch_id(conn)
        existing = conn.execute(
            """
            SELECT survey_req_id, status FROM internal_survey_requests
            WHERE epoch_id = ? AND requester_role = ? AND requester_node_id IS ?
              AND requester_session_id = ? AND question_id = ? AND query_md = ? AND focus_scope = ?
              AND status IN ('PENDING', 'RUNNING')
            """,
            (epoch, caller_role, node_id, session_id, question_id, query, focus_scope),
        ).fetchone()
        if existing is not None:
            data = dict(existing)
        else:
            if node_id:
                prior = conn.execute(
                    "SELECT COUNT(*) FROM internal_survey_requests WHERE epoch_id = ? AND requester_node_id = ?",
                    (epoch, node_id),
                ).fetchone()[0]
                if prior >= 2:
                    raise FailClosedError(ERR_LOCKED, "本节点两次专题综述配额已用完")
            req_id = f"isurv_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO internal_survey_requests(
                    survey_req_id, epoch_id, question_id, requester_role, requester_node_id, requester_session_id,
                    query_md, focus_scope, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (req_id, epoch, question_id, caller_role, node_id, session_id, query, focus_scope, now, now),
            )
            enqueue_runtime_effect(
                conn, effect_key=f"internal_survey:{req_id}", kind="RUN_INTERNAL_SURVEY",
                target_type="QUESTION", target_id=question_id, payload={"survey_req_id": req_id},
            )
            data = {"survey_req_id": req_id, "status": "PENDING"}
    return build_tool_receipt(
        conn=conn, tool_name="request_internal_survey", question_id=question_id, node_id=node_id,
        next_step_guidance="专题综述已排队，可继续研究并稍后拉取报告。", data=data,
    )


def tool_get_internal_survey_report(
    conn: sqlite3.Connection, caller_role: str, session_id: str, survey_req_id: str = "", question_id: str = "ALL",
    *, bound_node_id: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_internal_survey_report", session_id=session_id)
    if caller_role == "explorer":
        _check_survey_explorer(conn, session_id, bound_node_id)
    if survey_req_id:
        row = _survey_request(conn, survey_req_id)
        data = {key: row[key] for key in ("survey_req_id", "question_id", "status", "report_md", "error_note")}
        data["cited_entry_ids"] = json.loads(row["cited_entry_ids_json"])
        data["cited_obs_ids"] = json.loads(row["cited_obs_ids_json"])
    else:
        reports = conn.execute(
            """
            SELECT survey_req_id, question_id, query_md, focus_scope, status, fulfilled_at
            FROM internal_survey_requests
            WHERE epoch_id = ? AND status = 'FULFILLED' AND (? = 'ALL' OR question_id = ?)
            ORDER BY fulfilled_at DESC, survey_req_id LIMIT 20
            """,
            (epoch_id(conn), question_id, question_id),
        )
        data = {"reports": [dict(row) for row in reports]}
    return build_tool_receipt(
        conn=conn, tool_name="get_internal_survey_report", question_id=question_id,
        next_step_guidance="引用报告时保留原始证据编号和成立域。", data=data,
    )


def tool_get_internal_survey_task(
    conn: sqlite3.Connection, caller_role: str, session_id: str, survey_req_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_internal_survey_task", session_id=session_id)
    row = _survey_request(conn, survey_req_id)
    question_id = row["question_id"]
    scope = question_id if row["focus_scope"] == "QUESTION_ONLY" else "ALL"
    catalogs = {
        "catalog_cards": "SELECT * FROM v_library_mini_papers_catalog",
        "avoidance_radar": "SELECT * FROM v_library_avoidance_radar",
        "observations": (
            "SELECT obs_id, question_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text "
            "FROM observations"
        ),
    }
    data = {key: row[key] for key in ("survey_req_id", "question_id", "query_md", "focus_scope", "status")}
    for key, query in catalogs.items():
        valid = "AND obs_status IN ('VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED')" if key == "observations" else ""
        data[key] = [dict(item) for item in conn.execute(
            f"{query} WHERE (? = 'ALL' OR question_id = ?) {valid}", (scope, scope),
        )]
    return build_tool_receipt(
        conn=conn, tool_name="get_internal_survey_task", question_id=question_id,
        next_step_guidance="可从 get_chronicler_snapshot 查阅原文。逐条引用事实，客观陈述证据与前提缝隙。", data=data,
    )


def tool_publish_internal_survey_report(
    conn: sqlite3.Connection, caller_role: str, session_id: str, survey_req_id: str, report_md: str,
    cited_entry_ids: list[str], cited_obs_ids: list[str] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "publish_internal_survey_report", session_id=session_id)
    report = report_md.strip()
    if not 200 <= len(report) <= 4000:
        raise FailClosedError(ERR_INVALID_INPUT, f"专题综述当前 {len(report)} 字，须为 200–4000 字，请调整后重交")
    if _DIRECTIVE.search(report):
        raise FailClosedError(ERR_INVALID_INPUT, "专题综述不应向探索者直接下达路线指令，请仅客观综合证据")
    obs_ids = list(dict.fromkeys(cited_obs_ids or []))
    cited = set(cited_entry_ids) | set(obs_ids)
    paragraphs = _extract_factual_paragraphs(report)
    if cited != set(_CITATION.findall(report)) or not paragraphs or any(not _CITATION.search(para) for para in paragraphs):
        raise FailClosedError(ERR_INVALID_INPUT, "专题综述的每段事实须标注精确编号，正文引用须与提交列表一致")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        row = _survey_request(conn, survey_req_id)
        if row["status"] not in ("PENDING", "RUNNING"):
            raise FailClosedError(ERR_LOCKED, f"专题综述 {survey_req_id} 已结案")
        scope = row["question_id"] if row["focus_scope"] == "QUESTION_ONLY" else None
        entries = validate_library_citations(conn, cited_entry_ids, question_id=scope)
        for obs_id in obs_ids:
            obs = conn.execute(
                "SELECT question_id FROM observations WHERE obs_id = ? AND obs_status IN ('VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED')",
                (obs_id,),
            ).fetchone()
            if obs is None or (scope is not None and obs["question_id"] != scope):
                raise FailClosedError(ERR_INVALID_INPUT, f"观测 {obs_id!r} 不存在、无效或超出专题范围")
        conn.execute(
            """
            UPDATE internal_survey_requests SET status = 'FULFILLED', report_md = ?, cited_entry_ids_json = ?,
                cited_obs_ids_json = ?, chronicler_session_id = ?, updated_at = ?, fulfilled_at = ?
            WHERE survey_req_id = ?
            """,
            (report, json.dumps(entries), json.dumps(obs_ids), session_id, now, now, survey_req_id),
        )
        message = f"图书馆专题综述 {survey_req_id} 已送达，可调用 get_internal_survey_report 查阅。"
        target = row["requester_node_id"]
        enqueue_runtime_effect(
            conn, effect_key=f"internal_survey_arrived:{survey_req_id}",
            kind="DELIVER_BRANCH_NOTE" if target else "NOTIFY_CHIEF",
            target_type="NODE" if target else "QUESTION", target_id=target or row["question_id"],
            payload={
                "event_category": "INTERNAL_SURVEY_ARRIVED",
                "question_id": row["question_id"],
                "message": message,
                "survey_req_id": survey_req_id,
            },
        )
    return build_tool_receipt(
        conn=conn, tool_name="publish_internal_survey_report", question_id=row["question_id"],
        next_step_guidance=message, data={"survey_req_id": survey_req_id, "status": "FULFILLED"},
    )
