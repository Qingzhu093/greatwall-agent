/**
 * 捕获当前回合的人类直接指令凭证（用于 gw_chief 日常运维直执鉴权）。
 * 优先识别 DSH RC5 携带的 source.rpcId，同时兼容 UI/CLI 入口发出的
 * source.origin === 'ui' | 'client' 消息；拒绝无凭证的插件自发 steer 消息。
 */
export function watchHumanMandate(rootCtx, session, onHumanMessage) {
  let mandate = null
  const dispose = rootCtx?.on?.('session/event', (subject, event) => {
    if (subject !== session) return
    if (event.type === 'turn/end') {
      mandate = null
    } else if (event.type === 'user/message') {
      const { source, content } = event.data || {}
      if (source?.kind !== 'user') return
      const hasRpcId = typeof source?.rpcId === 'string' && source.rpcId.trim().length > 0
      const isHumanOrigin = source?.origin === 'ui' || source?.origin === 'client'
      if (!hasRpcId && !isHumanOrigin) return
      const rpcId = hasRpcId ? source.rpcId.trim() : `${source.origin}-turn:${Date.now()}`
      const parts = Array.isArray(content) ? content : []
      const text = parts.filter((part) => part?.type === 'text').map((part) => part.text).join('\n')
      mandate = { rpcId, text }
      onHumanMessage?.(mandate)
    }
  }, { global: true })
  return {
    current: () => mandate,
    dispose() {
      mandate = null
      dispose?.()
    },
  }
}

