"""长城 V6-Up (v3.0) MCP 公共核心辅助：配置加载、31 窄工具 RBAC、统一 JSON 回执、时钟信号与夜科学题库解析。"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_FACT_EDGE_TYPES,
    ERR_AUTH,
    ERR_INVALID_INPUT,
    FailClosedError,
    reject_null_bytes,
    rw_immediate_tx,
    utc_now_iso,
)

# 7 大角色唯一授权的 31 个单一职责窄工具白名单（v3.0 唯一权威映射，与 agent_kb/05 100% 对齐）
ALLOWED_TOOLS_BY_ROLE: dict[str, frozenset[str]] = {
    "explorer": frozenset(
        {
            "run_isolated_eval",
            "query_library_catalog",
            "get_library_entry",
            "request_literature_survey",
            "read_lineage_graph",
        }
    ),
    "lineage_companion": frozenset(
        {
            "get_companion_context",
            "save_lineage_briefing",
            "record_reflection_and_unlock_pull",
            "submit_node_handoff",
        }
    ),
    "logistics_coordinator": frozenset(
        {
            "get_logistics_dashboard",
            "register_method_family",
            "triage_node",
            "fork_branch",
            "dispatch_stagnation_five_lanes",
        }
    ),
    "library_surveyor": frozenset(
        {
            "get_survey_requests",
            "publish_external_literature_card",
            "export_stage3_final_delivery",
        }
    ),
    "library_verifier": frozenset(
        {
            "get_blind_manuscript",
            "submit_stage1_blind_ledger",
            "get_unblinded_manuscript_and_peers",
            "submit_stage2_unblind_verdict",
            "propose_salvaged_lemma",
        }
    ),
    "works_engineer": frozenset(
        {
            "get_works_engineering_queue",
            "register_question_instrument",
            "upgrade_instrument_with_calibration",
            "recompute_stage_b_only",
            "update_skill_ledger",
        }
    ),
    "supervisory_committee": frozenset(
        {
            "get_supervisory_audit_snapshot",
            "check_stage2_closure_gate",
            "record_compliance_check",
            "register_saved_graph_query",
        }
    ),
}

ALL_31_TOOL_NAMES: frozenset[str] = frozenset().union(*ALLOWED_TOOLS_BY_ROLE.values())

_SQL_WRITE_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


def core_python_root() -> Path:
    return Path(__file__).resolve().parent.parent


@lru_cache(maxsize=2)
def load_raw_config() -> dict[str, Any]:
    cfg_path = core_python_root() / "config.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def load_runtime_config() -> dict[str, Any]:
    """返回扁平化合并的运行时配置（同时兼容两段嵌套结构）。"""
    raw = load_raw_config()
    flat: dict[str, Any] = {}
    for section in ("session_context_clock", "orchestration_and_eval"):
        sub = raw.get(section)
        if isinstance(sub, dict):
            flat.update(sub)
    flat["_raw"] = raw
    return flat


@lru_cache(maxsize=1)
def load_holiday_prompts() -> list[dict[str, Any]]:
    """解析 `core_python/prompts/holiday_prompts.yaml`（纯标准库解析，零 PyYAML 依赖）。"""
    yaml_path = core_python_root() / "prompts" / "holiday_prompts.yaml"
    if not yaml_path.is_file():
        return []
    items: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for raw_line in yaml_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "prompts:":
            continue
        m_id = re.match(r"^-\s+id:\s*(\d+)\s*$", line)
        if m_id:
            if cur is not None:
                items.append(cur)
            cur = {"id": int(m_id.group(1)), "scope": "reflect_37", "text": ""}
            continue
        if cur is None:
            continue
        m_scope = re.match(r"^scope:\s*(\S+)\s*$", line)
        if m_scope:
            cur["scope"] = m_scope.group(1)
            continue
        m_text = re.match(r'^text:\s*"(.*)"\s*$', line)
        if m_text:
            cur["text"] = m_text.group(1).replace('\\"', '"')
    if cur is not None:
        items.append(cur)
    return items


def next_prefixed_id(conn: sqlite3.Connection, table: str, id_col: str, prefix: str, width: int = 3) -> str:
    """基于现有最大数字后缀生成单调递增人类可读 ID（如 Obs-001, L3-001, rev_001）。"""
    rows = conn.execute(f"SELECT {id_col} FROM {table} WHERE {id_col} LIKE ?", (f"{prefix}%",)).fetchall()
    max_num = 0
    for r in rows:
        val = str(r[id_col] or "")
        tail = val[len(prefix):]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    return f"{prefix}{max_num + 1:0{width}d}"


def enforce_role_tool_permission(
    conn: sqlite3.Connection,
    caller_role: str,
    tool_name: str,
    *,
    session_id: str = "",
    node_id: str = "",
) -> None:
    """服务端强 RBAC 白名单校验：越权调工具立刻拒绝。"""
    role = str(caller_role or "").strip()
    allowed = ALLOWED_TOOLS_BY_ROLE.get(role, frozenset())
    if tool_name not in allowed:
        raise FailClosedError(
            ERR_AUTH,
            f"RBAC 越权拦截：角色 {role!r} 无权调用工具 {tool_name!r}（仅授权 {sorted(allowed)}）",
        )
    if session_id:
        reject_null_bytes(session_id, "session_id")
    if node_id:
        reject_null_bytes(node_id, "node_id")


def record_fact_edge(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    target_id: str,
    edge_type: str,
    session_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    """写入客观 `FACT_LOG` 事实边（READ / RETRIEVED / USED_TOOL）。"""
    et = str(edge_type or "USED_TOOL").strip().upper()
    if et not in ALLOWED_FACT_EDGE_TYPES:
        et = "USED_TOOL"
    eid = f"fe_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO epistemic_edges(edge_id, source_id, target_id, edge_track, edge_type, session_id, metadata_json, created_at)
        VALUES (?, ?, ?, 'FACT_LOG', ?, ?, ?, ?)
        """,
        (eid, str(source_id), str(target_id), et, str(session_id or ""), json.dumps(metadata or {}, ensure_ascii=False), utc_now_iso()),
    )
    return eid


def record_declared_refs(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    declared_refs: list[str] | None,
    session_id: str = "",
    default_edge_type: str = "MOTIVATING_REF",
) -> list[str]:
    """将作者声明引用写入 `epistemic_edges(CLAIM_DECLARED)`，v3.0 默认 `MOTIVATING_REF`（不触发连坐撤回）。"""
    if declared_refs is None:
        return []
    if not isinstance(declared_refs, list):
        raise FailClosedError(ERR_INVALID_INPUT, "declared_refs 必须为字符串数组 list[str]")
    et = str(default_edge_type or "MOTIVATING_REF").strip().upper()
    if et not in ALLOWED_CLAIMED_EDGE_TYPES:
        et = "MOTIVATING_REF"
    recorded: list[str] = []
    now = utc_now_iso()
    for item in declared_refs:
        if not isinstance(item, str):
            raise FailClosedError(ERR_INVALID_INPUT, f"declared_refs 包含非法元素类型: {type(item).__name__}")
        ref = item.strip()
        if not ref:
            raise FailClosedError(ERR_INVALID_INPUT, "declared_refs 不得包含空字符串")
        eid = f"ce_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO epistemic_edges(edge_id, source_id, target_id, edge_track, edge_type, session_id, metadata_json, created_at)
            VALUES (?, ?, ?, 'CLAIM_DECLARED', ?, ?, '{}', ?)
            """,
            (eid, str(source_id), ref, et, str(session_id or ""), now),
        )
        recorded.append(ref)
    return recorded


def compute_clock_signal(pressure_tokens: int, first_reflection_unlocked: int, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """基于 500,000 真时钟计算回合间隙信号（v3.0 彻底废除 `eval_count >= 1` 前置门槛！）。"""
    c = cfg or load_runtime_config()
    window = int(c.get("context_window_tokens", 500000))
    reflect_pct = float(c.get("context_reflect_hint_pct", 0.37))
    handoff_pct = float(c.get("context_handoff_pct", 0.70))
    pct = float(pressure_tokens) / float(max(1, window))

    trigger = None
    if pct >= handoff_pct:
        trigger = "HANDOFF_70"
    elif pct >= reflect_pct and int(first_reflection_unlocked or 0) == 0:
        trigger = "REFLECT_37"

    return {
        "pressure_tokens": int(pressure_tokens),
        "context_window_tokens": window,
        "pressure_pct": round(pct, 4),
        "first_reflection_unlocked": int(first_reflection_unlocked or 0),
        "trigger": trigger,
    }


def build_state_snapshot(conn: sqlite3.Connection, *, node_id: str = "", question_id: str = "") -> dict[str, Any]:
    cfg = load_runtime_config()
    window = int(cfg.get("context_window_tokens", 500000))
    if node_id:
        row = conn.execute(
            "SELECT question_id, branch_id, node_id, node_status, pressure_tokens, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is not None:
            pt = int(row["pressure_tokens"] or 0)
            return {
                "question_id": str(row["question_id"]),
                "branch_id": str(row["branch_id"]),
                "node_id": str(row["node_id"]),
                "node_status": str(row["node_status"]),
                "pressure_tokens": pt,
                "context_window_tokens": window,
                "pressure_pct": round(pt / float(max(1, window)), 4),
                "first_reflection_unlocked": int(row["first_reflection_unlocked"] or 0),
            }
    return {
        "question_id": str(question_id or "ALL"),
        "branch_id": "",
        "node_id": str(node_id or ""),
        "node_status": "",
        "pressure_tokens": 0,
        "context_window_tokens": window,
        "pressure_pct": 0.0,
        "first_reflection_unlocked": 0,
    }


def build_tool_receipt(
    *,
    conn: sqlite3.Connection,
    tool_name: str,
    question_id: str = "ALL",
    node_id: str = "",
    next_step_guidance: str = "",
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """统一 31 工具标准 JSON 回执外壳（对齐 agent_kb/05 §0.1 与 09 §5.1）。"""
    guidance = next_step_guidance.strip()
    if guidance and not guidance.startswith("[JIT-Guidance]"):
        guidance = f"[JIT-Guidance] {guidance}"
    return {
        "ok": True,
        "tool": tool_name,
        "state_snapshot": build_state_snapshot(conn, node_id=node_id, question_id=question_id),
        "data": data if data is not None else {},
        "warnings": list(warnings or []),
        "next_step_guidance": guidance,
    }
