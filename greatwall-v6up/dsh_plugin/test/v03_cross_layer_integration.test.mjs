/**
 * GreatWall v0.3 真实跨层集成回归测试（Python 真实 SQLite 控制面 -> Node 派发/循环/总控/前端渲染，零假快照！）。
 * 覆盖静态审阅全部跨层断点：#1/#2/#3/#4/#5/#6/#10/#13/#14/#15。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

import { GreatwallMcpBridge } from '../lib/mcp_bridge.js'
import { GreatwallControlService } from '../lib/control_service.js'
import { GreatwallOrchestrator } from '../lib/orchestrator.js'
import { dispatchStage1Step } from '../lib/orchestrator/dispatch_stage1.js'
import { dispatchPendingHandoffRecoveries, dispatchStage2Step } from '../lib/orchestrator/dispatch_stage2.js'
import { driveExplorerCompanionPair } from '../lib/pair_lifecycle.js'
import { buildChiefAnchorCard, ChiefEventInbox, ensureChiefSession } from '../lib/sessions/chief_runtime.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PLUGIN_ROOT = path.resolve(__dirname, '..')
const CORE_PYTHON_ROOT = path.resolve(PLUGIN_ROOT, '..', 'core_python')

function makeTempEnv() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'gw-v03-xlayer-'))
  const ws = path.join(base, 'ws')
  const dataDir = path.join(base, 'data')
  fs.mkdirSync(ws, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })
  return {
    base,
    ws,
    dataDir,
    cleanup() {
      try { fs.rmSync(base, { recursive: true, force: true }) } catch {}
    },
  }
}

async function setupInitializedWorkspace(bridge, ws, { subquestions = ['Q1'], totalBudget = {}, stage = 'STAGE2_EVOLVE', initialInstruments = [] } = {}) {
  const init = await bridge.control('control_plane/init_parse0', {
    workspace_root: ws,
    goal_and_completion_md: '真实跨层集成回归目标',
    subquestions,
    total_budget: totalBudget,
    initial_instruments: initialInstruments,
    stage,
    human_signed_at: new Date().toISOString(),
    autonomy_mode: 'WAVE_CONFIRM',
  })
  assert.equal(init.ok, true, JSON.stringify(init))
}

async function createBranchViaPython(bridge, ws, questionId = 'Q1', familyId = 'fam_a') {
  const rFam = await bridge.callTool('register_method_family', {
    question_id: questionId,
    family_id: familyId,
    mechanism_signature: `机理 ${familyId}`,
    orthogonal_contrast: `正交对照 ${familyId}`,
  }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 's_log' })
  assert.equal(rFam.ok, true, JSON.stringify(rFam))

  const rFork = await bridge.callTool('fork_branch', {
    question_id: questionId,
    fork_mode: 'orthogonal',
    target_family_id: familyId,
  }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 's_log' })
  assert.equal(rFork.ok, true, JSON.stringify(rFork))
  return rFork.data
}

test('cross-1 (#1 & #6): 真实 Python 快照驱动圆桌派发，连续停滞熔断后自动写 DB FAILED 释放开会锁', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, { subquestions: ['Q1'] })
    await createBranchViaPython(bridge, env.ws, 'Q1', 'fam_w')

    const opened = await bridge.control('control_plane/open_wave_conference', { workspace_root: env.ws, question_id: 'Q1', force: true })
    assert.equal(opened.ok, true)
    assert.equal(opened.data.opened, true)
    const cid = opened.data.conference_id

    // 读取真实 Python schedule_snapshot（严禁 mock）
    const snapRes = await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })
    assert.equal(snapRes.ok, true)
    assert.ok(Array.isArray(snapRes.data.active_conferences) && snapRes.data.active_conferences.length === 1)
    assert.ok(Array.isArray(snapRes.data.active_wave_conferences) && snapRes.data.active_wave_conferences.length === 1)

    const orch = new GreatwallOrchestrator({ ctx: {}, bridge, corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
    let advancedCalls = 0
    orch.advanceWaveConference = async () => { advancedCalls += 1 } // 模拟无进展停滞

    // 第 1 次派发
    const p1 = orch.createDispatchRuntimePort()
    const d1 = await dispatchStage2Step(p1, snapRes.data, null, 2)
    assert.equal(d1.dispatched, true)
    await Promise.allSettled([...orch._runningGov.values()])
    assert.equal(advancedCalls, 1)

    // 第 2 次派发触发熔断（maxStalledRuns=2），应自动调 control_plane/fail_wave_conference 落库 FAILED 释放锁
    const snapRes2 = await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })
    const d2 = await dispatchStage2Step(orch.createDispatchRuntimePort(), snapRes2.data, null, 2)
    assert.equal(d2.dispatched, true)
    await Promise.allSettled([...orch._runningGov.values()])
    assert.equal(advancedCalls, 2)

    const snapAfter = await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })
    assert.equal(snapAfter.data.active_wave_conferences.length, 0, '熔断落库 FAILED 后圆桌必须退出活跃队列释放锁')

    // 确认可以立刻重开下一波（wave_no=2），绝不卡死
    const reopen = await bridge.control('control_plane/open_wave_conference', { workspace_root: env.ws, question_id: 'Q1', force: true })
    assert.equal(reopen.ok, true)
    assert.equal(reopen.data.opened, true)
    assert.notEqual(reopen.data.conference_id, cid)
    assert.equal(reopen.data.wave_no, 2)
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})

test('cross-2 (#2 & #10): 真实 Python ui_inspector 与 getControlStatus 喂入 ThreeQuestionsView & LivingSurveyView 零崩溃渲染', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, { subquestions: ['Q1', 'Q2'] })
    const inspRes = await bridge.control('control_plane/ui_inspector', { workspace_root: env.ws })
    assert.equal(inspRes.ok, true)
    assert.ok(Array.isArray(inspRes.data.subproblem_runtime_state))
    assert.equal(inspRes.data.subproblem_runtime_state.length, 2)
    assert.ok(Array.isArray(inspRes.data.living_surveys_list))

    const orch = new GreatwallOrchestrator({ ctx: {}, bridge, corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
    const status = await orch.getControlStatus()
    assert.ok(Array.isArray(status.subproblemStates))
    assert.equal(status.subproblemStates.length, 2)

    // 在真实 VM 中加载编译前组件并实际调用渲染函数（同时检验字典形状与数组形状均零崩溃）
    const threeSrc = fs.readFileSync(path.join(PLUGIN_ROOT, 'client_src', 'components', 'ThreeQuestionsView.js'), 'utf8')
    const livingSrc = fs.readFileSync(path.join(PLUGIN_ROOT, 'client_src', 'components', 'LivingSurveyView.js'), 'utf8')
    const sandbox = {
      jsx: (tag, props) => ({ tag, props }),
      jsxs: (tag, props) => ({ tag, props }),
      stateBadgeClass: (s) => `badge-${s}`,
    }
    vm.createContext(sandbox)
    vm.runInContext(`${threeSrc}\n${livingSrc}`, sandbox)

    const v3 = sandbox.ThreeQuestionsView({ data: { status, inspector: inspRes.data }, busy: false, onControl: () => {} })
    const v3Json = JSON.stringify(v3)
    assert.ok(v3Json.includes('Q1') && v3Json.includes('Q2'), 'ThreeQuestionsView 必须渲染出真实 Q1/Q2 子题')
    assert.ok(v3Json.includes('暂停该题'), '活跃子题必须显示暂停该题按钮')
    assert.ok(!v3Json.includes('尚未初始化 Parse 0 子题'))

    // LivingSurveyView 在真实空字典 living_surveys={} 情况下绝不抛 .map is not a function
    const vLiv = sandbox.LivingSurveyView({ data: { status, inspector: inspRes.data } })
    assert.ok(JSON.stringify(vLiv).includes('子题全局总览'))
    // 再验证旧字段仅返回字典对象时也不崩溃
    const vLivDictOnly = sandbox.LivingSurveyView({
      data: {
        inspector: {
          living_surveys: { Q1: { survey_id: 'sv_1', question_id: 'Q1', revision: 1, total_chars: 120 } },
          open_lemma_gaps: [],
          wave_conferences: [],
        },
      },
    })
    assert.ok(JSON.stringify(vLivDictOnly).includes('Q1 · r1 (120/4000 字)'))
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})

test('cross-3 (#3): 真实 sync_pressure 识别 PAUSE_DRAINING 立即让权，以及暂停后授权提前交班闭环消费 early_handoff_nodes', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, { subquestions: ['Q1'] })
    const branch = await createBranchViaPython(bridge, env.ws, 'Q1', 'fam_p')

    // 1) 探索循环读真实 Python sync_pressure 识别 PAUSE_DRAINING 立即优雅让权（零续推、零崩溃交班、不归档）
    await bridge.control('control_plane/pause_node', { workspace_root: env.ws, node_id: branch.node_id, actor_source: 'human_ui', reason: '45%接管' })
    let continueCalled = 0
    let disposedArchive = null
    let handoffCalled = 0

    const fakePort = {
      workspaceRoot: env.ws,
      bridge,
      ctx: { tokenMeter: { measure: () => ({ totalTokens: 5000 }) } },
      isPoolStopped: () => false,
      isPoolPaused: () => false,
      getEffectiveContextWindow: () => 500_000,
      control: (m, p) => bridge.control(m, p),
      recordEvent: () => {},
      resumeOrSpawnAgent: async ({ role }) => {
        if (role === 'lineage_companion') {
          handoffCalled += 1
          return { sessionId: `gw-comp-${branch.node_id}`, lastAssistantText: 'ok', turnSignals: [], dispose: async () => {} }
        }
        return {
          sessionId: `gw-exp-${branch.node_id}`,
          handle: { agent: { session: {} } },
          blackboxSummary: '',
          isAbnormalEnd: false,
          turnSignals: [],
          nativeThresholds: [],
          dispose: async (_st, _r, opts) => { disposedArchive = opts?.archive },
        }
      },
      continueAliveAgent: async () => { continueCalled += 1; return { lastAssistantText: '', turnSignals: [], nativeThresholds: [] } },
      setSessionReadonly: () => {},
      disposeCompanion: async () => {},
    }

    const snap0 = (await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })).data
    await driveExplorerCompanionPair(fakePort, { ...branch, question_id: 'Q1' }, snap0, `gw-exp-${branch.node_id}`)
    assert.equal(continueCalled, 0, 'PAUSE_DRAINING 时绝不可继续续推探索者')
    assert.equal(handoffCalled, 0, 'PAUSE_DRAINING 让权绝不可误触发崩溃交班')
    assert.equal(disposedArchive, false, '让权给人类时绝不可归档探索会话')

    // 2) 标记让权完成 -> 人类点击授权提前交班 -> dispatchPendingHandoffRecoveries 消费 early_handoff_nodes
    await bridge.control('control_plane/mark_node_yielded', { workspace_root: env.ws, node_id: branch.node_id })
    await bridge.control('control_plane/authorize_early_handoff', {
      workspace_root: env.ws,
      node_id: branch.node_id,
      actor_source: 'human_ui',
      reason: '人类收口',
    })

    const snapEarly = (await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })).data
    assert.equal(snapEarly.early_handoff_nodes.length, 1)

    const tasks = []
    let companionModeSeen = ''
    const portForEarly = {
      ...fakePort,
      isExplorerRunning: () => false,
      isBreakerOpen: () => false,
      evaluateBreakerAfterTask: async () => [],
      resumeOrSpawnAgent: async ({ role, prompt }) => {
        if (role === 'lineage_companion') {
          handoffCalled += 1
          companionModeSeen = prompt
        }
        return { sessionId: `gw-comp-${branch.node_id}`, lastAssistantText: 'ok', turnSignals: [], dispose: async () => {} }
      },
      launchGovTask: (_k, fn) => { tasks.push(fn()); return true },
    }

    const dispatched = dispatchPendingHandoffRecoveries(portForEarly, snapEarly, null)
    assert.equal(dispatched, true)
    await Promise.all(tasks)
    assert.equal(handoffCalled, 1)
    assert.ok(companionModeSeen.includes('HANDOFF_70'), '授权提前交班必须以 HANDOFF_70 模式驱动伴随封存')
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})

test('cross-4 (#4 & #5): 探索循环实时累计子题 Token 落库，且全局暂停时优雅停推不走崩溃抢救', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, { subquestions: ['Q1'], totalBudget: { max_tokens_per_subproblem: 100_000 } })
    const branch = await createBranchViaPython(bridge, env.ws, 'Q1', 'fam_tok')

    let poolPaused = false
    let turns = 0
    let crashCalled = false
    const fakePort = {
      workspaceRoot: env.ws,
      bridge,
      ctx: { tokenMeter: { measure: () => ({ totalTokens: turns === 0 ? 40_000 : 120_000 }) } },
      isPoolStopped: () => false,
      isPoolPaused: () => poolPaused,
      getEffectiveContextWindow: () => 500_000,
      control: (m, p) => bridge.control(m, p),
      recordEvent: () => {},
      resumeOrSpawnAgent: async ({ role }) => {
        if (role === 'lineage_companion') { crashCalled = true }
        return {
          sessionId: `gw-exp-${branch.node_id}`,
          handle: { agent: { session: {} } },
          blackboxSummary: '',
          isAbnormalEnd: false,
          turnSignals: [],
          nativeThresholds: [],
          dispose: async () => {},
        }
      },
      continueAliveAgent: async () => {
        turns += 1
        return { lastAssistantText: 'step', turnSignals: [], nativeThresholds: [], isAbnormalEnd: false }
      },
      setSessionReadonly: () => {},
      disposeCompanion: async () => {},
    }

    const snap0 = (await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })).data
    // 第一次采样 40k，续推 1 轮后第二次采样 120k -> 超过 100k 限额，Python 自动切 subproblem_dispatch_state=STOPPED_BUDGET_EXHAUSTED -> 循环立刻优雅退场
    await driveExplorerCompanionPair(fakePort, { ...branch, question_id: 'Q1' }, snap0, `gw-exp-${branch.node_id}`, { maxExploreTurns: 5 })
    assert.equal(crashCalled, false, '子题预算耗尽优雅退场绝不误触发崩溃交班')

    const snapAfter = (await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })).data
    const q1 = snapAfter.subproblem_runtime_state.find((s) => s.question_id === 'Q1')
    assert.ok(Number(q1.spent_tokens) >= 120_000, `期望 spent_tokens >= 120000，实得 ${q1.spent_tokens}`)
    assert.equal(q1.dispatch_state, 'PAUSED_BLOCKED')
    assert.equal(q1.block_reason_code, 'TOKEN_BUDGET_EXHAUSTED')

    // 再测试全局 pause 时也直接优雅退出不续推
    poolPaused = true
    turns = 0
    await driveExplorerCompanionPair(fakePort, { ...branch, question_id: 'Q1' }, snap0, `gw-exp-${branch.node_id}`, { maxExploreTurns: 5 })
    assert.equal(turns, 0, '全局暂停态探索循环绝不续推')
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})

test('cross-5 (#13 & #14): gw-chief 收件箱出队与 onBeforeStep 动态刷新锚点 + 待人类拍板时不空闲自退', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, { subquestions: ['Q1'] })
    const prop = await bridge.control('control_plane/create_control_proposal', {
      workspace_root: env.ws,
      action_type: 'SET_AUTONOMY_MODE',
      target_id: 'ALL',
      payload: { autonomy_mode: 'AUTOPILOT' },
      rationale_md: '请求切自主续航',
    })
    assert.equal(prop.ok, true)

    // 1) 验证 gw-chief 收件箱消费与每步动态刷新锚点
    const inbox = new ChiefEventInbox()
    inbox.ingest({ payload: { event_type: 'PENDING_HUMAN_PROPOSAL', proposal_id: prop.data.proposal_id } })
    assert.equal(inbox.peekCount(), 1)

    let capturedProvider = null
    let capturedBeforeStep = null
    let capturedPrompt = ''
    const fakeController = {
      workspaceRoot: env.ws,
      scheduleSnapshot: () => bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws }),
      orchestrator: {
        resumeOrSpawnAgent: async (opts) => {
          capturedProvider = opts.extraContextProvider
          capturedBeforeStep = opts.onBeforeStep
          capturedPrompt = opts.prompt
          return { sessionId: opts.sessionId, lastAssistantText: 'ok' }
        },
      },
    }
    const chiefRes = await ensureChiefSession(fakeController, { chiefInbox: inbox })
    assert.equal(chiefRes.drainedEventsCount, 1)
    assert.equal(inbox.peekCount(), 0, '打开 gw-chief 时必须消费收件箱批次')
    assert.equal(capturedPrompt ?? '', '', '打开总控无需启动模型回合')
    assert.ok(capturedProvider().includes(prop.data.proposal_id))

    // 批准提案后触发 onBeforeStep，锚点卡必须动态刷新为已无待拍板提案！
    await bridge.control('control_plane/approve_control_proposal', {
      workspace_root: env.ws,
      proposal_id: prop.data.proposal_id,
      decision: 'APPROVE',
      approved_by_source: 'human_ui',
    })
    await capturedBeforeStep()
    assert.ok(!capturedProvider().includes(prop.data.proposal_id), 'onBeforeStep 后锚点卡必须动态刷新反映最新状态')
    assert.ok(capturedProvider().includes('mode=AUTOPILOT'))

    // 2) 验证存在待人类拍板提案时，_runAsyncEventPool 不会 3 轮空闲退出
    const prop2 = await bridge.control('control_plane/create_control_proposal', {
      workspace_root: env.ws,
      action_type: 'SET_AUTONOMY_MODE',
      target_id: 'ALL',
      payload: { autonomy_mode: 'WAVE_CONFIRM' },
      rationale_md: '测试等待拍板不自退',
    })
    assert.equal(prop2.ok, true)

    const orch = new GreatwallOrchestrator({ ctx: {}, bridge, corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
    orch._requireExplicitModelBinding = false
    const ac = new AbortController()
    let waitCalls = 0
    orch._waitWakeOrTimeout = async () => {
      waitCalls += 1
      if (waitCalls >= 5) ac.abort(new Error('TEST_DONE'))
    }
    // 禁用普通派发干扰，仅让循环面对 pending_proposals 空转 5 轮
    await orch.runUntilClosed({ signal: ac.signal })
    assert.ok(waitCalls >= 5, `待人类拍板期间不应 3 轮自退，实际等待轮次=${waitCalls}`)
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})

test('cross-6 (#15): Stage 1 全部熔断时 dispatchStage1Step 返回 handled:true 绝不跌入 Stage 2', async () => {
  const env = makeTempEnv()
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: env.ws, dataDir: env.dataDir })
  try {
    await setupInitializedWorkspace(bridge, env.ws, {
      subquestions: ['Q1'],
      stage: 'STAGE1_PARSE0',
      initialInstruments: [{ question_id: 'Q1', instrument_id: 'ver_q1', instrument_role: 'VERDICT' }],
    })
    const snap = (await bridge.control('control_plane/schedule_snapshot', { workspace_root: env.ws })).data
    assert.equal(snap.stage, 'STAGE1_PARSE0')

    const events = []
    const fakePort = {
      isBreakerOpen: () => true, // 模拟 Stage 1 所有待办均已被熔断
      recordEvent: (name, detail) => events.push({ name, detail }),
    }
    const res = await dispatchStage1Step(fakePort, snap, null)
    assert.equal(res.handled, true, 'Stage 1 未放行前必须返回 handled:true 绝不跌落至 Stage 2')
    assert.ok(res.waitMs > 0)
    assert.ok(events.some((e) => e.name === 'stage1_waiting_or_circuit_broken'))
  } finally {
    await bridge.dispose()
    env.cleanup()
  }
})
