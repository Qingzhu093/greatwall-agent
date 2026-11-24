/**
 * 长城 V6-Up (v3.0) 外部无状态异步事件池编排器主入口。
 *
 * 职责划分（子模块位于 `./orchestrator/`）：
 * - `orchestrator/circuit_breaker.js`：单条待办项熔断器、探索者合法性过滤与客观指纹构造；
 * - `orchestrator/dispatch_stage1.js`：Stage 1 (Parse 0) 四步初始化派发；
 * - `orchestrator/dispatch_stage2.js`：Stage 2 待交接恢复、五类治理角色与探索者并发派发；
 * - `orchestrator/dispatch_stage3.js`：Stage 3 退修重导、盲审终核与监察联合终签派发；
 * - 本文件：编排器生命周期控制（start / pause / resume / stop / humanStop / abortNode / submitWorksTicket / syncPublicRulings）与极简主循环骨架。
 * @module dsh-greatwall-v6up/orchestrator
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { loadCoreRuntimeConfig, loadRolePrompts } from './prompts.js'
import { ensurePresetsInstalled } from './presets.js'
import { TelemetryCollector } from './telemetry.js'
import { AgentSessionHost, resolveAuthoritativeModelBinding } from './agent_session_host.js'
import { disposeNodeCompanion, driveExplorerCompanionPair } from './pair_lifecycle.js'
import {
  GovernanceItemCircuitBreaker,
  selectDispatchableExplorers,
} from './orchestrator/circuit_breaker.js'
import { dispatchStage1Step } from './orchestrator/dispatch_stage1.js'
import {
  dispatchPendingHandoffRecoveries,
  dispatchStage2Step,
} from './orchestrator/dispatch_stage2.js'
import { dispatchStage3Step } from './orchestrator/dispatch_stage3.js'

export { GovernanceItemCircuitBreaker, selectDispatchableExplorers }

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

    const clkCfg = this.runtimeConfig?.session_context_clock || {}
    const orchCfg = this.runtimeConfig?.orchestration_and_eval || {}
    this._windowCapTokens = Number(clkCfg.context_window_cap_tokens || clkCfg.context_window_tokens || 500_000)
    this._requireExplicitModelBinding = orchCfg.require_explicit_model_binding !== false
    this._itemBreaker = new GovernanceItemCircuitBreaker(
      Number(orchCfg.governance_item_circuit_breaker_max_stalled_runs || 2),
    )

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
      parentAgent: this.parentAgent,
      protectedDirs,
      defaultAgentOptions,
      effectiveContextWindow: this._windowCapTokens,
      autoArchiveShortTx,
      telemetry: this.telemetry,
    })

    this._modelBinding = null
    this._poolState = 'idle'
    this._loopAbortController = null
    this._backgroundTask = null
    /** @type {Set<() => void>} */
    this._wakeResolvers = new Set()
    this._lastError = null
    this._runningExplorers = new Map()
    this._runningGov = new Map()
    this._govCooldownUntil = new Map()
    /** 单节点同会话伴随暂停保活句柄表（严格按 node_id 绑定，绝不跨代复用） */
    this._nodeCompanionSessions = new Map()
    this._handoffsSinceHeartbeat = 0
    this._lastHeartbeatAt = 0
    this._seenAmbiguousAlertIds = new Set()
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

  _wakeLoop() {
    for (const r of [...this._wakeResolvers]) {
      this._wakeResolvers.delete(r)
      try { r() } catch {}
    }
  }

  _waitWakeOrTimeout(ms) {
    return new Promise((resolve) => {
      const done = () => {
        this._wakeResolvers.delete(done)
        clearTimeout(t)
        resolve()
      }
      const t = setTimeout(done, ms)
      this._wakeResolvers.add(done)
    })
  }

  /**
   * 启动前强制解析并锁定权威模型绑定与自适应窗口 W = min(500k, model_window)。
   * 缺 provider/model 时绝不静默放行，彻底杜绝第五轮隐式跌落到第三方中转站事故！
   */
  async _resolveAndLockModelBinding({ explicitOptions = {}, callerAgent = null } = {}) {
    const binding = await resolveAuthoritativeModelBinding({
      explicitOptions,
      callerAgent: callerAgent || this.parentAgent,
      ctx: this.ctx,
      configDefaultOptions: this.defaultAgentOptions,
      runtimeDefaultWindow: this._windowCapTokens,
    })
    if (!binding.ok && this._requireExplicitModelBinding) {
      return binding
    }
    if (binding.ok) {
      this.defaultAgentOptions = {
        ...this.defaultAgentOptions,
        provider: binding.provider,
        model: binding.model,
      }
    }
    this.host.effectiveContextWindow = binding.effectiveContextWindow || this._windowCapTokens
    this._modelBinding = binding
    this.telemetry.recordEvent('model_binding_locked', {
      provider: binding.provider || '(none)',
      model: binding.model || '(none)',
      effectiveContextWindow: this.host.effectiveContextWindow,
      detectedModelWindow: binding.detectedModelWindow,
      source: binding.source,
    })
    return binding
  }

  async startBackground({ maxConcurrentWorkers = null, agentOptions = {}, callerAgent = null } = {}) {
    if (callerAgent) {
      this.parentAgent = callerAgent
      this.host.parentAgent = callerAgent
    }
    // 幂等保护：若后台循环仍在存活，running 直接返回，paused 则恢复原循环，严禁起第二条并发循环
    if (this._backgroundTask) {
      if (this._poolState === 'paused') {
        await this.resumeBackground()
        return { started: true, alreadyRunning: true, resumed: true, status: await this.getControlStatus() }
      }
      if (this._poolState === 'running') {
        return { started: true, alreadyRunning: true, status: await this.getControlStatus() }
      }
    }

    // 1. 显式模型绑定硬门禁（未解析到明确 provider/model 一律拒启，绝不跌落未授权默认模型）
    const binding = await this._resolveAndLockModelBinding({
      explicitOptions: agentOptions,
      callerAgent,
    })
    if (!binding.ok && this._requireExplicitModelBinding) {
      this._lastError = 'MISSING_MODEL_BINDING: 无法解析权威 provider/model 绑定，已拒绝启动以防子会话静默跌落至未授权模型。请在主控会话先选定模型，或在 start 时显式传入 provider 与 model。'
      this.telemetry.recordEvent('start_blocked_missing_model_binding', { source: binding.source })
      return {
        started: false,
        alreadyRunning: false,
        blocked: 'MISSING_MODEL_BINDING',
        error: this._lastError,
        status: await this.getControlStatus(),
      }
    }

    // 2. 内核可达性与 Parse 0 签署门禁
    let preSnapRes = null
    try {
      preSnapRes = await this.bridge.control('control_plane/schedule_snapshot', {
        workspace_root: this.workspaceRoot,
        ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
      })
    } catch (err) {
      this._lastError = String(err?.message || err)
      return {
        started: false,
        alreadyRunning: false,
        blocked: 'KERNEL_UNAVAILABLE',
        error: this._lastError,
        status: await this.getControlStatus(),
      }
    }
    if (!preSnapRes?.ok || !preSnapRes?.data) {
      this._lastError = String(preSnapRes?.error || 'schedule_snapshot 返回失败')
      return {
        started: false,
        alreadyRunning: false,
        blocked: 'KERNEL_UNAVAILABLE',
        error: this._lastError,
        status: await this.getControlStatus(),
      }
    }
    if (!preSnapRes.data.parse0_signed) {
      return {
        started: false,
        alreadyRunning: false,
        blocked: 'NEED_PARSE0_SIGNATURE',
        error: '尚未签署 Parse 0 启动契约，请先调用 init（或传入非空 goal_and_completion_md）后再启动事件池。',
        status: await this.getControlStatus(),
      }
    }

    if (Array.isArray(preSnapRes.data.shared_inputs_rel_paths)) {
      this.host.sharedInputPaths = preSnapRes.data.shared_inputs_rel_paths
    }
    if (!this._loopAbortController || this._loopAbortController.signal.aborted) {
      this._loopAbortController = new AbortController()
    }
    this._lastError = null
    this._govCooldownUntil.clear()
    this._itemBreaker.resetAll()
    this._poolState = 'running'
    this._stage3Done = false
    this.telemetry.setOrchestratorState('running')
    this.telemetry.recordEvent('orchestrator_start', {
      maxConcurrentWorkers,
      modelBinding: {
        provider: this._modelBinding?.provider || '',
        model: this._modelBinding?.model || '',
        effectiveContextWindow: this.host.effectiveContextWindow,
      },
    })

    this._backgroundTask = this._runAsyncEventPool({ maxConcurrentWorkers })
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          this._lastError = String(err?.message || err)
          this.telemetry.recordEvent('orchestrator_error', { error: this._lastError })
        }
      })
      .finally(() => {
        if (this._poolState === 'running') {
          this._poolState = 'idle'
          this.telemetry.setOrchestratorState('idle')
        }
        this._backgroundTask = null
      })

    return { started: true, alreadyRunning: false, modelBinding: this._modelBinding, status: await this.getControlStatus() }
  }

  pauseBackground() {
    if (this._poolState !== 'running') return { paused: false, state: this._poolState }
    this._poolState = 'paused'
    this.telemetry.setOrchestratorState('paused')
    this.telemetry.recordEvent('orchestrator_pause')
    this._wakeLoop()
    return { paused: true, state: this._poolState }
  }

  /**
   * 恢复后台事件池：同步检测 `rulings/` 新增或修改的《补充裁决文档》（自动递增 `latest_spec_revision`
   * 供后续新派节点与 0 工具治理视图使用，严禁覆写已在跑旧口径节点的 worktree/inputs/），同时复位所有单待办熔断项。
   */
  async resumeBackground() {
    if (this._poolState !== 'paused') {
      return { resumed: false, state: this._poolState }
    }
    let rulingSync = null
    try {
      const r = await this.bridge.control('control_plane/sync_public_rulings', {
        workspace_root: this.workspaceRoot,
        refresh_active_worktrees: false,
      })
      rulingSync = r?.data || null
    } catch {}
    this._itemBreaker.resetAll()
    this._govCooldownUntil.clear()
    this._poolState = 'running'
    this.telemetry.setOrchestratorState('running')
    this.telemetry.recordEvent('orchestrator_resume', { rulingSync })
    this._wakeLoop()
    return { resumed: true, state: this._poolState, rulingSync }
  }

  /**
   * 确定性精准中止单个失控/旧口径探索节点（替代运行时 steer 广播）：
   * 1. 原子调用 `control_plane/abort_node` 将 SQLite 置为 `CLOSED` 并清空待交接标记；
   * 2. 向在线探索者发 cancel 并销毁对应伴随会话句柄，瞬间释槽且杜绝重派。
   */
  async abortNode(nodeId, reason = 'ABORTED_BY_CONTROLLER') {
    const nid = String(nodeId || '').trim()
    if (!nid) {
      return { aborted: false, error: 'node_id 不能为空' }
    }
    const dbRes = await this.bridge.control('control_plane/abort_node', {
      workspace_root: this.workspaceRoot,
      node_id: nid,
      reason: String(reason || 'ABORTED_BY_CONTROLLER'),
    })
    const running = this._runningExplorers.get(nid)
    if (running) {
      const sessEntry = this.liveSessions.get(running.sessionId)
      try {
        sessEntry?.handle?.agent?.cancel?.({ kind: 'parent' })
      } catch {}
    }
    await disposeNodeCompanion(this, nid, 'aborted')
    this._handoffsSinceHeartbeat += 1
    this.telemetry.recordEvent('node_aborted', { nodeId: nid, reason, dbOk: Boolean(dbRes?.ok) })
    this._wakeLoop()
    return {
      aborted: Boolean(dbRes?.ok),
      nodeId: nid,
      dbResult: dbRes?.data || null,
      error: dbRes?.ok ? null : (dbRes?.error || 'abort_node failed'),
      status: await this.getControlStatus(),
    }
  }

  /**
   * 主控/人类通过控制面正规通道向科研仪器科（works_engineering_queue）签发 OPEN 工单，
   * 复位工单队列冷却并立刻唤醒后台事件池派发 works_engineer 处置。
   */
  async submitWorksTicket({
    questionId = 'ALL',
    ticketType = 'INSTRUMENT_ERROR',
    instrumentId = null,
    description = '',
    source = 'main_controller',
  } = {}) {
    const desc = String(description || '').trim()
    if (!desc) {
      return { submitted: false, error: 'description（工单问题描述）不能为空' }
    }
    const dbRes = await this.bridge.control('control_plane/submit_works_ticket', {
      workspace_root: this.workspaceRoot,
      question_id: String(questionId || 'ALL').trim() || 'ALL',
      ticket_type: String(ticketType || 'INSTRUMENT_ERROR').trim().toUpperCase(),
      instrument_id: instrumentId ? String(instrumentId).trim() : null,
      description: desc,
      source: String(source || 'main_controller'),
    })
    if (dbRes?.ok) {
      this._govCooldownUntil.delete('works:queue')
      this.telemetry.recordEvent('works_ticket_submitted', {
        ticketId: dbRes?.data?.ticket_id || null,
        questionId: dbRes?.data?.question_id || questionId,
        ticketType: dbRes?.data?.ticket_type || ticketType,
        instrumentId: dbRes?.data?.instrument_id || instrumentId,
        source,
      })
      this._wakeLoop()
    }
    return {
      submitted: Boolean(dbRes?.ok),
      ticket: dbRes?.data || null,
      error: dbRes?.ok ? null : (dbRes?.error || 'submit_works_ticket failed'),
      status: await this.getControlStatus(),
    }
  }

  /** 主控显式同步工作区 `rulings/` 补充裁决文档（升版 spec_revision 并可选刷新活跃 Worktree）。 */
  async syncPublicRulings(refreshActiveWorktrees = false) {
    const dbRes = await this.bridge.control('control_plane/sync_public_rulings', {
      workspace_root: this.workspaceRoot,
      refresh_active_worktrees: Boolean(refreshActiveWorktrees),
    })
    if (dbRes?.ok) {
      this.telemetry.recordEvent('public_rulings_synced', {
        changed: Boolean(dbRes?.data?.changed),
        latestSpecRevision: dbRes?.data?.latest_spec_revision ?? null,
      })
      this._wakeLoop()
    }
    return {
      synced: Boolean(dbRes?.ok),
      rulingSync: dbRes?.data || null,
      error: dbRes?.ok ? null : (dbRes?.error || 'sync_public_rulings failed'),
    }
  }

  /**
   * 人类显式叫停唯一真源入口：写入控制面 `human_stop_requested_at` 并停止新探索派单，
   * 使 `PARTIAL_ON_HUMAN_STOP` 终局门禁可合法绕过 `min_commitment_window_sec` 进入 Stage 3 汇总导出。
   */
  async humanStop(note = 'HUMAN_UI_OR_CLI_STOP') {
    const res = await this.bridge.control('control_plane/record_human_stop', {
      workspace_root: this.workspaceRoot,
      note: String(note || 'HUMAN_UI_OR_CLI_STOP'),
    })
    this.telemetry.recordEvent('human_stop_recorded', { note })
    this._wakeLoop()
    return {
      humanStopRecorded: Boolean(res?.ok),
      record: res?.data || null,
      status: await this.getControlStatus(),
    }
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
    for (const nid of [...this._nodeCompanionSessions.keys()]) {
      await disposeNodeCompanion(this, nid, 'aborted')
    }
    const leftovers = [...this.liveSessions.values()]
    if (leftovers.length > 0) {
      await Promise.allSettled(leftovers.map((entry) => entry.handleDispose('aborted', { kind: 'aborted' })))
    }
    return { stopped: true, state: this._poolState }
  }

  async getControlStatus() {
    let snapData = null
    let kernelAlive = false
    let statusError = this._lastError || null
    try {
      const res = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      if (res?.ok && res?.data) {
        snapData = res.data
        kernelAlive = true
      } else {
        statusError = String(res?.error || 'schedule_snapshot 返回失败')
      }
    } catch (err) {
      statusError = String(err?.message || err)
    }
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
      kernelAlive,
      lastError: statusError,
      initialized: snapData ? Boolean(snapData.initialized ?? true) : false,
      stage: snapData?.stage || this.telemetry.state.stage,
      closureStatus: snapData?.closure_state?.status || 'OPEN',
      humanStopActive: Boolean(snapData?.human_stop_active),
      modelBinding: this._modelBinding,
      effectiveContextWindow: this.host.effectiveContextWindow,
      latestSpecRevision: Number(snapData?.latest_spec_revision || 0),
      runningExplorersCount: this._runningExplorers.size,
      runningExplorers: [...this._runningExplorers.values()].map((e) => ({
        nodeId: e.node.node_id,
        questionId: e.node.question_id,
        sessionId: e.sessionId,
      })),
      runningGovernanceTasks: [...this._runningGov.keys()],
      circuitBrokenItems: this._itemBreaker.getBrokenItems(),
      activeSessions: liveList,
      pendingHandoffNodes: (snapData?.pending_handoff_nodes || []).map((n) => n.node_id),
      ambiguousSpecAlerts: snapData?.ambiguous_spec_alerts || [],
      familyConcentrationAlerts: snapData?.family_concentration_alerts || [],
      closureAllowed: Boolean(snapData?.closure_gate?.closure_allowed),
      snapshot: snapData,
      telemetry: this.telemetry.getSummary(),
    }
  }

  _launchGovTask(taskKey, runner) {
    if (this._runningGov.has(taskKey)) return false
    const cooldownUntil = this._govCooldownUntil.get(taskKey) || 0
    if (cooldownUntil > Date.now()) return false
    let failed = false
    const p = Promise.resolve()
      .then(runner)
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          failed = true
          this._govCooldownUntil.set(taskKey, Date.now() + 3000)
          this.telemetry.recordEvent('gov_task_error', { taskKey, error: String(err?.message || err) })
        }
      })
      .finally(() => {
        this._runningGov.delete(taskKey)
        this._syncSlotsToTelemetry()
        if (!failed) {
          this._govCooldownUntil.delete(taskKey)
          this._wakeLoop()
        }
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

  /** 拉取最新快照并对刚刚执行完毕的一批单待办项结算无进展熔断计数。 */
  async _evaluateBreakerAfterTask(roleLabel, dispatchedItems, extractAfterMap) {
    if (!dispatchedItems?.length) return
    try {
      const postRes = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      if (!postRes?.ok || !postRes?.data) return
      const afterMap = extractAfterMap(postRes.data)
      const evals = this._itemBreaker.evaluateBatch(dispatchedItems, afterMap)
      for (const ev of evals) {
        if (ev.newlyBroken) {
          this.telemetry.recordEvent('governance_item_circuit_broken', {
            role: roleLabel,
            itemKey: ev.key,
            stalledCount: ev.stalledCount,
          })
        }
      }
    } catch {}
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

  async _runBlindReviewWithSandbox(rev, sig) {
    const reviewId = String(rev.review_id)
    const staged = await this.bridge.control('control_plane/stage_blind_sandbox', {
      workspace_root: this.workspaceRoot,
      review_id: reviewId,
    })
    const sandboxPath = staged?.data?.sandbox_abs_path || ''
    const uniqueVerifierSid = `gw_ver_${reviewId}_${crypto.randomUUID().slice(0, 6)}`
    try {
      await this.spawnAndRunAgent({
        role: 'library_verifier',
        sessionId: uniqueVerifierSid,
        questionId: rev.question_id,
        sandboxAbsPath: sandboxPath,
        uiLabel: `[图书馆盲审] ${rev.question_id || ''} ${reviewId}`.trim(),
        shortTransaction: true,
        signal: sig,
        taskContextText: sandboxPath
          ? `### 独立空白盲审沙箱目录\n- sandbox_abs_path: \`${sandboxPath}\`\n（沙箱内已只读挂载手稿绑定口径的 inputs/ 公开题面、A 栏与脱敏复核材料；物理断网且不可访问 DB/工作树/B 栏）`
          : '',
        prompt: rev.review_status === 'STAGE1_BLIND'
          ? `请以异会话执行盲审单 ${reviewId} (${rev.question_id})：先调 get_blind_manuscript 审阅脱敏 A 栏与沙箱复核工件（严格按手稿绑定 spec_revision 评判科学真伪），在空白沙箱内独立验算后调 submit_stage1_blind_ledger 锁定不可逆账本；若 Stage 1 判 PASS，紧接着调 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成终判（判 REVISE/REFUTED 时立即结束）。`
          : `请对审稿单 ${reviewId} (${rev.question_id}) 调用 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成 Stage 2 终审。`,
      })
    } finally {
      await this.bridge
        .control('control_plane/cleanup_blind_sandbox', {
          workspace_root: this.workspaceRoot,
          review_id: reviewId,
        })
        .catch(() => {})
    }
  }

  async _runAsyncEventPool({ maxConcurrentWorkers = null } = {}) {
    const sig = this._loopAbortController.signal
    let idleStreak = 0
    let snapshotErrorStreak = 0

    // 启动恢复：按原冻结快照续跑上次进程中断遗留的 heavy 异步评测作业
    try {
      const rec = await this.bridge.control('control_plane/recover_heavy_jobs', { workspace_root: this.workspaceRoot })
      if (rec?.data?.recovered_jobs?.length > 0) {
        this.telemetry.recordEvent('heavy_jobs_recovered', { count: rec.data.recovered_jobs.length })
      }
    } catch {}

    while (!sig.aborted && this._poolState !== 'stopped') {
      if (this._poolState === 'paused') {
        await this._waitWakeOrTimeout(400)
        continue
      }

      const snapRes = await this.bridge.control('control_plane/schedule_snapshot', {
        workspace_root: this.workspaceRoot,
        max_concurrent_workers: maxConcurrentWorkers,
      })
      if (!snapRes?.ok || !snapRes?.data) {
        snapshotErrorStreak += 1
        const errMsg = String(snapRes?.error || 'schedule_snapshot 返回空响应或失败回执')
        this.telemetry.recordEvent('orchestrator_snapshot_error', {
          streak: snapshotErrorStreak,
          error: errMsg,
        })
        if (snapshotErrorStreak >= 3) {
          this._lastError = errMsg
          this._poolState = 'error'
          this.telemetry.setOrchestratorState('error', this.telemetry.state.stage || 'ERROR')
          break
        }
        await this._waitWakeOrTimeout(250)
        continue
      }
      snapshotErrorStreak = 0

      const snap = snapRes.data
      if (Array.isArray(snap.shared_inputs_rel_paths)) {
        this.host.sharedInputPaths = snap.shared_inputs_rel_paths
      }
      const closureSt = snap?.closure_state?.status || 'OPEN'
      if (snap.stage === 'CLOSED_VERIFIED' || closureSt === 'CLOSED_VERIFIED' || this._stage3Done) {
        this.telemetry.setOrchestratorState('idle', 'CLOSED_VERIFIED')
        break
      }
      this._syncSlotsToTelemetry(snap.stage)

      // 红灯口径歧义告警：记入遥测留待人类核查，绝不停摆继续推进原已签口径
      for (const al of snap.ambiguous_spec_alerts || []) {
        if (al?.alert_id && !this._seenAmbiguousAlertIds.has(al.alert_id)) {
          this._seenAmbiguousAlertIds.add(al.alert_id)
          this.telemetry.recordEvent('alert_ambiguous_spec_red_light', {
            alertId: al.alert_id,
            notes: al.notes,
            policy: 'CONTINUE_BASELINE_WITH_RED_ALERT',
          })
        }
      }

      // 0. 待交接/崩溃抢救恢复
      let dispatchedSomething = dispatchPendingHandoffRecoveries(this, snap, sig)

      // 1. Stage 1 (Parse 0) 初始化四步
      const s1 = await dispatchStage1Step(this, snap, sig)
      if (s1.handled) {
        if (s1.waitMs) await this._waitWakeOrTimeout(s1.waitMs)
        continue
      }

      // 2. Stage 3 两步联合终核与退修闭环
      const s3 = dispatchStage3Step(this, snap, sig)
      if (s3.handled) {
        await this._waitWakeOrTimeout(s3.waitMs || 250)
        continue
      }

      // 3. Stage 2 治理与并发探索派发
      const s2 = await dispatchStage2Step(this, snap, sig, maxConcurrentWorkers)
      if (s2.dispatched) dispatchedSomething = true
      if (s2.continueImmediate) continue

      const hasCoolingGov = [...this._govCooldownUntil.values()].some((until) => until > Date.now())
      if (!dispatchedSomething && this._runningExplorers.size === 0 && this._runningGov.size === 0 && !hasCoolingGov) {
        idleStreak += 1
        if (idleStreak >= 3) break
      } else {
        idleStreak = 0
      }

      await this._waitWakeOrTimeout(250)
    }
  }

  async runUntilClosed({ signal = null, maxCycles = 25, maxConcurrentWorkers = null, agentOptions = {}, callerAgent = null } = {}) {
    void maxCycles
    const binding = await this._resolveAndLockModelBinding({ explicitOptions: agentOptions, callerAgent })
    if (!binding.ok && this._requireExplicitModelBinding) {
      const err = new Error('MISSING_MODEL_BINDING: 无法解析权威 provider/model 绑定，已拒绝启动')
      err.code = 'MISSING_MODEL_BINDING'
      throw err
    }

    this._loopAbortController = new AbortController()
    const onExtAbort = () => this._loopAbortController.abort(new Error('EXTERNAL_SIGNAL_ABORTED'))
    if (signal) {
      if (signal.aborted) onExtAbort()
      else signal.addEventListener('abort', onExtAbort, { once: true })
    }
    this._poolState = 'running'
    this._stage3Done = false
    this._itemBreaker.resetAll()
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
    const closed = finalSnap?.data?.stage === 'CLOSED_VERIFIED' || finalSnap?.data?.closure_state?.status === 'CLOSED_VERIFIED' || this._stage3Done
    return {
      closed,
      aborted,
      modelBinding: this._modelBinding,
      circuitBrokenItems: this._itemBreaker.getBrokenItems(),
      snapshot: finalSnap?.data,
    }
  }

  async disposeAll() {
    await this.stopBackground('DISPOSE_ALL')
    await this.host.disposeAllSessions()
  }
}
