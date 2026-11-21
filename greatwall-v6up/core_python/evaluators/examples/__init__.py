"""GreatWall v3.0 通用异构验证仪器示例包。

所有示例均严格遵循三档同码协议：
- 导出 `evaluate(artifact, spec, tier) -> {"status": "OK", "verdict": ..., "tracks": {...}, "details": "..."}`；
- 通过 `get_public_input(spec)` 读取外部输入，缺失时自动抛出 `InstrumentInputError`（由底座记为 `INSTRUMENT_ERROR`，绝不误伤探索者）；
- 不强制单标量打分，允许纯布尔判据、形式化验证摘要与多轨道 Pareto 向量。
"""

from .geom_counterexample import evaluate as evaluate_geom_counterexample
from .lean_formal_stub import evaluate as evaluate_lean_formal_stub
from .pareto_sim import evaluate as evaluate_pareto_sim

__all__ = [
    "evaluate_geom_counterexample",
    "evaluate_lean_formal_stub",
    "evaluate_pareto_sim",
]
