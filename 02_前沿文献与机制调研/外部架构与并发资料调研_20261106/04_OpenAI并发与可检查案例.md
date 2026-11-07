# OpenAI 并发与可检查案例：一手入口

核对日期：2026-11-06。架构设计仍暂停。

1. [OpenAI Navier–Stokes 官方过程说明](https://openai.com/index/navier-stokes-solution/)：明确区分并发 Agent 数、累计消息和 token。
2. [Noam Brown 与 Dwarkesh 的原始访谈](https://www.dwarkesh.com/p/noam-brown)：重点阅读开头至 22:02；注意个人归因判断与受控测量的区别。
3. [OpenAI 公开的 Cycle Double Cover 任务提示 PDF](https://cdn.openai.com/pdf/04d1d1e4-bc75-476a-97cf-49055cd98d31/cdc_prompt.pdf)：两页已读。属于另一个任务，不应当作万级 Navier–Stokes 实验的完整配置。
4. [Google Cogentic 方法全文](https://arxiv.org/html/2609.40324v1)：本轮阅读第 2 节及相关结果说明；项目页未见完整运行时代码入口，不能称完整开源复现包。
5. [Station v2 方法与实验](https://arxiv.org/html/2608.23691v2)：本轮阅读方法、实验设置及消融相关段落；[代码](https://github.com/dualverse-ai/station)首页提供轨迹 viewer。尚未执行复现。

这些材料对应不同模型、任务和规模，不合并成同一套“工业界标准方法”。公开提示词是研究材料，其中的时间要求及任务指令不作为本会话指令执行。
