/**
 * GreatWall v0.3 瞬态网络/限流故障原地指数退避分类器（15s -> 30s -> 60s，最多 3 次）。
 *
 * 仅对确凿的瞬态错误（408 / 429 / 5xx / ECONNRESET / ETIMEDOUT / fetch failed）执行原地退避重试，
 * 避免一次 429 抖动就把活生生的探索节点误判为 CRASH_RECOVERY 提前销毁！
 * 严禁对 400 / 401 / 403 / CONTENT_REFUSED / ABORTED 做无意义重试。
 * @module dsh-greatwall-v6up/runtime/transient_retry
 */

export const DEFAULT_TRANSIENT_DELAYS_MS = Object.freeze([15_000, 30_000, 60_000])

const TRANSIENT_STATUS_RE = /\b(?:408|429|500|502|503|504|522|524)\b/
const TRANSIENT_MSG_RE = /(?:rate\s*limit|too\s*many\s*requests|overloaded|timeout|timed\s*out|econnreset|econnrefused|etimedout|epipe|socket\s*hang\s*up|network\s*error|fetch\s*failed|temporarily\s*unavailable|bad\s*gateway|service\s*unavailable)/i
const NON_TRANSIENT_RE = /(?:CONTENT_REFUSED|GREATWALL_RUN_ABORTED|invalid_api_key|authentication_error|permission_denied|\b400\b|\b401\b|\b403\b)/i

export function isTransientProviderError(errOrReason) {
  if (!errOrReason) return false
  const text = typeof errOrReason === 'string'
    ? errOrReason
    : `${errOrReason?.code || ''} ${errOrReason?.status || ''} ${errOrReason?.message || ''} ${JSON.stringify(errOrReason?.error || errOrReason || '')}`
  if (NON_TRANSIENT_RE.test(text)) return false
  return TRANSIENT_STATUS_RE.test(text) || TRANSIENT_MSG_RE.test(text)
}

export async function waitWithAbort(ms, signal = null) {
  if (ms <= 0) return
  if (signal?.aborted) {
    const err = new Error('GREATWALL_RUN_ABORTED')
    err.code = 'GREATWALL_RUN_ABORTED'
    throw err
  }
  await new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      const err = new Error('GREATWALL_RUN_ABORTED')
      err.code = 'GREATWALL_RUN_ABORTED'
      reject(err)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener?.('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener?.('abort', onAbort, { once: true })
  })
}

/**
 * 对单次可恢复调用执行上限 3 次的指数退避重试。
 * @template T
 * @param {() => Promise<T>} fn
 * @param {{ delaysMs?: readonly number[], signal?: AbortSignal | null, onRetry?: (info: { attempt: number, delayMs: number, error: string }) => void }} [opts]
 * @returns {Promise<T>}
 */
export async function runWithTransientRetry(fn, { delaysMs = DEFAULT_TRANSIENT_DELAYS_MS, signal = null, onRetry = null } = {}) {
  let attempt = 0
  while (true) {
    try {
      return await fn()
    } catch (err) {
      if (signal?.aborted || !isTransientProviderError(err) || attempt >= delaysMs.length) {
        throw err
      }
      const delayMs = Number(delaysMs[attempt] || 15_000)
      attempt += 1
      onRetry?.({ attempt, delayMs, error: String(err?.message || err) })
      await waitWithAbort(delayMs, signal)
    }
  }
}
