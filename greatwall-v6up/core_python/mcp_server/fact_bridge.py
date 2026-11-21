"""DSH `tools/post-execute` 与安全门禁轻量非阻塞 FACT_LOG 写入桥接（v3.0）。

供上层 DSH Cordis 中间件在工具执行成功后或越权拦截发生时，
异步将真实 `READ` / `RETRIEVED` / `USED_TOOL` 事实边落入已有 SQLite WAL 数据库 `epistemic_edges`。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from .db_schema import open_rw_connection, resolve_storage_paths, rw_immediate_tx, utc_now_iso

_ALLOWED_FACT_EDGE_TYPES = frozenset({"READ", "RETRIEVED", "USED_TOOL"})


def _normalize_fact_edge_type(raw: str) -> str:
    val = str(raw or "").strip().upper()
    if val in _ALLOWED_FACT_EDGE_TYPES:
        return val
    return "USED_TOOL"


def record_fact_cli(argv: list[str] | None = None) -> int:
    """从 CLI 参数写入单条 FACT_LOG 边；数据库尚未初始化时静默跳过。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        return 0
    workspace_root, session_id, ref_id, raw_edge_type = args[0], args[1], args[2], args[3]
    node_id = args[4] if len(args) > 4 else ""
    evidence_json = args[5] if len(args) > 5 else "{}"

    try:
        paths = resolve_storage_paths(workspace_root)
    except Exception:
        return 0
    db_path: Path = paths["db_path"]
    if not db_path.exists():
        return 0

    try:
        extra_meta = json.loads(evidence_json) if evidence_json else {}
        if not isinstance(extra_meta, dict):
            extra_meta = {"raw": str(extra_meta)}
    except Exception:
        extra_meta = {"raw": str(evidence_json)}

    edge_type = _normalize_fact_edge_type(raw_edge_type)
    meta_obj = {
        "node_id": node_id[:128],
        "raw_edge_type": str(raw_edge_type)[:64],
        "via": "dsh_bridge",
        **extra_meta,
    }
    meta_str = json.dumps(meta_obj, ensure_ascii=False)[:2000]
    edge_id = f"fedge_{uuid.uuid4().hex[:12]}"
    source_id = (node_id or session_id or "global")[:128]
    target_id = ref_id[:256]

    conn = open_rw_connection(db_path, init_schema=False)
    try:
        with rw_immediate_tx(conn):
            conn.execute(
                """
                INSERT INTO epistemic_edges(
                    edge_id, source_id, target_id, edge_track, edge_type,
                    session_id, metadata_json, created_at
                ) VALUES (?, ?, ?, 'FACT_LOG', ?, ?, ?, ?);
                """,
                (
                    edge_id,
                    source_id,
                    target_id,
                    edge_type,
                    str(session_id or "")[:128],
                    meta_str,
                    utc_now_iso(),
                ),
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(record_fact_cli())
