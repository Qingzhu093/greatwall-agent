/**
 * GreatWall v0.3 设施工程、Superagent 总控、45% 人工接管、宏观圆桌与 Outbox 完整验收套件。
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { WorkspaceInstanceLock } from '../lib/runtime/instance_lock.js'
import { WorkerSlotAllocator } from '../lib/runtime/worker_slots.js'
import { isTransientProviderError, runWithTransientRetry } from '../lib/runtime/transient_retry.js'
import { RuntimeEffectsConsumer } from '../lib/runtime/effects_consumer.js'
import { HumanTakeoverCoordinator } from '../lib/sessions/human_takeover.js'
import {
  ChiefEventInbox,
  buildChiefAnchorCard,
  computeChiefAnchorBudgetChars,
  registerProposalActionCard,
} from '../lib/sessions/chief_runtime.js'
import { WaveConferenceRunner } from '../lib/orchestrator/wave_conference_runner.js'
import { ORCHESTRATE_TOOL_SCHEMA } from '../lib/orchestrate_tool.js'
import { SEALED_COMPANION_CONFERENCE_TOOLS } from '../lib/prompts.js'
import { Config, resolvePluginConfig } from '../lib/config.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const PLUGIN_ROOT = path.resolve(__dirname, '..')

test('v0.3-1: WorkspaceInstanceLock 防双活与死 PID 自动回收', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v03_lock_'))
  try {
    const lockPath = path.join(tmpDir, 'host.lock')
    const lockA = new WorkspaceInstanceLock(lockPath)
    const lockB = new WorkspaceInstanceLock(lockPath)

    const r1 = lockA.acquire()
    assert.equal(r1.ok, true)
    assert.equal(fs.existsSync(lockPath), true)

    // 活实例占用期间，第二实例必须被拒（防双活）
    const r2 = lockB.acquire()
    assert.equal(r2.ok, false)
    assert.match(String(r2.error || ''), /另一活跃 GreatWall 实例持有/)

    // 释放后可重入
    lockA.release()
    assert.equal(fs.existsSync(lockPath), false)
    assert.equal(lockB.acquire().ok, true)
    lockB.release()

    // 写入死 PID 残留锁 -> 自动回收成功
    fs.writeFileSync(lockPath, JSON.stringify({ ownerId: 'dead_inst', pid: 99999999, acquiredAt: '2020-01-01T00:00:00Z' }), 'utf8')
    const r3 = lockA.acquire()
    assert.equal(r3.ok, true, '死 PID 残留锁必须被自动清理并接管')
    lockA.release()
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
})

test('v0.3-2: WorkerSlotAllocator maxWorkers + 1 人类优先保留槽', () => {
  const alloc = new WorkerSlotAllocator(2, 1)
  assert.equal(alloc.acquire({ node_id: 'n1' }), 'normal')
  assert.equal(alloc.acquire({ node_id: 'n2' }), 'normal')
  // 普通任务占满 maxWorkers=2 后，绝不能侵占 +1 人类保留槽
  assert.equal(alloc.acquire({ node_id: 'n3' }), null)
  // 人类优先任务（HUMAN_SEEDED 或 human_modified=1）可合法拿到 +1 保留槽
  assert.equal(alloc.acquire({ node_id: 'n_human', branch_kind: 'HUMAN_SEEDED' }), 'human_reserve')
  assert.equal(alloc.acquire({ node_id: 'n_human2', human_modified: 1 }), null)

  const snap = alloc.snapshot()
  assert.equal(snap.normalActive, 2)
  assert.equal(snap.humanReserveActive, 1)

  alloc.release('n1')
  assert.equal(alloc.acquire({ node_id: 'n3' }), 'normal')
})

test('v0.3-3: transient_retry 瞬时 429/5xx 重试 vs 401/CONTENT_REFUSED 立即失败', async () => {
  assert.equal(isTransientProviderError({ status: 429 }), true)
  assert.equal(isTransientProviderError({ status: 503 }), true)
  assert.equal(isTransientProviderError({ code: 'ETIMEDOUT' }), true)
  assert.equal(isTransientProviderError({ status: 401 }), false)
  assert.equal(isTransientProviderError({ code: 'CONTENT_REFUSED' }), false)

  let attempts = 0
  const okVal = await runWithTransientRetry(
    async () => {
      attempts += 1
      if (attempts < 3) {
        const err = new Error('rate limit')
        err.status = 429
        throw err
      }
      return 'RECOVERED'
    },
    { delaysMs: [5, 5, 5] },
  )
  assert.equal(okVal, 'RECOVERED')
  assert.equal(attempts, 3)

  let fatalAttempts = 0
  await assert.rejects(
    () =>
      runWithTransientRetry(
        async () => {
          fatalAttempts += 1
          const err = new Error('bad key')
          err.status = 401
          throw err
        },
        { delaysMs: [5, 5] },
      ),
    /bad key/,
  )
  assert.equal(fatalAttempts, 1, '401 认证错误严禁重试')
})

test('v0.3-4: HumanTakeoverCoordinator source.rpcId 人类插话让权、白名单免误判与 ctx.jobs 清理/降级', async () => {
  const controlCalls = []
  const killedJobs = []
  let sessionEventCb = null

  const ctxWithJobs = {
    get(name) {
      if (name === 'jobs') {
        return {
          list: async () => [
            { id: 'job_mine', status: 'running' },
            { id: 'job_done', status: 'completed' },
          ],
          kill: async (id) => { killedJobs.push(id) },
        }
      }
      return null
    },
  }
  const fakeBridge = {
    async control(method, params) {
      controlCalls.push({ method, params })
      return { ok: true, data: {} }
    },
  }
  const coord = new HumanTakeoverCoordinator({
    ctx: ctxWithJobs,
    bridge: fakeBridge,
    workspaceRoot: '/tmp/ws_ht',
    telemetry: { recordEvent() {} },
  })

  const fakeSession = {
    id: 'gw-exp-n1',
    on(ev, fn) {
      if (ev === 'event') sessionEventCb = fn
      return () => {}
    },
  }
  let takeoverCallbackFired = false
  coord.watchExplorerSession('n1', fakeSession, { onHumanTakeover: () => { takeoverCallbackFired = true } })
  assert.ok(typeof sessionEventCb === 'function')

  // 1) 插件自发白名单消息 -> 绝不误触发人工接管
  coord.markPluginMessage('gw-exp-n1', '自动续推 prompt')
  sessionEventCb({ type: 'user/message', data: { text: '自动续推 prompt', source: { kind: 'user', rpcId: 'rpc_internal' } } })
  assert.equal(takeoverCallbackFired, false)
  assert.equal(controlCalls.length, 0)

  // 2) 人类在子节点聊天窗亲手发言（携带 source.rpcId）-> 立即触发 record_human_chat_detected
  sessionEventCb({ type: 'user/message', data: { text: '等一下，我来改一下参数', source: { kind: 'user', rpcId: 'rpc_ui_99' } } })
  assert.equal(takeoverCallbackFired, true)
  assert.ok(controlCalls.some((c) => c.method === 'control_plane/record_human_chat_detected' && c.params.node_id === 'n1'))

  // 3) 45% 暂停让权：取消活跃回合 + ctx.jobs 清理仅 running 作业 + 落库 mark_node_yielded
  let cancelCount = 0
  const drainRes = await coord.drainAndYieldNode({
    nodeId: 'n1',
    sessionId: 'gw-exp-n1',
    liveHandle: { agent: { cancel: () => { cancelCount += 1 } } },
    keepSessionForHuman: true,
    reason: 'HUMAN_PAUSE',
  })
  assert.equal(cancelCount, 1)
  assert.deepEqual(drainRes.killedJobIds, ['job_mine'])
  assert.ok(controlCalls.some((c) => c.method === 'control_plane/mark_node_yielded' && c.params.node_id === 'n1'))

  // 4) 无 ctx.jobs 服务时优雅降级不崩溃
  const coordNoJobs = new HumanTakeoverCoordinator({
    ctx: { get: () => null },
    bridge: fakeBridge,
    workspaceRoot: '/tmp/ws_ht',
    telemetry: { recordEvent() {} },
  })
  const fallbackRes = await coordNoJobs.drainAndYieldNode({ nodeId: 'n1', sessionId: 'gw-exp-n1', keepSessionForHuman: false })
  assert.deepEqual(fallbackRes.killedJobIds, [])
  coord.disposeAll()
})

test('v0.3-5: ChiefRuntime 弹性锚点卡字数公式、高信噪比收件箱与原生 Action Card 注册/降级', async () => {
  assert.equal(computeChiefAnchorBudgetChars(1), 400)
  assert.equal(computeChiefAnchorBudgetChars(4), 580)
  assert.equal(computeChiefAnchorBudgetChars(20), 1200)
  assert.equal(computeChiefAnchorBudgetChars(20, 900), 900)

  const anchor = buildChiefAnchorCard({
    initialized: true,
    stage: 'STAGE2_EVOLVE',
    autonomy_mode: 'WAVE_CONFIRM',
    latest_spec_revision: 1,
    closure_state: { status: 'OPEN' },
    subproblem_runtime_state: [
      { question_id: 'Q1', dispatch_state: 'DISPATCHING', active_spec_revision: 1, completed_waves: 1 },
      { question_id: 'Q2', dispatch_state: 'STOPPED_SOLVED', active_spec_revision: 0, solved_entry_id: 'L3-002', completed_waves: 1 },
    ],
    pending_proposals: [{ proposal_id: 'prop_01', action_type: 'AMEND_RULING_DRAFT', target_id: 'Q1' }],
  })
  assert.ok(anchor.includes('STAGE2_EVOLVE'))
  assert.ok(anchor.includes('Q1') && anchor.includes('Q2') && anchor.includes('L3-002'))
  assert.ok(anchor.length <= computeChiefAnchorBudgetChars(2))

  // 两阶段高信噪比收件箱过滤
  const inbox = new ChiefEventInbox()
  assert.equal(inbox.ingest({ event_type: 'SUBPROBLEM_SOLVED', question_id: 'Q2' }).accepted, true)
  assert.equal(inbox.ingest({ event_type: 'EXPLORER_HANDBACK', node_id: 'n1' }).accepted, true)
  assert.equal(inbox.ingest({ event_type: 'MINOR_HEARTBEAT_TICK' }).accepted, false)
  assert.equal(inbox.peekCount(), 2)
  assert.equal(inbox.drainBatch().length, 2)
  assert.equal(inbox.peekCount(), 0)

  // 原生 dsh-action-cards 注册 + 幂等审批转发
  const registeredCards = new Map()
  const executedCalls = []
  const reg = registerProposalActionCard(
    {
      get(name) {
        if (name === 'actionCards') {
          return {
            register(def) {
              registeredCards.set(def.kind, def)
              return () => registeredCards.delete(def.kind)
            },
          }
        }
        return null
      },
    },
    {
      async execute(req) {
        executedCalls.push(req)
        return { ok: true, alreadyResolved: executedCalls.length > 1 }
      },
    },
  )
  assert.equal(reg.registered, true)
  assert.ok(registeredCards.has('greatwall_proposal'))
  const card = registeredCards.get('greatwall_proposal')
  const r1 = await card.handleAction({ proposalId: 'prop_01', decision: 'APPROVE', workspaceRoot: '/tmp/ws' })
  const r2 = await card.handleAction({ proposalId: 'prop_01', decision: 'APPROVE', workspaceRoot: '/tmp/ws' })
  assert.equal(r1.ok, true)
  assert.equal(r2.alreadyResolved, true)
  assert.equal(executedCalls[0].caller, 'human_ui')
  assert.equal(executedCalls[0].payload.approved_by_source, 'action_card_human')
  reg.dispose()

  // 无宿主 actionCards 时平滑降级
  const fallbackReg = registerProposalActionCard({ get: () => null }, { execute: async () => ({}) })
  assert.equal(fallbackReg.registered, false)
})

test('v0.3-6: WaveConferenceRunner 四拍圆桌（封存伴随零写权唤醒 Round 1/2、总览刷新与主席拍板）', async () => {
  const trace = []
  const fakePort = {
    workspaceRoot: '/tmp/ws_wc',
    async resumeOrSpawnAgent(opts) {
      trace.push({
        type: 'resumeOrSpawn',
        role: opts.role,
        sessionId: opts.sessionId,
        allowedMcpOverride: opts.allowedMcpOverride ? [...opts.allowedMcpOverride] : null,
        archiveOnComplete: opts.archiveOnComplete,
      })
      return { sessionId: opts.sessionId || `s_${opts.role}`, lastAssistantText: 'ok', turnSignals: [] }
    },
    async spawnAndRunAgent(opts) {
      trace.push({ type: 'spawn', role: opts.role, archiveOnComplete: opts.archiveOnComplete })
      return { sessionId: `s_${opts.role}`, lastAssistantText: 'ok', turnSignals: [] }
    },
  }

  const runner = new WaveConferenceRunner(fakePort)

  // 第 2 拍：2 名已封存伴随按 Round 1 -> Round 2 唤醒，物理仅挂 SEALED_COMPANION_CONFERENCE_TOOLS，随后主席落纪要
  const res2 = await runner.advanceConference({
    conference_id: 'wc_q1_1',
    question_id: 'Q1',
    wave_no: 1,
    status: 'ROUND_1_CRITIQUE',
    participant_nodes: [
      { node_id: 'node_a', branch_id: 'b_a', companion_session_id: 'gw-comp-node_a' },
      { node_id: 'node_b', branch_id: 'b_b', companion_session_id: 'gw-comp-node_b' },
    ],
    chair_session_id: 'gw-chair-wc_q1_1',
  })
  assert.equal(res2.advanced, true)
  assert.equal(res2.nextExpectedStatus, 'SURVEY_REFRESHING')

  const compCalls = trace.filter((x) => x.role === 'lineage_companion')
  assert.equal(compCalls.length, 4, '2 名参会助手 × 2 轮交锋 = 4 次唤醒')
  for (const c of compCalls) {
    assert.deepEqual(c.allowedMcpOverride.sort(), [...SEALED_COMPANION_CONFERENCE_TOOLS].sort(), '封存伴随参会必须物理撤除写工具')
    assert.ok(!c.allowedMcpOverride.includes('submit_node_handoff'))
    assert.ok(!c.allowedMcpOverride.includes('save_lineage_briefing'))
    assert.equal(c.archiveOnComplete, true, '会后必须归档伴随会话')
  }
  assert.ok(trace.some((x) => x.role === 'conference_chair' && x.sessionId === 'gw-chair-wc_q1_1'))

  // 第 3 拍（或单分支跳过第 2 拍直入 SURVEY_REFRESHING）：零外网 library_chronicler 刷新总览
  trace.length = 0
  const res3 = await runner.advanceConference({
    conference_id: 'wc_q1_1',
    question_id: 'Q1',
    wave_no: 1,
    status: 'SURVEY_REFRESHING',
  })
  assert.equal(res3.nextExpectedStatus, 'ADJUDICATING')
  assert.equal(trace[0].role, 'library_chronicler')

  // 第 4 拍：原地 resume 同一主席会话拍板并归档
  trace.length = 0
  const res4 = await runner.advanceConference({
    conference_id: 'wc_q1_1',
    question_id: 'Q1',
    wave_no: 1,
    status: 'ADJUDICATING',
    chair_session_id: 'gw-chair-wc_q1_1',
  })
  assert.equal(res4.nextExpectedStatus, 'COMPLETED_OR_PENDING_HUMAN')
  assert.equal(trace[0].role, 'conference_chair')
  assert.equal(trace[0].sessionId, 'gw-chair-wc_q1_1')
  assert.equal(trace[0].archiveOnComplete, true)
})

test('v0.3-7: RuntimeEffectsConsumer 租约领取、副作用路由与 ack', async () => {
  const acked = []
  const handled = []
  const consumer = new RuntimeEffectsConsumer({
    bridge: {
      async control(method, params) {
        if (method === 'control_plane/claim_runtime_effects') {
          return {
            ok: true,
            data: {
              claimed: [
                { seq: 11, kind: 'NOTIFY_POLICY_CHANGED', target_type: 'NODE', target_id: 'n1', payload: { new_spec_revision: 1 } },
                { seq: 12, kind: 'NOTIFY_CHIEF', target_type: 'PROJECT', target_id: 'active', payload: { kind: 'SUBPROBLEM_SOLVED' } },
              ],
            },
          }
        }
        if (method === 'control_plane/complete_runtime_effect') {
          acked.push(params)
          return { ok: true, data: {} }
        }
        return { ok: true, data: {} }
      },
    },
    workspaceRoot: '/tmp/ws_eff',
    ownerInstanceId: 'inst_1',
    handlers: {
      NOTIFY_POLICY_CHANGED: async (eff, payload) => handled.push(['policy', eff.seq, payload.new_spec_revision]),
      NOTIFY_CHIEF: async (eff, payload) => handled.push(['chief', eff.seq, payload.kind]),
    },
  })
  const res = await consumer.drainOnce({ limit: 10 })
  assert.equal(res.claimedCount, 2)
  assert.equal(res.handledCount, 2)
  assert.deepEqual(handled, [
    ['policy', 11, 1],
    ['chief', 12, 'SUBPROBLEM_SOLVED'],
  ])
  assert.deepEqual(acked.map((a) => [a.seq, a.status]), [
    [11, 'DONE'],
    [12, 'DONE'],
  ])
})

test('v0.3-8: greatwall_orchestrate 仅保留 4 个薄入口且绝不暴露 human_ui 绕过口', () => {
  assert.deepEqual(ORCHESTRATE_TOOL_SCHEMA.properties.action.enum, ['init', 'start', 'status', 'stop'])
})

test('v0.3-9: Config 动态探测/回退、前端编译产物零禁令依赖与三问视图齐全', () => {
  assert.ok(Config && Config['~standard'], 'Config 必须暴露 Standard Schema v1 接口')
  const cfg = resolvePluginConfig({ chiefAnchorHardCapChars: 1500, requestTimeoutMs: 45_000 })
  assert.equal(cfg.chiefAnchorHardCapChars, 1500)
  assert.equal(cfg.requestTimeoutMs, 45_000)

  const pkgRaw = fs.readFileSync(path.join(PLUGIN_ROOT, 'package.json'), 'utf8')
  assert.ok(!pkgRaw.includes('dsh-client-ui-primitives'), 'package.json 严禁残留 dsh-client-ui-primitives')

  const clientPath = path.join(PLUGIN_ROOT, 'lib', 'client.js')
  assert.equal(fs.existsSync(clientPath), true, 'lib/client.js 必须已由 build_client.mjs 生成')
  const clientRaw = fs.readFileSync(clientPath, 'utf8')
  assert.ok(!clientRaw.includes('dsh-client-ui-primitives'), 'lib/client.js 严禁引用 dsh-client-ui-primitives')
  assert.ok(clientRaw.includes('--dsw-alias-'), 'lib/client.js 必须使用 DSH 原生 --dsw-alias-* 主题令牌')
  assert.ok(clientRaw.includes('ThreeQuestionsView') && clientRaw.includes('LivingSurveyView') && clientRaw.includes('BranchDetailDrawer'))
})
