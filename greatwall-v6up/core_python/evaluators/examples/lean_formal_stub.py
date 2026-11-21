"""v3.0 最小协议写法参考：形式化证明仪器接口示范（仅作通信协议样例，非真实 Lean 内核实证）。

演示形式化证明课题中：
- 通过 `get_public_input(spec)` 读取锁定命题声明与允许公理白名单；
- 严格返回标量 `tracks` 与规范三值枚举 `PASS / FAIL / UNDECIDED`；
- 校对命题 SHA-256、拦截 `sorry`/`admit` 与未授权公理，汇报未闭合义务数。
"""

from __future__ import annotations

import hashlib
from typing import Any

from core_python.evaluators.base_instrument import get_public_input

STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})


def _norm_sha256(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def evaluate(artifact: Any, spec: dict[str, Any], tier: str = "official") -> dict[str, Any]:
    """形式化证明产物最小协议核验示例。"""
    pub = get_public_input(spec)
    expected_stmt = str(pub.get("theorem_statement") or "").strip()
    allowed_axioms = STANDARD_AXIOMS | {
        str(x).strip() for x in pub.get("allowed_extra_axioms", []) if str(x).strip()
    }

    if not isinstance(artifact, dict):
        return {
            "status": "OK",
            "verdict": "FAIL",
            "tracks": {"tier": str(tier), "format_valid": False},
            "details": "候选证明产物必须为 JSON 对象。",
        }

    stmt = str(artifact.get("theorem_statement") or "").strip()
    if not stmt:
        return {
            "status": "OK",
            "verdict": "FAIL",
            "tracks": {"tier": str(tier), "theorem_matched": False},
            "details": "缺少 theorem_statement 字段。",
        }

    theorem_matched = (not expected_stmt) or (_norm_sha256(stmt) == _norm_sha256(expected_stmt))
    axioms = [str(a).strip() for a in (artifact.get("axioms_used") or []) if str(a).strip()]
    has_sorry = any("sorry" in a.lower() or "admit" in a.lower() for a in axioms)
    disallowed = sorted(set(axioms) - allowed_axioms)

    obligations = artifact.get("obligations") or []
    total_ob = len(obligations) if isinstance(obligations, list) else 0
    proved_ob = sum(
        1 for ob in obligations if isinstance(ob, dict) and ob.get("proved") is True
    ) if isinstance(obligations, list) else 0
    open_goals = max(0, total_ob - proved_ob)

    passed = theorem_matched and (not has_sorry) and (not disallowed) and (total_ob > 0) and (open_goals == 0)
    if passed:
        verdict = "PASS"
    elif tier == "probe" and theorem_matched and not has_sorry and not disallowed and open_goals > 0:
        verdict = "UNDECIDED"
    else:
        verdict = "FAIL"

    return {
        "status": "OK",
        "verdict": verdict,
        "tracks": {
            "tier": str(tier),
            "theorem_matched": theorem_matched,
            "has_sorry": has_sorry,
            "disallowed_axiom_count": len(disallowed),
            "disallowed_axioms": ",".join(disallowed),
            "proved_obligations": proved_ob,
            "total_obligations": total_ob,
            "open_goals": open_goals,
        },
        "details": (
            f"形式化证明协议样例通过（{proved_ob}/{total_ob} 义务闭合，无违规公理）。"
            if passed
            else f"未通过核验：theorem_matched={theorem_matched}, has_sorry={has_sorry}, disallowed={disallowed}, open_goals={open_goals}"
        ),
    }
