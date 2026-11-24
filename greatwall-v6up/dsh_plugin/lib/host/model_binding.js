/**
 * 长城 V6-Up (v3.0) 权威模型绑定解析链、自适应窗口计算、工具断言与会话消息纯函数。
 *
 * 从 `agent_session_host.js` 抽离，零会话状态，便于独立单测与模型适配演进。
 * @module dsh-greatwall-v6up/host/model_binding
 */
import crypto from 'node:crypto'
import { resolvePlatformShellTool } from '../prompts.js'

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

/**
 * 从会话事件流（model/selection / request/context）提取最新真实绑定的模型与上下文窗口。
 * 解决 DSH 桌面端用户在聊天框切换模型时只写会话事件、不反映在 `exec.agent.options` 上的问题。
 * @param {Array<any>} events
 */
export function extractModelBindingFromEvents(events) {
  let provider = ''
  let model = ''
  let contextWindow = 0
  let source = ''
  if (!Array.isArray(events)) return { provider, model, contextWindow, source }

  for (let i = events.length - 1; i >= 0; i--) {
    const ev = events[i]
    if (!ev || typeof ev !== 'object') continue
    const data = ev.data || ev.payload || {}
    if (!contextWindow && ev.type === 'request/context') {
      const cw = Number(data.contextWindow || 0)
      if (Number.isFinite(cw) && cw > 0) contextWindow = Math.round(cw)
    }
    if (!provider || !model) {
      if (ev.type === 'model/selection' || ev.type === 'request/context') {
        const p = String(data.provider || '').trim()
        const m = String(data.model || data.modelId || '').trim()
        if (p && m) {
          provider = p
          model = m
          source = `parent_session:${ev.type}`
          if (!contextWindow) {
            const cw = Number(data.contextWindow || 0)
            if (Number.isFinite(cw) && cw > 0) contextWindow = Math.round(cw)
          }
        }
      }
    }
    if (provider && model && contextWindow) break
  }
  return { provider, model, contextWindow, source }
}

/**
 * 计算有效上下文窗口上限：取真实模型物理窗口与显式/默认安全上限的较小值，
 * 杜绝 272k 模型按 500k 计算 37%/70% 永远到不了阈值的问题。
 */
export function resolveEffectiveContextWindow({
  explicitWindow = 0,
  modelWindow = 0,
  runtimeDefaultWindow = 500_000,
} = {}) {
  const exp = Number(explicitWindow || 0)
  const mod = Number(modelWindow || 0)
  const defCap = Math.max(1, Number(runtimeDefaultWindow || 500_000))
  const desiredCap = Number.isFinite(exp) && exp > 0 ? Math.round(exp) : defCap
  if (Number.isFinite(mod) && mod > 0) {
    return Math.min(desiredCap, Math.round(mod))
  }
  return desiredCap
}

/**
 * 解析并锁定权威模型绑定（严格禁止静默 fallback 到未授权第三方渠道）：
 * 优先级：explicitOptions > callerAgent.options > callerAgent 会话事件(model/selection, request/context) > configDefaultOptions。
 */
export async function resolveAuthoritativeModelBinding({
  explicitOptions = {},
  callerAgent = null,
  ctx = null,
  configDefaultOptions = {},
  runtimeDefaultWindow = 500_000,
} = {}) {
  let provider = ''
  let model = ''
  let source = 'unbound'
  let sessionContextWindow = 0

  const expP = String(explicitOptions?.provider || '').trim()
  const expM = String(explicitOptions?.model || '').trim()
  if (expP && expM) {
    provider = expP
    model = expM
    source = 'explicit'
  }

  if (!provider || !model) {
    const cOpts = callerAgent?.options || {}
    const cp = String(cOpts.provider || '').trim()
    const cm = String(cOpts.model || '').trim()
    if (cp && cm) {
      provider = cp
      model = cm
      source = 'caller_agent.options'
    }
  }

  // 从主控会话事件流读取用户在 UI 中真实选择的模型 (model/selection / request/context)
  if (callerAgent) {
    let events = null
    try {
      if (typeof callerAgent?.session?.snapshotEvents === 'function') {
        events = callerAgent.session.snapshotEvents()
      }
    } catch {}
    if (!Array.isArray(events) || events.length === 0) {
      try {
        const sid = callerAgent?.id || callerAgent?.session?.id
        if (sid && typeof ctx?.sessionQuery?.listEvents === 'function') {
          events = await ctx.sessionQuery.listEvents(sid)
        }
      } catch {}
    }
    const fromEv = extractModelBindingFromEvents(events)
    if (fromEv.contextWindow > 0) sessionContextWindow = fromEv.contextWindow
    if ((!provider || !model) && fromEv.provider && fromEv.model) {
      provider = fromEv.provider
      model = fromEv.model
      source = fromEv.source
    }
  }

  if (!provider || !model) {
    const cfgP = String(configDefaultOptions?.provider || '').trim()
    const cfgM = String(configDefaultOptions?.model || '').trim()
    if (cfgP && cfgM) {
      provider = cfgP
      model = cfgM
      source = 'plugin_config'
    }
  }

  // 查询 DSH LLM 注册表中的真实模型物理窗口
  let llmModelWindow = 0
  if (provider && model) {
    try {
      const llmSvc = typeof ctx?.get === 'function' ? ctx.get('llm') : ctx?.llm
      if (llmSvc && typeof llmSvc.resolveModelInfo === 'function') {
        const info = await llmSvc.resolveModelInfo(provider, model)
        const cw = Number(info?.contextWindow || info?.maxContextTokens || info?.limits?.context || 0)
        if (Number.isFinite(cw) && cw > 0) llmModelWindow = Math.round(cw)
      }
    } catch {}
  }

  const detectedModelWindow = llmModelWindow || sessionContextWindow || 0
  const explicitWin = Number(
    explicitOptions?.effectiveContextWindow ||
      explicitOptions?.contextWindowTokens ||
      configDefaultOptions?.effectiveContextWindow ||
      configDefaultOptions?.contextWindowTokens ||
      0,
  )
  const effectiveContextWindow = resolveEffectiveContextWindow({
    explicitWindow: explicitWin,
    modelWindow: detectedModelWindow,
    runtimeDefaultWindow,
  })

  return {
    ok: Boolean(provider && model),
    provider,
    model,
    effectiveContextWindow,
    contextWindowTokens: effectiveContextWindow,
    detectedModelWindow: detectedModelWindow || null,
    source,
  }
}
