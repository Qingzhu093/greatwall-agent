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
import fs from 'node:fs'
import path from 'node:path'
import {
  CANONICAL_ROLES,
  ROLE_EFFORT_MAP,
  formatNodeSessionTitle,
} from './prompts.js'
import { ROLE_TO_PRESET } from './presets.js'
import { syncLivePressureToDb } from './clock_and_turn_gap.js'
import { buildBlackboxTrajectorySummary } from './blackbox_projection.js'
import { mountCapabilitiesOnAgentSession } from './host/capability_mount.js'
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

  _canonicalizeForWorkspaceMatch(targetPath) {
    if (!targetPath) return ''
    let resolved = path.resolve(String(targetPath))
    try {
      resolved = fs.realpathSync(resolved)
    } catch {}
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
    // RC5 dsh-workspace 严格校验 realpathNormalize(header.cwd) === workspace.path；跨 cwd 子会话预期跳过 attachSession，
    // 同目录会话挂载失败则明确记遥测，不再静默吞错。
    if (!isCross) {
      try {
        const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
        const ws = await reg?.resolveByPath?.(this.workspaceRoot)
        if (ws && typeof ws.attachSession === 'function') {
          await ws.attachSession(session.id)
        }
      } catch (err) {
        this.telemetry?.recordEvent?.('session_attach_error', {
          sessionId: session.id,
          error: String(err?.message || err),
        })
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

  async archiveSession(sessionId, _session = null) {
    if (!this.autoArchiveShortTx || !sessionId) return { archived: false, skipped: true }
    const reg = typeof this.ctx?.get === 'function' ? this.ctx.get('workspaceRegistry') : this.ctx?.workspaceRegistry
    if (!reg || typeof reg.archiveSession !== 'function') {
      return { archived: false, skipped: true, reason: 'no_workspace_registry' }
    }
    try {
      // RC5 dsh-workspace.archiveSession 操作全局归档集，同目录与跨 cwd 子会话均直接调用原生归档
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

  _recordContentRefusal(sessionId, role, turnEndReason) {
    if (turnEndReason?.kind !== 'error' || turnEndReason.error?.code !== 'CONTENT_REFUSED') return
    this.telemetry.recordEvent('model_content_refused', {
      sessionId,
      role,
      code: turnEndReason.error.code,
      message: '模型提供方拒绝了本轮请求。',
    })
  }

  /**
   * 仅当主控父会话已获人类显式授权（例如桌面端 defaultPreset 或 CLI `--permission-mode danger-full-access`）时，
   * 将父会话的权限预设 / `sandbox/mode` 同步给新创建的子会话，避免 headless 下子会话跌落 `workspace-write`
   * 触发 Windows ACL 受限令牌跑 `pwsh` 报 `0xC0000142`（同时我方双向沙箱 Guard 仍 100% 同步拦截越界访问）。
   * @param {any} childSession
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
        if (
          parentPreset &&
          parentPreset !== 'custom' &&
          parentPreset !== 'auto' &&
          parentPreset !== childPreset
        ) {
          permSvc.set(childSession, parentPreset)
          return
        }
      }
    } catch {}

    // 回退路径：直接通过 DSH 原生 sandboxPolicy / 会话事件流同步 sandbox/mode 与 approval/policy
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
          if (!parentMode && ev?.type === 'sandbox/mode' && ev?.data?.mode) {
            parentMode = String(ev.data.mode).trim()
          }
          if (!parentApproval && ev?.type === 'approval/policy' && ev?.data?.policy) {
            parentApproval = String(ev.data.policy).trim()
          }
          if (parentMode && parentApproval) break
        }
      }
      if (parentMode && typeof childSession.append === 'function') {
        const curMode = sbSvc && typeof sbSvc.resolve === 'function'
          ? String(sbSvc.resolve({ session: childSession })?.mode || '').trim()
          : ''
        if (curMode !== parentMode) {
          childSession.append('sandbox/mode', { mode: parentMode })
        }
      }
      if (parentApproval && typeof childSession.append === 'function') {
        childSession.append('approval/policy', { policy: parentApproval })
      }
    } catch {}
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
    if (role === 'library_verifier' && !effSandbox) {
      throw new Error('BLIND_SANDBOX_REQUIRED: library_verifier 必须挂载独立空白盲审沙箱 sandboxAbsPath，禁止回退主工作区！')
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
      try {
        resolved = await agentPresetsSvc.resolve(targetPreset)
      } catch {}
      if (!resolved) {
        throw new Error(`角色 ${role} 所需的 Agent Preset "${targetPreset}" 无法在 agentPresets 中解析（请确认插件入口已装配或 cordis.patch.yml 已生效）。`)
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
            // 纯原生工具长回合跨过 37% / 70% 或节点在 DB 中已被外部关闭时主动安全收束当前 Turn
            if (ev?.trigger === 'REFLECT_37' || ev?.trigger === 'HANDOFF_70' || ev?.trigger === 'NODE_TERMINATED') {
              thresholdCancelled = true
              try {
                liveHandleRef?.agent?.cancel?.({ kind: 'hook', reason: ev.trigger })
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
      title: sessionTitle,
    })

    await this.attachAndNameSession(handle.agent.session, sessionTitle, { crossCwd })

    if (!shortTransaction && ['logistics_coordinator', 'works_engineer', 'library_surveyor', 'supervisory_committee'].includes(role)) {
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
      const sessionRef = handle?.agent?.session
      // 1. 先释放活跃会话句柄与挂载钩子（RC5 dsh-workspace 禁止归档仍处于活跃状态的会话）
      try {
        await handle.dispose()
      } catch {}
      for (const fn of cleanupFns.splice(0)) {
        try {
          await fn()
        } catch {}
      }
      // 2. 释放完毕后再执行原生归档，并将真实归档结果（而非期望值）写入遥测
      const wantArchive = archive !== null ? Boolean(archive) : Boolean(defaultShouldArchive)
      let archRes = { archived: false, error: null }
      if (wantArchive) {
        archRes = await this.archiveSession(effSid, sessionRef)
      }
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
    this._recordContentRefusal(effSid, role, turnEndReason)
    const isAbnormalEnd = Boolean(
      !thresholdCancelled && turnEndReason && (turnEndReason.kind === 'error' || turnEndReason.kind === 'aborted'),
    )
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
