"""GreatWall Agent v0.3 核心 stdio JSON-RPC 2.0 MCP 服务端入口（零第三方依赖）。

完整挂载 10 大角色共 47 个去重单一职责窄工具（单一契约源见 `tool_registry.py`）
+ Single-Writer 控制面内部原语（`control_plane_dispatch.py`）：
- 双线程池隔离派发（`fast_pool` 快路径 vs `compute_pool` 慢计算池）；
- 纯只读查询使用真正只读连接 `open_ro_connection` + `ro_consistent_tx` 一致快照；
- 支持标准 JSON-RPC `$/cancelRequest` 端到端真取消。
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    __package__ = "core_python.mcp_server"

from ..evaluators.isolated_runner import RequestCancelledError  # noqa: E402
from .control_plane_dispatch import dispatch_control_call, run_readonly_query  # noqa: E402
from .db_schema import (  # noqa: E402
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    FailClosedError,
    open_rw_connection,
    resolve_storage_paths,
)
from .tool_registry import (  # noqa: E402
    LONG_RUNNING_MCP_TOOLS,
    TOOL_DEFINITIONS,
    TOOL_SPEC_BY_NAME,
)
from .tools_chief import (  # noqa: E402
    tool_chief_get_overview_snapshot,
    tool_chief_preview_impact,
    tool_chief_propose_control_action,
    tool_chief_trace_entity,
)
from .tools_companion import (  # noqa: E402
    tool_get_companion_context,
    tool_record_reflection_and_unlock_pull,
    tool_save_lineage_briefing,
    tool_submit_node_handoff,
)
from .tools_explorer import (  # noqa: E402
    tool_get_library_entry,
    tool_get_living_survey,
    tool_handback_to_chief,
    tool_query_library_catalog,
    tool_read_lineage_graph,
    tool_request_literature_survey,
    tool_run_isolated_eval,
)
from .tools_library_roles import (  # noqa: E402
    tool_export_stage3_final_delivery,
    tool_get_chronicler_snapshot,
    tool_get_conference_dossier,
    tool_get_survey_requests,
    tool_publish_external_literature_card,
    tool_publish_living_survey,
    tool_record_conference_minutes,
    tool_submit_conference_statement,
    tool_submit_conference_verdict,
)
from .tools_logistics import (  # noqa: E402
    tool_fork_branch,
    tool_get_logistics_dashboard,
    tool_register_method_family,
    tool_triage_node,
)
from .tools_operator import (
    tool_chief_operate, tool_chief_read, tool_chief_seed_branch, tool_chief_send_branch_note,
)
from .tools_supervisory import (  # noqa: E402
    tool_check_stage2_closure_gate,
    tool_get_supervisory_audit_snapshot,
    tool_record_compliance_check,
    tool_register_saved_graph_query,
)
from .tools_verifier import (  # noqa: E402
    tool_get_blind_manuscript,
    tool_get_unblinded_manuscript_and_peers,
    tool_propose_salvaged_lemma,
    tool_submit_stage1_blind_ledger,
    tool_submit_stage2_unblind_verdict,
)
from .tools_works import (  # noqa: E402
    tool_get_works_engineering_queue,
    tool_recompute_stage_b_only,
    tool_register_question_instrument,
    tool_resolve_works_ticket,
    tool_update_skill_ledger,
    tool_upgrade_instrument_with_calibration,
)

SERVER_INFO = {"name": "greatwall-v6up-core", "version": "0.3.0-alpha.1"}
PROTOCOL_VERSION = "2024-11-05"

# 纯只读且无任何写库副作用的窄工具集合（排除写 FACT_LOG 的 get_library_entry 与挂载沙箱的 get_blind_manuscript / get_unblinded_manuscript_and_peers）
_PURE_READONLY_TOOLS: frozenset[str] = frozenset(
    {
        "chief_get_overview_snapshot",
        "chief_trace_entity",
        "chief_read",
        "chief_preview_impact",
        "get_living_survey",
        "query_library_catalog",
        "read_lineage_graph",
        "get_companion_context",
        "get_logistics_dashboard",
        "get_survey_requests",
        "get_chronicler_snapshot",
        "get_conference_dossier",
        "get_works_engineering_queue",
        "get_supervisory_audit_snapshot",
        "check_stage2_closure_gate",
    }
)

_COMPUTE_CONTROL_METHODS: frozenset[str] = frozenset(
    {
        "control_plane/recover_heavy_jobs",
        "control_plane/operator_finish_node_jobs",
        "control_plane/stage_blind_sandbox",
        "control_plane/cleanup_blind_sandbox",
    }
)

_TOOL_HANDLERS: dict[str, Any] = {
    # gw_chief (5)
    "chief_get_overview_snapshot": tool_chief_get_overview_snapshot,
    "chief_trace_entity": tool_chief_trace_entity,
    "chief_read": tool_chief_read,
    "chief_operate": tool_chief_operate,
    "chief_send_branch_note": tool_chief_send_branch_note,
    "chief_seed_branch": tool_chief_seed_branch,
    "chief_preview_impact": tool_chief_preview_impact,
    "chief_propose_control_action": tool_chief_propose_control_action,
    # explorer & 共享 Pull (7)
    "run_isolated_eval": tool_run_isolated_eval,
    "get_living_survey": tool_get_living_survey,
    "query_library_catalog": tool_query_library_catalog,
    "get_library_entry": tool_get_library_entry,
    "request_literature_survey": tool_request_literature_survey,
    "read_lineage_graph": tool_read_lineage_graph,
    "handback_to_chief": tool_handback_to_chief,
    # lineage_companion (5)
    "get_companion_context": tool_get_companion_context,
    "save_lineage_briefing": tool_save_lineage_briefing,
    "record_reflection_and_unlock_pull": tool_record_reflection_and_unlock_pull,
    "submit_node_handoff": tool_submit_node_handoff,
    "submit_conference_statement": tool_submit_conference_statement,
    # logistics_coordinator (4)
    "get_logistics_dashboard": tool_get_logistics_dashboard,
    "register_method_family": tool_register_method_family,
    "triage_node": tool_triage_node,
    "fork_branch": tool_fork_branch,
    # external_surveyor (2)
    "get_survey_requests": tool_get_survey_requests,
    "publish_external_literature_card": tool_publish_external_literature_card,
    # library_chronicler (3)
    "get_chronicler_snapshot": tool_get_chronicler_snapshot,
    "publish_living_survey": tool_publish_living_survey,
    "export_stage3_final_delivery": tool_export_stage3_final_delivery,
    # conference_chair (3)
    "get_conference_dossier": tool_get_conference_dossier,
    "record_conference_minutes": tool_record_conference_minutes,
    "submit_conference_verdict": tool_submit_conference_verdict,
    # library_verifier (5)
    "get_blind_manuscript": tool_get_blind_manuscript,
    "submit_stage1_blind_ledger": tool_submit_stage1_blind_ledger,
    "get_unblinded_manuscript_and_peers": tool_get_unblinded_manuscript_and_peers,
    "submit_stage2_unblind_verdict": tool_submit_stage2_unblind_verdict,
    "propose_salvaged_lemma": tool_propose_salvaged_lemma,
    # works_engineer (6)
    "get_works_engineering_queue": tool_get_works_engineering_queue,
    "register_question_instrument": tool_register_question_instrument,
    "upgrade_instrument_with_calibration": tool_upgrade_instrument_with_calibration,
    "recompute_stage_b_only": tool_recompute_stage_b_only,
    "update_skill_ledger": tool_update_skill_ledger,
    "resolve_works_ticket": tool_resolve_works_ticket,
    # supervisory_committee (4)
    "get_supervisory_audit_snapshot": tool_get_supervisory_audit_snapshot,
    "check_stage2_closure_gate": tool_check_stage2_closure_gate,
    "record_compliance_check": tool_record_compliance_check,
    "register_saved_graph_query": tool_register_saved_graph_query,
}

# 由 tool_registry.py 自动派生 (handler, needs_workspace_root, accepts_cancel_event) 映射
_TOOL_REGISTRY: dict[str, tuple[Any, bool, bool]] = {
    name: (
        _TOOL_HANDLERS[name],
        bool(spec["needs_workspace_root"]),
        "cancel_event" in inspect.signature(_TOOL_HANDLERS[name]).parameters,
    )
    for name, spec in TOOL_SPEC_BY_NAME.items()
}


class CancelRegistry:
    """按 JSON-RPC 请求 ID 跟踪取消信号的线程安全注册表。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[Any, threading.Event] = {}
        self._early_cancelled: set[Any] = set()

    def register(self, req_id: Any) -> threading.Event:
        with self._lock:
            ev = threading.Event()
            if req_id in self._early_cancelled:
                self._early_cancelled.discard(req_id)
                ev.set()
            self._events[req_id] = ev
            return ev

    def cancel(self, req_id: Any) -> bool:
        with self._lock:
            ev = self._events.get(req_id)
            if ev is not None:
                ev.set()
                return True
            if len(self._early_cancelled) < 256:
                self._early_cancelled.add(req_id)
            return False

    def unregister(self, req_id: Any) -> None:
        with self._lock:
            self._events.pop(req_id, None)
            self._early_cancelled.discard(req_id)

    def cancel_all(self) -> None:
        with self._lock:
            for ev in self._events.values():
                ev.set()


def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    workspace_root: str = "",
    caller_role: str = "",
    session_id: str = "",
    host_meta: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """统一执行全部窄工具入口：剥离模型伪造身份，注入可信宿主 _meta 并处理 FailClosedError 与取消信号。"""
    if cancel_event is not None and cancel_event.is_set():
        return FailClosedError(ERR_LOCKED, f"请求已取消 ({name})").to_dict()

    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return FailClosedError(ERR_INVALID_INPUT, f"未知工具: {name!r}").to_dict()
    if arguments is not None and not isinstance(arguments, dict):
        return FailClosedError(ERR_INVALID_INPUT, "tool arguments 必须为 JSON 对象").to_dict()

    raw_args = dict(arguments or {})
    meta = raw_args.pop("_meta", None)
    if not isinstance(meta, dict):
        meta = {}

    for spoof_k in ("workspace_root", "caller_role", "role", "session_id", "human_rpc_id", "human_message", "session_epoch_id"):
        raw_args.pop(spoof_k, None)

    if host_meta is not None:
        meta = {}
    eff_ws = str(workspace_root or meta.get("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    eff_role = str(caller_role or meta.get("caller_role", "") or meta.get("role", "")).strip()
    eff_sid = str(session_id or meta.get("session_id", "")).strip()

    fn, needs_ws, accepts_cancel = entry
    conn = None
    try:
        base_kwargs: dict[str, Any] = {
            "caller_role": eff_role,
            "session_id": eff_sid,
            **raw_args,
        }
        if name in ("chief_operate", "chief_send_branch_note", "chief_seed_branch", "handback_to_chief"):
            base_kwargs["human_rpc_id"] = str((host_meta or {}).get("human_rpc_id") or "")
        if name == "handback_to_chief":
            base_kwargs["human_message"] = str((host_meta or {}).get("human_message") or "")
        if accepts_cancel:
            base_kwargs["cancel_event"] = cancel_event

        if name in _PURE_READONLY_TOOLS:
            probe_paths = resolve_storage_paths(eff_ws, create_dirs=False)
            if probe_paths["db_path"].is_file():
                if needs_ws:
                    base_kwargs["workspace_root"] = eff_ws or str(probe_paths["data_dir"])
                return run_readonly_query(probe_paths["db_path"], lambda ro_conn: fn(conn=ro_conn, **base_kwargs))

        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        if host_meta is not None and name not in _PURE_READONLY_TOOLS:
            from .control_plane.operator_policy import epoch_id
            from .db.enums import ERR_STALE_EPOCH
            received = int(host_meta.get("session_epoch_id") or 1)
            if received != epoch_id(conn):
                raise FailClosedError(ERR_STALE_EPOCH, "此会话属于旧纪元，请打开当前纪元的会话")
        if needs_ws:
            base_kwargs["workspace_root"] = eff_ws or str(paths["data_dir"])
        return fn(conn=conn, **base_kwargs)
    except RequestCancelledError as exc:
        return FailClosedError(ERR_LOCKED, f"请求已取消 ({name}): {exc}").to_dict()
    except FailClosedError as exc:
        return exc.to_dict()
    except TypeError as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"参数签名不匹配 ({name}): {exc}").to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"执行异常 ({name}): {type(exc).__name__}: {exc}").to_dict()
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
                    content_length = int(header_line.split(b":", 1)[1].strip().decode("ascii"))
                nxt = stdin_buf.readline()
                if not nxt or nxt in (b"\r\n", b"\n"):
                    break
                header_line = nxt.strip()
            body = stdin_buf.read(content_length)
            return json.loads(body.decode("utf-8")), "lsp"
        return json.loads(stripped.decode("utf-8")), "ndjson"


def _write_message(
    stdout_buf: Any,
    payload: dict[str, Any],
    framing_mode: str,
    write_lock: threading.Lock | None = None,
) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    frame = (
        f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded
        if framing_mode == "lsp"
        else encoded + b"\n"
    )
    if write_lock is not None:
        with write_lock:
            stdout_buf.write(frame)
            stdout_buf.flush()
    else:
        stdout_buf.write(frame)
        stdout_buf.flush()


def _is_compute_request(msg: dict[str, Any]) -> bool:
    method = str(msg.get("method", ""))
    if method == "tools/call":
        params = msg.get("params") or {}
        return str(params.get("name", "")) in LONG_RUNNING_MCP_TOOLS
    return method in _COMPUTE_CONTROL_METHODS


def handle_jsonrpc_message(
    msg: dict[str, Any],
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any] | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method in ("notifications/initialized", "$/cancelRequest") or msg_id is None:
        return None
    if cancel_event is not None and cancel_event.is_set():
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32800, "message": f"Request cancelled before execution: {method}"},
        }
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
            host_meta=top_meta,
            cancel_event=cancel_event,
        )
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                "isError": not bool(res.get("ok", False)),
            },
        }
    if isinstance(method, str) and method.startswith("control_plane/"):
        res = dispatch_control_call(method, params, cancel_event=cancel_event)
        return {"jsonrpc": "2.0", "id": msg_id, "result": res}
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio(
    *,
    fast_workers: int | None = None,
    compute_workers: int | None = None,
) -> int:
    stdin_buf = sys.stdin.buffer
    stdout_buf = sys.stdout.buffer
    stdout_lock = threading.Lock()
    cancel_registry = CancelRegistry()

    eff_fast = max(2, int(fast_workers or os.environ.get("GREATWALL_FAST_WORKERS", "4") or 4))
    eff_compute = max(2, int(compute_workers or os.environ.get("GREATWALL_COMPUTE_WORKERS", "6") or 6))

    fast_pool = ThreadPoolExecutor(max_workers=eff_fast, thread_name_prefix="gw-fast")
    compute_pool = ThreadPoolExecutor(max_workers=eff_compute, thread_name_prefix="gw-compute")

    def _run_and_reply(req_msg: dict[str, Any], req_framing: str, req_id: Any, ev: threading.Event) -> None:
        try:
            resp = handle_jsonrpc_message(req_msg, cancel_event=ev)
            if resp is not None:
                _write_message(stdout_buf, resp, req_framing or "ndjson", stdout_lock)
        except Exception as exc:
            if req_id is not None:
                _write_message(
                    stdout_buf,
                    {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"Internal error: {exc}"}},
                    req_framing or "ndjson",
                    stdout_lock,
                )
        finally:
            if req_id is not None:
                cancel_registry.unregister(req_id)

    try:
        while True:
            try:
                msg, framing = _read_next_message(stdin_buf)
            except Exception as exc:
                _write_message(
                    stdout_buf,
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                    "ndjson",
                    stdout_lock,
                )
                continue
            if msg is None:
                return 0

            method = msg.get("method", "")
            if method == "$/cancelRequest":
                target_id = (msg.get("params") or {}).get("id")
                if target_id is not None:
                    cancel_registry.cancel(target_id)
                continue

            msg_id = msg.get("id")
            if method == "notifications/initialized" or msg_id is None:
                continue

            if method in ("initialize", "ping", "tools/list"):
                resp = handle_jsonrpc_message(msg)
                if resp is not None:
                    _write_message(stdout_buf, resp, framing or "ndjson", stdout_lock)
                continue

            ev = cancel_registry.register(msg_id)
            pool = compute_pool if _is_compute_request(msg) else fast_pool
            pool.submit(_run_and_reply, msg, framing, msg_id, ev)
    finally:
        cancel_registry.cancel_all()
        fast_pool.shutdown(wait=True, cancel_futures=True)
        compute_pool.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    raise SystemExit(serve_stdio())
