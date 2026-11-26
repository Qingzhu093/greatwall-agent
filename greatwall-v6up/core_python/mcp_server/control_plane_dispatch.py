"""GreatWall v0.3 Single-Writer 控制面内部原语分发器（仅供 Node Orchestrator / ControlService 调用）。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..evaluators.isolated_runner import RequestCancelledError
from .control_plane_service import (
    abort_lineage_node,
    approve_control_proposal,
    authorize_early_handoff,
    check_and_open_wave_conference,
    claim_runtime_effects,
    cleanup_blind_review_sandbox,
    complete_runtime_effect,
    create_control_proposal,
    evaluate_subproblem_locks,
    get_ui_full_inspector_payload,
    init_parse0_contract,
    inspect_public_rulings_draft_status,
    mark_node_yielded,
    mark_stage1_works_checked,
    pause_node,
    record_human_chat_detected,
    record_human_stop,
    record_pending_handoff,
    record_subproblem_tokens,
    recover_pending_heavy_jobs,
    renew_runtime_effect_lease,
    resume_node,
    schedule_control_plane_snapshot,
    set_autonomy_mode,
    set_subproblem_state,
    stage_blind_review_sandbox,
    submit_works_ticket,
    sync_public_inputs_to_worktree,
    sync_public_rulings,
    sync_session_pressure,
    uninitialized_schedule_snapshot,
)
from .db_schema import (
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    FailClosedError,
    open_ro_connection,
    open_rw_connection,
    resolve_storage_paths,
    ro_consistent_tx,
    rw_immediate_tx,
)
from .mcp_core_helpers import record_fact_edge
from .tool_registry import export_contracts_snapshot


def run_readonly_query(db_path: Path, fn: Any) -> Any:
    """在单一只读事务中执行只读查询；若遇旧库缺列则自动迁移一次后重试。"""
    conn: sqlite3.Connection | None = open_ro_connection(db_path)
    try:
        with ro_consistent_tx(conn):
            return fn(conn)
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "no such column" not in msg and "no such table" not in msg:
            raise
        conn.close()
        conn = None
        mig_conn = open_rw_connection(db_path, init_schema=True, force_init=True)
        mig_conn.close()
        conn = open_ro_connection(db_path)
        with ro_consistent_tx(conn):
            return fn(conn)
    finally:
        if conn is not None:
            conn.close()


def dispatch_control_call(
    method: str,
    params: dict[str, Any] | None,
    *,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Single-Writer 控制面内部桥接原语路由。"""
    if cancel_event is not None and cancel_event.is_set():
        return FailClosedError(ERR_LOCKED, f"控制面请求已取消 ({method})").to_dict()
    if method == "control_plane/describe_contracts":
        return {"ok": True, "data": export_contracts_snapshot()}

    p = dict(params or {})
    eff_ws = str(p.pop("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    conn = None
    try:
        if method in ("control_plane/schedule_snapshot", "control_plane/recover_heavy_jobs", "control_plane/ui_inspector"):
            probe_paths = resolve_storage_paths(eff_ws, create_dirs=False)
            if not probe_paths["db_path"].is_file():
                if method == "control_plane/schedule_snapshot":
                    return {"ok": True, "data": uninitialized_schedule_snapshot(max_concurrent_workers=p.get("max_concurrent_workers"))}
                if method == "control_plane/ui_inspector":
                    return {
                        "ok": True,
                        "data": {
                            "snapshot": uninitialized_schedule_snapshot(),
                            "topology_health": {},
                            "subproblem_runtime_state": [],
                            "pending_proposals": [],
                            "living_surveys": [],
                            "wave_conferences": [],
                            "open_lemma_gaps": [],
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

            if method == "control_plane/schedule_snapshot":
                res = run_readonly_query(
                    probe_paths["db_path"],
                    lambda ro_conn: schedule_control_plane_snapshot(
                        ro_conn, max_concurrent_workers=p.get("max_concurrent_workers"), workspace_root=eff_ws
                    ),
                )
                return {"ok": True, "data": res}
            if method == "control_plane/ui_inspector":
                res = run_readonly_query(
                    probe_paths["db_path"],
                    lambda ro_conn: get_ui_full_inspector_payload(
                        ro_conn,
                        workspace_root=eff_ws,
                        selected_node_id=p.get("selected_node_id"),
                        selected_worktree_rel_file=p.get("selected_worktree_rel_file"),
                    ),
                )
                return {"ok": True, "data": res}

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
                autonomy_mode=p.get("autonomy_mode"),
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

        if method == "control_plane/record_subproblem_tokens":
            record_subproblem_tokens(conn, question_id=str(p["question_id"]), delta_tokens=int(p.get("delta_tokens", 0)))
            return {"ok": True, "data": {"question_id": str(p["question_id"])}}

        if method == "control_plane/mark_stage1_works_checked":
            return {"ok": True, "data": mark_stage1_works_checked(conn)}

        if method == "control_plane/sync_public_rulings":
            res = sync_public_rulings(conn, workspace_root=eff_ws)
            refreshed_worktrees: list[str] = []
            if bool(p.get("refresh_active_worktrees", False)):
                p0_row = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
                shared_rels = json.loads(p0_row["shared_inputs_json"] or "[]") if p0_row else []
                for r in conn.execute("SELECT DISTINCT worktree_abs_path FROM lineage_nodes WHERE node_status IN ('EXPLORING','ACTIVE_REVISING')").fetchall():
                    wt = str(r["worktree_abs_path"] or "").strip()
                    if wt and Path(wt).is_dir():
                        sync_public_inputs_to_worktree(eff_ws, wt, shared_rels)
                        refreshed_worktrees.append(wt)
            res["refreshed_worktrees"] = refreshed_worktrees
            return {"ok": True, "data": res}

        if method == "control_plane/inspect_rulings_draft":
            return {"ok": True, "data": inspect_public_rulings_draft_status(conn, workspace_root=eff_ws)}

        if method == "control_plane/abort_node":
            return {"ok": True, "data": abort_lineage_node(conn, node_id=str(p["node_id"]), reason=str(p.get("reason", "ABORTED_BY_CONTROLLER")))}

        if method == "control_plane/submit_works_ticket":
            return {
                "ok": True,
                "data": submit_works_ticket(
                    conn,
                    question_id=str(p.get("question_id", "ALL")),
                    ticket_type=str(p.get("ticket_type", "INSTRUMENT_ERROR")),
                    instrument_id=p.get("instrument_id"),
                    description=str(p.get("description", p.get("reason", ""))),
                    source=str(p.get("source", "main_controller")),
                ),
            }

        if method == "control_plane/record_human_stop":
            return {"ok": True, "data": record_human_stop(conn, note=str(p.get("note", "HUMAN_UI_OR_CLI_STOP")))}

        if method == "control_plane/record_pending_handoff":
            return {
                "ok": True,
                "data": record_pending_handoff(
                    conn,
                    node_id=str(p["node_id"]),
                    mode=str(p.get("mode", "HANDOFF_70")),
                    explorer_will_md=str(p.get("explorer_will_md", "")),
                    reason=str(p.get("reason", "")),
                ),
            }

        if method == "control_plane/stage_blind_sandbox":
            return {"ok": True, "data": stage_blind_review_sandbox(conn, workspace_root=eff_ws, review_id=str(p["review_id"]))}

        if method == "control_plane/cleanup_blind_sandbox":
            return {"ok": True, "data": cleanup_blind_review_sandbox(eff_ws, str(p["review_id"]))}

        if method == "control_plane/recover_heavy_jobs":
            return {"ok": True, "data": {"recovered_jobs": recover_pending_heavy_jobs(conn, workspace_root=eff_ws, cancel_event=cancel_event)}}

        # === v0.3 新增控制面原语 ===
        if method == "control_plane/pause_node":
            return {"ok": True, "data": pause_node(conn, node_id=str(p["node_id"]), actor_source=str(p.get("actor_source", "human_ui")), reason=str(p.get("reason", "HUMAN_PAUSE")))}

        if method == "control_plane/mark_node_yielded":
            return {"ok": True, "data": mark_node_yielded(conn, node_id=str(p["node_id"]), details=p.get("details") if isinstance(p.get("details"), dict) else None)}

        if method == "control_plane/record_human_chat_detected":
            return {"ok": True, "data": record_human_chat_detected(conn, node_id=str(p["node_id"]), session_id=str(p.get("session_id", "")), message_preview=str(p.get("message_preview", "")))}

        if method == "control_plane/resume_node":
            return {"ok": True, "data": resume_node(conn, node_id=str(p["node_id"]), actor_source=str(p.get("actor_source", "human_ui")), cross_branch_note=str(p.get("cross_branch_note") or p.get("human_note_md") or ""))}

        if method == "control_plane/authorize_early_handoff":
            return {"ok": True, "data": authorize_early_handoff(conn, node_id=str(p["node_id"]), actor_source=str(p.get("actor_source", "human_ui")), reason=str(p.get("reason", "HUMAN_EARLY_HANDOFF")), cross_branch_note=str(p.get("cross_branch_note") or ""))}

        if method == "control_plane/set_subproblem_state":
            return {"ok": True, "data": set_subproblem_state(conn, question_id=str(p["question_id"]), desired_state=str(p["desired_state"]), actor_source=str(p.get("actor_source", "human_ui")), reason=str(p.get("reason", "")))}

        if method == "control_plane/set_autonomy_mode":
            return {"ok": True, "data": set_autonomy_mode(conn, autonomy_mode=str(p["autonomy_mode"]), actor_source=str(p.get("actor_source", "human_ui")))}

        if method == "control_plane/create_control_proposal":
            return {
                "ok": True,
                "data": create_control_proposal(
                    conn,
                    action_type=str(p["action_type"]),
                    target_id=str(p["target_id"]),
                    payload=p.get("payload") if isinstance(p.get("payload"), dict) else {},
                    rationale_md=str(p.get("rationale_md", "")),
                    proposed_by=str(p.get("proposed_by", "gw_chief")),
                ),
            }

        if method == "control_plane/approve_control_proposal":
            raw_dec = str(p.get("decision", "APPROVE")).strip().upper()
            norm_dec = "APPROVE" if raw_dec in ("APPROVE", "APPROVED") else ("REJECT" if raw_dec in ("REJECT", "REJECTED") else raw_dec)
            return {
                "ok": True,
                "data": approve_control_proposal(
                    conn,
                    workspace_root=eff_ws,
                    proposal_id=str(p["proposal_id"]),
                    decision=norm_dec,
                    approved_by_source=str(p.get("approved_by_source") or p.get("caller") or ""),
                ),
            }

        if method == "control_plane/evaluate_subproblem_locks":
            return {
                "ok": True,
                "data": evaluate_subproblem_locks(
                    conn,
                    question_id=p.get("question_id"),
                    semantic_saturation_requested=bool(p.get("semantic_saturation_requested", False)),
                    saturation_reason_md=str(p.get("saturation_reason_md", "")),
                ),
            }

        if method == "control_plane/open_wave_conference":
            return {"ok": True, "data": check_and_open_wave_conference(conn, question_id=str(p["question_id"]), force=bool(p.get("force", False)))}

        if method == "control_plane/claim_runtime_effects":
            res = claim_runtime_effects(
                conn,
                owner_instance_id=str(p.get("owner_instance_id") or p.get("lease_owner") or "dsh-host"),
                limit=int(p.get("limit", 16)),
                lease_sec=int(p.get("lease_sec", 60)),
                kinds=p.get("kinds"),
            )
            return {"ok": True, "data": {**res, "effects": res["claimed"]}}

        if method == "control_plane/renew_runtime_effect_lease":
            return {
                "ok": True,
                "data": renew_runtime_effect_lease(
                    conn,
                    seq=int(p.get("seq", p.get("effect_id", 0))),
                    owner_instance_id=str(p.get("owner_instance_id") or p.get("lease_owner") or "dsh-host"),
                    lease_sec=int(p.get("lease_sec", 60)),
                ),
            }

        if method == "control_plane/complete_runtime_effect":
            return {
                "ok": True,
                "data": complete_runtime_effect(
                    conn,
                    seq=int(p.get("seq", p.get("effect_id", 0))),
                    owner_instance_id=str(p.get("owner_instance_id") or p.get("lease_owner") or "dsh-host"),
                    status=str(p.get("status", "DONE")),
                    last_error=str(p.get("last_error") or p.get("error_text") or ""),
                    retry_delay_sec=int(p.get("retry_delay_sec", 0)),
                    external_handle_id=p.get("external_handle_id"),
                ),
            }

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
    except RequestCancelledError as exc:
        return FailClosedError(ERR_LOCKED, f"控制面请求已取消 ({method}): {exc}").to_dict()
    except FailClosedError as exc:
        return exc.to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"控制面异常 ({method}): {type(exc).__name__}: {exc}").to_dict()
    finally:
        if conn is not None:
            conn.close()
