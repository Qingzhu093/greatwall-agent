# v0.3 实机验收与子题控制说明

2026-11-26，在 Windows 上检查了远端主线 `9c5b8f3` 和待合并修复分支 `bcff985`。下列两个新增用例在后者上先失败，再在本次修订后通过。测试使用独立工作目录、真实 Python 子进程、插件的 Node 通信桥及 SQLite。DSH 安装检查使用独立 headless 配置。未调用付费模型。

## 暂停、恢复与预算

子题有两个不同的状态。人的操作决定期望状态，例如 ACTIVE 或 PAUSED；系统结合当前题目口径、已验证成果和预算，计算实际能否继续派发。用户点“恢复”后，应以返回的 `dispatch_state` 为准。

| 操作 | 预期结果 |
|---|---|
| 暂停正在探索的 Q1 | Q1 进入 PAUSED_HUMAN，正在运行的分支进入收尾流程 |
| 再次提交同一暂停 | 保持原调度代次，重试不产生一轮新的停工命令 |
| 恢复额度充足、尚未达标的子题 | 重新进入 DISPATCHING |
| 对已达硬预算的子题请求 ACTIVE | 期望状态可为 ACTIVE，实际状态保持 PAUSED_BLOCKED。重复恢复也不能重置消耗 |
| Q1 达到自己的预算上限 | 该上限只影响 Q1。Q2 仍按自己的条件运行 |

后勤规范允许已开工的分支在触达预算后收尾，因此最后用量可以高于触线时的用量。控制面要阻止继续派新班次，并保留可核对的最新停工原因。[后勤工程](./agent_kb_v0_3/ARCH_PAPER_03_后勤工程_Logistics_and_Lineage_Engineering.md) · [状态表与预算字段](./agent_kb_v0_3/agent_kb_v0_3_04_数据模型与旧库迁移_精确SQLite_DDL与工具契约增量.md)

## 实际发现与修正

1. **重复暂停改变调度代次。** 在新建 Q1 上连续两次调用同一暂停入口，第一次返回代次 2，第二次返回 3。原实现每次递增代次，存在活跃节点时还会用新代次再次生成收尾命令。现在在写事务中读取并核对当前状态，相同暂停或关闭请求直接返回已有代次。实测两次暂停代次相同，正常恢复随后成功。
2. **恢复操作漏查硬预算。** 为 Q1 单独设置 100 tokens 上限，通过控制面记入 100，再请求 ACTIVE，原入口返回 DISPATCHING。现在恢复请求在同一事务内重新结算已有的子题停工规则，再返回实际状态。实测直接恢复、先暂停再恢复两条路径均返回 PAUSED_BLOCKED。对未限额的 Q2 同样请求 ACTIVE，返回 DISPATCHING。

## 文档要求与验证范围

| 文档要求 | 本轮取得的证据 | 尚待验证 |
|---|---|---|
| 10 个角色、44 个工具、8 套预设 | 项目自检通过角色模板与跨语言工具契约检查。实际 DSH 0.2.2-rc.5 合成配置，出现长城入口和 8 套预设 | 本机默认桌面配置未声明此插件，自检给出警告。尚未验证 8 套预设都能在桌面中实际创建会话 |
| 人工控制、硬预算和各子题独立 | 通过真实通信桥发起暂停、重复暂停、记账、恢复；对 Q1、Q2 分别核对结果 | 这次用量为测试输入。服务商实际计费、长时间并发收尾的最终费用仍需在线试验 |
| 45% 人工接管、工件哈希对账、旧库迁移、Stage 3 冻结核签 | 仓库中对应的接管、迁移和冻结交付回归用例在本机通过 | 尚未把上述环节串成一次由真实模型驱动、经人工接管后最终交付的完整科研任务 |
| 角色模板的一致性 | 当前模板自检通过。历史逐字比对因缺少旧版参考文档而跳过 | 该跳过项没有提供历史模板逐字一致的证据 |

## 如何复测

在 Node ≥ 24、Python ≥ 3.11 的环境中，把 `GREATWALL_PYTHON` 指向实际解释器。在 `greatwall-v6up/dsh_plugin` 执行下列命令。

```sh
node tools/doctor.mjs --json
node --test --test-name-pattern="子题控制" test/v03_cross_layer_integration.test.mjs
node --test test/fake_llm_pipeline.test.mjs test/v03_cross_layer_integration.test.mjs test/v03_runtime_and_chief.test.mjs test/v3_control_plane_unit.test.mjs
```

再从 `greatwall-v6up` 执行 `python -X utf8 -m unittest discover -s tests -v`。本次 Node 共 56 项通过；Python 共 70 项，其中 69 项通过、1 项跳过。宿主检查另从全新 DSH_HOME 生成 headless 配置，按仓库首页挂载插件并执行 `dsh --profile headless --dump-config`，退出码为 0。配置合成、跨进程行为和整机科研任务分别验收。
