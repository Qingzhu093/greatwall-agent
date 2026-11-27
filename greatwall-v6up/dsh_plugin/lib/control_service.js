/**
 * GreatWall v0.3 统一控制服务（One Operation, Two Callers，裁决 1）。
 *
 * 严格权限隔离：
 * - `agent_tool`（极简 `greatwall_orchestrate`）：仅开放 `init / start / status / stop` 4 个薄入口（供 CLI Headless 与冷启动），
 *   **严禁任何大模型 MCP 工具伪造 `human_ui` 审批确认单或直接执行高危控制**；
 * - `human_ui`（右侧控制台 UI + 原生 Action Card + Headless 显式测试调用）：开放全部人类控制与乐观锁提案落签。
 * @module dsh-greatwall-v6up/control_service
 */
import path from 'node:path'
import { GreatwallMcpBridge } from './mcp_bridge.js'
import { GreatwallOrchestrator } from './orchestrator.js'
import { resolveTelemetryFilePath } from './telemetry.js'
import { ChiefEventInbox, chiefAnchorProvider, ensureChiefSession } from './sessions/chief_runtime.js'
import { createUserTextMessage } from './host/model_binding.js'

const WORKSPACE_ENTRY_ACTIONS = new Set(['init', 'start', 'resume', 'open_chief'])
const NODE_MODES = { pause_node: 'pause_takeover', resume_node: 'resume', authorize_early_handoff: 'early_handoff' }

export const CALLER_ALLOWED_ACTIONS = Object.freeze({
  agent_tool: Object.freeze([
    'init',
    'start',
    'status',
    'stop',
  ]),
  human_ui: Object.freeze([
    'init',
    'start',
    'pause',
    'resume',
    'stop',
    'human_stop',
    'abort_node',
    'submit_works_ticket',
    'sync_rulings',
    'status',
    'approve_proposal',
    'pause_node',
    'resume_node',
    'authorize_early_handoff',
    'set_subproblem_state',
    'set_autonomy_mode',
    'open_chief',
    'operator_command',
    'propose_epoch',
  ]),
})

function normalizeHumanSignedAt(raw) {
  if (raw === null || raw === undefined || raw === '') return null
  const text = String(raw).trim()
  if (!text || Number.isNaN(Date.parse(text))) return null
  return text
}

export function normalizeInitParse0Payload(args = {}) {
  const src = args && typeof args === 'object' ? args : {}
  const goalText = String(src.goal_and_completion_md ?? src.goalAndCompletionMd ?? src.goal_md ?? src.goalMd ?? '')
  const rawSubQs = src.subquestions ?? src.required_questions ?? src.requiredQuestions
  const subQs = Array.isArray(rawSubQs) && rawSubQs.length ? rawSubQs : ['Q1']
  const rawOrder = src.question_order ?? src.questionOrder
  const rawInsts = src.initial_instruments ?? src.initialInstruments
  const rawSeeds = src.seed_families ?? src.seedFamilies
  const rawBudget = src.total_budget ?? src.totalBudget
  const rawShared = src.shared_inputs_rel_paths ?? src.sharedInputsRelPaths
  const rawEpochId = src.epoch_id ?? src.epochId
  return {
    goalAndCompletionMd: goalText,
    subquestions: subQs,
    questionOrder: Array.isArray(rawOrder) ? rawOrder : [],
    initialInstruments: Array.isArray(rawInsts) ? rawInsts : [],
    seedFamilies: Array.isArray(rawSeeds) ? rawSeeds : [],
    totalBudget: rawBudget && typeof rawBudget === 'object' && !Array.isArray(rawBudget) ? rawBudget : {},
    minCommitmentWindowSec: Number(src.min_commitment_window_sec ?? src.minCommitmentWindowSec ?? 0) || 0,
    deliverySpecMd: String(src.delivery_spec_md ?? src.deliverySpecMd ?? ''),
    sharedInputsRelPaths: Array.isArray(rawShared) ? rawShared : [],
    stage: src.stage ? String(src.stage) : null,
    epochId: rawEpochId == null ? null : Number(rawEpochId),
    humanSignedAt: normalizeHumanSignedAt(src.human_signed_at ?? src.humanSignedAt ?? null),
    autonomyMode: src.autonomy_mode ?? src.autonomyMode ?? null,
  }
}

export class GreatwallControlService {
  constructor({ ctx, config, logger = console }) {
    this.ctx = ctx
    this.config = config
    this.logger = logger
    this.controllers = new Set()
    this.activeControllersByWs = new Map()
    this._wsLocks = new Map()
  }

  async adoptManualChief(agent, source) {
    const { session } = agent
    const { header, id: sessionId } = session
    const preset = this.ctx.get?.('agentPresets')?.presetForSession?.(session) ?? header.agentPreset
    if (preset !== 'greatwall-chief' || !header.cwd) return
    const ctrl = this.ensureController(header.cwd, { createIfMissing: true })
    const { host, telemetry } = ctrl.orchestrator
    if (host.hasSessionSetup(agent)) return
    try {
      const current = await ctrl.scheduleSnapshot()
      if (!current.ok) throw new Error(current.error)
      const currentEpoch = Number(current.data.epoch_id ?? 1)
      const known = telemetry.getSessionIdentity(sessionId)
      const epochId = Number(known?.sessionEpochId ?? (known || source === 'resume' ? 1 : currentEpoch))
      const readonly = epochId !== currentEpoch
      const anchor = readonly ? {} : chiefAnchorProvider(ctrl, current.data, { hardCapChars: this.config.chiefAnchorHardCapChars })
      const adopted = await host.adoptChief(agent, {
        ...anchor, epochId, readonly,
        onDispose: () => { if (ctrl.adoptedChief?.sessionId === sessionId) ctrl.adoptedChief = null },
      })
      if (adopted && !readonly) {
        ctrl.adoptedChief = { sessionId, epochId }
        ctrl.chiefMountError = null
      }
    } catch (error) {
      this._recordChiefMountError(ctrl, error)
    }
  }

  _recordChiefMountError(controller, error) {
    controller.chiefMountError = String(error?.message || error)
    controller.orchestrator.telemetry.recordEvent('chief_mount_error', { error: controller.chiefMountError })
  }

  _mountChief(controller) {
    if (controller.chiefMount) return controller.chiefMount
    const orchestrator = controller.orchestrator
    const task = (async () => {
      if (!controller.adoptedChief && !orchestrator._modelBinding?.ok) {
        const binding = await orchestrator._resolveAndLockModelBinding()
        if (!binding.ok) throw new Error('MISSING_MODEL_BINDING: 科研总控需要已选模型或插件默认模型')
      }
      return ensureChiefSession(controller, { hardCapChars: this.config.chiefAnchorHardCapChars })
    })().then((result) => {
      controller.chiefMountError = null
      return result
    }).catch((error) => {
      this._recordChiefMountError(controller, error)
      throw error
    }).finally(() => { controller.chiefMount = null })
    controller.chiefMount = task
    return task
  }

  async _withWorkspaceLock(wsKey, fn) {
    const prev = this._wsLocks.get(wsKey) || Promise.resolve()
    let release
    const gate = new Promise((resolve) => { release = resolve })
    const tail = prev.catch(() => {}).then(() => gate)
    this._wsLocks.set(wsKey, tail)
    try {
      await prev.catch(() => {})
      return await fn()
    } finally {
      release()
      if (this._wsLocks.get(wsKey) === tail) this._wsLocks.delete(wsKey)
    }
  }

  createSessionController(opts = {}) {
    const workspaceRoot = path.resolve(opts.workspaceRoot || process.cwd())
    const dataDir = opts.dataDir || this.config.dataDir || ''
    const bridge = new GreatwallMcpBridge({
      corePythonRoot: this.config.corePythonRoot,
      workspaceRoot,
      dataDir,
      pythonBin: opts.pythonBin || this.config.pythonBin || undefined,
      requestTimeoutMs: opts.requestTimeoutMs ?? this.config.requestTimeoutMs ?? 60_000,
      longToolTimeoutMs: opts.longToolTimeoutMs ?? this.config.longToolTimeoutMs ?? 300_000,
    })
    const wsDataRoot = path.dirname(resolveTelemetryFilePath({ dataDir, workspaceRoot }))
    const protectedDirs = [...new Set([wsDataRoot, ...(opts.protectedDirs || [])])]

    const chiefInbox = new ChiefEventInbox()
    const orchestrator = new GreatwallOrchestrator({
      ctx: this.ctx,
      bridge,
      corePythonRoot: this.config.corePythonRoot,
      workspaceRoot,
      dataDir,
      parentAgent: opts.parentAgent || null,
      defaultAgentOptions: opts.defaultAgentOptions || this.config.defaultAgentOptions || {},
      protectedDirs,
      onChiefNotify: async (ev) => {
        chiefInbox.ingest(ev)
        const handback = ev?.payload
        if (handback?.event_type === 'EXPLORER_HANDBACK') {
          const { sessionId } = await this._mountChief(controller)
          orchestrator.liveSessions.get(sessionId).handle.agent.steer(createUserTextMessage(
            `转办 ${handback.handback_id}：请先查询待办，按原始人类请求处理并核销。`,
          ))
        }
      },
    })

    const wsKey = workspaceRoot.toLowerCase()
    const controller = {
      workspaceRoot,
      corePythonRoot: this.config.corePythonRoot,
      bridge,
      orchestrator,
      chiefInbox,
      chiefMount: null,
      chiefMountError: null,
      async initParse0(rawPayload = {}) {
        const norm = normalizeInitParse0Payload(rawPayload)
        const res = await bridge.control('control_plane/init_parse0', {
          workspace_root: workspaceRoot,
          goal_and_completion_md: norm.goalAndCompletionMd,
          subquestions: norm.subquestions,
          question_order: norm.questionOrder,
          initial_instruments: norm.initialInstruments,
          seed_families: norm.seedFamilies,
          total_budget: norm.totalBudget,
          min_commitment_window_sec: norm.minCommitmentWindowSec,
          delivery_spec_md: norm.deliverySpecMd,
          shared_inputs_rel_paths: norm.sharedInputsRelPaths,
          stage: norm.stage,
          ...(Number.isInteger(norm.epochId) ? { epoch_id: norm.epochId } : {}),
          ...(norm.humanSignedAt ? { human_signed_at: norm.humanSignedAt } : {}),
          ...(norm.autonomyMode ? { autonomy_mode: norm.autonomyMode } : {}),
        })
        if (res?.ok) {
          orchestrator.host.sharedInputPaths = Array.isArray(res?.data?.shared_inputs_rel_paths)
            ? res.data.shared_inputs_rel_paths
            : norm.sharedInputsRelPaths
        }
        return res
      },
      async initEpoch(payload = {}) { return this.initParse0(payload) },
      async scheduleSnapshot(maxConcurrentWorkers = null) {
        return bridge.control('control_plane/schedule_snapshot', {
          workspace_root: workspaceRoot,
          ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
        })
      },
      async startBackground(runOpts = {}) { return orchestrator.startBackground(runOpts) },
      pauseBackground() { return orchestrator.pauseBackground() },
      async resumeBackground() { return orchestrator.resumeBackground() },
      async stopBackground(reason) { return orchestrator.stopBackground(reason) },
      async humanStop(note) { return orchestrator.humanStop(note) },
      async abortNode(nodeId, reason) { return orchestrator.abortNode(nodeId, reason) },
      async submitWorksTicket(ticketOpts) { return orchestrator.submitWorksTicket(ticketOpts) },
      async syncPublicRulings(refresh) { return orchestrator.syncPublicRulings(refresh) },
      async getControlStatus() { return orchestrator.getControlStatus() },
      async runUntilClosed(runOpts = {}) { return orchestrator.runUntilClosed(runOpts) },
      async dispose() {
        await orchestrator.disposeAll()
        await bridge.dispose()
        if (this._onDisposed) this._onDisposed()
      },
      _onDisposed: () => {
        this.controllers.delete(controller)
        if (this.activeControllersByWs.get(wsKey) === controller) this.activeControllersByWs.delete(wsKey)
      },
    }

    this.controllers.add(controller)
    this.activeControllersByWs.set(wsKey, controller)
    return controller
  }

  ensureController(workspaceRoot, { callerAgent = null, createIfMissing = false } = {}) {
    const ws = path.resolve(String(workspaceRoot))
    const key = ws.toLowerCase()
    let ctrl = this.activeControllersByWs.get(key)
    if (!ctrl && createIfMissing) {
      const callerOpts = callerAgent?.options || {}
      ctrl = this.createSessionController({
        workspaceRoot: ws,
        parentAgent: callerAgent || null,
        defaultAgentOptions: {
          ...this.config.defaultAgentOptions,
          ...(callerOpts.provider ? { provider: callerOpts.provider } : {}),
          ...(callerOpts.model ? { model: callerOpts.model } : {}),
          ...(callerOpts.reasoningEffort ? { reasoningEffort: callerOpts.reasoningEffort } : {}),
        },
      })
    } else if (ctrl && callerAgent) {
      ctrl.orchestrator.parentAgent = callerAgent
      if (ctrl.orchestrator.host) ctrl.orchestrator.host.parentAgent = callerAgent
    }
    return ctrl || null
  }

  async execute({ caller = 'agent_tool', action, workspaceRoot = '', controller = null, payload = {}, callerAgent = null }) {
    const act = String(action || '').trim()
    const allowed = CALLER_ALLOWED_ACTIONS[caller]
    if (!allowed) return { ok: false, action: act, callerSource: caller, error: `未知调用方身份: ${caller}` }
    if (!allowed.includes(act)) {
      return { ok: false, action: act, callerSource: caller, error: `调用方 ${caller} 无权执行动作 ${act}` }
    }

    const createIfMissing = WORKSPACE_ENTRY_ACTIONS.has(act)
    const ctrl = controller || (workspaceRoot ? this.ensureController(workspaceRoot, { callerAgent, createIfMissing }) : null)
    if (!ctrl) return { ok: false, action: act, callerSource: caller, error_code: 'WORKSPACE_INACTIVE', error: '目标工作区的长城控制器尚未启动。' }

    const ws = ctrl.workspaceRoot
    const wsKey = ws.toLowerCase()
    const defaultReasonPrefix = caller === 'human_ui' ? 'UI_CONSOLE' : 'MCP'
    const defaultSource = caller === 'human_ui' ? 'ui_console' : 'main_controller'

    if (act === 'init') {
      return this._withWorkspaceLock(wsKey, async () => {
        const initPayload = normalizeInitParse0Payload(payload)
        const initRes = await ctrl.initParse0(initPayload)
        return { ok: Boolean(initRes?.ok), action: act, callerSource: caller, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
      })
    }

    if (act === 'start') {
      return this._withWorkspaceLock(wsKey, async () => {
        const goalText = String(payload.goal_and_completion_md ?? payload.goalAndCompletionMd ?? payload.goal_md ?? '')
        const hasInlineInit = Boolean(goalText || (Array.isArray(payload.subquestions) && payload.subquestions.length))
        if (hasInlineInit && !ctrl.orchestrator.hasBackgroundTask()) {
          const preSnap = await ctrl.scheduleSnapshot()
          if (preSnap?.ok && !preSnap?.data?.parse0_signed) {
            const initRes = await ctrl.initParse0(normalizeInitParse0Payload(payload))
            if (!initRes?.ok) return { ok: false, action: act, callerSource: caller, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
          }
        }
        const explicitAgentOpts = {}
        if (payload.provider) explicitAgentOpts.provider = String(payload.provider).trim()
        if (payload.model) explicitAgentOpts.model = String(payload.model).trim()
        const expWin = Number(payload.effective_context_window || payload.context_window_tokens || 0)
        if (Number.isFinite(expWin) && expWin > 0) explicitAgentOpts.effectiveContextWindow = expWin
        const startRes = await ctrl.orchestrator.startBackground({
          maxConcurrentWorkers: payload.max_concurrent_workers ? Number(payload.max_concurrent_workers) : null,
          agentOptions: explicitAgentOpts,
          callerAgent,
        })
        // 裁决一：start 成功后自动异步拉起 gw-chief 出现在主工作区左侧栏，不再逼用户去右侧 UI 手动点按钮
        if (startRes?.started && !startRes?.alreadyRunning && typeof this.ctx?.agents?.create === 'function') {
          void this._mountChief(ctrl).catch(() => {})
        }
        return { ok: Boolean(startRes?.started), action: act, callerSource: caller, ...startRes }
      })
    }

    if (act === 'pause') {
      const pRes = await ctrl.orchestrator.pauseBackground()
      return {
        ok: Boolean(pRes?.paused),
        action: act,
        callerSource: caller,
        error: pRes?.paused ? null : (pRes?.error || `当前状态为 ${pRes?.state || 'unknown'}，无需暂停`),
        ...pRes,
      }
    }
    if (act === 'resume') {
      const rRes = await ctrl.orchestrator.resumeBackground()
      return {
        ok: Boolean(rRes?.resumed),
        action: act,
        callerSource: caller,
        error: rRes?.resumed ? null : (rRes?.error || `当前状态为 ${rRes?.state || 'unknown'}，无法恢复托管`),
        ...rRes,
      }
    }
    if (act === 'stop') {
      const stopRes = await ctrl.orchestrator.stopBackground(`${defaultReasonPrefix}_STOP`)
      await ctrl.bridge?.closeIdleChild?.()
      return { ok: true, action: act, callerSource: caller, ...stopRes }
    }
    if (act === 'human_stop') {
      const note = String(payload.note || payload.reason || `${defaultReasonPrefix}_HUMAN_STOP`)
      return { ok: true, action: act, callerSource: caller, ...(await ctrl.orchestrator.humanStop(note, { callerSource: caller })) }
    }
    if (act === 'abort_node') {
      const res = await ctrl.orchestrator.abortNode(String(payload.nodeId ?? payload.node_id ?? ''), String(payload.reason || `${defaultReasonPrefix}_ABORT_NODE`))
      return { ok: Boolean(res?.aborted), action: act, callerSource: caller, ...res }
    }
    if (act === 'submit_works_ticket') {
      const res = await ctrl.orchestrator.submitWorksTicket({
        questionId: String(payload.questionId ?? payload.question_id ?? 'ALL'),
        ticketType: String(payload.ticketType ?? payload.ticket_type ?? 'INSTRUMENT_ERROR'),
        instrumentId: (payload.instrumentId ?? payload.instrument_id) ? String(payload.instrumentId ?? payload.instrument_id) : null,
        description: String(payload.description || payload.reason || ''),
        source: String(payload.source || defaultSource),
      })
      return { ok: Boolean(res?.submitted), action: act, callerSource: caller, ...res }
    }
    if (act === 'sync_rulings') {
      const res = await ctrl.orchestrator.syncPublicRulings(Boolean(payload.refreshActiveWorktrees ?? payload.refresh_active_worktrees))
      return { ok: Boolean(res?.synced), action: act, callerSource: caller, ...res }
    }
    if (act === 'status') {
      return {
        ok: true,
        action: act,
        callerSource: caller,
        chiefPendingNotificationsCount: ctrl.chiefInbox?.peekCount() ?? 0,
        chiefMountError: ctrl.chiefMountError ?? null,
        ...(await ctrl.orchestrator.getControlStatus()),
      }
    }

    // === v0.3 新增 human_ui 专享高危与人工接管控制动作 ===
    if (act === 'approve_proposal') {
      const proposalId = String(payload.proposal_id ?? payload.proposalId ?? '')
      const proposal = await ctrl.bridge.control('control_plane/control_proposal_kind', {
        workspace_root: ws, proposal_id: proposalId,
      })
      const advancing = proposal?.data?.action_type === 'ADVANCE_EPOCH' &&
        proposal.data.status === 'PENDING_HUMAN' && String(payload.decision || 'APPROVE').toUpperCase() === 'APPROVE'
      if (advancing) {
        return this._withWorkspaceLock(wsKey, async () => {
          await ctrl.chiefMount?.catch(() => {})
          await ctrl.orchestrator.stopBackground('ADVANCE_EPOCH')
          const orchestrator = ctrl.orchestrator
          if (!(await orchestrator.awaitEpochQuiescence())) {
            return { ok: false, action: act, callerSource: caller, error: '旧纪元任务仍在退出，确认单仍可重试。' }
          }
          const lock = orchestrator.instanceLock.acquire()
          if (!lock.ok) return { ok: false, action: act, callerSource: caller, error: lock.error }
          try {
            const outcome = await ctrl.bridge.control('control_plane/approve_control_proposal', {
              workspace_root: ws, proposal_id: proposalId, decision: 'APPROVE', approved_by_source: 'human_ui',
            })
            if (outcome?.ok && outcome.data?.execution?.epoch_id) {
              ctrl.chiefInbox?.drainBatch()
              ctrl.chiefSessionId = null
              ctrl.chiefMountError = null
              await orchestrator.host.archiveAdoptedChiefs(outcome.data.execution.epoch_id)
            }
            return { ok: Boolean(outcome?.ok), action: act, callerSource: caller, data: outcome?.data, error: outcome?.error }
          } finally {
            orchestrator.instanceLock.release()
          }
        })
      }
      const res = await ctrl.bridge.control('control_plane/approve_control_proposal', {
        workspace_root: ws,
        proposal_id: proposalId,
        decision: String(payload.decision || 'APPROVE'),
        approved_by_source: String(payload.approved_by_source || 'human_ui'),
      })
      if (res?.ok) await ctrl.orchestrator.wakeOrRestartIfIdle?.()
      return { ok: Boolean(res?.ok), action: act, callerSource: caller, data: res?.data || null, error: res?.ok ? null : res?.error }
    }
    if (act === 'set_subproblem_state') {
      const desired = String(payload.desired_state ?? payload.desiredState ?? 'PAUSED').toUpperCase()
      const res = await ctrl.bridge.control('control_plane/set_subproblem_state', {
        workspace_root: ws,
        question_id: String(payload.question_id ?? payload.questionId ?? ''),
        desired_state: desired,
        actor_source: 'human_ui',
        reason: String(payload.reason || 'HUMAN_UI_SUBPROBLEM_TOGGLE'),
      })
      // 仅在恢复该题(ACTIVE)时唤醒或重启事件池，暂停单题绝不反向拉起已停机的事件池
      if (res?.ok && desired === 'ACTIVE') await ctrl.orchestrator.wakeOrRestartIfIdle?.()
      else if (res?.ok) ctrl.orchestrator._wakeLoop?.()
      return { ok: Boolean(res?.ok), action: act, callerSource: caller, data: res?.data || null, error: res?.ok ? null : res?.error }
    }
    if (act === 'set_autonomy_mode') {
      const res = await ctrl.bridge.control('control_plane/set_autonomy_mode', {
        workspace_root: ws,
        autonomy_mode: String(payload.autonomy_mode ?? payload.autonomyMode ?? 'WAVE_CONFIRM'),
        actor_source: 'human_ui',
      })
      if (res?.ok) ctrl.orchestrator._wakeLoop?.()
      return { ok: Boolean(res?.ok), action: act, callerSource: caller, data: res?.data || null, error: res?.ok ? null : res?.error }
    }
    if (act === 'propose_epoch') {
      const current = await ctrl.scheduleSnapshot()
      if (!current?.data?.parse0_signed) return { ok: false, action: act, error: '当前工作区没有可归档的已签署纪元' }
      const res = await ctrl.bridge.control('control_plane/create_control_proposal', {
        workspace_root: ws, action_type: 'ADVANCE_EPOCH', target_id: 'ALL', proposed_by: 'human_ui',
        rationale_md: `归档纪元 ${current.data.epoch_id}，按所选资产继承设置开启新纪元。`,
        payload: {
          expected_epoch_id: current.data.epoch_id,
          inherit_external_literature: payload.inherit_external_literature === true,
          inherit_instruments: payload.inherit_instruments === true,
        },
      })
      return { ok: Boolean(res?.ok), action: act, data: res?.data, error: res?.error }
    }
    const mode = NODE_MODES[act]
    if (act === 'operator_command' || mode) {
      const nodeAction = mode ? {
        mode, node_ids: [String(payload.node_id ?? payload.nodeId ?? '')],
        reason: payload.reason, cross_branch_note: payload.cross_branch_note ?? payload.note,
      } : payload.node_action
      const res = await ctrl.bridge.control('control_plane/operator_command', {
        workspace_root: ws,
        operation: mode ? 'node_intervene' : payload.operation, arrangement: payload.arrangement,
        arrangements: payload.arrangements, node_action: nodeAction, details: payload.details,
      })
      if (res?.ok) ctrl.orchestrator.notifyOperator()
      return { ok: Boolean(res?.ok), action: act, data: res?.data, error: res?.error }
    }
    if (act === 'open_chief') {
      let chiefRes
      try {
        chiefRes = await this._mountChief(ctrl)
      } catch (error) {
        return { ok: false, action: act, callerSource: caller, error: String(error?.message || error) }
      }
      const prompt = String(payload.prompt || '').trim()
      if (prompt) {
        void ctrl.orchestrator.resumeOrSpawnAgent({ role: 'gw_chief', sessionId: chiefRes.sessionId, prompt })
          .catch((error) => this.logger?.warn?.('[dsh-greatwall-v6up] chief followup failed', String(error?.message || error)))
      }
      return {
        ok: true,
        action: act,
        callerSource: caller,
        sessionId: chiefRes.sessionId,
        lastAssistantText: chiefRes.lastAssistantText,
        drainedEventsCount: chiefRes.drainedEventsCount,
      }
    }

    return { ok: false, action: act, callerSource: caller, error: `未知 action: ${act}` }
  }

  async disposeAll() {
    this.activeControllersByWs.clear()
    const active = [...this.controllers]
    await Promise.allSettled(active.map((c) => c.dispose()))
    this.controllers.clear()
    this._wsLocks.clear()
  }
}
