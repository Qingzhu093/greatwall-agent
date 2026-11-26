"""GreatWall v0.3 explorer 隔离仪器评测窄工具（run_isolated_eval）。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..evaluators.isolated_runner import (
    compute_eval_cache_key,
    compute_recursive_dir_sha256,
    compute_spec_sha256,
    run_isolated_instrument,
    sha256_file,
)
from .control_plane_service import execute_heavy_async_job, safe_resolve_in_worktree
from .db_schema import (
    ALLOWED_INSTRUMENT_TIERS,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    compute_clock_signal,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    next_prefixed_id,
    record_declared_refs,
    resolve_effective_context_window,
)


def _resolve_instrument_file(workspace_root: str, rel_path: str) -> Path:
    ws = Path(os.path.realpath(workspace_root))
    p1 = Path(os.path.realpath(ws / rel_path))
    if p1.is_file():
        return p1
    p2 = Path(os.path.realpath(core_python_root() / rel_path))
    if p2.is_file():
        return p2
    raise FailClosedError(ERR_NOT_FOUND, f"找不到仪器脚本 {rel_path!r}")


def _materialize_cached_obs_for_node(
    conn: sqlite3.Connection,
    *,
    cached: sqlite3.Row,
    question_id: str,
    branch_id: str,
    node_id: str,
    tier: str,
    linguistic_prediction: str,
    declared_refs: list[Any] | None,
    session_id: str,
    cfg: dict[str, Any],
    now: str,
) -> tuple[str, str | None]:
    """命中四元缓存时确保返回属于本节点的正式收据。"""
    src_obs_id = str(cached["obs_id"])
    if str(cached["node_id"]) == str(node_id):
        return src_obs_id, None

    reuse_prefix = f"[CACHE_REUSED_FROM {src_obs_id}] "
    base_details = str(cached["details_text"] or "")
    merged_details = base_details if base_details.startswith("[CACHE_REUSED_FROM ") else (reuse_prefix + base_details)
    with rw_immediate_tx(conn):
        new_obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
        conn.execute(
            """
            INSERT INTO observations(
                obs_id, question_id, branch_id, node_id, instrument_id, instrument_version, tier,
                candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256, cache_key,
                stage_a_artifact_path, revalidated_from_obs_id, obs_status, tracks_json,
                details_text, linguistic_prediction, spec_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_obs_id,
                question_id,
                branch_id,
                node_id,
                str(cached["instrument_id"]),
                int(cached["instrument_version"]),
                tier,
                str(cached["candidate_entry_sha256"]),
                str(cached["tools_dir_sha256"]),
                str(cached["spec_sha256"]),
                str(cached["instrument_sha256"]),
                cached["stage_a_artifact_path"],
                src_obs_id,
                str(cached["obs_status"]),
                str(cached["tracks_json"] or "{}"),
                merged_details,
                linguistic_prediction,
                str(cached["spec_json"] or "{}"),
                now,
                now,
            ),
        )
        record_declared_refs(
            conn,
            source_id=new_obs_id,
            declared_refs=declared_refs,
            session_id=session_id,
            default_edge_type=str(cfg.get("default_declared_ref_edge_type", "MOTIVATING_REF")),
        )
    return new_obs_id, src_obs_id


def _handle_instrument_error_ticket(
    conn: sqlite3.Connection,
    question_id: str,
    instrument_id: str,
    version: int,
    details: str,
    now: str,
    cfg: dict[str, Any],
) -> bool:
    """递增仪器连续出错计数，达阈值自动置 UNHEALTHY 熔断并入队工造司故障工单。"""
    threshold = int(cfg.get("instrument_unhealthy_consecutive_error_threshold", 3))
    row = conn.execute(
        "SELECT consecutive_error_count FROM instruments WHERE instrument_id = ? AND version = ?",
        (instrument_id, version),
    ).fetchone()
    new_cnt = int(row["consecutive_error_count"] or 0) + 1 if row else 1
    broken = new_cnt >= threshold
    conn.execute(
        """
        UPDATE instruments
        SET consecutive_error_count = ?, health_status = ?, updated_at = ?
        WHERE instrument_id = ? AND version = ?
        """,
        (new_cnt, "UNHEALTHY" if broken else "HEALTHY", now, instrument_id, version),
    )
    tid = f"tkt_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO works_engineering_queue(ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at)
        VALUES (?, ?, 'INSTRUMENT_ERROR', ?, ?, 'OPEN', ?, ?)
        """,
        (
            tid,
            question_id,
            instrument_id,
            json.dumps(
                {"version": version, "consecutive_error_count": new_cnt, "circuit_broken": broken, "details": details[:800]},
                ensure_ascii=False,
            ),
            now,
            now,
        ),
    )
    return broken


def tool_run_isolated_eval(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    instrument_id: str,
    tier: str,
    artifact_rel_path: str,
    linguistic_prediction: str,
    declared_refs: list[str] | None = None,
    job_id: str | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """统一三档仪器调用：probe（诊断不记 Obs）/ official（受控凭证）/ heavy（冻结现场异步幂等取回）。"""
    enforce_role_tool_permission(conn, caller_role, "run_isolated_eval", session_id=session_id, node_id=node_id)

    tier_l = str(tier or "").strip().lower()
    if tier_l not in ALLOWED_INSTRUMENT_TIERS:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 tier={tier!r}，仅允许 {sorted(ALLOWED_INSTRUMENT_TIERS)}")

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"节点 {node_id!r} 属于 {node['question_id']!r} 而非 {question_id!r}")

    cfg = load_runtime_config()
    eff_win = resolve_effective_context_window(conn, node_window=node["effective_context_window"], cfg=cfg)
    clock_sig = compute_clock_signal(
        int(node["pressure_tokens"] or 0),
        int(node["first_reflection_unlocked"] or 0),
        cfg,
        effective_context_window=eff_win,
    )

    if tier_l == "heavy" and job_id and str(job_id).strip():
        jres = execute_heavy_async_job(
            conn,
            workspace_root=workspace_root,
            job_id=str(job_id).strip(),
            cancel_event=cancel_event,
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="run_isolated_eval",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance=(
                f"重型作业 {job_id} 已按入队冻结现场完成，产出 {jres.get('obs_id')}（状态 {jres.get('obs_status')}，预算仅扣 1 次）。"
            ),
            data={**jres, "tier": "heavy", "clock_signal": clock_sig},
        )

    pred = str(linguistic_prediction or "").strip()
    if tier_l in ("official", "heavy") and len(pred) < 5:
        raise FailClosedError(ERR_INVALID_INPUT, "正式/重型实验调用前必须提供 >= 5 字可证伪的事前预测 linguistic_prediction")

    inst = conn.execute(
        "SELECT * FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    if inst is None:
        avail_rows = conn.execute(
            """
            SELECT instrument_id, version, instrument_role, artifact_schema
            FROM instruments
            WHERE is_active = 1 AND health_status = 'HEALTHY' AND (question_id = ? OR question_id = 'ALL')
            ORDER BY instrument_id, version DESC
            """,
            (question_id,),
        ).fetchall()
        avail_desc = ", ".join(
            f"{r['instrument_id']}(v{r['version']}/{r['instrument_role']}/{r['artifact_schema']})"
            for r in avail_rows
        ) or "（当前子题尚无已注册活跃仪器）"
        raise FailClosedError(ERR_NOT_FOUND, f"找不到活跃仪器 {instrument_id!r}，当前可用仪器: {avail_desc}")
    if str(inst["question_id"]) not in (str(question_id), "ALL"):
        raise FailClosedError(ERR_INVALID_INPUT, f"仪器 {instrument_id!r} 归属 {inst['question_id']!r}，不可跨题调用")
    if tier_l == "official" and str(inst["health_status"]) == "UNHEALTHY":
        raise FailClosedError(
            ERR_LOCKED,
            f"仪器 {instrument_id!r} (v{inst['version']}) 因连续报错已熔断置 UNHEALTHY 并报修工造司（非你算法问题），请暂改用其他仪器或推进推导。",
        )

    worktree_abs = str(node["worktree_abs_path"])
    raw_rel = str(artifact_rel_path or "").strip()
    if tier_l == "probe" and raw_rel in ("", "."):
        art_abs = Path(os.path.realpath(worktree_abs))
    else:
        art_abs = safe_resolve_in_worktree(worktree_abs, artifact_rel_path)
    if not art_abs.exists():
        raise FailClosedError(
            ERR_NOT_FOUND,
            f"在分支工作树 {worktree_abs} 下找不到相对路径 {artifact_rel_path!r}",
        )

    inst_abs = _resolve_instrument_file(workspace_root, str(inst["instrument_rel_path"]))
    spec = json.loads(inst["default_spec_json"] or "{}")
    if not isinstance(spec, dict):
        spec = {}
    spec.update(
        {
            "tier": tier_l,
            "question_id": question_id,
            "instrument_id": instrument_id,
            "instrument_version": int(inst["version"]),
        }
    )

    cand_sha = sha256_file(art_abs) if art_abs.is_file() else ""
    tools_sha = compute_recursive_dir_sha256(Path(worktree_abs) / "tools")
    spec_sha = compute_spec_sha256(spec, tier_l)
    inst_sha = str(inst["instrument_sha256"])
    cache_key = compute_eval_cache_key(
        candidate_entry_sha256=cand_sha,
        tools_dir_sha256=tools_sha,
        spec_sha256=spec_sha,
        instrument_sha256=inst_sha,
    )

    now = utc_now_iso()
    paths = resolve_storage_paths(workspace_root)

    if tier_l == "heavy":
        cached = conn.execute(
            """
            SELECT * FROM observations
            WHERE cache_key = ? AND tier = 'heavy'
              AND obs_status IN ('VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED','CANDIDATE_ERROR')
            ORDER BY created_at DESC LIMIT 1
            """,
            (cache_key,),
        ).fetchone()
        if cached is not None:
            eff_obs_id, reused_from = _materialize_cached_obs_for_node(
                conn,
                cached=cached,
                question_id=question_id,
                branch_id=str(node["branch_id"]),
                node_id=node_id,
                tier="heavy",
                linguistic_prediction=pred,
                declared_refs=declared_refs,
                session_id=session_id,
                cfg=cfg,
                now=now,
            )
            return build_tool_receipt(
                conn=conn,
                tool_name="run_isolated_eval",
                question_id=question_id,
                node_id=node_id,
                next_step_guidance=f"命中四元复合缓存，返回本节点重型收据 {eff_obs_id}（复用 {reused_from or '自身'}）。",
                data={
                    "cache_hit": True,
                    "tier": "heavy",
                    "obs_id": eff_obs_id,
                    "reused_from_obs_id": reused_from,
                    "obs_status": str(cached["obs_status"]),
                    "tracks": json.loads(cached["tracks_json"] or "{}"),
                    "details": str(cached["details_text"] or ""),
                    "instrument_id": instrument_id,
                    "instrument_version": int(cached["instrument_version"]),
                    "clock_signal": clock_sig,
                },
            )

        new_job_id = f"job_{uuid.uuid4().hex[:10]}"
        freeze_dir = paths["job_inputs_dir"] / new_job_id
        freeze_dir.mkdir(parents=True, exist_ok=True)
        frozen_art = freeze_dir / art_abs.name
        if art_abs.is_file():
            shutil.copy2(art_abs, frozen_art)
        else:
            shutil.copytree(art_abs, frozen_art, dirs_exist_ok=True)
        src_tools = Path(worktree_abs) / "tools"
        if src_tools.is_dir():
            shutil.copytree(
                src_tools,
                freeze_dir / "tools",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )
        frozen_inst = freeze_dir / f"frozen_instrument_v{int(inst['version'])}.py"
        if inst_abs.is_file():
            shutil.copy2(inst_abs, frozen_inst)

        with rw_immediate_tx(conn):
            conn.execute(
                """
                INSERT INTO async_eval_jobs(
                    job_id, obs_id, question_id, branch_id, node_id, instrument_id, instrument_version,
                    artifact_snapshot_path, frozen_instrument_path, spec_snapshot_json, cache_key, linguistic_prediction,
                    declared_refs_json, status, budget_charged, created_at, updated_at
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', 1, ?, ?)
                """,
                (
                    new_job_id,
                    question_id,
                    str(node["branch_id"]),
                    node_id,
                    instrument_id,
                    int(inst["version"]),
                    str(frozen_art),
                    str(frozen_inst) if frozen_inst.is_file() else None,
                    json.dumps(spec, ensure_ascii=False),
                    cache_key,
                    pred,
                    json.dumps(declared_refs or [], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="run_isolated_eval",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance=f"重型作业 {new_job_id} 已入队并冻结快照与仪器 v{inst['version']}；稍后可凭 job_id='{new_job_id}' 幂等取回。",
            data={
                "tier": "heavy",
                "job_id": new_job_id,
                "status": "QUEUED",
                "instrument_id": instrument_id,
                "instrument_version": int(inst["version"]),
                "budget_charged": 1,
                "cache_key": cache_key,
                "clock_signal": clock_sig,
            },
        )

    if tier_l == "probe":
        res = run_isolated_instrument(
            instrument_path=inst_abs,
            instrument_role=str(inst["instrument_role"]),
            artifact_path=art_abs,
            spec=spec,
            tier="probe",
            artifact_schema=str(inst["artifact_schema"]),
            worktree_root=worktree_abs,
            persist_stage_a_path=None,
            cancel_event=cancel_event,
        )
        with rw_immediate_tx(conn):
            if cancel_event is not None and cancel_event.is_set():
                raise FailClosedError(ERR_LOCKED, "probe 诊断请求已取消，未写入诊断日志")
            probe_id = next_prefixed_id(conn, "probe_diagnostic_logs", "probe_id", "probe_")
            conn.execute(
                """
                INSERT INTO probe_diagnostic_logs(probe_id, node_id, question_id, instrument_id, instrument_version, status, tracks_json, details_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    probe_id,
                    node_id,
                    question_id,
                    instrument_id,
                    int(inst["version"]),
                    str(res["status"]),
                    json.dumps(res.get("tracks") or {}, ensure_ascii=False),
                    str(res.get("details") or ""),
                    now,
                ),
            )
            if res["status"] == "INSTRUMENT_ERROR":
                _handle_instrument_error_ticket(conn, question_id, instrument_id, int(inst["version"]), str(res["details"]), now, cfg)

        guidance = (
            "平台仪器故障已自动报修工造司，非你算法问题（不扣修补配额、不记负结果）。"
            if res["status"] in ("INSTRUMENT_ERROR", "INFRA_ERROR")
            else f"probe 快速诊断完成 ({probe_id})，仅记录诊断日志不污染正式观测账。"
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="run_isolated_eval",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance=guidance,
            data={
                "tier": "probe",
                "probe_id": probe_id,
                "status": res["status"],
                "verdict": res["verdict"],
                "tracks": res.get("tracks") or {},
                "details": str(res.get("details") or ""),
                "instrument_id": instrument_id,
                "instrument_version": int(inst["version"]),
                "clock_signal": clock_sig,
            },
        )

    # official 档
    cached = conn.execute(
        """
        SELECT * FROM observations
        WHERE cache_key = ? AND tier = 'official'
          AND obs_status IN ('VALID_PASS','MEASURED_REJECTION','VALID_UNDECIDED','CANDIDATE_ERROR')
        ORDER BY created_at DESC LIMIT 1
        """,
        (cache_key,),
    ).fetchone()
    if cached is not None:
        eff_obs_id, reused_from = _materialize_cached_obs_for_node(
            conn,
            cached=cached,
            question_id=question_id,
            branch_id=str(node["branch_id"]),
            node_id=node_id,
            tier="official",
            linguistic_prediction=pred,
            declared_refs=declared_refs,
            session_id=session_id,
            cfg=cfg,
            now=now,
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="run_isolated_eval",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance=f"命中四元复合缓存，返回正式收据 {eff_obs_id}（状态 {cached['obs_status']}）。",
            data={
                "cache_hit": True,
                "tier": "official",
                "obs_id": eff_obs_id,
                "reused_from_obs_id": reused_from,
                "obs_status": str(cached["obs_status"]),
                "status": "CANDIDATE_ERROR" if cached["obs_status"] == "CANDIDATE_ERROR" else "OK",
                "verdict": "PASS" if cached["obs_status"] == "VALID_PASS" else ("FAIL" if cached["obs_status"] == "MEASURED_REJECTION" else "UNDECIDED"),
                "tracks": json.loads(cached["tracks_json"] or "{}"),
                "details": str(cached["details_text"] or ""),
                "instrument_id": instrument_id,
                "instrument_version": int(cached["instrument_version"]),
                "cache_key": cache_key,
                "clock_signal": clock_sig,
            },
        )

    staging_root = paths["eval_artifacts_dir"] / "_staging" / f"off_{uuid.uuid4().hex[:12]}"
    staging_stage_a = staging_root / "stage_a_output.json"
    try:
        res = run_isolated_instrument(
            instrument_path=inst_abs,
            instrument_role=str(inst["instrument_role"]),
            artifact_path=art_abs,
            spec=spec,
            tier="official",
            artifact_schema=str(inst["artifact_schema"]),
            worktree_root=worktree_abs,
            persist_stage_a_path=str(staging_stage_a),
            cancel_event=cancel_event,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise FailClosedError(ERR_LOCKED, "正式评测请求已取消，已丢弃暂存产物未落库")

        obs_status = str(res["obs_status"])
        stored_cache_key = cache_key if res["status"] == "OK" else ""
        circuit_broken = False
        obs_id = ""
        final_stage_a_path: str | None = None
        stale_reval_target_ver: int | None = None

        with rw_immediate_tx(conn):
            if cancel_event is not None and cancel_event.is_set():
                raise FailClosedError(ERR_LOCKED, "正式评测请求已取消，已丢弃暂存产物未落库")
            active_inst_row = conn.execute(
                "SELECT version FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
                (instrument_id,),
            ).fetchone()
            if (
                active_inst_row is not None
                and int(active_inst_row["version"]) > int(inst["version"])
                and obs_status in ("VALID_PASS", "MEASURED_REJECTION", "VALID_UNDECIDED")
            ):
                stale_reval_target_ver = int(active_inst_row["version"])
                obs_status = "PENDING_REVALIDATION"
                stored_cache_key = ""

            obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
            final_stage_a = paths["eval_artifacts_dir"] / obs_id / "stage_a_output.json"
            if staging_stage_a.is_file():
                final_stage_a.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staging_stage_a), str(final_stage_a))
                final_stage_a_path = str(final_stage_a)
            try:
                conn.execute(
                    """
                    INSERT INTO observations(
                        obs_id, question_id, branch_id, node_id, instrument_id, instrument_version, tier,
                        candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256, cache_key,
                        stage_a_artifact_path, obs_status, tracks_json, details_text, linguistic_prediction,
                        spec_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'official', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obs_id,
                        question_id,
                        str(node["branch_id"]),
                        node_id,
                        instrument_id,
                        int(inst["version"]),
                        cand_sha,
                        tools_sha,
                        spec_sha,
                        inst_sha,
                        stored_cache_key,
                        final_stage_a_path,
                        obs_status,
                        json.dumps(res.get("tracks") or {}, ensure_ascii=False),
                        str(res.get("details") or ""),
                        pred,
                        json.dumps(spec, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                if stale_reval_target_ver is not None:
                    conn.execute(
                        """
                        INSERT INTO pending_revalidation_queue(
                            queue_id, obs_id, question_id, target_instrument_id, target_version, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                        """,
                        (f"reval_{uuid.uuid4().hex[:10]}", obs_id, question_id, instrument_id, stale_reval_target_ver, now, now),
                    )
                record_declared_refs(
                    conn,
                    source_id=obs_id,
                    declared_refs=declared_refs,
                    session_id=session_id,
                    default_edge_type=str(cfg.get("default_declared_ref_edge_type", "MOTIVATING_REF")),
                )
                if res["status"] == "INSTRUMENT_ERROR":
                    circuit_broken = _handle_instrument_error_ticket(
                        conn, question_id, instrument_id, int(inst["version"]), str(res["details"]), now, cfg
                    )
                elif res["status"] in ("OK", "CANDIDATE_ERROR"):
                    conn.execute(
                        "UPDATE instruments SET consecutive_error_count = 0, updated_at = ? WHERE instrument_id = ? AND version = ?",
                        (now, instrument_id, int(inst["version"])),
                    )
            except Exception:
                if final_stage_a_path:
                    shutil.rmtree(Path(final_stage_a_path).parent, ignore_errors=True)
                raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    if res["status"] in ("INSTRUMENT_ERROR", "INFRA_ERROR"):
        guidance = (
            "平台仪器/基础设施故障已自动报修工造司，非你算法问题（零处罚、不扣修补配额、不进缓存）。"
            + (" 该仪器已触发连续3次故障熔断。" if circuit_broken else "")
        )
    elif clock_sig["trigger"] == "HANDOFF_70":
        guidance = f"已产出 {obs_id} ({obs_status})。水位已达 >=70%，请立即停止改码并在最后 1 轮只读回合亲笔总结成果与《科研遗嘱》！"
    elif clock_sig["trigger"] == "REFLECT_37":
        guidance = f"已产出 {obs_id} ({obs_status})。水位已跨 37%，回合间隙将切入伴随元反思并解锁内藏 L3/L2 与《子题全局总览》！"
    else:
        guidance = f"正式观测 {obs_id} 已入库（status={res['status']}, verdict={res['verdict']}, obs_status={obs_status}，绑定 {instrument_id} v{inst['version']}）。"

    return build_tool_receipt(
        conn=conn,
        tool_name="run_isolated_eval",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance=guidance,
        data={
            "cache_hit": False,
            "tier": "official",
            "obs_id": obs_id,
            "obs_status": obs_status,
            "status": res["status"],
            "verdict": res["verdict"],
            "tracks": res.get("tracks") or {},
            "details": str(res.get("details") or ""),
            "instrument_id": instrument_id,
            "instrument_version": int(inst["version"]),
            "cache_key": stored_cache_key,
            "instrument_circuit_broken": circuit_broken,
            "clock_signal": clock_sig,
        },
    )
