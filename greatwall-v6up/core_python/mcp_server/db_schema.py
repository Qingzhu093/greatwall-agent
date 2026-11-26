"""GreatWall Agent v0.3 SQLite WAL 持久化底座薄门面与公共辅助。

底层枚举、基础表、v0.3 增量表与无损迁移已拆至 `mcp_server/db/`，连接与单写者锁位于 `db_runtime.py`。
本文件保留所有历史导入兼容，并提供工作区隔离路径、FTS5 净化与依赖重审传播。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import (  # noqa: F401
    ALLOWED_AUTONOMY_MODES,
    ALLOWED_BRANCH_KINDS,
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_COMPANION_MODES,
    ALLOWED_COMPLIANCE_STAGES,
    ALLOWED_COMPLIANCE_STATUSES,
    ALLOWED_DEAD_END_CATEGORIES,
    ALLOWED_DELIVERY_MODES,
    ALLOWED_EVIDENCE_GRADES,
    ALLOWED_FACT_EDGE_TYPES,
    ALLOWED_FINAL_VERDICTS,
    ALLOWED_FORK_MODES,
    ALLOWED_GOAL_COVERAGES,
    ALLOWED_INSTRUMENT_ROLES,
    ALLOWED_INSTRUMENT_STATUSES,
    ALLOWED_INSTRUMENT_TIERS,
    ALLOWED_INTERVENTION_ACTIONS,
    ALLOWED_INTERVENTION_ACTORS,
    ALLOWED_L2_CATEGORIES,
    ALLOWED_L3_ENTRY_KINDS,
    ALLOWED_LEMMA_GAP_STATUSES,
    ALLOWED_METRIC_DIRECTIONS,
    ALLOWED_NODE_CONTROL_STATES,
    ALLOWED_NODE_STATUSES,
    ALLOWED_OBS_STATUSES,
    ALLOWED_PROPOSAL_ACTIONS,
    ALLOWED_PROPOSAL_STATUSES,
    ALLOWED_PUBLISH_TIERS,
    ALLOWED_READ_DEPTHS,
    ALLOWED_REVIEW_SOURCE_TYPES,
    ALLOWED_RUNTIME_EFFECT_KINDS,
    ALLOWED_RUNTIME_EFFECT_STATUSES,
    ALLOWED_RUNTIME_EFFECT_TARGETS,
    ALLOWED_STAGE1_VERDICTS,
    ALLOWED_SUBPROBLEM_DESIRED_STATES,
    ALLOWED_SUBPROBLEM_DISPATCH_STATES,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ALLOWED_SURVEY_STATUSES,
    ALLOWED_TICKET_RESOLUTIONS,
    ALLOWED_TRIAGE_ACTIONS,
    ALLOWED_TRIAGE_LEVELS,
    ALLOWED_VERDICT_3STATE,
    ALLOWED_VERDICTS,
    ALLOWED_WAVE_STATUSES,
    ALLOWED_WAVE_VERDICT_ACTIONS,
    ALLOWED_WORKS_TICKET_TYPES,
    BASE_SCHEMA_SQL,
    CORE_ERROR_CODES,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_EXECUTION,
    ERR_HUMAN_STOP_NOT_RECORDED,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_MISSING_MODEL_BINDING,
    ERR_NOT_FOUND,
    ERR_STORAGE,
    SCHEMA_SQL,
    SEALED_HANDOFF_TRIGGER_SQL,
    V03_SCHEMA_SQL,
    FailClosedError,
    init_database_schema,
)
from .db_runtime import (  # noqa: F401
    open_ro_connection,
    open_rw_connection_with_init,
    reset_initialized_db_cache,
    ro_consistent_tx,
    rw_immediate_tx,
)

_FTS5_META_RE = re.compile(r"[:*(){}^+\-.,;!?/\\|=<>&~@#$%\[\]\"']+")
_FTS5_RESERVED_WORDS = frozenset({"AND", "OR", "NOT", "NEAR"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def reject_null_bytes(value: Any, field_name: str = "input") -> None:
    if isinstance(value, str) and "\x00" in value:
        raise FailClosedError(ERR_INVALID_INPUT, f"{field_name} 包含非法空字节 \\x00")


def compute_workspace_hash(workspace_root: str) -> str:
    norm = os.path.realpath(workspace_root or os.getcwd())
    if os.name == "nt":
        norm = norm.lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def resolve_storage_paths(workspace_root: str = "", *, create_dirs: bool = True) -> dict[str, Path]:
    """解析并按需准备 `$PLUGIN_DATA/workspaces/<ws_hash>/` 全套物理隔离受控目录。"""
    base_data = (
        os.environ.get("GREATWALL_PLUGIN_DATA_DIR")
        or os.environ.get("PLUGIN_DATA")
        or os.environ.get("GREATWALL_DATA_DIR")
        or str(Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")) / "greatwall-v6up")
    )
    ws_hash = compute_workspace_hash(workspace_root)
    data_dir = Path(os.path.realpath(base_data)) / "workspaces" / ws_hash
    eval_artifacts_dir = data_dir / "eval_artifacts"
    job_inputs_dir = data_dir / "job_inputs"
    snapshots_dir = data_dir / "snapshots"
    hidden_calibrations_dir = data_dir / "_hidden_calibrations"
    blind_sandboxes_dir = data_dir / "blind_sandboxes"
    instrument_snapshots_dir = data_dir / "instrument_snapshots"
    skills_dir = data_dir / "skills"
    ruling_revisions_dir = data_dir / "ruling_revisions"
    frozen_deliveries_dir = data_dir / "frozen_deliveries"

    if create_dirs:
        for d in (
            data_dir,
            eval_artifacts_dir,
            job_inputs_dir,
            snapshots_dir,
            hidden_calibrations_dir,
            blind_sandboxes_dir,
            instrument_snapshots_dir,
            skills_dir,
            ruling_revisions_dir,
            frozen_deliveries_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    return {
        "data_dir": data_dir,
        "db_path": data_dir / "greatwall.db",
        "instance_lock_path": data_dir / "host.lock",
        "eval_artifacts_dir": eval_artifacts_dir,
        "job_inputs_dir": job_inputs_dir,
        "snapshots_dir": snapshots_dir,
        "hidden_calibrations_dir": hidden_calibrations_dir,
        "blind_sandboxes_dir": blind_sandboxes_dir,
        "instrument_snapshots_dir": instrument_snapshots_dir,
        "skills_ledger_path": skills_dir / "SKILL_LEDGER.json",
        "ruling_revisions_dir": ruling_revisions_dir,
        "frozen_deliveries_dir": frozen_deliveries_dir,
    }


def open_rw_connection(db_path: str | Path, *, init_schema: bool = True, force_init: bool = False) -> sqlite3.Connection:
    return open_rw_connection_with_init(
        db_path,
        init_fn=init_database_schema,
        init_schema=init_schema,
        force_init=force_init,
    )


def sanitize_fts5_query(raw_query: str) -> str:
    """净化中英文混合与标点查询词，确保 SQLite FTS5 MATCH 永远零语法崩溃。"""
    cleaned = _FTS5_META_RE.sub(" ", str(raw_query or "")).strip()
    if not cleaned:
        return ""
    tokens: list[str] = []
    for tok in cleaned.split():
        if not tok or tok.upper() in _FTS5_RESERVED_WORDS:
            continue
        safe = tok.replace('"', "")
        if safe:
            tokens.append(f'"{safe}"')
    return " OR ".join(tokens)


def propagate_dependency_recheck(conn: sqlite3.Connection, revoked_ids: list[str]) -> dict[str, list[str]]:
    """仅沿 Stage 2 显式认证的 `REQUIRED_PREMISE` 边精准传播依赖重审；`MOTIVATING_REF` 绝不连坐。"""
    raw_list = [revoked_ids] if isinstance(revoked_ids, str) else list(revoked_ids or [])
    clean_ids = [str(x).strip() for x in raw_list if str(x).strip()]
    if not clean_ids:
        return {
            "recheck_triggered_entries": [],
            "premise_revoked_branches": [],
            "motivating_or_independent_unaffected": [],
        }

    placeholders = ",".join("?" for _ in clean_ids)
    edges = conn.execute(
        f"""
        SELECT source_id, target_id, edge_type
        FROM epistemic_edges
        WHERE edge_track = 'CLAIM_DECLARED' AND target_id IN ({placeholders})
        """,
        tuple(clean_ids),
    ).fetchall()

    recheck_entries: set[str] = set()
    unaffected: set[str] = set()
    for e in edges:
        src = str(e["source_id"])
        if str(e["edge_type"]) == "REQUIRED_PREMISE":
            recheck_entries.add(src)
        else:
            unaffected.add(src)

    if recheck_entries:
        ph = ",".join("?" for _ in recheck_entries)
        conn.execute(
            f"UPDATE internal_research_ledger SET recheck_required = 1 WHERE entry_id IN ({ph})",
            tuple(sorted(recheck_entries)),
        )

    revoked_set = set(clean_ids)
    revoked_branches: set[str] = set()
    rows = conn.execute(
        "SELECT node_id, branch_id, requires_json FROM lineage_nodes WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE')"
    ).fetchall()
    for r in rows:
        reqs = json.loads(r["requires_json"] or "[]")
        if any(str(req) in revoked_set for req in reqs):
            conn.execute("UPDATE lineage_nodes SET premise_revoked = 1 WHERE node_id = ?", (r["node_id"],))
            revoked_branches.add(str(r["branch_id"]))

    return {
        "recheck_triggered_entries": sorted(recheck_entries),
        "premise_revoked_branches": sorted(revoked_branches),
        "motivating_or_independent_unaffected": sorted(unaffected - recheck_entries),
    }
