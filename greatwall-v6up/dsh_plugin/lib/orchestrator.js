/**
 * 长城 V6-Up (v2.2) 外部无状态异步事件池编排器（精简调度核心）：
 *
 * - 组合 `AgentSessionHost`（同区会话与 Preset/冷恢复）与 `pair_lifecycle`（探索-伴随配对与两轮问答）；
 * - 专责 `start | pause | resume | stop | status | intervene` 真异步后台调度与 Stage 1/2/3 状态机流转。
 * @module dsh-greatwall-v6up/orchestrator
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { loadCoreRuntimeConfig, loadRolePrompts } from './prompts.js'
import { ensurePresetsInstalled } from './presets.js'
import { TelemetryCollector } from './telemetry.js'
import { AgentSessionHost, createUserTextMessage } from './agent_session_host.js'
import { driveExplorerCompanionPair } from './pair_lifecycle.js'

export class GreatwallOrchestrator {
  constructor({
    ctx,
    bridge,
    corePythonRoot,
    workspaceRoot,
    dataDir = '',
    protectedDirs = [],
    defaultAgentOptions = {},
    parentAgent = null,
    autoArchiveShortTx = true,
  }) {
    this.ctx = ctx
    this.bridge = bridge
    this.corePythonRoot = path.resolve(corePythonRoot)
    this.workspaceRoot = path.resolve(workspaceRoot)
    this.dataDir = dataDir
    this.parentAgent = parentAgent

    this.runtimeConfig = loadCoreRuntimeConfig(this.corePythonRoot)
    this.rolePrompts = loadRolePrompts(this.corePythonRoot)
    this.telemetry = new TelemetryCollector({ workspaceRoot: this.workspaceRoot, dataDir })

    try {
      ensurePresetsInstalled({
        localPresetsDir: path.resolve(this.corePythonRoot, '..', 'dsh_plugin', 'presets'),
      })
    } catch {}

    this.host = new AgentSessionHost({
      ctx,
      bridge,
      workspaceRoot: this.workspaceRoot,
      rolePrompts: this.rolePrompts,
      protectedDirs,
      defaultAgentOptions,
      autoArchiveShortTx,
      telemetry: this.telemetry,
    })

    this._interventions = []
    this._poolState = 'idle'
    this._loopAbortController = null
    this._backgroundTask = null
    this._wakeResolvers = []
    this._runningExplorers = new Map()
    this._runningGov = new Map()
    this._pendingSalvageNodes = new Map()
    this._handoffsSinceHeartbeat = 0
    this._lastHeartbeatAt = 0
    this._stage3Done = false
  }

  get liveSessions() {
    return this.host.liveSessions
  }

  set defaultAgentOptions(val) {
    this.host.defaultAgentOptions = val
  }

  get defaultAgentOptions() {
    return this.host.defaultAgentOptions
  }

  spawnAndRunAgent(opts) {
    return this.host.spawnAndRunAgent(opts)
  }

  continueAliveAgent(sessionId, promptText, opts) {
    return this.host.continueAliveAgent(sessionId, promptText, opts)
  }

  _formatInterventionsForTarget(role, questionId = '', nodeId = '') {
    const matched = this._interventions.filter((iv) => {
      if (iv.targetType === 'global') return true
      if (iv.targetType === 'question' && questionId && iv.targetId === questionId) return true
      if (iv.targetType === 'node' && nodeId && iv.targetId === nodeId) return true
      if (iv.targetType === 'role' && iv.targetId === role) return true
      return false
    })
    if (!matched.length) return ''
    return '## 人类 / 主控最新定向纠偏指令\n' + matched.slice(-5).map((m) => `- [${m.at}] (${m.targetType}:${m.targetId}) ${m.directive}`).join('\n')
  }

  _appendInterventions(baseText, role, questionId = '', nodeId = '') {
    const iv = this._formatInterventionsForTarget(role, questionId, nodeId)
    const base = String(baseText || '').trim()
    if (!iv) return base
    return base ? `${iv}\n\n${base}` : iv
  }

  _interventionMatchesSession(entry, sessEntry) {
    if (!sessEntry) return false
    if (entry.targetType === 'global') return true
    if (entry.targetType === 'role') return sessEntry.role === entry.targetId
    if (entry.targetType === 'question') return Boolean(sessEntry.questionId) && sessEntry.questionId === entry.targetId
    if (entry.targetType === 'node') return Boolean(sessEntry.nodeId) && sessEntry.nodeId === entry.targetId
    return false
  }

  _wakeLoop() {
    for (const r of this._wakeResolvers.splice(0)) {
      try { r() } catch {}
    }
  }

  _waitWakeOrTimeout(ms) {
    return new Promise((resolve) => {
      const t = setTimeout(() => resolve(), ms)
      this._wakeResolvers.push(() => {
        clearTimeout(t)
        resolve()
      })
    })
  }

  async startBackground({ maxConcurrentWorkers = null, agentOptions = {} } = {}) {
    if (this._poolState === 'running' && this._backgroundTask) {
      return { started: true, alreadyRunning: true, status: await this.getControlStatus() }
    }
    if (agentOptions && Object.keys(agentOptions).length > 0) {
      this.defaultAgentOptions = { ...this.defaultAgentOptions, ...agentOptions }
    }
    if (!this._loopAbortController || this._loopAbortController.signal.aborted) {
      this._loopAbortController = new AbortController()
    }
    this._poolState = 'running'
    this._stage3Done = false
    this.telemetry.setOrchestratorState('running')
    this.telemetry.recordEvent('orchestrator_start', { maxConcurrentWorkers })

    this._backgroundTask = this._runAsyncEventPool({ maxConcurrentWorkers })
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          this.telemetry.recordEvent('orchestrator_error', { error: String(err?.message || err) })
        }
      })
      .finally(() => {
        if (this._poolState === 'running') {
          this._poolState = 'idle'
          this.telemetry.setOrchestratorState('idle')
        }
        this._backgroundTask = null
      })

    return { started: true, alreadyRunning: false, status: await this.getControlStatus() }
  }

  pauseBackground() {
    if (this._poolState !== 'running') return { paused: false, state: this._poolState }
    this._poolState = 'paused'
    this.telemetry.setOrchestratorState('paused')
    this.telemetry.recordEvent('orchestrator_pause')
    this._wakeLoop()
    return { paused: true, state: this._poolState }
  }

  resumeBackground() {
    if (this._poolState === 'paused') {
      this._poolState = 'running'
      this.telemetry.setOrchestratorState('running')
      this.telemetry.recordEvent('orchestrator_resume')
      this._wakeLoop()
      return { resumed: true, state: this._poolState }
    }
    return { resumed: false, state: this._poolState }
  }

  async stopBackground(reason = 'USER_STOPPED') {
    this._poolState = 'stopped'
    this.telemetry.setOrchestratorState('stopped')
    this.telemetry.recordEvent('orchestrator_stop', { reason })
    if (this._loopAbortController) {
      try {
        this._loopAbortController.abort(new Error(reason))
      } catch {}
    }
    for (const entry of this.liveSessions.values()) {
      try {
        entry.handle?.agent?.cancel?.({ kind: 'parent' })
      } catch {}
    }
    this._wakeLoop()
    if (this._backgroundTask) {
      await Promise.race([
        this._backgroundTask.catch(() => {}),
        new Promise((r) => setTimeout(r, 2500)),
      ])
    }
    const leftovers = [...this.liveSessions.values()]
    if (leftovers.length > 0) {
      await Promise.allSettled(leftovers.map((entry) => entry.handleDispose('aborted', { kind: 'aborted' })))
    }
    return { stopped: true, state: this._poolState }
  }

  async intervene({ targetType = 'global', targetId = 'ALL', directive = '', action = 'steer' } = {}) {
    const cleanAct = String(action || 'steer').toLowerCase()
    const entry = { targetType, targetId, directive: String(directive || ''), action: cleanAct }
    this._interventions.push({ at: new Date().toISOString(), ...entry })
    this.telemetry.addIntervention(entry)

    const steeredSessions = []
    if (cleanAct === 'steer' && entry.directive.trim()) {
      for (const [sid, sessEntry] of this.liveSessions.entries()) {
        if (!this._interventionMatchesSession(entry, sessEntry)) continue
        const steerFn = sessEntry?.handle?.agent?.steer
        if (typeof steerFn !== 'function') continue
        try {
          steerFn.call(
            sessEntry.handle.agent,
            createUserTextMessage(
              `[人类/主控实时定向纠偏 (${entry.targetType}:${entry.targetId})]\n请立即优先执行以下纠偏指令，勿继续无效重复检索或循环：\n${entry.directive}`,
              'user',
            ),
          )
          steeredSessions.push({
            sessionId: sid,
            role: sessEntry.role || '',
            questionId: sessEntry.questionId || '',
            nodeId: sessEntry.nodeId || '',
          })
        } catch {}
      }
    }

    if (cleanAct === 'abort_node' && targetId) {
      const running = this._runningExplorers.get(targetId)
      if (running) {
        const sessEntry = this.liveSessions.get(running.sessionId)
        try {
          sessEntry?.handle?.agent?.cancel?.({ kind: 'parent' })
        } catch {}
      }
    }
    this.telemetry.recordEvent('human_intervention', { ...entry, steeredSessions })
    this._wakeLoop()
    return { intervened: true, intervention: entry, steeredSessions, status: await this.getControlStatus() }
  }

  async getControlStatus() {
    let snapData = null
    try {
      const res = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      snapData = res?.data || null
    } catch {}
    const liveList = [...this.liveSessions.entries()].map(([sid, s]) => ({
      sessionId: sid,
      role: s.role,
      questionId: s.questionId,
      nodeId: s.nodeId,
      label: s.uiLabel,
      startedAt: s.startedAt,
    }))
    return {
      poolState: this._poolState,
      stage: snapData?.stage || this.telemetry.state.stage,
      runningExplorersCount: this._runningExplorers.size,
      runningExplorers: [...this._runningExplorers.values()].map((e) => ({
        nodeId: e.node.node_id,
        questionId: e.node.question_id,
        sessionId: e.sessionId,
      })),
      runningGovernanceTasks: [...this._runningGov.keys()],
      activeSessions: liveList,
      pendingSalvageNodes: [...this._pendingSalvageNodes.keys()],
      closureAllowed: Boolean(snapData?.closure_gate?.closure_allowed),
      snapshot: snapData,
      telemetry: this.telemetry.getSummary(),
    }
  }

  _launchGovTask(taskKey, runner) {
    if (this._runningGov.has(taskKey)) return false
    const p = Promise.resolve()
      .then(runner)
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          this.telemetry.recordEvent('gov_task_error', { taskKey, error: String(err?.message || err) })
        }
      })
      .finally(() => {
        this._runningGov.delete(taskKey)
        this._syncSlotsToTelemetry()
        this._wakeLoop()
      })
    this._runningGov.set(taskKey, p)
    this._syncSlotsToTelemetry()
    return true
  }

  async _launchGovTaskAndAwaitIfSync(taskKey, fn) {
    this._launchGovTask(taskKey, fn)
    const p = this._runningGov.get(taskKey)
    if (p) await p
  }

  _syncSlotsToTelemetry(stage = '') {
    this.telemetry.updateActiveSlots({
      stage,
      activeExplorers: [...this._runningExplorers.values()].map((e) => ({
        nodeId: e.node.node_id,
        questionId: e.node.question_id,
        sessionId: e.sessionId,
      })),
      activeGovernance: [...this._runningGov.keys()],
    })
  }

  _launchExplorerWorker(node, snap, sig) {
    const expSessionId = `gw_exp_${node.node_id}_${crypto.randomUUID().slice(0, 6)}`
    const p = driveExplorerCompanionPair(this, node, snap, expSessionId, { signal: sig })
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          this.telemetry.recordEvent('explorer_worker_error', { nodeId: node.node_id, error: String(err?.message || err) })
        }
      })
      .finally(() => {
        this._runningExplorers.delete(node.node_id)
        this._syncSlotsToTelemetry()
        this._wakeLoop()
      })
    this._runningExplorers.set(node.node_id, {
      promise: p,
      node,
      sessionId: expSessionId,
      startedAt: Date.now(),
    })
    this._syncSlotsToTelemetry()
  }

  async _runAsyncEventPool({ maxConcurrentWorkers = null } = {}) {
    const sig = this._loopAbortController.signal
    let idleStreak = 0

    while (!sig.aborted && this._poolState !== 'stopped') {
      if (this._poolState === 'paused') {
        await this._waitWakeOrTimeout(400)
        continue
      }

      const snapRes = await this.bridge.control('control_plane/schedule_snapshot', {
        workspace_root: this.workspaceRoot,
        max_concurrent_workers: maxConcurrentWorkers,
      })
      const snap = snapRes?.data
      if (!snap || snap.stage === 'CLOSED' || this._stage3Done) {
        this.telemetry.setOrchestratorState('idle', snap?.stage || 'CLOSED')
        break
      }
      this._syncSlotsToTelemetry(snap.stage)

      let dispatchedSomething = false

      if (this._pendingSalvageNodes.size > 0) {
        for (const [nid, info] of this._pendingSalvageNodes.entries()) {
          if (this._launchGovTask(`salvage:${nid}`, async () => {
            this._pendingSalvageNodes.delete(nid)
            await this.spawnAndRunAgent({
              role: 'lineage_companion',
              nodeId: nid,
              branchId: info.node.branch_id,
              questionId: info.node.question_id,
              cwd: info.node.worktree_abs_path,
              uiLabel: `[伴随-${info.node.question_id}] 崩溃打捞 ${nid}`,
              shortTransaction: true,
              signal: sig,
              taskContextText: this._appendInterventions(
                `### 节点意外中断打捞 (${info.reason})\n${info.blackboxSummary}`,
                'lineage_companion',
                info.node.question_id,
                nid,
              ),
              prompt: `探索者 ${nid} 异常中断（${info.reason}）。请调 get_companion_context(branch_id="${info.node.branch_id}", node_id="${nid}", mode="HANDOFF_70")，扫描实测与 worktree，有 [Obs###] 则 submit_node_handoff 入 DAG，若零实测崩溃则设 is_zero_eval_crash=true 写 scratch_log！`,
            })
            this._handoffsSinceHeartbeat += 1
          })) {
            dispatchedSomething = true
          }
        }
      }

      if (snap.stage === 'STAGE1_PARSE0') {
        if (snap.missing_hooks_or_fidelity?.length > 0) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage1:works', () =>
            this.spawnAndRunAgent({
              role: 'works_engineer',
              uiLabel: `[工造司] Parse0 建钩 (${snap.missing_hooks_or_fidelity.join(',')})`,
              shortTransaction: false,
              signal: sig,
              taskContextText: this._appendInterventions(
                `### 当前课题与子题列表\n${snap.goal_md || ''}\n### 子题契约\n${JSON.stringify(snap.contracts || {}, null, 2)}`,
                'works_engineer',
              ),
              prompt: `Stage 1 (Parse 0)：请为子题 ${snap.missing_hooks_or_fidelity.join(', ')} 编写各自隔离基线 baselines/baseline_<Q>.py 与钩子 evaluators/hooks/hook_<Q>.py（metrics 含 rank_score 且严禁 mpmath 慢循环），并调用 register_question_domain_hook 逐一注册（必须传入 public_input_sample，保证误差 <5%）。`,
            }),
          )
          continue
        }

        if (Number(snap.external_literature_count || 0) === 0) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage1:surveyor', () =>
            this.spawnAndRunAgent({
              role: 'library_surveyor',
              uiLabel: '[图书馆采编] 开局文献建卡',
              shortTransaction: false,
              signal: sig,
              taskContextText: this._appendInterventions(
                `### 课题 Goal\n${snap.goal_md || ''}`,
                'library_surveyor',
              ),
              prompt: `Stage 1 开局快速外藏建设：目前 external_literature_cards 为 0（阻塞后续编排启动）。\n1. 请直接依据课题 Goal 中的子题 ${JSON.stringify(snap.required_questions || [])} 核心数学物理机制，立即构造标准定理/解析算子卡片 [R001] 并调用 publish_external_literature_card 入库（无需在 Stage 1 执着连续多轮网搜或反复阅读工作区 baselines 脚本）。\n2. 严格遵守 Schema 约束：support_scope 必须使用英文枚举（如 DIRECT_PROOF_OR_EXACT_MEASUREMENT），read_depth 使用英文枚举（full_text | specified_sections | abstract_only），abstract_md 长度需在 60–1500 字之间（推荐 120–500 字独立高密度摘要）。\n3. 一旦成功发布 [R001] 并收到 ok: true，立即结束本会话以放行编排！`,
            }),
          )
          continue
        }

        if (snap.explorers_needing_briefing?.length === 0 && snap.explorers_ready_to_run?.length === 0) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage1:logistics_init', () =>
            this.spawnAndRunAgent({
              role: 'logistics_coordinator',
              uiLabel: '[后勤总管] Parse0 学派建档',
              shortTransaction: false,
              signal: sig,
              taskContextText: this._appendInterventions(
                `### 课题 Goal\n${snap.goal_md || ''}\n### 依赖状态\n${JSON.stringify(snap.question_dependencies || {}, null, 2)}\n### 公开输入契约\n${JSON.stringify(snap.public_input_samples || {}, null, 2)}`,
                'logistics_coordinator',
              ),
              prompt: `Stage 1 初始学派建档：请先调 get_logistics_dashboard 查看完整 goal_md 与 question_dependencies（只读 problem_pack/ 核实原题约束），为已解锁的子题各 register_method_family 至少 2 个贴合本题的正交学派并 fork_branch 开启探索分支（勿对未解锁前置依赖的子题浪费槽位）。`,
            }),
          )
          continue
        }

        dispatchedSomething = true
        await this._launchGovTaskAndAwaitIfSync('stage1:gate', () =>
          this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage1 门禁',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '请调用 get_supervisory_audit_snapshot 与 record_compliance_check(stage="STAGE1_GATE", status="PASSED") 核验钩子保真 <5% 并放行进入 STAGE2_EVOLVE。',
          }),
        )
        continue
      }

      for (const node of snap.explorers_needing_briefing || []) {
        if (this._launchGovTask(`brief:${node.node_id}`, () =>
          this.spawnAndRunAgent({
            role: 'lineage_companion',
            nodeId: node.node_id,
            branchId: node.branch_id,
            questionId: node.question_id,
            cwd: node.worktree_abs_path,
            uiLabel: `[伴随-${node.question_id}] 行前看板 ${node.node_id}`,
            shortTransaction: true,
            signal: sig,
            taskContextText: this._formatInterventionsForTarget('lineage_companion', node.question_id, node.node_id),
            prompt: `请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="PRE_SPAWN")，严格按五段预算 (<=2200字) 调用 save_lineage_briefing 写入初始看板。`,
          }),
        )) {
          dispatchedSomething = true
        }
      }

      if (snap.pending_surveys?.length > 0) {
        const reqIds = snap.pending_surveys.map((r) => r.request_id)
        if (this._launchGovTask('survey:pending', () =>
          this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: `[图书馆采编] 响应查新 (${reqIds.length}单)`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_surveyor'),
            prompt: `待采编外部文献请求 ${JSON.stringify(reqIds)} 已就绪，请先调 get_survey_requests 查看具体问题与检索词，然后调 publish_external_literature_card 写入标准外藏卡片 [R###]（务必传入对应的 fulfilled_request_ids 以精准核销！）。`,
          }),
        )) {
          dispatchedSomething = true
        }
      }

      if (snap.open_works_tickets?.length > 0 || snap.pending_revalidation?.length > 0) {
        if (this._launchGovTask('works:queue', () =>
          this.spawnAndRunAgent({
            role: 'works_engineer',
            uiLabel: '[工造司] 痛点/局部重评',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'works_engineer'),
            prompt: '请调 get_works_engineering_queue 检查未处理痛点与待重评队列：存在待重评观测请逐条调 recompute_stage_b_only；需要升版钩子请走 upgrade_hook_with_rqgm_gate。',
          }),
        )) {
          dispatchedSomething = true
        }
      }

      if (snap.awaiting_triage?.length > 0 || (snap.questions_needing_branch?.length > 0 && !this._runningGov.has('stage1:logistics_init'))) {
        if (this._launchGovTask('logistics:triage', async () => {
          const triageCount = snap.awaiting_triage?.length || 0
          const needQs = snap.questions_needing_branch || []
          await this.spawnAndRunAgent({
            role: 'logistics_coordinator',
            uiLabel: `[后勤总管] ${triageCount > 0 ? `分诊 (${triageCount}节点)` : `解锁派单 (${needQs.join(',')})`}`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions(
              `### 依赖状态\n${JSON.stringify(snap.question_dependencies || {}, null, 2)}`,
              'logistics_coordinator',
            ),
            prompt: triageCount > 0
              ? `有 ${triageCount} 个节点处于 AWAITING_TRIAGE！请调 get_logistics_dashboard 查看观测分数 (comparable_rank_score)、依赖状态与停滞计数，逐一调用 triage_node 裁决，并在满足前置依赖解锁时派生新分支！`
              : `子题 ${needQs.join(', ')} 前置依赖已解锁且尚无探索分支！请调 get_logistics_dashboard 检查依赖与学派状态，为这些子题调用 register_method_family / fork_branch 开启探索分支！`,
          })
          this._handoffsSinceHeartbeat += triageCount
        })) {
          dispatchedSomething = true
        }
      }

      for (const rev of snap.pending_reviews || []) {
        if (this._launchGovTask(`review:${rev.review_id}`, async () => {
          const uniqueVerifierSid = `gw_ver_${rev.review_id}_${crypto.randomUUID().slice(0, 6)}`
          await this.spawnAndRunAgent({
            role: 'library_verifier',
            sessionId: uniqueVerifierSid,
            questionId: rev.question_id,
            uiLabel: `[图书馆盲审] ${rev.question_id || ''} ${rev.review_id}`.trim(),
            shortTransaction: true,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_verifier', rev.question_id || ''),
            prompt: rev.review_status === 'STAGE1_BLIND'
              ? `请以异会话执行盲审单 ${rev.review_id} (${rev.question_id})：先调 get_blind_manuscript，完成 Stage 1 不可逆账本；若通过，再调 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict。`
              : `请对审稿单 ${rev.review_id} (${rev.question_id}) 调用 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成 Stage 2 终审。`,
          })
        })) {
          dispatchedSomething = true
        }
      }

      if (snap.stagnation_triggered) {
        if (this._launchGovTask('logistics:stagnation', () =>
          this.spawnAndRunAgent({
            role: 'logistics_coordinator',
            uiLabel: '[后勤总管] 停滞五车道打散',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'logistics_coordinator'),
            prompt: '停滞看门狗已触发！请立即调用 get_logistics_dashboard 与 dispatch_stagnation_five_lanes 对停滞分支执行五车道重排。',
          }),
        )) {
          dispatchedSomething = true
        }
      }

      const nowMs = Date.now()
      if (snap.stage === 'STAGE2_EVOLVE' && (this._handoffsSinceHeartbeat >= 2 || (this._lastHeartbeatAt > 0 && nowMs - this._lastHeartbeatAt > 180_000))) {
        if (this._launchGovTask('supervisory:heartbeat', async () => {
          this._handoffsSinceHeartbeat = 0
          this._lastHeartbeatAt = Date.now()
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage2 心跳对账',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '执行 STAGE2_HEARTBEAT 周期对账：请调 get_supervisory_audit_snapshot 核对未读声明引用与越权告警，调 record_compliance_check(stage="STAGE2_HEARTBEAT", status="PASSED" 或 "ALERT") 落库。',
          })
        })) {
          dispatchedSomething = true
        }
      }
      if (this._lastHeartbeatAt === 0) this._lastHeartbeatAt = nowMs

      const slotCap = Math.max(1, Number(snap.slot_cap || 6))
      for (const node of snap.explorers_ready_to_run || []) {
        if (this._runningExplorers.size >= slotCap) break
        if (this._runningExplorers.has(node.node_id)) continue
        dispatchedSomething = true
        this._launchExplorerWorker(node, snap, sig)
      }

      if (snap.closure_gate?.closure_allowed && snap.stage === 'STAGE2_EVOLVE' && this._runningExplorers.size === 0 && !this._runningGov.has('stage3:pipeline')) {
        dispatchedSomething = true
        await this._launchGovTaskAndAwaitIfSync('stage3:pipeline', async () => {
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage2 结题锁',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '全卷子题 L3_VERIFIED 均已达标！请调用 check_stage2_closure_gate 并签发 record_compliance_check(stage="STAGE2_CLOSURE_GATE", status="PASSED")。',
          })
          await this.spawnAndRunAgent({
            role: 'library_verifier',
            sessionId: `gw_ver_comp_${crypto.randomUUID().slice(0, 6)}`,
            uiLabel: '[图书馆盲审] Stage3 Comparator 择优',
            shortTransaction: true,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_verifier'),
            prompt: '进入 Stage 3 Comparator！请调用 get_unblinded_manuscript_and_peers(review_id="STAGE3_COMPARATOR") 拉取全卷 active L3_VERIFIED 及其 best_comparable_rank_score，比较各子题最优条目并输出结构化推荐排名（无需改写库）。',
          })
          await this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: '[图书馆采编] Stage3 论文汇编导出',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_surveyor'),
            prompt: 'Comparator 择优就绪！请调 get_survey_requests 读取 stage3_synthesis_bundle，撰写正式综合论文报告并调用 export_stage3_final_delivery 导出 final_delivery 五件套。',
          })
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage3 终审闭环',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '请执行最终核对，调用 get_supervisory_audit_snapshot 与 record_compliance_check(stage="STAGE3_FINAL_AUDIT", status="PASSED") 正式闭环。',
          })
          this._stage3Done = true
        })
        continue
      }

      if (!dispatchedSomething && this._runningExplorers.size === 0 && this._runningGov.size === 0) {
        idleStreak += 1
        if (idleStreak >= 3) break
      } else {
        idleStreak = 0
      }

      await this._waitWakeOrTimeout(250)
    }
  }

  async runUntilClosed({ signal = null, maxCycles = 25, maxConcurrentWorkers = null } = {}) {
    void maxCycles
    this._loopAbortController = new AbortController()
    const onExtAbort = () => this._loopAbortController.abort(new Error('EXTERNAL_SIGNAL_ABORTED'))
    if (signal) {
      if (signal.aborted) onExtAbort()
      else signal.addEventListener('abort', onExtAbort, { once: true })
    }
    this._poolState = 'running'
    this._stage3Done = false
    this.telemetry.setOrchestratorState('running')
    let aborted = false
    try {
      await this._runAsyncEventPool({ maxConcurrentWorkers })
    } catch (err) {
      if (err?.code === 'GREATWALL_RUN_ABORTED' || this._loopAbortController.signal.aborted) aborted = true
      else throw err
    } finally {
      if (signal) signal.removeEventListener('abort', onExtAbort)
      this._poolState = 'idle'
      this.telemetry.setOrchestratorState('idle')
    }
    const finalSnap = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
    return {
      closed: finalSnap?.data?.stage === 'CLOSED' || this._stage3Done,
      aborted,
      snapshot: finalSnap?.data,
    }
  }

  async disposeAll() {
    await this.stopBackground('DISPOSE_ALL')
    await this.host.disposeAllSessions()
  }
}
