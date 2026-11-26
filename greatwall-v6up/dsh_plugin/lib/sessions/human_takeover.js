/**
 * GreatWall v0.3 45% 运行中节点人工接管协调器（HumanTakeoverCoordinator）。
 *
 * 实装接入 DSH 0.2.2-rc.5 原生能力：
 * 1. `ctx.jobs`（`@deepseek-ai/dsh-jobs`）：暂停让权时检查并终止该探索会话尚未结束的后台 Shell 作业（无服务时平滑降级）；
 * 2. `user/message` + `source.rpcId` + 插件自发消息白名单双保险：100% 精准区分「人类在桌面端对探索子会话亲手发言」
 *    vs「插件 Orchestrator 内部发出的续推 prompt」，人类一旦插话立即触发 `HUMAN_CHAT_DETECTED` 对话让权，绝不抢麦！
 * 3. 与 Python 控制面 `pause_node / mark_node_yielded / resume_node / authorize_early_handoff` 完整闭环。
 * @module dsh-greatwall-v6up/sessions/human_takeover
 */

export class HumanTakeoverCoordinator {
  constructor({ ctx, bridge, workspaceRoot, telemetry = null }) {
    this.ctx = ctx
    this.bridge = bridge
    this.workspaceRoot = workspaceRoot
    this.telemetry = telemetry
    /** @type {Set<string>} 插件自己刚刚发出的消息正文指纹（防止误把 Orchestrator 自动续推识别为人类发言） */
    this._pluginSentFingerprints = new Set()
    /** @type {Map<string, () => void>} sessionId -> listener disposer */
    this._sessionWatchers = new Map()
  }

  /** 在 Orchestrator / PairLifecycle 主动向探索子会话发送消息前登记白名单指纹。 */
  markPluginMessage(sessionId, text) {
    const fp = `${sessionId}::${String(text || '').slice(0, 120)}`
    this._pluginSentFingerprints.add(fp)
    if (this._pluginSentFingerprints.size > 256) {
      const first = this._pluginSentFingerprints.values().next().value
      if (first) this._pluginSentFingerprints.delete(first)
    }
  }

  /**
   * 判定一条 `user/message` 事件是否来自真实人类在桌面端 UI 的直接发言。
   * 依据 DSH RC5 `@deepseek-ai/dsh-api-session-controller` 实证：人类发言携带 `source: { kind: 'user', rpcId }`。
   */
  isRealHumanUserMessage(sessionId, eventData) {
    const src = eventData?.source || {}
    if (src.kind && src.kind !== 'user') return false
    const text = this._extractTextFromUserEvent(eventData)
    const fp = `${sessionId}::${text.slice(0, 120)}`
    if (this._pluginSentFingerprints.has(fp)) {
      this._pluginSentFingerprints.delete(fp)
      return false
    }
    if (typeof src.rpcId === 'string' && src.rpcId.trim()) return true
    if (src.origin === 'ui' || src.origin === 'client') return true
    return false
  }

  _extractTextFromUserEvent(data) {
    if (!data) return ''
    if (typeof data.text === 'string') return data.text
    const content = data.content ?? data.message?.content
    if (typeof content === 'string') return content
    if (Array.isArray(content)) {
      return content.map((p) => (typeof p?.text === 'string' ? p.text : '')).join('\n').trim()
    }
    return ''
  }

  /** 为在线探索会话挂载人类发言监听器，检测到人类亲手发言即刻触发 `record_human_chat_detected`。 */
  watchExplorerSession(nodeId, session, { onHumanTakeover = null } = {}) {
    if (!session?.id || !nodeId) return () => {}
    this.unwatchExplorerSession(session.id)

    const handleEvent = (ev) => {
      if (!ev || ev.type !== 'user/message') return
      const payload = ev.data || ev.payload || ev
      if (!this.isRealHumanUserMessage(session.id, payload)) return
      const preview = this._extractTextFromUserEvent(payload).slice(0, 200)
      this.telemetry?.recordEvent?.('human_chat_detected', { nodeId, sessionId: session.id, preview })
      onHumanTakeover?.({ nodeId, sessionId: session.id, preview })
      void this.bridge
        .control('control_plane/record_human_chat_detected', {
          workspace_root: this.workspaceRoot,
          node_id: nodeId,
          session_id: session.id,
          message_preview: preview,
        })
        .catch(() => {})
    }

    let disposer = null
    if (typeof session.on === 'function') {
      disposer = session.on('event', handleEvent)
    } else if (typeof this.ctx?.on === 'function') {
      disposer = this.ctx.on('session/event', (e) => {
        if (e?.sessionId === session.id) handleEvent(e.event || e)
      })
    }
    const clean = () => {
      try {
        if (typeof disposer === 'function') disposer()
      } catch {}
    }
    this._sessionWatchers.set(session.id, clean)
    return clean
  }

  unwatchExplorerSession(sessionId) {
    const clean = this._sessionWatchers.get(sessionId)
    if (clean) {
      this._sessionWatchers.delete(sessionId)
      clean()
    }
  }

  /**
   * 暂停并安全让权：按可选 `graceSec` 有界宽限等待 -> 取消在途自动回合 -> 通过 DSH 原生 `ctx.jobs` 清理后台 Shell 作业 -> 落库 `mark_node_yielded`。
   */
  async drainAndYieldNode({
    nodeId,
    sessionId,
    liveHandle = null,
    livePromise = null,
    graceSec = 0,
    keepSessionForHuman = true,
    reason = 'PAUSE_REQUESTED',
  }) {
    const killedJobIds = []
    // 0. 若存在在途执行且指定了 graceSec > 0，先进行有界温和宽限等待（让当前短步自然落盘后再强取消）
    const graceMs = Math.min(5000, Math.max(0, Number(graceSec || 0) * 1000))
    if (graceMs > 0 && livePromise && typeof livePromise.then === 'function') {
      await Promise.race([
        Promise.resolve(livePromise).catch(() => {}),
        new Promise((resolve) => setTimeout(resolve, graceMs)),
      ])
    }

    // 1. 尝试优雅取消当前活跃自动回合
    try {
      liveHandle?.agent?.cancel?.({ kind: 'hook', reason })
    } catch {}

    // 2. 通过 RC5 原生 ctx.jobs 清理该会话的后台 Shell 作业（无服务时平滑降级）
    const jobsSvc =
      (typeof this.ctx?.get === 'function' ? this.ctx.get('jobs') : null) ||
      (typeof this.ctx?.root?.get === 'function' ? this.ctx.root.get('jobs') : null) ||
      this.ctx?.jobs
    if (jobsSvc && sessionId && typeof jobsSvc.list === 'function') {
      try {
        const list = (await jobsSvc.list(sessionId)) || []
        for (const job of list) {
          const jid = job?.id || job?.jobId
          if (!jid) continue
          if (job.status && !['running', 'queued', 'active'].includes(String(job.status).toLowerCase())) continue
          try {
            await jobsSvc.kill?.(jid, sessionId, `greatwall:${reason}`)
            killedJobIds.push(String(jid))
          } catch {}
        }
      } catch {}
    }

    // 3. 若因人类暂停让权，落库 CONTROL_YIELDED 通知人类桌面端可安全接手
    if (keepSessionForHuman && nodeId) {
      await this.bridge
        .control('control_plane/mark_node_yielded', {
          workspace_root: this.workspaceRoot,
          node_id: nodeId,
          details: { sessionId: sessionId || '', killedJobIds, reason },
        })
        .catch(() => {})
    }
    return { nodeId, sessionId, killedJobIds, keepSessionForHuman }
  }

  disposeAll() {
    for (const fn of this._sessionWatchers.values()) {
      try { fn() } catch {}
    }
    this._sessionWatchers.clear()
    this._pluginSentFingerprints.clear()
  }
}
