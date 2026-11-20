"""DSH `tools/post-execute` 与安全门禁轻量非阻塞 FACT_LOG 写入桥接。

供上层 DSH Cordis 中间件在普通工具执行成功后或越权拦截发生时，
异步将真实 `READ` / `USED_TOOL` / `UNAUTHORIZED_TOOL_ATTEMPT` 事实边落入已有 SQLite WAL 数据库 `epistemic_edges`。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from .db_schema import open_rw_connection, resolve_storage_paths, rw_immediate_tx, utc_now_iso


def record_fact_cli(argv: list[str] | None = None) -> int:
    """从 CLI 参数写入单条 FACT_LOG 边；数据库尚未初始化时静默跳过。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 4:
        return 0
    workspace_root, session_id, ref_id, edge_type = args[0], args[1], args[2], args[3]
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

    meta_obj = {
        "session_id": session_id[:128],
        "node_id": node_id[:128],
        "via": "dsh_bridge",
        **extra_meta,
    }
    meta_str = json.dumps(meta_obj, ensure_ascii=False)[:2000]
    edge_id = f"fedge_{uuid.uuid4().hex[:12]}"
    src_id = (node_id or session_id or "global")[:128]
    dst_id = ref_id[:256]

    conn = open_rw_connection(db_path, init_schema=False)
    try:
        with rw_immediate_tx(conn):
            conn.execute(
                """
                INSERT INTO epistemic_edges(
                    edge_id, src_id, dst_id, edge_track, edge_type, metadata_json, created_at
                ) VALUES (?, ?, ?, 'FACT_LOG', ?, ?, ?);
                """,
                (edge_id, src_id, dst_id, edge_type, meta_str, utc_now_iso()),
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(record_fact_cli())
