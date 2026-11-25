/**
 * 长城 V6-Up (v3.0) 统一控制服务（One Operation, Two Callers）。
 *
 * 将主控工具（`agent_tool`）与控制台 HTTP 路由（`human_ui`）收口到单一业务控制面：
 * - 显式声明两类调用方的允许动作矩阵（`CALLER_ALLOWED_ACTIONS`）；
 * - 所有动作强制携带调用方溯源 `callerSource`，避免双入口各自重复写分发逻辑；
 * - 对同一工作区的 `init` / `start` 施加按工作区粒度的异步互斥锁，杜绝并发冷启动竞态；
 * - 统一托管 `controllers` 与 `activeControllersByWs`，确保插件卸载时全量释放。
 * @module dsh-greatwall-v6up/control_service
 */
import path from 'node:path'
import { GreatwallMcpBridge } from './mcp_bridge.js'
import { GreatwallOrchestrator } from './orchestrator.js'
import { resolveTelemetryFilePath } from './telemetry.js'

export const CALLER_ALLOWED_ACTIONS = Object.freeze({
  agent_tool: Object.freeze([
    'init',
    'start',
    'pause',
    'resume',
    'stop',
    'human_stop',
    'abort_node',
    'submit_works_ticket',
    'sync_rulings',
    'inspect',
    'status',
  ]),
  human_ui: Object.freeze([
    'init',
    'pause',
    'resume',
    'stop',
    'human_stop',
    'abort_node',
    'submit_works_ticket',
    'sync_rulings',
    'status',
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
  const goalText = String(
    src.goal_and_completion_md ?? src.goalAndCompletionMd ?? src.goal_md ?? src.goalMd ?? '',
  )
  const rawSubQs = src.subquestions ?? src.required_questions ?? src.requiredQuestions
  const subQs = Array.isArray(rawSubQs) && rawSubQs.length ? rawSubQs : ['Q1']
  const rawOrder = src.question_order ?? src.questionOrder
  const rawInsts = src.initial_instruments ?? src.initialInstruments
  const rawSeeds = src.seed_families ?? src.seedFamilies
  const rawBudget = src.total_budget ?? src.totalBudget
  const rawShared = src.shared_inputs_rel_paths ?? src.sharedInputsRelPaths
  const rawEpochId = src.epoch_id ?? src.epochId ?? 1
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
    epochId: Number.isFinite(Number(rawEpochId)) ? Number(rawEpochId) : 1,
    humanSignedAt: normalizeHumanSignedAt(src.human_signed_at ?? src.humanSignedAt ?? null),
  }
}

export class GreatwallControlService {
  /**
   * @param {object} opts
   * @param {any} opts.ctx
   * @param {object} opts.config 已由 resolvePluginConfig 规范化的配置
   * @param {any} [opts.logger]
   */
  constructor({ ctx, config, logger = console }) {
    this.ctx = ctx
    this.config = config
    this.logger = logger
    /** @type {Set<{ dispose: () => Promise<void> }>} */
    this.controllers = new Set()
    /** @type {Map<string, any>} */
    this.activeControllersByWs = new Map()
    /** @type {Map<string, Promise<any>>} 同工作区串行互斥队列（防并发 init/start 竞态） */
    this._wsLocks = new Map()
  }

  /** 按工作区路径串行化执行关键写操作（init / start）。 */
  async _withWorkspaceLock(wsKey, fn) {
    const prev = this._wsLocks.get(wsKey) || Promise.resolve()
    let release
    const gate = new Promise((resolve) => {
      release = resolve
    })
    const tail = prev.catch(() => {}).then(() => gate)
    this._wsLocks.set(wsKey, tail)
    try {
      await prev.catch(() => {})
      return await fn()
    } finally {
      release()
      if (this._wsLocks.get(wsKey) === tail) {
        this._wsLocks.delete(wsKey)
      }
    }
  }

  /** 创建一个绑定特定科研工作区的独立运行控制器。 */
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

    const orchestrator = new GreatwallOrchestrator({
      ctx: this.ctx,
      bridge,
      corePythonRoot: this.config.corePythonRoot,
      workspaceRoot,
      dataDir,
      parentAgent: opts.parentAgent || null,
      defaultAgentOptions: opts.defaultAgentOptions || this.config.defaultAgentOptions || {},
      protectedDirs,
    })

    const wsKey = workspaceRoot.toLowerCase()
    const controller = {
      workspaceRoot,
      corePythonRoot: this.config.corePythonRoot,
      bridge,
      orchestrator,
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
          epoch_id: norm.epochId,
          ...(norm.humanSignedAt ? { human_signed_at: norm.humanSignedAt } : {}),
        })
        // 仅在服务端落库成功后，才以服务端规范化结果更新 host.sharedInputPaths（支持空数组清空旧值，失败绝不污染）
        if (res?.ok) {
          orchestrator.host.sharedInputPaths = Array.isArray(res?.data?.shared_inputs_rel_paths)
            ? res.data.shared_inputs_rel_paths
            : norm.sharedInputsRelPaths
        }
        return res
      },
      async initEpoch(payload = {}) {
        return this.initParse0(payload)
      },
      async scheduleSnapshot(maxConcurrentWorkers = null) {
        return bridge.control('control_plane/schedule_snapshot', {
          workspace_root: workspaceRoot,
          ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
        })
      },
      async startBackground(runOpts = {}) {
        return orchestrator.startBackground(runOpts)
      },
      pauseBackground() {
        return orchestrator.pauseBackground()
      },
      async resumeBackground() {
        return orchestrator.resumeBackground()
      },
      async stopBackground(reason) {
        return orchestrator.stopBackground(reason)
      },
      async humanStop(note) {
        return orchestrator.humanStop(note)
      },
      async abortNode(nodeId, reason) {
        return orchestrator.abortNode(nodeId, reason)
      },
      async submitWorksTicket(ticketOpts) {
        return orchestrator.submitWorksTicket(ticketOpts)
      },
      async syncPublicRulings(refreshActiveWorktrees = false) {
        return orchestrator.syncPublicRulings(refreshActiveWorktrees)
      },
      async getControlStatus() {
        return orchestrator.getControlStatus()
      },
      async runUntilClosed(runOpts = {}) {
        return orchestrator.runUntilClosed(runOpts)
      },
      async dispose() {
        await orchestrator.disposeAll()
        await bridge.dispose()
        if (this._onDisposed) this._onDisposed()
      },
      _onDisposed: () => {
        this.controllers.delete(controller)
        if (this.activeControllersByWs.get(wsKey) === controller) {
          this.activeControllersByWs.delete(wsKey)
        }
      },
    }

    this.controllers.add(controller)
    this.activeControllersByWs.set(wsKey, controller)
    return controller
  }

  /** 获取或按需创建工作区控制器（仅在 `createIfMissing=true` 时创建）。 */
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

  /**
   * 统一控制动作执行入口（One Operation, Two Callers）。
   * @param {object} req
   * @param {'agent_tool' | 'human_ui'} req.caller
   * @param {string} req.action
   * @param {string} [req.workspaceRoot]
   * @param {any} [req.controller] 外部已定向匹配好的控制器（如 HTTP 面板）
   * @param {Record<string, any>} [req.payload]
   * @param {any} [req.callerAgent]
   */
  async execute({ caller = 'agent_tool', action, workspaceRoot = '', controller = null, payload = {}, callerAgent = null }) {
    const act = String(action || '').trim()
    const allowed = CALLER_ALLOWED_ACTIONS[caller]
    if (!allowed) {
      return { ok: false, action: act, callerSource: caller, error: `未知调用方身份: ${caller}` }
    }
    if (!allowed.includes(act)) {
      return {
        ok: false,
        action: act,
        callerSource: caller,
        error: `调用方 ${caller} 无权执行动作 ${act}`,
      }
    }

    const createIfMissing = caller === 'agent_tool' || act === 'init'
    const ctrl = controller || (workspaceRoot ? this.ensureController(workspaceRoot, { callerAgent, createIfMissing }) : null)
    if (!ctrl) {
      return {
        ok: false,
        action: act,
        callerSource: caller,
        error: '未找到目标工作区对应的活跃长城控制器。',
      }
    }

    const ws = ctrl.workspaceRoot
    const wsKey = ws.toLowerCase()
    const defaultReasonPrefix = caller === 'human_ui' ? 'UI_CONSOLE' : 'MCP'
    const defaultSource = caller === 'human_ui' ? 'ui_console' : 'main_controller'

    if (act === 'init') {
      return this._withWorkspaceLock(wsKey, async () => {
        const initPayload = normalizeInitParse0Payload(payload)
        const initRes = await ctrl.initParse0(initPayload)
        ctrl.orchestrator.telemetry?.recordEvent?.('control_parse0_init', {
          callerSource: caller,
          ok: Boolean(initRes?.ok),
          humanSigned: Boolean(initPayload.humanSignedAt),
        })
        return {
          ok: Boolean(initRes?.ok),
          action: act,
          callerSource: caller,
          init: initRes,
          status: await ctrl.orchestrator.getControlStatus(),
        }
      })
    }

    if (act === 'start') {
      return this._withWorkspaceLock(wsKey, async () => {
        const goalText = String(
          payload.goal_and_completion_md ?? payload.goalAndCompletionMd ?? payload.goal_md ?? payload.goalMd ?? '',
        )
        const hasInlineInit = Boolean(
          goalText ||
            (Array.isArray(payload.subquestions) && payload.subquestions.length) ||
            (Array.isArray(payload.required_questions) && payload.required_questions.length) ||
            (Array.isArray(payload.requiredQuestions) && payload.requiredQuestions.length),
        )
        // start 只在尚未启动且未签署 Parse 0 的首次冷启动时顺手立项；运行中或已签过契约时绝不借 start 悄悄覆写契约
        if (hasInlineInit && !ctrl.orchestrator.hasBackgroundTask()) {
          const preSnap = await ctrl.scheduleSnapshot()
          if (preSnap?.ok && !preSnap?.data?.parse0_signed) {
            const initRes = await ctrl.initParse0(normalizeInitParse0Payload(payload))
            if (!initRes?.ok) {
              return {
                ok: false,
                action: act,
                callerSource: caller,
                init: initRes,
                status: await ctrl.orchestrator.getControlStatus(),
              }
            }
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
        return { ok: Boolean(startRes?.started), action: act, callerSource: caller, ...startRes }
      })
    }

    if (act === 'pause') {
      return { ok: true, action: act, callerSource: caller, ...ctrl.orchestrator.pauseBackground() }
    }
    if (act === 'resume') {
      return { ok: true, action: act, callerSource: caller, ...(await ctrl.orchestrator.resumeBackground()) }
    }
    if (act === 'stop') {
      const stopRes = await ctrl.orchestrator.stopBackground(`${defaultReasonPrefix}_STOP`)
      await ctrl.bridge?.closeIdleChild?.()
      return { ok: true, action: act, callerSource: caller, ...stopRes }
    }
    if (act === 'human_stop') {
      const note = String(payload.note || payload.reason || `${defaultReasonPrefix}_HUMAN_STOP`)
      const res = await ctrl.orchestrator.humanStop(note, { callerSource: caller })
      return { ok: true, action: act, callerSource: caller, ...res }
    }
    if (act === 'abort_node') {
      const nodeId = String(payload.nodeId ?? payload.node_id ?? payload.targetId ?? '')
      const reason = String(payload.reason || `${defaultReasonPrefix}_ABORT_NODE`)
      const res = await ctrl.orchestrator.abortNode(nodeId, reason)
      return { ok: Boolean(res?.aborted), action: act, callerSource: caller, ...res }
    }
    if (act === 'submit_works_ticket') {
      const res = await ctrl.orchestrator.submitWorksTicket({
        questionId: String(payload.questionId ?? payload.question_id ?? 'ALL'),
        ticketType: String(payload.ticketType ?? payload.ticket_type ?? 'INSTRUMENT_ERROR'),
        instrumentId: (payload.instrumentId ?? payload.instrument_id)
          ? String(payload.instrumentId ?? payload.instrument_id)
          : null,
        description: String(payload.description || payload.reason || ''),
        source: String(payload.source || defaultSource),
      })
      return { ok: Boolean(res?.submitted), action: act, callerSource: caller, ...res }
    }
    if (act === 'sync_rulings') {
      const refresh = Boolean(payload.refreshActiveWorktrees ?? payload.refresh_active_worktrees)
      const res = await ctrl.orchestrator.syncPublicRulings(refresh)
      return { ok: Boolean(res?.synced), action: act, callerSource: caller, ...res }
    }
    if (act === 'inspect') {
      const nodeId = payload.nodeId ?? payload.node_id
      const insp = await ctrl.bridge.control('control_plane/ui_inspector', {
        workspace_root: ws,
        ...(nodeId ? { selected_node_id: String(nodeId) } : {}),
      })
      return {
        ok: Boolean(insp?.ok),
        action: act,
        callerSource: caller,
        inspector: insp?.data || null,
        error: insp?.ok ? null : (insp?.error || 'inspect failed'),
      }
    }
    if (act === 'status') {
      return {
        ok: true,
        action: act,
        callerSource: caller,
        ...(await ctrl.orchestrator.getControlStatus()),
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
