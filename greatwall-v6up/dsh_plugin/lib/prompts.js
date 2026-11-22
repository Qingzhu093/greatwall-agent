/**
 * V6-Up (v3.0) 七大标准角色契约、31 窄工具角色路由表与平台感知原生工具白名单。
 * 零外部第三方依赖，直接从 ../core_python 权威资产直读。
 * @module dsh-greatwall-v6up/prompts
 */
import fs from 'node:fs'
import path from 'node:path'

export const CANONICAL_ROLES = Object.freeze([
  'explorer',
  'lineage_companion',
  'logistics_coordinator',
  'library_surveyor',
  'library_verifier',
  'works_engineer',
  'supervisory_committee',
])

/** 各角色默认思考强度映射（对齐 09 §5.1 ROLE_EFFORT_MAP）。 */
export const ROLE_EFFORT_MAP = Object.freeze({
  explorer: 'high',
  library_surveyor: 'high',
  library_verifier: 'high',
  lineage_companion: 'medium',
  works_engineer: 'medium',
  logistics_coordinator: 'low',
  supervisory_committee: 'low',
})

/** 每个角色专属的 3–5 个单一职责窄工具精确白名单（总计 31 个，100% 对齐 agent_kb/05 §0.2）。 */
export const ROLE_MCP_TOOLS = Object.freeze({
  explorer: Object.freeze([
    'run_isolated_eval',
    'query_library_catalog',
    'get_library_entry',
    'request_literature_survey',
    'read_lineage_graph',
  ]),
  lineage_companion: Object.freeze([
    'get_companion_context',
    'save_lineage_briefing',
    'record_reflection_and_unlock_pull',
    'submit_node_handoff',
  ]),
  logistics_coordinator: Object.freeze([
    'get_logistics_dashboard',
    'register_method_family',
    'triage_node',
    'fork_branch',
    'dispatch_stagnation_five_lanes',
  ]),
  library_surveyor: Object.freeze([
    'get_survey_requests',
    'publish_external_literature_card',
    'export_stage3_final_delivery',
  ]),
  library_verifier: Object.freeze([
    'get_blind_manuscript',
    'submit_stage1_blind_ledger',
    'get_unblinded_manuscript_and_peers',
    'submit_stage2_unblind_verdict',
    'propose_salvaged_lemma',
  ]),
  works_engineer: Object.freeze([
    'get_works_engineering_queue',
    'register_question_instrument',
    'upgrade_instrument_with_calibration',
    'recompute_stage_b_only',
    'update_skill_ledger',
    'resolve_works_ticket',
  ]),
  supervisory_committee: Object.freeze([
    'get_supervisory_audit_snapshot',
    'check_stage2_closure_gate',
    'record_compliance_check',
    'register_saved_graph_query',
  ]),
})

export const ALL_MCP_TOOLS = Object.freeze(new Set(Object.values(ROLE_MCP_TOOLS).flat()))
// 向后兼容导出名（现含 resolve_works_ticket 共 32 个窄工具）
export const ALL_31_MCP_TOOLS = ALL_MCP_TOOLS

/** 按宿主机平台解析 Shell 工具名（Windows -> pwsh，非 Windows -> bash）。 */
export function resolvePlatformShellTool(platform = process.platform) {
  return platform === 'win32' ? 'pwsh' : 'bash'
}

/**
 * 平台感知的 7 角色原生 DSH 工具允许清单（对齐 v3.0 沙箱平权矩阵）：
 * - `explorer` / `works_engineer`: 读写 fs + search + 平台 Shell
 * - `library_verifier`: 只读 fs + search + 平台 Shell（挂载独立空白盲审沙箱）
 * - `lineage_companion`: 只读 fs + search
 * - `library_surveyor`: 只读 fs + search + web
 * - `logistics_coordinator` / `supervisory_committee`: `[]`（物理 0 原生工具，纯 DB 驱动）
 * @param {string} role
 * @param {string} [platform]
 * @returns {string[]}
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
      return ['read', 'glob', 'grep']
    case 'library_surveyor':
      return ['read', 'read_image', 'glob', 'grep', 'web_search', 'web_fetch']
    case 'logistics_coordinator':
    case 'supervisory_committee':
    default:
      return []
  }
}

/** 当前运行平台的 7 角色静态白名单快照（向后兼容导出）。 */
export const ROLE_NATIVE_ALLOW_TOOLS = Object.freeze(
  Object.fromEntries(CANONICAL_ROLES.map((r) => [r, Object.freeze(resolvePlatformAllowedTools(r, process.platform))])),
)

export const ROLE_SHORT_LABELS = Object.freeze({
  explorer: '探索',
  lineage_companion: '伴随',
  logistics_coordinator: '后勤总管',
  library_surveyor: '图书馆采编',
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

/** 触发回合优雅收尾（exec.concludeTurn）的工具集合。 */
export const TURN_CONCLUDING_TOOLS = Object.freeze(new Set([
  'save_lineage_briefing',
  'record_reflection_and_unlock_pull',
  'submit_node_handoff',
  'submit_stage1_blind_ledger',
  'submit_stage2_unblind_verdict',
  'export_stage3_final_delivery',
  'record_compliance_check',
]))

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
