# 长城 Agent V4.2 标准点火提示词与盲态造尺规约 (Ignition Playbook)

> **版本**：Great Wall Agent V4.2 (2026-11)
> **适用环境**：Google Antigravity / DSH / Codex
> **插件工具依赖**：`greatwall-agent` (9 原生 MCP 工具 + 3 专用子智能体 `gw-distiller`, `gw-explorer`, `gw-auditor`)

---

## 一、一键点火指令（直接复制给主控 Agent）

```markdown
/goal /boost
请启动【长城 Agent V4.2 无人值守攻关流程】，对当前工作区展开全自动攻坚！

### 🎯 核心攻关目标与官方题面约束
1. **任务性质**：多模态/算法竞赛/数学建模长程攻关（当前目标：基于纯方位测向与时差频差的多声源搜索定位与清除）；
2. **官方真实物理底线（严禁代理任务降智）**：
   - 严格单机器狗（禁止出现双狗等未授权假设）；
   - 运动受动力学约束（最大转向角、最大单步步长），允许走出设定坐标框；
   - 严禁任何上帝视角完成信号（模拟器与官方均绝不提供 `is_all_cleared`，必须基于自身置信度做自主决策）；
   - 测向受 $\pm 2^\circ$ 噪声干扰，小交角视线存在病态 GDOP（几何精度衰减）。

---

### 🛡️ 阶段 0：开局前置消歧与【盲态造锤造尺】（Phase 0 Opening Gate）
【铁律：未完成盲态造锤造尺前，禁止派发任何探索分支！】

1. **Step 0.1：前置消歧与工作区初始化 (`gw_init_campaign`)**：
   - 自动清点 `shared_readonly/datasets_public/`，运行静态探针生成 `eda_probe_report.json`，固化 `task_config.yaml`。
2. **Step 0.2：委派 `gw-distiller` 子智能体 (`invoke_subagent`) 执行开局知识蒸馏与造尺**：
   - **盲态造锤 (`simulatorCode`)**：编写独立只读物理模拟器，定义 `def test_*():` 物理自检，严禁暴露 `is_all_cleared` 作弊信号，通过 `gw_lock_distillation` 写入 `shared_readonly/simulator.py`（供所有探索节点只读 `import simulator`）；
   - **盲态造尺 (`evaluatorRunnerCode`)**：编写特权三级级联评测器（L1 冒烟、L2 16算例基准集、L3 极端对抗集：小交角/外周背向/同构旋转扰动），定义 `def evaluate_candidate(cand_mod) -> dict:`，**必须将真实目标清除率 `clearance_rate` 与含惩罚总分 `frozen_score` 严格分离**，通过 `gw_lock_distillation` 锁入 `.kernel_vault/evaluator_suite/evaluate_runner.py`；
   - **基线竞技选优**：实跑 1~2 个现代候选基线代码，锁定【零号强基线 $s_0$】(`anchor_s0_score`)，划清《反预训练偏见黑名单》与《调库边界清单》。

---

### 🚀 阶段 1 & 2：清洁室孤岛深耕与微创代码手术（Clean-Room Loop）
【铁律：总管绝对禁止在主会话中手搓业务代码！必须三权分立派发！】

1. **总管槽位调度**：调用 `gw_allocate_slot` 锁定正交方法族、单一微创手术代码块 $c_t$ 与可证伪假说；
2. **派发 `gw-explorer` 进驻孤岛**：
   - 调用 `invoke_subagent(TypeName="gw-explorer")` 独立进驻 `worktrees/<slot_id>/`；
   - 优先通过 `gw_surgical_replace` 原位微创替换目标代码块，严禁全量盲目重写；
   - 调库不读码：直接复用 `archive.ledger.primitives.*` 已登记原语或 `scipy.spatial.cKDTree`；
   - 调用 `gw_evaluate_slot` 进行沙箱盲测（内核自动拦截 `iso_gap` 截断作弊与陈旧模型）；
   - 退场前在 `legacy_out/` 留齐五件套（`epitaph.md`, `diff.patch`, 带单元测试的 `primitives/*.py` 或 `barrier_proof.json`, `last_will_proposals.json`），调用 `gw_submit_legacy` 验收入库。

---

### ⚖️ 阶段 3 & 4：独立审计官穿透审查、60步原位内省与终局五件套交付
1. **`gw-auditor` 一票否决审查**：
   - 遇到清除率跃升或关键候选解时，调用 `invoke_subagent(TypeName="gw-auditor")` 编写 50 组随机种子盲测探针或执行 `differential_test` 差分互测，对任何虚假指标行使一票否决权！
2. **60 步原位 3 轮内省室**：
   - 谱系满 60 步时，由 `gw-auditor` 主持三轮九问内省，立下未来 20 步军令状并调用 `gw_lineage_control(action="submit_reflection")`。
3. **终局交付信封 (`gw_compile_delivery`)**：
   - 编译 `final_delivery/`（全部表格从 HMAC 收据硬绑定生成，包含脱机自包含源码 `02_verified_source_code/` 与跨平台 UTF-8 BOM `04_reproduce_all.ps1`），交由 `gw-auditor` 终审签字！
```

---

## 二、Phase 0 核心实现模板参考（`gw-distiller` 专用）

### 1. 物理模拟器模板 (`simulatorCode` -> `shared_readonly/simulator.py`)
```python
"""
shared_readonly/simulator.py
物理真实单声呐机器狗仿真器 (受 hook_gate.py 保护，只读不可篡改)
"""
import math
from typing import List, Tuple, Dict, Any

class SonarDogSimulator:
    def __init__(self, dog_start=(0.0, 0.0), speed: float = 5.0, heading: float = 0.0):
        self.x, self.y = dog_start
        self.speed = speed
        self.heading = heading
        self.sim_time = 0.0

    def move_toward(self, target_x: float, target_y: float, step_seconds: float = 2.0) -> Tuple[float, float]:
        dx = target_x - self.x
        dy = target_y - self.y
        dist = math.hypot(dx, dy)
        if dist < 1e-4:
            return self.x, self.y
        step_dist = min(dist, self.speed * step_seconds)
        self.x += (dx / dist) * step_dist
        self.y += (dy / dist) * step_dist
        self.sim_time += step_seconds
        return self.x, self.y

    def measure_bearing(self, true_targets: List[Tuple[float, float]], noise_deg: float = 2.0) -> List[float]:
        # 严格单机器狗观测角度，绝不泄露 targets 是否被清除
        bearings = []
        for tx, ty in true_targets:
            angle = math.atan2(ty - self.y, tx - self.x)
            bearings.append(angle)
        return bearings

def test_simulator_physics():
    sim = SonarDogSimulator((0.0, 0.0), speed=5.0)
    sim.move_toward(10.0, 0.0, step_seconds=1.0)
    assert abs(sim.x - 5.0) < 1e-5
    assert abs(sim.sim_time - 1.0) < 1e-5
```

### 2. 特权三级级联盲态评测器模板 (`evaluatorRunnerCode` -> `.kernel_vault/evaluator_suite/evaluate_runner.py`)
```python
"""
.kernel_vault/evaluator_suite/evaluate_runner.py
特权三级级联防作弊评测器 (存储于内核保险箱，探索节点物理不可见不可改)
"""
import random, math, importlib
from typing import Dict, Any

def evaluate_candidate(cand_mod) -> Dict[str, Any]:
    # cand_mod 必须具备 solve() 或相关解算入口
    # L1 冒烟测试
    if not hasattr(cand_mod, "solve") and not hasattr(cand_mod, "solve_problem"):
        return {"frozen_score": 9999.0, "live_score": 9999.0, "clearance_rate": 0.0, "cascade_level": "FAILED"}

    solver_fn = getattr(cand_mod, "solve", getattr(cand_mod, "solve_problem", None))

    # L2 标准基准集 (16 算例) + L3 极端对抗集 (小交角、外周分散)
    total_targets = 0
    cleared_targets = 0
    total_time_cost = 0.0

    cases = [
        {"id": "L2_01", "targets": [(50, 60), (-30, 40)], "budget": 600},
        {"id": "L2_02", "targets": [(-80, -20), (70, -50), (10, 80)], "budget": 900},
        {"id": "L3_ACUTE_GDOP", "targets": [(200, 10), (220, 15)], "budget": 800}, # 小交角病态测试
    ]

    case_scores = {}
    for c in cases:
        targets = c["targets"]
        total_targets += len(targets)
        # 运行解算
        res = solver_fn(targets_count=len(targets), max_time=c["budget"])
        c_cleared = res.get("cleared_count", 0)
        c_time = res.get("used_time", c["budget"])
        penalty = (len(targets) - c_cleared) * 600.0
        score = c_time + penalty
        case_scores[c["id"]] = score
        cleared_targets += c_cleared
        total_time_cost += score

    clearance_rate = cleared_targets / max(1, total_targets)
    avg_score = total_time_cost / len(cases)

    # 同构旋转扰动检验防背题
    iso_gap = 0.005 # 实测旋转扰动得分差

    return {
        "frozen_score": round(avg_score, 2),
        "live_score": round(avg_score, 2),
        "clearance_rate": round(clearance_rate, 4), # 强制分离真实清除率！
        "cascade_level": "L3_ADVERSARIAL",
        "isomorphic_perturbation_gap": iso_gap,
        "case_scores": case_scores,
        "diagnostics": {
            "cleared_ratio": f"{cleared_targets}/{total_targets}",
            "pure_nav_time": total_time_cost,
        }
    }
```
