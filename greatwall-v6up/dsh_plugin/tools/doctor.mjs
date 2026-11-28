#!/usr/bin/env node
/**
 * GreatWall V6-Up (dsh-greatwall-v6up) 运行环境与架构契约一键自检工具。
 *
 * 用法：
 *   node tools/doctor.mjs          # 人类可读诊断摘要
 *   node tools/doctor.mjs --json   # 机器可读 JSON 输出
 *
 * 退出码：
 *   0 — 所有必选检查通过（允许 soft/info 项）
 *   1 — 存在必需环境缺失或跨层契约失配
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  ALL_MCP_TOOLS,
  CANONICAL_ROLES,
  ROLE_MCP_TOOLS,
  TURN_CONCLUDING_TOOLS,
} from '../lib/prompts.js'
import { BUNDLE_PATCH_PATH, ROLE_TO_PRESET, loadBundlePresetConfigs } from '../lib/presets.js'
import { READONLY_BLOCKED_MCP_TOOLS } from '../lib/read_isolated_sandbox.js'
import { LONG_RUNNING_MCP_TOOLS } from '../lib/mcp_bridge.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PLUGIN_ROOT = path.resolve(__dirname, '..')
const PROJECT_ROOT = path.resolve(PLUGIN_ROOT, '..')
const CORE_PYTHON_ROOT = path.join(PROJECT_ROOT, 'core_python')

const AS_JSON = process.argv.includes('--json')
const PYTHON_BIN = process.env.GREATWALL_PYTHON || 'python'

/** @typedef {{ id: string, title: string, status: 'ok'|'warn'|'info'|'error', required: boolean, detail: string, extra?: Record<string, any> }} CheckItem */

function parseSemver(raw) {
  const m = String(raw || '').match(/(\d+)\.(\d+)\.(\d+)/)
  if (!m) return null
  return [Number(m[1]), Number(m[2]), Number(m[3])]
}

function cmpSemver(a, b) {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i]
  }
  return 0
}

function sortedDiff(expectedIter, actualIter) {
  const exp = new Set(expectedIter)
  const act = new Set(actualIter)
  const missing = [...exp].filter((x) => !act.has(x)).sort()
  const extra = [...act].filter((x) => !exp.has(x)).sort()
  return { missing, extra, equal: missing.length === 0 && extra.length === 0 }
}

/** @returns {CheckItem} */
function checkNodeRuntime() {
  const ver = parseSemver(process.versions.node)
  const ok = Boolean(ver && (cmpSemver(ver, [22, 19, 0]) >= 0))
  return {
    id: 'node_runtime',
    title: 'Node.js 运行时版本',
    status: ok ? 'ok' : 'error',
    required: true,
    detail: ok
      ? `Node v${process.versions.node}（满足 >=22.19.0）`
      : `Node v${process.versions.node} 过低，要求 ^22.19.0 || >=24.0.0`,
  }
}

/** @returns {{ item: CheckItem, pySnapshot: Record<string, any> | null }} */
function checkPythonAndContracts() {
  const script = [
    'import json, sys',
    `sys.path.insert(0, ${JSON.stringify(PROJECT_ROOT)})`,
    'from core_python.mcp_server.tool_registry import export_contracts_snapshot',
    'print(json.dumps({"python": sys.version.split()[0], "snapshot": export_contracts_snapshot()}, ensure_ascii=False))',
  ].join('\n')

  const proc = spawnSync(PYTHON_BIN, ['-c', script], {
    cwd: PROJECT_ROOT,
    encoding: 'utf8',
    timeout: 15_000,
    windowsHide: true,
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' },
  })

  if (proc.error || proc.status !== 0) {
    const errMsg = proc.error?.message || (proc.stderr || proc.stdout || '').trim().slice(0, 300)
    return {
      item: {
        id: 'python_runtime',
        title: 'Python 运行时与 core_python 可导入性',
        status: 'error',
        required: true,
        detail: `执行 ${PYTHON_BIN} 失败: ${errMsg || `exit=${proc.status}`}`,
      },
      pySnapshot: null,
    }
  }

  let parsed = null
  try {
    parsed = JSON.parse(String(proc.stdout || '').trim())
  } catch (err) {
    return {
      item: {
        id: 'python_runtime',
        title: 'Python 运行时与 core_python 可导入性',
        status: 'error',
        required: true,
        detail: `解析 Python 契约快照 JSON 失败: ${err?.message || err}`,
      },
      pySnapshot: null,
    }
  }

  const pyVer = parseSemver(parsed.python)
  const verOk = Boolean(pyVer && cmpSemver(pyVer, [3, 10, 0]) >= 0)
  return {
    item: {
      id: 'python_runtime',
      title: 'Python 运行时与 core_python 可导入性',
      status: verOk ? 'ok' : 'error',
      required: true,
      detail: verOk
        ? `Python ${parsed.python} (${PYTHON_BIN})，core_python.mcp_server.tool_registry 导入正常`
        : `Python ${parsed.python} 过低，要求 >=3.10`,
    },
    pySnapshot: parsed.snapshot || null,
  }
}

/** @returns {CheckItem} */
function checkGitRuntime() {
  const proc = spawnSync('git', ['--version'], {
    encoding: 'utf8',
    timeout: 5_000,
    windowsHide: true,
  })
  const ok = !proc.error && proc.status === 0
  return {
    id: 'git_runtime',
    title: 'Git Worktree 依赖',
    status: ok ? 'ok' : 'error',
    required: true,
    detail: ok ? String(proc.stdout || '').trim() : `git 不可用: ${proc.error?.message || proc.stderr}`,
  }
}

/**
 * 校验 Python 单一契约源与 Node 侧静态声明 100% 一致。
 * @param {Record<string, any> | null} pySnapshot
 * @returns {CheckItem}
 */
function checkToolContractsSync(pySnapshot) {
  if (!pySnapshot) {
    return {
      id: 'tool_contracts_sync',
      title: 'Python ↔ Node 窄工具与 10 角色跨层契约同步',
      status: 'error',
      required: true,
      detail: '因 Python 运行时检查失败，无法比对跨层契约',
    }
  }

  const mismatches = []
  if (pySnapshot.schema_version !== '0.3.2') mismatches.push({ field: 'schema_version' })
  if (pySnapshot.tool_count !== 53 || ALL_MCP_TOOLS.size !== 53) mismatches.push({ field: 'tool_count' })
  const pyRoles = pySnapshot.role_mcp_tools || {}
  const pyAllTools = [...new Set(Object.values(pyRoles).flat())]

  const allDiff = sortedDiff(pyAllTools, ALL_MCP_TOOLS)
  if (!allDiff.equal) mismatches.push({ field: 'all_tools', ...allDiff })

  const roleKeyDiff = sortedDiff(pySnapshot.canonical_roles || Object.keys(pyRoles), Object.keys(ROLE_MCP_TOOLS))
  if (!roleKeyDiff.equal) {
    mismatches.push({ field: 'role_names', ...roleKeyDiff })
  } else {
    for (const role of Object.keys(pyRoles)) {
      const d = sortedDiff(pyRoles[role] || [], ROLE_MCP_TOOLS[role] || [])
      if (!d.equal) mismatches.push({ field: `role_mcp_tools.${role}`, ...d })
    }
  }

  const roDiff = sortedDiff(pySnapshot.readonly_blocked_mcp_tools || [], READONLY_BLOCKED_MCP_TOOLS)
  if (!roDiff.equal) mismatches.push({ field: 'readonly_blocked_mcp_tools', ...roDiff })

  const longDiff = sortedDiff(pySnapshot.long_running_mcp_tools || [], LONG_RUNNING_MCP_TOOLS)
  if (!longDiff.equal) mismatches.push({ field: 'long_running_mcp_tools', ...longDiff })

  const concludeDiff = sortedDiff(pySnapshot.turn_concluding_tools || [], TURN_CONCLUDING_TOOLS)
  if (!concludeDiff.equal) mismatches.push({ field: 'turn_concluding_tools', ...concludeDiff })

  if (mismatches.length > 0) {
    return {
      id: 'tool_contracts_sync',
      title: 'Python ↔ Node 窄工具与 10 角色跨层契约同步',
      status: 'error',
      required: true,
      detail: `发现 ${mismatches.length} 处跨层契约漂移: ${mismatches.map((m) => m.field).join(', ')}`,
      extra: { mismatches },
    }
  }

  return {
    id: 'tool_contracts_sync',
    title: 'Python ↔ Node 窄工具与 10 角色跨层契约同步',
    status: 'ok',
    required: true,
    detail: `${ALL_MCP_TOOLS.size} 窄工具 / ${CANONICAL_ROLES.length} 角色路由 / ${READONLY_BLOCKED_MCP_TOOLS.size} 只读禁写 / ${LONG_RUNNING_MCP_TOOLS.size} 长耗时 / ${TURN_CONCLUDING_TOOLS.size} 回合收尾工具全部 100% 同步`,
  }
}

/** @returns {CheckItem} */
function checkPresetsIntegrity() {
  const presetIds = [...new Set(Object.values(ROLE_TO_PRESET))].sort()
  if (!fs.existsSync(BUNDLE_PATCH_PATH)) {
    return {
      id: 'presets_integrity',
      title: '8 套 v0.3 DSH Preset 单源声明 (cordis.patch.yml)',
      status: 'error',
      required: true,
      detail: `缺少权威 Bundle 声明文件: ${BUNDLE_PATCH_PATH}`,
    }
  }
  let declared = []
  try {
    declared = loadBundlePresetConfigs(process.platform, BUNDLE_PATCH_PATH)
  } catch (err) {
    return {
      id: 'presets_integrity',
      title: '8 套 v0.3 DSH Preset 单源声明 (cordis.patch.yml)',
      status: 'error',
      required: true,
      detail: `解析 cordis.patch.yml 失败: ${err?.message || err}`,
    }
  }
  const byId = new Map(declared.map((p) => [p.id, p]))
  const issues = []
  for (const pid of presetIds) {
    const def = byId.get(pid)
    if (!def) {
      issues.push(`缺失 Preset: ${pid}`)
      continue
    }
    const pluginNames = new Set((def.plugins || []).map((p) => p.name))
    if (!pluginNames.has('@deepseek-ai/dsh-persona')) {
      issues.push(`${pid} 缺少 @deepseek-ai/dsh-persona`)
    }
    if (!pluginNames.has('@deepseek-ai/dsh-tool-executor-native')) {
      issues.push(`${pid} 缺少 @deepseek-ai/dsh-tool-executor-native`)
    }
    if (pluginNames.has('@deepseek-ai/dsh-compaction-basic') || pluginNames.has('@deepseek-ai/dsh-token-meter')) {
      issues.push(`${pid} 将压缩或计量服务直接挂在 Preset 顶层`)
    }
    const compaction = def.plugins.find((p) => p.isolate?.compaction)
    if (pid === 'greatwall-chief' && !compaction?.config?.some((p) => p.name === '@deepseek-ai/dsh-command-compact')) {
      issues.push(`${pid} 缺少隔离的 /compact 命令`)
    }
    if (pid === 'greatwall-explorer' && (compaction || def.plugins.some((p) =>
      p.isolate?.toolResultPruner || p.name === '@deepseek-ai/dsh-compaction-tool-result-pruner'))) {
      issues.push(`${pid} 声明了压缩或裁剪能力`)
    }
  }
  const ok = presetIds.length === 8 && declared.length === 8 && issues.length === 0
  return {
    id: 'presets_integrity',
    title: '8 套 v0.3 DSH Preset 单源声明 (cordis.patch.yml)',
    status: ok ? 'ok' : 'error',
    required: true,
    detail: ok
      ? `8 套单源 Preset 齐全且全部符合 v0.3 隔离与 RC5 native executor 规约 (${presetIds.join(', ')})`
      : `Preset 声明异常: ${issues.join('; ')}`,
  }
}

/** @returns {CheckItem} */
function checkAgentTemplates() {
  const missing = []
  for (const role of CANONICAL_ROLES) {
    const fp = path.join(CORE_PYTHON_ROOT, 'agents', `${role}.md`)
    if (!fs.existsSync(fp)) missing.push(`agents/${role}.md`)
  }
  if (!fs.existsSync(path.join(CORE_PYTHON_ROOT, 'config.json'))) {
    missing.push('config.json')
  }
  const legacySurveyor = path.join(CORE_PYTHON_ROOT, 'agents', 'library_surveyor.md')
  const extras = fs.existsSync(legacySurveyor) ? ['agents/library_surveyor.md (旧 v0.2 遗留未清理)'] : []
  const ok = missing.length === 0 && extras.length === 0
  return {
    id: 'agent_templates',
    title: '10 份角色系统提示词与 core_python/config.json',
    status: ok ? 'ok' : 'error',
    required: true,
    detail: ok
      ? `10 份 v0.3 角色模板与 config.json 完整就绪（零旧版残留）`
      : `模板异常: ${[...missing.map((x) => `缺失 ${x}`), ...extras].join('; ')}`,
  }
}

/** @returns {CheckItem} */
function checkV03Redlines() {
  const issues = []
  const pkgPath = path.join(PLUGIN_ROOT, 'package.json')
  try {
    const pkgRaw = fs.readFileSync(pkgPath, 'utf8')
    if (pkgRaw.includes('dsh-client-ui-primitives')) {
      issues.push('package.json 仍包含禁止引用的 dsh-client-ui-primitives')
    }
  } catch (err) {
    issues.push(`无法读取 package.json: ${err?.message || err}`)
  }

  const clientPath = path.join(PLUGIN_ROOT, 'lib', 'client.js')
  if (!fs.existsSync(clientPath)) {
    issues.push('缺少前端编译产物 lib/client.js（请先运行 npm run build:client）')
  } else {
    const clientRaw = fs.readFileSync(clientPath, 'utf8')
    if (clientRaw.includes('dsh-client-ui-primitives')) {
      issues.push('lib/client.js 包含禁止引用的 dsh-client-ui-primitives')
    }
  }

  const ok = issues.length === 0
  return {
    id: 'v03_redlines',
    title: 'v0.3 前端构建产物与工程红线校验',
    status: ok ? 'ok' : 'error',
    required: true,
    detail: ok
      ? 'lib/client.js 已构建、零 dsh-client-ui-primitives 依赖'
      : issues.join('; '),
  }
}

/** @returns {CheckItem} */
function checkDshProfileMount() {
  const profilePkgPath = path.join(os.homedir(), '.dsh', 'profiles', 'desktop', 'package.json')
  if (!fs.existsSync(profilePkgPath)) {
    return {
      id: 'dsh_profile_mount',
      title: '本机 DSH Desktop 插件挂载状态（可选）',
      status: 'info',
      required: false,
      detail: `未检测到 ${profilePkgPath}（纯本地开发/CI 环境可忽略）`,
    }
  }
  try {
    const pkg = JSON.parse(fs.readFileSync(profilePkgPath, 'utf8'))
    const dep = pkg?.dependencies?.['dsh-greatwall-v6up'] || pkg?.devDependencies?.['dsh-greatwall-v6up']
    if (dep) {
      return {
        id: 'dsh_profile_mount',
        title: '本机 DSH Desktop 插件挂载状态（可选）',
        status: 'ok',
        required: false,
        detail: `已挂载 dsh-greatwall-v6up -> ${dep}`,
      }
    }
    return {
      id: 'dsh_profile_mount',
      title: '本机 DSH Desktop 插件挂载状态（可选）',
      status: 'warn',
      required: false,
      detail: `DSH Desktop profile 存在，但尚未声明 dsh-greatwall-v6up 依赖（可按 README 挂载本地路径）`,
    }
  } catch (err) {
    return {
      id: 'dsh_profile_mount',
      title: '本机 DSH Desktop 插件挂载状态（可选）',
      status: 'warn',
      required: false,
      detail: `读取 ${profilePkgPath} 失败: ${err?.message || err}`,
    }
  }
}

function main() {
  const { item: pyItem, pySnapshot } = checkPythonAndContracts()
  /** @type {CheckItem[]} */
  const checks = [
    checkNodeRuntime(),
    pyItem,
    checkGitRuntime(),
    checkToolContractsSync(pySnapshot),
    checkPresetsIntegrity(),
    checkAgentTemplates(),
    checkV03Redlines(),
    checkDshProfileMount(),
  ]

  const failedRequired = checks.filter((c) => c.required && c.status === 'error')
  const ok = failedRequired.length === 0
  const report = {
    ok,
    plugin: 'dsh-greatwall-v6up',
    projectRoot: PROJECT_ROOT,
    pluginRoot: PLUGIN_ROOT,
    checkedAt: new Date().toISOString(),
    checks,
  }

  if (AS_JSON) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
  } else {
    const iconMap = { ok: '[OK]  ', warn: '[WARN]', info: '[INFO]', error: '[FAIL]' }
    process.stdout.write(`GreatWall V6-Up 环境与架构契约诊断 (doctor)\n`)
    process.stdout.write(`工作区: ${PROJECT_ROOT}\n\n`)
    for (const c of checks) {
      process.stdout.write(`${iconMap[c.status] || '[????]'} ${c.title}: ${c.detail}\n`)
    }
    process.stdout.write(`\n结论: ${ok ? '全部必选项通过，可正常挂载与运行。' : `存在 ${failedRequired.length} 项必选检查失败，请按上述提示修复。`}\n`)
  }

  process.exit(ok ? 0 : 1)
}

main()
