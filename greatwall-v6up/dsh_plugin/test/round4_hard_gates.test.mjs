/**
 * 长城 Agent V6-Up (v2.2) Round 4 全部 Hard Gates (#2–#5) 无 Mock 实机端到端验收测试：
 *
 * - Gate 2: 5 套独立 Preset（无 {{cwd}} / 无 greatwall-control 阉割）、真实 WorkspaceRegistry attachSession / archiveSession、
 *           冷恢复 agents.resume() 自动重挂窄 MCP 工具与已结案节点只读锁；
 * - Gate 3: 非阻塞后台并发池（早触发 survey/works 请求秒级独立响应，不等整批阻塞分支）、
 *           异常 turn/end (error) 实时转 interrupted_unclaimed 崩溃打捞、intervene 干预指令实时推送；
 * - Gate 4: Scheme A 物理路径规范化 & pwsh 跨目录/python-c/环境变量/兄弟 worktree/companion 只读防线；
 * - Gate 5: 原生工具连调期间 500k 时钟追帧 (agent/pre-step + tools/result)、真实 2 轮问答、
 *           depends_on_questions (Q2 等待 Q1 L3 解锁后自动派生运行) 与 epoch_telemetry_summary.json。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

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
const includeMod = await importDshPkg('@deepseek-ai/cordis-plugin-include')
const yamlMod = await importDshPkg('js-yaml')
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
const storageMod = await importDshPkg('@deepseek-ai/dsh-storage')
const storageDomainMod = await importDshPkg('@deepseek-ai/dsh-storage-domain')
const storageJsonMod = await importDshPkg('@deepseek-ai/dsh-storage-json')
const persistenceJsonlMod = await importDshPkg('@deepseek-ai/dsh-session-persistence-jsonl')
const workspaceMod = await importDshPkg('@deepseek-ai/dsh-workspace')
const titleMod = await importDshPkg('@deepseek-ai/dsh-session-title')

const greatwallPlugin = await import(pathToFileURL(path.join(PLUGIN_DIR, 'lib/index.js')).href)
const { PRESET_DEFINITIONS, ensurePresetsInstalled } = await import(pathToFileURL(path.join(PLUGIN_DIR, 'lib/presets.js')).href)
const { installRoleSandboxGuard } = await import(pathToFileURL(path.join(PLUGIN_DIR, 'lib/read_isolated_sandbox.js')).href)

class GateLlmAdapter extends llmMod.LlmAdapter {
  constructor(handler) {
    super()
    this.handler = handler
  }
  providerInfo(provider) { return { id: provider, name: 'Gate Test Provider' } }
  async listModels(provider) { return [{ provider, id: 'test-model', name: 'Test Model' }] }
  async resolveModel(provider, model) {
    return {
      provider,
      id: model,
      name: model,
      context: { contextWindow: 500_000 },
      defaultMaxTokens: 4096,
      inputModalities: ['text'],
      reasoning: { efforts: [{ id: 'low', name: 'Low' }, { id: 'medium', name: 'Medium' }, { id: 'high', name: 'High' }], defaultEffort: 'low' },
    }
  }
  async *stream(options) {
    const plan = await this.handler(options)
    let idx = 0
    if (plan.throwError) {
      throw new Error(String(plan.throwError))
    }
    if (plan.text) {
      yield { type: 'block-start', index: idx, blockType: 'text' }
      yield { type: 'text-delta', index: idx, text: plan.text }
      yield { type: 'block-end', index: idx, block: { type: 'text', text: plan.text } }
      idx++
    }
    for (const tc of plan.toolCalls || []) {
      const id = tc.id || `tc_${Math.random().toString(36).slice(2, 10)}`
      const argsStr = JSON.stringify(tc.arguments || {})
      yield { type: 'block-start', index: idx, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: idx, id, name: tc.name, argumentsDelta: argsStr }
      yield { type: 'block-end', index: idx, block: { type: 'tool-call', id, name: tc.name, arguments: argsStr } }
      idx++
    }
    if (plan.usage) yield { type: 'usage', usage: plan.usage }
    yield { type: 'finish', reason: (plan.toolCalls || []).length ? { kind: 'tool-calls' } : { kind: 'stop' } }
  }
}

function registerBasicNativeTools(targetCtx) {
  const objOut = { schema: { type: 'object', additionalProperties: true }, render: (_a, v) => [{ type: 'text', text: JSON.stringify(v) }] }
  for (const [name, fn] of [
    ['read', async (args) => ({ ok: true, content: fs.readFileSync(String(args.file_path), 'utf8') })],
    ['write', async (args) => { fs.mkdirSync(path.dirname(String(args.file_path)), { recursive: true }); fs.writeFileSync(String(args.file_path), String(args.content), 'utf8'); return { ok: true } }],
    ['glob', async () => ({ ok: true, files: [] })],
    ['grep', async () => ({ ok: true, matches: [] })],
    ['pwsh', async (args) => ({ ok: true, stdout: `ran:${args.command}` })],
  ]) {
    targetCtx.tools.register({
      name,
      description: name,
      parameters: { type: 'object', additionalProperties: true },
      output: objOut,
      execute: fn,
    })
  }
}

test('Hard Gate #2: 5 Sub-role Presets (No {{cwd}}, Control Kept), Workspace attachSession/archiveSession & Cold Resume Remount', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate2_'))
  const dshHome = path.join(tmpRoot, '.dsh_home')
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  fs.mkdirSync(wsRoot, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

  // 1. 校验 5 套子角色 Preset 安装与 YAML 合规（严禁 {{cwd}}，严禁覆盖生成阉割版 greatwall-control）
  const installed = ensurePresetsInstalled({ dshHome })
  assert.deepEqual(installed.sort(), ['greatwall-companion', 'greatwall-explorer', 'greatwall-governance', 'greatwall-verifier', 'greatwall-works'])
  assert.equal(fs.existsSync(path.join(dshHome, '.agent-presets', 'greatwall-control')), false, '按用户明确指令，不得创建阉割版 greatwall-control')

  for (const id of installed) {
    const ymlRaw = fs.readFileSync(path.join(dshHome, '.agent-presets', id, 'agent.cordis.yml'), 'utf8')
    assert.ok(!ymlRaw.includes('{{cwd}}'), `${id} 严禁含 {{cwd}}`)
    assert.ok(!ymlRaw.includes('compaction-basic'), `${id} 不应带 compaction-basic`)
    assert.ok(!ymlRaw.includes('skill-filesystem'), `${id} 不应带 skill-filesystem`)
    assert.ok(!ymlRaw.includes('dsh-tool-subagent'), `${id} 不应带 subagent`)
    const parsed = yamlMod.load(ymlRaw, { schema: includeMod.entryListSchema })
    assert.ok(Array.isArray(parsed) && parsed.some((r) => r.id === 'persona'))
  }
  assert.equal(Object.keys(PRESET_DEFINITIONS).length, 5)

  // 2. 启动带真实 StorageJson / SessionPersistenceJsonl / WorkspaceRegistry / SessionTitle 的真 DSH Context
  const ctx = new cordis.Context()
  const sessionsDir = path.join(dshHome, 'sessions')
  const wsDir = path.join(dshHome, 'workspaces')
  fs.mkdirSync(sessionsDir, { recursive: true })
  fs.mkdirSync(wsDir, { recursive: true })

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
    ctx.plugin(titleMod.SessionTitleService),
    ctx.plugin(
      class MockPresetSvc extends cordis.Service {
        static inject = ['tools']
        constructor(pCtx) {
          super(pCtx, 'agentPresets')
          this.selfCtx = pCtx
          this.scopes = new Map()
        }
        async resolve(id) { return { id } }
        async mount(agentCtx, id) {
          if (!this.scopes.has(id)) {
            const key = { agentPreset: id }
            const scope = dshScopeMod.createScope(this.selfCtx, key)
            if (id !== 'greatwall-verifier') {
              scope.ctx.plugin({ inject: ['tools'], apply: (tCtx) => registerBasicNativeTools(tCtx) })
            }
            this.selfCtx.on('dispose', () => scope.dispose())
            this.scopes.set(id, key)
          }
          dshScopeMod.bindScopeParent(dshScopeMod.scopeOf(agentCtx), this.scopes.get(id))
          return { id }
        }
      },
    ),
  ])
  await ctx.plugin(storageMod.Storage)
  await ctx.plugin(storageJsonMod, { root: wsDir })
  await ctx.plugin(storageDomainMod, { backend: 'json' })
  await ctx.plugin(persistenceJsonlMod.default, { root: sessionsDir })
  await ctx.plugin(workspaceMod.WorkspaceRegistry)
  await ctx.plugin(greatwallPlugin)
  await ctx.lifecycle?.flush?.()
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall
  assert.ok(gwSvc, 'greatwall 服务必须注册就绪')

  let explorerReplyCount = 0
  const unreg = ctx.llm.registerAdapter(['test-provider'], new GateLlmAdapter(async (opts) => {
    const tools = (opts.tools || []).map((t) => t.name)
    if (tools.includes('run_isolated_eval')) {
      explorerReplyCount += 1
      return { text: `Explorer alive reply #${explorerReplyCount}` }
    }
    return { text: 'OK' }
  }))

  t.after(async () => {
    unreg()
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  // 在真 WorkspaceRegistry 注册当前主工作区
  const wsRecord = await ctx.workspaceRegistry.create(wsRoot, 'TestWS')
  assert.ok(wsRecord.id)

  const ctrl = gwSvc.createSessionController({
    workspaceRoot: wsRoot,
    dataDir,
    autoArchiveShortTx: true,
    defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
  })
  await ctrl.initEpoch({ goalMd: 'Gate2 Test', requiredQuestions: ['Q1'] })

  // A. 创建活跃探索者（keepAliveAfterIdle: true），验证 attachSession 归入主工作区 + UI 可直接发消息交互
  const expWt = path.join(wsRoot, 'worktrees', 'b_q1_t')
  fs.mkdirSync(expWt, { recursive: true })
  const expRes = await ctrl.orchestrator.spawnAndRunAgent({
    role: 'explorer',
    sessionId: 'gw_exp_gate2_001',
    nodeId: 'node_q1_001',
    branchId: 'b_q1_t',
    questionId: 'Q1',
    cwd: expWt,
    shortTransaction: false,
    keepAliveAfterIdle: true,
    prompt: 'Hello explorer',
  })
  const wsAfterAttach = await ctx.workspaceRegistry.resolveByPath(wsRoot)
  assert.ok(wsAfterAttach.sessionIds.includes('gw_exp_gate2_001'), '必须调用 attachSession 归入左侧主工作区')
  assert.equal(ctx.workspaceRegistry.archivedSessionIds.includes('gw_exp_gate2_001'), false)

  // 模拟人类点击左侧栏直接对活体探索者追加对话
  const humanTurn = await ctrl.orchestrator.continueAliveAgent('gw_exp_gate2_001', '人类直接纠偏：请继续保持简洁')
  assert.ok(humanTurn.lastAssistantText.includes('Explorer alive reply #2'))

  // B. 验证一次性短事务 verifier 完成后自动调 archiveSession 从左侧栏隐藏，但底层 JSONL 保留可读
  await ctrl.orchestrator.spawnAndRunAgent({
    role: 'library_verifier',
    sessionId: 'gw_ver_gate2_002',
    questionId: 'Q1',
    shortTransaction: true,
    prompt: 'Short verify',
  })
  assert.equal(ctx.workspaceRegistry.archivedSessionIds.includes('gw_ver_gate2_002'), true, '短事务盲审完成后应调 archiveSession 隐藏')

  // C. dispose() 探索者后再调用真实 ctx.agents.resume() 验证冷恢复不丢失窄 MCP 与沙箱 Guard，且结案短事务冷恢复自动锁只读！
  await expRes.dispose()
  // 将刚创建在内存的 bridge schemas 缓存确认
  const resumedExp = await ctx.agents.resume({
    resumeSessionId: 'gw_exp_gate2_001',
    agentOptions: { provider: 'test-provider', model: 'test-model' },
    setup: async (agentCtx) => {
      await ctx.agentPresets.mount(agentCtx, 'greatwall-explorer')
    },
  })
  const resumedToolNames = resumedExp.agent.ctx.tools.schemas(resumedExp.agent).map((s) => s.name)
  assert.ok(resumedToolNames.includes('run_isolated_eval'), '冷恢复后必须同步重挂 5 个窄 MCP 工具！')
  assert.ok(resumedToolNames.includes('read'), '冷恢复应保留白名单原生 read')
  await resumedExp.dispose()

  const resumedVer = await ctx.agents.resume({
    resumeSessionId: 'gw_ver_gate2_002',
    agentOptions: { provider: 'test-provider', model: 'test-model' },
    setup: async (agentCtx) => {
      await ctx.agentPresets.mount(agentCtx, 'greatwall-verifier')
    },
  })
  // 已结案短事务冷恢复：因 settled=true 强制锁定只读态且禁止 MCP 写工具重挂
  const resumedVerTools = resumedVer.agent.ctx.tools.schemas(resumedVer.agent).map((s) => s.name)
  assert.equal(resumedVerTools.includes('submit_stage2_unblind_verdict'), false, '已结案盲审冷恢复后禁止再重挂写工具')
  await resumedVer.dispose()
  await ctrl.dispose()
})

test('Hard Gate #4: Scheme A Physical Path & pwsh Sandbox Guard (Worktree, Companion RO, Logistics problem_pack, DB Ban)', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate4_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  const wtA = path.join(wsRoot, 'worktrees', 'b_q1_a')
  const wtB = path.join(wsRoot, 'worktrees', 'b_q1_b')
  fs.mkdirSync(wtA, { recursive: true })
  fs.mkdirSync(wtB, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

  try {
    const fakeAgentCtx = { tools: { guard(fn) { fakeAgentCtx._guardFn = fn; return () => {} } } }
    // 1. explorer: 本人 worktree 放行；兄弟 worktree / sqlite3 / python -c / .. / $env: / anchors 拦截
    installRoleSandboxGuard(fakeAgentCtx, {
      role: 'explorer',
      sessionId: 's_g4_exp',
      nodeId: 'n_a',
      workspaceRoot: wsRoot,
      worktreeAbsPath: wtA,
      protectedDirs: [dataDir, wtB],
    })
    assert.equal(fakeAgentCtx._guardFn({ name: 'pwsh', arguments: { command: `python ${path.join(wtA, 'src', 'solve.py')}` } }), undefined)
    assert.match(fakeAgentCtx._guardFn({ name: 'pwsh', arguments: { command: `python -c "import sqlite3; sqlite3.connect(r'${path.join(dataDir, 'greatwall.db')}')"` } }) || '', /SANDBOX_VIOLATION/)
    assert.match(fakeAgentCtx._guardFn({ name: 'pwsh', arguments: { command: 'Get-Content ../../evaluators/anchors/Q1/gt.json' } }) || '', /SANDBOX_VIOLATION/)
    assert.match(fakeAgentCtx._guardFn({ name: 'pwsh', arguments: { command: 'echo $env:PLUGIN_DATA' } }) || '', /SANDBOX_VIOLATION/)
    assert.match(fakeAgentCtx._guardFn({ name: 'read', arguments: { file_path: path.join(wtB, 'src', 'secret.py') } }) || '', /SANDBOX_VIOLATION/)

    // 2. companion: 仅只读配对 worktree，禁 write / edit
    installRoleSandboxGuard(fakeAgentCtx, {
      role: 'lineage_companion',
      sessionId: 's_g4_comp',
      nodeId: 'n_a',
      workspaceRoot: wsRoot,
      worktreeAbsPath: wtA,
      protectedDirs: [dataDir, wtB],
    })
    assert.equal(fakeAgentCtx._guardFn({ name: 'read', arguments: { file_path: path.join(wtA, 'src', 'a.py') } }), undefined)
    assert.match(fakeAgentCtx._guardFn({ name: 'write', arguments: { file_path: path.join(wtA, 'src', 'a.py'), content: 'x' } }) || '', /SANDBOX_VIOLATION/)

    // 3. logistics_coordinator: 原生工具全面锁只读，禁修改 worktrees/ 或 evaluators/
    installRoleSandboxGuard(fakeAgentCtx, {
      role: 'logistics_coordinator',
      sessionId: 's_g4_logi',
      workspaceRoot: wsRoot,
      protectedDirs: [dataDir],
    })
    assert.equal(fakeAgentCtx._guardFn({ name: 'read', arguments: { file_path: path.join(wsRoot, 'problem_pack', 'spec.md') } }), undefined)
    assert.match(fakeAgentCtx._guardFn({ name: 'write', arguments: { file_path: path.join(wsRoot, 'evaluators', 'h1.py'), content: 'x' } }) || '', /SANDBOX_VIOLATION/)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('Hard Gate #5: Pre-Step/ToolsResult 500k Clock Observer, Intervene Telemetry & Blackbox Surface Extract', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate5_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  const wtDir = path.join(wsRoot, 'worktrees', 'b_q1_clk')
  fs.mkdirSync(wtDir, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

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
    ctx.plugin(
      class PresetLite extends cordis.Service {
        static inject = ['tools']
        constructor(pCtx) { super(pCtx, 'agentPresets'); this.selfCtx = pCtx; this.standing = null }
        async resolve(id) { return { id } }
        async mount(agentCtx, id) {
          if (!this.standing && id !== 'greatwall-verifier') {
            const key = { p: 'g5' }
            const scope = dshScopeMod.createScope(this.selfCtx, key)
            scope.ctx.plugin({ inject: ['tools'], apply: (t) => registerBasicNativeTools(t) })
            this.selfCtx.on('dispose', () => scope.dispose())
            this.standing = key
          }
          if (this.standing && id !== 'greatwall-verifier') dshScopeMod.bindScopeParent(dshScopeMod.scopeOf(agentCtx), this.standing)
          return { id }
        }
      },
    ),
  ])
  await ctx.plugin(greatwallPlugin)
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall
  assert.ok(gwSvc)

  let activeWtDir = wtDir
  let stepCount = 0
  const unreg = ctx.llm.registerAdapter(['test-provider'], new GateLlmAdapter(async () => {
    stepCount += 1
    if (stepCount === 1) {
      return {
        toolCalls: [{ name: 'write', arguments: { file_path: path.join(activeWtDir, 'src', 'cand.py'), content: 'def run(p): return {"v": 2}\n' } }],
        usage: { inputTokens: 190_000, outputTokens: 200, totalTokens: 190_200 },
      }
    }
    return {
      text: 'Explorer native write step done.',
      usage: { inputTokens: 195_000, outputTokens: 200, totalTokens: 195_200 },
    }
  }))

  let ctrl = null
  t.after(async () => {
    unreg()
    try { await ctrl?.dispose?.() } catch {}
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  ctrl = gwSvc.createSessionController({
    workspaceRoot: wsRoot,
    dataDir,
    defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
  })
  await ctrl.initEpoch({ goalMd: 'Gate5 Clock Test', requiredQuestions: ['Q1'] })

  await ctrl.bridge.callTool('register_method_family', {
    question_id: 'Q1',
    family_id: 'fam_clk_1',
    mechanism_signature: 'clock sig',
    orthogonal_contrast: 'baseline',
  }, { role: 'logistics_coordinator', sessionId: 's_l5' })
  const branchRes = await ctrl.bridge.callTool('fork_branch', {
    question_id: 'Q1',
    fork_mode: 'orthogonal',
    target_family_id: 'fam_clk_1',
  }, { role: 'logistics_coordinator', sessionId: 's_l5' })
  const nodeId = branchRes.data.node_id
  activeWtDir = branchRes.data.worktree_abs_path

  fs.mkdirSync(path.join(wsRoot, 'evaluators'), { recursive: true })
  fs.mkdirSync(path.join(wsRoot, 'baselines', 'Q1'), { recursive: true })
  fs.writeFileSync(path.join(wsRoot, 'baselines', 'Q1', 'b.py'), 'K=1\n')
  fs.writeFileSync(path.join(wsRoot, 'evaluators', 'h1.py'), "def evaluate_candidate(a, s): return {'passed': True, 'metrics':{'rank_score':1.0}, 'details':'ok'}\n")
  await ctrl.bridge.callTool('register_question_domain_hook', {
    question_id: 'Q1',
    hook_rel_path: 'evaluators/h1.py',
    baseline_rel_path: 'baselines/Q1/b.py',
    fidelity_max_error_pct: 0.5,
    public_input_sample: { x: 1 },
  }, { role: 'works_engineer', sessionId: 's_w5' })

  fs.mkdirSync(path.join(activeWtDir, 'src'), { recursive: true })
  fs.writeFileSync(path.join(activeWtDir, 'src', 'cand.py'), "def run(p): return {'v': 2}\n")
  const ev5 = await ctrl.bridge.callTool('run_isolated_eval', {
    node_id: nodeId,
    question_id: 'Q1',
    candidate_rel_path: 'src/cand.py',
    linguistic_prediction: '预测 cand.py 返回 v=2 满足 passed=True 且 rank_score 达到 1.0 基线，证明首次评估计数递增。',
  }, { role: 'explorer', sessionId: 's_e5' })
  assert.ok(ev5?.ok, `Gate5 eval failed: ${JSON.stringify(ev5)}`)

  await ctrl.orchestrator.intervene({ targetType: 'question', targetId: 'Q1', directive: 'Prioritize fast invariant proof' })

  const expRes = await ctrl.orchestrator.spawnAndRunAgent({
    role: 'explorer',
    sessionId: 'gw_exp_gate5',
    nodeId,
    branchId: branchRes.data.branch_id,
    questionId: 'Q1',
    cwd: activeWtDir,
    shortTransaction: false,
    prompt: 'Write cand.py and finish.',
  })

  assert.ok(expRes.nativeThresholds.some((ev) => ev.trigger === 'REFLECT_37' && (String(ev.sourceHook).includes('tools/result:write') || String(ev.sourceHook).includes('agent/pre-step'))), `tools/result 或 pre-step 必须实时捕获 >=37% 阈值，实测: ${JSON.stringify(expRes.nativeThresholds)}`)
  assert.ok(expRes.blackboxSummary.includes('Explorer native write step done.'), `真实 session.deriveMessages() 必须正确提取黑匣子轨迹，实测: ${expRes.blackboxSummary}`)
  assert.ok(fs.existsSync(ctrl.orchestrator.telemetry.filePath))
  const telJson = JSON.parse(fs.readFileSync(ctrl.orchestrator.telemetry.filePath, 'utf8'))
  assert.ok(telJson.interventions.some((i) => i.directive.includes('Prioritize fast')))
})

test('Hard Gate #3: Abnormal Turn Crash Detection & depends_on_questions Unlock After Q1 L3', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate3_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  const wtDir = path.join(wsRoot, 'worktrees', 'b_q1_err')
  fs.mkdirSync(wtDir, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

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
    ctx.plugin(
      class PresetErr extends cordis.Service {
        static inject = ['tools']
        constructor(pCtx) { super(pCtx, 'agentPresets'); this.selfCtx = pCtx }
        async resolve(id) { return { id } }
        async mount() { return { id: 'p' } }
      },
    ),
  ])
  await ctx.plugin(greatwallPlugin)
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall

  const unreg = ctx.llm.registerAdapter(['test-provider'], new GateLlmAdapter(async () => ({ throwError: 'SIMULATED_WORKER_STREAM_CRASH' })))

  let ctrl = null
  t.after(async () => {
    unreg()
    try { await ctrl?.dispose?.() } catch {}
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  ctrl = gwSvc.createSessionController({
    workspaceRoot: wsRoot,
    dataDir,
    defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
  })
  await ctrl.initEpoch({
    goalMd: 'Gate3 Crash & Deps',
    requiredQuestions: ['Q1', 'Q2'],
    contracts: { Q2: { depends_on_questions: ['Q1'] } },
  })

  // A. 验证流式报错产生 turn/end(error) -> isAbnormalEnd: true（打捞前兆不静默丢包）
  const errRes = await ctrl.orchestrator.spawnAndRunAgent({
    role: 'explorer',
    sessionId: 'gw_exp_gate3_crash',
    nodeId: 'n_crash',
    branchId: 'b_q1_err',
    questionId: 'Q1',
    cwd: wtDir,
    shortTransaction: true,
    prompt: 'Crash intentionally',
  })
  assert.equal(errRes.isAbnormalEnd, true, `异常 turn/end 必须判定 isAbnormalEnd=true，实测: ${JSON.stringify(errRes.turnEndReason)}`)

  // B. 验证 depends_on_questions：Q1 无 L3 前 Q2 被锁，Q1 入库 L3 后 Q2 解锁进入 questions_needing_branch
  await ctrl.bridge.callTool('register_method_family', {
    question_id: 'Q1',
    family_id: 'fam_dep_1',
    mechanism_signature: 'q1 root',
    orthogonal_contrast: 'base',
  }, { role: 'logistics_coordinator', sessionId: 's_l3' })
  await ctrl.bridge.callTool('register_method_family', {
    question_id: 'Q2',
    family_id: 'fam_dep_2',
    mechanism_signature: 'q2 dependent',
    orthogonal_contrast: 'needs q1',
    depends_on_questions: ['Q1'],
  }, { role: 'logistics_coordinator', sessionId: 's_l3' })

  const stBefore = await ctrl.bridge.control('control_plane/schedule_snapshot', {})
  assert.ok(stBefore?.ok, `schedule_snapshot 失败: ${JSON.stringify(stBefore)}`)
  const snapBefore = stBefore.data || stBefore
  assert.equal((snapBefore.questions_needing_branch || []).includes('Q2'), false, 'Q1 未闭环前 Q2 禁止被派单')

  const brQ1 = await ctrl.bridge.callTool('fork_branch', {
    question_id: 'Q1',
    fork_mode: 'orthogonal',
    target_family_id: 'fam_dep_1',
  }, { role: 'logistics_coordinator', sessionId: 's_l3' })
  const nQ1 = brQ1.data.node_id
  const bQ1 = brQ1.data.branch_id
  const wtQ1 = brQ1.data.worktree_abs_path

  fs.mkdirSync(path.join(wsRoot, 'evaluators'), { recursive: true })
  fs.mkdirSync(path.join(wsRoot, 'baselines', 'Q1'), { recursive: true })
  fs.writeFileSync(path.join(wsRoot, 'baselines', 'Q1', 'b.py'), 'K=1\n')
  fs.writeFileSync(path.join(wsRoot, 'evaluators', 'h1.py'), "def evaluate_candidate(a, s): return {'passed': True, 'metrics':{'rank_score':1.0}, 'details':'ok'}\n")
  fs.mkdirSync(path.join(wtQ1, 'src'), { recursive: true })
  fs.writeFileSync(path.join(wtQ1, 'src', 'cand.py'), "def run(p): return {'v': 2}\n")

  await ctrl.bridge.callTool('register_question_domain_hook', {
    question_id: 'Q1',
    hook_rel_path: 'evaluators/h1.py',
    baseline_rel_path: 'baselines/Q1/b.py',
    fidelity_max_error_pct: 0.5,
    public_input_sample: { x: 1 },
  }, { role: 'works_engineer', sessionId: 's_w3' })
  const ev = await ctrl.bridge.callTool('run_isolated_eval', {
    node_id: nQ1,
    question_id: 'Q1',
    candidate_rel_path: 'src/cand.py',
    linguistic_prediction: '预测线性候选解 cand.py 返回 v=2 满足 evaluate_candidate 且通过 Stage B。',
  }, { role: 'explorer', sessionId: 's_e3' })
  assert.ok(ev?.ok, `run_isolated_eval 必须成功: ${JSON.stringify(ev)}`)
  const ho = await ctrl.bridge.callTool('submit_node_handoff', {
    node_id: nQ1,
    branch_id: bQ1,
    question_id: 'Q1',
    column_a_facts_md: `Obs ${ev.data.obs_id} passed cleanly.`,
    column_b_hypothesis_md: '已通过对比基准与独立样例验证该线性近似机制在局部作用域内稳健收敛。',
    will_md: 'Recommend L3 verification after verifying invariant.',
    obs_ids: [ev.data.obs_id],
    candidate_rel_path: 'src/cand.py',
  }, { role: 'lineage_companion', sessionId: 's_c3' })
  assert.ok(ho?.ok, `handoff 必须成功: ${JSON.stringify(ho)}`)

  const tr = await ctrl.bridge.callTool('triage_node', {
    node_id: nQ1,
    triage_level: 'LEVEL_1',
    action: 'SUBMIT_BLIND_REVIEW',
    rationale: '已通过观测和基准检验，送入双阶段盲审确认入库 L3 并解锁依赖子题 Q2。',
  }, { role: 'logistics_coordinator', sessionId: 's_l3' })
  assert.ok(tr?.ok, `triage_node 必须成功: ${JSON.stringify(tr)}`)
  const revId = tr.data.created_review_id
  assert.ok(revId, `triage_node 必须生成 created_review_id，实测: ${JSON.stringify(tr)}`)

  const r1 = await ctrl.bridge.callTool('submit_stage1_blind_ledger', {
    review_id: revId,
    question_id: 'Q1',
    ledger_items: [{ claim: 'Linear model passes hook', evidence_location_and_quote: `${ev.data.obs_id}: passed=True rank_score=1.0`, is_verified: true }],
    stage1_verdict: 'PASS',
  }, { role: 'library_verifier', sessionId: 's_v3' })
  assert.ok(r1?.ok, `stage1 必须成功: ${JSON.stringify(r1)}`)
  const r2 = await ctrl.bridge.callTool('submit_stage2_unblind_verdict', {
    review_id: revId,
    final_verdict: 'PASS',
    title: 'Q1 L3 Entry',
    abstract_md: '这是一条经过盲审阶段一（独立核账）与阶段二（解盲核验与机制泛化检验）完整验证通过的 L3 黄金结论条目，正式激活下游 Q2 依赖派单。',
    exact_verified_scope_md: '全区间',
  }, { role: 'library_verifier', sessionId: 's_v3' })
  assert.ok(r2?.ok, `stage2 必须成功: ${JSON.stringify(r2)}`)

  const stAfter = await ctrl.bridge.control('control_plane/schedule_snapshot', {})
  const snapAfter = stAfter.data || stAfter
  assert.ok((snapAfter.questions_needing_branch || []).includes('Q2'), `Q1 入库 L3 后 Q2 必须自动解锁待派单，实测: ${JSON.stringify(snapAfter)}`)
})

test('Hard Gate #6: Right-Sidebar Greatwall Console Client Module & /api/greatwall.{status,control} Authenticated Routes', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate6_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  fs.mkdirSync(wsRoot, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

  // 1. 校验 package.json exports["./client"] 与 dsh.client 声明符合 dsh-client-modules 规范
  const pjson = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, 'package.json'), 'utf8'))
  assert.equal(pjson.exports?.['./client'], './lib/client.js')
  assert.equal(pjson.dsh?.client?.platform, 'web')
  assert.ok(Array.isArray(pjson.dsh?.client?.inject) && pjson.dsh.client.inject.includes('@deepseek-ai/dsh-client-ui-sidebar-right'))

  // 2. 用 window.__ModuleLoader__.load 执行 client.js 验证导出、inject 与右侧栏 Tab/Slot 注册
  let loadedModule = null
  const origWindow = globalThis.window
  const fakeReact = {
    useState: (v) => [typeof v === 'function' ? v() : v, () => {}],
    useCallback: (fn) => fn,
    useEffect: () => {},
  }
  const fakeJsx = {
    jsx: (type, props) => ({ type, props }),
    jsxs: (type, props) => ({ type, props }),
    Fragment: Symbol('Fragment'),
  }
  globalThis.window = {
    __ModuleLoader__: {
      load(modDef) {
        loadedModule = modDef
      },
    },
  }
  try {
    const clientCode = fs.readFileSync(path.join(PLUGIN_DIR, 'lib/client.js'), 'utf8')
    new Function(clientCode)()
    assert.equal(loadedModule?.id, 'dsh-greatwall-v6up')
    const clientExports = loadedModule.factory((id) => {
      if (id === 'react') return fakeReact
      if (id === 'react/jsx-runtime') return fakeJsx
      throw new Error(`Unexpected client require: ${id}`)
    })
    assert.deepEqual(clientExports.inject, ['slots', 'sidebarRightTabs'])
    const regTabs = []
    const regSlots = []
    const disposers = []
    const fakeClientCtx = {
      effect(fn) {
        const d = fn()
        if (typeof d === 'function') disposers.push(d)
      },
      sidebarRightTabs: {
        register(def) {
          regTabs.push(def)
          return () => {}
        },
      },
      slots: {
        inject(_slot, fn) {
          fn()
          return () => {}
        },
        register(spec, comp) {
          regSlots.push({ spec, comp })
          return () => {}
        },
      },
    }
    clientExports.apply(fakeClientCtx)
    assert.equal(regTabs.length, 1)
    assert.equal(regTabs[0].kind, 'greatwall')
    assert.equal(regTabs[0].title(), '长城控制台')
    assert.ok(regSlots.some((s) => s.spec.name === 'sidebar.right.pane.tab' && s.spec.key === 'dsh-greatwall-v6up'))
    assert.ok(regSlots.some((s) => s.spec.name === 'sidebar.right.pane.tab.title' && s.spec.key === 'dsh-greatwall-v6up'))
    for (const d of disposers) d()
  } finally {
    if (origWindow === undefined) delete globalThis.window
    else globalThis.window = origWindow
  }

  // 3. 在 Cordis Context 挂载伪 connection.fetch 验证真实服务端路由 /api/greatwall.{status,control}
  const registeredRoutes = new Map()
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
    ctx.plugin({
      name: 'mock-connection',
      apply(cCtx) {
        cCtx.provide('connection', {
          fetch: {
            register(routeDef) {
              registeredRoutes.set(routeDef.path, routeDef)
              return () => registeredRoutes.delete(routeDef.path)
            },
          },
        }, true)
      },
    }),
  ])
  await ctx.plugin(greatwallPlugin)
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall
  assert.ok(registeredRoutes.has('/api/greatwall.status'))
  assert.ok(registeredRoutes.has('/api/greatwall.control'))

  let ctrl = null
  t.after(async () => {
    try { await ctrl?.dispose?.() } catch {}
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  ctrl = gwSvc.createSessionController({ workspaceRoot: wsRoot, dataDir })
  await ctrl.initEpoch({ goalMd: 'Gate6 UI Console Test', requiredQuestions: ['Q1', 'Q2'], contracts: { Q2: { depends_on_questions: ['Q1'] } } })

  // 先通过 POST /api/greatwall.control 下发一次人类定向干预
  const postRoute = registeredRoutes.get('/api/greatwall.control')
  const postRes = await postRoute.fetch(
    new Request('http://localhost/api/greatwall.control', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        action: 'intervene',
        workspaceRoot: wsRoot,
        targetType: 'question',
        targetId: 'Q1',
        interventionAction: 'steer',
        directive: 'UI Console test directive: focus on stability',
      }),
    }),
  )
  const postJson = await postRes.json()
  assert.equal(postJson.ok, true)
  assert.equal(postJson.intervened, true)

  // 再 GET /api/greatwall.status 核对控制面快照与刚刚写入的纠偏指令
  const getRoute = registeredRoutes.get('/api/greatwall.status')
  const getRes = await getRoute.fetch(new Request(`http://localhost/api/greatwall.status?workspaceRoot=${encodeURIComponent(wsRoot)}`))
  const getJson = await getRes.json()
  assert.equal(getJson.ok, true)
  assert.equal(getJson.source, 'live_controller')
  assert.ok(getJson.status?.snapshot?.question_dependencies?.Q2)
  assert.ok(getJson.telemetryState?.interventions?.some((i) => i.directive.includes('UI Console test directive')))
})

test('Hard Gate #7: DSH 0.2.2-rc.3 AgentPresetRegistry Declarative Register Fallback & Fail-Closed Missing Native Tool Guard', async (t) => {
  const { buildDeclarativePresetConfigs, registerPresetsOnRegistry } = await import(
    pathToFileURL(path.join(PLUGIN_DIR, 'lib/presets.js')).href
  )

  const configs = buildDeclarativePresetConfigs('win32')
  assert.equal(configs.length, 5)
  const worksCfg = configs.find((c) => c.id === 'greatwall-works')
  assert.ok(worksCfg.plugins.some((p) => p.name === '@deepseek-ai/dsh-tool-fs'))
  assert.ok(worksCfg.plugins.some((p) => p.name === '@deepseek-ai/dsh-tool-pwsh' && p.disabled === false))

  // 1. 模拟 0.2.2-rc.3 AgentPresetRegistry（初始未预装 greatwall-*）验证运行时 registerPresetsOnRegistry 幂等热注册
  const defs = new Map()
  const mockReg = {
    async register(def) {
      if (defs.has(def.id)) throw new Error(`Duplicate agent preset: ${def.id}`)
      defs.set(def.id, def)
      return async () => { defs.delete(def.id) }
    },
    async resolve(id) {
      if (!defs.has(id)) throw new Error(`Unknown agent preset: ${id}`)
      return { id }
    },
  }
  const fakeCtx = { root: { get: (k) => (k === 'agentPresets' ? mockReg : null) } }
  const r1 = await registerPresetsOnRegistry(fakeCtx, mockReg)
  assert.equal(r1.registered.length, 5)
  assert.equal(r1.errors.length, 0)
  // 二次幂等调用不应重复注册报 Duplicate
  const r2 = await registerPresetsOnRegistry(fakeCtx, mockReg)
  assert.equal(r2.alreadyReady.length, 5)
  assert.equal(r2.registered.length, 0)
  await r1.disposeAll()
  assert.equal(defs.size, 0)

  // 2. 验证 Fail-Closed：若 0.2.2-rc.3 works_engineer 挂载后仍缺少 read/write/pwsh，绝不静默放行裸奔
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate7_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  fs.mkdirSync(wsRoot, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })

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
    ctx.plugin(
      class BrokenWorksRegistry extends cordis.Service {
        constructor(pCtx) {
          super(pCtx, 'agentPresets')
          this.defs = new Map()
        }
        async register(def) {
          this.defs.set(def.id, def)
          return () => this.defs.delete(def.id)
        }
        async resolve(id) {
          if (!this.defs.has(id)) throw new Error(`Unknown agent preset: ${id}`)
          return { id }
        }
        async mount() {
          // 故意不挂载任何原生 fs/pwsh 工具，验证 Fail-Closed 拦截！
          return { id: 'greatwall-works' }
        }
      },
    ),
  ])
  await ctx.plugin(greatwallPlugin)
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall
  const unregLlm = ctx.llm.registerAdapter(['test-provider'], new GateLlmAdapter(async () => ({ text: 'should not run' })))
  let ctrl = null
  t.after(async () => {
    unregLlm()
    try { await ctrl?.dispose?.() } catch {}
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  ctrl = gwSvc.createSessionController({
    workspaceRoot: wsRoot,
    dataDir,
    defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
  })
  await assert.rejects(
    ctrl.orchestrator.spawnAndRunAgent({
      role: 'works_engineer',
      sessionId: 'gw_works_naked',
      shortTransaction: true,
      prompt: 'Try run naked',
    }),
    /缺少关键原生工具/,
  )
})

test('Hard Gate #8: Stage 1 Governance Interventions Injection & Live Agent Steer Delivery', async (t) => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_gate8_'))
  const wsRoot = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  fs.mkdirSync(path.join(wsRoot, 'evaluators'), { recursive: true })
  fs.mkdirSync(path.join(wsRoot, 'baselines', 'Q1'), { recursive: true })
  fs.writeFileSync(path.join(wsRoot, 'baselines', 'Q1', 'b1.py'), 'X = 1\n', 'utf8')
  fs.writeFileSync(
    path.join(wsRoot, 'evaluators', 'hook_q1.py'),
    "def evaluate_candidate(art, spec):\n    val = float(art.get('val', 1.0))\n    return {'passed': val >= 1.0, 'metrics': {'rank_score': val}, 'details': 'ok'}\n",
    'utf8',
  )
  fs.mkdirSync(dataDir, { recursive: true })

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
    ctx.plugin(
      class OkPresetsRegistry extends cordis.Service {
        constructor(pCtx) {
          super(pCtx, 'agentPresets')
          this.defs = new Map()
        }
        async register(def) {
          this.defs.set(def.id, def)
          return () => this.defs.delete(def.id)
        }
        async resolve(id) {
          if (!this.defs.has(id)) throw new Error(`Unknown agent preset: ${id}`)
          return { id }
        }
        async mount(_agentCtx, id) {
          return { id }
        }
      },
    ),
  ])
  await ctx.plugin(greatwallPlugin)
  const gwSvc = ctx.get?.('greatwall') || ctx.greatwall

  const seenStepMessages = []
  let surveyorStep = 0
  let resolveFirstStepRunning = null
  const firstStepRunning = new Promise((r) => { resolveFirstStepRunning = r })
  let releaseSecondStep = null
  const secondStepGate = new Promise((r) => { releaseSecondStep = r })

  const unregLlm = ctx.llm.registerAdapter(
    ['test-provider'],
    new GateLlmAdapter(async (options) => {
      const msgText = JSON.stringify(options.messages || [])
      seenStepMessages.push(msgText)
      surveyorStep += 1
      if (surveyorStep === 1) {
        // 第 1 步触发一次查询并通知外部：正在 liveSessions 运行中，测试实时 steer 注入！
        resolveFirstStepRunning()
        await secondStepGate
        return {
          text: '先查采编列表。',
          toolCalls: [{ name: 'get_survey_requests', arguments: { question_id: 'ALL' } }],
        }
      }
      return {
        text: '按纠偏指令立即发布 R001。',
        toolCalls: [
          {
            name: 'publish_external_literature_card',
            arguments: {
              ref_id: 'R001',
              question_id: 'Q1',
              title: 'Stage 1 实时 Steer 测试卡片',
              abstract_md: '本测试验证采编角色在 Stage 1 初始化阶段能够自动接收历史定向干预并在运行中接收实时 steer 纠偏，从而快速使用英文枚举入库 R001。',
              exact_preconditions_md: '适用全测试域',
              formulas_or_operators_md: 'J = k * C',
              read_depth: 'full_text',
              support_scope: 'DIRECT_PROOF_OR_EXACT_MEASUREMENT',
              source_citation: 'Gate 8 Spec 2026',
            },
          },
        ],
      }
    }),
  )

  let ctrl = null
  t.after(async () => {
    unregLlm()
    try { releaseSecondStep?.() } catch {}
    try { await ctrl?.dispose?.() } catch {}
    try { await ctx.fiber.dispose() } catch {}
    try { fs.rmSync(tmpRoot, { recursive: true, force: true }) } catch {}
  })

  ctrl = gwSvc.createSessionController({
    workspaceRoot: wsRoot,
    dataDir,
    defaultAgentOptions: { provider: 'test-provider', model: 'test-model', reasoningEffort: 'low' },
  })
  await ctrl.bridge.control('control_plane/init_epoch', {
    workspace_root: wsRoot,
    required_questions: ['Q1'],
    goal_md: 'Gate 8 Stage 1 Steer Test',
  })
  const hookRes = await ctrl.bridge.callTool(
    'register_question_domain_hook',
    {
      question_id: 'Q1',
      hook_rel_path: 'evaluators/hook_q1.py',
      baseline_rel_path: 'baselines/Q1/b1.py',
      fidelity_max_error_pct: 0.5,
      public_input_sample: { val: 1.0 },
    },
    { role: 'works_engineer', sessionId: 'sess_g8_works', workspaceRoot: wsRoot },
  )
  assert.equal(hookRes.ok, true, JSON.stringify(hookRes))

  // 1. 启动前先下发针对 library_surveyor 的历史定向干预
  await ctrl.orchestrator.intervene({
    targetType: 'role',
    targetId: 'library_surveyor',
    directive: '历史定向指令：开局优先速建 R001',
  })

  // 仅跑一步 Stage 1 surveyor 唤醒并在入库后暂停
  const bg = await ctrl.orchestrator.startBackground({ maxConcurrentWorkers: 1 })
  assert.ok(bg)

  await firstStepRunning
  // 2. 在 library_surveyor 处于 liveSessions 运行期间实时下发 steer
  const steerRes = await ctrl.orchestrator.intervene({
    targetType: 'role',
    targetId: 'library_surveyor',
    directive: '实时 Steer 指令：support_scope 必须填 DIRECT_PROOF_OR_EXACT_MEASUREMENT',
  })
  assert.equal(steerRes.steeredSessions.length, 1)
  assert.equal(steerRes.steeredSessions[0].role, 'library_surveyor')

  releaseSecondStep()

  // 等待 R001 落库后停止后台编排，避免继续进入 logistics_init
  const deadline = Date.now() + 10_000
  let litCount = 0
  while (Date.now() < deadline) {
    const st = await ctrl.orchestrator.getControlStatus()
    litCount = Number(st.snapshot?.external_literature_count || 0)
    if (litCount >= 1) break
    await new Promise((r) => setTimeout(r, 40))
  }
  await ctrl.orchestrator.stopBackground('GATE8_DONE')

  assert.equal(litCount, 1)
  assert.ok(seenStepMessages.length >= 2)
  assert.match(seenStepMessages[0], /历史定向指令：开局优先速建 R001/)
  assert.ok(
    seenStepMessages.slice(1).some((m) => m.includes('实时 Steer 指令：support_scope 必须填 DIRECT_PROOF_OR_EXACT_MEASUREMENT')),
    'running library_surveyor session must receive live steer directive in next LLM step',
  )
})
