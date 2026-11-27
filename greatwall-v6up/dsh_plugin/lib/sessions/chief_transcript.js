/** Paged public transcript projection without model-internal reasoning blocks. */
export async function readChiefTranscript(ctx, sessionId, args) {
  let messages
  try {
    const store = typeof ctx?.get === 'function' ? ctx.get('sessions') : ctx?.sessions
    messages = await store?.get?.(sessionId)?.deriveMessages?.()
  } catch {}
  if (!Array.isArray(messages)) {
    try {
      const service = typeof ctx?.get === 'function' ? ctx.get('sessionQuery') : ctx?.sessionQuery
      const result = await service?.readSurface?.(sessionId)
      messages = result?.surface?.messages || result?.messages
    } catch {}
  }
  if (!Array.isArray(messages)) return { ok: false, error_code: 'ERR_NOT_FOUND', error: '会话记录尚不可用' }
  const text = messages.map((message) => {
    const blocks = message.content || ''
    const publicText = typeof blocks === 'string' ? blocks : blocks.map((block) => {
      if (block?.type === 'text') return block.text
      if (block?.type === 'tool-call' || block?.type === 'tool_use') return `[工具 ${block.name}]`
      return ''
    }).filter(Boolean).join('\n')
    return publicText ? `[${message.role}]\n${publicText}` : ''
  }).filter(Boolean).join('\n\n')
  const low = (n) => text.charCodeAt(n) >= 0xdc00 && text.charCodeAt(n) <= 0xdfff
  let start = Math.min(text.length, Math.max(0, Number(args.offset) || 0))
  if (low(start)) start++
  let end = Math.min(text.length, start + Math.min(6000, Math.max(2, Number(args.limit) || 4000)))
  if (low(end)) end--
  return {
    ok: true,
    data: { resource: args.resource, offset: start, total_chars: text.length, next_offset: end < text.length ? end : null, text: text.slice(start, end) },
  }
}

