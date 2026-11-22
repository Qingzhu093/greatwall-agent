/**
 * 长城 V6-Up (v3.0) 外部无状态异步事件池编排器：
 *
 * 严格遵循 v3.0 顶层架构与 09 工程说明书（钱学森工程控制论原则：简洁、确定性、单一真源）：
 * 1. 启动强制显式模型绑定拒启门禁（`MISSING_MODEL_BINDING`），同步自适应窗口 `W = min(500k, model_window)` 至宿主机与 SQLite；
 * 2. 纯 SQLite 轮询快照 (`<50ms`) 驱动 Stage 1（含固定统一一次 `works_engineer` 初始核查）-> Stage 2 -> Stage 3 两步联合终核；
 * 3. 单条待办项级 2 次无客观进展熔断器（`GovernanceItemCircuitBreaker`）：按单项跟踪客观指纹，不误杀分步推进项、不连坐同队列其他健康项；
 * 4. 极简确定性人机控制：`pause / resume / stop / human_stop / abort_node`（彻底移除运行时 `steer` 广播与记忆队列）；
 * 5. 单节点伴随暂停续传、70% 硬跑两步交接（SQLite 单源持久化 `will_md`，取消内存双账本）与独立空白盲审沙箱。
 * @module dsh-greatwall-v6up/orchestrator
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { loadCoreRuntimeConfig, loadRolePrompts } from './prompts.js'
import { ensurePresetsInstalled } from './presets.js'
import { TelemetryCollector } from './telemetry.js'
import { AgentSessionHost, resolveAuthoritativeModelBinding } from './agent_session_host.js'
import {
  disposeNodeCompanion,
  driveExplorerCompanionPair,
  runHandoffWithCompanion,
  runPreSpawnBriefingWithCompanion,
} from './pair_lifecycle.js'

/**
 * 单条待办项级无客观进展熔断器（对齐 09 §2.2 第 6 条）：
 * - 同一条待办项连续 `maxStalledRuns`（默认 2）次被调度后客观指纹毫无变化，才仅挂起该单项；
 * - 若该项取得任何可核验客观进展（指纹变化）或离队，计数立刻归零；
 * - 同队列其他健康待办项完全不受影响；外部状态改变或人工 `resume` 时自动复位。
 */
export class GovernanceItemCircuitBreaker {
  constructor(maxStalledRuns = 2) {
    this.maxStalledRuns = Math.max(1, Number(maxStalledRuns) || 2)
    /** @type {Map<string, { stalledCount: number, lastFingerprint: string, broken: boolean, brokenAt: string | null }>} */
    this._items = new Map()
  }

  /**
   * 依据最新快照指纹判断某项是否已被熔断；若外部状态变化（指纹不同）则自动复位解除熔断！
   * @param {string} itemKey
   * @param {string} currentFingerprint
   */
  isBroken(itemKey, currentFingerprint) {
    const rec = this._items.get(itemKey)
    if (!rec) return false
    if (rec.lastFingerprint && currentFingerprint && rec.lastFingerprint !== currentFingerprint) {
      this._items.delete(itemKey)
      return false
    }
    return rec.broken
  }

  /**
   * 在某批待办项执行完毕并拉取新快照后，按单条项逐一评估是否取得客观进展。
   * @param {Array<{ key: string, beforeFp: string }>} dispatchedItems
   * @param {Map<string, string>} afterFpMap 仍在队列中的待办项最新指纹表（不在表中表示已出队完成）
   * @returns {Array<{ key: string, stalledCount: number, newlyBroken: boolean }>}
   */
  evaluateBatch(dispatchedItems, afterFpMap) {
    const results = []
    for (const { key, beforeFp } of dispatchedItems || []) {
      if (!afterFpMap.has(key)) {
        this._items.delete(key)
        continue
      }
      const afterFp = String(afterFpMap.get(key) || '')
      if (afterFp !== String(beforeFp || '')) {
        // 虽未出队但已产生可核验客观进展，计数清零绝不误熔断
        this._items.set(key, {
          stalledCount: 0,
          lastFingerprint: afterFp,
          broken: false,
          brokenAt: null,
        })
        results.push({ key, stalledCount: 0, newlyBroken: false })
        continue
      }
      const prev = this._items.get(key)
      const nextCount = (prev?.stalledCount || 0) + 1
      const wasBroken = Boolean(prev?.broken)
      const nowBroken = nextCount >= this.maxStalledRuns
      this._items.set(key, {
        stalledCount: nextCount,
        lastFingerprint: afterFp,
        broken: nowBroken,
        brokenAt: nowBroken ? (prev?.brokenAt || new Date().toISOString()) : null,
      })
      results.push({ key, stalledCount: nextCount, newlyBroken: nowBroken && !wasBroken })
    }
    return results
  }

  resetAll() {
    this._items.clear()
  }

  getBrokenItems() {
    const out = []
    for (const [key, rec] of this._items.entries()) {
      if (rec.broken) {
        out.push({ key, stalledCount: rec.stalledCount, brokenAt: rec.brokenAt })
      }
    }
    return out
  }
}

/**
 * 纯函数过滤本轮合法可派发的探索者节点（严格实施 `triage_locked_branches` 防抢跑与 `human_stop_active` 拦截，
 * 且遵循无人值守红灯策略：`ambiguous_spec_alerts` 绝不阻塞继续派单）。
 * @param {any} snap
 * @param {Set<string>} runningExplorerIds
 * @param {number} [slotCapOverride]
 */
export function selectDispatchableExplorers(snap, runningExplorerIds = new Set(), slotCapOverride = null) {
  if (!snap || snap.human_stop_active || snap.closure_gate?.closure_allowed) return []
  const slotCap = Math.max(1, Number(slotCapOverride || snap.slot_cap || 6))
  const lockedBranches = new Set(snap.triage_locked_branches || [])
  const candidates = []
  let occupied = runningExplorerIds.size
  for (const node of snap.explorers_ready_to_run || []) {
    if (occupied >= slotCap) break
    if (!node || !node.node_id) continue
    if (runningExplorerIds.has(node.node_id)) continue
    if (node.branch_id && lockedBranches.has(node.branch_id)) continue
    candidates.push(node)
    occupied += 1
  }
  return candidates
}

/** 为快照中各治理队列的每一条独立待办构造可核验客观指纹映射（严格单条隔离，不受同队列他项进出影响）。 */
function buildWorksItemFingerprints(snap) {
  const map = new Map()
  const instFpById = new Map()
  for (const s of snap?.active_instruments_fingerprint || []) {
    const id = String(s || '').split(':', 1)[0]
    if (id) instFpById.set(id, String(s))
  }
  for (const inst of snap?.unhealthy_instruments || []) {
    const k = `works:inst:${inst.instrument_id}`
    map.set(k, `inst:v${inst.version}:err=${inst.consecutive_error_count}:${inst.updated_at || ''}`)
  }
  for (const t of snap?.open_works_tickets || []) {
    const k = `works:ticket:${t.ticket_id}`
    // 仅绑定本工单自身状态及其直接关联的单个 instrument_id，严禁受其他无关仪器变动干扰
    const boundInstFp = t.instrument_id ? (instFpById.get(String(t.instrument_id)) || '') : ''
    map.set(k, `tkt:${t.updated_at || ''}:${t.payload_json || ''}|inst=${boundInstFp}`)
  }
  for (const rv of snap?.pending_revalidation || []) {
    const k = `works:reval:${rv.queue_id}`
    map.set(k, `reval:${rv.obs_id}:v${rv.target_version}:${rv.updated_at || ''}`)
  }
  return map
}

function buildSurveyItemFingerprints(snap) {
  const map = new Map()
  for (const r of snap?.pending_surveys || []) {
    const id = r.req_id || r.request_id
    if (!id) continue
    // 仅绑定单条查新单自身状态，严禁被同批其他查新单入卡计数重置计数
    map.set(`survey:${id}`, `req:${id}:${r.status || 'PENDING'}`)
  }
  return map
}

function buildTriageItemFingerprints(snap) {
  const map = new Map()
  for (const n of snap?.awaiting_triage || []) {
    if (!n?.node_id) continue
    map.set(`triage:${n.node_id}`, `triage:${n.node_id}:${n.family_id || ''}:${n.evidence_grade || ''}`)
  }
  return map
}

function buildReviewItemFingerprints(snap) {
  const map = new Map()
  for (const r of snap?.pending_reviews || []) {
    if (!r?.review_id) continue
    map.set(`review:${r.review_id}`, `rev:${r.review_id}:${r.review_status || ''}`)
  }
  return map
}

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

    // 1. 显式模型绑定硬门禁（F1：未解析到明确 provider/model 一律拒启，绝不跌落未授权默认模型！）
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
        sessEntry?.handle?.agent?.cancel?.({ kind: 'greatwall_abort_node' })
      } catch {}
    }
    await disposeNodeCompanion(this, nid, 'aborted')
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

      // 红灯口径歧义告警：记入遥测留待人类核查，**绝不停摆继续推进原已签口径！**
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

      let dispatchedSomething = false

      // 0. SQLite 单真源待交接/崩溃抢救恢复（彻底取消内存双账本）
      //    若 pending_handoff_mode === 'HANDOFF_70' 但未落库亲笔遗嘱（will_md/explorer_will_md 均空），降级为 CRASH_RECOVERY 并如实标注原文缺失
      for (const pnode of snap.pending_handoff_nodes || []) {
        if (this._runningExplorers.has(pnode.node_id)) continue
        const recKey = `recover:${pnode.node_id}`
        const recFp = `${pnode.pending_handoff_mode}:${pnode.updated_at || ''}`
        if (this._itemBreaker.isBroken(recKey, recFp)) continue
        const persistedWill = String(pnode.will_md || pnode.explorer_will_md || '').trim()
        const effMode =
          pnode.pending_handoff_mode === 'HANDOFF_70' && persistedWill
            ? 'HANDOFF_70'
            : 'CRASH_RECOVERY'
        const effReason =
          pnode.pending_handoff_mode === 'HANDOFF_70' && !persistedWill
            ? 'host_restart_before_will_persisted'
            : (pnode.pending_handoff_reason || 'host_restart_recovery')

        if (this._launchGovTask(`recover_handoff:${pnode.node_id}`, async () => {
          await runHandoffWithCompanion(this, pnode, {
            mode: effMode,
            explorerWillText: persistedWill,
            interruptReason: effReason,
            signal: sig,
          })
          this._handoffsSinceHeartbeat += 1
          await this._evaluateBreakerAfterTask(
            'lineage_companion',
            [{ key: recKey, beforeFp: recFp }],
            (nextSnap) => new Map(
              (nextSnap?.pending_handoff_nodes || []).map((n) => [
                `recover:${n.node_id}`,
                `${n.pending_handoff_mode}:${n.updated_at || ''}`,
              ]),
            ),
          )
        })) {
          dispatchedSomething = true
        }
      }

      // Stage 1: Parse 0 初始化与门禁放行（含固定统一一次 works_engineer 初始核查）
      if (snap.stage === 'STAGE1_PARSE0') {
        if (!snap.parse0_signed) {
          this.telemetry.recordEvent('waiting_parse0_signature', {})
          await this._waitWakeOrTimeout(500)
          continue
        }

        // 1.1 固定统一核查一次 works_engineer（初始仪器非空则逐台就绪；为空则确认无仪器后落标 stage1_works_checked=1）
        if (!snap.stage1_works_checked) {
          const missingInsts = snap.missing_initial_instruments || []
          const stage1WorksItems = missingInsts.length > 0
            ? missingInsts.map((m, idx) => ({
                key: `works:stage1:${m.instrument_id || m.id || idx}`,
                beforeFp: `missing:${JSON.stringify(m)}|insts=${JSON.stringify(snap.active_instruments_fingerprint || [])}`,
              }))
            : [{ key: 'works:stage1:empty_check', beforeFp: 'unchecked:empty' }]
          const activeStage1Items = stage1WorksItems.filter((it) => !this._itemBreaker.isBroken(it.key, it.beforeFp))

          if (activeStage1Items.length > 0) {
            dispatchedSomething = true
            await this._launchGovTaskAndAwaitIfSync('stage1:works_check', async () => {
              await this.spawnAndRunAgent({
                role: 'works_engineer',
                uiLabel: missingInsts.length > 0
                  ? `[科研仪器科] Stage1 初始仪器锻造 (${missingInsts.length}项)`
                  : '[科研仪器科] Stage1 初始核查确认',
                shortTransaction: false,
                signal: sig,
                taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 待就绪初始仪器清单\n${JSON.stringify(missingInsts, null, 2)}`,
                prompt: missingInsts.length > 0
                  ? `Stage 1 初始仪器核查：请调用 get_works_engineering_queue(question_id="ALL")，为 Parse 0 声明且尚未激活的初始仪器 ${JSON.stringify(missingInsts)} 逐一编写脚本与校准集并调用 register_question_instrument 完成激活。`
                  : 'Stage 1 统一初始仪器核查：Parse 0 未声明初始仪器（如纯理论/推导课题）。请调用一次 get_works_engineering_queue(question_id="ALL") 确认当前无需锻造初始仪器后直接正常返回，控制面将自动标记 stage1_works_checked=1 推进后续流程。',
              })
              // 控制面客观测验全部初始仪器是否已激活（或初始清单为空），达标即落标 stage1_works_checked=1
              const checkRes = await this.bridge.control('control_plane/mark_stage1_works_checked', {
                workspace_root: this.workspaceRoot,
              })
              if (!checkRes?.data?.stage1_works_checked) {
                await this._evaluateBreakerAfterTask('works_engineer', activeStage1Items, (nextSnap) => {
                  const m = new Map()
                  if (!nextSnap?.stage1_works_checked) {
                    const rem = nextSnap?.missing_initial_instruments || []
                    if (rem.length > 0) {
                      rem.forEach((x, i) => m.set(
                        `works:stage1:${x.instrument_id || x.id || i}`,
                        `missing:${JSON.stringify(x)}|insts=${JSON.stringify(nextSnap.active_instruments_fingerprint || [])}`,
                      ))
                    } else {
                      m.set('works:stage1:empty_check', 'unchecked:empty')
                    }
                  }
                  return m
                })
              }
            })
            continue
          }
        }

        // 1.2 外藏文献预建卡
        if (Number(snap.external_literature_count || 0) === 0) {
          const s1Key = 'stage1:surveyor'
          const s1Fp = 'ext_count=0'
          if (!this._itemBreaker.isBroken(s1Key, s1Fp)) {
            dispatchedSomething = true
            await this._launchGovTaskAndAwaitIfSync('stage1:surveyor', async () => {
              await this.spawnAndRunAgent({
                role: 'library_surveyor',
                uiLabel: '[图书馆采编] 开局文献建卡',
                shortTransaction: false,
                signal: sig,
                taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}`,
                prompt: `Stage 1 开局外藏建设：请围绕 Parse 0 子题 ${JSON.stringify(snap.required_questions || [])} 的核心机理与背景文献，调研并发布至少 1 张高密度外藏卡片 [R001]（调 publish_external_literature_card；outcome="CARD_PUBLISHED"，support_scope 严格使用 5 项英文枚举之一，read_depth 使用英文枚举，abstract_md 长度 60–1500 字）。成功入库后即可收尾放行编排。`,
              })
              await this._evaluateBreakerAfterTask('library_surveyor', [{ key: s1Key, beforeFp: s1Fp }], (nextSnap) => {
                const m = new Map()
                if (Number(nextSnap?.external_literature_count || 0) === 0) m.set(s1Key, 'ext_count=0')
                return m
              })
            })
            continue
          }
        }

        // 1.3 后勤按需开枝
        if (snap.questions_needing_branch?.length > 0) {
          const branchItems = snap.questions_needing_branch.map((q) => ({ key: `stage1:branch:${q}`, beforeFp: `need:${q}` }))
          const activeBranchItems = branchItems.filter((it) => !this._itemBreaker.isBroken(it.key, it.beforeFp))
          if (activeBranchItems.length > 0) {
            dispatchedSomething = true
            await this._launchGovTaskAndAwaitIfSync('stage1:logistics_init', async () => {
              await this.spawnAndRunAgent({
                role: 'logistics_coordinator',
                uiLabel: '[后勤总管] 开局按需开枝',
                shortTransaction: false,
                signal: sig,
                taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 子题解锁状态\n${JSON.stringify(snap.question_order_status || {}, null, 2)}`,
                prompt: `Stage 1 初始调度：请先调用 get_logistics_dashboard(question_id="ALL")，按课题本质（纯理论/数值/反例等）为已解锁子题 ${JSON.stringify(snap.questions_needing_branch)} 登记贴合机理的方法学派 (register_method_family) 并按需 fork_branch 开启初始分支（不强制固定学派数，禁止为凑数造伪学派）。`,
              })
              await this._evaluateBreakerAfterTask('logistics_coordinator', activeBranchItems, (nextSnap) =>
                new Map((nextSnap?.questions_needing_branch || []).map((q) => [`stage1:branch:${q}`, `need:${q}`])),
              )
            })
            continue
          }
        }

        // 1.4 监察委 Parse 0 门禁放行
        const gateKey = 'stage1:gate'
        const gateFp = `stage:${snap.stage}`
        if (!this._itemBreaker.isBroken(gateKey, gateFp)) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage1:gate', async () => {
            await this.spawnAndRunAgent({
              role: 'supervisory_committee',
              uiLabel: '[监察委员会] Parse0 门禁',
              shortTransaction: false,
              signal: sig,
              prompt: '请调用 get_supervisory_audit_snapshot 核验 Parse 0 六项启动表单已签署与开局就绪，调用 record_compliance_check(stage="PARSE0_GATE", status="PASSED", blocking_questions=[], notes="Parse 0 合规放行") 进入 STAGE2_EVOLVE。',
            })
            await this._evaluateBreakerAfterTask('supervisory_committee', [{ key: gateKey, beforeFp: gateFp }], (nextSnap) => {
              const m = new Map()
              if (nextSnap?.stage === 'STAGE1_PARSE0') m.set(gateKey, `stage:${nextSnap.stage}`)
              return m
            })
          })
          continue
        }
      }

      // Stage 3 两步联合终核与退修闭环状态机
      if (snap.stage3_revision_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        const revNotes = snap.closure_state?.verifier_revision_notes || '请修正边界表述与复现一致性'
        const deliveryMode = snap.closure_state?.delivery_mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
        const revKey = `stage3:revise:${latestDid}`
        const revFp = `revise:${latestDid}`
        if (!this._itemBreaker.isBroken(revKey, revFp)) {
          if (this._launchGovTask(revKey, async () => {
            await this.spawnAndRunAgent({
              role: 'library_surveyor',
              uiLabel: `[图书馆采编] Stage3 退修重导 ${latestDid}`,
              shortTransaction: false,
              signal: sig,
              taskContextText: `### 盲审终核退修意见 (${latestDid})\n${revNotes}`,
              prompt: `盲审官已将 Stage 3 交付包 ${latestDid} 退修 (REVISION_REQUESTED)！请逐条核查上述退修意见，调 get_survey_requests(question_id="ALL") 对齐最新 L3 范围与复现节点，修正论文后调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出全新版本交付包。`,
            })
            await this._evaluateBreakerAfterTask('library_surveyor', [{ key: revKey, beforeFp: revFp }], (nextSnap) => {
              const m = new Map()
              if (nextSnap?.stage3_revision_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
                m.set(revKey, revFp)
              }
              return m
            })
          })) {
            dispatchedSomething = true
          }
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      if (snap.stage3_final_audit_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        const auditRevId = `STAGE3_FINAL_AUDIT:${latestDid}`
        const auditKey = `stage3:final_audit:${latestDid}`
        const auditFp = `audit:${latestDid}`
        if (!this._itemBreaker.isBroken(auditKey, auditFp)) {
          if (this._launchGovTask(auditKey, async () => {
            const staged = await this.bridge.control('control_plane/stage_blind_sandbox', {
              workspace_root: this.workspaceRoot,
              review_id: auditRevId,
            })
            const sandboxPath = staged?.data?.sandbox_abs_path || ''
            try {
              await this.spawnAndRunAgent({
                role: 'library_verifier',
                sessionId: `gw_ver_s3_${crypto.randomUUID().slice(0, 6)}`,
                sandboxAbsPath: sandboxPath,
                uiLabel: `[图书馆盲审] Stage3 终稿终核 ${latestDid}`,
                shortTransaction: true,
                signal: sig,
                taskContextText: sandboxPath
                  ? `### 独立只读终核沙箱（含交付包副本与 verified_l3_scopes.json）\n- sandbox_abs_path: \`${sandboxPath}\``
                  : '',
                prompt: `Stage 3 终稿独立核验：请在只读沙箱内对照 verified_l3_scopes.json 审阅 final_delivery/ 副本（版本 ${latestDid}），核对所有引用 [L3-###]/[Obs-###]/[R###] 溯源真实、范围未夸大后，调用 submit_stage2_unblind_verdict(review_id="${auditRevId}", final_verdict="ACCEPT" 或 "REVISE", title="...", abstract_md="...") 落库。`,
              })
            } finally {
              await this.bridge
                .control('control_plane/cleanup_blind_sandbox', {
                  workspace_root: this.workspaceRoot,
                  review_id: auditRevId,
                })
                .catch(() => {})
            }
            await this._evaluateBreakerAfterTask('library_verifier', [{ key: auditKey, beforeFp: auditFp }], (nextSnap) => {
              const m = new Map()
              if (nextSnap?.stage3_final_audit_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
                m.set(auditKey, auditFp)
              }
              return m
            })
          })) {
            dispatchedSomething = true
          }
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      if (snap.stage3_supervisory_sign_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        const signKey = `stage3:sign:${latestDid}`
        const signFp = `sign:${latestDid}`
        if (!this._itemBreaker.isBroken(signKey, signFp)) {
          if (this._launchGovTask(signKey, async () => {
            await this.spawnAndRunAgent({
              role: 'supervisory_committee',
              uiLabel: `[监察委员会] 联合终签 ${latestDid}`,
              shortTransaction: false,
              signal: sig,
              prompt: `盲审官已完成最新版交付包 (${latestDid}) 独立终核！请调用 get_supervisory_audit_snapshot 确认版本哈希匹配，调用 record_compliance_check(stage="CLOSURE_GATE", status="PASSED", blocking_questions=[], notes="三项版本匹配校验通过，正式结项") 晋升 CLOSED_VERIFIED。`,
            })
            await this._evaluateBreakerAfterTask('supervisory_committee', [{ key: signKey, beforeFp: signFp }], (nextSnap) => {
              const m = new Map()
              if (nextSnap?.stage3_supervisory_sign_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
                m.set(signKey, signFp)
              }
              return m
            })
          })) {
            dispatchedSomething = true
          }
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      // Stage 2: 1) PRE_SPAWN 同节点伴随写看板并挂起保活（受 slot_cap 约束 + 单节点防自旋熔断）
      const effSlotCap = Math.max(1, Number(maxConcurrentWorkers || snap.slot_cap || 6))
      const runningBriefings = [...this._runningGov.keys()].filter((k) => k.startsWith('brief:')).length
      const readyWaitingCount = (snap.explorers_ready_to_run || []).filter((n) => !this._runningExplorers.has(n.node_id)).length
      let availBriefSlots = Math.max(0, effSlotCap - this._runningExplorers.size - runningBriefings - readyWaitingCount)
      for (const node of snap.explorers_needing_briefing || []) {
        if (availBriefSlots <= 0) break
        const bKey = `brief:${node.node_id}`
        const bFp = `brief:${node.node_id}:${node.updated_at || ''}`
        if (this._itemBreaker.isBroken(bKey, bFp)) continue
        if (this._launchGovTask(bKey, async () => {
          await runPreSpawnBriefingWithCompanion(this, node, { signal: sig })
          await this._evaluateBreakerAfterTask('lineage_companion', [{ key: bKey, beforeFp: bFp }], (nextSnap) =>
            new Map((nextSnap?.explorers_needing_briefing || []).map((n) => [`brief:${n.node_id}`, `brief:${n.node_id}:${n.updated_at || ''}`])),
          )
        })) {
          dispatchedSomething = true
          availBriefSlots -= 1
        }
      }

      // 2) 外藏查新需求响应（修复 r.req_id 列名 + 单条查新请求级熔断，不连坐健康查新单）
      const surveyFpMap = buildSurveyItemFingerprints(snap)
      const activeSurveyItems = []
      for (const [k, fp] of surveyFpMap.entries()) {
        if (!this._itemBreaker.isBroken(k, fp)) {
          activeSurveyItems.push({ key: k, beforeFp: fp, reqId: k.slice('survey:'.length) })
        }
      }
      if (activeSurveyItems.length > 0) {
        const reqIds = activeSurveyItems.map((it) => it.reqId)
        if (this._launchGovTask('survey:pending', async () => {
          await this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: `[图书馆采编] 响应查新 (${reqIds.length}单)`,
            shortTransaction: false,
            signal: sig,
            prompt: `待采编外部文献请求 ${JSON.stringify(reqIds)} 已就绪，请先调 get_survey_requests(question_id="ALL") 查看问题与检索词：若找到真实来源，调 publish_external_literature_card(outcome="CARD_PUBLISHED", ..., fulfilled_request_ids=...) 写入外藏卡片 [R###]；若确认资料客观不存在或违背合规边界，严禁造伪卡，请调 publish_external_literature_card(outcome="UNAVAILABLE_REPORT", question_id=..., fulfilled_request_ids=..., unavailable_reason_md=...) 诚实结案为 CLOSED_UNAVAILABLE。`,
          })
          await this._evaluateBreakerAfterTask('library_surveyor', activeSurveyItems, buildSurveyItemFingerprints)
        })) {
          dispatchedSomething = true
        }
      }

      // 3) 科研仪器科：熔断修复 / 痛点工单 / Stage B 离线重评（按单条待办项独立熔断，不连坐健康工单）
      const worksFpMap = buildWorksItemFingerprints(snap)
      const activeWorksItems = []
      for (const [k, fp] of worksFpMap.entries()) {
        if (!this._itemBreaker.isBroken(k, fp)) {
          activeWorksItems.push({ key: k, beforeFp: fp })
        }
      }
      if (activeWorksItems.length > 0) {
        const unhealthyInsts = (snap.unhealthy_instruments || []).filter(
          (i) => !this._itemBreaker.isBroken(`works:inst:${i.instrument_id}`, worksFpMap.get(`works:inst:${i.instrument_id}`) || ''),
        )
        const activeTickets = (snap.open_works_tickets || []).filter(
          (t) => !this._itemBreaker.isBroken(`works:ticket:${t.ticket_id}`, worksFpMap.get(`works:ticket:${t.ticket_id}`) || ''),
        )
        if (this._launchGovTask('works:queue', async () => {
          await this.spawnAndRunAgent({
            role: 'works_engineer',
            uiLabel: unhealthyInsts.length > 0
              ? `[科研仪器科] 仪器熔断修复 (${unhealthyInsts.map((i) => i.instrument_id).join(',')})`
              : `[科研仪器科] 工单与重评 (${activeWorksItems.length}项)`,
            shortTransaction: false,
            signal: sig,
            taskContextText: [
              unhealthyInsts.length > 0 ? `### 连续报错熔断仪器清单\n${JSON.stringify(unhealthyInsts, null, 2)}` : '',
              activeTickets.length > 0 ? `### 本次需处置工单 ID 列表\n${JSON.stringify(activeTickets.map((t) => t.ticket_id))}` : '',
            ].filter(Boolean).join('\n\n'),
            prompt: '请调用 get_works_engineering_queue(question_id="ALL") 检查熔断仪器、痛点工单与 pending_revalidation 队列：对故障或需升版仪器调用 upgrade_instrument_with_calibration（或 register_question_instrument）；对待重评旧观测调 recompute_stage_b_only；对每条已处理或无需改动的工单必须显式调用 resolve_works_ticket(ticket_id, resolution="RESOLVED"|"WONTFIX"|"DUPLICATE", resolution_note) 结案！',
          })
          await this._evaluateBreakerAfterTask('works_engineer', activeWorksItems, buildWorksItemFingerprints)
        })) {
          dispatchedSomething = true
        }
      }

      // 4) 后勤总管：分诊 AWAITING_TRIAGE + 无豁免聚拢分流 + 已解锁无分支子题派单
      const triageFpMap = buildTriageItemFingerprints(snap)
      const activeTriageItems = []
      for (const [k, fp] of triageFpMap.entries()) {
        if (!this._itemBreaker.isBroken(k, fp)) {
          activeTriageItems.push({ key: k, beforeFp: fp })
        }
      }
      const concAlerts = (snap.family_concentration_alerts || []).filter(
        (a) => !this._itemBreaker.isBroken(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`),
      )
      const needQs = (snap.questions_needing_branch || []).filter(
        (q) => !this._itemBreaker.isBroken(`need_branch:${q}`, `need:${q}`),
      )
      const logisticsItems = [
        ...activeTriageItems,
        ...concAlerts.map((a) => ({
          key: `conc:${a.question_id}:${a.family_id}`,
          beforeFp: `cnt=${a.branch_count_in_family}/${a.total_active_branches}`,
        })),
        ...needQs.map((q) => ({ key: `need_branch:${q}`, beforeFp: `need:${q}` })),
      ]
      if (logisticsItems.length > 0) {
        const triageCount = activeTriageItems.length
        if (this._launchGovTask('logistics:triage', async () => {
          await this.spawnAndRunAgent({
            role: 'logistics_coordinator',
            uiLabel: `[后勤总管] ${triageCount > 0 ? `分诊(${triageCount})` : (concAlerts.length > 0 ? '正交分流' : `派单(${needQs.join(',')})`)}`,
            shortTransaction: false,
            signal: sig,
            taskContextText: [
              concAlerts.length > 0 ? `### 学派聚拢红线告警 (>=2 且 >50%，无高产豁免)\n${JSON.stringify(concAlerts, null, 2)}` : '',
              snap.latest_spec_revision > 0 ? `### 最新公开裁决版本 v${snap.latest_spec_revision}\n${snap.latest_ruling_summary_md || ''}` : '',
            ].filter(Boolean).join('\n\n'),
            prompt: [
              '请调用 get_logistics_dashboard(question_id="ALL") 查看全卷待分诊节点、方法学派分布、最新公开裁决版本与子题进度：',
              triageCount > 0 ? `- 现有 ${triageCount} 个节点处于 AWAITING_TRIAGE（其分支已被硬锁禁止抢跑），请逐一调用 triage_node 做出裁决；` : '',
              concAlerts.length > 0 ? `- 触发学派聚拢红线告警（>=2 分支且占比 >50%，严禁高产豁免），请立即登记新正交学派并通过 fork_branch(fork_mode="orthogonal") 分流！` : '',
              needQs.length > 0 ? `- 子题 ${needQs.join(', ')} 尚无活跃探索分支，请按需开枝。` : '',
            ].filter(Boolean).join('\n'),
          })
          this._handoffsSinceHeartbeat += triageCount
          await this._evaluateBreakerAfterTask('logistics_coordinator', logisticsItems, (nextSnap) => {
            const m = buildTriageItemFingerprints(nextSnap)
            for (const a of nextSnap?.family_concentration_alerts || []) {
              m.set(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`)
            }
            for (const q of nextSnap?.questions_needing_branch || []) {
              m.set(`need_branch:${q}`, `need:${q}`)
            }
            return m
          })
        })) {
          dispatchedSomething = true
        }
      }

      // 5) 图书馆盲审官：独立空白沙箱两阶段盲审（单审稿单独立熔断）
      const reviewFpMap = buildReviewItemFingerprints(snap)
      for (const rev of snap.pending_reviews || []) {
        const rKey = `review:${rev.review_id}`
        const rFp = reviewFpMap.get(rKey) || `rev:${rev.review_id}:${rev.review_status}`
        if (this._itemBreaker.isBroken(rKey, rFp)) continue
        if (this._launchGovTask(rKey, async () => {
          await this._runBlindReviewWithSandbox(rev, sig)
          await this._evaluateBreakerAfterTask('library_verifier', [{ key: rKey, beforeFp: rFp }], buildReviewItemFingerprints)
        })) {
          dispatchedSomething = true
        }
      }

      // 6) 停滞五车道重排
      if (snap.stagnation_triggered) {
        const stagKey = 'logistics:stagnation'
        const stagFp = 'stagnation:1'
        if (!this._itemBreaker.isBroken(stagKey, stagFp)) {
          if (this._launchGovTask(stagKey, async () => {
            await this.spawnAndRunAgent({
              role: 'logistics_coordinator',
              uiLabel: '[后勤总管] 停滞五车道重排',
              shortTransaction: false,
              signal: sig,
              prompt: '连续无 L1 产出停滞看门狗已触发！请立即调用 get_logistics_dashboard 与 dispatch_stagnation_five_lanes 执行五车道正交重排。',
            })
            await this._evaluateBreakerAfterTask('logistics_coordinator', [{ key: stagKey, beforeFp: stagFp }], (nextSnap) => {
              const m = new Map()
              if (nextSnap?.stagnation_triggered) m.set(stagKey, stagFp)
              return m
            })
          })) {
            dispatchedSomething = true
          }
        }
      }

      // 7) 监察委周期心跳审计（仅在有新交接/分诊进展时按频次或 3 分钟节律触发，0 进展期间绝不空转）
      const nowMs = Date.now()
      if (
        snap.stage === 'STAGE2_EVOLVE' &&
        (this._handoffsSinceHeartbeat >= 3 ||
          (this._handoffsSinceHeartbeat > 0 && this._lastHeartbeatAt > 0 && nowMs - this._lastHeartbeatAt > 180_000))
      ) {
        if (this._launchGovTask('supervisory:heartbeat', async () => {
          this._handoffsSinceHeartbeat = 0
          this._lastHeartbeatAt = Date.now()
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage2 心跳审计',
            shortTransaction: false,
            signal: sig,
            prompt: '执行 STAGE2_HEARTBEAT 周期审计：请调 get_supervisory_audit_snapshot 核对流程合规、聚拢告警、最新公开裁决版本与仪器健康，调 record_compliance_check(stage="STAGE2_HEARTBEAT", status="PASSED" 或 "ALERT" 或 "ALERT_AMBIGUOUS_SPEC") 落库。',
          })
        })) {
          dispatchedSomething = true
        }
      }
      if (this._lastHeartbeatAt === 0) this._lastHeartbeatAt = nowMs

      // 8) 检查 Stage 2 结题放行
      if (
        snap.closure_gate?.closure_allowed &&
        snap.stage === 'STAGE2_EVOLVE' &&
        closureSt === 'OPEN' &&
        this._runningExplorers.size === 0 &&
        !this._runningGov.has('stage3:export')
      ) {
        const deliveryMode = snap.closure_gate?.mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
        const expKey = `stage3:export:${deliveryMode}`
        const expFp = `export:${deliveryMode}:OPEN`
        if (!this._itemBreaker.isBroken(expKey, expFp)) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage3:export', async () => {
            await this.spawnAndRunAgent({
              role: 'library_surveyor',
              uiLabel: `[图书馆采编] Stage3 五件套导出 (${deliveryMode})`,
              shortTransaction: false,
              signal: sig,
              prompt: `Stage 2 结题门禁已放行 (delivery_mode="${deliveryMode}")！请调用 get_survey_requests(question_id="ALL") 获取全卷已审 L3_VERIFIED 列表与溯源信息，严禁混入未过盲审草稿，撰写正式综合论文并调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出 final_delivery 五件套，进入两步联合终核。`,
            })
            await this._evaluateBreakerAfterTask('library_surveyor', [{ key: expKey, beforeFp: expFp }], (nextSnap) => {
              const m = new Map()
              if ((nextSnap?.closure_state?.status || 'OPEN') === 'OPEN' && nextSnap?.stage === 'STAGE2_EVOLVE') {
                m.set(expKey, expFp)
              }
              return m
            })
          })
          continue
        }
      }

      // 9) 探索者并发派发（严守 triage_locked_branches 防抢跑、human_stop_active 与 closure_gate 收口停新派）
      const runningIds = new Set(this._runningExplorers.keys())
      const readyNodes = selectDispatchableExplorers(snap, runningIds, maxConcurrentWorkers)
      for (const node of readyNodes) {
        dispatchedSomething = true
        this._launchExplorerWorker(node, snap, sig)
      }

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
