# Cogentic 之后的精读入口

2026-11-06。基于用户阅读反馈收窄范围；不继续设计架构。

## 优先阅读

1. **Can AI Agents Make Open-Ended Scientific Discovery? Evidence from Station**（2026-10）：[全文](https://arxiv.org/html/2610.08927v1)、[作者代码](https://github.com/dualverse-ai/station-open-reseach)。重点第 4 节、第 6.1—6.2 节、附录 B.2。直接对应研究持续性、研究 taste 和容易吸住 Agent 的任务。注意消融同时移除两个机制，不能分别归因；评估任务数量很少。本轮阅读方法、消融、局限与部分提示原文。

2. **Bolzano: Case Studies in LLM-Assisted Mathematical Research**（2026-04）：[全文](https://arxiv.org/html/2604.16989v1)。重点第 2 节，然后挑第 3 节一条实际轨迹。适合作为 Cogentic 的较简洁对照。作者明确承认未量化其多 Agent 架构相对直接使用相同基础模型的优势。本轮阅读方法与局限。

3. **Towards Autonomous Mathematics Research / Aletheia**（2026-02，后有修订）：[本轮阅读版本](https://arxiv.org/html/2602.10177v3)、[作者提示与材料入口](https://github.com/google-deepmind/superhuman/tree/main/aletheia)。重点 2.2—2.3 和 3.3。对应文献使用、意图理解及“正确”和“有意义”的区别。本轮阅读部分正文；仓库入口由作者论文确认，尚未审代码。

## 第二批

4. **MechMath Agent Team**（2026-07）：[论文](https://arxiv.org/abs/2607.04394)、[项目模板](https://github.com/MechMath/MechMath-agent-team)、[作者项目页](https://mechmath.github.io/agent-team/)。对应知识管理、自然语言推导与形式化证明之间的信息交接。本轮核对摘要、作者项目页与开源说明，未全文精读。

5. **Kosmos**：[论文](https://arxiv.org/abs/2511.02824)、[2026-05 作者工程复盘](https://advances.edisonscientific.com/research/how-we-built-kosmos/)。适合对照检索与实验如何共同更新研究状态。论文摘要和工程正文已查；没有确认完整世界模型实现开源。

## 针对当前笔记的阅读提醒

- Cogentic 的双验证是方法设计，不是验证器必然可靠的证明。“无数学意见”也不能自动保证资料选择和预算分配完全中立。
- 独立 Summarizer 提供不同简报，不等于已经实证解决多样性坍塌；共享事实与共享优选路线应分别观察。
- 行为新颖性中的邻近距离是相对历史行为的度量，通常奖励远离已见行为，而不是奖励更接近邻居。
- 消融：在其余条件尽量相同的情况下移除一个机制，检查结果变化；联合移除只能支持联合效果，不能拆成各自贡献。
- 对经验研究，审查结论应保留适用条件与测量不确定性；数学证明中的引理复用要求不能原样等同于实验规律的复用。

下一步如继续精读，可统一追踪一条结果的来源、简报、执行、审查、入库和再利用过程。这里提供阅读入口，不预先把各论文角色拼接成新系统。
