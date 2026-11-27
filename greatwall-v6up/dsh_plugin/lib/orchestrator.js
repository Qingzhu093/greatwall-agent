/**
 * GreatWall v0.3 异步事件池编排器主入口（精简高内聚，零上帝文件）。
 *
 * v0.3 架构集成：
 * - `WorkspaceInstanceLock`：单机单实例 `host.lock` 防双活抢单；
 * - `RuntimeEffectsConsumer`：每轮先消费 SQLite Outbox（60s 租约、崩溃认领、热注入 `NOTIFY_POLICY_CHANGED`、45% 让权与 `NOTIFY_CHIEF` 路由）；
 * - `WorkerSlotAllocator`：`maxWorkers` 普通槽 + `+1` 人类优先保留槽；
 * - `HumanTakeoverCoordinator`：45% 暂停让权 + `ctx.jobs` 清理 + `source.rpcId` 人类对话让权；
 * - `WaveConferenceRunner`：宏观大外环四拍脉冲确定性驱动；
 * - 废除 `resume` 扫盘自动升版暗门（改为只读草稿提示，裁决 4）。
 * @module dsh-greatwall-v6up/orchestrator
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { loadCoreRuntimeConfig, loadRolePrompts } from './prompts.js'
import { TelemetryCollector, resolveTelemetryFilePath } from './telemetry.js'
import { AgentSessionHost, resolveAuthoritativeModelBinding } from './agent_session_host.js'
import { disposeNodeCompanion, driveExplorerCompanionPair } from './pair_lifecycle.js'
import { WorkspaceInstanceLock } from './runtime/instance_lock.js'
import { WorkerSlotAllocator } from './runtime/worker_slots.js'
import { RuntimeEffectsConsumer } from './runtime/effects_consumer.js'
import { HumanTakeoverCoordinator } from './sessions/human_takeover.js'
import { GovernanceItemCircuitBreaker, selectDispatchableExplorers } from './orchestrator/circuit_breaker.js'
import { assertValidBlindSandboxResult, buildDispatchRuntimePort } from './orchestrator/runtime_port.js'
import { WaveConferenceRunner } from './orchestrator/wave_conference_runner.js'
import { dispatchStage1Step } from './orchestrator/dispatch_stage1.js'
import { dispatchPendingHandoffRecoveries, dispatchStage2Step } from './orchestrator/dispatch_stage2.js'
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
    onChiefNotify = null,
  }) {
    this.ctx = ctx
    this.bridge = bridge
    this.corePythonRoot = path.resolve(corePythonRoot)
    this.workspaceRoot = path.resolve(workspaceRoot)
    this.dataDir = dataDir
    this.parentAgent = parentAgent
    this._onChiefNotify = onChiefNotify

    this.runtimeConfig = loadCoreRuntimeConfig(this.corePythonRoot)
    this.rolePrompts = loadRolePrompts(this.corePythonRoot)
    this.telemetry = new TelemetryCollector({ workspaceRoot: this.workspaceRoot, dataDir })

    const clkCfg = this.runtimeConfig?.session_context_clock || {}
    const orchCfg = this.runtimeConfig?.orchestration_and_eval || {}
    this._windowCapTokens = Number(clkCfg.context_window_cap_tokens || clkCfg.context_window_tokens || 500_000)
    this._requireExplicitModelBinding = orchCfg.require_explicit_model_binding !== false
    this._itemBreaker = new GovernanceItemCircuitBreaker(Number(orchCfg.governance_item_circuit_breaker_max_stalled_runs || 2))

    const wsDataRoot = path.dirname(resolveTelemetryFilePath({ dataDir, workspaceRoot: this.workspaceRoot }))
    this.instanceLock = new WorkspaceInstanceLock(path.join(wsDataRoot, 'host.lock'))
    this.slotAllocator = new WorkerSlotAllocator(Number(orchCfg.default_max_concurrent_workers || 4), 1)
    this.humanTakeover = new HumanTakeoverCoordinator({
      ctx,
      bridge,
      workspaceRoot: this.workspaceRoot,
      telemetry: this.telemetry,
    })

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
      humanTakeover: this.humanTakeover,
      telemetry: this.telemetry,
    })

    this.effectsConsumer = new RuntimeEffectsConsumer({
      bridge,
      workspaceRoot: this.workspaceRoot,
      ownerInstanceId: this.instanceLock.ownerId,
      telemetry: this.telemetry,
      handlers: this._buildEffectHandlers(),
    })

    this._modelBinding = null
    this._poolState = 'idle'
    this._loopAbortController = null
    this._backgroundTask = null
    this._wakeResolvers = new Set()
    this._lastError = null
    this._runningExplorers = new Map()
    this._runningGov = new Map()
    this._govCooldownUntil = new Map()
    this._explorerCooldownUntil = new Map()
    this._nodeCompanionSessions = new Map()
    this._seenAmbiguousAlertIds = new Set()
    this._stage3Done = false
  }

  _buildEffectHandlers() {
    return {
      DRAIN_AND_STOP_NODE: async (eff, payload) => {
        const nid = String(eff.target_id || '')
        const running = this._runningExplorers.get(nid)
        const sid = running?.sessionId || `gw-exp-${nid}`
        const liveEntry = this.liveSessions.get(sid)
        await this.humanTakeover.drainAndYieldNode({
          nodeId: nid,
          sessionId: sid,
          liveHandle: liveEntry?.handle || null,
          livePromise: running?.promise || null,
          graceSec: Number(payload?.grace_sec || 0),
          keepSessionForHuman: Boolean(payload?.keep_session_for_human),
          reason: String(payload?.reason || 'DRAIN_AND_STOP_NODE'),
        })
      },
      CANCEL_NODE_SESSION: async (eff, payload) => {
        const nid = String(eff.target_id || '')
        const running = this._runningExplorers.get(nid)
        const sid = running?.sessionId || `gw-exp-${nid}`
        const liveEntry = this.liveSessions.get(sid)
        await this.humanTakeover.drainAndYieldNode({
          nodeId: nid,
          sessionId: sid,
          liveHandle: liveEntry?.handle || null,
          keepSessionForHuman: false,
          reason: String(payload?.reason || 'CANCEL_NODE_SESSION'),
        })
      },
      NOTIFY_POLICY_CHANGED: async (eff, payload) => {
        const nid = String(eff.target_id || '')
        const running = this._runningExplorers.get(nid)
        if (!running) return
        const notice = `[新公开裁决口径 v${payload?.new_spec_revision || '?'}] 人类已修订子题 ${payload?.question_id || ''} 口径：${payload?.summary_md || ''}（详见 ${payload?.ruling_file || 'rulings/'}）。你当前在途思路仍可自然收尾，但若需达最新 FULL_GOAL 请对齐新口径。`
        this.host.injectPolicyChange(running.sessionId, notice)
      },
      NOTIFY_CHIEF: async (eff, payload) => {
        this.telemetry.recordEvent('chief_notification_received', { seq: eff.seq, targetId: eff.target_id, payload })
        if (typeof this._onChiefNotify === 'function') {
          await this._onChiefNotify({ seq: eff.seq, targetType: eff.target_type, targetId: eff.target_id, payload })
        }
      },
      WAKE_BLOCKED_BRANCH: async () => { this._wakeLoop() },
      SPAWN_PAIR: async () => { this._wakeLoop() },
      RUN_WAVE_CONFERENCE: async () => { this._wakeLoop() },
      REFRESH_LIVING_SURVEY: async () => { this._wakeLoop() },
    }
  }

  get liveSessions() { return this.host.liveSessions }
  get poolState() { return this._poolState }
  getPoolState() { return this._poolState }
  isPoolStopped() { return this._poolState === 'stopped' }
  isPoolPaused() { return this._poolState === 'paused' }
  hasBackgroundTask() { return Boolean(this._backgroundTask) }
  getEffectiveContextWindow() { return this.host.effectiveContextWindow }
  isExplorerRunning(nodeId) { return this._runningExplorers.has(nodeId) }
  getRunningExplorerCount() { return this._runningExplorers.size }
  getRunningExplorerIds() { return new Set(this._runningExplorers.keys()) }
  isGovTaskRunning(taskKey) { return this._runningGov.has(taskKey) }
  isBreakerOpen(key, fp) { return this._itemBreaker.isBroken(key, fp) }
  launchGovTask(taskKey, runner) { return this._launchGovTask(taskKey, runner) }
  launchGovTaskAndAwait(taskKey, runner) { return this._launchGovTaskAndAwaitIfSync(taskKey, runner) }
  evaluateBreakerAfterTask(roleLabel, items, extractAfterMap) { return this._evaluateBreakerAfterTask(roleLabel, items, extractAfterMap) }
  launchExplorer(node, snap, sig) { return this._launchExplorerWorker(node, snap, sig) }
  runBlindReview(rev, sig) { return this._runBlindReviewWithSandbox(rev, sig) }
  advanceWaveConference(conf, sig) { return new WaveConferenceRunner(this.createDispatchRuntimePort()).advanceConference(conf, sig) }
  setSessionReadonly(sid, flag) { this.host?.setSessionReadonly?.(sid, flag) }
  archiveSession(sid) { return this.host?.archiveSession?.(sid) }
  control(method, params = {}, opts = {}) { return this.bridge.control(method, params, opts) }
  recordEvent(eventName, detail = {}) { this.telemetry?.recordEvent?.(eventName, detail) }
  createDispatchRuntimePort() { return buildDispatchRuntimePort(this) }
  set defaultAgentOptions(val) { this.host.defaultAgentOptions = val }
  get defaultAgentOptions() { return this.host.defaultAgentOptions }
  spawnAndRunAgent(opts) { return this.host.spawnAndRunAgent(opts) }
  resumeOrSpawnAgent(opts) { return this.host.resumeOrSpawnAgent(opts) }
  continueAliveAgent(sid, promptText, opts) { return this.host.continueAliveAgent(sid, promptText, opts) }
  assertValidBlindSandbox(staged, reviewId) { return assertValidBlindSandboxResult(staged, reviewId, this.workspaceRoot, this.telemetry) }

  setChiefNotifyHandler(fn) {
    this._onChiefNotify = typeof fn === 'function' ? fn : null
  }

  getAvailableBriefSlots(snap, maxConcurrentWorkers = null) {
    const effCap = Math.max(1, Number(maxConcurrentWorkers || snap?.slot_cap || this.slotAllocator.maxWorkers))
    const runningBriefings = [...this._runningGov.keys()].filter((k) => k.startsWith('brief:')).length
    const readyWaitingCount = (snap?.explorers_ready_to_run || []).filter((n) => !this._runningExplorers.has(n.node_id)).length
    return Math.max(0, effCap + 1 - this._runningExplorers.size - runningBriefings - readyWaitingCount)
  }

  getLiveCompanion(nodeId) {
    if (!nodeId) return null
    const handle = this._nodeCompanionSessions.get(nodeId)
    if (!handle || !this.liveSessions?.has?.(handle.sessionId)) {
      this._nodeCompanionSessions.delete(nodeId)
      return null
    }
    return handle
  }

  setLiveCompanion(nodeId, handle) {
    if (nodeId && handle) this._nodeCompanionSessions.set(nodeId, handle)
  }

  async disposeCompanion(nodeId, status = 'completed') {
    if (!nodeId) return
    const handle = this._nodeCompanionSessions.get(nodeId)
    this._nodeCompanionSessions.delete(nodeId)
    if (handle && typeof handle.dispose === 'function') {
      try { await handle.dispose(status) } catch {}
    }
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

  async _resolveAndLockModelBinding({ explicitOptions = {}, callerAgent = null } = {}) {
    const fallbackSessionIds = Object.values(this.telemetry?.state?.sessions || {})
      .filter((s) => s?.sessionId)
      .sort((a, b) => String(b.startedAt || '').localeCompare(String(a.startedAt || '')))
      .map((s) => String(s.sessionId))
    const binding = await resolveAuthoritativeModelBinding({
      explicitOptions,
      callerAgent: callerAgent || this.parentAgent,
      ctx: this.ctx,
      configDefaultOptions: this.defaultAgentOptions,
      persistedBinding: this.telemetry?.state?.lastModelBinding || null,
      fallbackSessionIds,
      runtimeDefaultWindow: this._windowCapTokens,
    })
    if (!binding.ok && this._requireExplicitModelBinding) return binding
    if (binding.ok) {
      this.defaultAgentOptions = { ...this.defaultAgentOptions, provider: binding.provider, model: binding.model }
      this.telemetry.setModelBinding(binding)
    }
    this.host.effectiveContextWindow = binding.effectiveContextWindow || this._windowCapTokens
    this._modelBinding = binding
    this.telemetry.recordEvent('model_binding_locked', {
      provider: binding.provider || '(none)',
      model: binding.model || '(none)',
      effectiveContextWindow: this.host.effectiveContextWindow,
      source: binding.source,
    })
    return binding
  }

  async startBackground({ maxConcurrentWorkers = null, agentOptions = {}, callerAgent = null } = {}) {
    if (callerAgent) {
      this.parentAgent = callerAgent
      this.host.parentAgent = callerAgent
    }
    if (this._startingPromise) {
      return this._startingPromise
    }
    if (this._backgroundTask) {
      if (this._poolState === 'paused') {
        await this.resumeBackground()
        return { started: true, alreadyRunning: true, resumed: true, status: await this.getControlStatus() }
      }
      if (this._poolState === 'running') {
        return { started: true, alreadyRunning: true, status: await this.getControlStatus() }
      }
    }

    const startSeq = (this._startSeq = (this._startSeq || 0) + 1)
    const isStartCancelled = () => this._poolState === 'stopped' || this._startSeq !== startSeq

    const runStart = async () => {
      const lockRes = this.instanceLock.acquire()
      if (!lockRes.ok) {
        this._lastError = lockRes.error
        return { started: false, alreadyRunning: false, blocked: 'INSTANCE_LOCKED', error: lockRes.error, status: await this.getControlStatus() }
      }
      this._poolState = 'starting'

      const binding = await this._resolveAndLockModelBinding({ explicitOptions: agentOptions, callerAgent })
      if (isStartCancelled()) {
        this.instanceLock.release()
        return { started: false, alreadyRunning: false, blocked: 'STOPPED_DURING_START', status: await this.getControlStatus() }
      }
      if (!binding.ok && this._requireExplicitModelBinding) {
        this.instanceLock.release()
        this._poolState = 'idle'
        this._lastError = 'MISSING_MODEL_BINDING: 无法解析权威 provider/model 绑定，已拒绝启动。'
        return { started: false, alreadyRunning: false, blocked: 'MISSING_MODEL_BINDING', error: this._lastError, status: await this.getControlStatus() }
      }

      let preSnapRes = null
      try {
        preSnapRes = await this.bridge.control('control_plane/schedule_snapshot', {
          workspace_root: this.workspaceRoot,
          ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
        })
      } catch (err) {
        this.instanceLock.release()
        if (!isStartCancelled()) this._poolState = 'idle'
        this._lastError = String(err?.message || err)
        return { started: false, alreadyRunning: false, blocked: 'KERNEL_UNAVAILABLE', error: this._lastError, status: await this.getControlStatus() }
      }
      if (isStartCancelled()) {
        this.instanceLock.release()
        return { started: false, alreadyRunning: false, blocked: 'STOPPED_DURING_START', status: await this.getControlStatus() }
      }
      if (!preSnapRes?.ok || !preSnapRes?.data) {
        this.instanceLock.release()
        this._poolState = 'idle'
        this._lastError = String(preSnapRes?.error || 'schedule_snapshot 返回失败')
        return { started: false, alreadyRunning: false, blocked: 'KERNEL_UNAVAILABLE', error: this._lastError, status: await this.getControlStatus() }
      }
      if (!preSnapRes.data.parse0_signed) {
        this.instanceLock.release()
        this._poolState = 'idle'
        return { started: false, alreadyRunning: false, blocked: 'NEED_PARSE0_SIGNATURE', error: '尚未签署 Parse 0 启动契约。', status: await this.getControlStatus() }
      }

      if (maxConcurrentWorkers) this.slotAllocator.setMaxWorkers(maxConcurrentWorkers)
      if (Array.isArray(preSnapRes.data.shared_inputs_rel_paths)) this.host.sharedInputPaths = preSnapRes.data.shared_inputs_rel_paths
      if (!this._loopAbortController || this._loopAbortController.signal.aborted) this._loopAbortController = new AbortController()
      this._lastError = null
      this._govCooldownUntil.clear()
      this._itemBreaker.resetAll()
      this._poolState = 'running'
      this._stage3Done = false
      this.telemetry.setOrchestratorState('running')

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
          this.instanceLock.release()
          this._backgroundTask = null
        })

      return { started: true, alreadyRunning: false, modelBinding: this._modelBinding, status: await this.getControlStatus() }
    }

    this._startingPromise = runStart().finally(() => {
      this._startingPromise = null
    })
    return this._startingPromise
  }

  async _resumeAllHumanPausedNodes(note = 'GLOBAL_RESUME_FULL_AUTOPILOT') {
    const resumedNodeIds = []
    try {
      const snapRes = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      const pausedNodes = Array.isArray(snapRes?.data?.human_paused_nodes) ? snapRes.data.human_paused_nodes : []
      for (const n of pausedNodes) {
        const nid = String(n?.node_id || '').trim()
        if (!nid) continue
        const r = await this.bridge.control('control_plane/resume_node', {
          workspace_root: this.workspaceRoot,
          node_id: nid,
          actor_source: 'human_ui',
          cross_branch_note: note,
        }).catch(() => null)
        if (r?.ok) resumedNodeIds.push(nid)
      }
    } catch {}
    return resumedNodeIds
  }

  async pauseBackground() {
    if (this._poolState !== 'running') {
      return { paused: false, state: this._poolState, pausedNodeIds: [], error: `当前处于 ${this._poolState} 状态，无需暂停` }
    }
    this._poolState = 'paused'
    this.telemetry.setOrchestratorState('paused')

    // 统一状态机：全局暂停 = 将所有在跑及排队中的活跃探索节点同步切入「等待人类接管 (PAUSE_DRAINING -> HUMAN_ACTIVE)」
    const targetIds = new Set()
    for (const running of this._runningExplorers.values()) {
      const nid = String(running?.node?.node_id || '').trim()
      if (nid) targetIds.add(nid)
    }
    try {
      const snapRes = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      for (const n of snapRes?.data?.dispatchable_explorers || []) {
        const nid = String(n?.node_id || '').trim()
        if (nid) targetIds.add(nid)
      }
    } catch {}

    const pausedNodeIds = []
    for (const nid of targetIds) {
      try {
        const res = await this.bridge.control('control_plane/pause_node', {
          workspace_root: this.workspaceRoot,
          node_id: nid,
          actor_source: 'human_ui',
          reason: 'GLOBAL_PAUSE_HUMAN_TAKEOVER',
        })
        if (res?.ok) {
          pausedNodeIds.push(nid)
          if (!this._runningExplorers.has(nid)) {
            await this.bridge.control('control_plane/mark_node_yielded', {
              workspace_root: this.workspaceRoot,
              node_id: nid,
              yield_reason: 'GLOBAL_PAUSE_QUEUED_NODE',
            }).catch(() => {})
          }
        }
      } catch {}
    }
    this._wakeLoop()
    return { paused: true, state: this._poolState, pausedNodeIds }
  }

  async resumeBackground() {
    // 若处于 idle / stopped（如重启后从历史工作区恢复），先对所有暂停接管态节点做 SHA 对账，再拉起后台编排器进入全面托管
    if (this._poolState === 'idle' || this._poolState === 'stopped') {
      const resumedNodeIds = await this._resumeAllHumanPausedNodes('GLOBAL_COLD_RESUME_FULL_AUTOPILOT')
      const st = await this.startBackground()
      if (st?.started) {
        return { resumed: true, restarted: true, state: this._poolState, resumedNodeIds, ...st }
      }
      return {
        resumed: false,
        state: this._poolState,
        resumedNodeIds,
        error: st?.error || `当前处于 ${this._poolState} 状态，无法启动全面托管`,
      }
    }
    if (this._poolState !== 'paused') {
      return { resumed: false, state: this._poolState, resumedNodeIds: [], error: `当前处于 ${this._poolState} 状态，无需恢复` }
    }

    // 统一状态机：全局恢复全面托管前，对所有暂停接管态节点统一执行 resume_node（自动完成 Worktree SHA 对账）
    const resumedNodeIds = await this._resumeAllHumanPausedNodes('GLOBAL_RESUME_FULL_AUTOPILOT')

    // 裁决 4：彻底废除扫盘自动静默升版暗门，仅只读检测是否有未审批磁盘草稿
    let draftNotice = null
    try {
      const r = await this.bridge.control('control_plane/inspect_rulings_draft', { workspace_root: this.workspaceRoot })
      draftNotice = r?.data || null
    } catch {}
    this._itemBreaker.resetAll()
    this._govCooldownUntil.clear()
    this._explorerCooldownUntil.clear()
    this._poolState = 'running'
    this.telemetry.setOrchestratorState('running')
    this._wakeLoop()
    return { resumed: true, state: this._poolState, resumedNodeIds, draftNotice }
  }

  async abortNode(nodeId, reason = 'ABORTED_BY_CONTROLLER') {
    const nid = String(nodeId || '').trim()
    if (!nid) return { aborted: false, error: 'node_id 不能为空' }
    const dbRes = await this.bridge.control('control_plane/abort_node', {
      workspace_root: this.workspaceRoot,
      node_id: nid,
      reason: String(reason || 'ABORTED_BY_CONTROLLER'),
    })
    const running = this._runningExplorers.get(nid)
    if (running) {
      try { this.liveSessions.get(running.sessionId)?.handle?.agent?.cancel?.({ kind: 'parent' }) } catch {}
    }
    await disposeNodeCompanion(this, nid, 'aborted')
    this._wakeLoop()
    return { aborted: Boolean(dbRes?.ok), nodeId: nid, dbResult: dbRes?.data || null, error: dbRes?.ok ? null : dbRes?.error, status: await this.getControlStatus() }
  }

  async submitWorksTicket({ questionId = 'ALL', ticketType = 'INSTRUMENT_ERROR', instrumentId = null, description = '', source = 'main_controller' } = {}) {
    const desc = String(description || '').trim()
    if (!desc) return { submitted: false, error: 'description 不能为空' }
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
      this._wakeLoop()
    }
    return { submitted: Boolean(dbRes?.ok), ticket: dbRes?.data || null, error: dbRes?.ok ? null : dbRes?.error, status: await this.getControlStatus() }
  }

  async syncPublicRulings(refreshActiveWorktrees = false) {
    const dbRes = await this.bridge.control('control_plane/sync_public_rulings', {
      workspace_root: this.workspaceRoot,
      refresh_active_worktrees: Boolean(refreshActiveWorktrees),
    })
    return { synced: Boolean(dbRes?.ok), rulingSync: dbRes?.data || null, error: dbRes?.ok ? null : dbRes?.error }
  }

  async wakeOrRestartIfIdle() {
    if (this._poolState === 'running' && this._backgroundTask) {
      this._wakeLoop()
      return { woken: true, restarted: false }
    }
    if (this._poolState === 'idle' && !this._backgroundTask && (this._modelBinding?.ok || !this._requireExplicitModelBinding)) {
      const res = await this.startBackground()
      return { woken: true, restarted: Boolean(res?.started) }
    }
    return { woken: false, restarted: false }
  }

  async humanStop(note = 'HUMAN_UI_OR_CLI_STOP', { callerSource = 'unknown' } = {}) {
    const res = await this.bridge.control('control_plane/record_human_stop', {
      workspace_root: this.workspaceRoot,
      note: String(note || 'HUMAN_UI_OR_CLI_STOP'),
    })
    this.telemetry.recordEvent('human_stop_recorded', { note, callerSource })
    for (const running of this._runningExplorers.values()) {
      const liveEntry = this.liveSessions.get(running.sessionId)
      try { liveEntry?.handle?.agent?.cancel?.({ kind: 'hook', reason: 'HUMAN_STOP' }) } catch {}
    }
    // 人类收工后必须确保事件池处于 running 态以驱动 Stage 3 冻结包导出与盲审终签（新探索派发已由 DB human_stop_active 硬拦截）
    if (res?.ok) {
      if (this._poolState === 'paused') {
        this._poolState = 'running'
        this.telemetry.setOrchestratorState('running')
      } else if ((this._poolState === 'idle' || this._poolState === 'stopped') && !this._backgroundTask) {
        await this.startBackground().catch(() => {})
      }
    }
    this._wakeLoop()
    return { humanStopRecorded: Boolean(res?.ok), callerSource, record: res?.data || null, status: await this.getControlStatus() }
  }

  async stopBackground(reason = 'USER_STOPPED') {
    this._startSeq = (this._startSeq || 0) + 1
    this._poolState = 'stopped'
    this.telemetry.setOrchestratorState('stopped')
    if (this._loopAbortController) {
      try { this._loopAbortController.abort(new Error(reason)) } catch {}
    }
    for (const entry of this.liveSessions.values()) {
      try { entry.handle?.agent?.cancel?.({ kind: 'parent' }) } catch {}
    }
    this._wakeLoop()
    if (this._backgroundTask) {
      await Promise.race([this._backgroundTask.catch(() => {}), new Promise((r) => setTimeout(r, 2500))])
    }
    for (const nid of [...this._nodeCompanionSessions.keys()]) await disposeNodeCompanion(this, nid, 'aborted')
    const leftovers = [...this.liveSessions.values()]
    if (leftovers.length > 0) {
      await Promise.allSettled(leftovers.map((entry) => entry.handleDispose('aborted', { kind: 'aborted' })))
    }
    this.instanceLock.release()
    return { stopped: true, state: this._poolState }
  }

  async getControlStatus() {
    let snapData = null
    let kernelAlive = false
    let statusError = this._lastError || null
    try {
      const res = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      if (res?.ok && res?.data) { snapData = res.data; kernelAlive = true }
      else statusError = String(res?.error || 'schedule_snapshot 返回失败')
    } catch (err) { statusError = String(err?.message || err) }

    return {
      poolState: this._poolState,
      state: this._poolState,
      kernelAlive,
      lastError: statusError,
      initialized: snapData ? Boolean(snapData.initialized ?? true) : false,
      stage: snapData?.stage || this.telemetry.state.stage,
      autonomyMode: snapData?.autonomy_mode || 'WAVE_CONFIRM',
      closureStatus: snapData?.closure_state?.status || 'OPEN',
      humanStopActive: Boolean(snapData?.human_stop_active),
      slotAllocation: this.slotAllocator.snapshot(),
      modelBinding: this._modelBinding,
      effectiveContextWindow: this.host.effectiveContextWindow,
      latestSpecRevision: Number(snapData?.latest_spec_revision || 0),
      runningExplorersCount: this._runningExplorers.size,
      runningExplorers: [...this._runningExplorers.values()].map((e) => ({ nodeId: e.node.node_id, questionId: e.node.question_id, sessionId: e.sessionId, startedAt: e.startedAt || null })),
      runningGovernanceTasks: [...this._runningGov.keys()],
      circuitBrokenItems: this._itemBreaker.getBrokenItems(),
      activeSessions: [...this.liveSessions.entries()].map(([sid, s]) => ({ sessionId: sid, role: s.role, questionId: s.questionId, nodeId: s.nodeId, label: s.uiLabel, startedAt: s.startedAt })),
      pendingHandoffNodes: (snapData?.pending_handoff_nodes || []).map((n) => n.node_id),
      pendingProposalsCount: (snapData?.pending_proposals || []).length,
      subproblemStates: Array.isArray(snapData?.subproblem_runtime_state)
        ? snapData.subproblem_runtime_state
        : Object.values(snapData?.subproblem_states || {}),
      closureAllowed: Boolean(snapData?.closure_gate?.closure_allowed),
      snapshot: snapData,
      telemetry: this.telemetry.getSummary(),
    }
  }

  _launchGovTask(taskKey, runner) {
    if (this._runningGov.has(taskKey)) return false
    if ((this._govCooldownUntil.get(taskKey) || 0) > Date.now()) return false
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

  async _evaluateBreakerAfterTask(roleLabel, dispatchedItems, extractAfterMap) {
    if (!dispatchedItems?.length) return []
    try {
      const postRes = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
      if (!postRes?.ok || !postRes?.data) return []
      const evals = this._itemBreaker.evaluateBatch(dispatchedItems, extractAfterMap(postRes.data))
      for (const ev of evals) {
        if (ev.newlyBroken) this.telemetry.recordEvent('governance_item_circuit_broken', { role: roleLabel, itemKey: ev.key, stalledCount: ev.stalledCount })
      }
      return evals
    } catch {
      return []
    }
  }

  _syncSlotsToTelemetry(stage = '') {
    this.telemetry.updateActiveSlots({
      stage,
      activeExplorers: [...this._runningExplorers.values()].map((e) => ({ nodeId: e.node.node_id, questionId: e.node.question_id, sessionId: e.sessionId })),
      activeGovernance: [...this._runningGov.keys()],
    })
  }

  _launchExplorerWorker(node, snap, sig) {
    const nid = String(node?.node_id || '')
    if (!nid) return
    if ((this._explorerCooldownUntil?.get(nid) || 0) > Date.now()) return
    const slotTier = this.slotAllocator.acquire(node)
    if (!slotTier) return
    const expSessionId = `gw-exp-${nid}`
    let failed = false
    const p = driveExplorerCompanionPair(this.createDispatchRuntimePort(), node, snap, expSessionId, { signal: sig })
      .catch((err) => {
        if (err?.code !== 'GREATWALL_RUN_ABORTED') {
          failed = true
          this._explorerCooldownUntil?.set(nid, Date.now() + 3000)
          this.telemetry.recordEvent('explorer_worker_error', { nodeId: nid, error: String(err?.message || err) })
        }
      })
      .finally(() => {
        this._runningExplorers.delete(nid)
        this.slotAllocator.release(nid)
        this._syncSlotsToTelemetry()
        if (!failed) {
          this._explorerCooldownUntil?.delete(nid)
          this._wakeLoop()
        }
      })
    this._runningExplorers.set(nid, { promise: p, node, sessionId: expSessionId, slotTier, startedAt: Date.now() })
    this._syncSlotsToTelemetry()
  }

  async _runBlindReviewWithSandbox(rev, sig) {
    const reviewId = String(rev.review_id)
    const staged = await this.bridge.control('control_plane/stage_blind_sandbox', { workspace_root: this.workspaceRoot, review_id: reviewId })
    const sandboxPath = this.assertValidBlindSandbox(staged, reviewId)
    const uniqueVerifierSid = `gw_ver_${reviewId}_${crypto.randomUUID().slice(0, 6)}`
    try {
      await this.spawnAndRunAgent({
        role: 'library_verifier',
        sessionId: uniqueVerifierSid,
        questionId: rev.question_id,
        reviewId,
        sandboxAbsPath: sandboxPath,
        uiLabel: `[图书馆盲审] ${rev.question_id || ''} ${reviewId}`.trim(),
        shortTransaction: true,
        signal: sig,
        taskContextText: `### 独立空白盲审沙箱目录\n- sandbox_abs_path: \`${sandboxPath}\``,
        prompt: rev.review_status === 'STAGE1_BLIND'
          ? `请异会话执行盲审单 ${reviewId} (${rev.question_id})：调 get_blind_manuscript 独立验算后调 submit_stage1_blind_ledger（PASS 或 PARTIAL_PASS 均推进 Stage 2）；若通过即调 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成终判。`
          : `请对审稿单 ${reviewId} (${rev.question_id}) 调 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成 Stage 2 终判。`,
      })
    } finally {
      await this.bridge.control('control_plane/cleanup_blind_sandbox', { workspace_root: this.workspaceRoot, review_id: reviewId }).catch(() => {})
    }
  }

  async _runAsyncEventPool({ maxConcurrentWorkers = null } = {}) {
    const sig = this._loopAbortController.signal
    let idleStreak = 0
    let snapshotErrorStreak = 0

    // 重型实验崩溃恢复放到后台异步执行，绝不阻塞主循环消费 Outbox 快控制
    void this.bridge.control('control_plane/recover_heavy_jobs', { workspace_root: this.workspaceRoot }, { signal: sig }).catch(() => {})

    while (!sig.aborted && this._poolState !== 'stopped') {
      // 每轮（含全局暂停态）先消费 Outbox 副作用队列，确保节点让权、新口径热通知与总控通知不被暂停卡死
      await this.effectsConsumer.drainOnce({ limit: 12, signal: sig }).catch(() => {})

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
        this.telemetry.recordEvent('orchestrator_snapshot_error', {
          error: String(snapRes?.error || 'schedule_snapshot 返回失败'),
          streak: snapshotErrorStreak,
        })
        if (snapshotErrorStreak >= 3) {
          this._lastError = String(snapRes?.error || 'schedule_snapshot 连续失败')
          this._poolState = 'error'
          this.telemetry.setOrchestratorState('error', 'ERROR')
          break
        }
        await this._waitWakeOrTimeout(250)
        continue
      }
      snapshotErrorStreak = 0

      const snap = snapRes.data
      if (Array.isArray(snap.shared_inputs_rel_paths)) this.host.sharedInputPaths = snap.shared_inputs_rel_paths
      if (snap.stage === 'CLOSED_VERIFIED' || snap?.closure_state?.status === 'CLOSED_VERIFIED' || this._stage3Done) {
        this.telemetry.setOrchestratorState('idle', 'CLOSED_VERIFIED')
        break
      }
      this._syncSlotsToTelemetry(snap.stage)

      for (const al of snap.ambiguous_spec_alerts || []) {
        if (al?.alert_id && !this._seenAmbiguousAlertIds.has(al.alert_id)) {
          this._seenAmbiguousAlertIds.add(al.alert_id)
          this.telemetry.recordEvent('alert_ambiguous_spec_red_light', { alertId: al.alert_id, notes: al.notes })
        }
      }

      const port = this.createDispatchRuntimePort()
      let dispatchedSomething = dispatchPendingHandoffRecoveries(port, snap, sig)

      const s1 = await dispatchStage1Step(port, snap, sig)
      if (s1.handled) {
        if (s1.waitMs) await this._waitWakeOrTimeout(s1.waitMs)
        continue
      }

      const s3 = dispatchStage3Step(port, snap, sig)
      if (s3.handled) {
        await this._waitWakeOrTimeout(s3.waitMs || 250)
        continue
      }

      const s2 = await dispatchStage2Step(port, snap, sig, maxConcurrentWorkers)
      if (s2.dispatched) dispatchedSomething = true
      if (s2.continueImmediate) continue

      const hasCoolingGov = [...this._govCooldownUntil.values()].some((until) => until > Date.now())
      const activeConfs = Array.isArray(snap.active_wave_conferences)
        ? snap.active_wave_conferences
        : (Array.isArray(snap.active_conferences) ? snap.active_conferences : [])
      const hasPendingHumanWait =
        (snap.pending_proposals || []).length > 0 ||
        (snap.human_paused_nodes || []).length > 0 ||
        activeConfs.some((c) => String(c?.status || '') === 'PENDING_HUMAN_APPROVAL')

      if (!dispatchedSomething && this._runningExplorers.size === 0 && this._runningGov.size === 0 && !hasCoolingGov) {
        if (hasPendingHumanWait) {
          idleStreak = 0
          await this._waitWakeOrTimeout(1000)
          continue
        }
        idleStreak += 1
        if (idleStreak >= 3) break
      } else {
        idleStreak = 0
      }

      await this._waitWakeOrTimeout(250)
    }
  }

  async runUntilClosed({ signal = null, maxConcurrentWorkers = null, agentOptions = {}, callerAgent = null } = {}) {
    const binding = await this._resolveAndLockModelBinding({ explicitOptions: agentOptions, callerAgent })
    if (!binding.ok && this._requireExplicitModelBinding) {
      const err = new Error('MISSING_MODEL_BINDING: 无法解析权威 provider/model 绑定')
      err.code = 'MISSING_MODEL_BINDING'
      throw err
    }
    const lockRes = this.instanceLock.acquire()
    if (!lockRes.ok) throw new Error(lockRes.error)
    if (maxConcurrentWorkers) this.slotAllocator.setMaxWorkers(maxConcurrentWorkers)

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
      this.instanceLock.release()
    }
    const finalSnap = await this.bridge.control('control_plane/schedule_snapshot', { workspace_root: this.workspaceRoot })
    const closed = finalSnap?.data?.stage === 'CLOSED_VERIFIED' || finalSnap?.data?.closure_state?.status === 'CLOSED_VERIFIED' || this._stage3Done
    return { closed, aborted, modelBinding: this._modelBinding, circuitBrokenItems: this._itemBreaker.getBrokenItems(), snapshot: finalSnap?.data }
  }

  async disposeAll() {
    await this.stopBackground('DISPOSE_ALL')
    this.humanTakeover.disposeAll()
    await this.host.disposeAllSessions()
    this.instanceLock.release()
  }
}
