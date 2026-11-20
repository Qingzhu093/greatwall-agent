/**
 * V6-Up (v2.2) 七大标准角色契约、31 窄工具角色路由表与运行时配置加载器。
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

/** 各角色默认思考强度映射（对齐 09 §3.2 ROLE_EFFORT_MAP）。 */
export const ROLE_EFFORT_MAP = Object.freeze({
  explorer: 'high',
  library_surveyor: 'high',
  library_verifier: 'high',
  lineage_companion: 'medium',
  works_engineer: 'medium',
  logistics_coordinator: 'low',
  supervisory_committee: 'low',
})

/** 每个角色专属的 3–5 个单一职责窄工具精确白名单（总计 31 个）。 */
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
    'register_question_domain_hook',
    'upgrade_hook_with_rqgm_gate',
    'recompute_stage_b_only',
    'update_skill_ledger',
  ]),
  supervisory_committee: Object.freeze([
    'get_supervisory_audit_snapshot',
    'check_stage2_closure_gate',
    'record_compliance_check',
    'register_saved_graph_query',
  ]),
})

export const ALL_31_MCP_TOOLS = Object.freeze(new Set(Object.values(ROLE_MCP_TOOLS).flat()))

/**
 * 7 大角色继承原生 DSH 工具允许清单：
 * - 空集合表示物理 0 原生工具（纯 DB / 纯文本角色），setup 内全部 deny。
 * - 非空集合仅作白名单交集过滤（再配合 sandbox guard 收紧目录范围）。
 */
export const ROLE_NATIVE_ALLOW_TOOLS = Object.freeze({
  explorer: Object.freeze([
    'read',
    'write',
    'edit',
    'read_image',
    'glob',
    'grep',
    'pwsh',
    'bash',
  ]),
  lineage_companion: Object.freeze([
    'read',
    'glob',
    'grep',
  ]),
  logistics_coordinator: Object.freeze([
    'read',
    'glob',
    'grep',
  ]),
  library_surveyor: Object.freeze([
    'read',
    'read_image',
    'glob',
    'grep',
    'web_search',
    'web_fetch',
  ]),
  library_verifier: Object.freeze([]),
  works_engineer: Object.freeze([
    'read',
    'write',
    'edit',
    'read_image',
    'glob',
    'grep',
    'pwsh',
    'bash',
  ]),
  supervisory_committee: Object.freeze([]),
})

export const ROLE_SHORT_LABELS = Object.freeze({
  explorer: '探索',
  lineage_companion: '伴随',
  logistics_coordinator: '后勤总管',
  library_surveyor: '图书馆采编',
  library_verifier: '图书馆盲审',
  works_engineer: '工造司',
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

/** 触发回合优雅收尾（exec.concludeTurn）的工具结果判定集合。 */
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
