"""长城 V6-Up (v3.0) explorer（一线科研探索者）5 个单一职责窄工具。"""

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
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    sanitize_fts5_query,
    utc_now_iso,
)
from .mcp_core_helpers import (
    _SQL_WRITE_FORBIDDEN_RE,
    build_tool_receipt,
    compute_clock_signal,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    next_prefixed_id,
    record_declared_refs,
    record_fact_edge,
)

_FORBIDDEN_TENANT_TABLES = (
    "review_queue",
    "compliance_alerts",
    "parse0_contract",
    "project_closure_state",
    "works_engineering_queue",
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
    declared_refs: list[Any],
    session_id: str,
    cfg: dict[str, Any],
    now: str,
) -> tuple[str, str | None]:
    """命中四元缓存时确保返回属于本节点的正式收据：
    - 同节点复用：直接返回原 obs_id；
    - 跨节点/跨分支复用：零重跑容器，为本节点签发一条独立归属的 Obs-###（revalidated_from_obs_id 指向原收据，cache_key 留空）。
    """
    src_obs_id = str(cached["obs_id"])
    if str(cached["node_id"]) == str(node_id):
        return src_obs_id, None

    new_obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
    reuse_prefix = f"[CACHE_REUSED_FROM {src_obs_id}] "
    base_details = str(cached["details_text"] or "")
    merged_details = base_details if base_details.startswith("[CACHE_REUSED_FROM ") else (reuse_prefix + base_details)
    with rw_immediate_tx(conn):
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
) -> dict[str, Any]:
    """统一三档仪器调用：probe（诊断不记 Obs）/ official（受控凭证）/ heavy（冻结现场异步幂等取回）。"""
    enforce_role_tool_permission(conn, caller_role, "run_isolated_eval", session_id=session_id, node_id=node_id)

    tier_l = str(tier or "").strip().lower()
    if tier_l not in ALLOWED_INSTRUMENT_TIERS:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 tier={tier!r}，仅允许 {sorted(ALLOWED_INSTRUMENT_TIERS)}",
        )

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"节点 {node_id!r} 属于 {node['question_id']!r} 而非 {question_id!r}")

    cfg = load_runtime_config()
    clock_sig = compute_clock_signal(int(node["pressure_tokens"] or 0), int(node["first_reflection_unlocked"] or 0), cfg)

    # 1. 重型作业凭 job_id 幂等取回/执行（按入队冻结快照与原仪器版本运行，仅扣费一次）
    if tier_l == "heavy" and job_id and str(job_id).strip():
        jres = execute_heavy_async_job(conn, workspace_root=workspace_root, job_id=str(job_id).strip())
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
        """
        SELECT * FROM instruments
        WHERE instrument_id = ? AND is_active = 1
        ORDER BY version DESC LIMIT 1
        """,
        (instrument_id,),
    ).fetchone()
    if inst is None:
        raise FailClosedError(ERR_NOT_FOUND, f"找不到活跃仪器 {instrument_id!r}，请核对已注册仪器清单")
    if str(inst["question_id"]) not in (str(question_id), "ALL"):
        raise FailClosedError(ERR_INVALID_INPUT, f"仪器 {instrument_id!r} 归属 {inst['question_id']!r}，不可跨题调用")
    if tier_l == "official" and str(inst["health_status"]) == "UNHEALTHY":
        raise FailClosedError(
            ERR_LOCKED,
            f"仪器 {instrument_id!r} (v{inst['version']}) 因连续报错已熔断置 UNHEALTHY 并报修工造司（非你算法问题），请暂改用其他仪器或推进推导。",
        )

    worktree_abs = str(node["worktree_abs_path"])
    art_abs = safe_resolve_in_worktree(worktree_abs, artifact_rel_path)
    if not art_abs.exists():
        raise FailClosedError(
            ERR_NOT_FOUND,
            f"在分支工作树 {worktree_abs} 下找不到相对路径 {artifact_rel_path!r}（artifact_rel_path 必须相对于分支工作树根目录）",
        )

    inst_abs = _resolve_instrument_file(workspace_root, str(inst["instrument_rel_path"]))
    spec = json.loads(inst["default_spec_json"] or "{}")
    if not isinstance(spec, dict):
        spec = {}
    spec["tier"] = tier_l
    spec["question_id"] = question_id
    spec["instrument_id"] = instrument_id
    spec["instrument_version"] = int(inst["version"])

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

    # 2. heavy 首次入队：冻结候选 + tools/ 快照、原仪器版本与规格至 async_eval_jobs（仅扣费 1 次）
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
                next_step_guidance=(
                    f"命中四元复合缓存（复用 {reused_from}），已零算力签发本节点重型收据 {eff_obs_id}。"
                    if reused_from
                    else f"命中四元复合缓存，直接返回历史重型收据 {eff_obs_id}（零额外开销）。"
                ),
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
        # 同步物理冻结当前版本仪器源码，彻底杜绝同路径原地升版串版本！
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
            next_step_guidance=f"重型作业 {new_job_id} 已入队并冻结候选快照与仪器 v{inst['version']}（预算已计 1 次）；稍后可凭 job_id='{new_job_id}' 幂等取回结果。",
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

    # 3. probe 档：只写 probe_diagnostic_logs，绝不污染 observations
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
        )
        probe_id = next_prefixed_id(conn, "probe_diagnostic_logs", "probe_id", "probe_")
        with rw_immediate_tx(conn):
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

    # 4. official 档：四元缓存检查（INSTRUMENT_ERROR / INFRA_ERROR 绝对穿透不命中）
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
            next_step_guidance=(
                f"命中四元复合缓存（复用 {reused_from}），已零算力签发本节点正式收据 {eff_obs_id}（状态 {cached['obs_status']}）。"
                if reused_from
                else f"命中四元复合缓存，直接返回正式收据 {eff_obs_id}（状态 {cached['obs_status']}）。"
            ),
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

    obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
    stage_a_persist = str(paths["eval_artifacts_dir"] / obs_id / "stage_a_output.json")
    res = run_isolated_instrument(
        instrument_path=inst_abs,
        instrument_role=str(inst["instrument_role"]),
        artifact_path=art_abs,
        spec=spec,
        tier="official",
        artifact_schema=str(inst["artifact_schema"]),
        worktree_root=worktree_abs,
        persist_stage_a_path=stage_a_persist,
    )
    obs_status = str(res["obs_status"])
    # 故障穿透：任何错误态（CANDIDATE_ERROR / INSTRUMENT_ERROR / INFRA_ERROR）绝不写 cache_key 进永久缓存！
    stored_cache_key = cache_key if res["status"] == "OK" else ""

    circuit_broken = False
    with rw_immediate_tx(conn):
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
                stage_a_persist if Path(stage_a_persist).is_file() else None,
                obs_status,
                json.dumps(res.get("tracks") or {}, ensure_ascii=False),
                str(res.get("details") or ""),
                pred,
                json.dumps(spec, ensure_ascii=False),
                now,
                now,
            ),
        )
        # 声明引用默认以 MOTIVATING_REF 写入（防全军连坐）
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

    if res["status"] in ("INSTRUMENT_ERROR", "INFRA_ERROR"):
        guidance = (
            "平台仪器/基础设施故障已自动报修工造司，非你算法问题（零处罚、不扣修补配额、不进缓存）。"
            + (" 该仪器已触发连续3次故障熔断。" if circuit_broken else "")
        )
    elif clock_sig["trigger"] == "HANDOFF_70":
        guidance = f"已产出 {obs_id} ({obs_status})。水位已达 >=70%，请立即停止改码并在最后 1 轮只读回合亲笔总结成果与《科研遗嘱》！"
    elif clock_sig["trigger"] == "REFLECT_37":
        guidance = f"已产出 {obs_id} ({obs_status})。水位已跨 37%，回合间隙将切入伴随元反思并解锁内藏 L3/L2！"
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


def _handle_instrument_error_ticket(
    conn: sqlite3.Connection,
    question_id: str,
    instrument_id: str,
    version: int,
    details: str,
    now: str,
    cfg: dict[str, Any],
) -> bool:
    """递增仪器连续出错计数，达阈值自动置 UNHEALTHY 熔断，并自动入队工造司故障工单。"""
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
            json.dumps({"version": version, "consecutive_error_count": new_cnt, "circuit_broken": broken, "details": details[:800]}, ensure_ascii=False),
            now,
            now,
        ),
    )
    return broken


def tool_query_library_catalog(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    scope: str = "ALL",
    keyword: str = "",
) -> dict[str, Any]:
    """一级目录卡按需检索（0-37% 物理锁定内藏，仅返 EXTERNAL_R；37% 解锁后全馆两翼开放）。"""
    enforce_role_tool_permission(conn, caller_role, "query_library_catalog", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = int(node["first_reflection_unlocked"] or 0) == 1

    scope_u = str(scope or "ALL").strip().upper()
    if scope_u not in ("EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "ALL"):
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 scope={scope!r}，仅允许 ['ALL', 'EXTERNAL_R', 'INTERNAL_L2', 'INTERNAL_L3']",
        )

    fts_q = sanitize_fts5_query(keyword)
    cards: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 左翼外藏 [R###] 从 0% 起全程开放
    if scope_u in ("EXTERNAL_R", "ALL"):
        if fts_q:
            rows = conn.execute(
                """
                SELECT c.ref_id, c.question_id, c.title, c.abstract_md, c.read_depth, c.support_scope, c.is_unverified_external
                FROM external_literature_cards c
                JOIN external_literature_fts f ON f.rowid = c.rowid
                WHERE external_literature_fts MATCH ?
                  AND (? = 'ALL' OR c.question_id = ? OR c.question_id = 'ALL')
                ORDER BY c.ref_id
                """,
                (fts_q, question_id, question_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ref_id, question_id, title, abstract_md, read_depth, support_scope, is_unverified_external
                FROM external_literature_cards
                WHERE ? = 'ALL' OR question_id = ? OR question_id = 'ALL'
                ORDER BY ref_id
                """,
                (question_id, question_id),
            ).fetchall()
        for r in rows:
            cards.append(
                {
                    "entry_id": str(r["ref_id"]),
                    "wing": "EXTERNAL_R",
                    "question_id": str(r["question_id"]),
                    "title": str(r["title"]),
                    "abstract_preview": str(r["abstract_md"])[:350],
                    "read_depth": str(r["read_depth"]),
                    "support_scope": str(r["support_scope"]),
                    "is_unverified_external": bool(r["is_unverified_external"]),
                }
            )

    # 右翼内藏 L3 / L2：0-37% 物理锁死
    if scope_u in ("INTERNAL_L3", "INTERNAL_L2", "ALL"):
        if not unlocked:
            if scope_u in ("INTERNAL_L3", "INTERNAL_L2"):
                raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期物理锁定内藏 L3/L2，完成 37% 伴随元反思后立即可读")
            warnings.append("当前处于 0-37% 独思净室期，本次仅返回左翼外藏 [R###]；完成 37% 元反思后将解锁 L3/L2。")
        else:
            ltypes = ("L3_VERIFIED",) if scope_u == "INTERNAL_L3" else (("L2_FAILURE_RECORD",) if scope_u == "INTERNAL_L2" else ("L3_VERIFIED", "L2_FAILURE_RECORD"))
            ph = ",".join("?" for _ in ltypes)
            if fts_q:
                rows = conn.execute(
                    f"""
                    SELECT l.entry_id, l.question_id, l.ledger_type, l.l3_entry_kind, l.goal_coverage, l.l2_category, l.title, l.abstract_md
                    FROM internal_research_ledger l
                    JOIN internal_research_fts f ON f.rowid = l.rowid
                    WHERE internal_research_fts MATCH ?
                      AND l.is_active = 1
                      AND l.ledger_type IN ({ph})
                      AND (? = 'ALL' OR l.question_id = ?)
                    ORDER BY l.entry_id
                    """,
                    (fts_q, *ltypes, question_id, question_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage, l2_category, title, abstract_md
                    FROM internal_research_ledger
                    WHERE is_active = 1
                      AND ledger_type IN ({ph})
                      AND (? = 'ALL' OR question_id = ?)
                    ORDER BY entry_id
                    """,
                    (*ltypes, question_id, question_id),
                ).fetchall()
            for r in rows:
                cards.append(
                    {
                        "entry_id": str(r["entry_id"]),
                        "wing": str(r["ledger_type"]),
                        "question_id": str(r["question_id"]),
                        "l3_entry_kind": r["l3_entry_kind"],
                        "goal_coverage": r["goal_coverage"],
                        "l2_category": r["l2_category"],
                        "title": str(r["title"]),
                        "abstract_preview": str(r["abstract_md"])[:350],
                    }
                )

    return build_tool_receipt(
        conn=conn,
        tool_name="query_library_catalog",
        question_id=question_id,
        node_id=node_id,
        warnings=warnings,
        next_step_guidance=f"共检索到 {len(cards)} 张目录卡；选定 1-2 张高相关卡片调用 get_library_entry 拉取全文。",
        data={"unlocked": unlocked, "cards": cards},
    )


def tool_get_library_entry(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    entry_id: str,
) -> dict[str, Any]:
    """二级详卡按 ID 拉取，并静默写入参考性 `FACT_LOG(READ)` 边。"""
    enforce_role_tool_permission(conn, caller_role, "get_library_entry", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = int(node["first_reflection_unlocked"] or 0) == 1

    ext = conn.execute("SELECT * FROM external_literature_cards WHERE ref_id = ?", (entry_id,)).fetchone()
    if ext is not None:
        with rw_immediate_tx(conn):
            record_fact_edge(conn, source_id=node_id, target_id=entry_id, edge_type="READ", session_id=session_id)
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取外藏参考卡 {entry_id}（注意：未复验外部参考摘要，须在推导/计算中自行核验适用前提）。",
            data={"wing": "EXTERNAL_R", "entry": dict(ext)},
        )

    led = conn.execute("SELECT * FROM internal_research_ledger WHERE entry_id = ?", (entry_id,)).fetchone()
    if led is not None:
        if not unlocked:
            raise FailClosedError(ERR_LOCKED, f"0-37% 独思期物理锁定内藏条目 {entry_id!r}，完成 37% 反思后开放")
        with rw_immediate_tx(conn):
            record_fact_edge(conn, source_id=node_id, target_id=entry_id, edge_type="READ", session_id=session_id)
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取内藏 {led['ledger_type']} 条目 {entry_id} 并静默记录参考 READ 轨迹。",
            data={"wing": str(led["ledger_type"]), "entry": dict(led)},
        )

    raise FailClosedError(ERR_NOT_FOUND, f"图书馆条目 {entry_id!r} 不存在")


def tool_request_literature_survey(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    topic_query: str,
    reason: str,
) -> dict[str, Any]:
    """委托图书馆外藏采编补充外部文献/标准定理卡。"""
    enforce_role_tool_permission(conn, caller_role, "request_literature_survey", session_id=session_id, node_id=node_id)
    if not str(topic_query or "").strip() or not str(reason or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "topic_query 与 reason 均不能为空")
    req_id = next_prefixed_id(conn, "survey_requests", "req_id", "sreq_")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO survey_requests(req_id, question_id, node_id, topic_query, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (req_id, question_id, node_id, topic_query.strip(), reason.strip(), now, now),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="request_literature_survey",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance=f"查新请求 {req_id} 已入队，后台采编馆员完成后将自动入库 [R###]。",
        data={"req_id": req_id, "status": "PENDING"},
    )


def tool_read_lineage_graph(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    target_node_id: str | None = None,
    view: str = "nodes",
    saved_query_name: str | None = None,
) -> dict[str, Any]:
    """37% 解锁后翻阅本门派私有谱系 DAG 或 `lineage_dead_ends` 全表（强隔离他脉与盲审表）。"""
    enforce_role_tool_permission(conn, caller_role, "read_lineage_graph", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(
            ERR_AUTH,
            f"门派物理隔离拦截：节点 {node_id!r} 隶属分支 {node['branch_id']!r}，严禁跨分支偷读 {branch_id!r}！",
        )
    if int(node["first_reflection_unlocked"] or 0) != 1:
        raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期暂锁本脉深层谱系 DAG 与 dead_ends，完成 37% 反思后立即开放")

    if saved_query_name:
        sq = conn.execute("SELECT sql_select, description FROM saved_graph_queries WHERE query_name = ?", (saved_query_name,)).fetchone()
        if sq is None:
            raise FailClosedError(ERR_NOT_FOUND, f"已保存查询视图 {saved_query_name!r} 不存在")
        sql = str(sq["sql_select"]).strip()
        if _SQL_WRITE_FORBIDDEN_RE.search(sql) or ";" in sql.rstrip(";"):
            raise FailClosedError(ERR_AUTH, "非法非只读 SQL 视图")
        sql_l = sql.lower()
        for forbidden_tbl in _FORBIDDEN_TENANT_TABLES:
            if forbidden_tbl in sql_l:
                raise FailClosedError(ERR_AUTH, f"租户隔离阻断：探索者禁止执行涉及受保护表 {forbidden_tbl!r} 的 SQL 视图")
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已执行只读视图 {saved_query_name!r}，返回 {len(rows)} 行。",
            data={"saved_query_name": saved_query_name, "rows": rows},
        )

    view_l = str(view or "nodes").strip().lower()
    if view_l not in ("nodes", "dead_ends"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 view={view!r}，仅允许 'nodes' 或 'dead_ends'")

    if view_l == "dead_ends":
        de_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lineage_dead_ends WHERE branch_id = ? ORDER BY created_at ASC",
                (branch_id,),
            ).fetchall()
        ]
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取本脉 {branch_id} 全部 {len(de_rows)} 条历史死胡同排除记录。",
            data={"view": "dead_ends", "branch_id": branch_id, "dead_ends": de_rows},
        )

    if target_node_id:
        tgt = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (target_node_id,)).fetchone()
        if tgt is None:
            raise FailClosedError(ERR_NOT_FOUND, f"目标谱系节点 {target_node_id!r} 不存在")
        if str(tgt["branch_id"]) != str(branch_id):
            raise FailClosedError(ERR_AUTH, f"门派物理隔离拦截：目标节点 {target_node_id!r} 不属于本分支 {branch_id!r}")
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已读取本脉祖先节点 {target_node_id} 完整记录。",
            data={"view": "nodes", "node": dict(tgt)},
        )

    nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, generation, node_status, evidence_grade, mechanism_summary,
                   column_a_facts_md, will_md, created_at
            FROM lineage_nodes
            WHERE branch_id = ?
            ORDER BY generation ASC, created_at ASC
            """,
            (branch_id,),
        ).fetchall()
    ]
    return build_tool_receipt(
        conn=conn,
        tool_name="read_lineage_graph",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance=f"已读取本脉 {branch_id} 共 {len(nodes)} 代谱系节点摘要。",
        data={"view": "nodes", "branch_id": branch_id, "nodes": nodes},
    )
