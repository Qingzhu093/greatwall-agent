/**
 * GreatWall V6-Up (v3.0) DSH 插件纯模块级快速单元测试（零 DSH SDK 启动，全量 <5s 跑完）。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  ALL_31_MCP_TOOLS,
  ALL_MCP_TOOLS,
  CANONICAL_ROLES,
  ROLE_MCP_TOOLS,
  TURN_CONCLUDING_TOOLS,
  resolvePlatformAllowedTools,
  resolvePlatformShellTool,
} from '../lib/prompts.js'
import { PRESET_DEFINITIONS, ROLE_TO_PRESET, buildDeclarativePresetConfigs } from '../lib/presets.js'
import { READONLY_BLOCKED_MCP_TOOLS, createSandboxCallEvaluator } from '../lib/read_isolated_sandbox.js'
import {
  evaluateContextClockTrigger,
  sampleAgentContextPressure,
  shouldConcludeTurnAfterTool,
} from '../lib/clock_and_turn_gap.js'
import {
  AgentSessionHost,
  assertRequiredNativeTools,
  extractModelBindingFromEvents,
  resolveAuthoritativeModelBinding,
  resolveEffectiveContextWindow,
} from '../lib/agent_session_host.js'
import { GreatwallMcpBridge, LONG_RUNNING_MCP_TOOLS } from '../lib/mcp_bridge.js'
import {
  driveExplorerCompanionPair,
  runPreSpawnBriefingWithCompanion,
} from '../lib/pair_lifecycle.js'
import {
  GovernanceItemCircuitBreaker,
  GreatwallOrchestrator,
  selectDispatchableExplorers,
} from '../lib/orchestrator.js'
import { TelemetryCollector } from '../lib/telemetry.js'
import { pickController } from '../lib/console_routes.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CORE_PYTHON_ROOT = path.resolve(__dirname, '..', '..', 'core_python')

test('DSH RC5 流式拒答：首次回合与续跑均保留错误码并写入遥测', async () => {
  const refusal = { kind: 'error', error: { code: 'CONTENT_REFUSED', message: 'Provider refused the request' } }
  const reasons = [{ kind: 'completed' }, refusal, refusal]
  const recorded = []
  const host = new AgentSessionHost({
    ctx: {
      agents: {
        async create() {
          const events = []
          return {
            agent: {
              session: { snapshotEvents: () => events },
              followup() {
                events.push({ type: 'turn/end', data: { reason: reasons.shift() } })
              },
              async whenIdle() {},
            },
            async dispose() {},
          }
        },
      },
    },
    bridge: { listTools: async () => [] },
    workspaceRoot: os.tmpdir(),
    telemetry: {
      recordSessionStart() {},
      recordSessionEnd() {},
      recordEvent: (type, detail) => recorded.push({ type, ...detail }),
    },
  })
  const run = { role: 'library_surveyor', prompt: 'Replay a model turn', archiveOnComplete: false }
  const first = await host.spawnAndRunAgent({ ...run, sessionId: 'live', keepAliveAfterIdle: true })
  assert.equal(first.isAbnormalEnd, false)
  assert.deepEqual(recorded, [])

  const resumed = await host.continueAliveAgent('live', run.prompt)
  const short = await host.spawnAndRunAgent({ ...run, sessionId: 'short' })
  for (const result of [resumed, short]) {
    assert.equal(result.isAbnormalEnd, true)
    assert.deepEqual(result.turnEndReason, refusal)
  }
  assert.deepEqual(recorded.map(({ type, sessionId, code }) => [type, sessionId, code]), [
    ['model_content_refused', 'live', 'CONTENT_REFUSED'],
    ['model_content_refused', 'short', 'CONTENT_REFUSED'],
  ])
  await host.disposeAllSessions()
})

test('1. 6套Preset、角色路由与平台感知原生工具白名单', () => {
  assert.equal(ALL_31_MCP_TOOLS.size, 32)
  assert.ok(ROLE_MCP_TOOLS.works_engineer.includes('register_question_instrument'))
  assert.ok(ROLE_MCP_TOOLS.works_engineer.includes('upgrade_instrument_with_calibration'))
  assert.ok(ROLE_MCP_TOOLS.works_engineer.includes('resolve_works_ticket'))

  // 7 角色全映射到 6 套职责极净 Preset
  const presets = Object.keys(PRESET_DEFINITIONS)
  assert.equal(presets.length, 6)
  for (const role of CANONICAL_ROLES) {
    assert.ok(presets.includes(ROLE_TO_PRESET[role]), `角色 ${role} 映射缺失`)
  }
  assert.equal(ROLE_TO_PRESET.logistics_coordinator, 'greatwall-db-only')
  assert.equal(ROLE_TO_PRESET.supervisory_committee, 'greatwall-db-only')
  assert.equal(ROLE_TO_PRESET.library_verifier, 'greatwall-verifier')
  assert.equal(ROLE_TO_PRESET.library_surveyor, 'greatwall-surveyor')

  // 严禁 {{cwd}} 模板变量
  for (const [id, def] of Object.entries(PRESET_DEFINITIONS)) {
    assert.ok(!def.cordisYml.includes('{{cwd}}'), `Preset ${id} 不可包含 {{cwd}}`)
  }

  // 平台感知 Shell 工具与平权矩阵
  assert.equal(resolvePlatformShellTool('win32'), 'pwsh')
  assert.equal(resolvePlatformShellTool('linux'), 'bash')
  assert.deepEqual(resolvePlatformAllowedTools('logistics_coordinator', 'win32'), [])
  assert.deepEqual(resolvePlatformAllowedTools('supervisory_committee', 'linux'), [])
  assert.deepEqual(resolvePlatformAllowedTools('library_verifier', 'win32'), ['read', 'glob', 'grep', 'pwsh'])
  assert.deepEqual(resolvePlatformAllowedTools('library_verifier', 'linux'), ['read', 'glob', 'grep', 'bash'])

  // 声明式 Preset 插件校验：verifier 有只读 fs + 平台 shell，db-only 仅 persona
  const winDefs = Object.fromEntries(buildDeclarativePresetConfigs('win32').map((d) => [d.id, d]))
  const verPlugins = winDefs['greatwall-verifier'].plugins
  assert.equal(verPlugins.find((p) => p.id === 'tool-fs')?.config?.write, false)
  assert.equal(verPlugins.find((p) => p.id === 'tool-pwsh')?.disabled, false)
  assert.equal(verPlugins.find((p) => p.id === 'tool-bash')?.disabled, true)
  assert.deepEqual(winDefs['greatwall-db-only'].plugins.map((p) => p.id), ['persona'])
})

test('2. 平台感知原生工具挂载强断言 (assertRequiredNativeTools)', () => {
  assert.doesNotThrow(() => assertRequiredNativeTools('explorer', ['read', 'write', 'pwsh'], 'win32'))
  assert.throws(() => assertRequiredNativeTools('explorer', ['read', 'write', 'bash'], 'win32'), /pwsh/)
  assert.doesNotThrow(() => assertRequiredNativeTools('library_verifier', ['read', 'bash'], 'linux'))
  assert.throws(() => assertRequiredNativeTools('library_verifier', ['read', 'write', 'pwsh'], 'win32'), /严禁挂载写工具/)
  assert.doesNotThrow(() => assertRequiredNativeTools('logistics_coordinator', [], 'win32'))
  assert.throws(() => assertRequiredNativeTools('supervisory_committee', ['read'], 'win32'), /纯 DB 治理角色/)
})

test('3. 双隔离沙箱 Guard：探索Worktree + 动态只读遗嘱 + 空白盲审沙箱 + 工造司禁改worktrees', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_guard_'))
  try {
    const ws = path.join(tmpRoot, 'ws')
    const wt1 = path.join(ws, 'worktrees', 'b_q1_1')
    const wt2 = path.join(ws, 'worktrees', 'b_q1_2')
    const blindDir = path.join(tmpRoot, 'plugin_data', 'workspaces', 'abc', 'blind_sandboxes', 'blind_sandbox_rev_001')
    const pluginDataDir = path.join(tmpRoot, 'plugin_data', 'workspaces', 'abc')
    fs.mkdirSync(wt1, { recursive: true })
    fs.mkdirSync(wt2, { recursive: true })
    fs.mkdirSync(blindDir, { recursive: true })
    fs.mkdirSync(path.join(ws, 'evaluators', '_hidden_calibrations'), { recursive: true })

    // 3.1 explorer：正常读写 + 动态只读态（70% 亲笔遗嘱回合）
    let expReadonly = false
    const evalExp = createSandboxCallEvaluator({
      role: 'explorer',
      workspaceRoot: ws,
      worktreeAbsPath: wt1,
      protectedDirs: [pluginDataDir],
      readonly: () => expReadonly,
    })
    assert.equal(evalExp({ name: 'write', arguments: { file_path: path.join(wt1, 'cand.py') } }), undefined)
    assert.equal(evalExp({ name: 'pwsh', arguments: { command: 'python cand.py' } }), undefined)
    assert.match(String(evalExp({ name: 'read', arguments: { file_path: path.join(wt2, 'secret.py') } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalExp({ name: 'write', arguments: { file_path: path.join(wt1, 'HANDOFF_note.md') } })), /NO_MD_DOSSIER_POLICY/)
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: 'cat ../b_q1_2/secret.py' } })), /SANDBOX_VIOLATION/)

    // 切至 70% 只读遗嘱态：立刻阻断写文件与 Shell，仍允许只读
    expReadonly = true
    assert.equal(evalExp({ name: 'read', arguments: { file_path: path.join(wt1, 'cand.py') } }), undefined)
    assert.match(String(evalExp({ name: 'write', arguments: { file_path: path.join(wt1, 'cand.py') } })), /只读态/)
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: 'python cand.py' } })), /只读态/)

    // 3.2 library_verifier：锁在空白盲审沙箱，允许只读与本地计算，严禁写/外网/DB/worktrees
    const evalVer = createSandboxCallEvaluator({
      role: 'library_verifier',
      workspaceRoot: ws,
      sandboxAbsPath: blindDir,
      protectedDirs: [pluginDataDir],
    })
    assert.equal(evalVer({ name: 'read', arguments: { file_path: path.join(blindDir, 'artifact.py') } }), undefined)
    assert.equal(evalVer({ name: 'pwsh', arguments: { command: 'python -c "print(1+1)"' } }), undefined)
    assert.match(String(evalVer({ name: 'write', arguments: { file_path: path.join(blindDir, 'x.py') } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalVer({ name: 'read', arguments: { file_path: path.join(wt1, 'cand.py') } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalVer({ name: 'pwsh', arguments: { command: 'curl https://example.com' } })), /物理断网/)
    assert.match(String(evalVer({ name: 'pwsh', arguments: { command: 'python -c "import requests"' } })), /物理断网/)
    assert.match(String(evalVer({ name: 'pwsh', arguments: { command: 'sqlite3 greatwall.db ".tables"' } })), /SANDBOX_VIOLATION/)

    // 3.3 works_engineer：可写 evaluators/ 与 _hidden_calibrations/，严禁改 worktrees/
    const evalWorks = createSandboxCallEvaluator({
      role: 'works_engineer',
      workspaceRoot: ws,
      protectedDirs: [pluginDataDir],
    })
    assert.equal(evalWorks({ name: 'write', arguments: { file_path: path.join(ws, 'evaluators', 'inst.py') } }), undefined)
    assert.equal(
      evalWorks({ name: 'write', arguments: { file_path: path.join(ws, 'evaluators', '_hidden_calibrations', 'c.json') } }),
      undefined,
    )
    assert.match(String(evalWorks({ name: 'write', arguments: { file_path: path.join(wt1, 'cand.py') } })), /严禁修改探索者分支工作树/)

    // 3.4 纯 DB 角色：拒一切原生工具，放行 31 窄工具
    const evalLog = createSandboxCallEvaluator({ role: 'logistics_coordinator', workspaceRoot: ws })
    assert.match(String(evalLog({ name: 'read', arguments: { file_path: path.join(ws, 'a.txt') } })), /0 原生工具/)
    assert.equal(evalLog({ name: 'triage_node', arguments: {} }), undefined)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('4. 500k 物理时钟（无 eval_count 门槛）与 Stage 1 REVISE/REFUTED 回合收尾', () => {
  // 零观测纯推导节点在 37% 照常触发 REFLECT_37
  assert.equal(evaluateContextClockTrigger({ pressureTokens: 184_999, firstReflectionUnlocked: false }).trigger, null)
  assert.equal(evaluateContextClockTrigger({ pressureTokens: 185_000, firstReflectionUnlocked: false }).trigger, 'REFLECT_37')
  assert.equal(evaluateContextClockTrigger({ pressureTokens: 200_000, firstReflectionUnlocked: true }).trigger, null)
  assert.equal(evaluateContextClockTrigger({ pressureTokens: 350_000, firstReflectionUnlocked: true }).trigger, 'HANDOFF_70')

  // 采样器优先 sessionProjections，降级 tokenMeter
  const fakeCtx = {
    sessionProjections: {
      snapshot: () => ({ values: { contextPressure: { projectedTokens: 192_000, contextWindow: 500_000 } } }),
    },
  }
  const s1 = sampleAgentContextPressure(fakeCtx, { session: { id: 's1' } })
  assert.equal(s1.pressureTokens, 192_000)
  assert.equal(s1.source, 'sessionProjections.contextPressure')

  // Stage 1 判 PASS 不中断（继续 Stage 2）；REVISE / REFUTED 立即收尾
  assert.equal(shouldConcludeTurnAfterTool('submit_stage1_blind_ledger', { ok: true, data: { stage1_verdict: 'PASS' } }), false)
  assert.equal(shouldConcludeTurnAfterTool('submit_stage1_blind_ledger', { ok: true, data: { stage1_verdict: 'REVISE' } }), true)
  assert.equal(shouldConcludeTurnAfterTool('submit_stage1_blind_ledger', { ok: true, data: { stage1_verdict: 'REFUTED' } }), true)
  assert.equal(shouldConcludeTurnAfterTool('submit_node_handoff', { ok: true }), true)
})

test('5. GreatwallMcpBridge 分级超时与 Python 31 窄工具实时握手冒烟', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_bridge_'))
  const ws = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'data')
  fs.mkdirSync(ws, { recursive: true })
  const bridge = new GreatwallMcpBridge({
    corePythonRoot: CORE_PYTHON_ROOT,
    workspaceRoot: ws,
    dataDir,
    requestTimeoutMs: 60_000,
    longToolTimeoutMs: 300_000,
  })
  try {
    assert.equal(bridge.resolveToolTimeoutMs('get_logistics_dashboard', {}), 60_000)
    assert.equal(bridge.resolveToolTimeoutMs('run_isolated_eval', { tier: 'probe' }), 60_000)
    assert.equal(bridge.resolveToolTimeoutMs('run_isolated_eval', { tier: 'official' }), 300_000)
    assert.equal(bridge.resolveToolTimeoutMs('upgrade_instrument_with_calibration', {}), 300_000)
    assert.equal(bridge.resolveControlTimeoutMs('control_plane/schedule_snapshot'), 60_000)
    assert.equal(bridge.resolveControlTimeoutMs('control_plane/recover_heavy_jobs'), 300_000)

    const tools = await bridge.listTools()
    assert.equal(tools.length, 32)
    const snap = await bridge.control('control_plane/schedule_snapshot', {})
    assert.equal(snap?.ok, true)
    assert.equal(snap?.data?.stage, 'STAGE1_PARSE0')
  } finally {
    await bridge.dispose()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('6. pair_lifecycle 单节点同会话伴随暂停续传与 70% 两步清醒交接', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_pair_'))
  try {
    const wt = path.join(tmpRoot, 'wt')
    fs.mkdirSync(wt, { recursive: true })
    const node = { node_id: 'node_q1_01', branch_id: 'b_q1_1', question_id: 'Q1', worktree_abs_path: wt }

    const events = []
    const readonlyStates = new Map()
    const liveSessions = new Map()
    const disposedIds = []

    const fakeOrch = {
      liveSessions,
      _nodeCompanionSessions: new Map(),
      _pendingSalvageNodes: new Map(),
      _handoffsSinceHeartbeat: 0,
      host: {
        setSessionReadonly(sid, flag) {
          readonlyStates.set(sid, flag)
          events.push({ type: 'setReadonly', sid, flag })
        },
        async archiveSession(sid) {
          events.push({ type: 'archive', sid })
        },
      },
      _formatInterventionsForTarget: () => '',
      _appendInterventions: (t) => t,
      async spawnAndRunAgent(opts) {
        const sid = opts.sessionId || `s_${opts.role}_${events.length}`
        events.push({ type: 'spawn', role: opts.role, sid, keepAlive: opts.keepAliveAfterIdle })
        const res = {
          sessionId: sid,
          role: opts.role,
          turnSignals: opts.role === 'explorer' ? [{ trigger: 'REFLECT_37' }] : [],
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'blackbox',
          lastAssistantText: opts.role === 'lineage_companion' ? '请说明核心边界假设？' : 'initial',
          handle: { agent: { session: { id: sid } } },
          async dispose(st) {
            liveSessions.delete(sid)
            disposedIds.push({ sid, role: opts.role, st })
          },
        }
        if (opts.keepAliveAfterIdle) liveSessions.set(sid, { role: opts.role, turnSignals: res.turnSignals })
        return res
      },
      async continueAliveAgent(sid, promptText) {
        const sess = liveSessions.get(sid)
        events.push({ type: 'continue', role: sess?.role, sid, promptHead: promptText.slice(0, 28) })
        if (sess?.role === 'lineage_companion' && promptText.includes('探索者 Round 1')) {
          sess.turnSignals.push({ toolName: 'record_reflection_and_unlock_pull' })
        }
        if (sess?.role === 'explorer' && promptText.includes('37–70% 深度攻坚')) {
          sess.turnSignals.push({ trigger: 'HANDOFF_70' })
        }
        return {
          lastAssistantText: sess?.role === 'explorer' ? '亲笔遗嘱：边界已收紧，建议下代检验极值点。' : '已诊断并解锁',
          blackboxSummary: 'blackbox_v2',
          turnSignals: sess?.turnSignals || [],
          nativeThresholds: [],
          isAbnormalEnd: false,
        }
      },
    }

    // 1) PRE_SPAWN：创建伴随并保活
    const compPre = await runPreSpawnBriefingWithCompanion(fakeOrch, node)
    assert.ok(fakeOrch._nodeCompanionSessions.has(node.node_id))

    // 2) 探索 -> 37% 续传同一个伴随 -> 70% 探索者切只读亲笔遗嘱 -> 续传同一个伴随交接 -> 彻底销毁伴随
    await driveExplorerCompanionPair(fakeOrch, node, { goal_and_completion_md: '# Goal' }, 'exp_sid_1')

    const compSpawns = events.filter((e) => e.type === 'spawn' && e.role === 'lineage_companion')
    const compContinues = events.filter((e) => e.type === 'continue' && e.role === 'lineage_companion')
    assert.equal(compSpawns.length, 1, '同节点 PRE_SPAWN -> 37% -> 70% 应仅启动 1 个伴随会话')
    assert.ok(compContinues.every((e) => e.sid === compPre.sessionId), '所有续传必须命中同一个伴随 sessionId')
    assert.equal(readonlyStates.get('exp_sid_1'), true, '70% 收官前探索者必须被动态置为只读态')
    assert.equal(fakeOrch._nodeCompanionSessions.has(node.node_id), false, '节点结束后伴随句柄必须清空，严禁跨代常驻')
    assert.ok(disposedIds.some((d) => d.sid === compPre.sessionId), '伴随必须被显式 dispose')
    assert.equal(fakeOrch._handoffsSinceHeartbeat, 1)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('7. selectDispatchableExplorers 防抢跑硬锁、红灯不停摆与 human_stop 拦截', () => {
  const snap = {
    slot_cap: 4,
    human_stop_active: false,
    triage_locked_branches: ['b_locked'],
    ambiguous_spec_alerts: [{ alert_id: 'ca_1', notes: '口径存在二义性红灯，但按已签基线不停机' }],
    explorers_ready_to_run: [
      { node_id: 'n_locked', branch_id: 'b_locked' },
      { node_id: 'n_ok_1', branch_id: 'b_free_1' },
      { node_id: 'n_running', branch_id: 'b_free_2' },
      { node_id: 'n_ok_2', branch_id: 'b_free_3' },
    ],
  }
  const picked = selectDispatchableExplorers(snap, new Set(['n_running']))
  assert.deepEqual(picked.map((n) => n.node_id), ['n_ok_1', 'n_ok_2'])

  // human_stop_active 置 true 后停止新派单
  const stopped = selectDispatchableExplorers({ ...snap, human_stop_active: true }, new Set())
  assert.deepEqual(stopped, [])
})

test('8. 无阈值绝不跳过 37% 提前交接 + 70% 只读禁写/评测 MCP + 亲笔遗嘱持久化', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_noshortcut_'))
  try {
    const wt = path.join(tmpRoot, 'wt')
    fs.mkdirSync(wt, { recursive: true })
    const node = {
      node_id: 'node_q1_99',
      branch_id: 'b_q1_9',
      question_id: 'Q1',
      worktree_abs_path: wt,
      briefing_snapshot_md: '#### 1. 核心机制\nBRIEF_BODY_MARKER',
      lane_assignment: 'EXPLORATION: 测试五车道透传',
    }

    // 1) 验证 70% 只读态同步拦死 run_isolated_eval / request_literature_survey
    let ro = true
    const evalExp = createSandboxCallEvaluator({
      role: 'explorer',
      workspaceRoot: tmpRoot,
      worktreeAbsPath: wt,
      readonly: () => ro,
    })
    assert.match(String(evalExp({ name: 'run_isolated_eval', arguments: {} })), /只读态/)
    assert.match(String(evalExp({ name: 'request_literature_survey', arguments: {} })), /只读态/)
    assert.equal(evalExp({ name: 'query_library_catalog', arguments: {} }), undefined)

    // 2) 验证探索者首轮未触 37% 时绝不直接切只读收官，必须续推并在触达 37% -> 70% 后才持久化遗嘱
    let expTurn = 0
    let receivedTaskCtx = ''
    const persistedCalls = []
    const sequence = []
    const liveSessions = new Map()

    const fakeOrch = {
      workspaceRoot: tmpRoot,
      liveSessions,
      _nodeCompanionSessions: new Map(),
      _pendingSalvageNodes: new Map(),
      _handoffsSinceHeartbeat: 0,
      bridge: {
        async control(method, params) {
          persistedCalls.push({ method, params })
          return { ok: true }
        },
      },
      host: {
        setSessionReadonly(sid, flag) {
          sequence.push(`setReadonly:${flag}`)
        },
        async archiveSession() {},
      },
      _formatInterventionsForTarget: () => '',
      _appendInterventions: (t) => t,
      async spawnAndRunAgent(opts) {
        const sid = opts.sessionId || `s_${opts.role}`
        if (opts.role === 'explorer') {
          receivedTaskCtx = opts.taskContextText || ''
          expTurn += 1
          sequence.push('explorer:turn1:no_threshold')
        } else {
          sequence.push(`companion:${opts.prompt.slice(0, 14)}`)
        }
        const sigs = []
        if (opts.keepAliveAfterIdle) liveSessions.set(sid, { role: opts.role, turnSignals: sigs })
        return {
          sessionId: sid,
          role: opts.role,
          turnSignals: sigs,
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'bb',
          lastAssistantText: 'reply',
          handle: { agent: { session: { id: sid } } },
          async dispose() { liveSessions.delete(sid) },
        }
      },
      async continueAliveAgent(sid, promptText) {
        const sess = liveSessions.get(sid)
        if (sess?.role === 'explorer') {
          if (promptText.includes('70% 清醒收官')) {
            sequence.push('explorer:will_turn')
            return { lastAssistantText: '亲笔遗嘱正文_PERSISTED', blackboxSummary: 'bb_final', turnSignals: sess.turnSignals, nativeThresholds: [], isAbnormalEnd: false }
          }
          expTurn += 1
          if (expTurn === 2) {
            sequence.push('explorer:turn2:hit_37')
            sess.turnSignals.push({ trigger: 'REFLECT_37' })
          } else if (expTurn === 3) {
            sequence.push('explorer:turn3:hit_70')
            sess.turnSignals.push({ trigger: 'HANDOFF_70' })
          }
        } else if (sess?.role === 'lineage_companion') {
          if (promptText.includes('探索者 Round 1')) {
            sess.turnSignals.push({ toolName: 'record_reflection_and_unlock_pull' })
          }
        }
        return { lastAssistantText: 'ok', blackboxSummary: 'bb', turnSignals: sess?.turnSignals || [], nativeThresholds: [], isAbnormalEnd: false }
      },
    }

    await driveExplorerCompanionPair(fakeOrch, node, { goal_and_completion_md: '# Goal' }, 'exp_noshortcut')

    assert.ok(receivedTaskCtx.includes('BRIEF_BODY_MARKER'), '探索者上下文必须包含五段看板正文')
    assert.ok(receivedTaskCtx.includes('EXPLORATION: 测试五车道透传'), '探索者上下文必须包含五车道指令')
    assert.ok(sequence.indexOf('explorer:turn2:hit_37') > sequence.indexOf('explorer:turn1:no_threshold'), '首轮无阈值必须续推，不可跳过 37%')
    assert.ok(sequence.indexOf('setReadonly:true') > sequence.indexOf('explorer:turn3:hit_70'), '必须触达 70% 后才切只读收官')
    const persistWill = persistedCalls.find((c) => c.method === 'control_plane/record_pending_handoff')
    assert.ok(persistWill, '探索者写完遗嘱销毁前必须持久化 pending_handoff 至 SQLite')
    assert.equal(persistWill.params.explorer_will_md, '亲笔遗嘱正文_PERSISTED')
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('9. console_routes 写操作严格校验目标工作区，严禁兜底误杀隔壁工作区', () => {
  const wsA = path.resolve('/tmp/gw_ws_a')
  const wsB = path.resolve('/tmp/gw_ws_b')
  const map = new Map([[wsB.toLowerCase(), { workspaceRoot: wsB, orchestrator: { _poolState: 'running' } }]])

  // 只读状态查询允许兜底
  const readFound = pickController({ activeControllersByWs: map, reqWorkspaceRoot: wsA, allowFallback: true })
  assert.equal(readFound?.workspaceRoot, wsB)

  // 写控制操作（stop / human_stop / intervene）显式指定 wsA 但仅运行 wsB 时，必须返回 null 拒绝误杀！
  const writeFound = pickController({ activeControllersByWs: map, reqWorkspaceRoot: wsA, allowFallback: false })
  assert.equal(writeFound, null)
})

test('10. 不跑到 70% 不停工（>8 轮续推不强切）+ 37% 未真解锁时不谎称解锁', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_no8cap_'))
  const wt = path.join(tmpRoot, 'wt')
  fs.mkdirSync(wt, { recursive: true })
  try {
    const node = {
      node_id: 'n_long',
      branch_id: 'b_long',
      question_id: 'Q1',
      worktree_abs_path: wt,
      briefing_snapshot_md: '五段看板',
      lane_assignment: '',
    }
    let expTurn = 0
    const explorerPrompts = []
    const liveSessions = new Map()
    const fakeOrch = {
      workspaceRoot: tmpRoot,
      liveSessions,
      _nodeCompanionSessions: new Map(),
      _pendingSalvageNodes: new Map(),
      _handoffsSinceHeartbeat: 0,
      telemetry: { recordEvent() {} },
      bridge: {
        async control(method) {
          if (method === 'control_plane/schedule_snapshot') {
            return { ok: true, data: { explorers_ready_to_run: [{ node_id: 'n_long', reflect_unlocked: false }] } }
          }
          return { ok: true }
        },
      },
      host: {
        setSessionReadonly() {},
        async archiveSession() {},
      },
      _formatInterventionsForTarget: () => '',
      _appendInterventions: (t) => t,
      async spawnAndRunAgent(opts) {
        const sid = opts.sessionId || `s_${opts.role}`
        if (opts.role === 'explorer') expTurn += 1
        const sigs = []
        if (opts.keepAliveAfterIdle) liveSessions.set(sid, { role: opts.role, turnSignals: sigs })
        return {
          sessionId: sid,
          role: opts.role,
          turnSignals: sigs,
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'bb',
          lastAssistantText: 'ok',
          handle: { agent: { session: { id: sid } } },
          async dispose() { liveSessions.delete(sid) },
        }
      },
      async continueAliveAgent(sid, promptText) {
        const sess = liveSessions.get(sid)
        if (sess?.role === 'explorer') {
          explorerPrompts.push(promptText)
          if (promptText.includes('70% 清醒收官')) {
            return { lastAssistantText: '11轮后亲笔遗嘱', blackboxSummary: 'bb', turnSignals: sess.turnSignals, nativeThresholds: [], isAbnormalEnd: false }
          }
          expTurn += 1
          if (expTurn === 2) {
            sess.turnSignals.push({ trigger: 'REFLECT_37' })
          } else if (expTurn === 11) {
            sess.turnSignals.push({ trigger: 'HANDOFF_70' })
          }
        }
        // 故意让伴随在 37% 问答中不调用 record_reflection_and_unlock_pull
        return { lastAssistantText: 'companion_reply_no_unlock', blackboxSummary: 'bb', turnSignals: sess?.turnSignals || [], nativeThresholds: [], isAbnormalEnd: false }
      },
    }

    await driveExplorerCompanionPair(fakeOrch, node, { goal_and_completion_md: '# Goal' }, 'exp_long')

    assert.equal(expTurn, 11, '不到 70% 严禁在第 8 轮强行停工，必须持续推到第 11 轮触达 HANDOFF_70')
    assert.ok(
      explorerPrompts.some((p) => p.includes('暂未完成服务端内藏解锁')),
      '37% 问答未真正调用解锁工具时，严禁向探索者谎称已解锁',
    )
    assert.ok(
      !explorerPrompts.some((p) => p.includes('伴随助手已完成 37% 专家诊断并解锁内藏')),
      '未真正解锁时绝不能发送"已完成 37% 专家诊断并解锁内藏"',
    )
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('11. closure_gate 预算/结项达标时停止派发新探索者', () => {
  const snap = {
    human_stop_active: false,
    slot_cap: 4,
    triage_locked_branches: [],
    closure_gate: { closure_allowed: true, gate_code: 'GATE_PASSED_PARTIAL_BUDGET' },
    explorers_ready_to_run: [{ node_id: 'n1', branch_id: 'b1' }],
  }
  assert.deepEqual(selectDispatchableExplorers(snap, new Set()), [])
})

test('12. orchestrator 连续快照失败进入 error 退出，绝不假报 CLOSED_VERIFIED', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_snaperr_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    const events = []
    const states = []
    const stages = []
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: {
        async control(method) {
          if (method === 'control_plane/recover_heavy_jobs') return { ok: true, data: {} }
          if (method === 'control_plane/schedule_snapshot') return { ok: false, error: 'sqlite busy' }
          return { ok: true, data: {} }
        },
      },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })
    orch._poolState = 'running'
    orch._loopAbortController = new AbortController()
    orch._waitWakeOrTimeout = async () => {}
    orch.telemetry.recordEvent = (kind, data) => events.push({ kind, data })
    orch.telemetry.setOrchestratorState = (st) => states.push(st)
    orch.telemetry.setStage = (sg) => stages.push(sg)

    await orch._runAsyncEventPool()

    assert.equal(orch._poolState, 'error')
    assert.ok(events.some((e) => e.kind === 'orchestrator_snapshot_error'))
    assert.ok(states.includes('error'))
    assert.ok(!stages.includes('CLOSED_VERIFIED'), '快照报错绝不可伪造 CLOSED_VERIFIED')
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('13. getControlStatus 暴露 kernelAlive 与 lastError，绝不假健康', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_health_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: {
        async control() {
          throw new Error('python kernel crashed (EPIPE)')
        },
      },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })
    const st = await orch.getControlStatus()
    assert.equal(st.kernelAlive, false)
    assert.match(String(st.lastError), /EPIPE/)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('14. pause 后再 start 复用原循环不双开 + _waitWakeOrTimeout 无泄漏', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_pause_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: {
        async control(method) {
          if (method === 'control_plane/schedule_snapshot') {
            return { ok: true, data: { initialized: true, parse0_signed: true, stage: 'STAGE2_EVOLVE', closure_state: { status: 'OPEN' } } }
          }
          return { ok: true, data: {} }
        },
      },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })

    // 1) 连续 20 次超时等待后 _wakeResolvers 必须为 0（零泄漏）
    for (let i = 0; i < 20; i += 1) {
      await orch._waitWakeOrTimeout(1)
    }
    assert.equal(orch._wakeResolvers.size, 0, '超时后必须清理 _wakeResolvers 避免长跑内存泄漏')

    // 2) start -> pause -> start 绝不可启动第二条事件池
    let loopsStarted = 0
    let releaseLoop = null
    orch._runAsyncEventPool = async () => {
      loopsStarted += 1
      await new Promise((resolve) => {
        releaseLoop = resolve
      })
    }
    const r1 = await orch.startBackground({
      agentOptions: { provider: 'deepseek-account', model: 'deepseek-flash' },
    })
    assert.equal(r1.started, true)
    assert.equal(r1.alreadyRunning, false)
    assert.equal(loopsStarted, 1)

    orch.pauseBackground()
    assert.equal(orch._poolState, 'paused')

    const r2 = await orch.startBackground()
    assert.equal(r2.started, true)
    assert.equal(r2.alreadyRunning, true)
    assert.equal(r2.resumed, true)
    assert.equal(orch._poolState, 'running')
    assert.equal(loopsStarted, 1, 'pause 后再 start 必须复用原循环，严禁起第二条并发循环')

    releaseLoop?.()
    await orch.stopBackground('TEST_DONE')
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('15. 未签 Parse 0 禁止 start 空转 + TelemetryCollector 跨重建保留 countersByRole', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_nop0_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: {
        async control(method) {
          if (method === 'control_plane/schedule_snapshot') {
            return { ok: true, data: { initialized: false, parse0_signed: false, stage: 'STAGE1_PARSE0', closure_state: { status: 'OPEN' } } }
          }
          return { ok: true, data: {} }
        },
      },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })
    const res = await orch.startBackground({
      agentOptions: { provider: 'deepseek-account', model: 'deepseek-flash' },
    })
    assert.equal(res.started, false)
    assert.equal(res.blocked, 'NEED_PARSE0_SIGNATURE')
    assert.equal(orch._poolState, 'idle')

    // TelemetryCollector 跨重建必须保留 countersByRole
    const t1 = new TelemetryCollector({ workspaceRoot: tmpRoot, dataDir })
    t1.recordSessionStart({ sessionId: 's1', role: 'explorer' })
    t1.recordSessionStart({ sessionId: 's2', role: 'lineage_companion' })
    const t2 = new TelemetryCollector({ workspaceRoot: tmpRoot, dataDir })
    assert.equal(t2.getSummary().countersByRole.explorer?.total, 1)
    assert.equal(t2.getSummary().countersByRole.lineage_companion?.total, 1)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('16. _launchGovTask 失败进入冷却且不立刻 _wakeLoop()，防紧循环空转', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_govcool_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: { async control() { return { ok: true, data: {} } } },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })
    let wakes = 0
    orch._wakeLoop = () => { wakes += 1 }
    let calls = 0
    const launched1 = orch._launchGovTask('works:queue', async () => {
      calls += 1
      throw new Error('instant spawn error')
    })
    assert.equal(launched1, true)
    await new Promise((r) => setTimeout(r, 20))
    assert.equal(calls, 1)
    assert.equal(wakes, 0, '治理任务失败时不应该立刻 _wakeLoop() 触发紧循环')

    // 冷却期内再次尝试拉起同一 taskKey 必须被跳过
    const launched2 = orch._launchGovTask('works:queue', async () => { calls += 1 })
    assert.equal(launched2, false)
    assert.equal(calls, 1)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('17. 显式模型绑定拒启 (MISSING_MODEL_BINDING) + 主控事件流模型继承与 272k 自适应窗口', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_modelbind_'))
  const dataDir = path.join(tmpRoot, 'data')
  try {
    // 1) 无任何模型绑定 -> 必拒启 MISSING_MODEL_BINDING
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: {
        async control() {
          return { ok: true, data: { initialized: true, parse0_signed: true, stage: 'STAGE2_EVOLVE', closure_state: { status: 'OPEN' } } }
        },
      },
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: tmpRoot,
      dataDir,
    })
    const blocked = await orch.startBackground()
    assert.equal(blocked.started, false)
    assert.equal(blocked.blocked, 'MISSING_MODEL_BINDING')
    assert.equal(orch._poolState, 'idle')

    // 2) 从主控会话事件流 (model/selection + request/context) 自动继承真实模型与 272k 窗口
    const fakeCaller = {
      id: 'ptc_sess',
      options: {},
      session: {
        snapshotEvents: () => [
          { type: 'model/selection', data: { provider: 'deepseek-account', model: 'deepseek-flash' } },
          { type: 'request/context', data: { provider: 'deepseek-account', model: 'deepseek-flash', contextWindow: 272_000 } },
        ],
      },
    }
    const evBind = extractModelBindingFromEvents(fakeCaller.session.snapshotEvents())
    assert.equal(evBind.provider, 'deepseek-account')
    assert.equal(evBind.model, 'deepseek-flash')
    assert.equal(evBind.contextWindow, 272_000)

    const resolved = await resolveAuthoritativeModelBinding({ callerAgent: fakeCaller, runtimeDefaultWindow: 500_000 })
    assert.equal(resolved.ok, true)
    assert.equal(resolved.provider, 'deepseek-account')
    assert.equal(resolved.model, 'deepseek-flash')
    assert.equal(resolved.effectiveContextWindow, 272_000)

    // 1M 模型钳位至 500k
    assert.equal(resolveEffectiveContextWindow({ modelWindow: 1_000_000, runtimeDefaultWindow: 500_000 }), 500_000)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('18. 双向沙箱放行公开输入/https URL/dsh-spill-*，严防内部向外部逃逸', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_bisandbox_'))
  try {
    const ws = path.join(tmpRoot, 'ws')
    const wt = path.join(ws, 'worktrees', 'b_q1_1')
    const probDir = path.join(ws, 'problem_pack')
    const evalDir = path.join(ws, 'evaluators')
    const hiddenDir = path.join(ws, '_hidden_calibrations')
    const spillFile = path.join(os.tmpdir(), 'dsh-spill-abc123', 'out.txt')
    fs.mkdirSync(wt, { recursive: true })
    fs.mkdirSync(probDir, { recursive: true })
    fs.mkdirSync(evalDir, { recursive: true })
    fs.mkdirSync(hiddenDir, { recursive: true })
    fs.mkdirSync(path.dirname(spillFile), { recursive: true })
    fs.writeFileSync(path.join(probDir, 'q.md'), '# Q1')
    fs.writeFileSync(spillFile, 'spilled')

    const evalExp = createSandboxCallEvaluator({
      role: 'explorer',
      workspaceRoot: ws,
      worktreeAbsPath: wt,
      protectedDirs: [path.join(tmpRoot, 'plugin_data')],
    })
    // 公开输入与 dsh-spill-* 只读放行；写公开输入（含工作树内 inputs/ 副本）禁止
    assert.equal(evalExp({ name: 'read', arguments: { file_path: path.join(probDir, 'q.md') } }), undefined)
    assert.equal(evalExp({ name: 'read', arguments: { file_path: spillFile } }), undefined)
    assert.match(String(evalExp({ name: 'write', arguments: { file_path: path.join(probDir, 'q.md') } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalExp({ name: 'write', arguments: { file_path: path.join(wt, 'inputs', 'q.md') } })), /SANDBOX_VIOLATION/)
    // 严拦 evaluators/ 与 _hidden_calibrations/
    assert.match(String(evalExp({ name: 'read', arguments: { file_path: path.join(evalDir, 'eval.py') } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalExp({ name: 'read', arguments: { file_path: path.join(hiddenDir, 'c.json') } })), /SANDBOX_VIOLATION/)

    // 盲审官仅限独立空白沙箱内只读（不可越界读主工作区事后新增的 rulings/）
    const rulingsDir = path.join(ws, 'rulings')
    const blindDir = path.join(tmpRoot, 'plugin_data', 'blind_sandbox_rev_001')
    fs.mkdirSync(rulingsDir, { recursive: true })
    fs.mkdirSync(blindDir, { recursive: true })
    fs.writeFileSync(path.join(rulingsDir, 'ruling_new.md'), '# v1')
    const evalVer = createSandboxCallEvaluator({
      role: 'library_verifier',
      workspaceRoot: ws,
      sandboxAbsPath: blindDir,
      protectedDirs: [path.join(tmpRoot, 'plugin_data')],
    })
    assert.match(String(evalVer({ name: 'read', arguments: { file_path: path.join(rulingsDir, 'ruling_new.md') } })), /SANDBOX_VIOLATION/)
    assert.equal(evalVer({ name: 'read', arguments: { file_path: spillFile } }), undefined)

    // surveyor web_fetch https:// 零误杀
    const evalSurv = createSandboxCallEvaluator({
      role: 'library_surveyor',
      workspaceRoot: ws,
      protectedDirs: [path.join(tmpRoot, 'plugin_data')],
    })
    assert.equal(evalSurv({ name: 'web_fetch', arguments: { url: 'https://arxiv.org/abs/2401.00001' } }), undefined)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('19. GovernanceItemCircuitBreaker 单待办熔断：分步进展不误杀、2次无进展仅熔断单项、状态变化自动复位', () => {
  const cb = new GovernanceItemCircuitBreaker(2)
  // 第 1 次调度：tkt_stuck 无变化 (count=1)，tkt_progress 指纹变化 (count=0)
  let res = cb.evaluateBatch(
    [
      { key: 'works:ticket:tkt_stuck', beforeFp: 'v1' },
      { key: 'works:ticket:tkt_progress', beforeFp: 'p1' },
    ],
    new Map([
      ['works:ticket:tkt_stuck', 'v1'],
      ['works:ticket:tkt_progress', 'p2'],
    ]),
  )
  assert.equal(cb.isBroken('works:ticket:tkt_stuck', 'v1'), false)
  assert.equal(cb.isBroken('works:ticket:tkt_progress', 'p2'), false)
  assert.equal(res.find((r) => r.key === 'works:ticket:tkt_progress')?.stalledCount, 0)

  // 第 2 次调度：tkt_stuck 仍无变化 -> 熔断；tkt_progress 仍在推进 -> 绝不连坐！
  res = cb.evaluateBatch(
    [
      { key: 'works:ticket:tkt_stuck', beforeFp: 'v1' },
      { key: 'works:ticket:tkt_progress', beforeFp: 'p2' },
    ],
    new Map([
      ['works:ticket:tkt_stuck', 'v1'],
      ['works:ticket:tkt_progress', 'p3'],
    ]),
  )
  assert.equal(res.find((r) => r.key === 'works:ticket:tkt_stuck')?.newlyBroken, true)
  assert.equal(cb.isBroken('works:ticket:tkt_stuck', 'v1'), true)
  assert.equal(cb.isBroken('works:ticket:tkt_progress', 'p3'), false)

  // 若 tkt_stuck 的外部指纹发生变化（如人类或他工具改动）-> 自动复位解除熔断
  assert.equal(cb.isBroken('works:ticket:tkt_stuck', 'v2_changed'), false)
})

test('20. 防僵尸探索者核查：DB 节点置 CLOSED 后下一轮立即停推并同时销毁探索者与私有伴随', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_zombie_'))
  const wt = path.join(tmpRoot, 'wt')
  fs.mkdirSync(wt, { recursive: true })
  try {
    const node = { node_id: 'n_zombie', branch_id: 'b_z', question_id: 'Q1', worktree_abs_path: wt }
    let continueCalls = 0
    const disposed = []
    const liveSessions = new Map()
    const compHandle = {
      sessionId: 'comp_z_1',
      async dispose(st) {
        liveSessions.delete('comp_z_1')
        disposed.push({ role: 'lineage_companion', st })
      },
    }
    liveSessions.set('comp_z_1', { role: 'lineage_companion' })

    const fakeOrch = {
      workspaceRoot: tmpRoot,
      _poolState: 'running',
      liveSessions,
      _nodeCompanionSessions: new Map([['n_zombie', compHandle]]),
      _handoffsSinceHeartbeat: 0,
      telemetry: { recordEvent() {} },
      bridge: {
        async control(method) {
          if (method === 'control_plane/sync_pressure') {
            return { ok: true, data: { node_status: 'CLOSED', pressure_tokens: 10000, effective_context_window: 272000 } }
          }
          return { ok: true }
        },
      },
      host: {
        effectiveContextWindow: 272000,
        setSessionReadonly() {},
        async archiveSession() {},
      },
      async spawnAndRunAgent(opts) {
        const sid = opts.sessionId
        liveSessions.set(sid, { role: opts.role })
        return {
          sessionId: sid,
          role: opts.role,
          turnSignals: [],
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'bb',
          lastAssistantText: 'turn1',
          handle: { agent: { session: { id: sid } } },
          async dispose(st) {
            liveSessions.delete(sid)
            disposed.push({ role: opts.role, st })
          },
        }
      },
      async continueAliveAgent() {
        continueCalls += 1
        return { lastAssistantText: 'should_not_run', turnSignals: [], nativeThresholds: [], isAbnormalEnd: false }
      },
    }

    await driveExplorerCompanionPair(fakeOrch, node, { goal_and_completion_md: '# G' }, 'exp_zombie')
    assert.equal(continueCalls, 0, 'DB 节点已置 CLOSED 时，严禁继续调用 continueAliveAgent 占槽续推！')
    assert.equal(fakeOrch._nodeCompanionSessions.has('n_zombie'), false, '私有伴随必须同步销毁释槽')
    assert.ok(disposed.some((d) => d.role === 'explorer' && d.st === 'terminated_external'))
    assert.ok(disposed.some((d) => d.role === 'lineage_companion' && d.st === 'terminated_external'))
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('21. 活跃科研仪器清单自动 Push 给对应子题探索者（屏蔽他题与 UNHEALTHY 仪器）', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_inst_push_'))
  const wt = path.join(tmpRoot, 'wt')
  fs.mkdirSync(wt, { recursive: true })
  try {
    let capturedTaskCtx = ''
    const node = {
      node_id: 'n_inst',
      branch_id: 'b_inst',
      question_id: 'Q1',
      worktree_abs_path: wt,
      briefing_snapshot_md: 'BRIEF_OK',
    }
    const snap = {
      goal_and_completion_md: '# Goal',
      active_instruments: [
        { instrument_id: 'inst_q1_mec', version: 2, question_id: 'Q1', instrument_role: 'VERDICT', artifact_schema: 'python_run', health_status: 'HEALTHY' },
        { instrument_id: 'inst_all_probe', version: 1, question_id: 'ALL', instrument_role: 'PROBE', artifact_schema: 'python_run', health_status: 'HEALTHY' },
        { instrument_id: 'inst_q2_other', version: 1, question_id: 'Q2', instrument_role: 'VERDICT', artifact_schema: 'python_run', health_status: 'HEALTHY' },
        { instrument_id: 'inst_q1_broken', version: 1, question_id: 'Q1', instrument_role: 'PROBE', artifact_schema: 'python_run', health_status: 'UNHEALTHY' },
      ],
    }
    const fakeOrch = {
      workspaceRoot: tmpRoot,
      _poolState: 'running',
      liveSessions: new Map(),
      _nodeCompanionSessions: new Map(),
      _handoffsSinceHeartbeat: 0,
      telemetry: { recordEvent() {} },
      bridge: {
        async control(method) {
          if (method === 'control_plane/sync_pressure') return { ok: true, data: { node_status: 'CLOSED' } }
          return { ok: true }
        },
      },
      host: { effectiveContextWindow: 272000, setSessionReadonly() {}, async archiveSession() {} },
      async spawnAndRunAgent(opts) {
        capturedTaskCtx = opts.taskContextText || ''
        return {
          sessionId: opts.sessionId,
          role: opts.role,
          turnSignals: [],
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'bb',
          lastAssistantText: 'ok',
          handle: { agent: { session: { id: opts.sessionId } } },
          async dispose() {},
        }
      },
      async continueAliveAgent() {
        return { lastAssistantText: 'ok', turnSignals: [], nativeThresholds: [], isAbnormalEnd: false }
      },
    }

    await driveExplorerCompanionPair(fakeOrch, node, snap, 'exp_inst_push')
    assert.ok(capturedTaskCtx.includes('inst_q1_mec'), '必须推送本子题健康仪器 inst_q1_mec')
    assert.ok(capturedTaskCtx.includes('inst_all_probe'), '必须推送全局健康仪器 inst_all_probe')
    assert.ok(!capturedTaskCtx.includes('inst_q2_other'), '不得误推其他子题仪器 inst_q2_other')
    assert.ok(!capturedTaskCtx.includes('inst_q1_broken'), '不得推送已熔断 UNHEALTHY 仪器')
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('22. 子会话自动继承父会话 permissionPresets / sandbox/mode（根治 Windows headless 子会话 pwsh ACL 崩溃）', () => {
  const applied = []
  const parentSession = {
    id: 'parent_1',
    snapshotEvents: () => [
      { type: 'sandbox/mode', data: { mode: 'danger-full-access' } },
      { type: 'approval/policy', data: { policy: 'never' } },
    ],
  }
  const childEvents = []
  const childSession = {
    id: 'child_1',
    append(type, data) {
      childEvents.push({ type, data })
    },
  }

  // 路径 A：permissionPresets 服务可用时，直接通过官方 set 同步
  const hostA = new AgentSessionHost({
    ctx: {
      get(name) {
        if (name === 'permissionPresets') {
          return {
            current: (s) => (s === parentSession ? 'danger-full-access' : 'workspace-write'),
            set: (s, preset) => applied.push({ sid: s.id, preset }),
          }
        }
        return null
      },
    },
    bridge: {},
    workspaceRoot: os.tmpdir(),
    rolePrompts: {},
    parentAgent: { session: parentSession },
    telemetry: { recordEvent() {} },
  })
  hostA._inheritParentPermissionState(childSession)
  assert.deepEqual(applied, [{ sid: 'child_1', preset: 'danger-full-access' }])

  // 路径 B：无 permissionPresets 时，回退同步 sandbox/mode 与 approval/policy 事件
  const hostB = new AgentSessionHost({
    ctx: {
      get(name) {
        if (name === 'sandboxPolicy') {
          return {
            resolve: ({ session }) => ({ mode: session === parentSession ? 'danger-full-access' : 'workspace-write' }),
          }
        }
        return null
      },
    },
    bridge: {},
    workspaceRoot: os.tmpdir(),
    rolePrompts: {},
    parentAgent: { session: parentSession },
    telemetry: { recordEvent() {} },
  })
  hostB._inheritParentPermissionState(childSession)
  assert.ok(childEvents.some((e) => e.type === 'sandbox/mode' && e.data.mode === 'danger-full-access'))
  assert.ok(childEvents.some((e) => e.type === 'approval/policy' && e.data.policy === 'never'))
})

test('23. 4处Preset定义100%对齐 complete:false + AgentSessionHost 白名单防全局污染且保留 required 上下文', async () => {
  // 1) JS 声明式 Preset
  for (const def of buildDeclarativePresetConfigs('win32')) {
    const persona = def.plugins.find((p) => p.id === 'persona')
    assert.equal(persona?.config?.complete, false, `${def.id} declarative persona 必须为 complete:false`)
    assert.equal(persona?.config?.includeRuntimeContext, false, `${def.id} 必须保持 includeRuntimeContext:false`)
  }
  // 2) PRESET_DEFINITIONS YAML 模板
  for (const [id, def] of Object.entries(PRESET_DEFINITIONS)) {
    assert.ok(def.cordisYml.includes('complete: false'), `${id} PRESET_DEFINITIONS 必须含 complete: false`)
    assert.ok(!def.cordisYml.includes('complete: true'), `${id} PRESET_DEFINITIONS 严禁残留 complete: true`)
  }
  // 3) cordis.patch.yml 与 dsh_plugin/presets/*/agent.cordis.yml
  const patchYml = fs.readFileSync(path.resolve(__dirname, '..', 'cordis.patch.yml'), 'utf8')
  assert.ok(!patchYml.includes('complete: true'), 'cordis.patch.yml 严禁残留 complete: true')
  for (const id of Object.keys(PRESET_DEFINITIONS)) {
    const pFile = path.resolve(__dirname, '..', 'presets', id, 'agent.cordis.yml')
    const txt = fs.readFileSync(pFile, 'utf8')
    assert.ok(txt.includes('complete: false'), `${pFile} 必须含 complete: false`)
    assert.ok(!txt.includes('complete: true'), `${pFile} 严禁残留 complete: true`)
  }

  // 4) AgentSessionHost 注册 interpolate:false + required:true 及 assemble 白名单防第三方插件污染
  const regSections = []
  const regContexts = []
  let assembleHook = null
  const fakeAgentCtx = {
    tools: {
      schemas: () => [],
      restrict() {},
      guard: () => () => {},
      register: () => () => {},
    },
    systemPrompt: {
      section(s) { regSections.push(s); return () => {} },
      context(c) { regContexts.push(c); return () => {} },
    },
    on(ev, fn) {
      if (ev === 'system-prompt/assemble') assembleHook = fn
      return () => {}
    },
  }
  const host = new AgentSessionHost({
    ctx: { on: () => () => {} },
    bridge: {},
    workspaceRoot: os.tmpdir(),
    rolePrompts: { explorer: '# Explorer Contract with {{formula}}' },
    telemetry: { recordEvent() {} },
  })
  host.mountCapabilitiesOnAgent(fakeAgentCtx, { id: 'exp_test_1', session: { id: 'exp_test_1' } }, {
    role: 'explorer',
    nodeId: 'n1',
    cwd: os.tmpdir(),
    toolSchemas: [],
    taskContextText: '## Task with {{x}}',
    cleanupFns: [],
    turnSignals: [],
  })
  const contractSec = regSections.find((s) => s.name === 'greatwall:contract:explorer')
  const taskCtx = regContexts.find((c) => c.name === 'greatwall:task:exp_test_1')
  assert.equal(contractSec?.interpolate, false, '角色模板必须关闭 {{var}} 插值防崩溃')
  assert.equal(taskCtx?.required, true, '任务上下文必须标记 required:true 穿透 includeRuntimeContext:false')
  assert.equal(taskCtx?.interpolate, false, '任务上下文必须关闭 {{var}} 插值防崩溃')

  const filtered = await assembleHook(
    {},
    {},
    async () => ({
      sections: [
        { name: 'harness:identity', text: 'id' },
        { name: 'greatwall:contract:explorer', text: 'contract' },
        { name: 'tool-pwsh', text: 'pwsh' },
        { name: 'tool-fs:guidance', text: 'drop' },
        { name: 'mcp:playwright', text: 'third-party-drop' },
        { name: 'deployment:persona-prefix', text: 'persona-drop' },
      ],
    }),
  )
  assert.deepEqual(
    filtered.sections.map((s) => s.name),
    ['harness:identity', 'greatwall:contract:explorer', 'tool-pwsh'],
  )
})

test('24. 含空格自身沙箱路径零误杀 + 100% 拦截同辈 Worktree（含前缀碰撞）、Evaluators 与宿主机外部路径', () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_space_sandbox_'))
  try {
    const ws = path.join(tmpRoot, 'deepseek harness', 'v6 第六轮测试')
    const wt1 = path.join(ws, 'worktrees', 'b_q1_1')
    const wt10 = path.join(ws, 'worktrees', 'b_q1_10')
    const wt2 = path.join(ws, 'worktrees', 'b_q1_2')
    const evalDir = path.join(ws, 'evaluators')
    fs.mkdirSync(path.join(wt1, 'code'), { recursive: true })
    fs.mkdirSync(path.join(wt10, 'code'), { recursive: true })
    fs.mkdirSync(path.join(wt2, 'code'), { recursive: true })
    fs.mkdirSync(evalDir, { recursive: true })

    const evalExp = createSandboxCallEvaluator({
      role: 'explorer',
      workspaceRoot: ws,
      worktreeAbsPath: wt1,
      protectedDirs: [path.join(tmpRoot, 'plugin_data')],
    })

    // 1) 自身含空格沙箱路径（双引号/单引号/正斜杠）全部放行
    assert.equal(evalExp({ name: 'pwsh', arguments: { command: `cd "${path.join(wt1, 'code')}"; python q1.py` } }), undefined)
    assert.equal(evalExp({ name: 'pwsh', arguments: { command: `cd '${path.join(wt1, 'code')}'` } }), undefined)
    assert.equal(evalExp({ name: 'pwsh', arguments: { command: `python "${path.join(wt1, 'code', 'q1.py').replace(/\\/g, '/')}"` } }), undefined)

    // 2) 同辈他脉（含 b_q1_1 vs b_q1_10 前缀碰撞！）必须 100% 拦截
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: `Get-Content "${path.join(wt2, 'code', 'secret.py')}"` } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: `Get-Content "${path.join(wt10, 'code', 'secret.py')}"` } })), /SANDBOX_VIOLATION/)

    // 3) 主工作区 evaluators/ 与宿主机含空格外部路径必须 100% 拦截
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: `Get-Content "${path.join(evalDir, 'loc.py')}"` } })), /SANDBOX_VIOLATION/)
    assert.match(String(evalExp({ name: 'pwsh', arguments: { command: `Get-Content "${path.join(tmpRoot, 'other folder', 'secret.txt')}"` } })), /SANDBOX_VIOLATION/)
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('25. 活跃仪器 default_spec_json.interface_hint 自动渲染进探索者上下文', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_hint_'))
  const wt = path.join(tmpRoot, 'wt')
  fs.mkdirSync(wt, { recursive: true })
  try {
    let capturedTaskCtx = ''
    const fakeOrch = {
      workspaceRoot: tmpRoot,
      _poolState: 'running',
      liveSessions: new Map(),
      _nodeCompanionSessions: new Map(),
      _handoffsSinceHeartbeat: 0,
      telemetry: { recordEvent() {} },
      bridge: {
        async control(method) {
          if (method === 'control_plane/sync_pressure') return { ok: true, data: { node_status: 'CLOSED' } }
          return { ok: true }
        },
      },
      host: { effectiveContextWindow: 500_000, setSessionReadonly() {}, async archiveSession() {} },
      async spawnAndRunAgent(opts) {
        capturedTaskCtx = opts.taskContextText || ''
        return {
          sessionId: opts.sessionId,
          role: opts.role,
          turnSignals: [],
          nativeThresholds: [],
          isAbnormalEnd: false,
          blackboxSummary: 'bb',
          lastAssistantText: 'ok',
          handle: { agent: { session: { id: opts.sessionId } } },
          async dispose() {},
        }
      },
      async continueAliveAgent() {
        return { lastAssistantText: 'ok', turnSignals: [], nativeThresholds: [], isAbnormalEnd: false }
      },
    }
    await driveExplorerCompanionPair(
      fakeOrch,
      { node_id: 'n_h', branch_id: 'b_h', question_id: 'Q1', worktree_abs_path: wt, briefing_snapshot_md: 'BRIEF' },
      {
        goal_and_completion_md: '# G',
        active_instruments: [
          {
            instrument_id: 'LOCATOR_EVAL',
            version: 1,
            question_id: 'Q1',
            instrument_role: 'VERDICT',
            artifact_schema: 'python_run',
            health_status: 'HEALTHY',
            default_spec_json: JSON.stringify({ interface_hint: '脚本须向 stdout 输出含 {"error_max": float} 的 JSON' }),
          },
        ],
      },
      'exp_hint_1',
    )
    assert.ok(capturedTaskCtx.includes('LOCATOR_EVAL'))
    assert.ok(capturedTaskCtx.includes('接口约定: 脚本须向 stdout 输出含 {"error_max": float} 的 JSON'))
  } finally {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('26. GreatwallMcpBridge.describeContracts 实时握手与 Node 静态契约 100% 一致', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v3_contracts_'))
  const dataDir = path.join(tmpRoot, 'plugin_data')
  fs.mkdirSync(dataDir, { recursive: true })
  const bridge = new GreatwallMcpBridge({
    corePythonRoot: CORE_PYTHON_ROOT,
    workspaceRoot: tmpRoot,
    dataDir,
    requestTimeoutMs: 15_000,
  })
  try {
    const snap1 = await bridge.describeContracts()
    const pyAll = Object.values(snap1.role_mcp_tools || {}).flat().sort()
    assert.equal(snap1.tool_count, 32)
    assert.deepEqual(pyAll, [...ALL_MCP_TOOLS].sort())
    assert.deepEqual([...snap1.readonly_blocked_mcp_tools].sort(), [...READONLY_BLOCKED_MCP_TOOLS].sort())
    assert.deepEqual([...snap1.long_running_mcp_tools].sort(), [...LONG_RUNNING_MCP_TOOLS].sort())
    assert.deepEqual([...snap1.turn_concluding_tools].sort(), [...TURN_CONCLUDING_TOOLS].sort())
    for (const role of CANONICAL_ROLES) {
      assert.deepEqual([...(snap1.role_mcp_tools[role] || [])].sort(), [...ROLE_MCP_TOOLS[role]].sort())
    }
    // 二次调用默认走内存缓存返回同一引用
    const snap2 = await bridge.describeContracts()
    assert.strictEqual(snap2, snap1)
  } finally {
    await bridge.dispose()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})
