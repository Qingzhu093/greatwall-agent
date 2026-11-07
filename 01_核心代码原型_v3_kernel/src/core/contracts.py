"""
Core Data Contracts, System Enums, Exceptions, and Abstract Base Classes for AFEVA Architecture.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# 1. 系统枚举集合 (System Enums)
# ============================================================================

class FSMState(str, Enum):
    """14 状态形式化异步有限状态机定义 (含终端故障兼容态)"""
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
    S14_FAILED = "S14_FAILED"

    @property
    def category(self) -> StateCategory:
        """获取当前状态的宏观分类"""
        return STATE_TO_CATEGORY.get(self, StateCategory.TERMINAL)


class StateCategory(str, Enum):
    """状态宏观分类六大域"""
    EXPLORATION = "EXPLORATION"      # 假说推演与引物播种 (S02, S03)
    EXECUTION = "EXECUTION"          # 代码沙箱合成 (S04)
    EVOLUTION = "EVOLUTION"          # 偏科监护、捕食对抗与杂交脉冲 (S06, S07, S08, S13)
    VERIFICATION = "VERIFICATION"    # CAID 阶梯门禁与法医审计 (S05, S09, S10, S11)
    PERSISTENCE = "PERSISTENCE"      # 主干原子提交与快照 (S12)
    TERMINAL = "TERMINAL"            # 空闲初始与凋亡清栈/故障态 (S01, S14)


STATE_TO_CATEGORY: Dict[FSMState, StateCategory] = {
    FSMState.S01_IDLE: StateCategory.TERMINAL,
    FSMState.S02_SEEDING: StateCategory.EXPLORATION,
    FSMState.S03_BLIND_IDEATION: StateCategory.EXPLORATION,
    FSMState.S04_CODE_SYNTHESIS: StateCategory.EXECUTION,
    FSMState.S05_ROUGH_EVAL: StateCategory.VERIFICATION,
    FSMState.S06_PROBATION: StateCategory.EVOLUTION,
    FSMState.S07_PREDATOR_PAIRING: StateCategory.EVOLUTION,
    FSMState.S08_HYBRID_REPAIR: StateCategory.EVOLUTION,
    FSMState.S09_STAGING_EVAL: StateCategory.VERIFICATION,
    FSMState.S10_FORENSIC_AUDIT: StateCategory.VERIFICATION,
    FSMState.S11_IRON_EVAL: StateCategory.VERIFICATION,
    FSMState.S12_ATOMIC_COMMIT: StateCategory.PERSISTENCE,
    FSMState.S13_REHEATING_PULSE: StateCategory.EVOLUTION,
    FSMState.S14_APOPTOSIS_FLUSH: StateCategory.TERMINAL,
    FSMState.S14_FAILED: StateCategory.TERMINAL,
}


class EventPriority(IntEnum):
    """四级事件调度优先级 (数值越小优先级越高，支持标准规范别名)"""
    P0_CRITICAL_POISON = 0     # 毒丸级联清算、看门狗熔断、SIGKILL
    P1_STAGE_GATE_EVAL = 1     # 门禁裁决、法医审计完成、原子合并信号
    P1_WATCHDOG_HEARTBEAT = 1  # 看门狗心跳超时报警
    P2_WORKER_PROGRESS = 2     # 算法合成完成、冒烟测试通过、反例生成
    P2_CAUSAL_DATAFLOW = 2     # 因果数据流就绪令牌
    P3_BACKGROUND_TICK = 3     # 周期心跳、Playbook 衰减剪枝、日志物化


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
# 2. 强类型核心数据契约 (Core Typed Dataclasses)
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
        """判定令牌物理生命期是否已耗尽"""
        return time.time() > self.expires_at


# ============================================================================
# 3. 系统级异常谱系 (AFEVA Exception Hierarchy)
# ============================================================================

class AFEVASystemError(Exception):
    """AFEVA 架构顶层基础异常"""
    pass


class WorktreeLockException(AFEVASystemError):
    """物理工作树锁争用或文件句柄释放异常 (Win32 错误 32 专用捕获)"""
    pass


class MergeConflictException(AFEVASystemError):
    """主干合并检测到并发分支同文件冲突 (Blind Overwrite 拦截)"""
    def __init__(self, message: str, conflict_files: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.conflict_files = conflict_files or []


class InvalidTransitionException(AFEVASystemError):
    """状态机尝试执行非法转移或守卫条件违背"""
    pass


class CausalDeadlockException(AFEVASystemError):
    """因果依赖图中检测到强连通环路或非单调因果违规"""
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


class WALCorruptionError(AFEVASystemError):
    """预写日志校验和不匹配或格式损坏异常"""
    pass


class SnapshotError(AFEVASystemError):
    """快照原子序列化或恢复过程异常"""
    pass


# ============================================================================
# 4. 核心抽象基类规范 (Abstract Base Classes, ABCs)
# ============================================================================

class IFSMDriver(ABC):
    """形式化 14 状态异步并发驱动引擎标准接口"""

    @abstractmethod
    def get_current_state(self) -> FSMState:
        """获取当前引擎所处的状态机状态"""
        pass

    @abstractmethod
    async def submit_event(self, event: Any) -> None:
        """
        向引擎优先级事件队列提交新事件 (线程安全 / 协程安全)。
        P0 级事件将直接触发异步抢占。
        """
        pass

    @abstractmethod
    async def transition(self, event: Any) -> FSMState:
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


class IWorktreeManager(ABC):
    """RAM-Disk 隔离沙箱生命周期管理器标准接口 (完全绝缘 Windows NTFS 锁)"""

    @abstractmethod
    def create_worktree(self, task_id: str, base_commit: str) -> WorktreeSpec:
        """在 RAM-Disk 内存盘中创建独立的 Git 工作树沙箱"""
        pass

    @abstractmethod
    def remove_worktree(self, worktree_id: str, force: bool = False) -> bool:
        """安全释放并销毁指定的内存沙箱"""
        pass

    @abstractmethod
    def commit_worktree(self, worktree_id: str, message: str) -> str:
        """在沙箱内部完成代码提交，返回生成的 SHA-256 Commit Hash"""
        pass

    @abstractmethod
    def merge_to_main(self, worktree_id: str) -> bool:
        """将通过 Tier 3 终审的代码原子合并至本地 main 主干分支"""
        pass

    @abstractmethod
    def reset_worktree(self, worktree_id: str) -> None:
        """执行沙箱环境的物理归零重置 (Fork-and-Flush)"""
        pass


class IValidationGate(ABC):
    """CAID 三级渐进式门禁验证器接口"""

    @abstractmethod
    def validate_candidate(self, worktree_spec: WorktreeSpec, diff_spec: DiffSpec, tier: int = 1) -> GateVerdict:
        """执行指定层级的门禁检验 (Tier 1: Rough, Tier 2: Staging, Tier 3: Iron)"""
        pass

    @abstractmethod
    def execute_test_suite(self, worktree_path: str, test_level: int) -> PhysicalMetrics:
        """在受保护隔离子进程中执行指定 Level 的物理测试套件"""
        pass

    @abstractmethod
    def check_ast_contract(self, source_code: str, expected_scope: str) -> bool:
        """静态解析 AST 语法树，验证公共接口签名未被破坏"""
        pass


class IAnnealingController(ABC):
    """滑动窗口稳健 MAD 标度退火动力学控制器"""

    @abstractmethod
    def evaluate_acceptance(self, current_metrics: PhysicalMetrics, candidate_metrics: PhysicalMetrics, step: int) -> bool:
        """依据 Metropolis 准则评估是否接纳候选变异解"""
        pass

    @abstractmethod
    def compute_dimensionless_delta(self, current_metrics: PhysicalMetrics, candidate_metrics: PhysicalMetrics) -> float:
        """利用滑动窗口 MAD 稳健估计，计算无量纲综合相对能量差 ΔE"""
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


class IASTDistanceAssessor(ABC):
    """轻量级 AST 三级正交判定器与语义自旋监测接口"""

    @abstractmethod
    def compute_ast_hash(self, source_code: str) -> str:
        """计算源码规范化 AST 树拓扑哈希 (< 1ms)"""
        pass

    @abstractmethod
    def compute_orthogonal_distance(self, code_a: str, code_b: str) -> float:
        """计算两段代码的三级正交距离"""
        pass

    @abstractmethod
    def is_semantic_spinning(self, history: List[CandidateSolution]) -> bool:
        """判定最近演化是否陷入“高 AST 变异、零性能位移”的语义自旋死循环"""
        pass


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
        """执行稀疏有向环迁移总线的数据交换 (0 -> 1 -> 2 -> 0)"""
        pass

    @abstractmethod
    def get_island_role(self, island_id: int) -> IslandRole:
        """获取指定孤岛的演化定位角色"""
        pass


class IDualLedger(ABC):
    """事件溯源双账本物理隔离与 Stanford ACE 战术手册标准接口"""

    @abstractmethod
    def append_event(self, event: Any) -> None:
        """向仅追加事件日志流写入新事件"""
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


class IForensicAuditor(ABC):
    """对抗性法医审计员标准接口 (拥有终局二进制一票否决权)"""

    @abstractmethod
    def audit_candidate(self, worktree_spec: WorktreeSpec, claimed_metrics: PhysicalMetrics) -> ForensicAuditVerdict:
        """对声称高分的提交开展深度法医调查"""
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
