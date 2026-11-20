"""V6-Up (v2.2) works_engineer（工造司）5 工具与 RQGM 锚点/Q_P 升版门禁。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any

from evaluators.isolated_runner import (
    run_stage_b_revaluation,
    sha256_file,
)
from .control_plane_service import (
    backup_retained_candidate_snapshot,
    check_stage2_closure_gate_data,
    export_stage3_deliverables,
    get_question_dependency_status,
    restore_retained_candidate_snapshot,
)
from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    propagate_dependency_recheck,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    VALID_FORK_MODES,
    VALID_STAGNATION_LANES,
    build_tool_receipt,
    check_mechanism_similarity,
    compute_adversarial_qp,
    compute_bb_epsilon,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    record_fact_edge,
    validate_baseline_isolation_ast,
)
from .governance_common import (
    _SQL_WRITE_FORBIDDEN_RE,
    _audit_node_unread_citations,
    _collect_proposer_sessions,
    _extract_referenced_cards_for_blind_review,
    _next_id,
    _next_ledger_id,
    _parse_proposer_sessions,
    _require_reviewer_session,
)

# ==============================================================================
# 角色 6：works_engineer（5 个窄工具）
# ==============================================================================


def tool_get_works_engineering_queue(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    question_id: str = "ALL",
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_works_engineering_queue", session_id=session_id)
    qf = (question_id or "ALL").strip()
    if qf.upper() == "ALL":
        hooks = [dict(r) for r in conn.execute("SELECT * FROM domain_hooks_by_question ORDER BY question_id").fetchall()]
        tickets = [dict(r) for r in conn.execute("SELECT * FROM works_engineering_queue ORDER BY status, created_at").fetchall()]
        revals = [dict(r) for r in conn.execute("SELECT * FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at").fetchall()]
    else:
        hooks = [dict(r) for r in conn.execute("SELECT * FROM domain_hooks_by_question WHERE question_id = ?", (qf,)).fetchall()]
        tickets = [dict(r) for r in conn.execute("SELECT * FROM works_engineering_queue WHERE question_id = ? ORDER BY status, created_at", (qf,)).fetchall()]
        revals = [dict(r) for r in conn.execute("SELECT * FROM pending_revalidation_queue WHERE question_id = ? AND status = 'PENDING' ORDER BY created_at", (qf,)).fetchall()]

    return build_tool_receipt(
        conn=conn,
        tool_name="get_works_engineering_queue",
        question_id=qf,
        next_step_guidance=f"现有 {len(hooks)} 个子题钩子、{len(tickets)} 条痛点工单、{len(revals)} 条待重评观测。若存在待重评观测请逐条调 recompute_stage_b_only 秒级恢复 VALID。",
        data={"domain_hooks": hooks, "pain_point_tickets": tickets, "pending_revalidation": revals},
    )


def _resolve_repo_or_ws_file(workspace_root: str, rel_path: str) -> Path:
    ws = Path(os.path.realpath(workspace_root))
    cand1 = Path(os.path.realpath(ws / rel_path))
    if cand1.is_file():
        return cand1
    cand2 = Path(os.path.realpath(core_python_root() / rel_path))
    if cand2.is_file():
        return cand2
    raise FailClosedError(ERR_NOT_FOUND, f"找不到相对路径文件 {rel_path!r}（已检查工作区与 core_python）")


def _normalize_hook_or_base_rel_path(workspace_root: str, abs_path: Path, raw_rel: str) -> str:
    """将路径统一规范为相对于 workspace_root 或 core_python_root 的 POSIX 相对路径，消除裂脑。"""
    ws = Path(os.path.realpath(workspace_root))
    try:
        return abs_path.relative_to(ws).as_posix()
    except ValueError:
        try:
            return abs_path.relative_to(core_python_root()).as_posix()
        except ValueError:
            return str(raw_rel).replace("\\", "/")


def tool_register_question_domain_hook(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    question_id: str,
    hook_rel_path: str,
    baseline_rel_path: str,
    fidelity_max_error_pct: float,
    plugin_protocol_version: str = "v1",
    public_input_sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "register_question_domain_hook", session_id=session_id)
    cfg = load_runtime_config()
    max_err = float(cfg.get("simulator_fidelity_max_error_pct", 5.0))
    if isinstance(fidelity_max_error_pct, bool) or float(fidelity_max_error_pct) >= max_err or float(fidelity_max_error_pct) < 0.0:
        raise FailClosedError(
            ERR_INVARIANT,
            f"仿真器保真门禁拦截 (P25)：子题 {question_id} 最大分布误差 {fidelity_max_error_pct}% 不满足 < {max_err}%！",
        )

    ep = conn.execute("SELECT stage, contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    stage = str(ep["stage"]) if ep else "STAGE1_PARSE0"
    existing_hook = conn.execute(
        "SELECT hook_sha256, eval_epoch_version FROM domain_hooks_by_question WHERE question_id = ?",
        (question_id,),
    ).fetchone()
    if existing_hook is not None and stage in ("STAGE2_EVOLVE", "STAGE3_CONSOLIDATE", "CLOSED"):
        raise FailClosedError(
            ERR_LOCKED,
            f"STAGE2_HOOK_OVERRIDE_FORBIDDEN: 当前处于 {stage} 且子题 {question_id} 已有锁定钩子 (v{existing_hook['eval_epoch_version']})，禁止用 register_question_domain_hook 静默覆盖；请走 upgrade_hook_with_rqgm_gate 门禁升版！",
        )

    hook_abs = _resolve_repo_or_ws_file(workspace_root, hook_rel_path)
    base_abs = _resolve_repo_or_ws_file(workspace_root, baseline_rel_path)
    norm_hook_rel = _normalize_hook_or_base_rel_path(workspace_root, hook_abs, hook_rel_path)
    norm_base_rel = _normalize_hook_or_base_rel_path(workspace_root, base_abs, baseline_rel_path)
    # P24 AST 跨题隔离扫描
    validate_baseline_isolation_ast(base_abs, question_id)
    hook_sha = sha256_file(hook_abs)
    now = utc_now_iso()

    pub_sample = dict(public_input_sample) if isinstance(public_input_sample, dict) else {}
    pub_sample_json = json.dumps(pub_sample, ensure_ascii=False)

    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO domain_hooks_by_question(
                question_id, hook_rel_path, hook_sha256, baseline_rel_path,
                fidelity_max_error_pct, plugin_protocol_version, eval_epoch_version,
                public_input_sample_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(question_id) DO UPDATE SET
                hook_rel_path = excluded.hook_rel_path,
                hook_sha256 = excluded.hook_sha256,
                baseline_rel_path = excluded.baseline_rel_path,
                fidelity_max_error_pct = excluded.fidelity_max_error_pct,
                plugin_protocol_version = excluded.plugin_protocol_version,
                public_input_sample_json = CASE
                    WHEN excluded.public_input_sample_json != '{}' THEN excluded.public_input_sample_json
                    ELSE domain_hooks_by_question.public_input_sample_json
                END,
                updated_at = excluded.updated_at
            """,
            (
                question_id,
                norm_hook_rel,
                hook_sha,
                norm_base_rel,
                float(fidelity_max_error_pct),
                plugin_protocol_version,
                pub_sample_json,
                now,
                now,
            ),
        )
        if ep is not None and pub_sample:
            contracts = json.loads(ep["contracts_json"]) if ep["contracts_json"] else {}
            if not isinstance(contracts, dict):
                contracts = {}
            qc = dict(contracts.get(question_id) or {})
            qc["public_input_sample"] = pub_sample
            ev_spec = dict(qc.get("evaluator_spec") or {})
            if "public_input" not in ev_spec:
                ev_spec["public_input"] = pub_sample
            qc["evaluator_spec"] = ev_spec
            contracts[question_id] = qc
            conn.execute(
                "UPDATE epoch_config SET contracts_json = ?, updated_at = ? WHERE config_id = 'active'",
                (json.dumps(contracts, ensure_ascii=False), now),
            )
    return build_tool_receipt(
        conn=conn,
        tool_name="register_question_domain_hook",
        question_id=question_id,
        next_step_guidance=f"子题 {question_id} 验证钩子与隔离基线已过 <{max_err}% 保真与 AST 隔离门禁并入库，SHA={hook_sha[:12]}。",
        data={
            "question_id": question_id,
            "hook_rel_path": norm_hook_rel,
            "hook_sha256": hook_sha,
            "fidelity_max_error_pct": float(fidelity_max_error_pct),
            "public_input_sample": pub_sample,
        },
    )


def _load_anchor_cases_for_question(workspace_root: str, question_id: str) -> list[dict[str, Any]]:
    anchors_dir = Path(os.path.realpath(workspace_root)) / "evaluators" / "anchors" / question_id
    if not anchors_dir.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for jf in sorted(anchors_dir.glob("*.json")):
        try:
            loaded = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                cases.extend(c for c in loaded if isinstance(c, dict))
            elif isinstance(loaded, dict):
                cases.append(loaded)
        except Exception:
            continue
    return cases


def _eval_hook_on_anchors(hook_abs: Path, anchors: list[dict[str, Any]]) -> tuple[int, int, float, float, float]:
    s_gt = 0
    f_gt = 0
    pos_total = 0
    pos_pass = 0
    neg_total = 0
    neg_rej = 0
    adv_total = 0
    adv_rej = 0
    with tempfile.TemporaryDirectory(prefix="gw_anchor_") as tmp:
        for i, case in enumerate(anchors):
            art = case.get("stage_a_artifact") or {}
            spec = dict(case.get("spec") or {})
            spec["domain_hook_path"] = str(hook_abs)
            art_file = Path(tmp) / f"art_{i}.json"
            art_file.write_text(json.dumps(art, ensure_ascii=False), encoding="utf-8")
            ver = run_stage_b_revaluation(domain="anchor", evaluator_spec=spec, stage_a_output_path=str(art_file))
            actual_passed = bool(ver.get("passed"))
            expected = bool(case.get("expected_passed", True))
            is_adv = bool(case.get("is_adversarial"))
            if is_adv:
                adv_total += 1
                if not actual_passed:
                    adv_rej += 1
            elif expected:
                pos_total += 1
                if actual_passed:
                    pos_pass += 1
            else:
                neg_total += 1
                if not actual_passed:
                    neg_rej += 1

            if actual_passed == expected:
                s_gt += 1
            else:
                f_gt += 1

    p_plus = (pos_pass / float(pos_total)) if pos_total > 0 else (s_gt / float(max(1, s_gt + f_gt)))
    rp = (adv_rej / float(adv_total)) if adv_total > 0 else 1.0
    p_minus = (neg_rej / float(neg_total)) if neg_total > 0 else rp
    return s_gt, f_gt, p_plus, p_minus, rp


def tool_upgrade_hook_with_rqgm_gate(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    question_id: str,
    new_hook_rel_path: str,
    gt_success_count: int,
    gt_failure_count: int,
    adv_pool_reject_rate: float | None = None,
    adv_pool_positive_rate: float | None = None,
    adv_pool_negative_rate: float | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "upgrade_hook_with_rqgm_gate", session_id=session_id)
    cur = conn.execute("SELECT * FROM domain_hooks_by_question WHERE question_id = ?", (question_id,)).fetchone()
    if cur is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id} 尚未注册初始验证钩子，请先调 register_question_domain_hook")

    old_hook_abs = _resolve_repo_or_ws_file(workspace_root, str(cur["hook_rel_path"]))
    new_hook_abs = _resolve_repo_or_ws_file(workspace_root, new_hook_rel_path)
    norm_new_rel = _normalize_hook_or_base_rel_path(workspace_root, new_hook_abs, new_hook_rel_path)
    old_sha = str(cur["hook_sha256"])
    new_sha = sha256_file(new_hook_abs)
    cfg = load_runtime_config()
    eps = float(cfg.get("eval_anchor_epsilon", 0.05))
    min_samples = int(cfg.get("eval_anchor_min_samples", 5))

    # 拍板 4：若存在自动化真值锚点集，服务端后台实跑新旧钩子覆盖入参计数（防自填！）
    anchors = _load_anchor_cases_for_question(workspace_root, question_id)
    server_ran_anchors = False
    old_qp: float | None
    if anchors:
        server_ran_anchors = True
        s_old, f_old, p_plus_old, p_minus_old, rp_old = _eval_hook_on_anchors(old_hook_abs, anchors)
        s_new, f_new, p_plus_new, p_minus_new, rp_new = _eval_hook_on_anchors(new_hook_abs, anchors)
        old_bb = compute_bb_epsilon(s_old, f_old, eps)
        new_bb = compute_bb_epsilon(s_new, f_new, eps)
        old_qp = compute_adversarial_qp(p_plus_old, p_minus_old, rp_old)
        qp_new = compute_adversarial_qp(p_plus_new, p_minus_new, rp_new)
        eff_rp = rp_new
    else:
        s_new = int(gt_success_count)
        f_new = int(gt_failure_count)
        if s_new + f_new < min_samples:
            raise FailClosedError(
                ERR_INVARIANT,
                f"RQGM 门禁阻断：真值锚点样本数 {s_new + f_new} < 最小要求 {min_samples}",
            )
        old_bb = float(cur["bb_epsilon_score"]) if cur["bb_epsilon_score"] is not None else 0.0
        new_bb = compute_bb_epsilon(s_new, f_new, eps)
        eff_rp = float(adv_pool_reject_rate) if adv_pool_reject_rate is not None else 1.0
        p_plus_new = float(adv_pool_positive_rate) if adv_pool_positive_rate is not None else (s_new / float(max(1, s_new + f_new)))
        p_minus_new = float(adv_pool_negative_rate) if adv_pool_negative_rate is not None else eff_rp
        qp_new = compute_adversarial_qp(p_plus_new, p_minus_new, eff_rp)
        old_qp = float(cur["adversarial_qp_score"]) if cur["adversarial_qp_score"] is not None else None

    # 双向门禁：BB_eps 与 Q_P 均需严格护航（平局保留 incumbent）
    if new_bb <= old_bb + 1e-12:
        raise FailClosedError(
            ERR_INVARIANT,
            f"RQGM 双向门禁拒止（平局保留在位者）：challenger BB_eps={new_bb:.4f} 未严格超越 incumbent={old_bb:.4f}",
        )
    if old_qp is not None and old_qp < 1.0 - 1e-12 and qp_new <= old_qp + 1e-12:
        raise FailClosedError(
            ERR_INVARIANT,
            f"RQGM 对抗池门禁拒止：challenger Q_P={qp_new:.4f} 未严格超越 incumbent Q_P={old_qp:.4f}",
        )
    if old_qp is not None and qp_new < old_qp - 1e-12:
        raise FailClosedError(
            ERR_INVARIANT,
            f"RQGM 对抗池门禁拒止：challenger Q_P={qp_new:.4f} 低于 incumbent Q_P={old_qp:.4f}",
        )

    now = utc_now_iso()
    new_ver = int(cur["eval_epoch_version"]) + 1
    queued_obs: list[str] = []

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE domain_hooks_by_question
            SET hook_rel_path = ?, hook_sha256 = ?, eval_epoch_version = ?, bb_epsilon_score = ?, adversarial_qp_score = ?, updated_at = ?
            WHERE question_id = ?
            """,
            (norm_new_rel, new_sha, new_ver, new_bb, qp_new, now, question_id),
        )
        # 根治 P26：仅选择性将 DEPENDS_ON 该旧钩子的本子题观测标为 PENDING_REVALIDATION 并同事务入队！他题零误杀！
        affected = conn.execute(
            "SELECT obs_id FROM observations WHERE question_id = ? AND obs_status = 'VALID' AND domain_hook_sha256 != ?",
            (question_id, new_sha),
        ).fetchall()
        for row in affected:
            oid = str(row["obs_id"])
            qid_row = f"reval_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO pending_revalidation_queue(queue_id, obs_id, question_id, old_hook_sha256, new_hook_sha256, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (qid_row, oid, question_id, old_sha, new_sha, now, now),
            )
            conn.execute(
                """
                UPDATE observations
                SET obs_status = 'PENDING_REVALIDATION', comparable_rank_score = NULL, updated_at = ?
                WHERE obs_id = ?
                """,
                (now, oid),
            )
            queued_obs.append(oid)
        if queued_obs:
            propagate_dependency_recheck(conn, queued_obs)

    return build_tool_receipt(
        conn=conn,
        tool_name="upgrade_hook_with_rqgm_gate",
        question_id=question_id,
        next_step_guidance=f"{question_id} 钩子已升版至 v{new_ver}（未波及其他子题）。请对 {len(queued_obs)} 条入队观测调 recompute_stage_b_only 读取 stage_a_output.json 秒级恢复 VALID。",
        data={
            "question_id": question_id,
            "new_eval_epoch_version": new_ver,
            "new_hook_sha256": new_sha,
            "server_ran_anchors": server_ran_anchors,
            "bb_epsilon_incumbent": old_bb,
            "bb_epsilon_challenger": new_bb,
            "adversarial_qp": qp_new,
            "pending_revalidation_obs_ids": queued_obs,
        },
    )


def tool_recompute_stage_b_only(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    obs_id: str,
    question_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "recompute_stage_b_only", session_id=session_id)
    obs = conn.execute("SELECT * FROM observations WHERE obs_id = ?", (obs_id,)).fetchone()
    if obs is None:
        raise FailClosedError(ERR_NOT_FOUND, f"观测 {obs_id!r} 不存在")
    if str(obs["question_id"]) != question_id:
        raise FailClosedError(ERR_INVALID_INPUT, f"观测 {obs_id!r} 不属于子题 {question_id!r}")

    hook = conn.execute("SELECT * FROM domain_hooks_by_question WHERE question_id = ?", (question_id,)).fetchone()
    if hook is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id!r} 缺少验证钩子")
    hook_abs = _resolve_repo_or_ws_file(workspace_root, str(hook["hook_rel_path"]))

    stage_a_path = str(obs["stage_a_artifact_path"] or "")
    if not stage_a_path or not Path(stage_a_path).is_file():
        raise FailClosedError(ERR_NOT_FOUND, f"持久化 stage_a_output.json 缺失: {stage_a_path!r}")

    spec = json.loads(obs["evaluator_spec_json"] or "{}")
    spec["domain_hook_path"] = str(hook_abs)
    reval = run_stage_b_revaluation(domain=question_id, evaluator_spec=spec, stage_a_output_path=stage_a_path)

    new_status = str(reval["obs_status"])
    new_passed = 1 if reval.get("passed") else 0
    new_metrics = json.dumps(reval.get("metrics") or {}, ensure_ascii=False)
    new_details = str(reval.get("details") or "")
    new_score = reval.get("comparable_rank_score")
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE observations
            SET obs_status = ?, passed = ?, metrics_json = ?, details_text = ?,
                comparable_rank_score = ?, domain_hook_sha256 = ?, eval_epoch_version = ?, updated_at = ?
            WHERE obs_id = ?
            """,
            (
                new_status,
                new_passed,
                new_metrics,
                new_details,
                new_score,
                str(hook["hook_sha256"]),
                int(hook["eval_epoch_version"]),
                now,
                obs_id,
            ),
        )
        conn.execute(
            "UPDATE pending_revalidation_queue SET status = 'COMPLETED', updated_at = ? WHERE obs_id = ? AND status = 'PENDING'",
            (now, obs_id),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="recompute_stage_b_only",
        question_id=question_id,
        next_step_guidance=f"{obs_id} Stage B 免重跑秒级重算完成，当前状态 {new_status}。",
        data={
            "obs_id": obs_id,
            "obs_status": new_status,
            "passed": bool(new_passed),
            "metrics": reval.get("metrics") or {},
            "details": new_details,
            "comparable_rank_score": new_score,
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
    enforce_role_tool_permission(conn, caller_role, "update_skill_ledger", session_id=session_id)
    if not re.match(r"^[a-z0-9_]+$", (skill_id or "").strip()):
        raise FailClosedError(ERR_INVALID_INPUT, f"skill_id 必须匹配 ^[a-z0-9_]+$（无空格连字符）：{skill_id!r}")

    artifact_abs = _resolve_repo_or_ws_file(workspace_root, verified_artifact_rel_path)
    if artifact_abs.stat().st_size == 0:
        raise FailClosedError(ERR_INVARIANT, f"No File 物理验证失败：产物为空文件 {verified_artifact_rel_path!r}")

    paths = resolve_storage_paths(workspace_root)
    ledger_path = Path(paths["skill_ledger_path"])
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.is_file():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    else:
        base_ledger = core_python_root() / "skills" / "SKILL_LEDGER.json"
        ledger = json.loads(base_ledger.read_text(encoding="utf-8")) if base_ledger.is_file() else {"schema_version": "2.2.0", "skills": {}}
    ledger.setdefault("skills", {})[skill_id] = {
        "skill_id": skill_id,
        "applicable_scope": applicable_scope.strip(),
        "version": int(version),
        "raw_success_count": int(raw_success_count),
        "raw_failure_count": int(raw_failure_count),
        "verified_artifact_rel_path": verified_artifact_rel_path,
        "rollback_pointer": rollback_pointer,
        "last_no_file_passed": True,
        "updated_at": utc_now_iso(),
    }
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return build_tool_receipt(
        conn=conn,
        tool_name="update_skill_ledger",
        question_id="GLOBAL",
        next_step_guidance=f"B 档工具 {skill_id} 已过 No File 物理校验并写入工作区隔离账本 {ledger_path.as_posix()}。",
        data={
            "skill_id": skill_id,
            "verified_artifact_rel_path": verified_artifact_rel_path,
            "skill_ledger_path": str(ledger_path),
        },
    )


