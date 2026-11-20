"""治理侧公共事务辅助原语（安全 ID、盲审会话校验、FACT_LOG 引用对账）。"""
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

_SQL_WRITE_FORBIDDEN_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


def _next_id(conn: sqlite3.Connection, table: str, col: str, prefix: str, width: int = 3) -> str:
    rows = conn.execute(f"SELECT {col} FROM {table} WHERE {col} LIKE ?", (f"{prefix}%",)).fetchall()
    max_num = 0
    for r in rows:
        tail = str(r[col])[len(prefix):]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    idx = max(max_num + 1, int(conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()["cnt"] or 0) + 1)
    while True:
        cand = f"{prefix}{idx:0{width}d}"
        if conn.execute(f"SELECT 1 FROM {table} WHERE {col} = ?", (cand,)).fetchone() is None:
            return cand
        idx += 1


def _next_ledger_id(conn: sqlite3.Connection, ledger_type: str) -> str:
    prefix = "L3-" if ledger_type == "L3_VERIFIED" else "L2-"
    rows = conn.execute(
        "SELECT entry_id FROM internal_research_ledger WHERE ledger_type = ?",
        (ledger_type,),
    ).fetchall()
    max_num = 0
    for r in rows:
        val = str(r["entry_id"])
        if val.startswith(prefix) and val[len(prefix):].isdigit():
            max_num = max(max_num, int(val[len(prefix):]))
    idx = max(max_num + 1, len(rows) + 1)
    while True:
        cand = f"{prefix}{idx:03d}"
        if conn.execute("SELECT 1 FROM internal_research_ledger WHERE entry_id = ?", (cand,)).fetchone() is None:
            return cand
        idx += 1


def _require_reviewer_session(session_id: str, action_label: str = "盲审") -> str:
    sid = str(session_id or "").strip()
    if not sid:
        raise FailClosedError(
            ERR_CONFLICT,
            f"SELF_REVIEW_FORBIDDEN: {action_label}必须提供非空独立审核者 session_id（严禁空会话 ID 绕过自审门禁）",
        )
    return sid


def _extract_referenced_cards_for_blind_review(
    conn: sqlite3.Connection,
    texts: list[str],
    obs_ids: list[str],
) -> list[dict[str, Any]]:
    """提取盲审手稿与声明边引用的 [R###] / [L3-###] 卡片及 read_depth，供盲审核验阅读深度。"""
    ref_ids: list[str] = []
    seen: set[str] = set()
    ref_pat = re.compile(r"\b(R\d+|L3-\d+|L2-\d+)\b")
    for t in texts:
        for m in ref_pat.findall(str(t or "")):
            if m not in seen:
                seen.add(m)
                ref_ids.append(m)
    if obs_ids:
        oph = ",".join("?" for _ in obs_ids)
        rows = conn.execute(
            f"SELECT DISTINCT dst_id FROM epistemic_edges WHERE edge_track = 'CLAIM_DECLARED' AND src_id IN ({oph})",
            obs_ids,
        ).fetchall()
        for r in rows:
            dst = str(r["dst_id"])
            if dst not in seen:
                seen.add(dst)
                ref_ids.append(dst)

    cards: list[dict[str, Any]] = []
    for rid in ref_ids:
        ext = conn.execute(
            "SELECT ref_id, question_id, title, abstract_md, exact_preconditions_md, formulas_or_operators_md, read_depth, support_scope, source_citation FROM external_literature_cards WHERE ref_id = ?",
            (rid,),
        ).fetchone()
        if ext is not None:
            cards.append({"wing": "EXTERNAL_R", **dict(ext)})
            continue
        intl = conn.execute(
            "SELECT entry_id, question_id, ledger_type, title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md, ledger_status FROM internal_research_ledger WHERE entry_id = ?",
            (rid,),
        ).fetchone()
        if intl is not None:
            cards.append({"wing": str(intl["ledger_type"]), **dict(intl)})
    return cards


def _parse_proposer_sessions(raw: Any) -> set[str]:
    text = str(raw or "").strip()
    if not text:
        return set()
    if text.startswith("["):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                return {str(x).strip() for x in loaded if str(x).strip()}
        except Exception:
            pass
    return {s.strip() for s in text.split(",") if s.strip()}


def _collect_proposer_sessions(conn: sqlite3.Connection, node_id: str, logistics_session_id: str) -> str:
    sessions: list[str] = []
    seen: set[str] = set()
    rows = conn.execute(
        "SELECT metadata_json FROM epistemic_edges WHERE edge_track = 'FACT_LOG' AND src_id = ?",
        (node_id,),
    ).fetchall()
    for r in rows:
        try:
            meta = json.loads(str(r["metadata_json"] or "{}"))
            sid = str(meta.get("session_id") or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                sessions.append(sid)
        except Exception:
            continue
    for extra in (logistics_session_id or "").strip(),:
        if extra and extra not in seen:
            seen.add(extra)
            sessions.append(extra)
    return json.dumps(sessions, ensure_ascii=False)


def _audit_node_unread_citations(conn: sqlite3.Connection, node_id: str) -> dict[str, Any]:
    """核对节点在 observations 中声明的 cited_refs 是否均存在于该节点/祖先 FACT_LOG READ 边中。"""
    anc_rows = conn.execute(
        """
        WITH RECURSIVE anc AS (
            SELECT node_id, parent_node_id FROM lineage_nodes WHERE node_id = ?
            UNION ALL
            SELECT p.node_id, p.parent_node_id FROM lineage_nodes p JOIN anc ON anc.parent_node_id = p.node_id
        )
        SELECT node_id FROM anc
        """,
        (node_id,),
    ).fetchall()
    anc_ids = [str(r["node_id"]) for r in anc_rows] or [node_id]
    ph = ",".join("?" for _ in anc_ids)

    read_dsts = {
        str(r["dst_id"])
        for r in conn.execute(
            f"SELECT DISTINCT dst_id FROM epistemic_edges WHERE edge_track = 'FACT_LOG' AND edge_type = 'READ' AND src_id IN ({ph})",
            anc_ids,
        ).fetchall()
    }
    obs_ids = [
        str(r["obs_id"])
        for r in conn.execute("SELECT obs_id FROM observations WHERE node_id = ?", (node_id,)).fetchall()
    ]
    unread: list[str] = []
    verified_read: list[str] = []
    if obs_ids:
        oph = ",".join("?" for _ in obs_ids)
        declared = conn.execute(
            f"SELECT DISTINCT dst_id, edge_type FROM epistemic_edges WHERE edge_track = 'CLAIM_DECLARED' AND src_id IN ({oph})",
            obs_ids,
        ).fetchall()
        for r in declared:
            dst = str(r["dst_id"])
            if dst.startswith(("Obs-", "node_")):
                continue
            if dst in read_dsts:
                verified_read.append(dst)
            else:
                unread.append(dst)
    return {"verified_read_refs": verified_read, "unread_claimed_refs": unread}


