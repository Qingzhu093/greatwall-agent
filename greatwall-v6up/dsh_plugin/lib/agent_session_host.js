/**
 * 长城 V6-Up (v3.0) 独立会话托管宿主机（AgentSessionHost）：
 *
 * 核心能力：
 * 1. 基于 6 套专用 Preset 创建同工作区独立会话；`library_verifier` 挂载独立空白盲审沙箱 `sandboxAbsPath`；
 * 2. 平台感知原生工具挂载强断言 (`win32->pwsh`, 非 `win32->bash`，覆盖 `explorer`、`works_engineer`、`library_verifier`)；
 * 3. `setSessionReadonly(sessionId, flag)` 支持 70% 两步清醒交接期间将在线探索者瞬时锁为只读文本收官态；
 * 4. 完整支持单节点伴随会话保活 (`keepAliveAfterIdle`)、冷恢复自动重挂窄工具与沙箱 Guard、短事务归档。
 * @module dsh-greatwall-v6up/agent_session_host
 */
import crypto from 'node:crypto'
import path from 'node:path'
import {
  CANONICAL_ROLES,
  ROLE_EFFORT_MAP,
  ROLE_MCP_TOOLS,
  formatNodeSessionTitle,
  resolvePlatformAllowedTools,
  resolvePlatformShellTool,
} from './prompts.js'
import { ROLE_TO_PRESET, registerPresetsOnRegistry } from './presets.js'
import { installRoleSandboxGuard } from './read_isolated_sandbox.js'
import { installFactLogMiddleware } from './fact_log_middleware.js'
import {
  installLiveClockObservers,
  registerScopedMcpTools,
  syncLivePressureToDb,
} from './clock_and_turn_gap.js'
import { buildBlackboxTrajectorySummary } from './blackbox_projection.js'

export function createUserTextMessage(text, label = 'user') {
  return {
    id: crypto.randomUUID(),
    role: 'user',
    content: [{ type: 'text', text: String(text) }],
    source: { kind: label },
  }
}

export function createAbortGraceRace(signal, workPromise) {
  if (!signal) return workPromise
  if (signal.aborted) {
    const err = new Error('GREATWALL_RUN_ABORTED')
    err.code = 'GREATWALL_RUN_ABORTED'
    return Promise.reject(err)
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      reject(err)
    }
    signal.addEventListener('abort', onAbort, { once: true })
    workPromise.then(
      (val) => {
        signal.removeEventListener('abort', onAbort)
        resolve(val)
      },
      (err) => {
        signal.removeEventListener('abort', onAbort)
        reject(err)
      },
    )
  })
}

export function extractLastAssistantText(surfaceSnap) {
  const msgs = surfaceSnap?.surface?.messages || surfaceSnap?.messages || []
  if (!Array.isArray(msgs)) return ''
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (!m || m.role !== 'assistant') continue
    if (typeof m.content === 'string' && m.content.trim()) return m.content.trim()
    if (Array.isArray(m.content)) {
      const texts = m.content
        .filter((b) => b?.type === 'text' && typeof b.text === 'string' && b.text.trim())
        .map((b) => b.text.trim())
      if (texts.length) return texts.join('\n')
    }
  }
  return ''
}

/**
 * 平台感知原生工具挂载强断言（纯函数，兼供单测校验）。
 * @param {string} role
 * @param {Iterable<string>} mountedToolNames
 * @param {string} [platform]
 */
export function assertRequiredNativeTools(role, mountedToolNames, platform = process.platform) {
  const mounted = new Set(mountedToolNames || [])
  const expectedShell = resolvePlatformShellTool(platform)
  const missing = []

  if (role === 'explorer' || role === 'works_engineer') {
    for (const req of ['read', 'write', expectedShell]) {
      if (!mounted.has(req)) missing.push(req)
    }
  } else if (role === 'library_verifier') {
    for (const req of ['read', expectedShell]) {
      if (!mounted.has(req)) missing.push(req)
    }
    if (mounted.has('write') || mounted.has('edit')) {
      throw new Error(`角色 library_verifier 严禁挂载写工具 (write/edit)，当前已挂载: ${[...mounted].join(', ')}`)
    }
  } else if (role === 'logistics_coordinator' || role === 'supervisory_committee') {
    const forbidden = ['read', 'write', 'edit', 'pwsh', 'bash', 'web_search', 'web_fetch'].filter((n) => mounted.has(n))
    if (forbidden.length > 0) {
      throw new Error(`纯 DB 治理角色 ${role} 严禁挂载原生工具: ${forbidden.join(', ')}`)
    }
  }

  if (missing.length > 0) {
    throw new Error(
      `角色 ${role} (platform=${platform}) 缺少关键原生工具: ${missing.join(', ')}（当前仅有: ${[...mounted].join(', ')}）`,
    )
  }
}

export class AgentSessionHost {
  constructor({
    ctx,
    bridge,
    workspaceRoot,
    rolePrompts,
    protectedDirs = [],
    defaultAgentOptions = {},
    autoArchiveShortTx = true,
    telemetry,
  }) {
    this.ctx = ctx
    this.bridge = bridge
    this.workspaceRoot = path.resolve(workspaceRoot)
    this.rolePrompts = rolePrompts
    this.protectedDirs = protectedDirs
    this.defaultAgentOptions = defaultAgentOptions
    this.autoArchiveShortTx = Boolean(autoArchiveShortTx)
    this.telemetry = telemetry

    /** @type {Map<string, any>} */
    this.liveSessions = new Map()
    /** @type {Map<string, boolean>} */
    this._sessionReadonlyFlags = new Map()
    /** @type {Set<string>} */
    this._setupHandledAgentIds = new Set()
    /** @type {Array<object> | null} */
    this._cachedToolSchemas = null
    /** @type {Map<string, string>} */
    this._latestGovernanceSessions = new Map()

    this._resumeListenerDisposer = this._installResumeAutoRemountListener()
  }

  /** 动态切换指定在线会话的只读保护标志（用于 70% 探索者最后一轮亲笔遗嘱只读收官）。 */
  setSessionReadonly(sessionId, isReadonly) {
    if (!sessionId) return
    this._sessionReadonlyFlags.set(sessionId, Boolean(isReadonly))
  }

  isSessionReadonly(sessionId) {
    return Boolean(this._sessionReadonlyFlags.get(sessionId))
  }

  _installResumeAutoRemountListener() {
    if (!this.ctx?.on) return () => {}
    return this.ctx.on('agent/created', ({ agent }) => {
      try {
        if (!agent?.session || !agent?.ctx) return
        if (this._setupHandledAgentIds.has(agent.id)) return
        const ident = this._readGreatwallIdentityFromSession(agent.session)
        if (!ident || !ident.role) return
        if (ident.workspaceRoot && path.resolve(ident.workspaceRoot) !== this.workspaceRoot) return
        const settled = this._isSessionSettled(agent.session)
        const cachedSchemas = this._cachedToolSchemas || []
        const cleanups = []
        this.mountCapabilitiesOnAgent(agent.ctx, agent, {
          role: ident.role,
          nodeId: ident.nodeId || '',
          cwd: ident.worktreeAbsPath || this.workspaceRoot,
          sandboxAbsPath: ident.sandboxAbsPath || '',
          toolSchemas: cachedSchemas,
          readonly: settled || Boolean(ident.readonly),
          taskContextText: settled
            ? '⚠️ 注意：该节点短事务已结案，当前处于冷恢复只读追问/审计模式（严禁写磁盘或篡改库状态）。'
            : '',
          cleanupFns: cleanups,
          turnSignals: [],
        })
        agent.ctx.effect?.(() => () => {
          for (const fn of cleanups.splice(0)) {
            try { fn() } catch {}
          }
        }, 'greatwall:resumeCleanup')
      } catch {}
    })
  }

  _readGreatwallIdentityFromSession(session) {
    return this.telemetry?.getSessionIdentity?.(session?.id) || null
  }

  _isSessionSettled(session) {
    const ident = this.telemetry?.getSessionIdentity?.(session?.id)
    return Boolean(ident && (ident.readonly === true || (ident.shortTransaction === true && ident.archived === true)))
  }

  async attachAndNameSession(session, title) {
    if (!session?.id) return
    try {
      const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
      const ws = await reg?.resolveByPath?.(this.workspaceRoot)
      await ws?.attachSession?.(session.id)
    } catch {}
    if (title) {
      try {
        const titleSvc = typeof this.ctx?.get === 'function' ? this.ctx.get('sessionTitle') : this.ctx?.sessionTitle
        if (typeof titleSvc?.rename === 'function') {
          await titleSvc.rename(session, title)
        } else if (typeof session.append === 'function') {
          session.append('session/title', { title, messageSeqs: [], source: { kind: 'user' } })
        }
      } catch {}
    }
  }

  async archiveSession(sessionId, _session = null) {
    if (!this.autoArchiveShortTx || !sessionId) return
    try {
      const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
      await reg?.archiveSession?.(sessionId)
    } catch {}
    try {
      this.telemetry.markArchived(sessionId, { readonly: true })
    } catch {}
  }

  mountCapabilitiesOnAgent(
    agentCtx,
    agent,
    {
      role,
      nodeId = '',
      cwd = '',
      sandboxAbsPath = '',
      toolSchemas = [],
      taskContextText = '',
      readonly = false,
      cleanupFns = [],
      turnSignals = [],
      onNativeThresholdHit = null,
    },
  ) {
    const allowNative = readonly
      ? (role === 'logistics_coordinator' || role === 'supervisory_committee' ? [] : ['read', 'glob', 'grep'])
      : resolvePlatformAllowedTools(role, process.platform)
    const mcpToolNames = readonly ? [] : (ROLE_MCP_TOOLS[role] || [])

    if (typeof agentCtx.tools?.presentAs === 'function') {
      cleanupFns.push(agentCtx.tools.presentAs('native'))
    }

    const inherited = agentCtx.tools?.schemas?.(agent)?.map((s) => s.name) || []
    if (inherited.length > 0) {
      if (allowNative.length === 0) {
        agentCtx.tools.restrict({ deny: inherited })
      } else {
        const allowSet = new Set(allowNative)
        const matchedAllow = inherited.filter((n) => allowSet.has(n))
        if (matchedAllow.length > 0) {
          agentCtx.tools.restrict({ allow: matchedAllow })
        } else {
          agentCtx.tools.restrict({ deny: inherited })
        }
      }
    }

    const effWorktree = (role === 'explorer' || role === 'lineage_companion') && cwd ? path.resolve(cwd) : this.workspaceRoot
    const effSandbox = role === 'library_verifier' && sandboxAbsPath ? path.resolve(sandboxAbsPath) : ''
    this._sessionReadonlyFlags.set(agent.id, Boolean(readonly))

    cleanupFns.push(
      installRoleSandboxGuard(agentCtx, {
        role,
        sessionId: agent.id,
        nodeId,
        workspaceRoot: this.workspaceRoot,
        worktreeAbsPath: effWorktree,
        sandboxAbsPath: effSandbox,
        protectedDirs: this.protectedDirs,
        readonly: () => Boolean(readonly) || this.isSessionReadonly(agent.id),
        bridge: this.bridge,
      }),
    )

    cleanupFns.push(
      installFactLogMiddleware(agentCtx, {
        workspaceRoot: this.workspaceRoot,
        role,
        sessionId: agent.id,
        nodeId,
        bridge: this.bridge,
      }),
    )

    cleanupFns.push(
      installLiveClockObservers({
        rootCtx: this.ctx,
        agentCtx,
        agent,
        bridge: this.bridge,
        workspaceRoot: this.workspaceRoot,
        nodeId,
        role,
        onNativeThresholdHit,
      }),
    )

    const rolePromptText = this.rolePrompts[role] || `# Role: ${role}`
    cleanupFns.push(
      agentCtx.systemPrompt.section({
        name: `greatwall:contract:${role}`,
        order: 10,
        text: rolePromptText,
      }),
    )

    if (taskContextText) {
      cleanupFns.push(
        agentCtx.systemPrompt.context({
          name: `greatwall:task:${agent.id}`,
          order: 20,
          text: taskContextText,
        }),
      )
    }

    cleanupFns.push(
      agentCtx.on('system-prompt/assemble', async (assembly, _assembleCtx, next) => {
        const out = await next()
        if (Array.isArray(out?.sections)) {
          out.sections = out.sections.filter((sec) => {
            const nm = String(sec?.name || '')
            return (
              !nm.startsWith('deployment:persona') &&
              nm !== 'tool-fs:guidance' &&
              nm !== 'coding-agent' &&
              nm !== 'agent-instructions' &&
              !nm.startsWith('subagent:')
            )
          })
        }
        return out
      }),
    )

    if (mcpToolNames.length > 0 && toolSchemas.length > 0) {
      cleanupFns.push(
        registerScopedMcpTools({
          rootCtx: this.ctx,
          agentCtx,
          agent,
          bridge: this.bridge,
          toolSchemas,
          allowedToolNames: mcpToolNames,
          role,
          workspaceRoot: this.workspaceRoot,
          nodeId,
          onTurnSignal: (sig) => turnSignals.push(sig),
        }),
      )
    }
  }

  async _resolveSafeReasoningEffort(targetEffort, provider, model) {
    if (!targetEffort) return undefined
    const llmSvc = this.ctx?.get?.('llm')
    if (!llmSvc || typeof llmSvc.resolveModelInfo !== 'function' || !provider || !model) {
      return targetEffort
    }
    try {
      const info = await llmSvc.resolveModelInfo(provider, model)
      const efforts = info?.reasoning?.efforts
      if (!Array.isArray(efforts) || efforts.length === 0) return undefined
      const ids = efforts.map((e) => String(e?.id || '')).filter(Boolean)
      if (ids.includes(targetEffort)) return targetEffort
      if (targetEffort === 'medium') {
        if (ids.includes('high')) return 'high'
        if (ids.includes('low')) return 'low'
      }
      if (targetEffort === 'high') return ids[ids.length - 1]
      return ids[0]
    } catch {
      return targetEffort
    }
  }

  async inspectLastTurnEndReason(sessionId, session = null) {
    try {
      const liveSess = session || this.ctx?.sessions?.get?.(sessionId)
      let events = typeof liveSess?.snapshotEvents === 'function' ? liveSess.snapshotEvents() : null
      if (!Array.isArray(events)) {
        const sq = this.ctx?.sessionQuery
        if (sq && typeof sq.listEvents === 'function') {
          events = await sq.listEvents(sessionId)
        }
      }
      if (!Array.isArray(events)) return null
      for (let i = events.length - 1; i >= 0; i--) {
        const ev = events[i]
        if (ev?.type === 'turn/end') {
          return ev?.data?.reason || ev?.payload?.reason || { kind: 'stop' }
        }
      }
    } catch {}
    return null
  }

  async _readLastAssistantText(sessionId, session = null) {
    try {
      const liveSess = session || this.ctx?.sessions?.get?.(sessionId)
      if (typeof liveSess?.deriveMessages === 'function') {
        const txt = extractLastAssistantText({ messages: liveSess.deriveMessages() })
        if (txt) return txt
      }
      const surf = await this.ctx?.sessionQuery?.readSurface?.(sessionId)
      return extractLastAssistantText(surf)
    } catch {}
    return ''
  }

  async spawnAndRunAgent({
    role,
    prompt,
    sessionId = '',
    nodeId = '',
    branchId = '',
    questionId = '',
    cwd = '',
    sandboxAbsPath = '',
    taskContextText = '',
    agentOptions = {},
    keepAliveAfterIdle = false,
    uiLabel = '',
    shortTransaction = true,
    archiveOnComplete = null,
    signal = null,
  }) {
    if (!CANONICAL_ROLES.includes(role)) {
      throw new Error(`非法角色名: ${role}`)
    }
    if (!this.ctx?.agents || typeof this.ctx.agents.create !== 'function') {
      throw new Error('DSH ctx.agents.create 不可用')
    }
    if (signal?.aborted) {
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }

    const toolSchemas = await this.bridge.listTools()
    this._cachedToolSchemas = toolSchemas

    const effSid = sessionId || `gw_${role}_${crypto.randomUUID().slice(0, 8)}`
    const effWorktree = (role === 'explorer' || role === 'lineage_companion') && cwd ? path.resolve(cwd) : this.workspaceRoot
    const effSandbox = role === 'library_verifier' && sandboxAbsPath ? path.resolve(sandboxAbsPath) : ''
    const metaCwd = role === 'library_verifier' && effSandbox
      ? effSandbox
      : ((role === 'explorer' || role === 'lineage_companion') ? effWorktree : this.workspaceRoot)

    const sessionTitle = uiLabel || formatNodeSessionTitle(role, { questionId, branchId, nodeId })
    const turnSignals = []
    const nativeThresholds = []
    const cleanupFns = []
    let liveHandleRef = null
    let thresholdCancelled = false

    const mergedAgentOptions = { ...this.defaultAgentOptions, ...agentOptions }
    const effEffort = await this._resolveSafeReasoningEffort(
      agentOptions?.reasoningEffort || ROLE_EFFORT_MAP[role],
      mergedAgentOptions.provider,
      mergedAgentOptions.model,
    )
    if (effEffort) mergedAgentOptions.reasoningEffort = effEffort
    else delete mergedAgentOptions.reasoningEffort

    const agentPresetsSvc = (typeof this.ctx?.get === 'function' ? this.ctx.get('agentPresets') : null)
      || (typeof this.ctx?.root?.get === 'function' ? this.ctx.root.get('agentPresets') : null)
    const targetPreset = ROLE_TO_PRESET[role]
    let resolvedPresetId = null
    if (agentPresetsSvc && targetPreset) {
      let resolved = null
      try {
        resolved = await agentPresetsSvc.resolve(targetPreset)
      } catch {}
      if (!resolved && typeof agentPresetsSvc.register === 'function') {
        await registerPresetsOnRegistry(this.ctx, agentPresetsSvc, { targetId: targetPreset })
        resolved = await agentPresetsSvc.resolve(targetPreset)
      }
      if (!resolved) {
        throw new Error(`角色 ${role} 所需的 Agent Preset "${targetPreset}" 无法在 agentPresets 中解析，禁止裸奔启动。`)
      }
      if (resolved.broken) {
        throw new Error(`角色 ${role} 所需的 Agent Preset "${targetPreset}" 损坏 (${resolved.broken})，请检查 Cordis 插件声明。`)
      }
      resolvedPresetId = targetPreset
    }

    const createOpts = {
      sessionId: effSid,
      meta: {
        cwd: metaCwd,
        ...(resolvedPresetId ? { agentPreset: resolvedPresetId } : {}),
      },
      agentOptions: mergedAgentOptions,
      setup: async (agentCtx, agent) => {
        this._setupHandledAgentIds.add(agent.id)
        const scopedPresets = (typeof agentCtx?.get === 'function' ? agentCtx.get('agentPresets') : null) || agentPresetsSvc
        if (resolvedPresetId && scopedPresets && typeof scopedPresets.mount === 'function') {
          await scopedPresets.mount(agentCtx, resolvedPresetId)
        }
        this.mountCapabilitiesOnAgent(agentCtx, agent, {
          role,
          nodeId,
          cwd: effWorktree,
          sandboxAbsPath: effSandbox,
          toolSchemas,
          taskContextText,
          cleanupFns,
          turnSignals,
          onNativeThresholdHit: (ev) => {
            nativeThresholds.push(ev)
            // 纯原生工具长回合跨过 37% / 70% 时主动安全收束当前 Turn，防止一路冲过头
            if (ev?.trigger === 'REFLECT_37' || ev?.trigger === 'HANDOFF_70') {
              thresholdCancelled = true
              try {
                liveHandleRef?.agent?.cancel?.({ kind: 'greatwall_threshold' })
              } catch {}
            }
          },
        })
        if (typeof agentPresetsSvc?.register === 'function') {
          const mountedNames = (agentCtx.tools?.schemas?.(agent) || []).map((s) => s.name)
          assertRequiredNativeTools(role, mountedNames, process.platform)
        }
      },
    }

    const handle = await this.ctx.agents.create(createOpts)
    liveHandleRef = handle
    this.telemetry.recordSessionStart({
      sessionId: effSid,
      role,
      questionId,
      nodeId,
      branchId,
      worktreeAbsPath: effWorktree,
      sandboxAbsPath: effSandbox,
      workspaceRoot: this.workspaceRoot,
      shortTransaction,
      title: sessionTitle,
    })

    await this.attachAndNameSession(handle.agent.session, sessionTitle)

    if (!shortTransaction && ['logistics_coordinator', 'works_engineer', 'library_surveyor', 'supervisory_committee'].includes(role)) {
      const prevSid = this._latestGovernanceSessions.get(role)
      if (prevSid && prevSid !== effSid && !this.liveSessions.has(prevSid)) {
        await this.archiveSession(prevSid)
      }
      this._latestGovernanceSessions.set(role, effSid)
    }

    let disposed = false
    const shouldArchive = archiveOnComplete ?? shortTransaction
    const disposeAll = async (statusLabel = 'completed', reasonObj = null) => {
      if (disposed) return
      disposed = true
      this.liveSessions.delete(effSid)
      this._sessionReadonlyFlags.delete(effSid)
      this._setupHandledAgentIds.delete(effSid)
      const sessionRef = handle?.agent?.session
      if (shouldArchive) {
        await this.archiveSession(effSid, sessionRef)
      }
      try {
        await handle.dispose()
      } catch {}
      for (const fn of cleanupFns.splice(0)) {
        try {
          await fn()
        } catch {}
      }
      this.telemetry.recordSessionEnd({
        sessionId: effSid,
        status: statusLabel,
        turnEndReason: reasonObj,
        archived: shouldArchive,
      })
    }

    this.liveSessions.set(effSid, {
      handle,
      role,
      nodeId,
      questionId,
      uiLabel: sessionTitle,
      startedAt: Date.now(),
      turnSignals,
      nativeThresholds,
      consumeThresholdCancel: () => {
        const hit = thresholdCancelled
        thresholdCancelled = false
        return hit
      },
      handleDispose: disposeAll,
    })

    const onAbortSignal = () => {
      try {
        handle.agent.cancel?.({ kind: 'parent' })
      } catch {}
    }
    if (signal) {
      if (signal.aborted) onAbortSignal()
      else signal.addEventListener('abort', onAbortSignal, { once: true })
    }

    try {
      if (!signal?.aborted) {
        handle.agent.followup(createUserTextMessage(prompt, 'user'))
        await createAbortGraceRace(signal, handle.agent.whenIdle())
      }
    } finally {
      if (signal) signal.removeEventListener('abort', onAbortSignal)
    }

    if (signal?.aborted) {
      await disposeAll('aborted', { kind: 'aborted' })
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }

    const turnEndReason = await this.inspectLastTurnEndReason(effSid, handle?.agent?.session)
    const isAbnormalEnd = Boolean(
      !thresholdCancelled && turnEndReason && (turnEndReason.kind === 'error' || turnEndReason.kind === 'aborted'),
    )
    thresholdCancelled = false

    if (role === 'explorer' && nodeId) {
      await syncLivePressureToDb(this.ctx, handle.agent, this.bridge, this.workspaceRoot, nodeId)
    }

    const blackboxSummary = role === 'explorer' ? await buildBlackboxTrajectorySummary(this.ctx, effSid, 4800, handle?.agent?.session) : ''
    const lastAssistantText = await this._readLastAssistantText(effSid, handle?.agent?.session)

    if (!keepAliveAfterIdle) {
      await disposeAll(isAbnormalEnd ? 'interrupted_unclaimed' : 'completed', turnEndReason)
    }

    return {
      sessionId: effSid,
      role,
      nodeId,
      turnSignals,
      nativeThresholds,
      turnEndReason,
      isAbnormalEnd: Boolean(isAbnormalEnd),
      blackboxSummary,
      lastAssistantText,
      handle: keepAliveAfterIdle ? handle : null,
      dispose: (st, rs) => disposeAll(st, rs),
    }
  }

  async continueAliveAgent(sessionId, promptText, { signal = null } = {}) {
    const entry = this.liveSessions.get(sessionId)
    if (!entry) throw new Error(`会话 ${sessionId} 未处于保活状态`)
    if (signal?.aborted) {
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }
    const onAbort = () => {
      try {
        entry.handle?.agent?.cancel?.({ kind: 'parent' })
      } catch {}
    }
    if (signal) signal.addEventListener('abort', onAbort, { once: true })

    try {
      entry.handle.agent.followup(createUserTextMessage(promptText, 'user'))
      await createAbortGraceRace(signal, entry.handle.agent.whenIdle())
    } finally {
      if (signal) signal.removeEventListener('abort', onAbort)
    }

    if (signal?.aborted) {
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }
    if (entry.role === 'explorer' && entry.nodeId) {
      await syncLivePressureToDb(this.ctx, entry.handle.agent, this.bridge, this.workspaceRoot, entry.nodeId)
    }
    const turnEndReason = await this.inspectLastTurnEndReason(sessionId, entry.handle?.agent?.session)
    const wasThresholdCancel = Boolean(entry.consumeThresholdCancel?.())
    const blackbox = entry.role === 'explorer' ? await buildBlackboxTrajectorySummary(this.ctx, sessionId, 4800, entry.handle?.agent?.session) : ''
    const lastAssistantText = await this._readLastAssistantText(sessionId, entry.handle?.agent?.session)
    return {
      blackboxSummary: blackbox,
      lastAssistantText,
      turnSignals: entry.turnSignals || [],
      nativeThresholds: entry.nativeThresholds || [],
      turnEndReason,
      isAbnormalEnd: Boolean(!wasThresholdCancel && turnEndReason && (turnEndReason.kind === 'error' || turnEndReason.kind === 'aborted')),
    }
  }

  async disposeAllSessions() {
    try {
      this._resumeListenerDisposer?.()
    } catch {}
    const entries = [...this.liveSessions.values()]
    if (entries.length > 0) {
      await Promise.allSettled(entries.map((entry) => entry.handleDispose('disposed')))
    }
    this._sessionReadonlyFlags.clear()
  }
}
