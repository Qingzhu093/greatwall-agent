"""v3.0 通用仪器示例 1：纯几何反例构造独立复核（无单标量，二值硬判据）。

演示当探索者声称构造出一个违反猜想不等式 `f(x) <= threshold` 的几何点位时，
仪器只用 `get_public_input(spec)` 中的几何参数和约束容差做独立精确复核。
"""

from __future__ import annotations

import math
from typing import Any

from core_python.evaluators.base_instrument import get_public_input


def evaluate(artifact: Any, spec: dict[str, Any], tier: str = "official") -> dict[str, Any]:
    """核验候选反例是否满足可行域约束并严格突破目标界。"""
    pub = get_public_input(spec)
    threshold = float(pub.get("conjecture_bound", 1.0))
    eps = float(pub.get("tol", 1e-9))
    min_dim = int(pub.get("dimension", 2))

    if not isinstance(artifact, dict) or not isinstance(artifact.get("points"), list):
        return {
            "status": "OK",
            "verdict": "FAIL",
            "tracks": {"format_valid": False, "tier": tier},
            "details": "候选产物缺少合法的 points 坐标列表。",
        }

    points = artifact["points"]
    if len(points) < 2:
        return {
            "status": "OK",
            "verdict": "FAIL",
            "tracks": {"point_count": len(points), "tier": tier},
            "details": "反例点集数量不足（至少需要 2 个点）。",
        }

    parsed: list[list[float]] = []
    for pt in points:
        if not isinstance(pt, list) or len(pt) != min_dim:
            return {
                "status": "OK",
                "verdict": "FAIL",
                "tracks": {"dimension_match": False, "tier": tier},
                "details": f"点坐标维度与题目要求 dim={min_dim} 不一致。",
            }
        coords = [float(v) for v in pt]
        if not all(math.isfinite(c) for c in coords):
            return {
                "status": "OK",
                "verdict": "FAIL",
                "tracks": {"finite": False, "tier": tier},
                "details": "点坐标包含 NaN 或 Inf。",
            }
        parsed.append(coords)

    # 独立计算最大两两欧氏距离与规范化能量比率
    max_dist = 0.0
    min_dist = float("inf")
    n = len(parsed)
    for i in range(n):
        for j in range(i + 1, n):
            d = math.dist(parsed[i], parsed[j])
            max_dist = max(max_dist, d)
            min_dist = min(min_dist, d)

    ratio = (max_dist / min_dist) if min_dist > eps else float("inf")
    is_counterexample = math.isfinite(ratio) and (ratio > threshold + eps)

    return {
        "status": "OK",
        "verdict": "PASS" if is_counterexample else "FAIL",
        "tracks": {
            "tier": tier,
            "point_count": n,
            "min_dist": min_dist,
            "max_dist": max_dist,
            "aspect_ratio": ratio if math.isfinite(ratio) else None,
            "conjecture_bound": threshold,
            "is_counterexample": is_counterexample,
        },
        "details": (
            f"独立复核通过：aspect_ratio={ratio:.6g} > bound={threshold:.6g}"
            if is_counterexample
            else f"未构成有效反例：aspect_ratio={ratio:.6g} <= bound={threshold:.6g}"
        ),
    }
