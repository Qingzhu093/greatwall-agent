"""多保真物理仿真领域适配器（质量守恒 / 二次凸熵非增 / Lax 熵条件）。

核心不变量（对齐《宿主机边界与文献源码对齐说明.md》§1.1 & §2.4）：
1. 总质量守恒：|sum(u_final)*dx - sum(u_init)*dx| <= mass_tol。
2. 二次凸熵非增：E(u) = 0.5 * sum(u^2) * dx，验证末态及历史序列不发生非物理熵增。
3. Lax 熵条件（双曲守恒律如 1D Burgers）：拦截尖锐非物理膨胀激波（u_L < u_R - threshold）。
"""

from __future__ import annotations

import math
from typing import Any


def _is_num_list(val: Any) -> bool:
    return (
        isinstance(val, list)
        and len(val) >= 4
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x)) for x in val)
    )


def _as_finite_float(val: Any) -> float | None:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def evaluate_physics_sim(
    candidate_output: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """评估一维守恒律/物理仿真候选解。"""
    u_init_raw = candidate_output.get("u_init")
    u_final_raw = candidate_output.get("u_final")
    dx_raw = candidate_output.get("dx")

    if not _is_num_list(u_init_raw) or not _is_num_list(u_final_raw):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_FIELD_ARRAY",
        }
    if len(u_init_raw) != len(u_final_raw):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "GRID_SHAPE_MISMATCH",
        }
    if (
        not isinstance(dx_raw, (int, float))
        or isinstance(dx_raw, bool)
        or not math.isfinite(float(dx_raw))
        or float(dx_raw) <= 0.0
    ):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_DX",
        }

    u_init = [float(x) for x in u_init_raw]
    u_final = [float(x) for x in u_final_raw]
    dx = float(dx_raw)

    # 锚定题目给定的 u_init / dx（spec 优先，其次 spec.public_input）
    pub = spec.get("public_input") if isinstance(spec.get("public_input"), dict) else {}
    init_tol = float(spec.get("init_tol", 1e-9))
    expected_u_init = spec.get("expected_u_init")
    if expected_u_init is None:
        expected_u_init = spec.get("u_init")
    if expected_u_init is None:
        expected_u_init = pub.get("u_init")
    if isinstance(expected_u_init, list):
        if not _is_num_list(expected_u_init) or len(expected_u_init) != len(u_init):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INIT_CONDITION_MISMATCH",
            }
        max_init_diff = max(abs(a - float(b)) for a, b in zip(u_init, expected_u_init))
        if max_init_diff > init_tol:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"max_init_diff": max_init_diff},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INIT_CONDITION_MISMATCH",
            }

    expected_dx = spec.get("expected_dx")
    if expected_dx is None:
        expected_dx = spec.get("dx")
    if expected_dx is None:
        expected_dx = pub.get("dx")
    if expected_dx is None:
        domain_len = spec.get("domain_length")
        if domain_len is None:
            domain_len = spec.get("L")
        if domain_len is None:
            domain_len = pub.get("domain_length")
        if domain_len is None:
            domain_len = pub.get("L")
        dom_len_f = _as_finite_float(domain_len)
        if dom_len_f is not None and dom_len_f > 0.0:
            expected_dx = dom_len_f / float(len(u_init))

    exp_dx_f = _as_finite_float(expected_dx)
    has_anchored_dx = exp_dx_f is not None and exp_dx_f > 0.0
    if has_anchored_dx:
        if abs(dx - exp_dx_f) > 1e-12 * max(1.0, abs(exp_dx_f)):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"expected_dx": exp_dx_f, "actual_dx": dx},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "DX_MISMATCH",
            }
    else:
        min_dx = _as_finite_float(spec.get("min_dx"))
        min_dx_val = min_dx if (min_dx is not None and min_dx > 0.0) else 1e-6
        if dx < min_dx_val:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"actual_dx": dx, "min_dx": min_dx_val},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INVALID_DX",
            }

    # 若提供解析参考解则先强校验形状（供后续开放边界/误差计算使用）
    ref = spec.get("reference_u_final")
    has_ref = isinstance(ref, list)
    ref_vals: list[float] = []
    if has_ref:
        if not _is_num_list(ref) or len(ref) != len(u_final):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "REFERENCE_SHAPE_MISMATCH",
            }
        ref_vals = [float(x) for x in ref]

    mass_tol = float(spec.get("mass_tol", 1e-8))
    entropy_tol = float(spec.get("entropy_tol", 1e-9))
    periodic = bool(spec.get("periodic", False))
    boundary_type = str(spec.get("boundary_type", "periodic" if periodic else "closed")).strip().lower()
    is_open_boundary = (not periodic) and (boundary_type in {"outflow", "open"})

    exp_net = _as_finite_float(spec.get("expected_net_mass_change"))
    if exp_net is None:
        exp_net = _as_finite_float(spec.get("expected_mass_change"))
    if exp_net is None:
        exp_net = _as_finite_float(pub.get("expected_net_mass_change"))
    if exp_net is None:
        exp_net = _as_finite_float(pub.get("expected_mass_change"))
    in_flux = _as_finite_float(spec.get("inflow_flux"))
    if in_flux is None:
        in_flux = _as_finite_float(pub.get("inflow_flux"))
    out_flux = _as_finite_float(spec.get("outflow_flux"))
    if out_flux is None:
        out_flux = _as_finite_float(pub.get("outflow_flux"))
    if exp_net is None and in_flux is not None and out_flux is not None:
        exp_net = in_flux - out_flux

    if is_open_boundary and exp_net is None and not has_ref:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {"boundary_type": boundary_type},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "MISSING_BOUNDARY_FLUX_SPEC",
        }

    # 1. 总质量守恒（未锚定 dx 时校验格点尺度防微小 dx 缩放逃逸；开放边界核验净通量残差）
    mass_init = sum(u_init) * dx
    mass_final = sum(u_final) * dx
    mass_drift = abs(mass_final - mass_init)
    n_cells = len(u_init)
    eff_mass_scale = 1.0 if has_anchored_dx else max(1.0, (1.0 / float(n_cells)) / dx)
    if is_open_boundary:
        target_net = exp_net if exp_net is not None else ((sum(ref_vals) - sum(u_init)) * dx)
        net_err = abs((mass_final - mass_init) - target_net)
        mass_ok = (net_err * eff_mass_scale) <= mass_tol
    else:
        target_net = 0.0
        net_err = mass_drift
        mass_ok = (mass_drift * eff_mass_scale) <= mass_tol

    # 2. 二次凸熵非增 E(u) = 0.5 * sum(u^2) * dx（若提供 u_history 强制锚定首尾帧及所有中间帧）
    def _quad_entropy(arr: list[float]) -> float:
        return 0.5 * sum(v * v for v in arr) * dx

    entropy_init = _quad_entropy(u_init)
    entropy_final = _quad_entropy(u_final)
    max_entropy_increase = entropy_final - entropy_init
    max_abs_u_seen = max(max(abs(v) for v in u_init), max(abs(v) for v in u_final))
    history_max_mass_drift = 0.0

    u_history = candidate_output.get("u_history")
    has_history = isinstance(u_history, list) and len(u_history) >= 2
    if has_history:
        first_frame = u_history[0]
        last_frame = u_history[-1]
        if not _is_num_list(first_frame) or len(first_frame) != len(u_init) or not _is_num_list(last_frame) or len(last_frame) != len(u_final):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INVALID_HISTORY_STEP",
            }
        if (
            max(abs(float(a) - b) for a, b in zip(first_frame, u_init)) > init_tol
            or max(abs(float(a) - b) for a, b in zip(last_frame, u_final)) > init_tol
        ):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "HISTORY_ENDPOINT_MISMATCH",
            }
        prev_e = None
        for step_arr in u_history:
            if not _is_num_list(step_arr) or len(step_arr) != len(u_init):
                return {
                    "validity_state": "INVALIDATED",
                    "raw_metrics": {},
                    "domain_invariants_passed": False,
                    "comparable_rank_score": None,
                    "failure_category": "INVALID_HISTORY_STEP",
                }
            frame_vals = [float(x) for x in step_arr]
            frame_max_abs = max(abs(v) for v in frame_vals)
            if frame_max_abs > max_abs_u_seen:
                max_abs_u_seen = frame_max_abs
            if not is_open_boundary:
                frame_mass_drift = abs(sum(frame_vals) * dx - mass_init)
                if frame_mass_drift > history_max_mass_drift:
                    history_max_mass_drift = frame_mass_drift
                if (frame_mass_drift * eff_mass_scale) > mass_tol:
                    mass_ok = False
            cur_e = _quad_entropy(frame_vals)
            if prev_e is not None:
                delta_step = cur_e - prev_e
                if delta_step > max_entropy_increase:
                    max_entropy_increase = delta_step
            if not is_open_boundary:
                net_step_e = cur_e - entropy_init
                if net_step_e > max_entropy_increase:
                    max_entropy_increase = net_step_e
            prev_e = cur_e

    if is_open_boundary:
        max_abs_u_init = max(abs(v) for v in u_init)
        spec_u_bound = None
        for bkey in ("max_u_bound", "inflow_u", "u_inflow", "boundary_u"):
            bv = _as_finite_float(spec.get(bkey))
            if bv is None:
                bv = _as_finite_float(pub.get(bkey))
            if bv is not None:
                spec_u_bound = max(spec_u_bound or 0.0, abs(bv))
        if has_ref:
            ref_max_abs = max(abs(v) for v in ref_vals)
            u_bound = max(max_abs_u_init, ref_max_abs) * (1.0 + 1e-6) + 1e-9
        elif spec_u_bound is not None:
            u_bound = max(max_abs_u_init, spec_u_bound) * (1.0 + 1e-6) + 1e-9
        else:
            dom_len_eff = dx * float(n_cells)
            u_bound = max(max_abs_u_init, 1.0 + abs(target_net) / dom_len_eff) * 2.0
        bounded_ok = max_abs_u_seen <= u_bound + 1e-9

        efb = _as_finite_float(spec.get("entropy_flux_bound"))
        if efb is not None:
            entropy_ok = bounded_ok and (max_entropy_increase <= efb + entropy_tol)
        elif has_ref:
            entropy_ref = _quad_entropy(ref_vals)
            ref_inc_bound = max(0.0, entropy_ref - entropy_init) + max(entropy_tol, 0.05 * max(1.0, entropy_ref))
            entropy_ok = bounded_ok and (max_entropy_increase <= ref_inc_bound)
        elif (in_flux is not None and in_flux <= 0.0) or (in_flux is None and target_net <= 0.0):
            # 纯流出或无入流：能量不可显著增长，幅度亦受初值极值约束
            entropy_ok = bounded_ok and (max_abs_u_seen <= max_abs_u_init + 1e-6) and (max_entropy_increase <= entropy_tol)
        else:
            inflow_scale = max(in_flux if in_flux is not None else 0.0, abs(target_net))
            phys_e_bound = 0.5 * (u_bound ** 2) * inflow_scale + entropy_tol
            entropy_ok = bounded_ok and (max_entropy_increase <= phys_e_bound)
    else:
        entropy_ok = max_entropy_increase <= entropy_tol

    # 3. 离散 Oleinik / Lax 熵条件（局部单侧 Lipschitz 衰减上界 + 跨声速驻定膨胀激波拦截）
    lax_violations = 0
    max_expansion_jump = 0.0
    n = len(u_final)
    upper = n if periodic else n - 1
    init_max_jump = max([0.0] + [u_init[(i + 1) % n] - u_init[i] for i in range(upper)])

    explicit_thresh = _as_finite_float(spec.get("shock_jump_threshold"))
    t_final_val = _as_finite_float(spec.get("t_final"))
    if t_final_val is None:
        t_final_val = _as_finite_float(pub.get("t_final"))
    if t_final_val is None and has_history:
        dt_val = _as_finite_float(spec.get("dt")) or _as_finite_float(pub.get("dt"))
        if dt_val is not None and dt_val > 0.0:
            t_final_val = dt_val * float(len(u_history) - 1)

    for i in range(upper):
        u_left = u_final[i]
        u_right = u_final[(i + 1) % n]
        jump = u_right - u_left
        if jump > max_expansion_jump:
            max_expansion_jump = jump
        if jump <= 0.0:
            continue
        if explicit_thresh is not None:
            if jump > explicit_thresh:
                lax_violations += 1
        else:
            # (a) 凸通量禁止膨胀段反向陡化（jump > init_max_jump）
            if jump > init_max_jump + max(1e-9, 1e-9 * init_max_jump):
                lax_violations += 1
            elif t_final_val is not None and t_final_val > 0.0:
                if u_left < 0.0 < u_right:
                    # (b1) 跨声速点 (u_L < 0 < u_R) 离散 Godunov / Oleinik 衰减上界
                    trans_bound = (
                        (4.0 * dx) / (t_final_val + (4.0 * dx / max(init_max_jump, 1e-12)))
                        if init_max_jump > 0.0
                        else 0.0
                    )
                    if jump > 1.05 * trans_bound + 1e-9:
                        lax_violations += 1
                    else:
                        # 极粗网格单步尺度下仍维持原间断的静态跨声速驻定跃迁予以拦截
                        tol_static = min(
                            1e-3,
                            0.01 * t_final_val * max(abs(u_init[i]), abs(u_init[(i + 1) % n])) / dx,
                        )
                        if (
                            jump >= max(0.25, 0.99 * init_max_jump)
                            and abs(u_left - u_init[i]) <= tol_static
                            and abs(u_right - u_init[(i + 1) % n]) <= tol_static
                        ):
                            lax_violations += 1
                else:
                    # (b2) 同号单侧稀疏区间局部 Oleinik 上界 dx / t_final
                    mono_bound = dx / t_final_val
                    if jump > 1.05 * mono_bound + 1e-9:
                        lax_violations += 1
            else:
                # (c) 缺失演化时间 t_final 时拦截跨声速孤立强间断驻定解
                if u_left < 0.0 < u_right and jump >= max(0.25, 0.95 * init_max_jump):
                    lax_violations += 1
    lax_ok = lax_violations == 0

    raw_metrics: dict[str, Any] = {
        "mass_init": mass_init,
        "mass_final": mass_final,
        "mass_drift": mass_drift,
        "history_max_mass_drift": history_max_mass_drift,
        "mass_ok": mass_ok,
        "entropy_init": entropy_init,
        "entropy_final": entropy_final,
        "max_entropy_increase": max_entropy_increase,
        "entropy_ok": entropy_ok,
        "lax_violations": lax_violations,
        "max_expansion_jump": max_expansion_jump,
        "init_max_expansion_jump": init_max_jump,
        "lax_ok": lax_ok,
        "boundary_type": boundary_type,
    }

    # 若提供解析参考解则计算 L1 误差（未锚定 dx 时使用格点平均误差防止 dx 缩放作弊）
    l1_error: float | None = None
    mean_l1_error: float | None = None
    if has_ref:
        abs_errs = [abs(a - b) for a, b in zip(u_final, ref_vals)]
        l1_error = sum(abs_errs) * dx
        mean_l1_error = sum(abs_errs) / float(len(u_final))
        raw_metrics["l1_error"] = l1_error
        raw_metrics["mean_l1_error"] = mean_l1_error

    failure_reasons: list[str] = []
    if not mass_ok:
        failure_reasons.append("MASS_CONSERVATION_VIOLATED")
    if not entropy_ok:
        failure_reasons.append("ENTROPY_PRODUCTION_VIOLATED")
    if not lax_ok:
        failure_reasons.append("LAX_ENTROPY_VIOLATED")

    if failure_reasons:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": raw_metrics,
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": failure_reasons[0],
        }

    if l1_error is not None:
        score = -l1_error if has_anchored_dx else -float(mean_l1_error)
    elif is_open_boundary:
        score = -net_err
    else:
        score = -mass_drift
    return {
        "validity_state": "VALID",
        "raw_metrics": raw_metrics,
        "domain_invariants_passed": True,
        "comparable_rank_score": score,
        "failure_category": "",
    }


def evaluate(candidate_output: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """标准可插拔课题验证钩子入口。"""
    return evaluate_physics_sim(candidate_output, spec)
