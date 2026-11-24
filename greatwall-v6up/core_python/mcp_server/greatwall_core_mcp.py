"""长城 Agent V6-Up (v3.0) 核心 stdio JSON-RPC 2.0 MCP 服务端入口（零第三方依赖）。

完整挂载 7 大角色共 32 个单一职责窄工具（单一契约源见 `tool_registry.py`）
+ Single-Writer 控制面内部原语（`control_plane/*`）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    __package__ = "core_python.mcp_server"

from .control_plane_service import (  # noqa: E402
    abort_lineage_node,
    cleanup_blind_review_sandbox,
    get_ui_full_inspector_payload,
    init_parse0_contract,
    mark_stage1_works_checked,
    record_human_stop,
    record_pending_handoff,
    recover_pending_heavy_jobs,
    schedule_control_plane_snapshot,
    stage_blind_review_sandbox,
    submit_works_ticket,
    sync_public_inputs_to_worktree,
    sync_public_rulings,
    sync_session_pressure,
    uninitialized_schedule_snapshot,
)
from .db_schema import (  # noqa: E402
    ERR_INVALID_INPUT,
    FailClosedError,
    open_rw_connection,
    resolve_storage_paths,
    rw_immediate_tx,
)
from .mcp_core_helpers import record_fact_edge  # noqa: E402
from .tool_registry import (  # noqa: E402
    TOOL_DEFINITIONS,
    TOOL_SPEC_BY_NAME,
    export_contracts_snapshot,
)
from .tools_companion import (  # noqa: E402
    tool_get_companion_context,
    tool_record_reflection_and_unlock_pull,
    tool_save_lineage_briefing,
    tool_submit_node_handoff,
)
from .tools_explorer import (  # noqa: E402
    tool_get_library_entry,
    tool_query_library_catalog,
    tool_read_lineage_graph,
    tool_request_literature_survey,
    tool_run_isolated_eval,
)
from .tools_surveyor import (  # noqa: E402
    tool_export_stage3_final_delivery,
    tool_get_survey_requests,
    tool_publish_external_literature_card,
)
from .tools_verifier import (  # noqa: E402
    tool_get_blind_manuscript,
    tool_get_unblinded_manuscript_and_peers,
    tool_propose_salvaged_lemma,
    tool_submit_stage1_blind_ledger,
    tool_submit_stage2_unblind_verdict,
)
from .tools_logistics import (  # noqa: E402
    tool_dispatch_stagnation_five_lanes,
    tool_fork_branch,
    tool_get_logistics_dashboard,
    tool_register_method_family,
    tool_triage_node,
)
from .tools_supervisory import (  # noqa: E402
    tool_check_stage2_closure_gate,
    tool_get_supervisory_audit_snapshot,
    tool_record_compliance_check,
    tool_register_saved_graph_query,
)
from .tools_works import (  # noqa: E402
    tool_get_works_engineering_queue,
    tool_recompute_stage_b_only,
    tool_register_question_instrument,
    tool_resolve_works_ticket,
    tool_update_skill_ledger,
    tool_upgrade_instrument_with_calibration,
)

SERVER_INFO = {"name": "greatwall-v6up-core", "version": "3.0.0"}
PROTOCOL_VERSION = "2024-11-05"

_TOOL_HANDLERS: dict[str, Any] = {
    "run_isolated_eval": tool_run_isolated_eval,
    "query_library_catalog": tool_query_library_catalog,
    "get_library_entry": tool_get_library_entry,
    "request_literature_survey": tool_request_literature_survey,
    "read_lineage_graph": tool_read_lineage_graph,
    "get_companion_context": tool_get_companion_context,
    "save_lineage_briefing": tool_save_lineage_briefing,
    "record_reflection_and_unlock_pull": tool_record_reflection_and_unlock_pull,
    "submit_node_handoff": tool_submit_node_handoff,
    "get_logistics_dashboard": tool_get_logistics_dashboard,
    "register_method_family": tool_register_method_family,
    "triage_node": tool_triage_node,
    "fork_branch": tool_fork_branch,
    "dispatch_stagnation_five_lanes": tool_dispatch_stagnation_five_lanes,
    "get_survey_requests": tool_get_survey_requests,
    "publish_external_literature_card": tool_publish_external_literature_card,
    "export_stage3_final_delivery": tool_export_stage3_final_delivery,
    "get_blind_manuscript": tool_get_blind_manuscript,
    "submit_stage1_blind_ledger": tool_submit_stage1_blind_ledger,
    "get_unblinded_manuscript_and_peers": tool_get_unblinded_manuscript_and_peers,
    "submit_stage2_unblind_verdict": tool_submit_stage2_unblind_verdict,
    "propose_salvaged_lemma": tool_propose_salvaged_lemma,
    "get_works_engineering_queue": tool_get_works_engineering_queue,
    "register_question_instrument": tool_register_question_instrument,
    "upgrade_instrument_with_calibration": tool_upgrade_instrument_with_calibration,
    "recompute_stage_b_only": tool_recompute_stage_b_only,
    "update_skill_ledger": tool_update_skill_ledger,
    "resolve_works_ticket": tool_resolve_works_ticket,
    "get_supervisory_audit_snapshot": tool_get_supervisory_audit_snapshot,
    "check_stage2_closure_gate": tool_check_stage2_closure_gate,
    "record_compliance_check": tool_record_compliance_check,
    "register_saved_graph_query": tool_register_saved_graph_query,
}

# 由 tool_registry.py 自动派生 (handler, needs_workspace_root) 映射，杜绝手工失配
_TOOL_REGISTRY: dict[str, tuple[Any, bool]] = {
    name: (_TOOL_HANDLERS[name], bool(spec["needs_workspace_root"]))
    for name, spec in TOOL_SPEC_BY_NAME.items()
}


def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    workspace_root: str = "",
    caller_role: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """统一执行 32 个窄工具入口：剥离模型伪造身份，注入可信宿主 _meta 并处理 FailClosedError。"""
    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return FailClosedError(ERR_INVALID_INPUT, f"未知工具: {name!r}").to_dict()
    if arguments is not None and not isinstance(arguments, dict):
        return FailClosedError(ERR_INVALID_INPUT, "tool arguments 必须为 JSON 对象").to_dict()

    raw_args = dict(arguments or {})
    meta = raw_args.pop("_meta", None)
    if not isinstance(meta, dict):
        meta = {}

    # 严格丢弃模型参数内私夹的身份伪造字段
    for spoof_k in ("workspace_root", "caller_role", "role", "session_id"):
        raw_args.pop(spoof_k, None)

    eff_ws = str(workspace_root or meta.get("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    eff_role = str(caller_role or meta.get("caller_role", "") or meta.get("role", "")).strip()
    eff_sid = str(session_id or meta.get("session_id", "")).strip()

    fn, needs_ws = entry
    conn = None
    try:
        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        kwargs: dict[str, Any] = {
            "conn": conn,
            "caller_role": eff_role,
            "session_id": eff_sid,
            **raw_args,
        }
        if needs_ws:
            kwargs["workspace_root"] = eff_ws or str(paths["data_dir"])
        return fn(**kwargs)
    except FailClosedError as exc:
        return exc.to_dict()
    except TypeError as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"参数签名不匹配 ({name}): {exc}").to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"执行异常 ({name}): {type(exc).__name__}: {exc}").to_dict()
    finally:
        if conn is not None:
            conn.close()


def dispatch_control_call(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Single-Writer 控制面内部桥接原语（仅供 Node Orchestrator 调用，非模型侧工具）。"""
    if method == "control_plane/describe_contracts":
        return {"ok": True, "data": export_contracts_snapshot()}

    p = dict(params or {})
    eff_ws = str(p.pop("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    conn = None
    try:
        # 纯只读探测与启动恢复：若尚未初始化数据库，严禁无故创建目录与 300KB 空库
        if method in ("control_plane/schedule_snapshot", "control_plane/recover_heavy_jobs", "control_plane/ui_inspector"):
            probe_paths = resolve_storage_paths(eff_ws, create_dirs=False)
            if not probe_paths["db_path"].is_file():
                if method == "control_plane/schedule_snapshot":
                    return {
                        "ok": True,
                        "data": uninitialized_schedule_snapshot(
                            max_concurrent_workers=p.get("max_concurrent_workers")
                        ),
                    }
                if method == "control_plane/ui_inspector":
                    return {
                        "ok": True,
                        "data": {
                            "snapshot": uninitialized_schedule_snapshot(),
                            "topology_health": {},
                            "method_families": [],
                            "lineage_nodes": [],
                            "observations": [],
                            "probes": [],
                            "reviews": [],
                            "internal_ledger": [],
                            "works_tickets": [],
                            "compliance_logs": [],
                            "selected_node_detail": None,
                        },
                    }
                return {"ok": True, "data": {"recovered_jobs": []}}

        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        if method in ("control_plane/init_parse0", "control_plane/init_epoch"):
            res = init_parse0_contract(
                conn,
                goal_and_completion_md=str(p.get("goal_and_completion_md") or p.get("goal_md") or ""),
                subquestions=p.get("subquestions") or p.get("required_questions"),
                question_order=p.get("question_order"),
                initial_instruments=p.get("initial_instruments"),
                seed_families=p.get("seed_families"),
                total_budget=p.get("total_budget"),
                min_commitment_window_sec=int(p.get("min_commitment_window_sec", 0) or 0),
                delivery_spec_md=str(p.get("delivery_spec_md") or ""),
                shared_inputs_rel_paths=p.get("shared_inputs_rel_paths"),
                stage=p.get("stage") if p.get("stage") else None,
                epoch_id=int(p.get("epoch_id", 1)),
                human_signed_at=p.get("human_signed_at"),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/schedule_snapshot":
            res = schedule_control_plane_snapshot(
                conn,
                max_concurrent_workers=p.get("max_concurrent_workers"),
                workspace_root=eff_ws,
            )
            return {"ok": True, "data": res}
        if method == "control_plane/ui_inspector":
            res = get_ui_full_inspector_payload(
                conn,
                workspace_root=eff_ws,
                selected_node_id=p.get("selected_node_id"),
                selected_worktree_rel_file=p.get("selected_worktree_rel_file"),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/sync_pressure":
            res = sync_session_pressure(
                conn,
                node_id=str(p["node_id"]),
                pressure_tokens=int(p["pressure_tokens"]),
                effective_context_window=p.get("effective_context_window"),
                context_window_tokens=p.get("context_window_tokens"),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/mark_stage1_works_checked":
            res = mark_stage1_works_checked(conn)
            return {"ok": True, "data": res}
        if method == "control_plane/sync_public_rulings":
            res = sync_public_rulings(conn, workspace_root=eff_ws)
            refreshed_worktrees: list[str] = []
            if bool(p.get("refresh_active_worktrees", False)):
                p0_row = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
                shared_rels = json.loads(p0_row["shared_inputs_json"] or "[]") if p0_row else []
                for r in conn.execute(
                    "SELECT DISTINCT worktree_abs_path FROM lineage_nodes WHERE node_status IN ('EXPLORING','ACTIVE_REVISING')"
                ).fetchall():
                    wt = str(r["worktree_abs_path"] or "").strip()
                    if wt and Path(wt).is_dir():
                        sync_public_inputs_to_worktree(eff_ws, wt, shared_rels)
                        refreshed_worktrees.append(wt)
            res["refreshed_worktrees"] = refreshed_worktrees
            return {"ok": True, "data": res}
        if method == "control_plane/abort_node":
            res = abort_lineage_node(
                conn,
                node_id=str(p["node_id"]),
                reason=str(p.get("reason", "ABORTED_BY_CONTROLLER")),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/submit_works_ticket":
            res = submit_works_ticket(
                conn,
                question_id=str(p.get("question_id", "ALL")),
                ticket_type=str(p.get("ticket_type", "INSTRUMENT_ERROR")),
                instrument_id=p.get("instrument_id"),
                description=str(p.get("description", p.get("reason", ""))),
                source=str(p.get("source", "main_controller")),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/record_human_stop":
            res = record_human_stop(conn, note=str(p.get("note", "HUMAN_UI_OR_CLI_STOP")))
            return {"ok": True, "data": res}
        if method == "control_plane/record_pending_handoff":
            res = record_pending_handoff(
                conn,
                node_id=str(p["node_id"]),
                mode=str(p.get("mode", "HANDOFF_70")),
                explorer_will_md=str(p.get("explorer_will_md", "")),
                reason=str(p.get("reason", "")),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/stage_blind_sandbox":
            res = stage_blind_review_sandbox(conn, workspace_root=eff_ws, review_id=str(p["review_id"]))
            return {"ok": True, "data": res}
        if method == "control_plane/cleanup_blind_sandbox":
            res = cleanup_blind_review_sandbox(eff_ws, str(p["review_id"]))
            return {"ok": True, "data": res}
        if method == "control_plane/recover_heavy_jobs":
            res = recover_pending_heavy_jobs(conn, workspace_root=eff_ws)
            return {"ok": True, "data": {"recovered_jobs": res}}
        if method == "control_plane/fact_edge":
            with rw_immediate_tx(conn):
                record_fact_edge(
                    conn,
                    source_id=str(p.get("source_id") or p.get("src_id") or p.get("node_id") or p.get("session_id") or "host"),
                    target_id=str(p.get("target_id") or p.get("dst_id") or ""),
                    edge_type=str(p.get("edge_type") or "USED_TOOL"),
                    session_id=str(p.get("session_id") or ""),
                    metadata=p.get("metadata") if isinstance(p.get("metadata"), dict) else {},
                )
            return {"ok": True}
        return FailClosedError(ERR_INVALID_INPUT, f"未知控制面方法: {method!r}").to_dict()
    except FailClosedError as exc:
        return exc.to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"控制面异常 ({method}): {exc}").to_dict()
    finally:
        if conn is not None:
            conn.close()


def _read_next_message(stdin_buf: Any) -> tuple[dict[str, Any] | None, str]:
    while True:
        raw_line = stdin_buf.readline()
        if not raw_line:
            return None, ""
        stripped = raw_line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith(b"content-length:") or lower.startswith(b"content-type:"):
            content_length = 0
            header_line = stripped
            while True:
                if header_line.lower().startswith(b"content-length:"):
                    val_str = header_line.split(b":", 1)[1].strip().decode("ascii")
                    content_length = int(val_str)
                nxt = stdin_buf.readline()
                if not nxt or nxt in (b"\r\n", b"\n"):
                    break
                header_line = nxt.strip()
            body = stdin_buf.read(content_length)
            return json.loads(body.decode("utf-8")), "lsp"
        return json.loads(stripped.decode("utf-8")), "ndjson"


def _write_message(stdout_buf: Any, payload: dict[str, Any], framing_mode: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if framing_mode == "lsp":
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        stdout_buf.write(header + encoded)
    else:
        stdout_buf.write(encoded + b"\n")
    stdout_buf.flush()


def handle_jsonrpc_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "notifications/initialized" or msg_id is None:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOL_DEFINITIONS}}
    if method == "tools/call":
        t_name = str(params.get("name", ""))
        t_args = params.get("arguments", {})
        top_meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        res = dispatch_tool_call(
            t_name,
            t_args,
            workspace_root=str(top_meta.get("workspace_root", "") or ""),
            caller_role=str(top_meta.get("caller_role", "") or top_meta.get("role", "") or ""),
            session_id=str(top_meta.get("session_id", "") or ""),
        )
        is_err = not bool(res.get("ok", False))
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                "isError": is_err,
            },
        }
    if isinstance(method, str) and method.startswith("control_plane/"):
        res = dispatch_control_call(method, params)
        return {"jsonrpc": "2.0", "id": msg_id, "result": res}
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio() -> int:
    stdin_buf = sys.stdin.buffer
    stdout_buf = sys.stdout.buffer
    while True:
        try:
            msg, framing = _read_next_message(stdin_buf)
        except Exception as exc:
            _write_message(
                stdout_buf,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                "ndjson",
            )
            continue
        if msg is None:
            return 0
        resp = handle_jsonrpc_message(msg)
        if resp is not None:
            _write_message(stdout_buf, resp, framing or "ndjson")


if __name__ == "__main__":
    raise SystemExit(serve_stdio())
