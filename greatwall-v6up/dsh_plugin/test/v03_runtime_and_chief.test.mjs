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
import { ORCHESTRATE_TOOL_SCHEMA, projectOrchestrateResultForAgent } from '../lib/orchestrate_tool.js'
import { normalizeSchemaForDsh } from '../lib/bridge/dsh_schema_adapter.js'
import { CANONICAL_ROLES, ROLE_MCP_TOOLS, SEALED_COMPANION_CONFERENCE_TOOLS } from '../lib/prompts.js'
import { createSandboxCallEvaluator } from '../lib/read_isolated_sandbox.js'
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

test('node takeover waits for RC5 jobs to exit before recording yield', async () => {
  const calls = []
  const job = { id: 'job_mine', owner: 'gw-exp-n1', status: 'running' }
  let finish
  const stopping = new Promise((resolve) => { finish = resolve })
  const jobs = {
    list: () => [job, { id: 'global_job', status: 'running' }],
    kill: (id) => { calls.push(id); return 'requested' },
    wait: () => stopping,
  }
  const bridge = { async control(method) { calls.push(method); return { ok: true } } }
  const coord = new HumanTakeoverCoordinator({ ctx: { get: () => jobs }, bridge, workspaceRoot: '/tmp/ws_ht' })
  await coord.recordHumanChat('n1', job.owner, '等一下，我来改参数')
  const draining = coord.drainAndYieldNode({
    nodeId: 'n1', sessionId: job.owner,
    liveHandle: { agent: { cancel: () => { calls.push('cancel') }, whenIdle: async () => {} } },
  })
  await new Promise(setImmediate)
  assert.deepEqual(calls, ['control_plane/record_human_chat_detected', 'cancel', 'job_mine'])
  finish({ ...job, status: 'killed' })
  assert.deepEqual((await draining).killedJobIds, ['job_mine'])
  assert.equal(calls.at(-1), 'control_plane/mark_node_yielded')
})

test('v0.3-5: ChiefRuntime 弹性锚点卡字数公式、高信噪比收件箱与原生 Action Card 注册/降级', async () => {
  assert.equal(computeChiefAnchorBudgetChars(1), 500)
  assert.equal(computeChiefAnchorBudgetChars(4), 720)
  assert.equal(computeChiefAnchorBudgetChars(20), 1500)
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
              ].filter((effect) => params.kinds.includes(effect.kind)),
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
  await consumer.whenIdle()
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
  const adapted = normalizeSchemaForDsh(ORCHESTRATE_TOOL_SCHEMA, { toolName: 'greatwall_orchestrate' })
  assert.ok(adapted?.properties?.total_budget?.properties?.max_total_handoffs)
  assert.ok(adapted?.properties?.initial_instruments?.items?.properties?.instrument_id)
  assert.ok(adapted?.properties?.seed_families?.items?.properties?.family_id)

  // 验证 Inline & Spill 投影：剔除 20KB+ 重型 snapshot/telemetry，同时零损失保留全部 10 个子题骨架
  const tenSubs = Array.from({ length: 10 }, (_, i) => ({
    question_id: `Q${i + 1}`,
    desired_state: 'ACTIVE',
    dispatch_state: 'DISPATCHING',
    active_spec_revision: 2,
    completed_waves: i,
    spent_tokens: 1000 * (i + 1),
    extra_huge_blob: 'X'.repeat(1200),
  }))
  const hugeRaw = {
    ok: true,
    action: 'start',
    started: true,
    status: {
      poolState: 'running',
      kernelAlive: true,
      initialized: true,
      stage: 'STAGE2_EVOLVE',
      autonomyMode: 'WAVE_CONFIRM',
      closureStatus: 'OPEN',
      humanStopActive: false,
      latestSpecRevision: 2,
      runningExplorersCount: 1,
      runningExplorers: [{ nodeId: 'n1', questionId: 'Q1', sessionId: 's1' }],
      runningGovernanceTasks: [],
      pendingProposalsCount: 0,
      pendingHandoffNodes: [],
      closureAllowed: false,
      subproblemStates: tenSubs,
      modelBinding: { ok: true, provider: 'deepseek-account', model: 'deepseek-chat' },
      effectiveContextWindow: 128000,
      snapshot: { goal_and_completion_md: 'G'.repeat(18000), huge_dup: tenSubs },
      telemetry: { sessions: { s1: { trace: 'T'.repeat(8000) } } },
    },
  }
  const projected = projectOrchestrateResultForAgent(hugeRaw)
  const serialized = JSON.stringify(projected)
  assert.equal(projected.ok, true)
  assert.equal(projected.started, true)
  assert.equal(projected.subproblemStates.length, 10, '绝不能砍掉任何一个子题')
  assert.equal(projected.snapshot, undefined)
  assert.equal(projected.telemetry, undefined)
  assert.ok(serialized.length < 4096, `投影体积必须远小于 8192 截断线，实测 ${serialized.length}`)
  assert.ok(projected.next_step_guidance.includes('gw-chief'))

  const skillPath = path.resolve(PLUGIN_ROOT, '..', 'core_python', 'skills', 'greatwall-research-loop', 'SKILL.md')
  const skillText = fs.readFileSync(skillPath, 'utf8')
  assert.ok(!skillText.includes('action: "init" | "start" | "status" | "pause"'), 'SKILL.md 不得残留 v0.2 已废除动作')
  assert.ok(!skillText.includes('物理剥夺了文件读写权'), 'SKILL.md 必须与裁决一同步，不得残留 gw-chief 剥夺文件读权禁令')
  assert.ok(skillText.includes('gw-chief'))

  // 回归：control_service(action="status") 将字段平铺在顶层（无 raw.status），投影必须完整保留所有字段
  const flatStatusRaw = {
    ok: true,
    action: 'status',
    callerSource: 'agent_tool',
    chiefPendingNotificationsCount: 0,
    poolState: 'running',
    state: 'running',
    kernelAlive: true,
    initialized: true,
    stage: 'STAGE1_PARSE0',
    autonomyMode: 'WAVE_CONFIRM',
    closureStatus: 'OPEN',
    humanStopActive: false,
    latestSpecRevision: 0,
    runningExplorersCount: 1,
    runningExplorers: [{ nodeId: 'n1', questionId: 'Q1', sessionId: 's1' }],
    runningGovernanceTasks: ['stage1:works_check'],
    pendingProposalsCount: 0,
    pendingHandoffNodes: [],
    closureAllowed: false,
    subproblemStates: tenSubs.slice(0, 4),
    modelBinding: { ok: true, provider: 'deepseek-account', model: 'deepseek-flash' },
    effectiveContextWindow: 500000,
    snapshot: { goal_and_completion_md: 'G'.repeat(18000) },
    telemetry: { sessions: {} },
  }
  const flatProj = projectOrchestrateResultForAgent(flatStatusRaw)
  assert.equal(flatProj.ok, true)
  assert.equal(flatProj.poolState, 'running')
  assert.equal(flatProj.kernelAlive, true, '平铺 status 不可丢失 kernelAlive')
  assert.equal(flatProj.initialized, true, '平铺 status 不可丢失 initialized')
  assert.equal(flatProj.stage, 'STAGE1_PARSE0', '平铺 status 不可丢失 stage')
  assert.equal(flatProj.subproblemStates.length, 4, '平铺 status 不可丢失 subproblemStates')
  assert.equal(flatProj.runningExplorersCount, 1)
  assert.deepEqual(flatProj.runningGovernanceTasks, ['stage1:works_check'])
  assert.equal(flatProj.snapshot, undefined)
  assert.equal(flatProj.telemetry, undefined)
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

test('v0.3-10: 全部 10 份角色 System Prompt 具备 Tool Guidance + Guardrails 且精确覆盖全部工具与权威枚举', () => {
  const agentsDir = path.resolve(PLUGIN_ROOT, '..', 'core_python', 'agents')
  for (const role of CANONICAL_ROLES) {
    const fp = path.join(agentsDir, `${role}.md`)
    assert.equal(fs.existsSync(fp), true, `缺失角色提示词: ${role}.md`)
    const text = fs.readFileSync(fp, 'utf8')
    assert.ok(text.includes('Tool Guidance'), `${role}.md 必须包含 Tool Guidance 章节`)
    assert.ok(text.includes('Guardrails'), `${role}.md 必须包含 Guardrails 章节`)
    for (const toolName of ROLE_MCP_TOOLS[role] || []) {
      assert.ok(text.includes(toolName), `${role}.md 缺少授权工具说明: ${toolName}`)
    }
  }

  const chiefMd = fs.readFileSync(path.join(agentsDir, 'gw_chief.md'), 'utf8')
  for (const act of [
    'AMEND_RULING_DRAFT',
    'AUTHORIZE_PARTIAL_DELIVERY',
    'APPROVE_WAVE_VERDICT',
    'ADVANCE_EPOCH',
  ]) {
    assert.ok(chiefMd.includes(act), `gw_chief.md 缺少真实提案枚举: ${act}`)
  }

  const chairMd = fs.readFileSync(path.join(agentsDir, 'conference_chair.md'), 'utf8')
  for (const act of ['OPEN_NEW_BRANCH', 'PROTECT', 'SPAWN_SYNTHESIS', 'HIBERNATE', 'DISCRIMINATOR', 'PAUSE_FOR_HUMAN']) {
    assert.ok(chairMd.includes(act), `conference_chair.md 缺少真实圆桌裁决枚举: ${act}`)
  }

  const survMd = fs.readFileSync(path.join(agentsDir, 'external_surveyor.md'), 'utf8')
  for (const rd of ['full_text', 'specified_sections', 'abstract_only']) {
    assert.ok(survMd.includes(rd), `external_surveyor.md 缺少真实 read_depth 枚举: ${rd}`)
  }
})

test('v0.3-11: 裁决一 & 二安全红线——gw_chief 只读工作区/分支代码但禁写禁终端禁读隐藏集；主工作区归属探索者仍锁死 Worktree', () => {
  const tmpWs = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v03_sec_'))
  const dataDir = path.join(tmpWs, '..', 'gw_plugin_data_ext')
  const wtDir = path.join(tmpWs, 'worktrees', 'b_q1_fam')
  const hiddenDir = path.join(tmpWs, 'evaluators', '_hidden_calibrations')
  fs.mkdirSync(wtDir, { recursive: true })
  fs.mkdirSync(hiddenDir, { recursive: true })
  fs.mkdirSync(dataDir, { recursive: true })
  fs.writeFileSync(path.join(tmpWs, 'problem.md'), '# B题', 'utf8')
  fs.writeFileSync(path.join(wtDir, 'solve.py'), 'print(1)', 'utf8')
  fs.writeFileSync(path.join(hiddenDir, 'secret.json'), '{}', 'utf8')
  try {
    const chiefEval = createSandboxCallEvaluator({
      role: 'gw_chief',
      workspaceRoot: tmpWs,
      protectedDirs: [dataDir],
    })
    assert.equal(chiefEval({ name: 'read', arguments: { path: path.join(tmpWs, 'problem.md') } }), undefined, 'gw_chief 应可只读工作区题面')
    assert.equal(chiefEval({ name: 'read', arguments: { path: path.join(wtDir, 'solve.py') } }), undefined, 'gw_chief 应可只读分支源码')
    assert.ok(chiefEval({ name: 'write', arguments: { path: path.join(wtDir, 'solve.py') } }), 'gw_chief 严禁写文件')
    assert.ok(chiefEval({ name: 'pwsh', arguments: { command: 'ls' } }), 'gw_chief 严禁终端')
    assert.ok(chiefEval({ name: 'read', arguments: { path: path.join(hiddenDir, 'secret.json') } }), 'gw_chief 严禁读隐藏校准集')
    assert.ok(chiefEval({ name: 'read', arguments: { path: path.join(dataDir, 'greatwall.db') } }), 'gw_chief 严禁读数据库')

    const expEval = createSandboxCallEvaluator({
      role: 'explorer',
      workspaceRoot: tmpWs,
      worktreeAbsPath: wtDir,
      protectedDirs: [dataDir],
    })
    assert.equal(expEval({ name: 'read', arguments: { path: 'solve.py' } }), undefined, '探索者应可读写本 Worktree 相对路径')
    assert.ok(expEval({ name: 'read', arguments: { path: path.join(tmpWs, 'evaluators', 'inst.py') } }), '探索者严禁越界读 evaluators')
    assert.ok(expEval({ name: 'read', arguments: { path: path.join(hiddenDir, 'secret.json') } }), '探索者严禁读隐藏校准集')

    const anchor = buildChiefAnchorCard(
      { initialized: true, stage: 'STAGE2_EVOLVE', autonomy_mode: 'WAVE_CONFIRM', latest_spec_revision: 0, closure_state: { status: 'OPEN' }, subproblem_runtime_state: [] },
      { liveRuntime: { runningExplorers: [{ nodeId: 'node_q1_1', questionId: 'Q1', sessionId: 'gw-exp-node_q1_1', elapsedSec: 42 }], runningGovernanceTasks: [] } },
    )
    assert.ok(anchor.includes('实时活跃探索者(1') && anchor.includes('node_q1_1'), '锚点卡必须内联实时在跑探索者')
  } finally {
    fs.rmSync(tmpWs, { recursive: true, force: true })
    fs.rmSync(dataDir, { recursive: true, force: true })
  }
})

test('v0.3-12: 全局暂停=全部等待人类接管 & 全局恢复=批量 SHA 对账全面托管，且非运行态暂停不再谎报成功', async () => {
  const { GreatwallOrchestrator } = await import('../lib/orchestrator.js')
  const { GreatwallControlService } = await import('../lib/control_service.js')
  const tmpWs = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v03_pause_unify_'))
  const controlCalls = []
  const fakeBridge = {
    async control(method, params) {
      controlCalls.push({ method, params })
      if (method === 'control_plane/schedule_snapshot') {
        return { ok: true, data: { human_paused_nodes: [{ node_id: 'node_q1_a' }, { node_id: 'node_q1_b' }] } }
      }
      return { ok: true, data: {} }
    },
    async dispose() {},
  }
  try {
    const orch = new GreatwallOrchestrator({
      ctx: {},
      bridge: fakeBridge,
      corePythonRoot: path.resolve(__dirname, '..', '..', 'core_python'),
      workspaceRoot: tmpWs,
      dataDir: path.join(tmpWs, '.data'),
    })
    // 1. 模拟运行中带 2 条活跃探索者，调用全局 pauseBackground -> 批量触发 pause_node
    orch._poolState = 'running'
    orch._runningExplorers.set('node_q1_a', { node: { node_id: 'node_q1_a', question_id: 'Q1' }, sessionId: 'gw-exp-node_q1_a' })
    orch._runningExplorers.set('node_q1_b', { node: { node_id: 'node_q1_b', question_id: 'Q1' }, sessionId: 'gw-exp-node_q1_b' })
    const pRes = await orch.pauseBackground()
    assert.equal(pRes.paused, true)
    assert.equal(orch._poolState, 'paused')
    assert.deepEqual(pRes.pausedNodeIds, ['node_q1_a', 'node_q1_b'])
    assert.equal(controlCalls.filter((c) => c.method === 'control_plane/pause_node').length, 2)

    // 2. 调用全局 resumeBackground -> 批量触发 resume_node (SHA 对账) 并切回 running
    const rRes = await orch.resumeBackground()
    assert.equal(rRes.resumed, true)
    assert.equal(orch._poolState, 'running')
    assert.deepEqual(rRes.resumedNodeIds, ['node_q1_a', 'node_q1_b'])
    assert.equal(controlCalls.filter((c) => c.method === 'control_plane/resume_node').length, 2)

    // 3. ControlService 在 idle 态调用 pause 绝不谎报 ok: true
    const svc = new GreatwallControlService({
      ctx: {},
      config: { corePythonRoot: path.resolve(__dirname, '..', '..', 'core_python'), dataDir: path.join(tmpWs, '.data') },
    })
    const ctrl = svc.createSessionController({ workspaceRoot: tmpWs })
    const idlePause = await svc.execute({ caller: 'human_ui', action: 'pause', workspaceRoot: tmpWs, controller: ctrl })
    assert.equal(idlePause.ok, false, 'idle 态暂停必须返回 ok:false 而非谎报成功')
    await svc.disposeAll()
  } finally {
    fs.rmSync(tmpWs, { recursive: true, force: true })
  }
})

test('v0.3-13: 三层对齐回归——TelemetryCollector 保留 stage/events/modelBinding + 停机态 UI 联合投影绝不误报攻关中', async () => {
  const { TelemetryCollector } = await import('../lib/telemetry.js')
  const vm = await import('node:vm')
  const tmpWs = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_v03_align_'))
  const dataDir = path.join(tmpWs, '.data')
  try {
    // 1. TelemetryCollector 重建必须保留 stage / startedAt / recentEvents / lastModelBinding
    const t1 = new TelemetryCollector({ workspaceRoot: tmpWs, dataDir })
    t1.setOrchestratorState('running', 'STAGE2_EVOLVE')
    t1.setModelBinding({ provider: 'deepseek-account', model: 'deepseek-flash', effectiveContextWindow: 272000 })
    t1.recordEvent('test_ev', { ok: true })
    const t2 = new TelemetryCollector({ workspaceRoot: tmpWs, dataDir })
    assert.equal(t2.state.stage, 'STAGE2_EVOLVE')
    assert.equal(t2.state.lastModelBinding?.model, 'deepseek-flash')
    assert.equal(t2.state.recentEvents.length, 1)

    // 2. 前端 ThreeQuestionsView & BranchDetailDrawer 在 poolState='stopped' 下绝不显示「攻关中」与「系统正按授权自主推进」
    const stylesSrc = fs.readFileSync(path.resolve(__dirname, '..', 'client_src', 'styles.js'), 'utf8')
    const threeSrc = fs.readFileSync(path.resolve(__dirname, '..', 'client_src', 'components', 'ThreeQuestionsView.js'), 'utf8')
    const branchSrc = fs.readFileSync(path.resolve(__dirname, '..', 'client_src', 'components', 'BranchDetailDrawer.js'), 'utf8')
    const sb = {
      jsx: (tag, props) => ({ tag, props }),
      jsxs: (tag, props) => ({ tag, props }),
      React: { useState: (init) => [typeof init === 'function' ? init() : init, () => {}] },
      openNativeSession: () => true,
    }
    vm.createContext(sb)
    vm.runInContext(`${stylesSrc}\n${threeSrc}\n${branchSrc}`, sb)
    const sampleData = {
      status: { poolState: 'stopped', stage: 'STAGE2_EVOLVE', activeSessions: [], runningExplorers: [] },
      inspector: {
        subproblem_runtime_state: [{ question_id: 'Q1', dispatch_state: 'DISPATCHING', desired_state: 'ACTIVE', active_spec_revision: 0 }],
        pending_proposals: [],
        internal_ledger: [{ entry_id: 'L3-001', question_id: 'Q1', ledger_type: 'L3_VERIFIED', is_active: 1, title: '定理一', exact_verified_scope_md: '已验证' }],
        lineage_nodes: [{ node_id: 'node_q1_1', question_id: 'Q1', family_id: 'F1', node_status: 'EXPLORING', control_state: 'AUTO_RUNNING', generation: 1 }],
        method_families: [{ family_id: 'F1', mechanism_signature: '几何法' }],
      },
      telemetryState: { sessions: {} },
    }
    const threeOut = JSON.stringify(sb.ThreeQuestionsView({ data: sampleData, busy: false, onControl: () => {} }))
    assert.ok(threeOut.includes('待恢复(未运行)'), '停机态子题必须显示待恢复而非攻关中')
    assert.ok(!threeOut.includes('系统正按授权全面托管推进中'), '停机态绝不可声称正在自主推进')
    assert.ok(threeOut.includes('L3-001') && threeOut.includes('定理一'), 'L3 列表必须正常渲染')

    const branchOut = JSON.stringify(sb.BranchDetailDrawer({ data: sampleData, busy: false, onControl: () => {}, getUiWorkspace: () => null }))
    assert.ok(branchOut.includes('已停机待续'), '停机态分支必须显示已停机待续而非攻关中')
    assert.ok(!branchOut.includes('暂停接管'), '停机态绝不可显示单节点暂停接管按钮')
  } finally {
    fs.rmSync(tmpWs, { recursive: true, force: true })
  }
})
