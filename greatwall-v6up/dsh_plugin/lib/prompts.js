/**
 * GreatWall Agent 十大角色契约与平台感知原生工具白名单。
 * 权威单一契约源位于 `core_python/mcp_server/tool_registry.py`，由跨层架构测试与 doctor 强制校验 100% 同步。
 * @module dsh-greatwall-v6up/prompts
 */
import fs from 'node:fs'
import path from 'node:path'

const contracts = JSON.parse(fs.readFileSync(new URL('./contracts.generated.json', import.meta.url), 'utf8'))
export const CONTRACTS_SCHEMA_VERSION = contracts.schema_version
export const CANONICAL_ROLES = Object.freeze(contracts.canonical_roles)
export const READONLY_BLOCKED_MCP_TOOLS = Object.freeze(new Set(contracts.readonly_blocked_mcp_tools))
export const LONG_RUNNING_MCP_TOOLS = Object.freeze(new Set(contracts.long_running_mcp_tools))

export const ROLE_EFFORT_MAP = Object.freeze({
  gw_chief: 'medium',
  explorer: 'high',
  library_verifier: 'high',
  library_chronicler: 'high',
  conference_chair: 'high',
  external_surveyor: 'medium',
  lineage_companion: 'medium',
  works_engineer: 'medium',
  logistics_coordinator: 'low',
  supervisory_committee: 'low',
})

export const ROLE_MCP_TOOLS = Object.freeze(Object.fromEntries(
  Object.entries(contracts.role_mcp_tools).map(([role, tools]) => [role, Object.freeze(tools)]),
))

/** 已封存伴随助手进入圆桌参会态时的只读窄工具子集（物理卸载全部档案写工具）。 */
export const SEALED_COMPANION_CONFERENCE_TOOLS = Object.freeze([
  'get_companion_context',
  'get_living_survey',
  'query_library_catalog',
  'get_library_entry',
  'submit_conference_statement',
])

export const ALL_MCP_TOOLS = Object.freeze(new Set(Object.values(ROLE_MCP_TOOLS).flat()))
export const ALL_31_MCP_TOOLS = ALL_MCP_TOOLS

export function resolvePlatformShellTool(platform = process.platform) {
  return platform === 'win32' ? 'pwsh' : 'bash'
}

/**
 * 平台感知的 10 角色原生 DSH 工具允许清单：
 * - `explorer` / `works_engineer`: 读写 fs + search + 平台 Shell
 * - `library_verifier`: 只读 fs + search + 平台 Shell（挂载独立空白盲审沙箱）
 * - `lineage_companion` / `gw_chief`: 只读 fs + search
 * - `external_surveyor`: 仅 web_search / web_fetch（唯一联网，零本地 fs 防院内泄露）
 * - `library_chronicler` / `conference_chair` / `logistics_coordinator` / `supervisory_committee`: `[]`（物理 0 原生工具）
 */
export function resolvePlatformAllowedTools(role, platform = process.platform) {
  const shell = resolvePlatformShellTool(platform)
  switch (role) {
    case 'explorer':
    case 'works_engineer':
      return ['read', 'write', 'edit', 'read_image', 'glob', 'grep', shell]
    case 'library_verifier':
      return ['read', 'glob', 'grep', shell]
    case 'lineage_companion':
    case 'gw_chief':
      return ['read', 'glob', 'grep']
    case 'external_surveyor':
      return ['web_search', 'web_fetch']
    case 'library_chronicler':
    case 'conference_chair':
    case 'logistics_coordinator':
    case 'supervisory_committee':
    default:
      return []
  }
}

export const ROLE_NATIVE_ALLOW_TOOLS = Object.freeze(
  Object.fromEntries(CANONICAL_ROLES.map((r) => [r, Object.freeze(resolvePlatformAllowedTools(r, process.platform))])),
)

export const ROLE_SHORT_LABELS = Object.freeze({
  gw_chief: '科研总控',
  explorer: '探索',
  lineage_companion: '伴随',
  logistics_coordinator: '后勤总管',
  external_surveyor: '对外采编',
  library_chronicler: '综述终稿官',
  conference_chair: '圆桌主席',
  library_verifier: '图书馆盲审',
  works_engineer: '科研仪器科',
  supervisory_committee: '监察委员会',
})

export function formatNodeSessionTitle(role, { questionId = '', branchId = '', nodeId = '', suffix = '' } = {}) {
  const base = ROLE_SHORT_LABELS[role] || role
  let head = `[${base}]`
  if (role === 'explorer') {
    const tag = [questionId, '探索'].filter(Boolean).join('-')
    head = `[${tag || base}]`
  } else if (role === 'lineage_companion') {
    const tag = ['伴随', questionId].filter(Boolean).join('-')
    head = `[${tag}]`
  }
  const tail = [nodeId || branchId, suffix].filter(Boolean).join(' ')
  return tail ? `${head} ${tail}` : head
}

/** 触发回合优雅收尾（exec.concludeTurn）的工具集合（与 Python tool_registry.py 同步）。 */
export const TURN_CONCLUDING_TOOLS = Object.freeze(new Set(contracts.turn_concluding_tools))

export function loadCoreRuntimeConfig(corePythonRoot) {
  const cfgPath = path.join(corePythonRoot, 'config.json')
  if (!fs.existsSync(cfgPath)) {
    throw new Error(`找不到核心运行时配置文件: ${cfgPath}`)
  }
  return JSON.parse(fs.readFileSync(cfgPath, 'utf8'))
}

export function loadRolePrompts(corePythonRoot) {
  const agentsDir = path.join(corePythonRoot, 'agents')
  /** @type {Record<string, string>} */
  const prompts = {}
  for (const role of CANONICAL_ROLES) {
    const fp = path.join(agentsDir, `${role}.md`)
    if (fs.existsSync(fp)) {
      prompts[role] = fs.readFileSync(fp, 'utf8')
    }
  }
  return prompts
}
