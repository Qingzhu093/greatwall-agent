"""多目标帕累托前沿领域适配器（nadir 底线过滤 / 支配判定 / Level 3 特异保护标记）。

核心不变量（对齐《宿主机边界与文献源码对齐说明.md》§1.1 & §2.4）：
1. r_nadir 底线向量硬过滤：任一目标跌破底线即判 INVALIDATED，禁止入前沿。
2. 标准化正向空间内的 Pareto 支配关系判定与参考超体积计算。
3. 偏科特异候选标记（level3_candidate=True）：全维达标且非支配、至少在一维超越现有前沿极值 novelty_margin。
"""

from __future__ import annotations

import math
from typing import Any


def _extract_vector(
    obj: Any, names: list[str]
) -> list[float] | None:
    if isinstance(obj, dict):
        vec: list[float] = []
        for name in names:
            if name not in obj:
                return None
            v = obj[name]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                return None
            vec.append(float(v))
        return vec
    if isinstance(obj, list) and len(obj) == len(names):
        vec = []
        for v in obj:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                return None
            vec.append(float(v))
        return vec
    return None


def evaluate_pareto_frontier(
    candidate_output: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """评估多目标帕累托前沿候选解。"""
    raw_obj = candidate_output.get("objectives")
    r_nadir_raw = spec.get("r_nadir")
    names = spec.get("objective_names")
    if not isinstance(names, list) or not names:
        if isinstance(r_nadir_raw, dict) and r_nadir_raw:
            names = [str(k) for k in r_nadir_raw.keys()]
        elif isinstance(raw_obj, dict) and raw_obj:
            names = [str(k) for k in raw_obj.keys()]
        else:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "MISSING_OBJECTIVE_NAMES",
            }
    names = [str(n) for n in names]
    dim = len(names)
    raw_tol = spec.get("numerical_tol", 1e-12)
    if (
        isinstance(raw_tol, bool)
        or not isinstance(raw_tol, (int, float))
        or not math.isfinite(float(raw_tol))
        or float(raw_tol) < 0.0
    ):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_NUMERICAL_TOL",
        }
    eps = float(raw_tol)

    vec = _extract_vector(raw_obj, names)
    if vec is None:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_OBJECTIVES_VECTOR",
        }

    directions = spec.get("directions", ["max"] * dim)
    if not isinstance(directions, list) or len(directions) != dim:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_DIRECTIONS",
        }
    dirs_norm: list[str] = []
    for d in directions:
        ds = str(d).strip().lower()
        if ds not in {"max", "min"}:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INVALID_DIRECTION_VALUE",
            }
        dirs_norm.append(ds)

    nadir_vec = _extract_vector(r_nadir_raw, names)
    if nadir_vec is None:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "MISSING_R_NADIR",
        }

    # 1. r_nadir 底线硬过滤（含 IEEE-754 数值容差）并转换至统一最大化正向空间 z >= 0
    violated_dims: list[str] = []
    z_cand: list[float] = []
    for idx in range(dim):
        val = vec[idx]
        floor = nadir_vec[idx]
        if dirs_norm[idx] == "max":
            margin = val - floor
        else:
            margin = floor - val
        if margin < -eps:
            violated_dims.append(names[idx])
        z_cand.append(max(0.0, margin) if margin >= -eps else margin)

    if violated_dims:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {
                "nadir_violated": True,
                "violated_dimensions": violated_dims,
            },
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "NADIR_FLOOR_VIOLATED",
        }

    # 2. 对比参考前沿判定支配关系（引入 eps 数值容差）
    def _to_z(raw_point: Any) -> list[float] | None:
        pv = _extract_vector(raw_point, names)
        if pv is None:
            return None
        out: list[float] = []
        for idx in range(dim):
            m = pv[idx] - nadir_vec[idx] if dirs_norm[idx] == "max" else nadir_vec[idx] - pv[idx]
            out.append(max(0.0, m) if m >= -eps else m)
        return out

    def _dominates(a: list[float], b: list[float]) -> bool:
        return all(x >= y - eps for x, y in zip(a, b)) and any(x > y + eps for x, y in zip(a, b))

    ref_frontier_raw = spec.get("reference_frontier", [])
    ref_z_points: list[list[float]] = []
    if isinstance(ref_frontier_raw, list):
        for pt in ref_frontier_raw:
            zp = _to_z(pt)
            if zp is not None and all(v >= -eps for v in zp):
                ref_z_points.append(zp)

    dominated_by_frontier = any(_dominates(rp, z_cand) for rp in ref_z_points)
    dominates_count = sum(1 for rp in ref_z_points if _dominates(z_cand, rp))

    # 计算相对 nadir 矩形体积与加权参考标量
    hypervolume_box = 1.0
    for zv in z_cand:
        hypervolume_box *= max(zv, 0.0)

    weights_raw = spec.get("weights")
    if isinstance(weights_raw, list) and len(weights_raw) == dim:
        weights = [float(w) for w in weights_raw]
    else:
        weights = [1.0 / dim] * dim
    scalar_score = sum(w * zv for w, zv in zip(weights, z_cand))

    # 3. Level 3 偏科特异保护标记
    novelty_margin = float(spec.get("novelty_margin", 0.05))
    novel_dimensions: list[str] = []
    if not dominated_by_frontier and ref_z_points:
        for idx in range(dim):
            best_ref_i = max(rp[idx] for rp in ref_z_points)
            if z_cand[idx] + eps >= best_ref_i + novelty_margin:
                novel_dimensions.append(names[idx])
    level3_candidate = (not dominated_by_frontier) and len(novel_dimensions) > 0

    return {
        "validity_state": "VALID",
        "raw_metrics": {
            "nadir_violated": False,
            "dominated_by_frontier": dominated_by_frontier,
            "dominates_count": dominates_count,
            "hypervolume_box": hypervolume_box,
            "scalar_score": scalar_score,
            "level3_candidate": level3_candidate,
            "novel_dimensions": novel_dimensions,
        },
        "domain_invariants_passed": True,
        "comparable_rank_score": scalar_score,
        "failure_category": "",
    }


def evaluate(candidate_output: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """标准可插拔课题验证钩子入口。"""
    return evaluate_pareto_frontier(candidate_output, spec)
