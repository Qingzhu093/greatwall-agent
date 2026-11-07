# Great Wall Agent V4.2 for Codex

Codex 移植包沿用 `greatwall-agent` V4.2 的 Python 内核、9 个 MCP 工具、技能、规则和探索角色说明。Python 3 标准库即可运行 MCP 服务。

## 安装

通过 NPM 取得完整插件目录：

```sh
npm pack codex-greatwall-agent
```

解包后将 `package/` 目录放在 Codex 本地插件源下。插件根目录的 `plugin.json`、`mcp.json` 和 `skills/` 由 Codex 插件加载器发现。也可从私有 GitHub 仓库克隆同一目录。启动 MCP 需要 `python` 在 PATH 中。

使用 Codex CLI 手动挂载时，在 `~/.codex/config.toml` 中注册 `mcp_servers.greatwall_agent`，令 `command = "python"`，`args` 指向解包目录内的 `bin/gw_mcp_server.py`，并设置 `PYTHONUTF8 = "1"`。将 `rules/AGENTS.md` 放到赛题工作区，按 `skills/greatwall-campaign/SKILL.md` 使用工具。

## 验证

```sh
python tests/test_plugin_e2e.py
```

此版本仍处于实测阶段。Codex 宿主接线按当前插件格式封装，内核逻辑保持原版。
