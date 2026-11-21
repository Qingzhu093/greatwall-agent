/**
 * 长城 V6-Up (v3.0) 外部无状态异步事件池编排器：
 *
 * 严格遵循 v3.0 顶层架构与 09 工程说明书：
 * 1. 纯 SQLite 轮询快照 (`<50ms`) 驱动 Stage 1 (`STAGE1_PARSE0`) -> Stage 2 (`STAGE2_EVOLVE`) -> Stage 3 两步联合终核 (`DELIVERY_EXPORTED` -> `CLOSED_VERIFIED`)；
 * 2. 防抢跑硬锁 (`triage_locked_branches`)、无豁免聚拢检测 (`family_concentration_alerts`)、`ALERT_AMBIGUOUS_SPEC` 红灯不停摆；
 * 3. 单节点伴随暂停续传 (`_nodeCompanionSessions`)、70% 两步清醒交接、盲审现建/销毁独立空白沙箱 (`stage_blind_sandbox`/`cleanup_blind_sandbox`)；
 * 4. 启动自动恢复中断的 `heavy` 冻结作业 (`recover_heavy_jobs`)；人类叫停唯一合法控制面入口 `humanStop(note)` (`record_human_stop`)。
 * @module dsh-greatwall-v6up/orchestrator
 */
import crypto from 'node:crypto'
import path from 'node:path'
import { loadCoreRuntimeConfig, loadRolePrompts } from './prompts.js'
import { ensurePresetsInstalled } from './presets.js'
import { TelemetryCollector } from './telemetry.js'
import { AgentSessionHost, createUserTextMessage } from './agent_session_host.js'
import {
  disposeNodeCompanion,
  driveExplorerCompanionPair,
  runHandoffWithCompanion,
  runPreSpawnBriefingWithCompanion,
} from './pair_lifecycle.js'

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
    /** @type {Set<() => void>} */
    this._wakeResolvers = new Set()
    this._lastError = null
    this._runningExplorers = new Map()
    this._runningGov = new Map()
    this._govCooldownUntil = new Map()
    /** 单节点同会话伴随暂停保活句柄表（严格按 node_id 绑定，绝不跨代复用） */
    this._nodeCompanionSessions = new Map()
    this._pendingSalvageNodes = new Map()
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

  async startBackground({ maxConcurrentWorkers = null, agentOptions = {} } = {}) {
    // 幂等保护：若后台循环仍在存活，running 直接返回，paused 则恢复原循环，严禁起第二条并发循环！
    if (this._backgroundTask) {
      if (this._poolState === 'paused') {
        this.resumeBackground()
        return { started: true, alreadyRunning: true, resumed: true, status: await this.getControlStatus() }
      }
      if (this._poolState === 'running') {
        return { started: true, alreadyRunning: true, status: await this.getControlStatus() }
      }
    }

    // 启动前置门禁：核验内核可达且已签署 Parse 0，杜绝未签契约静默空转刷盘
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

    if (agentOptions && Object.keys(agentOptions).length > 0) {
      this.defaultAgentOptions = { ...this.defaultAgentOptions, ...agentOptions }
    }
    if (!this._loopAbortController || this._loopAbortController.signal.aborted) {
      this._loopAbortController = new AbortController()
    }
    this._lastError = null
    this._poolState = 'running'
    this._stage3Done = false
    this.telemetry.setOrchestratorState('running')
    this.telemetry.recordEvent('orchestrator_start', { maxConcurrentWorkers })

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
              `[人类/主控实时定向纠偏 (${entry.targetType}:${entry.targetId})]\n请立即优先执行以下纠偏指令，勿继续无效重复循环：\n${entry.directive}`,
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
      runningExplorersCount: this._runningExplorers.size,
      runningExplorers: [...this._runningExplorers.values()].map((e) => ({
        nodeId: e.node.node_id,
        questionId: e.node.question_id,
        sessionId: e.sessionId,
      })),
      runningGovernanceTasks: [...this._runningGov.keys()],
      activeSessions: liveList,
      pendingSalvageNodes: [...this._pendingSalvageNodes.keys()],
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
        taskContextText: this._appendInterventions(
          sandboxPath ? `### 独立空白盲审沙箱目录\n- sandbox_abs_path: \`${sandboxPath}\`\n（你仅可在此沙箱内只读浏览并运行独立验证脚本，物理断网且不可访问 DB/工作树/B 栏）` : '',
          'library_verifier',
          rev.question_id || '',
        ),
        prompt: rev.review_status === 'STAGE1_BLIND'
          ? `请以异会话执行盲审单 ${reviewId} (${rev.question_id})：先调 get_blind_manuscript 审阅脱敏 A 栏与沙箱复核工件，在空白沙箱内独立验算后调 submit_stage1_blind_ledger 锁定不可逆账本；若 Stage 1 判 PASS，紧接着调 get_unblinded_manuscript_and_peers 与 submit_stage2_unblind_verdict 完成终判（判 REVISE/REFUTED 时立即结束）。`
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

      // 0. 异常中断 (<70%) 崩溃抢救 + SQLite 持久化重启恢复（含已写完遗嘱待伴随交接的节点）
      if (this._pendingSalvageNodes.size > 0) {
        for (const [nid, info] of this._pendingSalvageNodes.entries()) {
          if (this._launchGovTask(`salvage:${nid}`, async () => {
            this._pendingSalvageNodes.delete(nid)
            await runHandoffWithCompanion(this, info.node, {
              mode: 'CRASH_RECOVERY',
              latestBlackbox: info.blackboxSummary,
              interruptReason: info.reason,
              signal: sig,
            })
            this._handoffsSinceHeartbeat += 1
          })) {
            dispatchedSomething = true
          }
        }
      }
      for (const pnode of snap.pending_handoff_nodes || []) {
        if (this._runningExplorers.has(pnode.node_id) || this._pendingSalvageNodes.has(pnode.node_id)) continue
        if (this._launchGovTask(`recover_handoff:${pnode.node_id}`, async () => {
          await runHandoffWithCompanion(this, pnode, {
            mode: pnode.pending_handoff_mode || 'HANDOFF_70',
            explorerWillText: pnode.explorer_will_md || '',
            interruptReason: pnode.pending_handoff_reason || 'host_restart_recovery',
            signal: sig,
          })
          this._handoffsSinceHeartbeat += 1
        })) {
          dispatchedSomething = true
        }
      }

      // Stage 1: Parse 0 初始化与门禁放行（不强逼建固定数值基线或硬凑学派数量）
      if (snap.stage === 'STAGE1_PARSE0') {
        if (!snap.parse0_signed) {
          this.telemetry.recordEvent('waiting_parse0_signature', {})
          await this._waitWakeOrTimeout(500)
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
                `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}`,
                'library_surveyor',
              ),
              prompt: `Stage 1 开局外藏建设：请围绕 Parse 0 子题 ${JSON.stringify(snap.required_questions || [])} 的核心机理与背景文献，调研并发布至少 1 张高密度外藏卡片 [R001]（调 publish_external_literature_card；support_scope 严格使用 5 项英文枚举之一，read_depth 使用英文枚举，abstract_md 长度 60–1500 字）。成功入库后即可收尾放行编排。`,
            }),
          )
          continue
        }

        if (snap.questions_needing_branch?.length > 0) {
          dispatchedSomething = true
          await this._launchGovTaskAndAwaitIfSync('stage1:logistics_init', () =>
            this.spawnAndRunAgent({
              role: 'logistics_coordinator',
              uiLabel: '[后勤总管] 开局按需开枝',
              shortTransaction: false,
              signal: sig,
              taskContextText: this._appendInterventions(
                `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 子题解锁状态\n${JSON.stringify(snap.question_order_status || {}, null, 2)}`,
                'logistics_coordinator',
              ),
              prompt: `Stage 1 初始调度：请先调用 get_logistics_dashboard(question_id="ALL")，按课题本质（纯理论/数值/反例等）为已解锁子题 ${JSON.stringify(snap.questions_needing_branch)} 登记贴合机理的方法学派 (register_method_family) 并按需 fork_branch 开启初始分支（不强制固定学派数，禁止为凑数造伪学派）。`,
            }),
          )
          continue
        }

        dispatchedSomething = true
        await this._launchGovTaskAndAwaitIfSync('stage1:gate', () =>
          this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Parse0 门禁',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '请调用 get_supervisory_audit_snapshot 核验 Parse 0 六项启动表单已签署与开局就绪，调用 record_compliance_check(stage="PARSE0_GATE", status="PASSED", blocking_questions=[], notes="Parse 0 合规放行") 进入 STAGE2_EVOLVE。',
          }),
        )
        continue
      }

      // Stage 3 两步联合终核与退修闭环状态机（REVISION_REQUESTED -> 馆员重导；DELIVERY_EXPORTED -> 独立沙箱终核 -> 监察委终签）
      if (snap.stage3_revision_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        const revNotes = snap.closure_state?.verifier_revision_notes || '请修正边界表述与复现一致性'
        const deliveryMode = snap.closure_state?.delivery_mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
        if (this._launchGovTask(`stage3:revise:${latestDid}`, () =>
          this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: `[图书馆采编] Stage3 退修重导 ${latestDid}`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions(
              `### 盲审终核退修意见 (${latestDid})\n${revNotes}`,
              'library_surveyor',
            ),
            prompt: `盲审官已将 Stage 3 交付包 ${latestDid} 退修 (REVISION_REQUESTED)！请逐条核查上述退修意见，调 get_survey_requests(question_id="ALL") 对齐最新 L3 范围与复现节点，修正论文后调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出全新版本交付包。`,
          }),
        )) {
          dispatchedSomething = true
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      if (snap.stage3_final_audit_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        const auditRevId = `STAGE3_FINAL_AUDIT:${latestDid}`
        if (this._launchGovTask(`stage3:final_audit:${latestDid}`, async () => {
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
              taskContextText: this._appendInterventions(
                sandboxPath ? `### 独立只读终核沙箱（含交付包副本与 verified_l3_scopes.json）\n- sandbox_abs_path: \`${sandboxPath}\`` : '',
                'library_verifier',
              ),
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
        })) {
          dispatchedSomething = true
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      if (snap.stage3_supervisory_sign_pending) {
        const latestDid = snap.closure_state?.latest_delivery_id || ''
        if (this._launchGovTask(`stage3:sign:${latestDid}`, async () => {
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: `[监察委员会] 联合终签 ${latestDid}`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: `盲审官已完成最新版交付包 (${latestDid}) 独立终核！请调用 get_supervisory_audit_snapshot 确认版本哈希匹配，调用 record_compliance_check(stage="CLOSURE_GATE", status="PASSED", blocking_questions=[], notes="三项版本匹配校验通过，正式结项") 晋升 CLOSED_VERIFIED。`,
          })
        })) {
          dispatchedSomething = true
        }
        await this._waitWakeOrTimeout(250)
        continue
      }

      // Stage 2: 1) PRE_SPAWN 同节点伴随写看板并挂起保活（受 slot_cap 约束，避免多起空转保活伴随）
      const effSlotCap = Math.max(1, Number(maxConcurrentWorkers || snap.slot_cap || 6))
      const runningBriefings = [...this._runningGov.keys()].filter((k) => k.startsWith('brief:')).length
      const readyWaitingCount = (snap.explorers_ready_to_run || []).filter((n) => !this._runningExplorers.has(n.node_id)).length
      let availBriefSlots = Math.max(0, effSlotCap - this._runningExplorers.size - runningBriefings - readyWaitingCount)
      for (const node of snap.explorers_needing_briefing || []) {
        if (availBriefSlots <= 0) break
        if (this._launchGovTask(`brief:${node.node_id}`, () =>
          runPreSpawnBriefingWithCompanion(this, node, { signal: sig }),
        )) {
          dispatchedSomething = true
          availBriefSlots -= 1
        }
      }

      // 2) 外藏查新需求响应
      if (snap.pending_surveys?.length > 0) {
        const reqIds = snap.pending_surveys.map((r) => r.request_id)
        if (this._launchGovTask('survey:pending', () =>
          this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: `[图书馆采编] 响应查新 (${reqIds.length}单)`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_surveyor'),
            prompt: `待采编外部文献请求 ${JSON.stringify(reqIds)} 已就绪，请先调 get_survey_requests(question_id="ALL") 查看问题与检索词，调研后调用 publish_external_literature_card 写入标准外藏卡片 [R###] 并传入 fulfilled_request_ids 精准核销。`,
          }),
        )) {
          dispatchedSomething = true
        }
      }

      // 3) 科研仪器科：熔断修复 / 痛点工单 / Stage B 离线重评
      const unhealthyInsts = snap.unhealthy_instruments || []
      if (unhealthyInsts.length > 0 || snap.open_works_tickets?.length > 0 || snap.pending_revalidation?.length > 0) {
        if (this._launchGovTask('works:queue', () =>
          this.spawnAndRunAgent({
            role: 'works_engineer',
            uiLabel: unhealthyInsts.length > 0
              ? `[科研仪器科] 仪器熔断修复 (${unhealthyInsts.map((i) => i.instrument_id).join(',')})`
              : '[科研仪器科] 仪器校准/StageB重评',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions(
              unhealthyInsts.length > 0 ? `### 连续报错熔断仪器清单\n${JSON.stringify(unhealthyInsts, null, 2)}` : '',
              'works_engineer',
            ),
            prompt: '请调用 get_works_engineering_queue(question_id="ALL") 检查熔断仪器、痛点工单与 pending_revalidation 队列：对故障或需升版仪器编写/完善校准集并调用 upgrade_instrument_with_calibration（或 register_question_instrument）；对待重评旧观测逐条调用 recompute_stage_b_only（绝不覆写旧收据，缺字段诚实标 INCOMPATIBLE）。',
          }),
        )) {
          dispatchedSomething = true
        }
      }

      // 4) 后勤总管：分诊 AWAITING_TRIAGE + 无豁免聚拢分流 + 已解锁无分支子题派单
      const concAlerts = snap.family_concentration_alerts || []
      const triageCount = snap.awaiting_triage?.length || 0
      const needQs = snap.questions_needing_branch || []
      if (triageCount > 0 || concAlerts.length > 0 || needQs.length > 0) {
        if (this._launchGovTask('logistics:triage', async () => {
          await this.spawnAndRunAgent({
            role: 'logistics_coordinator',
            uiLabel: `[后勤总管] ${triageCount > 0 ? `分诊(${triageCount})` : (concAlerts.length > 0 ? '正交分流' : `派单(${needQs.join(',')})`)}`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions(
              concAlerts.length > 0 ? `### 学派聚拢红线告警 (>=2 且 >50%，无高产豁免)\n${JSON.stringify(concAlerts, null, 2)}` : '',
              'logistics_coordinator',
            ),
            prompt: [
              '请调用 get_logistics_dashboard(question_id="ALL") 查看全卷待分诊节点、方法学派分布与子题进度：',
              triageCount > 0 ? `- 现有 ${triageCount} 个节点处于 AWAITING_TRIAGE（其分支已被硬锁禁止抢跑），请逐一调用 triage_node 做出裁决；` : '',
              concAlerts.length > 0 ? `- 触发学派聚拢红线告警（>=2 分支且占比 >50%，严禁高产豁免），请立即登记新正交学派并通过 fork_branch(fork_mode="orthogonal") 分流！` : '',
              needQs.length > 0 ? `- 子题 ${needQs.join(', ')} 尚无活跃探索分支，请按需开枝。` : '',
            ].filter(Boolean).join('\n'),
          })
          this._handoffsSinceHeartbeat += triageCount
        })) {
          dispatchedSomething = true
        }
      }

      // 5) 图书馆盲审官：独立空白沙箱两阶段盲审
      for (const rev of snap.pending_reviews || []) {
        if (this._launchGovTask(`review:${rev.review_id}`, () => this._runBlindReviewWithSandbox(rev, sig))) {
          dispatchedSomething = true
        }
      }

      // 6) 停滞五车道重排
      if (snap.stagnation_triggered) {
        if (this._launchGovTask('logistics:stagnation', () =>
          this.spawnAndRunAgent({
            role: 'logistics_coordinator',
            uiLabel: '[后勤总管] 停滞五车道重排',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'logistics_coordinator'),
            prompt: '连续无 L1 产出停滞看门狗已触发！请立即调用 get_logistics_dashboard 与 dispatch_stagnation_five_lanes 执行五车道正交重排。',
          }),
        )) {
          dispatchedSomething = true
        }
      }

      // 7) 监察委周期心跳审计
      const nowMs = Date.now()
      if (snap.stage === 'STAGE2_EVOLVE' && (this._handoffsSinceHeartbeat >= 3 || (this._lastHeartbeatAt > 0 && nowMs - this._lastHeartbeatAt > 180_000))) {
        if (this._launchGovTask('supervisory:heartbeat', async () => {
          this._handoffsSinceHeartbeat = 0
          this._lastHeartbeatAt = Date.now()
          await this.spawnAndRunAgent({
            role: 'supervisory_committee',
            uiLabel: '[监察委员会] Stage2 心跳审计',
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'supervisory_committee'),
            prompt: '执行 STAGE2_HEARTBEAT 周期审计：请调 get_supervisory_audit_snapshot 核对流程合规、聚拢告警与仪器健康，调 record_compliance_check(stage="STAGE2_HEARTBEAT", status="PASSED" 或 "ALERT" 或 "ALERT_AMBIGUOUS_SPEC") 落库。',
          })
        })) {
          dispatchedSomething = true
        }
      }
      if (this._lastHeartbeatAt === 0) this._lastHeartbeatAt = nowMs

      // 8) 先检查 Stage 2 结题放行（预算耗尽或 FULL 达标时不再新派活，等场上在跑的自然归零后立刻导出 Stage 3 五件套）
      if (
        snap.closure_gate?.closure_allowed &&
        snap.stage === 'STAGE2_EVOLVE' &&
        closureSt === 'OPEN' &&
        this._runningExplorers.size === 0 &&
        !this._runningGov.has('stage3:export')
      ) {
        const deliveryMode = snap.closure_gate?.mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
        dispatchedSomething = true
        await this._launchGovTaskAndAwaitIfSync('stage3:export', async () => {
          await this.spawnAndRunAgent({
            role: 'library_surveyor',
            uiLabel: `[图书馆采编] Stage3 五件套导出 (${deliveryMode})`,
            shortTransaction: false,
            signal: sig,
            taskContextText: this._appendInterventions('', 'library_surveyor'),
            prompt: `Stage 2 结题门禁已放行 (delivery_mode="${deliveryMode}")！请调用 get_survey_requests(question_id="ALL") 获取全卷已审 L3_VERIFIED 列表与溯源信息，严禁混入未过盲审草稿，撰写正式综合论文并调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出 final_delivery 五件套，进入两步联合终核。`,
          })
        })
        continue
      }

      // 9) 探索者并发派发（严守 triage_locked_branches 防抢跑、human_stop_active 与 closure_gate 收口停新派）
      const runningIds = new Set(this._runningExplorers.keys())
      const readyNodes = selectDispatchableExplorers(snap, runningIds, maxConcurrentWorkers)
      for (const node of readyNodes) {
        dispatchedSomething = true
        this._launchExplorerWorker(node, snap, sig)
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
    const closed = finalSnap?.data?.stage === 'CLOSED_VERIFIED' || finalSnap?.data?.closure_state?.status === 'CLOSED_VERIFIED' || this._stage3Done
    return {
      closed,
      aborted,
      snapshot: finalSnap?.data,
    }
  }

  async disposeAll() {
    await this.stopBackground('DISPOSE_ALL')
    await this.host.disposeAllSessions()
  }
}
