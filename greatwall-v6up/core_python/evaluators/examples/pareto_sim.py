"""v3.0 最小协议写法参考：多轨道向量核验样例（无单一总分，仅作通信协议示范）。

演示多目标课题中：
- 严格返回标量键值 `tracks`（将各维度展开为 `obj_<dim>` 标量，不嵌套 dict/list）；
- 强校验 `nadir_floors` 要求的全部目标维度均已提交且均不跌破底线；
- 合法零解与边界解按真实底线正常判定，底座不做越权拦截。
"""

from __future__ import annotations

import math
from typing import Any

from core_python.evaluators.base_instrument import get_public_input


def evaluate(artifact: Any, spec: dict[str, Any], tier: str = "official") -> dict[str, Any]:
    """多目标设计方案的最小多轨道底线核验样例。"""
    pub = get_public_input(spec)
    nadir = pub.get("nadir_floors") or {}
    if not isinstance(artifact, dict) or not isinstance(artifact.get("objectives"), dict):
        return {
            "status": "OK",
            "verdict": "FAIL",
            "tracks": {"tier": str(tier), "format_valid": False},
            "details": "候选产物必须提供 objectives 字典。",
        }

    objs = artifact["objectives"]
    tracks: dict[str, Any] = {"tier": str(tier)}
    violated: list[str] = []
    missing_dims: list[str] = []

    # 校验每个声明的底线维度均必须出现，防遗漏维度绕过底线检查
    for req_dim in nadir.keys():
        if str(req_dim) not in objs:
            missing_dims.append(str(req_dim))

    dim_count = 0
    for dim_name, raw_val in objs.items():
        dkey = str(dim_name)
        if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)) or not math.isfinite(float(raw_val)):
            return {
                "status": "OK",
                "verdict": "FAIL",
                "tracks": {"tier": str(tier), "invalid_dim": dkey},
                "details": f"目标维度 {dkey} 非有限数值。",
            }
        val = float(raw_val)
        tracks[f"obj_{dkey}"] = val
        dim_count += 1
        if dkey in nadir:
            floor = float(nadir[dkey])
            if val < floor - 1e-12:
                violated.append(dkey)

    tracks["dimension_count"] = dim_count
    tracks["missing_nadir_count"] = len(missing_dims)
    tracks["violated_nadir_count"] = len(violated)
    tracks["violated_nadir_dims"] = ",".join(sorted(violated))
    tracks["missing_nadir_dims"] = ",".join(sorted(missing_dims))

    passed = (len(missing_dims) == 0) and (len(violated) == 0) and (dim_count > 0)
    return {
        "status": "OK",
        "verdict": "PASS" if passed else "FAIL",
        "tracks": tracks,
        "details": (
            f"多轨道底线复核通过（{dim_count} 维全部达标）。"
            if passed
            else f"未通过底线核验：missing={missing_dims}, violated={violated}"
        ),
    }
