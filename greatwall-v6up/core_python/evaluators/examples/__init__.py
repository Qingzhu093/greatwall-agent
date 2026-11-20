"""AI for Science 可插拔课题级参考验证钩子示例包（由工造司按需挂载，非通用底座硬编码）。"""

from .formal_proof import evaluate_formal_proof
from .pareto_frontier import evaluate_pareto_frontier
from .physics_sim import evaluate_physics_sim

__all__ = [
    "evaluate_formal_proof",
    "evaluate_pareto_frontier",
    "evaluate_physics_sim",
]
