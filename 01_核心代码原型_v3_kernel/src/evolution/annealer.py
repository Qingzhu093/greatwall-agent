"""
Dimensionless Adaptive Simulated Annealing Controller for AFEVA Architecture.
Implements Robust MAD Metric Scaling, Analytical Initial Temperature Inversion,
Metropolis-Hastings Probability Criterion, Multiple Cooling Schedules, and Re-heating Pulses.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import math
import random
import statistics
from collections import deque
from typing import Dict, List, Optional, Tuple, Any

from src.core.contracts import (
    IAnnealingController,
    PhysicalMetrics,
)


class AnnealingController(IAnnealingController):
    """
    滑动窗口稳健 MAD (Median Absolute Deviation) 动态无量纲退火控制器。
    消除耗时 (s)、内存 (Bytes)、碰撞惩罚等量纲悬殊导致的梯度淹没。
    """

    def __init__(
        self,
        initial_temperature: Optional[float] = None,
        cooling_schedule: str = "exponential",
        cooling_rate: float = 0.88,
        linear_delta: float = 0.05,
        min_temperature: float = 1e-5,
        window_size: int = 20,
        delta_e_tol: float = 0.8,
        p0_nominal: float = 0.45,
        weights: Optional[Tuple[float, float, float]] = None,
        prior_scales: Optional[Tuple[float, float, float]] = None,
    ) -> None:
        """
        初始化退火控制器。
        
        Args:
            initial_temperature: 初始温度 T0；若为 None 则通过解析公式反解
            cooling_schedule: 冷却曲线类型 ('exponential', 'linear', 'logarithmic')
            cooling_rate: 指数降温衰减因子 gamma (默认 0.88)
            linear_delta: 线性降温步长 (默认 0.05)
            min_temperature: 允许的最低底限温度
            window_size: 滑动历史窗口大小 (默认 20)
            delta_e_tol: 标称相对劣变容忍度 (默认 0.8)
            p0_nominal: 标称劣变下的期望接收概率 (默认 0.45)
            weights: (时间, 内存, 碰撞率) 加权系数，默认 (0.6, 0.2, 0.2)
            prior_scales: 先验物理尺度标尺 (时间s, 内存Bytes, 碰撞惩罚)，默认 (1.0, 10_000_000, 0.1)
        """
        self.delta_e_tol = delta_e_tol
        self.p0_nominal = max(1e-4, min(0.99, p0_nominal))

        # 解析反解初始温度: T0 = -ΔE_tol / ln(P0)
        calculated_t0 = -self.delta_e_tol / math.log(self.p0_nominal)
        self.initial_temperature = initial_temperature if initial_temperature is not None else calculated_t0
        self.current_temperature = self.initial_temperature

        self.cooling_schedule = cooling_schedule.lower()
        self.cooling_rate = cooling_rate
        self.linear_delta = linear_delta
        self.min_temperature = min_temperature
        self.window_size = window_size

        self.weights = weights or (0.6, 0.2, 0.2)
        self.prior_scales = prior_scales or (1.0, 10_000_000.0, 0.1)

        # 维护滑动窗口历史
        self._history_time: deque[float] = deque(maxlen=window_size)
        self._history_mem: deque[float] = deque(maxlen=window_size)
        self._history_collision: deque[float] = deque(maxlen=window_size)

        # 跟踪代际最优能量用于重加热检测
        self._recent_best_energies: deque[float] = deque(maxlen=5)
        self.step_count: int = 0

    def get_current_temperature(self) -> float:
        """获取当前控制温度 T"""
        return self.current_temperature

    def update_history(self, metrics: PhysicalMetrics) -> None:
        """记录新的物理实测指标进入滑动窗口"""
        if metrics.is_viable():
            self._history_time.append(metrics.execution_time_s)
            self._history_mem.append(float(metrics.peak_memory_bytes))
            self._history_collision.append(metrics.collision_penalty)

    def _compute_mad_scale(self, history: deque[float], prior_scale: float) -> float:
        """
        计算单维度的非参数稳健 MAD 标度：
        Med = median(x_i), MAD = median(|x_i - Med|)
        当窗口样本 < 3 或 MAD 退化为 0 时，平滑切换至先验标尺。
        """
        if len(history) < 3:
            return prior_scale

        med = statistics.median(history)
        deviations = [abs(x - med) for x in history]
        mad = statistics.median(deviations)

        if mad < 1e-4:
            return prior_scale

        # 1.4826 为正态分布下的标准差一致性校正系数
        return 1.4826 * mad

    def compute_dimensionless_energy(self, metrics: PhysicalMetrics) -> float:
        """
        利用当前稳健标度计算个体的综合无量纲标量能量 E。
        能量越低代表综合性能越优秀。
        """
        scale_time = self._compute_mad_scale(self._history_time, self.prior_scales[0])
        scale_mem = self._compute_mad_scale(self._history_mem, self.prior_scales[1])
        scale_col = self._compute_mad_scale(self._history_collision, self.prior_scales[2])

        norm_time = metrics.execution_time_s / max(1e-6, scale_time)
        norm_mem = float(metrics.peak_memory_bytes) / max(1.0, scale_mem)
        norm_col = metrics.collision_penalty / max(1e-4, scale_col)

        w_t, w_m, w_c = self.weights
        energy = (w_t * norm_time) + (w_m * norm_mem) + (w_c * norm_col)

        # 超时或崩溃惩罚项
        if metrics.exit_code != 0:
            energy += 100.0
        if metrics.is_timeout:
            energy += 50.0

        return energy

    def compute_dimensionless_delta(self, current_metrics: PhysicalMetrics, candidate_metrics: PhysicalMetrics) -> float:
        """
        计算候选解相较于当前解的相对无量纲能量差 ΔE = E_cand - E_curr。
        ΔE <= 0 说明候选解更优，ΔE > 0 说明候选解变劣。
        """
        # 先将指标暂存入滑动窗口以保证动态标定实时性
        self.update_history(current_metrics)
        self.update_history(candidate_metrics)

        e_curr = self.compute_dimensionless_energy(current_metrics)
        e_cand = self.compute_dimensionless_energy(candidate_metrics)
        return e_cand - e_curr

    def evaluate_acceptance(
        self,
        current_metrics: PhysicalMetrics,
        candidate_metrics: PhysicalMetrics,
        step: int
    ) -> bool:
        """
        依据 Metropolis-Hastings 概率准则评估是否接纳候选变异解。
        若 ΔE <= 0：100% 接纳。
        若 ΔE > 0：按概率 P = exp(-ΔE / T) 接纳。
        """
        self.step_count = step
        delta_e = self.compute_dimensionless_delta(current_metrics, candidate_metrics)

        # 变优解无条件接纳
        if delta_e <= 0.0:
            return True

        # 绝对零度贪心模式
        if self.current_temperature <= self.min_temperature:
            return False

        # 计算 Metropolis 接收概率
        # 防止 exp 溢出
        scaled_delta = delta_e / self.current_temperature
        if scaled_delta > 50.0:
            prob = 0.0
        else:
            prob = math.exp(-scaled_delta)

        return random.random() < prob

    def evaluate_with_stepping_stone_protection(
        self,
        current_metrics: PhysicalMetrics,
        candidate_metrics: PhysicalMetrics,
        step: int,
        is_novel_stepping_stone: bool = False
    ) -> Tuple[bool, bool]:
        """
        带踏脚石制度化保护的评估接口。
        
        Returns:
            (is_accepted, is_sheltered_as_stepping_stone)
        """
        accepted = self.evaluate_acceptance(current_metrics, candidate_metrics, step)
        sheltered = False

        if not accepted and is_novel_stepping_stone:
            # 踏脚石虽在测试上落后，但填补空白行为网格，赋予特别庇护
            sheltered = True

        return (accepted or sheltered), sheltered

    def step_cooling(self) -> float:
        """
        执行一次退火降温步进，更新并返回降温后的新温度。
        支持三种标准调度模式。
        """
        if self.cooling_schedule == "exponential":
            self.current_temperature = max(
                self.min_temperature,
                self.current_temperature * self.cooling_rate
            )
        elif self.cooling_schedule == "linear":
            self.current_temperature = max(
                self.min_temperature,
                self.current_temperature - self.linear_delta
            )
        elif self.cooling_schedule == "logarithmic":
            k = max(1, self.step_count + 1)
            self.current_temperature = max(
                self.min_temperature,
                self.initial_temperature / math.log(1.0 + k)
            )
        else:
            # 默认指数
            self.current_temperature = max(
                self.min_temperature,
                self.current_temperature * self.cooling_rate
            )

        return self.current_temperature

    def trigger_reheating_pulse(self, boost_amount: Optional[float] = None) -> float:
        """
        系统陷入平原死锁或多样性枯竭时，强制激发重加热升温脉冲。
        默认恢复 0.5 * T0 温度。
        """
        boost = boost_amount if boost_amount is not None else (0.5 * self.initial_temperature)
        self.current_temperature += boost
        return self.current_temperature

    def record_epoch_best(self, best_energy: float) -> bool:
        """
        记录每代最优能量；若连续 3 代能量方差小于 1e-5，判定陷入鞍点并自动重加热。
        
        Returns:
            bool: 是否触发了重加热脉冲
        """
        self._recent_best_energies.append(best_energy)
        if len(self._recent_best_energies) >= 3:
            var = statistics.variance(self._recent_best_energies)
            if var < 1e-5:
                self.trigger_reheating_pulse()
                return True
        return False
