# CUMCM 2026 B 题：无线电干扰源的快速自动定位与清除 —— 赛题精解与接口规范 (`BRIEF_AND_PROBLEM.md`)

## 一、 物理场景与全局几何参数

1. **目标分布区域**：半径 $R_{\text{arena}} = 1800\text{ m}$ 的二维圆形区域 $\Omega = \{(x,y) \in \mathbb{R}^2 \mid x^2 + y^2 \le 1800^2\}$，圆心 $(0,0)$ 为原点，正东为 $x$ 轴正向，正北为 $y$ 轴正向（单位：米）。
2. **干扰源特征**：
   - 总数 $N \in [10, 16]$ 未知，各干扰源所在频道互不相同且不随时间变化，位于编号 $\{1, 2, \dots, 20\}$ 的 20 个频道中（即有 $20 - N \in [4, 10]$ 个频道为**无源空频道**）。
   - 各干扰源的有效接收半径 $R_{\text{rec}, i} \in [1000, 1500]\text{ m}$ 固定但未知。
   - **全向干扰源（Q1~Q3 全部、Q4 部分）**：覆盖角度 $360^\circ$。
   - **定向干扰源（Q4 部分）**：具有特定发射主瓣方向 $\phi_i \in [0^\circ, 360^\circ)$，有效覆盖角度范围为定向方向两侧各 $90^\circ$（含），即 $|\text{wrap}(\text{atan2}(y - y_i, x - x_i) - \phi_i)| \le 90^\circ$ 半平面内有信号，半平面外无信号辐射。
3. **测向机与机器狗运动学参数**：
   - 机器狗初始位置 $(0,0)$，初始测向频道 $c_0 = 1$，直线移动速度 $v = 5\text{ m/s}$。
   - **测向误差模型**：示向度 $\hat{\theta} \in [0^\circ, 360^\circ)$ 为 $x$ 轴正向逆时针旋转至“检测点指向干扰源向量”的方位角，读数保留两位小数。测向误差 $\epsilon = \hat{\theta} - \theta_{\text{true}} \in [-1^\circ, 1^\circ]$，同一地点电磁环境固定（重复检测误差不变），不同地点呈统计分布。
   - **近场过载盲区**：当检测点与干扰源距离 $d \le 5\text{ m}$ 且在有效覆盖角度范围内时，无法获得示向度，模拟器返回 `"near"`。
   - **耗时规则（虚拟时钟）**：
     - `/enter` 与 `/exit`：耗时 $0\text{ s}$。
     - `/measure(position, channel)`：
       $$\Delta t_{\text{measure}} = \frac{\|\mathbf{p}_{\text{new}} - \mathbf{p}_{\text{prev}}\|_2}{5.0} + \mathbb{I}(c_{\text{new}} \ne c_{\text{curr}}) \times 1.0 + 5.0\text{ (s)}$$
       返回结果：`"no_signal"`、`"near"`（$d \le 5\text{ m}$）、或 `"direction"`（附带 `"svd_deg"`）。成功后更新当前频道 $c_{\text{curr}} \leftarrow c_{\text{new}}$。
     - `/clear(position, channel)`：
       $$\Delta t_{\text{clear}} = \frac{\|\mathbf{p}_{\text{new}} - \mathbf{p}_{\text{prev}}\|_2}{5.0} + \begin{cases} 5.0\text{ s} & \text{若 } d(\mathbf{p}_{\text{new}}, \mathbf{s}_c) \le 20\text{ m 且未清除 (返回 "success")} \\ 3.0\text{ s} & \text{若 } 20\text{ m 内无该频道未清除源 (返回 "no\_target\_in\_range")} \end{cases}$$
       **关键特性**：`/clear` 的 `channel` 参数仅指定激光清除的目标源频道，**不改变测向机当前频道 $c_{\text{curr}}$，也不产生 $1\text{ s}$ 频道切换耗时**！且光学定位与激光清除是否成功**仅取决于距离是否 $\le 20\text{ m}$，与定向干扰源的发射方向无关**。

---

## 二、 四大核心问题数学定义与评价指标

1. **问题 1（多边形交会定位区域直径与圆覆盖充要条件）**：
   - 已知 $K$ 个检测点坐标 $S_k = (x_k, y_k)$ 及测得示向度 $\hat{\theta}_k$，由误差界 $\pm \Delta\theta$（$\Delta\theta = 1^\circ$）构成 $K$ 个扇形角域（半平面交），交集形成凸多边形定位区域 $\mathcal{P}$。
   - 设计高效精确算法计算 $\mathcal{P}$ 的直径 $D(\mathcal{P}) = \max_{p, q \in \mathcal{P}} \|p - q\|_2$（半平面交 $O(K\log K)$ + Shamos-Toussaint 对踵点对有向叉积旋转卡尺 $O(m)$）。
   - 严格论证：**以定位区域直径 $D(\mathcal{P})$ 为直径（即半径 $R = D/2$）的圆能否覆盖此定位区域 $\mathcal{P}$？**（结论：**不能保证总是覆盖**；由 Jung 定理 $\frac{D}{\sqrt{3}} \ge R_{\text{MEC}} \ge \frac{D}{2}$，当且仅当直径两端点中点到所有其余顶点距离均 $\le D/2$——即对所有其余顶点张角均为直角或钝角 $\angle V_i P^* Q^* \ge 90^\circ$ 时能覆盖；若存在锐角张角如正三角形或多检测点交会出的锐角三角形/近正多边形交会区，以直径为直径的圆无法覆盖全部区域）。

2. **问题 2（全向干扰源第二个检测点 $S_2$ 最优选址策略与候选区域）**：
   - 已知第一检测点 $S_1 = (x_1, y_1)$ 测得示向度 $\hat{\theta}_1$，干扰源真实位置 $G$ 位于射线角域 $[\hat{\theta}_1 - 1^\circ, \hat{\theta}_1 + 1^\circ]$ 与有效接收圆 $d(S_1, G) \in (5, R_{\text{rec}}]$ 及圆域 $\Omega$ 的交集条带 $\mathcal{U}_1$ 内。
   - 建立基于 **Fisher 信息矩阵（FIM）/ 几何精度因子（GDOP）与最坏情况交会多边形直径 $D(S_2)$ 加上移动耗时惩罚** 的多目标选址优化模型，推导正交交会定理（$\alpha^* = |\theta_2 - \theta_1| = 90^\circ$）与距离-移动时间折中解，给出 $S_2$ 的显式候选区域。

3. **问题 3（全向干扰源 $N \in [10, 16]$ 快速自动搜索、定位与清除）**：
   - 全部为全向干扰源，分布于 20 个频道中的 $N \in [10, 16]$ 个未知频道。
   - 评价统计量：
     $$\text{被清除干扰源个数的比例} = \frac{N_{\text{cleared}}}{N_{\text{total}}}, \qquad \text{平均定位清除时间} = \frac{T_{\text{total}}}{N_{\text{cleared}}}$$
   - **核心瓶颈**：消除清完真实干扰源后对 $20 - N$ 个无源空频道的盲目外圈巡逻空耗（`empty_or_redundant_waste_ratio`），确保 $100\%$ 清除率且平均定位清除时间 $\le 220\text{ s}$。

4. **问题 4（全向 + $180^\circ$ 定向混合干扰源快速定位与清除）**：
   - 含未知数量、未知主瓣朝向 $\phi_i$ 的 $180^\circ$ 定向干扰源。当定向源位于外环 $r \in [1500, 1800]\text{ m}$ 且主瓣朝向圆外时，常规内圈探测处于其背向盲区，必须设计具备**贴边向心逆向包络覆盖**与**半平面可见性联合推断**的鲁棒搜索与异侧交会清除策略。
