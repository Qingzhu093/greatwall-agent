/**
 * GreatWall v0.3 独立会话托管宿主机（AgentSessionHost）。
 *
 * v0.3 升级：
 * 1. 支持 DSH 0.2.2-rc.5 原生 `ctx.agents.resume(options)` 按确定性 sessionId 从磁盘恢复历史会话
 *    （用于 `gw-comp-<node_id>`、`gw-chair-<conference_id>`、`gw-chief-<ws_hash>`），无历史时平滑回退 `create`；
 * 2. 严守 7 条工程红线：保留 `_inheritParentPermissionState`（防 Windows 0xC0000142）、先 `handle.dispose()` 再 `archiveSession()`、
 *    探索者禁开 pruner；
 * 3. 集成 `runWithTransientRetry` 瞬态 429/5xx 原地退避与 `humanTakeover` 人类发言监测、温和 `injectPolicyChange`。
 * @module dsh-greatwall-v6up/agent_session_host
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { CANONICAL_ROLES, ROLE_EFFORT_MAP, formatNodeSessionTitle } from './prompts.js'
import { ROLE_TO_PRESET } from './presets.js'
import { syncLivePressureToDb } from './clock_and_turn_gap.js'
import { buildBlackboxTrajectorySummary } from './blackbox_projection.js'
import { mountCapabilitiesOnAgentSession } from './host/capability_mount.js'
import { runWithTransientRetry } from './runtime/transient_retry.js'
import {
  assertRequiredNativeTools,
  createAbortGraceRace,
  createUserTextMessage,
  extractLastAssistantText,
  extractModelBindingFromEvents,
  resolveAuthoritativeModelBinding,
  resolveEffectiveContextWindow,
} from './host/model_binding.js'

export {
  assertRequiredNativeTools,
  createAbortGraceRace,
  createUserTextMessage,
  extractLastAssistantText,
  extractModelBindingFromEvents,
  resolveAuthoritativeModelBinding,
  resolveEffectiveContextWindow,
}

export class AgentSessionHost {
  constructor({
    ctx,
    bridge,
    workspaceRoot,
    rolePrompts,
    parentAgent = null,
    protectedDirs = [],
    sharedInputPaths = [],
    defaultAgentOptions = {},
    effectiveContextWindow = 500_000,
    autoArchiveShortTx = true,
    humanTakeover = null,
    telemetry,
  }) {
    this.ctx = ctx
    this.bridge = bridge
    this.workspaceRoot = path.resolve(workspaceRoot)
    this.rolePrompts = rolePrompts
    this.parentAgent = parentAgent
    this.protectedDirs = protectedDirs
    this.sharedInputPaths = Array.isArray(sharedInputPaths) ? sharedInputPaths : []
    this.defaultAgentOptions = defaultAgentOptions
    this.effectiveContextWindow = Math.max(1, Number(effectiveContextWindow || 500_000))
    this.autoArchiveShortTx = Boolean(autoArchiveShortTx)
    this.humanTakeover = humanTakeover
    this.telemetry = telemetry

    this.liveSessions = new Map()
    this._sessionReadonlyFlags = new Map()
    this._setupHandledAgentIds = new Set()
    this._cachedToolSchemas = null
    this._latestGovernanceSessions = new Map()
    this._resumeListenerDisposer = this._installResumeAutoRemountListener()
  }

  setSessionReadonly(sessionId, isReadonly) {
    if (!sessionId) return
    this._sessionReadonlyFlags.set(sessionId, Boolean(isReadonly))
  }

  isSessionReadonly(sessionId) {
    return Boolean(this._sessionReadonlyFlags.get(sessionId))
  }

  /** 向在线探索会话温和热注入新口径裁决通知（绝不强杀在途旧口径分支）。 */
  injectPolicyChange(sessionId, noticeText) {
    const entry = this.liveSessions.get(sessionId)
    if (!entry?.handle?.agent) return { injected: false, reason: 'session_not_live' }
    const msg = createUserTextMessage(noticeText, 'user')
    this.humanTakeover?.markPluginMessage?.(sessionId, noticeText)
    if (typeof entry.handle.agent.inject === 'function') {
      entry.handle.agent.inject(msg)
      return { injected: true, method: 'inject' }
    }
    return { injected: false, reason: 'agent_inject_unavailable' }
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
            ? '⚠️ 注意：该节点短事务已结案或已封存，当前处于只读追问/审计模式（严禁写磁盘或篡改库状态）。'
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

  _canonicalizeForWorkspaceMatch(targetPath) {
    if (!targetPath) return ''
    let resolved = path.resolve(String(targetPath))
    try { resolved = fs.realpathSync(resolved) } catch {}
    const norm = path.normalize(resolved)
    return process.platform === 'win32' ? norm.toLowerCase() : norm
  }

  _isCrossCwd(sessionCwd) {
    if (!sessionCwd) return false
    return this._canonicalizeForWorkspaceMatch(sessionCwd) !== this._canonicalizeForWorkspaceMatch(this.workspaceRoot)
  }

  async attachAndNameSession(session, title, { crossCwd = null } = {}) {
    if (!session?.id) return
    const sessionCwd = session?.header?.cwd || ''
    const isCross = crossCwd !== null ? Boolean(crossCwd) : this._isCrossCwd(sessionCwd)
    if (!isCross) {
      try {
        const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
        const ws = await reg?.resolveByPath?.(this.workspaceRoot)
        if (ws && typeof ws.attachSession === 'function') await ws.attachSession(session.id)
      } catch (err) {
        this.telemetry?.recordEvent?.('session_attach_error', { sessionId: session.id, error: String(err?.message || err) })
      }
    }
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

  async archiveSession(sessionId) {
    if (!this.autoArchiveShortTx || !sessionId) return { archived: false, skipped: true }
    const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
    if (!reg || typeof reg.archiveSession !== 'function') {
      return { archived: false, skipped: true, reason: 'no_workspace_registry' }
    }
    try {
      await reg.archiveSession(sessionId)
    } catch (err) {
      const msg = String(err?.message || err)
      try {
        this.telemetry?.markArchiveFailed?.(sessionId, msg)
        this.telemetry?.recordEvent?.('session_archive_failed', { sessionId, error: msg })
      } catch {}
      return { archived: false, error: msg }
    }
    try {
      this.telemetry?.markArchived?.(sessionId, { readonly: true })
    } catch {}
    return { archived: true }
  }

  mountCapabilitiesOnAgent(agentCtx, agent, mountOpts) {
    return mountCapabilitiesOnAgentSession(
      {
        rootCtx: this.ctx,
        bridge: this.bridge,
        workspaceRoot: this.workspaceRoot,
        rolePrompts: this.rolePrompts,
        protectedDirs: this.protectedDirs,
        sharedInputPaths: this.sharedInputPaths,
        effectiveContextWindow: this.effectiveContextWindow,
        setSessionReadonly: (sid, flag) => this.setSessionReadonly(sid, flag),
        isSessionReadonly: (sid) => this.isSessionReadonly(sid),
      },
      agentCtx,
      agent,
      mountOpts,
    )
  }

  async _resolveSafeReasoningEffort(targetEffort, provider, model) {
    if (!targetEffort) return undefined
    const llmSvc = this.ctx?.get?.('llm')
    if (!llmSvc || typeof llmSvc.resolveModelInfo !== 'function' || !provider || !model) return targetEffort
    try {
      const info = await llmSvc.resolveModelInfo(provider, model)
      const efforts = info?.reasoning?.efforts
      if (!Array.isArray(efforts) || efforts.length === 0) return undefined
      const ids = efforts.map((e) => String(e?.id || '')).filter(Boolean)
      if (ids.includes(targetEffort)) return targetEffort
      if (targetEffort === 'medium') return ids.includes('high') ? 'high' : (ids.includes('low') ? 'low' : ids[0])
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
      if (!Array.isArray(events) && typeof this.ctx?.sessionQuery?.listEvents === 'function') {
        events = await this.ctx.sessionQuery.listEvents(sessionId)
      }
      if (!Array.isArray(events)) return null
      for (let i = events.length - 1; i >= 0; i--) {
        if (events[i]?.type === 'turn/end') return events[i]?.data?.reason || events[i]?.payload?.reason || { kind: 'stop' }
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

  _recordContentRefusal(sessionId, role, turnEndReason) {
    if (turnEndReason?.kind !== 'error' || turnEndReason.error?.code !== 'CONTENT_REFUSED') return
    this.telemetry.recordEvent('model_content_refused', { sessionId, role, code: turnEndReason.error.code })
  }

  /**
   * 不可触碰工程红线 1：同步父会话权限预设 / sandbox/mode，防 Windows headless 跑 pwsh 报 0xC0000142。
   */
  _inheritParentPermissionState(childSession) {
    const parentSession = this.parentAgent?.session
    if (!parentSession || !childSession || parentSession === childSession) return
    try {
      const permSvc =
        (typeof this.ctx?.get === 'function' ? this.ctx.get('permissionPresets') : null) ||
        (typeof this.ctx?.root?.get === 'function' ? this.ctx.root.get('permissionPresets') : null)
      if (permSvc && typeof permSvc.current === 'function' && typeof permSvc.set === 'function') {
        const parentPreset = permSvc.current(parentSession)
        const childPreset = permSvc.current(childSession)
        if (parentPreset && parentPreset !== 'custom' && parentPreset !== 'auto' && parentPreset !== childPreset) {
          permSvc.set(childSession, parentPreset)
          return
        }
      }
    } catch {}

    try {
      let parentMode = ''
      const sbSvc =
        (typeof this.ctx?.get === 'function' ? this.ctx.get('sandboxPolicy') : null) ||
        (typeof this.ctx?.root?.get === 'function' ? this.ctx.root.get('sandboxPolicy') : null)
      if (sbSvc && typeof sbSvc.resolve === 'function') {
        parentMode = String(sbSvc.resolve({ session: parentSession })?.mode || '').trim()
      }
      let parentApproval = ''
      if (typeof parentSession.snapshotEvents === 'function') {
        const evs = parentSession.snapshotEvents() || []
        for (let i = evs.length - 1; i >= 0; i--) {
          const ev = evs[i]
          if (!parentMode && ev?.type === 'sandbox/mode' && ev?.data?.mode) parentMode = String(ev.data.mode).trim()
          if (!parentApproval && ev?.type === 'approval/policy' && ev?.data?.policy) parentApproval = String(ev.data.policy).trim()
          if (parentMode && parentApproval) break
        }
      }
      if (parentMode && typeof childSession.append === 'function') {
        const curMode = sbSvc && typeof sbSvc.resolve === 'function' ? String(sbSvc.resolve({ session: childSession })?.mode || '').trim() : ''
        if (curMode !== parentMode) childSession.append('sandbox/mode', { mode: parentMode })
      }
      if (parentApproval && typeof childSession.append === 'function') {
        childSession.append('approval/policy', { policy: parentApproval })
      }
    } catch {}
  }

  /**
   * 优先通过 DSH RC5 原生 `ctx.agents.resume(sessionId)` 从磁盘恢复确定性会话；
   * 若会话尚未落盘或宿主无 `resume`，自动透明回退到 `spawnAndRunAgent`。
   */
  async resumeOrSpawnAgent(opts) {
    const sid = String(opts?.sessionId || '').trim()
    if (sid && this.liveSessions.has(sid) && !opts.allowedMcpOverride) {
      return this.continueAliveAgent(sid, opts.prompt, { signal: opts.signal })
    }
    return this.spawnAndRunAgent({ ...opts, preferResume: Boolean(sid) })
  }

  async spawnAndRunAgent({
    role,
    prompt,
    sessionId = '',
    nodeId = '',
    branchId = '',
    questionId = '',
    reviewId = '',
    deliveryId = '',
    cwd = '',
    sandboxAbsPath = '',
    taskContextText = '',
    extraContextProvider = null,
    allowedMcpOverride = null,
    agentOptions = {},
    keepAliveAfterIdle = false,
    uiLabel = '',
    shortTransaction = true,
    archiveOnComplete = null,
    preferResume = false,
    signal = null,
  }) {
    if (!CANONICAL_ROLES.includes(role)) throw new Error(`非法角色名: ${role}`)
    if (!this.ctx?.agents || typeof this.ctx.agents.create !== 'function') throw new Error('DSH ctx.agents.create 不可用')
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
    if (role === 'library_verifier' && !effSandbox) {
      throw new Error('BLIND_SANDBOX_REQUIRED: library_verifier 必须挂载独立空白盲审沙箱 sandboxAbsPath！')
    }
    const metaCwd = role === 'library_verifier'
      ? effSandbox
      : ((role === 'explorer' || role === 'lineage_companion') ? effWorktree : this.workspaceRoot)

    const sessionTitle = uiLabel || formatNodeSessionTitle(role, { questionId, branchId, nodeId })
    const turnSignals = []
    const nativeThresholds = []
    const cleanupFns = []
    let liveHandleRef = null
    let thresholdCancelled = false

    const mergedAgentOptions = { ...this.defaultAgentOptions, ...agentOptions }
    delete mergedAgentOptions.contextWindowTokens
    delete mergedAgentOptions.effectiveContextWindow
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
      try { resolved = await agentPresetsSvc.resolve(targetPreset) } catch {}
      if (!resolved) throw new Error(`角色 ${role} 所需的 Agent Preset "${targetPreset}" 无法在 agentPresets 中解析。`)
      if (resolved.broken) throw new Error(`角色 ${role} 所需的 Agent Preset "${targetPreset}" 损坏 (${resolved.broken})。`)
      resolvedPresetId = targetPreset
    }

    const setupFn = async (agentCtx, agent) => {
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
        extraContextProvider,
        allowedMcpOverride,
        cleanupFns,
        turnSignals,
        onNativeThresholdHit: (ev) => {
          nativeThresholds.push(ev)
          if (ev?.trigger === 'REFLECT_37' || ev?.trigger === 'HANDOFF_70' || ev?.trigger === 'NODE_TERMINATED') {
            thresholdCancelled = true
            try { liveHandleRef?.agent?.cancel?.({ kind: 'hook', reason: ev.trigger }) } catch {}
          }
        },
      })
      if (typeof agentPresetsSvc?.register === 'function') {
        const mountedNames = (agentCtx.tools?.schemas?.(agent) || []).map((s) => s.name)
        assertRequiredNativeTools(role, mountedNames, process.platform)
      }
    }

    const commonOpts = {
      sessionId: effSid,
      meta: { cwd: metaCwd, ...(resolvedPresetId ? { agentPreset: resolvedPresetId } : {}) },
      agentOptions: mergedAgentOptions,
      setup: setupFn,
    }

    let handle = null
    let resumedFromDisk = false
    if (preferResume && typeof this.ctx.agents.resume === 'function') {
      try {
        handle = await this.ctx.agents.resume(commonOpts)
        resumedFromDisk = true
      } catch {
        handle = null
      }
    }
    if (!handle) {
      handle = await this.ctx.agents.create(commonOpts)
    }

    liveHandleRef = handle
    this._inheritParentPermissionState(handle?.agent?.session)
    const crossCwd = this._isCrossCwd(metaCwd)
    this.telemetry.recordSessionStart({
      sessionId: effSid,
      role,
      questionId,
      nodeId,
      branchId,
      reviewId,
      deliveryId,
      worktreeAbsPath: effWorktree,
      sandboxAbsPath: effSandbox,
      workspaceRoot: this.workspaceRoot,
      crossCwd,
      shortTransaction,
      resumedFromDisk,
      title: sessionTitle,
    })

    await this.attachAndNameSession(handle.agent.session, sessionTitle, { crossCwd })

    if (role === 'explorer' && nodeId && this.humanTakeover) {
      const unwatch = this.humanTakeover.watchExplorerSession(nodeId, handle.agent.session)
      cleanupFns.push(unwatch)
    }

    if (!shortTransaction && ['logistics_coordinator', 'works_engineer', 'external_surveyor', 'library_chronicler', 'supervisory_committee'].includes(role)) {
      const prevSid = this._latestGovernanceSessions.get(role)
      if (prevSid && prevSid !== effSid && !this.liveSessions.has(prevSid)) {
        await this.archiveSession(prevSid)
      }
      this._latestGovernanceSessions.set(role, effSid)
    }

    let disposed = false
    const defaultShouldArchive = archiveOnComplete ?? shortTransaction
    const disposeAll = async (statusLabel = 'completed', reasonObj = null, { archive = null } = {}) => {
      if (disposed) return
      disposed = true
      this.liveSessions.delete(effSid)
      this._sessionReadonlyFlags.delete(effSid)
      this._setupHandledAgentIds.delete(effSid)
      // 严格先 dispose() 再 archiveSession()
      try { await handle.dispose() } catch {}
      for (const fn of cleanupFns.splice(0)) {
        try { await fn() } catch {}
      }
      const wantArchive = archive !== null ? Boolean(archive) : Boolean(defaultShouldArchive)
      let archRes = { archived: false, error: null }
      if (wantArchive) archRes = await this.archiveSession(effSid)
      this.telemetry.recordSessionEnd({
        sessionId: effSid,
        status: statusLabel,
        turnEndReason: reasonObj,
        archived: Boolean(archRes?.archived),
        archiveError: archRes?.error || null,
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

    if (prompt) {
      await this._runFollowupTurn(effSid, handle, prompt, signal, role)
    }

    if (signal?.aborted) {
      await disposeAll('aborted', { kind: 'aborted' })
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }

    const turnEndReason = await this.inspectLastTurnEndReason(effSid, handle?.agent?.session)
    this._recordContentRefusal(effSid, role, turnEndReason)
    const isAbnormalEnd = Boolean(!thresholdCancelled && turnEndReason && (turnEndReason.kind === 'error' || turnEndReason.kind === 'aborted'))
    thresholdCancelled = false

    if (role === 'explorer' && nodeId) {
      await syncLivePressureToDb(this.ctx, handle.agent, this.bridge, this.workspaceRoot, nodeId, this.effectiveContextWindow)
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
      resumedFromDisk,
      turnSignals,
      nativeThresholds,
      turnEndReason,
      isAbnormalEnd: Boolean(isAbnormalEnd),
      blackboxSummary,
      lastAssistantText,
      handle: keepAliveAfterIdle ? handle : null,
      dispose: (st, rs, opts) => disposeAll(st, rs, opts),
    }
  }

  async _runFollowupTurn(sessionId, handle, promptText, signal, role) {
    const onAbortSignal = () => {
      try { handle.agent.cancel?.({ kind: 'parent' }) } catch {}
    }
    if (signal) {
      if (signal.aborted) onAbortSignal()
      else signal.addEventListener('abort', onAbortSignal, { once: true })
    }
    try {
      await runWithTransientRetry(
        async () => {
          if (signal?.aborted) return
          this.humanTakeover?.markPluginMessage?.(sessionId, promptText)
          handle.agent.followup(createUserTextMessage(promptText, 'user'))
          await createAbortGraceRace(signal, handle.agent.whenIdle())
          const reason = await this.inspectLastTurnEndReason(sessionId, handle?.agent?.session)
          if (reason?.kind === 'error' && reason?.error) {
            const err = new Error(String(reason.error.message || reason.error.code || 'turn_error'))
            err.code = reason.error.code
            err.status = reason.error.status
            throw err
          }
        },
        {
          signal,
          onRetry: ({ attempt, delayMs, error }) => {
            this.telemetry?.recordEvent?.('transient_provider_retry', { sessionId, role, attempt, delayMs, error })
          },
        },
      ).catch(() => {
        // 非瞬态或耗尽重试后交由上层 inspectLastTurnEndReason 统一处置
      })
    } finally {
      if (signal) signal.removeEventListener('abort', onAbortSignal)
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
    await this._runFollowupTurn(sessionId, entry.handle, promptText, signal, entry.role)
    if (signal?.aborted) {
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      throw err
    }
    if (entry.role === 'explorer' && entry.nodeId) {
      await syncLivePressureToDb(this.ctx, entry.handle.agent, this.bridge, this.workspaceRoot, entry.nodeId, this.effectiveContextWindow)
    }
    const turnEndReason = await this.inspectLastTurnEndReason(sessionId, entry.handle?.agent?.session)
    this._recordContentRefusal(sessionId, entry.role, turnEndReason)
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
    try { this._resumeListenerDisposer?.() } catch {}
    const entries = [...this.liveSessions.values()]
    if (entries.length > 0) {
      await Promise.allSettled(entries.map((entry) => entry.handleDispose('disposed')))
    }
    this._sessionReadonlyFlags.clear()
  }
}
