/**
 * Blackbox 探索轨迹投影（严禁提取 `thinking` / `reasoning_content`）。
 * 使用 DSH 原生 `ctx.sessionQuery.readSurface` / `listEvents` 从探索者对话读取外部动作历史：
 * - 最新工具执行、观测回执、报错及代码修改摘要；
 * - 绝不复制思维链或全量上下文，以轻量紧凑摘要 Push 给 `lineage_companion`。
 * @module dsh-greatwall-v6up/blackbox_projection
 */

function stripTextFromBlocks(blocks) {
  if (!Array.isArray(blocks)) {
    return typeof blocks === 'string' ? blocks : ''
  }
  const parts = []
  for (const blk of blocks) {
    if (!blk || typeof blk !== 'object') continue
    // 物理剔除 thinking / reasoning 类内部块
    if (blk.type === 'thinking' || blk.type === 'reasoning') continue
    if (blk.type === 'text' && typeof blk.text === 'string') {
      parts.push(blk.text)
    } else if (blk.type === 'tool-call' || blk.type === 'tool_use') {
      const argText = typeof blk.arguments === 'string' ? blk.arguments : JSON.stringify(blk.input ?? blk.arguments ?? {})
      parts.push(`[ToolCall ${blk.name}(${argText.slice(0, 500)})]`)
    } else if (blk.type === 'tool-result' || blk.type === 'tool_result') {
      parts.push(`[ToolResult ${String(blk.toolCallId ?? blk.tool_use_id ?? '')}: ${JSON.stringify(blk.content ?? '').slice(0, 600)}]`)
    }
  }
  return parts.join('\n')
}

/**
 * 提取黑匣子行为轨迹摘要（严格不含 reasoning/thinking）。
 * @param {object} ctx DSH Cordis Context（需含或可选含 `sessionQuery`）
 * @param {string} sessionId
 * @param {number} [maxChars=4800]
 */
export async function buildBlackboxTrajectorySummary(ctx, sessionId, maxChars = 4800, session = null) {
  if (!sessionId && !session) {
    return '(无可用 sessionId 黑匣子投影)'
  }

  const lines = []
  try {
    const sessStore = typeof ctx?.get === 'function' ? ctx.get('sessions') : ctx?.sessions
    const liveSess = session || sessStore?.get?.(sessionId)
    let msgs = typeof liveSess?.deriveMessages === 'function' ? liveSess.deriveMessages() : null
    if (!Array.isArray(msgs) && typeof ctx?.sessionQuery?.readSurface === 'function') {
      const surfaceSnap = await ctx.sessionQuery.readSurface(sessionId)
      msgs = surfaceSnap?.surface?.messages || surfaceSnap?.messages || []
    }
    const tail = Array.isArray(msgs) ? msgs.slice(-20) : []
    for (const m of tail) {
      if (!m || typeof m !== 'object') continue
      const role = String(m.role || 'unknown')
      const txt = stripTextFromBlocks(m.content).trim()
      if (txt) {
        lines.push(`[${role}] ${txt.slice(0, 800)}`)
      }
    }
  } catch {}

  if (!lines.length) {
    try {
      const sessStore = typeof ctx?.get === 'function' ? ctx.get('sessions') : ctx?.sessions
      const liveSess = session || sessStore?.get?.(sessionId)
      let events = typeof liveSess?.snapshotEvents === 'function' ? liveSess.snapshotEvents() : null
      if (!Array.isArray(events) && typeof ctx?.sessionQuery?.listEvents === 'function') {
        events = await ctx.sessionQuery.listEvents(sessionId)
      }
      const tail = Array.isArray(events) ? events.slice(-24) : []
      for (const ev of tail) {
        if (!ev || typeof ev !== 'object') continue
        const t = String(ev.type || ev.kind || 'event')
        if (t.includes('thinking') || t.includes('reasoning')) continue
        lines.push(`[${t}] ${JSON.stringify(ev.payload ?? ev.data ?? {}).slice(0, 600)}`)
      }
    } catch {}
  }

  if (!lines.length) {
    return '(该探索节点暂无可提取对话外显轨迹)'
  }

  const joined = lines.join('\n')
  return joined.length <= maxChars ? joined : joined.slice(joined.length - maxChars)
}
