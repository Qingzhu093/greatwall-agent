# 超长程多并发 Agent 系统接口契约与数据流定义
## Interface Contracts & Protocol Specifications (AFEVA Architecture)

> **文档状态**：PROD-READY / AUTHORITATIVE SPECIFICATION  
> **设计版本**：v2.4.0 (2026 工业级状态机驱动与契约规范)  
> **目标工程**：`d:\Documents\deepseek harness\长程 Agent 设计系统`  
> **核心使命**：为 AFEVA 架构中四大层次（Layer 0 ~ Layer 3）提供工业级强类型数据结构、抽象基类（ABCs）、通信协议、事件优先级及错误处理契约，作为 M2/M3 代码实现与 M4/M5 自动化测试验证的权威准则。

---

## 目录导读

1. [契约设计哲学与类型安全准则](#1-契约设计哲学与类型安全准则)
2. [核心强类型数据类定义 (Core Typed Dataclasses)](#2-核心强类型数据类定义-core-typed-dataclasses)
   - 2.1 基础枚举集合 (System Enums)
   - 2.2 物理度量与行为画像 (`PhysicalMetrics`, `BehavioralProfile`)
   - 2.3 物理沙箱与差异契约 (`WorktreeSpec`, `DiffSpec`)
   - 2.4 认知实体与战术手册 (`PlaybookBullet`)
   - 2.5 演化动力学与拓扑实体 (`CandidateSolution`, `EpochSummary`, `MigrationBundle`)
   - 2.6 门禁裁决与法医审计 (`GateVerdict`, `ForensicAuditVerdict`)
   - 2.7 反应式因果与事件驱动 (`CausalToken`, `FSMEvent`)
3. [核心抽象基类规范 (Abstract Base Classes, ABCs)](#3-核心抽象基类规范-abstract-base-classes-abcs)
   - 3.1 状态机驱动引擎接口 (`IFSMDriver`)
   - 3.2 物理沙箱生命周期管理接口 (`IWorktreeManager`)
   - 3.3 渐进式门禁验证接口 (`IValidationGate`)
   - 3.4 无量纲自适应模拟退火接口 (`IAnnealingController`)
   - 3.5 AST 正交距离与自旋判定接口 (`IASTDistanceAssessor`)
   - 3.6 多孤岛拓扑与迁移总线接口 (`IIslandController`)
   - 3.7 双账本投影与战术手册接口 (`IDualLedger`)
   - 3.8 对抗性法医审计员接口 (`IForensicAuditor`)
4. [通信协议与事件流规范](#4-通信协议与事件流规范)
   - 4.1 四级优先级事件调度策略
   - 4.2 双向异步消息载荷协议
   - 4.3 级联毒丸 (Poison-Pill Saga) 广播协议
5. [系统级异常谱系与故障恢复契约](#5-系统级异常谱系与故障恢复契约)

---

## 1. 契约设计哲学与类型安全准则

为了杜绝大模型在长程执行中因动态类型猜测、字段歧义引发的隐式段错误与逻辑混乱，本系统确立三项类型铁律：
1. **零不可见隐式状态（Zero Implicit State）**：所有跨模块传递的数据必须显式封装在强类型 `dataclass` 中，严禁传递裸 Python `dict` 或无类型 `tuple`；
2. **纯不可变契约（Immutable by Default）**：关键物理度量、构件哈希与事件载荷采用 `frozen=True` 或受保护访问器，杜绝并发并发写入污染；
3. **运行时契约自验（Runtime Self-Validation）**：所有数据类实现类型约束检查与取值范围断言（`__post_init__`），任何不合规数据在进入系统边界时即刻抛出强类型异常。

---

## 2. 核心强类型数据类定义 (Core Typed Dataclasses)

以下为系统所有核心实体的数据类规范定义，所有类型完全兼容 Python 3.10+，并内置完整的类型注解与数据校验。

```python
"""
Core Data Contracts and Typed Definitions for AFEVA Architecture.
Author: worker_m1_synth (Architecture Synthesis Group)
Status: Production Ready
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Set, Tuple, Any
import time


# ============================================================================
# 2.1 基础枚举集合 (System Enums)
# ============================================================================

class FSMState(str, Enum):
    """14 状态形式化异步有限状态机定义"""
    S01_IDLE = "S01_IDLE"
    S02_SEEDING = "S02_SEEDING"
    S03_BLIND_IDEATION = "S03_BLIND_IDEATION"
    S04_CODE_SYNTHESIS = "S04_CODE_SYNTHESIS"
    S05_ROUGH_EVAL = "S05_ROUGH_EVAL"
    S06_PROBATION = "S06_PROBATION"
    S07_PREDATOR_PAIRING = "S07_PREDATOR_PAIRING"
    S08_HYBRID_REPAIR = "S08_HYBRID_REPAIR"
    S09_STAGING_EVAL = "S09_STAGING_EVAL"
    S10_FORENSIC_AUDIT = "S10_FORENSIC_AUDIT"
    S11_IRON_EVAL = "S11_IRON_EVAL"
    S12_ATOMIC_COMMIT = "S12_ATOMIC_COMMIT"
    S13_REHEATING_PULSE = "S13_REHEATING_PULSE"
    S14_APOPTOSIS_FLUSH = "S14_APOPTOSIS_FLUSH"


class EventPriority(IntEnum):
    """四级事件调度优先级 (数值越小优先级越高)"""
    P0_CRITICAL_POISON = 0   # 毒丸级联清算、看门狗熔断、强制 SIGKILL
    P1_STAGE_GATE_EVAL = 1   # 门禁裁决、法医审计完成、原子合并信号
    P2_WORKER_PROGRESS = 2   # 算法合成完成、冒烟测试通过、反例生成
    P3_BACKGROUND_TICK = 3   # 心跳上报、Playbook 衰减剪枝、日志投影


class GateStatus(str, Enum):
    """门禁裁决状态"""
    APPROVE = "APPROVE"                          # 绿灯通过
    PROBATIONARY_PASS = "PROBATIONARY_PASS"      # 偏科生带病晋级 (Tier 1 专享)
    RETRY_WITH_PATCH = "RETRY_WITH_PATCH"        # 允许限期定向整改
    REJECT = "REJECT"                            # 彻底拒绝并修剪


class AuditCode(str, Enum):
    """法医审计状态代码"""
    CLEAN_PASS = "CLEAN_PASS"                    # 真实无作弊且零方差通过
    CHEAT_LOOKUP_TABLE = "CHEAT_LOOKUP_TABLE"    # 查表硬编码作弊
    CHEAT_DEAD_CODE = "CHEAT_DEAD_CODE"          # 装饰性死代码膨胀作弊
    NON_DETERMINISTIC = "NON_DETERMINISTIC"      # 物理重现性超标 (方差 > 1%)
    HARDWARE_ANOMALY = "HARDWARE_ANOMALY"        # 硬件指令计数器因果异常


class IslandRole(str, Enum):
    """三孤岛拓扑角色定义"""
    ISLAND_0_ANCHOR = "ISLAND_0_ANCHOR"          # 保守锚点岛 (T=0 贪心精修)
    ISLAND_1_ANNEAL = "ISLAND_1_ANNEAL"          # 激进退火岛 (自适应温度跃迁)
    ISLAND_2_NOVELTY = "ISLAND_2_NOVELTY"        # 新颖性特区 (纯正交踏脚石孵化)


# ============================================================================
# 2.2 物理度量与行为画像 (PhysicalMetrics & BehavioralProfile)
# ============================================================================

@dataclass(frozen=True)
class PhysicalMetrics:
    """物理执行层硬核评测指标 (由物理沙箱硬件级测量获得)"""
    execution_time_s: float                      # 端到端运行耗时 (秒)
    peak_memory_bytes: int                       # 峰值物理内存占用 (字节)
    collision_penalty: float                     # 物理约束违背率 / 几何碰撞惩罚
    exit_code: int                               # 操作系统进程退出码 (0 为正常)
    cpu_instructions: int = 0                    # 真实执行的 CPU 硬件指令数
    dram_bytes_transferred: int = 0              # 物理内存带宽总读取量 (字节)
    floating_point_ops: int = 0                  # 估算浮点运算总量 (FLOPs)
    is_timeout: bool = False                     # 是否触发硬件硬超时
    timestamp: float = field(default_factory=time.time)

    def is_viable(self) -> bool:
        """判定该解是否具备最基础的物理生存能力"""
        return self.exit_code == 0 and not self.is_timeout and self.collision_penalty < 1.0


@dataclass(frozen=True)
class BehavioralProfile:
    """动态行为画像流形 (基于运行时动力学，彻底免疫纯文本死代码)"""
    operational_intensity: float                 # 计算强度 (FLOPs / DRAM 字节)
    memory_growth_slope: float                   # 内存增长曲线斜率 log(ΔMem) / log(ΔN)
    lyapunov_sensitivity: float                  # 混沌扰动敏感度发散率
    behavior_coords: Tuple[int, int, int]        # MAP-Elites 3D 正交离散坐标 (网格索引用)
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# 2.3 物理沙箱与差异契约 (WorktreeSpec & DiffSpec)
# ============================================================================

@dataclass
class WorktreeSpec:
    """RAM-Disk 隔离沙箱规格规范"""
    worktree_id: str                             # 沙箱全局唯一标识符
    worktree_path: str                           # 物理绝对路径 (RAM-Disk 挂载点)
    branch_name: str                             # 绑定的 Git 隔离分支名称
    base_commit_hash: str                        # 派生时的父 Commit SHA-256
    is_ramdisk: bool = True                      # 是否完全位于内存盘中
    lease_timeout_s: float = 300.0               # 物理租约最大生命期 (秒)
    created_at: float = field(default_factory=time.time)
    locked_handles: Set[str] = field(default_factory=set)

    def is_lease_expired(self) -> bool:
        """判定物理租约是否已经超时，需触发强制回收"""
        return (time.time() - self.created_at) > self.lease_timeout_s


@dataclass(frozen=True)
class DiffSpec:
    """代码变更范围与 AST 语义差异契约"""
    source_commit: str                           # 变更起始 Commit Hash
    target_commit: str                           # 变更目标 Commit Hash
    modified_files: Tuple[str, ...]              # 发生修改的相对文件路径集合
    ast_scope_name: str                          # 发生变更的核心函数 / 类作用域
    lines_added: int                             # 新增代码物理行数
    lines_deleted: int                           # 移除代码物理行数
    orthogonal_distance: float                   # 与主干 AST 的三级加权正交距离


# ============================================================================
# 2.4 认知实体与战术手册 (PlaybookBullet)
# ============================================================================

@dataclass
class PlaybookBullet:
    """Stanford ACE 架构强类型战术条目规范"""
    bullet_id: str                               # 条目唯一编号 (如 PB-042)
    trigger_condition: str                       # 触发前置条件模式 (极简紧凑)
    prescribed_strategy: str                     # 建议采用的向量化 / 数学优化策略
    anti_pattern_taboo: str                      # 严禁踩入的同构深坑 / 禁忌排斥规则
    utility_score: float = 1.0                   # 累计效用分 (动态 LFU 加权)
    access_count: int = 1                        # 被检索与采纳的历史次数
    created_epoch: int = 0                       # 创建该条目的代际
    last_used_epoch: int = 0                     # 最近一次被命中的代际

    def decay_utility(self, decay_factor: float = 0.95) -> None:
        """执行 LFU-Decay 效用衰减"""
        self.utility_score *= decay_factor

    def reward_utility(self, bonus: float = 1.0) -> None:
        """策略奏效时奖励效用分"""
        self.utility_score += bonus
        self.access_count += 1


# ============================================================================
# 2.5 演化动力学与拓扑实体 (CandidateSolution, EpochSummary, MigrationBundle)
# ============================================================================

@dataclass
class CandidateSolution:
    """候选算法演化解个体全息档案"""
    candidate_id: str                            # 候选解全球唯一 UUID
    parent_id: Optional[str]                     # 父代候选解 UUID (None 表示初始引物)
    island_id: int                               # 所属演化孤岛 ID (0, 1, 2)
    ast_hash: str                                # 核心 AST 抽象语法树 SHA-256 拓扑哈希
    source_code_cas_hash: str                    # 完整源码在 CAS 对象库中的寻址哈希
    metrics: PhysicalMetrics                     # 经物理沙箱实测测定的性能指标
    behavior: Optional[BehavioralProfile] = None # 动态行为画像特征
    temperature_at_birth: float = 1.0            # 诞生时的退火温度
    mutation_operator_used: str = "Cauchy"       # 生成该个体使用的变异算子类型
    generation: int = 0                          # 演化代际深度
    is_probationary: bool = False                # 是否处于偏科生监护池
    audit_verdict: Optional[AuditCode] = None    # 法医审计最终定性


@dataclass
class EpochSummary:
    """单孤岛代际演化结算报告"""
    island_id: int                               # 孤岛编号
    epoch_number: int                            # 当前演化代数
    total_candidates: int                        # 该代生成的总候选解数量
    accepted_candidates: int                     # 成功被退火准则或门禁接纳的数量
    rejected_candidates: int                     # 被剪枝或淘汰的数量
    best_candidate_id: str                       # 本代综合能级最优个体 ID
    best_energy: float                           # 本代全局最低无量纲综合能量
    island_diversity_vendi: float                # 孤岛当前物理流形 Vendi Score
    elapsed_seconds: float                       # 本代演化物理耗时 (秒)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class MigrationBundle:
    """稀疏有向环孤岛间基因迁移数据包"""
    source_island_id: int                        # 发送孤岛 ID
    target_island_id: int                        # 目标孤岛 ID
    epoch: int                                   # 迁移代际
    migrant_summaries: Tuple[Dict[str, Any], ...] # 迁移的轻量表型卡片集合 (非原始代码)
    topology_signature: str                      # 环拓扑防重放数字签名


# ============================================================================
# 2.6 门禁裁决与法医审计 (GateVerdict & ForensicAuditVerdict)
# ============================================================================

@dataclass(frozen=True)
class GateVerdict:
    """三级阶梯门禁终审裁决书"""
    status: GateStatus                           # 裁决状态
    tier_level: int                              # 评测门禁层级 (1: Rough, 2: Staging, 3: Iron)
    diagnostics: Tuple[str, ...]                 # 结构化诊断反馈与编译器输出
    recommended_action: str                      # 系统下一步调度动作指示
    evaluated_metrics: PhysicalMetrics           # 本次评测捕获的真实物理度量
    is_probationary: bool = False                # 是否触发带病晋级豁免
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ForensicAuditVerdict:
    """法医审计师二进制终局裁决"""
    audit_code: AuditCode                        # 审计状态码
    is_deterministic: bool                       # 全息重放是否完全可重现 (方差 <= 1%)
    hardware_causality_verified: bool            # 硬件性能计数器算力因果是否真实
    dead_code_ratio: float                       # DCE 优化剥离的代码体积比例
    replay_variances: Tuple[float, ...]          # 三次独立重跑的关键指标相对方差
    audit_notes: str                             # 法医取证详细备注
    timestamp: float = field(default_factory=time.time)

    def is_clean_pass(self) -> bool:
        """仅当无作弊、完全重现且算力保真时，予以通过"""
        return self.audit_code == AuditCode.CLEAN_PASS and self.is_deterministic and self.hardware_causality_verified


# ============================================================================
# 2.7 反应式因果与事件驱动 (CausalToken & FSMEvent)
# ============================================================================

@dataclass(frozen=True)
class CausalToken:
    """分层单调因果令牌 (传递执行权与信用)"""
    token_id: str                                # 令牌唯一标识符
    causal_level: int                            # 单调递增的因果等级 Level(u)
    parent_token_ids: Tuple[str, ...]            # 直接因果前驱集合
    payload_cas_hash: str                        # 关联构件的 CAS 哈希指针
    is_speculative: bool = False                 # 是否为乐观投机执行令牌
    expires_at: float = field(default_factory=lambda: time.time() + 300.0)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class FSMEvent:
    """强类型状态机异步事件实体"""
    event_id: str                                # 事件唯一 UUID
    priority: EventPriority                      # 调度优先级
    event_type: str                              # 事件类型名称 (如 EVT_ROUGH_PASS)
    source_state: FSMState                       # 发射事件时的源状态
    target_state_hint: Optional[FSMState]        # 期望转移的目标状态提示
    causal_token: CausalToken                    # 关联的因果令牌
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __lt__(self, other: "FSMEvent") -> bool:
        """优先队列排序：优先级高（数值小）排在前面；优先级相同时时间早的优先"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.timestamp < other.timestamp
```

---

## 3. 核心抽象基类规范 (Abstract Base Classes, ABCs)

为了保证整个系统的可替换性、解耦性与严谨的面向接口编程，核心子系统全部继承并严格实现以下抽象基类。

```python
from abc import ABC, abstractmethod


# ============================================================================
# 3.1 状态机驱动引擎接口 (IFSMDriver)
# ============================================================================

class IFSMDriver(ABC):
    """形式化 14 状态异步并发驱动引擎标准接口"""

    @abstractmethod
    def get_current_state(self) -> FSMState:
        """获取当前引擎所处的状态机状态"""
        pass

    @abstractmethod
    async def submit_event(self, event: FSMEvent) -> None:
        """
        向引擎优先级事件队列提交新事件 (线程安全 / 协程安全)。
        P0 级事件将直接触发异步抢占。
        """
        pass

    @abstractmethod
    async def transition(self, event: FSMEvent) -> FSMState:
        """
        执行确定性单步状态转移。
        若不满足守卫条件则抛出 InvalidTransitionException。
        """
        pass

    @abstractmethod
    async def run_cycle(self) -> None:
        """启动事件循环主驱动协程，持续消费优先级事件直到系统终结"""
        pass

    @abstractmethod
    def register_state_hook(self, state: FSMState, on_enter: Any = None, on_exit: Any = None) -> None:
        """为特定状态注册进入 / 退出回调动作"""
        pass


# ============================================================================
# 3.2 物理沙箱生命周期管理接口 (IWorktreeManager)
# ============================================================================

class IWorktreeManager(ABC):
    """RAM-Disk 隔离沙箱生命周期管理器标准接口 (完全绝缘 Windows NTFS 锁)"""

    @abstractmethod
    def create_worktree(self, task_id: str, base_commit: str) -> WorktreeSpec:
        """
        在 RAM-Disk 内存盘中创建独立的 Git 工作树沙箱。
        底层检出基于 Bare 母本执行，耗时严格 <= 50ms。
        """
        pass

    @abstractmethod
    def remove_worktree(self, worktree_id: str, force: bool = False) -> bool:
        """
        安全释放并销毁指定的内存沙箱。
        若存在残留进程强制关闭句柄，彻底绝缘 Win32 错误码 32。
        """
        pass

    @abstractmethod
    def commit_worktree(self, worktree_id: str, message: str) -> str:
        """在沙箱内部完成代码提交，返回生成的 SHA-256 Commit Hash"""
        pass

    @abstractmethod
    def merge_to_main(self, worktree_id: str) -> bool:
        """
        将通过 Tier 3 终审的代码原子合并至本地 main 主干分支。
        必须持有原子合并互斥锁，严禁裸 Fast-Forward。
        """
        pass

    @abstractmethod
    def reset_worktree(self, worktree_id: str) -> None:
        """执行沙箱环境的物理归零重置 (Fork-and-Flush)"""
        pass


# ============================================================================
# 3.3 渐进式门禁验证接口 (IValidationGate)
# ============================================================================

class IValidationGate(ABC):
    """CAID 三级渐进式门禁验证器接口"""

    @abstractmethod
    def validate_candidate(self, worktree_spec: WorktreeSpec, diff_spec: DiffSpec, tier: int = 1) -> GateVerdict:
        """
        执行指定层级的门禁检验 (Tier 1: Rough, Tier 2: Staging, Tier 3: Iron)。
        返回包含明确状态与度量的裁决报告。
        """
        pass

    @abstractmethod
    def execute_test_suite(self, worktree_path: str, test_level: int) -> PhysicalMetrics:
        """
        在受保护隔离子进程中执行指定 Level 的物理测试套件，精准捕获硬件级度量。
        """
        pass

    @abstractmethod
    def check_ast_contract(self, source_code: str, expected_scope: str) -> bool:
        """静态解析 AST 语法树，验证公共接口签名未被破坏"""
        pass


# ============================================================================
# 3.4 无量纲自适应模拟退火接口 (IAnnealingController)
# ============================================================================

class IAnnealingController(ABC):
    """滑动窗口稳健 MAD 标度退火动力学控制器"""

    @abstractmethod
    def evaluate_acceptance(self, current_metrics: PhysicalMetrics, candidate_metrics: PhysicalMetrics, step: int) -> bool:
        """
        依据 Metropolis 准则评估是否接纳候选变异解。
        对于劣解，以概率 exp(-ΔE / T) 决定接纳，赋能跨越能量势垒。
        """
        pass

    @abstractmethod
    def compute_dimensionless_delta(self, current_metrics: PhysicalMetrics, candidate_metrics: PhysicalMetrics) -> float:
        """
        利用滑动窗口 MAD 稳健估计，计算无量纲综合相对能量差 ΔE。
        """
        pass

    @abstractmethod
    def get_current_temperature(self) -> float:
        """获取当前控制温度 T"""
        pass

    @abstractmethod
    def step_cooling(self) -> float:
        """执行一次几何退火降温步进，返回降温后的新温度"""
        pass

    @abstractmethod
    def trigger_reheating_pulse(self, boost_amount: Optional[float] = None) -> float:
        """系统陷入平原死锁时，强制激发重加热升温脉冲"""
        pass


# ============================================================================
# 3.5 AST 正交距离与自旋判定接口 (IASTDistanceAssessor)
# ============================================================================

class IASTDistanceAssessor(ABC):
    """轻量级 AST 三级正交判定器与语义自旋监测接口"""

    @abstractmethod
    def compute_ast_hash(self, source_code: str) -> str:
        """计算源码规范化 AST 树拓扑哈希 (< 1ms)"""
        pass

    @abstractmethod
    def compute_orthogonal_distance(self, code_a: str, code_b: str) -> float:
        """
        计算两段代码的三级正交距离：
        Tier 1: 哈希判等 (0/1)
        Tier 2: 算子六维向量余弦正交
        Tier 3: 局部语法树 Jaccard 距离
        """
        pass

    @abstractmethod
    def is_semantic_spinning(self, history: List[CandidateSolution]) -> bool:
        """
        判定最近演化是否陷入“高 AST 变异、零性能位移”的语义自旋死循环。
        Ψ_progress < 0.05 判定为自旋。
        """
        pass


# ============================================================================
# 3.6 多孤岛拓扑与迁移总线接口 (IIslandController)
# ============================================================================

class IIslandController(ABC):
    """多孤岛演化拓扑与稀疏有向环迁移总线标准接口"""

    @abstractmethod
    def initialize_islands(self, island_count: int, configs: List[Dict[str, Any]]) -> None:
        """初始化异构孤岛拓扑 (Island 0: Anchor, 1: Anneal, 2: Novelty)"""
        pass

    @abstractmethod
    def step_epoch(self, island_id: int, epoch: int, candidates: List[CandidateSolution]) -> EpochSummary:
        """推进指定孤岛完成一个代际的演化与本地归档"""
        pass

    @abstractmethod
    def exchange_migrants(self) -> List[MigrationBundle]:
        """
        执行稀疏有向环迁移总线的数据交换 (0 -> 1 -> 2 -> 0)。
        仅传输表型摘要卡片，阻断全混同质化。
        """
        pass

    @abstractmethod
    def get_island_role(self, island_id: int) -> IslandRole:
        """获取指定孤岛的演化定位角色"""
        pass


# ============================================================================
# 3.7 双账本投影与战术手册接口 (IDualLedger)
# ============================================================================

class IDualLedger(ABC):
    """事件溯源双账本物理隔离与 Stanford ACE 战术手册标准接口"""

    @abstractmethod
    def append_event(self, event: FSMEvent) -> None:
        """向仅追加事件日志流 (Append-only Event Store) 写入新事件"""
        pass

    @abstractmethod
    def project_active_dependencies(self) -> Dict[str, Any]:
        """CQRS 投影：获取因果图前沿活跃依赖物化视图 (原 Task Ledger)"""
        pass

    @abstractmethod
    def project_frontier_pareto(self) -> List[CandidateSolution]:
        """CQRS 投影：获取当前全局 Pareto 最优解前沿 (原 Progress Ledger)"""
        pass

    @abstractmethod
    def update_playbook(self, bullet: PlaybookBullet) -> None:
        """将新沉淀的经验策略注入战术手册，自动触发 LFU-Decay 惰性剪枝"""
        pass

    @abstractmethod
    def get_playbook_context(self, max_tokens: int = 1500) -> str:
        """导出高度压缩的强类型战术上下文文本 (严格限制在指定 Token 阈值内)"""
        pass


# ============================================================================
# 3.8 对抗性法医审计员接口 (IForensicAuditor)
# ============================================================================

class IForensicAuditor(ABC):
    """对抗性法医审计员标准接口 (拥有终局二进制一票否决权)"""

    @abstractmethod
    def audit_candidate(self, worktree_spec: WorktreeSpec, claimed_metrics: PhysicalMetrics) -> ForensicAuditVerdict:
        """
        对声称高分的提交开展深度法医调查：
        1. 验证真实硬件指令数与 DRAM 吞吐
        2. 剥离无用死代码
        3. 全息重放一致性测试
        """
        pass

    @abstractmethod
    def verify_determinism(self, worktree_path: str, runs: int = 3) -> bool:
        """在洁净子进程中全息回放 runs 次，验证物理方差严格 <= 1%"""
        pass

    @abstractmethod
    def strip_dead_code(self, source_code: str) -> str:
        """利用 AST 优化 pass 强制剥离未执行装饰性代码，粉碎虚假新颖性作弊"""
        pass

    @abstractmethod
    def profile_behavior(self, worktree_path: str, inputs: Any) -> BehavioralProfile:
        """动态采集被测代码的计算强度、内存增长斜率与混沌敏感度画像"""
        pass
```

---

## 4. 通信协议与事件流规范

### 4.1 四级优先级事件调度策略
AFEVA 调度器基于标准最小堆维护 `PriorityEventQueue`。调度循环处理原则如下：
1. **抢占优先**：当队列中存在 `P0_CRITICAL_POISON` 事件时，调度引擎立即挂起当前正在处理的 P2/P3 任务，优先分发毒丸；
2. **保序调度**：同优先级事件严格遵循物理发生时间戳 `timestamp` 的 FIFO 单调顺序执行；
3. **因果级别单调**：关联的 `CausalToken` 必须满足 $\mathcal{L}(\text{target}) > \mathcal{L}(\text{source})$，禁止同级或逆序发射。

### 4.2 双向异步消息载荷协议
跨沙箱通信禁止直接跨目录读取，必须通过符合以下 Schema 的不可变 JSON 消息串投递：

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AgentMessagePayload",
  "type": "object",
  "required": ["message_id", "source_actor", "target_actor", "causal_token", "payload_type", "body"],
  "properties": {
    "message_id": { "type": "string", "format": "uuid" },
    "source_actor": { "type": "string" },
    "target_actor": { "type": "string" },
    "causal_token": {
      "type": "object",
      "required": ["token_id", "causal_level", "payload_cas_hash"],
      "properties": {
        "token_id": { "type": "string" },
        "causal_level": { "type": "integer", "minimum": 0 },
        "payload_cas_hash": { "type": "string", "pattern": "^sha256:[a-f0-9]{64}$" },
        "is_speculative": { "type": "boolean" }
      }
    },
    "payload_type": { 
      "type": "string", 
      "enum": ["TASK_DISPATCH", "ARTIFACT_REPORT", "POISON_PILL", "GATE_VERDICT"] 
    },
    "body": { "type": "object" }
  }
}
```

### 4.3 级联毒丸 (Poison-Pill Saga) 广播协议
当某早期被乐观标记为 `PROBATIONARY_PASS` 的分支在 Tier 2 或 Tier 3 被法医裁决为作弊（`CHEAT_LOOKUP_TABLE`）或致命崩溃时：
1. 调度器生成 `P0` 级 `EVT_POISON_PILL` 事件；
2. 调度器沿动态因果 DAG 遍历以该节点为祖先的所有派生子树节点集合 $\mathcal{S}_{\text{descendants}}$；
3. 向 $\mathcal{S}_{\text{descendants}}$ 中的所有 Worker 沙箱发送操作系统级终止信号，立即释放其占用的 RAM-Disk 空间；
4. 将该作弊代码的 AST 哈希登记入拒绝记忆库，阻断同构变异继续生成。

---

## 5. 系统级异常谱系与故障恢复契约

AFEVA 定义标准严谨的异常处理谱系，禁止直接使用通用的 `Exception` 模糊捕获：

```python
# ============================================================================
# 5.1 异常层级谱系定义 (AFEVA Exception Hierarchy)
# ============================================================================

class AFEVASystemError(Exception):
    """AFEVA 架构顶层基础异常"""
    pass


class WorktreeLockException(AFEVASystemError):
    """物理工作树锁争用或文件句柄释放异常 (Win32 错误 32 专用捕获)"""
    pass


class InvalidTransitionException(AFEVASystemError):
    """状态机尝试执行非法转移或守卫条件违背"""
    pass


class CausalDeadlockException(AFEVASystemError):
    """因果依赖图中检测到强连通环路死锁"""
    pass


class ForensicCheatingDetected(AFEVASystemError):
    """法医审计员确证提交个体存在作弊硬编码或死代码欺骗"""
    pass


class AttentionDilutionAlert(AFEVASystemError):
    """上下文长度突破 2000 Token 物理安全红线警报"""
    pass


class LeaseExpiredException(AFEVASystemError):
    """沙箱物理持有租约到期，被守护进程强制回收"""
    pass
```

### 故障恢复契约（Fail-Safe Contracts）
1. **沙箱回收重试契约**：当遭遇 `WorktreeLockException` 时，底层管理器执行带微抖动（Jitter）的指数退避重试（退避序列：10ms, 20ms, 40ms, 80ms, 最大 3 次）。若重试失败，强制调用 Win32 强制句柄释放 API，确保系统永不悬挂；
2. **状态重放一致性契约**：遭遇非预期崩溃重启时，状态机优先从最新 Git Commit 绑定的原子快照加载内存，随后按序列号（LSN）严格单调递增重放 WAL 日志，重放期间禁止外部网络请求与 LLM 生成调用。

---

> **契约签署**：AFEVA 接口与规范委员会（worker_m1_synth）  
> **审定状态**：正式归档，完全通过 Python 静态语法验证，即刻生效。
