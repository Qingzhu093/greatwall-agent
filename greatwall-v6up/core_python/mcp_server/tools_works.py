"""长城 V6-Up (v3.0) works_engineer（工造司 · 科研仪器科）5 个单一职责窄工具。"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..evaluators.isolated_runner import (
    RequestCancelledError,
    run_calibration_suite,
    run_stage_b_revaluation,
    sha256_file,
)

from .control_plane_service import sync_public_instruments_to_all_active_worktrees
from .db_schema import (
    ALLOWED_INSTRUMENT_ROLES,
    ALLOWED_TICKET_RESOLUTIONS,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_NOT_FOUND,
    FailClosedError,
    propagate_dependency_recheck,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    core_python_root,
    enforce_role_tool_permission,
    next_prefixed_id,
)

_SKILL_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _resolve_ws_or_core_file(workspace_root: str, rel_path: str) -> Path:
    ws = Path(os.path.realpath(workspace_root))
    c1 = Path(os.path.realpath(ws / rel_path))
    if c1.is_file():
        return c1
    c2 = Path(os.path.realpath(core_python_root() / rel_path))
    if c2.is_file():
        return c2
    raise FailClosedError(ERR_NOT_FOUND, f"找不到相对路径文件 {rel_path!r}（已检查工作区与 core_python）")


def _freeze_instrument_snapshot(
    workspace_root: str,
    instrument_id: str,
    version: int,
    inst_abs: Path,
    inst_sha: str,
) -> str:
    """将已通过校准的仪器源码按版本冻结归档至不可变快照目录，防止同路径连续升版串版本。"""
    paths = resolve_storage_paths(workspace_root)
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(instrument_id))
    dst = paths["instrument_snapshots_dir"] / f"{safe_id}_v{int(version)}_{inst_sha[:10]}{inst_abs.suffix or '.py'}"
    shutil.copy2(inst_abs, dst)
    return str(dst)


def _norm_rel_path(workspace_root: str, abs_path: Path, raw_rel: str) -> str:
    ws = Path(os.path.realpath(workspace_root))
    try:
        return abs_path.relative_to(ws).as_posix()
    except ValueError:
        try:
            return abs_path.relative_to(core_python_root()).as_posix()
        except ValueError:
            return str(raw_rel).replace("\\", "/")


def tool_get_works_engineering_queue(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    """纯查 SQLite (<50ms) 返回仪器清单、健康熔断状态、故障/痛点工单与 `pending_revalidation` 待重评队列。"""
    enforce_role_tool_permission(conn, caller_role, "get_works_engineering_queue", session_id=session_id)
    qf = str(question_id or "ALL").strip()

    if qf.upper() == "ALL":
        insts = [dict(r) for r in conn.execute("SELECT * FROM instruments ORDER BY question_id, instrument_id, version DESC").fetchall()]
        tickets = [dict(r) for r in conn.execute("SELECT * FROM works_engineering_queue ORDER BY status, created_at ASC").fetchall()]
        revals = [dict(r) for r in conn.execute("SELECT * FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at ASC").fetchall()]
    else:
        insts = [dict(r) for r in conn.execute("SELECT * FROM instruments WHERE question_id = ? ORDER BY instrument_id, version DESC", (qf,)).fetchall()]
        tickets = [dict(r) for r in conn.execute("SELECT * FROM works_engineering_queue WHERE question_id = ? ORDER BY status, created_at ASC", (qf,)).fetchall()]
        revals = [dict(r) for r in conn.execute("SELECT * FROM pending_revalidation_queue WHERE question_id = ? AND status = 'PENDING' ORDER BY created_at ASC", (qf,)).fetchall()]

    unhealthy = [i for i in insts if int(i.get("is_active") or 0) == 1 and str(i.get("health_status")) == "UNHEALTHY"]
    return build_tool_receipt(
        conn=conn,
        tool_name="get_works_engineering_queue",
        question_id=qf,
        next_step_guidance=(
            f"现有 {len(insts)} 条仪器记录（熔断 {len(unhealthy)} 个）、{len(tickets)} 条工单、{len(revals)} 条待重评观测。"
            + (" 存在待重评队列，请逐条调 recompute_stage_b_only 重算（缺字段将诚实标 INCOMPATIBLE）。" if revals else "")
        ),
        data={
            "instruments": insts,
            "unhealthy_instruments": unhealthy,
            "engineering_tickets": tickets,
            "pending_revalidation": revals,
        },
    )


def tool_register_question_instrument(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    question_id: str,
    instrument_id: str,
    instrument_role: str,
    instrument_rel_path: str,
    calibration_suite_rel_path: str | None = None,
    artifact_schema: str = "python_run",
    plugin_protocol_version: str = "v3",
    default_spec: dict[str, Any] | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """注册新科研仪器：VERDICT 强跑独立校准集（100% 匹配自声明预期），PROBE/ENV 可免校准集。"""
    enforce_role_tool_permission(conn, caller_role, "register_question_instrument", session_id=session_id)
    iid = str(instrument_id or "").strip()
    role_u = str(instrument_role or "").strip().upper()
    if not iid:
        raise FailClosedError(ERR_INVALID_INPUT, "instrument_id 不能为空")
    if role_u not in ALLOWED_INSTRUMENT_ROLES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 instrument_role={instrument_role!r}，仅允许 {sorted(ALLOWED_INSTRUMENT_ROLES)}")

    existing = conn.execute("SELECT 1 FROM instruments WHERE instrument_id = ? LIMIT 1", (iid,)).fetchone()
    if existing is not None:
        raise FailClosedError(ERR_CONFLICT, f"仪器 {iid!r} 已注册，请走 upgrade_instrument_with_calibration 校准升版")

    inst_abs = _resolve_ws_or_core_file(workspace_root, instrument_rel_path)
    norm_inst_rel = _norm_rel_path(workspace_root, inst_abs, instrument_rel_path)
    inst_sha = sha256_file(inst_abs)

    cal_rel: str | None = None
    cal_report: dict[str, Any] | None = None
    if role_u == "VERDICT":
        if not str(calibration_suite_rel_path or "").strip():
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"VERDICT 判定器 {iid!r} 必须附带 >= 1 条独立校准用例 calibration_suite_rel_path（PROBE/ENV 可传 null）",
            )
    if str(calibration_suite_rel_path or "").strip():
        cal_abs = _resolve_ws_or_core_file(workspace_root, str(calibration_suite_rel_path))
        cal_rel = _norm_rel_path(workspace_root, cal_abs, str(calibration_suite_rel_path))
        cal_report = run_calibration_suite(
            instrument_path=inst_abs,
            instrument_role=role_u,
            calibration_suite_path=cal_abs,
            workspace_root=workspace_root,
            artifact_schema=artifact_schema,
            cancel_event=cancel_event,
        )
        if not cal_report.get("passed"):
            raise FailClosedError(
                ERR_INVARIANT,
                f"校准集回归拦截：仪器 {iid!r} 未 100% 匹配校准用例自声明预期（通过 {cal_report.get('passed_count')}/{cal_report.get('total')}，失败明细：{cal_report.get('failed_cases') or cal_report.get('error')}）",
            )

    now = utc_now_iso()
    spec_json = json.dumps(default_spec if isinstance(default_spec, dict) else {}, ensure_ascii=False)
    with rw_immediate_tx(conn):
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelledError(f"仪器注册 {iid!r} 已取消，拒绝入库")
        if conn.execute("SELECT 1 FROM instruments WHERE instrument_id = ? LIMIT 1", (iid,)).fetchone() is not None:
            raise FailClosedError(ERR_CONFLICT, f"仪器 {iid!r} 已被并发注册，请走 upgrade_instrument_with_calibration")
        frozen_snap = _freeze_instrument_snapshot(workspace_root, iid, 1, inst_abs, inst_sha)
        conn.execute(
            """
            INSERT INTO instruments(
                instrument_id, version, question_id, instrument_role, instrument_rel_path,
                frozen_snapshot_path, instrument_sha256, calibration_suite_rel_path, artifact_schema,
                plugin_protocol_version, health_status, consecutive_error_count, is_active,
                default_spec_json, created_at, updated_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'HEALTHY', 0, 1, ?, ?, ?)
            """,
            (
                iid,
                question_id,
                role_u,
                norm_inst_rel,
                frozen_snap,
                inst_sha,
                cal_rel,
                str(artifact_schema or "python_run").strip(),
                str(plugin_protocol_version or "v3").strip(),
                spec_json,
                now,
                now,
            ),
        )

    sync_public_instruments_to_all_active_worktrees(conn, workspace_root)

    return build_tool_receipt(
        conn=conn,
        tool_name="register_question_instrument",
        question_id=question_id,
        next_step_guidance=f"仪器 {iid} v1 ({role_u}) 已通过校准集并激活（SHA={inst_sha[:12]}，公开 PROBE/ENV 与仪器目录已同步至活跃 Worktree）。",
        data={
            "question_id": question_id,
            "instrument_id": iid,
            "version": 1,
            "instrument_role": role_u,
            "instrument_sha256": inst_sha,
            "calibration_report": cal_report,
        },
    )


def tool_upgrade_instrument_with_calibration(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    question_id: str,
    instrument_id: str,
    new_instrument_rel_path: str,
    calibration_suite_rel_path: str,
    artifact_schema: str | None = None,
    default_spec: dict[str, Any] | None = None,
    cancel_event: Any = None,
    resolved_ticket_ids: list[str] | None = None,
    upgrade_summary_md: str = "",
) -> dict[str, Any]:
    """校准集回归驱动仪器升版（100% 过校准即直接升版，支持同步更新 artifact_schema 与 default_spec，仅局部将该仪器旧观测入待重评队列，绝零误杀他题）。"""
    enforce_role_tool_permission(conn, caller_role, "upgrade_instrument_with_calibration", session_id=session_id)
    cur = conn.execute(
        "SELECT * FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    if cur is None:
        raise FailClosedError(ERR_NOT_FOUND, f"仪器 {instrument_id!r} 尚未注册，请先调 register_question_instrument")
    if str(cur["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"仪器 {instrument_id!r} 归属 {cur['question_id']!r} 而非 {question_id!r}")

    ticket_ids = list(dict.fromkeys(resolved_ticket_ids or []))
    summary = upgrade_summary_md.strip()
    if ticket_ids and not summary:
        raise FailClosedError(ERR_INVALID_INPUT, "结案 resolved_ticket_ids 时必须提供非空 upgrade_summary_md")

    new_abs = _resolve_ws_or_core_file(workspace_root, new_instrument_rel_path)
    norm_new_rel = _norm_rel_path(workspace_root, new_abs, new_instrument_rel_path)
    cal_abs = _resolve_ws_or_core_file(workspace_root, calibration_suite_rel_path)
    norm_cal_rel = _norm_rel_path(workspace_root, cal_abs, calibration_suite_rel_path)

    role_u = str(cur["instrument_role"])
    art_schema = str(artifact_schema).strip() if (artifact_schema and str(artifact_schema).strip()) else str(cur["artifact_schema"])
    eff_default_spec_json = (
        json.dumps(default_spec, ensure_ascii=False)
        if isinstance(default_spec, dict)
        else str(cur["default_spec_json"] or "{}")
    )
    cal_report = run_calibration_suite(
        instrument_path=new_abs,
        instrument_role=role_u,
        calibration_suite_path=cal_abs,
        workspace_root=workspace_root,
        artifact_schema=art_schema,
        cancel_event=cancel_event,
    )
    if not cal_report.get("passed"):
        raise FailClosedError(
            ERR_INVARIANT,
            f"校准集升版阻断：新仪器 {norm_new_rel} 未 100% 匹配校准预期（通过 {cal_report.get('passed_count')}/{cal_report.get('total')}，失败：{cal_report.get('failed_cases') or cal_report.get('error')}）",
        )

    new_sha = sha256_file(new_abs)
    now = utc_now_iso()
    queued_obs: list[str] = []

    with rw_immediate_tx(conn):
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelledError(f"仪器升版 {instrument_id!r} 已取消，拒绝升版入库")
        max_row = conn.execute(
            "SELECT MAX(version) AS max_ver FROM instruments WHERE instrument_id = ?",
            (instrument_id,),
        ).fetchone()
        new_ver = int(max_row["max_ver"] or cur["version"]) + 1
        frozen_snap = _freeze_instrument_snapshot(workspace_root, instrument_id, new_ver, new_abs, new_sha)
        conn.execute(
            "UPDATE instruments SET is_active = 0, updated_at = ? WHERE instrument_id = ? AND is_active = 1",
            (now, instrument_id),
        )
        conn.execute(
            """
            INSERT INTO instruments(
                instrument_id, version, question_id, instrument_role, instrument_rel_path,
                frozen_snapshot_path, instrument_sha256, calibration_suite_rel_path, artifact_schema,
                plugin_protocol_version, health_status, consecutive_error_count, is_active,
                default_spec_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'HEALTHY', 0, 1, ?, ?, ?)
            """,
            (
                instrument_id,
                new_ver,
                question_id,
                role_u,
                norm_new_rel,
                frozen_snap,
                new_sha,
                norm_cal_rel,
                art_schema,
                str(cur["plugin_protocol_version"]),
                eff_default_spec_json,
                now,
                now,
            ),
        )
        # 1) 连续升版收敛：若此前已有指向旧版本的 PENDING 待重评单，直接将其目标版本提升至最新版 new_ver（绝不漏评新版！）
        existing_pending = conn.execute(
            """
            SELECT queue_id, obs_id FROM pending_revalidation_queue
            WHERE question_id = ? AND target_instrument_id = ? AND status = 'PENDING' AND target_version < ?
            """,
            (question_id, instrument_id, new_ver),
        ).fetchall()
        for erow in existing_pending:
            conn.execute(
                "UPDATE pending_revalidation_queue SET target_version = ?, updated_at = ? WHERE queue_id = ?",
                (new_ver, now, str(erow["queue_id"])),
            )
            queued_obs.append(str(erow["obs_id"]))

        # 2) 仅选择性将本仪器旧版本的有效观测转入 pending_revalidation_queue（绝不波及其他子题或其他仪器！）
        affected = conn.execute(
            """
            SELECT obs_id FROM observations
            WHERE question_id = ? AND instrument_id = ? AND instrument_version < ?
              AND obs_status IN ('VALID_PASS', 'MEASURED_REJECTION', 'VALID_UNDECIDED')
            """,
            (question_id, instrument_id, new_ver),
        ).fetchall()
        for row in affected:
            oid = str(row["obs_id"])
            qid_row = f"reval_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO pending_revalidation_queue(queue_id, obs_id, question_id, target_instrument_id, target_version, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (qid_row, oid, question_id, instrument_id, new_ver, now, now),
            )
            conn.execute(
                "UPDATE observations SET obs_status = 'PENDING_REVALIDATION', updated_at = ? WHERE obs_id = ?",
                (now, oid),
            )
            queued_obs.append(oid)
        if queued_obs:
            propagate_dependency_recheck(conn, queued_obs)

        for ticket_id in ticket_ids:
            updated = conn.execute(
                """
                UPDATE works_engineering_queue
                SET status = 'RESOLVED', resolution_note = ?, resolved_by_version = ?, updated_at = ?
                WHERE ticket_id = ? AND question_id = ? AND instrument_id = ? AND status = 'OPEN'
                """,
                (f"[Instrument v{new_ver} 校准通过自动结案] {summary}", new_ver, now,
                 ticket_id, question_id, instrument_id),
            )
            if updated.rowcount != 1:
                raise FailClosedError(ERR_INVALID_INPUT, f"工单 {ticket_id!r} 必须属于本子题、仪器且处于 OPEN")

    sync_public_instruments_to_all_active_worktrees(conn, workspace_root)

    return build_tool_receipt(
        conn=conn,
        tool_name="upgrade_instrument_with_calibration",
        question_id=question_id,
        next_step_guidance=(
            f"仪器 {instrument_id} 已通过 100% 校准回归并升版至 v{new_ver}（未波及其他子题）。"
            f" 共 {len(queued_obs)} 条旧观测已入 pending_revalidation_queue，请调 recompute_stage_b_only 重评。"
        ),
        data={
            "question_id": question_id,
            "instrument_id": instrument_id,
            "new_version": new_ver,
            "new_instrument_sha256": new_sha,
            "calibration_report": cal_report,
            "pending_revalidation_obs_ids": queued_obs,
            "resolved_ticket_ids": ticket_ids,
        },
    )


def tool_recompute_stage_b_only(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    obs_id: str,
    question_id: str,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """诚实重评：永久保留旧 [Obs###] 不覆盖，成功则生成绑定新版的新 [Obs###] 并按精确 target_version 结案队列；缺字段诚实标 INCOMPATIBLE。"""
    enforce_role_tool_permission(conn, caller_role, "recompute_stage_b_only", session_id=session_id)
    obs = conn.execute("SELECT * FROM observations WHERE obs_id = ?", (obs_id,)).fetchone()
    if obs is None:
        raise FailClosedError(ERR_NOT_FOUND, f"观测 {obs_id!r} 不存在")
    if str(obs["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"观测 {obs_id!r} 不属于子题 {question_id!r}")

    inst_id = str(obs["instrument_id"])
    # 优先严格按待重评队列登记的 target_version 执行，避免跨版升版时错位重评与误关队列
    pending_q = conn.execute(
        """
        SELECT queue_id, target_instrument_id, target_version
        FROM pending_revalidation_queue
        WHERE obs_id = ? AND status = 'PENDING'
        ORDER BY created_at ASC LIMIT 1
        """,
        (obs_id,),
    ).fetchone()
    if pending_q is not None:
        target_inst_id = str(pending_q["target_instrument_id"] or inst_id)
        target_ver = int(pending_q["target_version"])
        new_inst = conn.execute(
            "SELECT * FROM instruments WHERE instrument_id = ? AND version = ?",
            (target_inst_id, target_ver),
        ).fetchone()
        inst_id = target_inst_id
    else:
        new_inst = conn.execute(
            "SELECT * FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
            (inst_id,),
        ).fetchone()
    if new_inst is None:
        raise FailClosedError(ERR_NOT_FOUND, f"仪器 {inst_id!r} 缺少目标版本")

    stage_a_path = str(obs["stage_a_artifact_path"] or "").strip()
    if not stage_a_path or not Path(stage_a_path).is_file():
        raise FailClosedError(ERR_NOT_FOUND, f"持久化 stage_a_output.json 缺失: {stage_a_path!r}")

    # 优先加载该版本冻结的不可变仪器源码快照，并强制比对 SHA-256 杜绝同路径覆写错版！
    frozen_snap_raw = str(new_inst["frozen_snapshot_path"] or "").strip() if "frozen_snapshot_path" in new_inst.keys() else ""
    inst_abs: Path | None = Path(frozen_snap_raw) if (frozen_snap_raw and Path(frozen_snap_raw).is_file()) else None
    if inst_abs is None:
        inst_abs = _resolve_ws_or_core_file(workspace_root, str(new_inst["instrument_rel_path"]))
    expected_sha = str(new_inst["instrument_sha256"] or "").strip()
    actual_sha = sha256_file(inst_abs)
    if expected_sha and actual_sha != expected_sha:
        raise FailClosedError(
            ERR_INVARIANT,
            f"仪器 {inst_id} v{new_inst['version']} 源码哈希校验失败（预期 {expected_sha[:12]}，实际 {actual_sha[:12]}）：目标路径已被其他版本覆写，拒绝产出版本失真的重评收据！",
        )
    spec = json.loads(obs["spec_json"] or "{}")
    if not isinstance(spec, dict):
        spec = {}
    run_ver = int(new_inst["version"])
    spec["instrument_version"] = run_ver

    reval = run_stage_b_revaluation(
        instrument_path=inst_abs,
        instrument_role=str(new_inst["instrument_role"]),
        stage_a_output_path=stage_a_path,
        code_snapshot_path=obs["frozen_code_snapshot_path"],
        spec=spec,
        tier=str(obs["tier"]),
        cancel_event=cancel_event,
    )
    now = utc_now_iso()
    target_queue_id = str(pending_q["queue_id"]) if pending_q is not None else None

    # 严格区分：① 旧产物缺字段/结构不兼容 -> 诚实标 INCOMPATIBLE；② 新版仪器自身故障 -> 保留队列不甩锅给历史证据！
    if reval.get("incompatible"):
        superseded_by_newer = False
        with rw_immediate_tx(conn):
            if cancel_event is not None and cancel_event.is_set():
                raise RequestCancelledError(f"Stage B 重评 {obs_id!r} 已取消，拒绝落库")
            active_inst = conn.execute(
                "SELECT version FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
                (inst_id,),
            ).fetchone()
            active_ver = int(active_inst["version"]) if active_inst is not None else run_ver
            if target_queue_id:
                cur_q = conn.execute(
                    """
                    UPDATE pending_revalidation_queue
                    SET status = 'INCOMPATIBLE', updated_at = ?
                    WHERE queue_id = ? AND target_version = ? AND status = 'PENDING'
                    """,
                    (now, target_queue_id, run_ver),
                )
                superseded_by_newer = cur_q.rowcount == 0 and active_ver > run_ver
            else:
                conn.execute(
                    "UPDATE pending_revalidation_queue SET status = 'INCOMPATIBLE', updated_at = ? WHERE obs_id = ? AND target_version = ? AND status = 'PENDING'",
                    (now, obs_id, run_ver),
                )
                superseded_by_newer = active_ver > run_ver
            if not superseded_by_newer:
                conn.execute(
                    "UPDATE observations SET obs_status = 'INCOMPATIBLE', details_text = ?, updated_at = ? WHERE obs_id = ?",
                    (f"[INCOMPATIBLE] {reval.get('details', '')}", now, obs_id),
                )
        return build_tool_receipt(
            conn=conn,
            tool_name="recompute_stage_b_only",
            question_id=question_id,
            next_step_guidance=(
                f"重评期间仪器 {inst_id} 已升版至更高版本，旧 v{run_ver} 不兼容结果未误关新版待重评队列。"
                if superseded_by_newer
                else f"旧观测 {obs_id} 缺少新版仪器 {inst_id} v{run_ver} 所需字段，已诚实标记为 INCOMPATIBLE 并结案对应重评队列。"
            ),
            data={
                "old_obs_id": obs_id,
                "new_obs_id": None,
                "status": "SUPERSEDED_BY_NEWER_INSTRUMENT" if superseded_by_newer else "INCOMPATIBLE",
                "target_version": run_ver,
                "details": str(reval.get("details") or ""),
            },
        )

    if reval.get("status") in ("INSTRUMENT_ERROR", "INFRA_ERROR"):
        return build_tool_receipt(
            conn=conn,
            tool_name="recompute_stage_b_only",
            question_id=question_id,
            next_step_guidance=f"新版仪器 {inst_id} v{run_ver} 自身运行时故障（{reval.get('status')}），未误判旧观测 {obs_id} 为 INCOMPATIBLE，请先修复仪器后重试重评。",
            data={
                "old_obs_id": obs_id,
                "new_obs_id": None,
                "status": str(reval.get("status")),
                "target_version": run_ver,
                "details": str(reval.get("details") or ""),
            },
        )

    # 重评成功：在单写者事务内统一分配新 Obs 编号、检查并发升版、按精确 target_version 结案队列！
    raw_new_obs_status = str(reval["obs_status"])
    stale_due_to_upgrade = False
    active_ver = run_ver
    with rw_immediate_tx(conn):
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelledError(f"Stage B 重评 {obs_id!r} 已取消，拒绝入库")
        active_inst = conn.execute(
            "SELECT version FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
            (inst_id,),
        ).fetchone()
        active_ver = int(active_inst["version"]) if active_inst is not None else run_ver
        stale_due_to_upgrade = active_ver > run_ver and raw_new_obs_status in (
            "VALID_PASS",
            "MEASURED_REJECTION",
            "VALID_UNDECIDED",
        )
        # 若原 obs_id 已有指向更新版本 active_ver 的 PENDING 队列，说明本条 run_ver 结果一出生就已被取代：
        # 直接记为 SUPERSEDED_REVALIDATED，绝不制造无待办的 PENDING_REVALIDATION 孤儿观测！
        still_pending = (
            conn.execute(
                """
                SELECT 1 FROM pending_revalidation_queue
                WHERE obs_id = ? AND target_instrument_id = ? AND target_version = ? AND status = 'PENDING'
                LIMIT 1
                """,
                (obs_id, inst_id, active_ver),
            ).fetchone()
            if stale_due_to_upgrade
            else None
        )
        if stale_due_to_upgrade:
            new_obs_status = "SUPERSEDED_REVALIDATED" if still_pending is not None else "PENDING_REVALIDATION"
        else:
            new_obs_status = raw_new_obs_status
        new_obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
        conn.execute(
            """
            INSERT INTO observations(
                obs_id, question_id, branch_id, node_id, instrument_id, instrument_version, tier,
                candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256, cache_key,
                frozen_code_snapshot_path, stage_a_artifact_path, revalidated_from_obs_id, obs_status, tracks_json,
                details_text, linguistic_prediction, spec_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_obs_id,
                question_id,
                str(obs["branch_id"]),
                str(obs["node_id"]),
                inst_id,
                run_ver,
                str(obs["tier"]),
                str(obs["candidate_entry_sha256"]),
                str(obs["tools_dir_sha256"]),
                str(obs["spec_sha256"]),
                str(new_inst["instrument_sha256"]),
                obs["frozen_code_snapshot_path"],
                stage_a_path,
                obs_id,
                new_obs_status,
                json.dumps(reval.get("tracks") or {}, ensure_ascii=False),
                str(reval.get("details") or ""),
                str(obs["linguistic_prediction"] or ""),
                json.dumps(spec, ensure_ascii=False),
                now,
                now,
            ),
        )
        if target_queue_id:
            conn.execute(
                """
                UPDATE pending_revalidation_queue
                SET status = 'DONE', updated_at = ?
                WHERE queue_id = ? AND target_version = ? AND status = 'PENDING'
                """,
                (now, target_queue_id, run_ver),
            )
        else:
            conn.execute(
                """
                UPDATE pending_revalidation_queue
                SET status = 'DONE', updated_at = ?
                WHERE obs_id = ? AND target_version = ? AND status = 'PENDING'
                """,
                (now, obs_id, run_ver),
            )

        if not stale_due_to_upgrade:
            conn.execute(
                "UPDATE observations SET obs_status = 'SUPERSEDED_REVALIDATED', updated_at = ? WHERE obs_id = ?",
                (now, obs_id),
            )
        elif still_pending is None:
            # 仅当不存在指向 active_ver 的待办时，才给标记为 PENDING_REVALIDATION 的 new_obs_id 补挂对应待办（1:1 严格配对）
            conn.execute(
                """
                INSERT INTO pending_revalidation_queue(
                    queue_id, obs_id, question_id, target_instrument_id, target_version, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (f"reval_{uuid.uuid4().hex[:10]}", new_obs_id, question_id, inst_id, active_ver, now, now),
            )

    return build_tool_receipt(
        conn=conn,
        tool_name="recompute_stage_b_only",
        question_id=question_id,
        next_step_guidance=(
            f"重评期间仪器 {inst_id} 已升至 v{active_ver}：已记录绑定 v{run_ver} 的历史收据 {new_obs_id} (PENDING_REVALIDATION)，并保留指向 v{active_ver} 的待重评队列。"
            if stale_due_to_upgrade
            else f"已免重跑 Stage A 完成重评：旧收据 {obs_id} 保留为 SUPERSEDED_REVALIDATED，已生成绑定 v{run_ver} 的新收据 {new_obs_id} ({new_obs_status})。"
        ),
        data={
            "old_obs_id": obs_id,
            "old_obs_status": str(obs["obs_status"]) if stale_due_to_upgrade else "SUPERSEDED_REVALIDATED",
            "new_obs_id": new_obs_id,
            "new_obs_status": new_obs_status,
            "instrument_id": inst_id,
            "instrument_version": run_ver,
            "active_instrument_version": active_ver,
            "stale_due_to_upgrade": stale_due_to_upgrade,
            "tracks": reval.get("tracks") or {},
            "details": str(reval.get("details") or ""),
        },
    )


def tool_update_skill_ledger(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    skill_id: str,
    applicable_scope: str,
    version: int,
    raw_success_count: int,
    raw_failure_count: int,
    verified_artifact_rel_path: str,
    rollback_pointer: str,
) -> dict[str, Any]:
    """No-File 校验后向工作区隔离 `$PLUGIN_DATA/.../skills/SKILL_LEDGER.json` 登记共享技能/探针。"""
    enforce_role_tool_permission(conn, caller_role, "update_skill_ledger", session_id=session_id)
    sid = str(skill_id or "").strip()
    if not _SKILL_ID_RE.match(sid):
        raise FailClosedError(ERR_INVALID_INPUT, f"skill_id 必须匹配 ^[a-z0-9_]+$（无空格连字符）：{skill_id!r}")
    ver_int = int(version)
    succ_int = int(raw_success_count)
    fail_int = int(raw_failure_count)
    if ver_int < 1:
        raise FailClosedError(ERR_INVALID_INPUT, f"version 必须 >= 1，实收 {version!r}")
    if succ_int < 0 or fail_int < 0:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"raw_success_count 与 raw_failure_count 必须 >= 0，实收 ({raw_success_count!r}, {raw_failure_count!r})",
        )

    art_abs = _resolve_ws_or_core_file(workspace_root, verified_artifact_rel_path)
    if art_abs.stat().st_size <= 0:
        raise FailClosedError(ERR_INVARIANT, f"No File 物理验证失败：产物为空文件 {verified_artifact_rel_path!r}")

    paths = resolve_storage_paths(workspace_root)
    ledger_path = paths["skills_ledger_path"]
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        src_default = core_python_root() / "skills" / "SKILL_LEDGER.json"
        ledger = json.loads(src_default.read_text(encoding="utf-8")) if src_default.is_file() else {"schema_version": "3.0.0", "skills": {}}

    skills_map = ledger.setdefault("skills", {})
    entry = {
        "skill_id": sid,
        "applicable_scope": str(applicable_scope or "").strip(),
        "version": int(version),
        "raw_success_count": int(raw_success_count),
        "raw_failure_count": int(raw_failure_count),
        "verified_artifact_rel_path": _norm_rel_path(workspace_root, art_abs, verified_artifact_rel_path),
        "rollback_pointer": str(rollback_pointer or "none").strip(),
        "last_no_file_passed": True,
        "updated_at": utc_now_iso(),
    }
    skills_map[sid] = entry
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_public_instruments_to_all_active_worktrees(conn, workspace_root)

    return build_tool_receipt(
        conn=conn,
        tool_name="update_skill_ledger",
        question_id="ALL",
        next_step_guidance=f"共享技能 {sid} v{version} 已通过 No-File 校验并写入工作区隔离台账。",
        data={"skill_id": sid, "ledger_path": str(ledger_path), "entry": entry},
    )


def tool_resolve_works_ticket(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    ticket_id: str,
    resolution: str,
    resolution_note: str,
) -> dict[str, Any]:
    """显式结案工造司工单（含 PAIN_POINT / DUPLICATE_TOOL / EXPLOIT / INSTRUMENT_ERROR），杜绝 OPEN 工单无限自旋唤醒。"""
    enforce_role_tool_permission(conn, caller_role, "resolve_works_ticket", session_id=session_id)
    tid = str(ticket_id or "").strip()
    if not tid:
        raise FailClosedError(ERR_INVALID_INPUT, "ticket_id 不能为空")
    res_u = str(resolution or "").strip().upper()
    if res_u not in ALLOWED_TICKET_RESOLUTIONS:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 resolution={resolution!r}，仅允许 {sorted(ALLOWED_TICKET_RESOLUTIONS)}",
        )
    note = str(resolution_note or "").strip()
    if len(note) < 5:
        raise FailClosedError(ERR_INVALID_INPUT, "resolution_note 须至少 5 个字符，清楚写明核查结果或处理依据")

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        row = conn.execute("SELECT * FROM works_engineering_queue WHERE ticket_id = ?", (tid,)).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"工单 {tid!r} 不存在")
        if row["status"] != "OPEN":
            return build_tool_receipt(
                conn=conn,
                tool_name="resolve_works_ticket",
                question_id=row["question_id"],
                next_step_guidance=f"工单 {tid} 已结案为 {row['status']}。",
                data={"ticket_id": tid, "status": row["status"],
                      "resolution_note": row["resolution_note"], "idempotent_skip": True},
            )
        conn.execute(
            """
            UPDATE works_engineering_queue
            SET status = ?, resolution_note = ?, updated_at = ?
            WHERE ticket_id = ?
            """,
            (res_u, note, now, tid),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="resolve_works_ticket",
        question_id=str(row["question_id"]),
        next_step_guidance=f"工单 {tid} ({row['ticket_type']}) 已结案（{res_u}），不再重复触发 works:queue 唤醒。",
        data={
            "ticket_id": tid,
            "ticket_type": str(row["ticket_type"]),
            "question_id": str(row["question_id"]),
            "status": res_u,
            "resolution": res_u,
            "resolution_note": note,
        },
    )


def tool_submit_works_ticket(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
    ticket_type: str = "PAIN_POINT",
    description: str = "",
    instrument_id: str | None = None,
) -> dict[str, Any]:
    """全院共享的工造司报修/公共工具需求入口（内置同键 OPEN 幂等合并、单会话限 2 单与全院队列软上限防洪阀）。"""
    enforce_role_tool_permission(conn, caller_role, "submit_works_ticket", session_id=session_id)
    from .control_plane.lifecycle_ops import submit_works_ticket

    res = submit_works_ticket(
        conn,
        question_id=question_id,
        ticket_type=ticket_type,
        instrument_id=instrument_id,
        description=description,
        source=f"role:{caller_role}",
        reporter_session_id=str(session_id or ""),
    )
    msg = (
        f"同类工单 {res['ticket_id']} 正在由工造司处理中，已将你的补充说明合并附入（累计 {res.get('report_count', 1)} 条），请耐心等待，无需重复刷单。"
        if res.get("deduplicated")
        else f"工单 {res['ticket_id']} ({res['ticket_type']}) 已进入工造司队列等待处理，请耐心等待并继续推进当前任务。"
    )
    return build_tool_receipt(
        conn=conn,
        tool_name="submit_works_ticket",
        question_id=str(res["question_id"]),
        next_step_guidance=msg,
        data=res,
    )
