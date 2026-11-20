/**
 * V6-Up (v2.2) 无 Mock 真实 DSH `0.2.2-rc.3` SDK 端到端集成测试。
 *
 * - 直接从本机安装的 `@deepseek-ai/dsh` 依赖树加载真实的 Cordis、SessionStore、
 *   SessionProjectionRegistry、SessionQuerySqlite、SystemPrompt、ToolRuntime、TokenMeter、
 *   SkillRegistry、LlmRuntime、AgentRegistry、AgentLoop；
 * - 零 Mock 任何 DSH 内核 API；仅通过标准 `ctx.llm.registerAdapter` 挂载脚本化 `LlmAdapter`
 *   触发多轮真实 AgentLoop Turn、TokenUsage、ToolGuard、concludeTurn() 与闭环演进。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PLUGIN_DIR = path.resolve(__dirname, '..')
const CORE_PYTHON_DIR = path.resolve(PLUGIN_DIR, '..', 'core_python')

const DSH_NODE_MODULES = 'C:/Users/wangy/nodejs/node_modules/@deepseek-ai/dsh/node_modules'

async function importDshPkg(pkgName) {
  const parts = pkgName.split('/')
  const pkgDir = path.join(DSH_NODE_MODULES, ...parts)
  const pjson = JSON.parse(fs.readFileSync(path.join(pkgDir, 'package.json'), 'utf8'))
  const exp = pjson.exports?.['.']
  const rel = typeof exp === 'string' ? exp : (exp?.import || exp?.default || pjson.main || 'lib/index.js')
  return import(pathToFileURL(path.join(pkgDir, rel)).href)
}

const cordis = await importDshPkg('@deepseek-ai/cordis')
const sessionMod = await importDshPkg('@deepseek-ai/dsh-session')
const projMod = await importDshPkg('@deepseek-ai/dsh-session-projection')
const sqSqliteMod = await importDshPkg('@deepseek-ai/dsh-session-query-sqlite')
const sysPromptMod = await importDshPkg('@deepseek-ai/dsh-system-prompt')
const toolsMod = await importDshPkg('@deepseek-ai/dsh-tools')
const tokenMeterMod = await importDshPkg('@deepseek-ai/dsh-token-meter')
const skillMod = await importDshPkg('@deepseek-ai/dsh-skill')
const llmMod = await importDshPkg('@deepseek-ai/dsh-llm')
const agentMod = await importDshPkg('@deepseek-ai/dsh-agent')
const agentLoopMod = await importDshPkg('@deepseek-ai/dsh-agent-loop')
const dshScopeMod = await importDshPkg('@deepseek-ai/dsh-scope')
const subagentMod = await importDshPkg('@deepseek-ai/dsh-subagent')

const greatwallPlugin = await import(pathToFileURL(path.join(PLUGIN_DIR, 'lib/index.js')).href)

function registerDshNativeToolsOn(targetCtx) {
  const objOut = {
    schema: { type: 'object', additionalProperties: true },
    render(_args, value) {
      return [{ type: 'text', text: JSON.stringify(value) }]
    },
  }
  const disposers = [
    targetCtx.tools.register({
      name: 'read',
      description: 'Read local file text',
      parameters: { type: 'object', properties: { file_path: { type: 'string' } }, required: ['file_path'] },
      output: objOut,
      async execute(args) {
        const content = fs.readFileSync(String(args.file_path), 'utf8')
        return { ok: true, content }
      },
    }),
    targetCtx.tools.register({
      name: 'write',
      description: 'Write local file text',
      parameters: {
        type: 'object',
        properties: { file_path: { type: 'string' }, content: { type: 'string' } },
        required: ['file_path', 'content'],
      },
      output: objOut,
      async execute(args) {
        fs.mkdirSync(path.dirname(String(args.file_path)), { recursive: true })
        fs.writeFileSync(String(args.file_path), String(args.content), 'utf8')
        return { ok: true, written: String(args.file_path) }
      },
    }),
    targetCtx.tools.register({
      name: 'edit',
      description: 'Edit local file text',
      parameters: {
        type: 'object',
        properties: { file_path: { type: 'string' }, old_string: { type: 'string' }, new_string: { type: 'string' } },
        required: ['file_path', 'old_string', 'new_string'],
      },
      output: objOut,
      async execute(args) {
        const fp = String(args.file_path)
        const raw = fs.readFileSync(fp, 'utf8')
        fs.writeFileSync(fp, raw.replace(String(args.old_string), String(args.new_string)), 'utf8')
        return { ok: true, edited: fp }
      },
    }),
    targetCtx.tools.register({
      name: 'read_image',
      description: 'Read local image file',
      parameters: { type: 'object', properties: { file_path: { type: 'string' } }, required: ['file_path'] },
      output: objOut,
      async execute(args) {
        return { ok: true, image: String(args.file_path) }
      },
    }),
    targetCtx.tools.register({
      name: 'glob',
      description: 'Glob search files',
      parameters: { type: 'object', properties: { pattern: { type: 'string' }, path: { type: 'string' } }, required: ['pattern'] },
      output: objOut,
      async execute() {
        return { ok: true, files: [] }
      },
    }),
    targetCtx.tools.register({
      name: 'grep',
      description: 'Grep search files',
      parameters: { type: 'object', properties: { pattern: { type: 'string' }, path: { type: 'string' } }, required: ['pattern'] },
      output: objOut,
      async execute() {
        return { ok: true, matches: [] }
      },
    }),
    targetCtx.tools.register({
      name: 'pwsh',
      description: 'Run PowerShell snippet',
      parameters: { type: 'object', properties: { command: { type: 'string' }, description: { type: 'string' } }, required: ['command'] },
      output: objOut,
      async execute(args) {
        return { ok: true, command: String(args.command), stdout: 'pwsh-ok' }
      },
    }),
    targetCtx.tools.register({
      name: 'web_search',
      description: 'Search web literature',
      parameters: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] },
      output: objOut,
      async execute(args) {
        return { ok: true, query: String(args.query), results: [] }
      },
    }),
    targetCtx.tools.register({
      name: 'web_fetch',
      description: 'Fetch web URL',
      parameters: { type: 'object', properties: { url: { type: 'string' } }, required: ['url'] },
      output: objOut,
      async execute(args) {
        return { ok: true, url: String(args.url), content: '' }
      },
    }),
  ]
  return () => {
    for (const d of disposers) {
      try { d() } catch {}
    }
  }
}

class ScriptedTestLlmAdapter extends llmMod.LlmAdapter {
  constructor(handler) {
    super()
    this.handler = handler
  }
  providerInfo(provider) {
    return { id: provider, name: 'Test Scripted Provider' }
  }
  async listModels(provider) {
    return [{ provider, id: 'test-model', name: 'Test Model' }]
  }
  async resolveModel(provider, model) {
    return {
      provider,
      id: model,
      name: model,
      context: { contextWindow: 500_000 },
      defaultMaxTokens: 4096,
      inputModalities: ['text'],
      reasoning: {
        efforts: [
          { id: 'low', name: 'Low' },
          { id: 'medium', name: 'Medium' },
          { id: 'high', name: 'High' },
        ],
        defaultEffort: 'low',
      },
    }
  }
  async *stream(options) {
    const stepPlan = await this.handler(options)
    let idx = 0

    if (stepPlan.reasoning) {
      yield { type: 'block-start', index: idx, blockType: 'reasoning' }
      yield { type: 'reasoning-delta', index: idx, text: stepPlan.reasoning }
      yield { type: 'block-end', index: idx, block: { type: 'reasoning', text: stepPlan.reasoning } }
      idx++
    }

    if (stepPlan.text) {
      yield { type: 'block-start', index: idx, blockType: 'text' }
      yield { type: 'text-delta', index: idx, text: stepPlan.text }
      yield { type: 'block-end', index: idx, block: { type: 'text', text: stepPlan.text } }
      idx++
    }

    const toolCalls = stepPlan.toolCalls || []
    for (const tc of toolCalls) {
      const id = tc.id || `call_${crypto.randomUUID().slice(0, 8)}`
      const argsStr = JSON.stringify(tc.arguments || {})
      yield { type: 'block-start', index: idx, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: idx, id, name: tc.name, argumentsDelta: argsStr }
      yield { type: 'block-end', index: idx, block: { type: 'tool-call', id, name: tc.name, arguments: argsStr } }
      idx++
    }

    if (stepPlan.usage) {
      yield { type: 'usage', usage: stepPlan.usage }
    }
    yield {
      type: 'finish',
      reason: toolCalls.length > 0 ? { kind: 'tool-calls' } : { kind: 'stop' },
    }
  }
}

async function createRealDshHarness(tmpDir, adapterHandler) {
  const ctx = new cordis.Context()
  const fibers = [
    ctx.plugin(sessionMod.SessionStore),
    ctx.plugin(projMod.SessionProjectionRegistry),
    ctx.plugin(sqSqliteMod.default, { path: ':memory:', openAt: 'never' }),
    ctx.plugin(sysPromptMod.SystemPrompt, {
      personaPrefix: 'You are a coding agent powered by the {{model}} model.',
      personaSuffix: 'Your working directory is {{cwd}}.',
    }),
    ctx.plugin(toolsMod.ToolRuntime, { mode: 'native' }),
    ctx.plugin(tokenMeterMod.TokenMeter),
    ctx.plugin(skillMod.SkillRegistry),
    ctx.plugin(llmMod.LlmRuntime),
    ctx.plugin(agentMod.AgentRegistry),
    ctx.plugin(agentLoopMod.AgentLoop, { agents: [] }),
    ctx.plugin(subagentMod.SubagentRuntime),
    // 真实复现 dsh-web-app 的 AgentPresets 作用域：原生工具挂在 standing ancestor scope，通过 bindScopeParent 继承给子角色
    ctx.plugin(
      class TestAgentPresets extends cordis.Service {
        static inject = ['tools']
        constructor(pCtx) {
          super(pCtx, 'agentPresets')
          this.selfCtx = pCtx
          this.standing = new Map()
        }
        async resolve(presetName) {
          return { id: presetName }
        }
        async mount(agentCtx, presetName) {
          if (presetName !== 'standard' && !String(presetName).startsWith('greatwall-')) {
            return { id: presetName }
          }
          if (!this.standing.has(presetName)) {
            const key = { agentPreset: presetName }
            const scope = dshScopeMod.createScope(this.selfCtx, key)
            if (presetName !== 'greatwall-verifier') {
              scope.ctx.plugin({
                inject: ['tools'],
                apply(tCtx) {
                  registerDshNativeToolsOn(tCtx)
                },
              })
            }
            this.selfCtx.on('dispose', () => scope.dispose())
            this.standing.set(presetName, { key, scope })
          }
          const st = this.standing.get(presetName)
          const agentKey = dshScopeMod.scopeOf(agentCtx)
          dshScopeMod.bindScopeParent(agentKey, st.key)
          return { id: presetName }
        }
      },
    ),
    ctx.plugin(greatwallPlugin),
  ]

  await Promise.all(fibers)
  const unregisterAdapter = ctx.llm.registerAdapter(['test-provider'], new ScriptedTestLlmAdapter(adapterHandler))

  return {
    ctx,
    async cleanup() {
      unregisterAdapter()
      await ctx.fiber.dispose()
      void tmpDir
    },
  }
}

test('Real DSH SDK 0.2.2-rc.3 E2E: Zero-mock Orchestrator, Sandbox Guard, 37% Turn Gap & Stage 0-3 Closure', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_dsh_e2e_'))
  const wsRoot = path.join(tmpRoot, 'workspace')
  const dataDir = path.join(tmpRoot, 'external_data')
  fs.mkdirSync(wsRoot, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })
  let totalStreamCalls = 0

  // 记录各角色观察到的 tool schemas / system prompts / sandbox violations 与 blackbox 脱敏
  const observedByRole = {
    toolNamesByRole: {},
    systemTextsByRole: {},
    effortsByRole: {},
    explorerGuardViolations: [],
    surveyorGuardViolations: [],
    surveyorReadProblemOk: false,
    blackboxStrings: [],
    createdSessionHeaders: [],
  }

  // 脚本状态机 counters（按工具调用和消息追踪真实 DSH 对话流）
  const roleCounters = new Map()
  let createdBranchId = ''
  let createdNodeId = ''
  let createdWorktreeAbs = ''
  let createdObsId = ''
  let createdReviewId = ''
  let createdL3Id = ''
  let verifierStage1Done = false

  const harness = await createRealDshHarness(tmpRoot, async (options) => {
    const sysText = String(options.system || '')
    const toolNames = (options.tools || []).map((t) => t.name)
    const msgs = options.messages || []

    // 从系统与工具面辨识当前调度到的标准角色
    let role = 'unknown'
    if (toolNames.includes('register_question_domain_hook')) role = 'works_engineer'
    else if (toolNames.includes('record_compliance_check')) role = 'supervisory_committee'
    else if (toolNames.includes('register_method_family')) role = 'logistics_coordinator'
    else if (toolNames.includes('get_blind_manuscript')) role = 'library_verifier'
    else if (toolNames.includes('get_companion_context')) role = 'lineage_companion'
    else if (toolNames.includes('run_isolated_eval')) role = 'explorer'
    else if (toolNames.includes('publish_external_literature_card')) role = 'library_surveyor'

    observedByRole.toolNamesByRole[role] = toolNames
    observedByRole.systemTextsByRole[role] = sysText
    observedByRole.effortsByRole[role] = options.reasoningEffort

    const stepIdx = (roleCounters.get(role) || 0) + 1
    roleCounters.set(role, stepIdx)

    // 真实解析本对话的所有 user 文本与 tool-result JSON，避免 JSON.stringify 二次转义匹配失效
    const toolResultTexts = []
    const parsedResults = []
    const userPromptParts = []
    for (const m of msgs) {
      if (m.role === 'user' && Array.isArray(m.content)) {
        for (const b of m.content) {
          if (b?.type === 'text' && typeof b.text === 'string') {
            userPromptParts.push(b.text)
          } else if (b?.type === 'tool-result') {
            const raw = Array.isArray(b.content)
              ? b.content.map((c) => c?.text ?? '').join('\n')
              : String(b.content ?? '')
            toolResultTexts.push({ isError: Boolean(b.isError), text: raw })
            try {
              parsedResults.push(JSON.parse(raw))
            } catch {}
          }
        }
      }
    }
    const allUserText = userPromptParts.join('\n')
    const latestUserText = userPromptParts.length ? userPromptParts[userPromptParts.length - 1] : ''
    const allResultText = toolResultTexts.map((r) => r.text).join('\n')
    const hasToolDone = (name) => parsedResults.some((r) => r?.ok && r?.tool === name)
    totalStreamCalls += 1
    if (totalStreamCalls > 80) {
      throw new Error(`ScriptedTestLlmAdapter circuit breaker triggered at ${role}#${stepIdx} (errors=${toolResultTexts.filter((r)=>r.isError).map((r)=>r.text).join(' | ')})`)
    }

    if (role === 'works_engineer') {
      if (stepIdx === 1) {
        return {
          toolCalls: [
            {
              name: 'write',
              arguments: {
                file_path: path.join(wsRoot, 'evaluators', 'hook_q1.py'),
                content:
                  "def evaluate(stage_a_out, ctx):\n" +
                  "    v = float(stage_a_out.get('energy', 99.0))\n" +
                  "    return {'passed': v <= 1.05, 'metrics': {'comparable_rank_score': -abs(v - 1.0)}, 'details': 'ok'}\n",
              },
            },
            {
              name: 'write',
              arguments: {
                file_path: path.join(wsRoot, 'baselines', 'Q1', 'baseline.py'),
                content: 'BASELINE_E = 1.0\n',
              },
            },
          ],
        }
      }
      if (!hasToolDone('register_question_domain_hook')) {
        return {
          toolCalls: [
            {
              name: 'register_question_domain_hook',
              arguments: {
                question_id: 'Q1',
                hook_rel_path: 'evaluators/hook_q1.py',
                baseline_rel_path: 'baselines/Q1/baseline.py',
                fidelity_max_error_pct: 0.9,
              },
            },
          ],
        }
      }
      return { text: 'Works Engineer 钩子已注册。' }
    }

    if (role === 'supervisory_committee') {
      if (allUserText.includes('STAGE1_GATE')) {
        if (!hasToolDone('get_supervisory_audit_snapshot')) {
          return { toolCalls: [{ name: 'get_supervisory_audit_snapshot', arguments: {} }] }
        }
        if (!hasToolDone('record_compliance_check')) {
          return {
            toolCalls: [
              {
                name: 'record_compliance_check',
                arguments: {
                  stage: 'STAGE1_GATE',
                  status: 'PASSED',
                  blocking_questions_zero_l3: [],
                  unread_citation_nodes: [],
                  notes: 'Q1 钩子与基线均合格。',
                },
              },
            ],
          }
        }
      }
      if (allUserText.includes('STAGE2_CLOSURE_GATE') && !hasToolDone('record_compliance_check')) {
        return {
          toolCalls: [
            {
              name: 'record_compliance_check',
              arguments: {
                stage: 'STAGE2_CLOSURE_GATE',
                status: 'PASSED',
                blocking_questions_zero_l3: [],
                unread_citation_nodes: [],
                notes: 'Q1 已有 L3_VERIFIED，准予结题。',
              },
            },
          ],
        }
      }
      if (allUserText.includes('STAGE3_FINAL_AUDIT') && !hasToolDone('record_compliance_check')) {
        return {
          toolCalls: [
            {
              name: 'record_compliance_check',
              arguments: {
                stage: 'STAGE3_FINAL_AUDIT',
                status: 'PASSED',
                blocking_questions_zero_l3: [],
                unread_citation_nodes: [],
                notes: 'Stage 3 五件套终审合格。',
              },
            },
          ],
        }
      }
      return { text: 'Supervisory check done.' }
    }

    if (role === 'logistics_coordinator') {
      if (!createdNodeId) {
        if (!hasToolDone('register_method_family')) {
          return {
            toolCalls: [
              {
                name: 'register_method_family',
                arguments: {
                  question_id: 'Q1',
                  family_id: 'fam_symp',
                  mechanism_signature: '对称辛离散演化方案。',
                  orthogonal_contrast: '对比传统显式欧拉步进。',
                },
              },
            ],
          }
        }
        if (!hasToolDone('fork_branch')) {
          return {
            toolCalls: [
              {
                name: 'fork_branch',
                arguments: {
                  question_id: 'Q1',
                  fork_mode: 'orthogonal',
                  target_family_id: 'fam_symp',
                },
              },
            ],
          }
        }
        const forkRes = parsedResults.find((r) => r?.ok && r?.tool === 'fork_branch')
        if (forkRes?.data) {
          createdNodeId = forkRes.data.node_id
          createdBranchId = forkRes.data.branch_id
          createdWorktreeAbs = forkRes.data.worktree_abs_path
        }
        return { text: `已开辟探索节点 ${createdNodeId}` }
      }
      // 分诊流程
      if (!hasToolDone('get_logistics_dashboard')) {
        return {
          toolCalls: [{ name: 'get_logistics_dashboard', arguments: { question_id: 'ALL' } }],
        }
      }
      if (!hasToolDone('triage_node')) {
        return {
          toolCalls: [
            {
              name: 'triage_node',
              arguments: {
                node_id: createdNodeId,
                triage_level: 'LEVEL_1',
                action: 'SUBMIT_BLIND_REVIEW',
                rationale: '实测能量达到收敛标准，送异会话盲审。',
              },
            },
          ],
        }
      }
      const trRes = parsedResults.find((r) => r?.ok && r?.tool === 'triage_node')
      if (trRes?.data?.created_review_id) createdReviewId = trRes.data.created_review_id
      return { text: `分诊送审 ${createdReviewId}` }
    }

    if (role === 'lineage_companion') {
      if (allUserText.includes('黑匣子') || sysText.includes('黑匣子')) {
        observedByRole.blackboxStrings.push(allUserText + '\n' + sysText)
      }
      if (allUserText.includes('PRE_SPAWN')) {
        if (!hasToolDone('save_lineage_briefing')) {
          return {
            toolCalls: [
              {
                name: 'save_lineage_briefing',
                arguments: {
                  branch_id: createdBranchId,
                  node_id: createdNodeId,
                  sec1_mechanism: '辛保结构能量守恒求解',
                  sec2_verified_baseline: '基线参照 E=1.0',
                  sec3_bottleneck: '需确认步长取值下的误差',
                  sec4_dead_ends: '无',
                  sec5_immediate_will: '先读本工作树并运行 run_isolated_eval',
                },
              },
            ],
          }
        }
      } else if (allUserText.includes('REFLECT_37')) {
        if (!hasToolDone('get_companion_context')) {
          return {
            toolCalls: [
              {
                name: 'get_companion_context',
                arguments: { branch_id: createdBranchId, node_id: createdNodeId, mode: 'REFLECT_37' },
              },
            ],
          }
        }
        if (!allUserText.includes('[探索者 Round 1 回答]')) {
          return { text: '请围绕 Attractor Tasks 解释：当前 symp 解法的 energy=1.01 是否存在人为步长吸引子偏移？（<=100字）' }
        }
        return {
          toolCalls: [
            {
              name: 'record_reflection_and_unlock_pull',
              arguments: {
                node_id: createdNodeId,
                selected_categories: ['7. Attractor Tasks'],
                holiday_prompt_id: 3,
                turns: [
                  { question: '是否存在吸引子固着？', answer: '已确认物理误差真实收敛，非硬编码过拟合。' },
                ],
                verdict_3state: 'SUFFICIENT_EVIDENCE',
              },
            },
          ],
        }
      } else if (allUserText.includes('HANDOFF_70')) {
        if (!hasToolDone('get_companion_context')) {
          return {
            toolCalls: [
              {
                name: 'get_companion_context',
                arguments: { branch_id: createdBranchId, node_id: createdNodeId, mode: 'HANDOFF_70' },
              },
            ],
          }
        }
        return {
          toolCalls: [
            {
              name: 'submit_node_handoff',
              arguments: {
                node_id: createdNodeId,
                branch_id: createdBranchId,
                question_id: 'Q1',
                column_a_facts_md: `依据 [${createdObsId}] 实测能量=1.01 <= 1.05。`,
                column_b_hypothesis_md: '本辛算法稳定满足能量界限，建议提交盲审。',
                will_md: '提交后勤 Level 1 盲审入库。',
                obs_ids: [createdObsId],
                candidate_rel_path: 'src/solver.py',
              },
            },
          ],
        }
      }
      return { text: 'Companion finished.' }
    }

    if (role === 'explorer') {
      // Step 1: 故意尝试方案 A 红线攻击（读取外部 DB + 写入 HANDOFF.md + pwsh 上跳），验证 Guard 实锤拦截！
      if (stepIdx === 1) {
        return {
          reasoning: 'SECRET_COT_NEVER_LEAK_IN_BLACKBOX',
          toolCalls: [
            { name: 'read', arguments: { file_path: path.join(dataDir, 'greatwall.db') } },
            { name: 'write', arguments: { file_path: path.join(createdWorktreeAbs, 'HANDOFF.md'), content: 'bad' } },
            { name: 'pwsh', arguments: { command: 'Get-Content ..\\..\\external_data\\greatwall.db' } },
          ],
        }
      }
      // Step 2: 收集刚才的 3 个 Guard 拒绝证明，并在自己 worktree 合法写代码 + 执行本分支 pwsh + 注入 186,000 token usage
      if (stepIdx === 2) {
        observedByRole.explorerGuardViolations.push(...toolResultTexts.filter((r) => r.isError).map((r) => r.text))
        return {
          reasoning: 'SECRET_COT_STEP2_DO_NOT_LEAK',
          toolCalls: [
            {
              name: 'write',
              arguments: {
                file_path: path.join(createdWorktreeAbs, 'src', 'solver.py'),
                content: "def run(public_input):\n    return {'energy': 1.01}\n",
              },
            },
            {
              name: 'pwsh',
              arguments: { command: 'python --version' },
            },
          ],
          usage: { inputTokens: 186_000, outputTokens: 1_200, totalTokens: 187_200 },
        }
      }
      // Step 3: 此时 DSH TokenMeter 已含 >=186,000 tokens，调 run_isolated_eval 触发 REFLECT_37 + exec.concludeTurn()！
      if (!allUserText.includes('37–70%') && !hasToolDone('run_isolated_eval')) {
        return {
          toolCalls: [
            {
              name: 'run_isolated_eval',
              arguments: {
                node_id: createdNodeId,
                question_id: 'Q1',
                candidate_rel_path: 'src/solver.py',
                linguistic_prediction: '对称辛求解器预测能量 <= 1.05。',
              },
            },
          ],
        }
      }
      const ev1 = parsedResults.find((r) => r?.ok && r?.tool === 'run_isolated_eval')
      if (ev1?.data?.obs_id) createdObsId = ev1.data.obs_id

      // 37% 真实两轮对话期间只读回答 companion 质询（仅匹配最新 user 质询消息）
      if (latestUserText.includes('[伴随助手 37% 质询 Round')) {
        return { text: '已在当前数值域交叉验证不同步长，energy=1.01 真实收敛且无硬编码兜底。' }
      }

      // Step 4 (37% 解锁后续跑)：调 query_library_catalog(ALL) 验证已解锁，且写入 356,000 usage 预备 70%
      if (!hasToolDone('query_library_catalog')) {
        return {
          toolCalls: [
            {
              name: 'query_library_catalog',
              arguments: { node_id: createdNodeId, question_id: 'Q1', scope: 'ALL' },
            },
          ],
          usage: { inputTokens: 356_000, outputTokens: 1_200, totalTokens: 357_200 },
        }
      }
      // Step 5：用 357k 水位再评估新候选（触发 HANDOFF_70 + exec.concludeTurn()！）
      const evalResults = parsedResults.filter((r) => r?.ok && r?.tool === 'run_isolated_eval')
      if (evalResults.length < 2) {
        return {
          toolCalls: [
            {
              name: 'write',
              arguments: {
                file_path: path.join(createdWorktreeAbs, 'src', 'solver.py'),
                content: "def run(public_input):\n    return {'energy': 1.005}\n",
              },
            },
            {
              name: 'run_isolated_eval',
              arguments: {
                node_id: createdNodeId,
                question_id: 'Q1',
                candidate_rel_path: 'src/solver.py',
                linguistic_prediction: '精调步长后预期能量进一步收敛到 1.005。',
              },
            },
          ],
        }
      }
      const evLatest = evalResults[evalResults.length - 1]
      if (evLatest?.data?.obs_id) createdObsId = evLatest.data.obs_id
      return { text: 'Explorer turn concluded.' }
    }

    if (role === 'library_verifier') {
      if (allUserText.includes('STAGE3_COMPARATOR')) {
        if (!hasToolDone('get_unblinded_manuscript_and_peers')) {
          return {
            toolCalls: [{ name: 'get_unblinded_manuscript_and_peers', arguments: { review_id: 'STAGE3_COMPARATOR' } }],
          }
        }
        return { text: 'Stage 3 Comparator 择优推荐完毕：Q1 最优为当前活跃 L3 条目。' }
      }
      if (!verifierStage1Done && !hasToolDone('get_blind_manuscript')) {
        return { toolCalls: [{ name: 'get_blind_manuscript', arguments: { review_id: createdReviewId } }] }
      }
      if (!verifierStage1Done) {
        verifierStage1Done = true
        return {
          toolCalls: [
            {
              name: 'submit_stage1_blind_ledger',
              arguments: {
                review_id: createdReviewId,
                question_id: 'Q1',
                ledger_items: [
                  { claim: 'energy <= 1.05', evidence_location_and_quote: `${createdObsId}: energy converged`, is_verified: true },
                ],
                stage1_verdict: 'PASS',
              },
            },
          ],
        }
      }
      if (!hasToolDone('get_unblinded_manuscript_and_peers')) {
        return {
          toolCalls: [{ name: 'get_unblinded_manuscript_and_peers', arguments: { review_id: createdReviewId } }],
        }
      }
      return {
        toolCalls: [
          {
            name: 'submit_stage2_unblind_verdict',
            arguments: {
              review_id: createdReviewId,
              final_verdict: 'PASS',
              title: '[Q1] 对称辛几何收敛定式',
              abstract_md: '在真实 DSH 无 Mock 编排下验证对称辛解法稳定达到能量界限 <=1.05，完整过 Stage 1 与 Stage 2 盲审。',
              exact_verified_scope_md: '适用于 Q1 标准基线对称区间。',
            },
          },
        ],
      }
    }

    if (role === 'library_surveyor') {
      if (allUserText.includes('Stage 1 开局外藏建设')) {
        if (!hasToolDone('publish_external_literature_card')) {
          return {
            toolCalls: [
              {
                name: 'publish_external_literature_card',
                arguments: {
                  ref_id: 'R001',
                  question_id: 'Q1',
                  title: 'Symplectic Euler & Verlet Long-Time Energy Conservation',
                  abstract_md: '本文严格证明四阶辛积分方法在哈密顿系统长时演进中可将修正哈密顿量能量振幅保持在有界误差范围内，并给出明确稳定性上界条件。',
                  exact_preconditions_md: '光滑可分哈密顿系统且步长满足线性稳定阈值。',
                  formulas_or_operators_md: 'Phi_dt = exp(dt/2 D_T) exp(dt D_V) exp(dt/2 D_T)',
                  read_depth: 'full_text',
                  support_scope: 'DIRECT_PROOF_OR_EXACT_MEASUREMENT',
                  source_citation: 'Hairer et al., Geometric Numerical Integration, 2006',
                },
              },
            ],
          }
        }
        return { text: 'Stage 1 外藏 [R001] 建卡完成。' }
      }
      if (toolResultTexts.length > 0 && !observedByRole.surveyorReadProblemOk) {
        observedByRole.surveyorReadProblemOk = parsedResults.some((r) => r?.ok && String(r?.content || '').includes('Symplectic'))
        observedByRole.surveyorGuardViolations.push(...toolResultTexts.filter((r) => r.isError).map((r) => r.text))
      }
      if (toolResultTexts.length === 0) {
        return {
          toolCalls: [
            { name: 'read', arguments: { file_path: path.join(wsRoot, 'problem_pack', 'PROBLEM.md') } },
            { name: 'read', arguments: { file_path: path.join(dataDir, 'greatwall.db') } },
          ],
        }
      }
      if (!hasToolDone('get_survey_requests')) {
        return { toolCalls: [{ name: 'get_survey_requests', arguments: { question_id: 'ALL' } }] }
      }
      const srRes = parsedResults.find((r) => r?.ok && r?.tool === 'get_survey_requests')
      const l3List = srRes?.data?.stage3_synthesis_bundle?.l3_verified || []
      if (l3List.length > 0) createdL3Id = l3List[0].entry_id
      return {
        toolCalls: [
          {
            name: 'export_stage3_final_delivery',
            arguments: {
              formal_paper_md:
                `# Q1 正式科研结题报告（V6-Up v2.2 真实 DSH SDK 闭环验证）\n\n` +
                `## 一、核心结论摘要\n` +
                `基于经过 Stage 1 不可逆证据账本与 Stage 2 独立盲审终审的黄金结论 [${createdL3Id || 'L3-001'}]，` +
                `对称辛几何离散算法在标准基准测试下取得严格数值能量收敛（实测 energy <= 1.05）。\n`,
              selected_l3_ids_by_question: { Q1: [createdL3Id || 'L3-001'] },
              reproduction_candidate_nodes: [createdNodeId],
            },
          },
        ],
      }
    }

    void allResultText
    return { text: 'Done.' }
  })

  try {
    // 准备只读题面资料用于验证 library_surveyor 可读 problem_pack 且禁读 greatwall.db
    fs.mkdirSync(path.join(wsRoot, 'problem_pack'), { recursive: true })
    fs.writeFileSync(path.join(wsRoot, 'problem_pack', 'PROBLEM.md'), '# Q1 Symplectic Energy Problem\n', 'utf8')

    // 验证插件服务与技能包已装配
    assert.ok(harness.ctx.greatwall, 'ctx.greatwall 服务应已挂载')
    assert.equal(harness.ctx.greatwall.canonicalRoles.length, 7)

    // 创建模拟桌面主对话会话作为 parentAgent，验证顶部子 Agent 监视窗父子血统恢复
    const parentHandle = await harness.ctx.agents.create({
      sessionId: 'root_desktop_parent',
      meta: { cwd: wsRoot, isSeeded: false },
      agentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
    })

    const ctrl = harness.ctx.greatwall.createSessionController({
      workspaceRoot: wsRoot,
      dataDir,
      parentAgent: parentHandle.agent,
      defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
    })
    t.after(async () => {
      try { await ctrl.dispose() } catch {}
      try { await parentHandle.dispose() } catch {}
      try { await harness.cleanup() } catch {}
      try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
    })

    try {
      const initRes = await ctrl.initEpoch({
        goalMd: '无 Mock 真实 DSH 验证 Q1',
        requiredQuestions: ['Q1'],
        stage: 'STAGE1_PARSE0',
      })
      assert.equal(initRes.ok, true)

      const disposeCreatedSpy = harness.ctx.on('agent/created', ({ agent }) => {
        if (agent?.id?.startsWith('gw_')) {
          observedByRole.createdSessionHeaders.push({
            id: agent.id,
            cwd: agent.session?.header?.cwd,
            origin: agent.session?.header?.origin,
            agentPreset: agent.session?.header?.agentPreset,
          })
        }
      })
      let runRes
      try {
        runRes = await ctrl.runUntilClosed({ maxCycles: 16 })
      } finally {
        disposeCreatedSpy()
      }
      assert.equal(runRes.closed, true, `预期 Stage 3 彻底闭环 CLOSED，实测状态: ${JSON.stringify(runRes.snapshot)}`)

      // 0. 验证 Round 4 同工作区独立会话路线：摘除假 subagent 壳，统一 meta.cwd = wsRoot，无 retainedUiDisposers 内存队列
      assert.ok(observedByRole.createdSessionHeaders.length >= 6, `预期至少 6 个真实独立会话节点，实测 ${observedByRole.createdSessionHeaders.length}`)
      for (const s of observedByRole.createdSessionHeaders) {
        assert.notEqual(s.origin, 'subagent', '不得再伪装 origin=subagent')
        assert.equal(path.resolve(s.cwd || ''), path.resolve(wsRoot), '所有节点 meta.cwd 必须为主工作区以允许 attachSession')
        assert.ok(String(s.agentPreset || '').startsWith('greatwall-'), `应声明专用 greatwall-* preset，实得 ${s.agentPreset}`)
      }

      // 1. 验证 preset mount + 工具严格隔离：
      //    - 0 原生工具角色 (library_verifier, supervisory_committee) 精确为 0 个原生工具
      //    - works_engineer / explorer 精确拥有本地 fs + pwsh + 各自 MCP 工具
      //    - lineage_companion / logistics_coordinator 拥有只读 read/glob/grep + MCP（不含 write/edit/pwsh）
      //    - library_surveyor 拥有只读 + Web 工具 (read, read_image, glob, grep, web_search, web_fetch)
      assert.deepEqual(
        observedByRole.toolNamesByRole.library_verifier.sort(),
        harness.ctx.greatwall.roleMcpTools.library_verifier.slice().sort(),
      )
      assert.deepEqual(
        observedByRole.toolNamesByRole.lineage_companion.slice().sort(),
        [...harness.ctx.greatwall.roleMcpTools.lineage_companion, 'read', 'glob', 'grep'].sort(),
      )
      assert.deepEqual(
        observedByRole.toolNamesByRole.logistics_coordinator.slice().sort(),
        [...harness.ctx.greatwall.roleMcpTools.logistics_coordinator, 'read', 'glob', 'grep'].sort(),
      )
      for (const expectedTool of ['read', 'write', 'edit', 'read_image', 'glob', 'grep', 'pwsh']) {
        assert.ok(observedByRole.toolNamesByRole.works_engineer.includes(expectedTool), `works_engineer 缺少 ${expectedTool}`)
        assert.ok(observedByRole.toolNamesByRole.explorer.includes(expectedTool), `explorer 缺少 ${expectedTool}`)
      }
      assert.ok(!observedByRole.toolNamesByRole.works_engineer.includes('web_search'))
      assert.ok(!observedByRole.toolNamesByRole.explorer.includes('web_search'))

      for (const expectedTool of ['read', 'read_image', 'glob', 'grep', 'web_search', 'web_fetch']) {
        assert.ok(observedByRole.toolNamesByRole.library_surveyor.includes(expectedTool), `library_surveyor 缺少 ${expectedTool}`)
      }
      for (const forbiddenTool of ['write', 'edit', 'pwsh']) {
        assert.ok(!observedByRole.toolNamesByRole.library_surveyor.includes(forbiddenTool), `library_surveyor 不应拥有 ${forbiddenTool}`)
      }
      assert.equal(observedByRole.surveyorReadProblemOk, true, 'library_surveyor 应可只读 problem_pack/PROBLEM.md')
      assert.ok(observedByRole.surveyorGuardViolations.some((t) => t.includes('SANDBOX_VIOLATION')), 'library_surveyor 读隔离库应触发 SANDBOX_VIOLATION')

      assert.ok(observedByRole.toolNamesByRole.explorer.includes('run_isolated_eval'))

      // 2. 验证 system-prompt 洗净了通用编程助理前缀
      assert.ok(!observedByRole.systemTextsByRole.explorer.includes('You are a coding agent'))
      assert.ok(!observedByRole.systemTextsByRole.library_verifier.includes('You are a coding agent'))

      // 2.5 验证 09 §3.2 ROLE_EFFORT_MAP 严格覆盖了根会话 default 'low'
      assert.equal(observedByRole.effortsByRole.explorer, 'high')
      assert.equal(observedByRole.effortsByRole.library_surveyor, 'high')
      assert.equal(observedByRole.effortsByRole.library_verifier, 'high')
      assert.equal(observedByRole.effortsByRole.lineage_companion, 'medium')
      assert.equal(observedByRole.effortsByRole.works_engineer, 'medium')
      assert.equal(observedByRole.effortsByRole.logistics_coordinator, 'low')
      assert.equal(observedByRole.effortsByRole.supervisory_committee, 'low')

      // 3. 验证方案 A Guard 同步拦截了 3 类越权攻击 + 写入 FACT_LOG
      assert.equal(observedByRole.explorerGuardViolations.length, 3)
      assert.ok(observedByRole.explorerGuardViolations.some((t) => t.includes('SANDBOX_VIOLATION')))
      assert.ok(observedByRole.explorerGuardViolations.some((t) => t.includes('NO_MD_DOSSIER_POLICY')))

      // 4. 验证 Blackbox 投影严格剔除了 reasoning 思维链
      assert.ok(observedByRole.blackboxStrings.length >= 1)
      for (const bb of observedByRole.blackboxStrings) {
        assert.ok(!bb.includes('SECRET_COT_NEVER_LEAK_IN_BLACKBOX'))
        assert.ok(!bb.includes('SECRET_COT_STEP2_DO_NOT_LEAK'))
      }

      // 5. 验证工作区不存在任何过程 .md 公文（仅允许 final_delivery/01_formal_paper.md）
      assert.ok(fs.existsSync(path.join(wsRoot, 'final_delivery', '01_formal_paper.md')))
      assert.ok(!fs.existsSync(path.join(createdWorktreeAbs, 'HANDOFF.md')))

      // 6. 验证外部隔离 SQLite 中确实写入了真实 UNAUTHORIZED_TOOL_ATTEMPT & TokenMeter 压力 & 37%解锁 & L3_VERIFIED
      const pyInspect = execFileSync(
        'python',
        [
          '-c',
          `import sqlite3, json; from mcp_server.db_schema import resolve_storage_paths; ` +
          `dbp = resolve_storage_paths(r'${wsRoot}')['db_path']; ` +
          `c = sqlite3.connect(dbp); ` +
          `print(json.dumps({` +
          `'db_path': str(dbp),` +
          `'unauth': c.execute("SELECT COUNT(*) FROM epistemic_edges WHERE edge_track='FACT_LOG' AND edge_type='UNAUTHORIZED_TOOL_ATTEMPT'").fetchone()[0],` +
          `'pressure': c.execute("SELECT pressure_tokens, first_reflection_unlocked FROM lineage_nodes WHERE node_id=?", (r'${createdNodeId}',)).fetchone(),` +
          `'l3': c.execute("SELECT COUNT(*) FROM internal_research_ledger WHERE ledger_type='L3_VERIFIED'").fetchone()[0]` +
          `}))`,
        ],
        {
          encoding: 'utf8',
          env: {
            ...process.env,
            PLUGIN_DATA: dataDir,
            GREATWALL_DATA_DIR: dataDir,
            PYTHONPATH: CORE_PYTHON_DIR,
          },
        },
      )
      const dbMetrics = JSON.parse(pyInspect.trim())
      assert.ok(dbMetrics.db_path.toLowerCase().startsWith(dataDir.toLowerCase()), `SQLite 数据库必须外部隔离存放于 dataDir，实得 ${dbMetrics.db_path}`)
      assert.ok(dbMetrics.unauth >= 3, `预期 >=3 条 UNAUTHORIZED_TOOL_ATTEMPT，实测 ${dbMetrics.unauth}`)
      assert.ok(Array.isArray(dbMetrics.pressure), `未找到节点 ${createdNodeId}，dbMetrics=${JSON.stringify(dbMetrics)}`)
      assert.ok(dbMetrics.pressure[0] >= 350_000, `预期 TokenMeter 同步到 >=350000，实测 ${dbMetrics.pressure[0]}`)
      assert.equal(dbMetrics.pressure[1], 1, '预期 37% 反思已设置 first_reflection_unlocked=1')
      assert.equal(dbMetrics.l3, 1, '预期 Q1 已产生 1 条 L3_VERIFIED')

      // 7. 验证入口工具 greatwall_orchestrate status 返回实时状态与遥测文件已生成
      const orchTool = harness.ctx.tools.get('greatwall_orchestrate')
      assert.ok(orchTool, '应注册入口工具 greatwall_orchestrate')
      const statusOut = await orchTool.execute({ action: 'status', workspace_root: wsRoot }, { agent: parentHandle.agent })
      assert.equal(statusOut.ok, true)
      assert.ok(fs.existsSync(statusOut.telemetry.telemetryFile), '应生成 epoch_telemetry_summary.json')
    } finally {
      await ctrl.dispose()
      assert.equal(ctrl.orchestrator.liveSessions.size, 0)
      await parentHandle.dispose()
    }
  } finally {
    await harness.cleanup()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('Desktop Profile Mount & Cordis Bundle Patch Verification (No {{cwd}}, 500k Window, Symlink Resolve)', async () => {
  const desktopPkg = 'C:/Users/wangy/.dsh/profiles/desktop/package.json'
  assert.ok(fs.existsSync(desktopPkg), '桌面 Profile package.json 应存在')
  const desktopJson = JSON.parse(fs.readFileSync(desktopPkg, 'utf8'))
  assert.ok(desktopJson?.dsh?.profile?.bundles?.includes('dsh-greatwall-v6up'), 'bundles 列表必须包含 dsh-greatwall-v6up')

  const reqFromDesktop = createRequire(desktopPkg)
  const resolvedEntry = reqFromDesktop.resolve('dsh-greatwall-v6up')
  assert.equal(
    fs.realpathSync(resolvedEntry).toLowerCase(),
    fs.realpathSync(path.join(PLUGIN_DIR, 'lib', 'index.js')).toLowerCase(),
  )

  const patchPath = reqFromDesktop.resolve('dsh-greatwall-v6up/cordis.patch.yml')
  const patchRaw = fs.readFileSync(patchPath, 'utf8')
  assert.ok(!patchRaw.includes('{{cwd}}'), '严禁残留 {{cwd}}')
  assert.ok(!patchRaw.includes('178500'), '严禁残留错误 178500 窗口数')
  assert.ok(!patchRaw.includes('compaction-basic'), '严禁包含 compaction-basic')
  assert.ok(!patchRaw.includes('skill-filesystem'), '严禁包含 skill-filesystem')

  const yamlMod = await importDshPkg('js-yaml')
  const includeMod = await importDshPkg('@deepseek-ai/cordis-plugin-include')
  const parsedPatch = yamlMod.load(patchRaw, { schema: includeMod.entryListSchema })
  assert.ok(Array.isArray(parsedPatch) && parsedPatch[0]?.insert?.[0])
  const row = parsedPatch[0].insert[0]
  assert.equal(row.name, 'dsh-greatwall-v6up')
  assert.equal(row.config.contextWindowTokens, 500000)
  const presetRows = parsedPatch[0].insert.filter((r) => r.name === '@deepseek-ai/dsh-agent-preset')
  assert.deepEqual(
    presetRows.map((r) => r.config?.id).sort(),
    ['greatwall-companion', 'greatwall-explorer', 'greatwall-governance', 'greatwall-verifier', 'greatwall-works'],
  )

  // 用真实 DSH Context + Patch Config 实测可一次启动且无任何报错
  const ctx = new cordis.Context()
  await Promise.all([
    ctx.plugin(sessionMod.SessionStore),
    ctx.plugin(projMod.SessionProjectionRegistry),
    ctx.plugin(sqSqliteMod.default, { path: ':memory:', openAt: 'never' }),
    ctx.plugin(sysPromptMod.SystemPrompt, { personaPrefix: 'p', personaSuffix: 's' }),
    ctx.plugin(toolsMod.ToolRuntime, { mode: 'native' }),
    ctx.plugin(tokenMeterMod.TokenMeter),
    ctx.plugin(skillMod.SkillRegistry),
    ctx.plugin(llmMod.LlmRuntime),
    ctx.plugin(agentMod.AgentRegistry),
    ctx.plugin(agentLoopMod.AgentLoop, { agents: [] }),
    ctx.plugin(subagentMod.SubagentRuntime),
    ctx.plugin(await import(pathToFileURL(resolvedEntry).href), row.config),
  ])
  try {
    assert.ok(ctx.greatwall, '通过 Desktop 软链入口和 Patch Config 挂载后必须激活 ctx.greatwall')
    assert.equal(ctx.greatwall.config.contextWindowTokens, 500000)
    assert.ok(ctx.tools.get('greatwall_orchestrate'), '桌面主会话应拥有入口工具 greatwall_orchestrate')
    const sopSkill = await ctx.skills.get('greatwall-research-loop')
    assert.ok(sopSkill && sopSkill.name === 'greatwall-research-loop', 'SkillRegistry 应成功挂载核心科研 SOP 技能 greatwall-research-loop')
  } finally {
    await ctx.fiber.dispose()
  }
})

test('Async Background Control (1s start, Immune to Caller exec.signal Timeout, Graceful Stop)', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_async_e2e_'))
  const wsRoot = path.join(tmpRoot, 'workspace')
  const dataDir = path.join(tmpRoot, 'external_data')
  fs.mkdirSync(wsRoot, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

  let subCallStarted = false
  let signalObserved = false
  const harness = await createRealDshHarness(tmpRoot, async (options) => {
    subCallStarted = true
    await new Promise((resolve) => {
      const timer = setTimeout(resolve, 10_000)
      options.signal?.addEventListener(
        'abort',
        () => {
          signalObserved = true
          clearTimeout(timer)
          resolve()
        },
        { once: true },
      )
    })
    return { text: 'stopped-gracefully' }
  })

  try {
    const parentHandle = await harness.ctx.agents.create({
      sessionId: 'root_async_parent',
      meta: { cwd: wsRoot, isSeeded: false },
      agentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
    })
    const ctrl = harness.ctx.greatwall.createSessionController({
      workspaceRoot: wsRoot,
      dataDir,
      parentAgent: parentHandle.agent,
      defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
    })
    t.after(async () => {
      try { await ctrl.dispose() } catch {}
      try { await parentHandle.dispose() } catch {}
      try { await harness.cleanup() } catch {}
      try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
    })

    const orchTool = harness.ctx.tools.get('greatwall_orchestrate')
    await orchTool.execute(
      { action: 'init', workspace_root: wsRoot, required_questions: ['Q1'], goal_md: '异步免疫 600s 超时测试' },
      { agent: parentHandle.agent },
    )

    // 传入调用方的 AbortController，验证 start 1s 内立刻返回，且即使随后触发外部 abort() 也不误杀后台任务！
    const callerTimeoutCtrl = new AbortController()
    const tStart = Date.now()
    const startRes = await orchTool.execute(
      { action: 'start', workspace_root: wsRoot },
      { agent: parentHandle.agent, signal: callerTimeoutCtrl.signal },
    )
    assert.equal(startRes.ok, true)
    assert.equal(startRes.started, true)
    assert.ok(Date.now() - tStart < 1500, 'greatwall_orchestrate(action="start") 必须在 1s 左右立即返回')

    const deadlineMs = Date.now() + 3000
    while (!subCallStarted && Date.now() < deadlineMs) {
      await new Promise((r) => setTimeout(r, 30))
    }
    assert.equal(subCallStarted, true, '后台异步事件池应已拉起子角色')

    // 模拟外部 600s 超时 Abort（连坐攻击）：后台子角色绝不能被中止！
    callerTimeoutCtrl.abort(new Error('SIMULATED_600S_CALLER_TIMEOUT'))
    await new Promise((r) => setTimeout(r, 120))
    assert.equal(signalObserved, false, '后台调度池不得绑定调用方 exec.signal，外部超时绝不可连坐杀死子角色！')

    const statusDuring = await orchTool.execute(
      { action: 'status', workspace_root: wsRoot },
      { agent: parentHandle.agent },
    )
    assert.equal(statusDuring.ok, true)
    assert.equal(statusDuring.poolState, 'running')

    // 唯有显式调用 action='stop' 才优雅中止后台循环与运行中子会话
    const t0 = Date.now()
    const stopRes = await orchTool.execute(
      { action: 'stop', workspace_root: wsRoot },
      { agent: parentHandle.agent },
    )
    const elapsedMs = Date.now() - t0

    assert.equal(stopRes.ok, true)
    assert.equal(stopRes.stopped, true)
    assert.equal(signalObserved, true, '显式 stop 必须触发子角色优雅中止')
    assert.ok(elapsedMs < 3500, `stop 优雅中止耗时过久: ${elapsedMs}ms`)
    assert.equal(ctrl.orchestrator.liveSessions.size, 0, 'stop 后不得遗留活跃孤儿子会话')

    await ctrl.dispose()
    await parentHandle.dispose()
  } finally {
    await harness.cleanup()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})
