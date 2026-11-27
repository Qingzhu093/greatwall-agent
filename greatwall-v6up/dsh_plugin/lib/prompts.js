/**
 * GreatWall Agent v0.3 十大标准角色契约、44 个去重窄工具路由表与平台感知原生工具白名单。
 * 权威单一契约源位于 `core_python/mcp_server/tool_registry.py`，由跨层架构测试与 doctor 强制校验 100% 同步。
 * @module dsh-greatwall-v6up/prompts
 */
import fs from 'node:fs'
import path from 'node:path'

export const CANONICAL_ROLES = Object.freeze([
  'gw_chief',
  'supervisory_committee',
  'works_engineer',
  'explorer',
  'lineage_companion',
  'logistics_coordinator',
  'external_surveyor',
  'library_chronicler',
  'library_verifier',
  'conference_chair',
])

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

/** 10 角色授权 MCP 窄工具精确白名单（总去重 44 个，与 Python tool_registry.py 100% 一致）。 */
export const ROLE_MCP_TOOLS = Object.freeze({
  gw_chief: Object.freeze([
    'chief_get_overview_snapshot',
    'chief_trace_entity',
    'chief_get_wave_digest',
    'chief_preview_impact',
    'chief_propose_control_action',
  ]),
  explorer: Object.freeze([
    'run_isolated_eval',
    'get_living_survey',
    'query_library_catalog',
    'get_library_entry',
    'request_literature_survey',
    'read_lineage_graph',
    'handback_to_chief',
  ]),
  lineage_companion: Object.freeze([
    'get_living_survey',
    'query_library_catalog',
    'get_library_entry',
    'get_companion_context',
    'save_lineage_briefing',
    'record_reflection_and_unlock_pull',
    'submit_node_handoff',
    'submit_conference_statement',
  ]),
  logistics_coordinator: Object.freeze([
    'get_logistics_dashboard',
    'register_method_family',
    'triage_node',
    'fork_branch',
  ]),
  external_surveyor: Object.freeze([
    'get_survey_requests',
    'publish_external_literature_card',
  ]),
  library_chronicler: Object.freeze([
    'get_chronicler_snapshot',
    'publish_living_survey',
    'export_stage3_final_delivery',
  ]),
  conference_chair: Object.freeze([
    'get_conference_dossier',
    'record_conference_minutes',
    'submit_conference_verdict',
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
 * - `lineage_companion`: 只读 fs + search
 * - `external_surveyor`: 仅 web_search / web_fetch（唯一联网，零本地 fs 防院内泄露）
 * - `gw_chief` / `library_chronicler` / `conference_chair` / `logistics_coordinator` / `supervisory_committee`: `[]`（物理 0 原生工具）
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
export const TURN_CONCLUDING_TOOLS = Object.freeze(new Set([
  'save_lineage_briefing',
  'record_reflection_and_unlock_pull',
  'submit_node_handoff',
  'submit_conference_statement',
  'publish_living_survey',
  'export_stage3_final_delivery',
  'record_conference_minutes',
  'submit_conference_verdict',
  'submit_stage1_blind_ledger',
  'submit_stage2_unblind_verdict',
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
