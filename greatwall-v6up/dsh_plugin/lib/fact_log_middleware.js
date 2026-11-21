/**
 * DSH `tools/result` 确定性 FACT_LOG 中间件（v3.0）：
 * 捕捉每一次成功的原生工具调用，通过 Single-Writer 控制面写入
 * `epistemic_edges (edge_track='FACT_LOG', source_id, target_id, session_id)`。
 * @module dsh-greatwall-v6up/fact_log_middleware
 */
import { extractPathValues } from './read_isolated_sandbox.js'
import { ALL_31_MCP_TOOLS } from './prompts.js'

/**
 * @param {object} agentCtx
 * @param {object} opts
 * @param {string} opts.workspaceRoot
 * @param {string} opts.role
 * @param {string} opts.sessionId
 * @param {string} [opts.nodeId]
 * @param {import('./mcp_bridge.js').GreatwallMcpBridge} opts.bridge
 */
export function installFactLogMiddleware(agentCtx, opts) {
  /** @type {Set<Promise<any>>} */
  const inFlight = new Set()

  const dispose = agentCtx.on('tools/result', (exec, result) => {
    try {
      if (!exec || !result || result.isError) return
      const name = String(exec.name || '')
      // 全部 31 个 Python MCP 窄工具与 `greatwall_*` 已在事务内部精确记录，过滤避免双写
      if (name.startsWith('greatwall_') || ALL_31_MCP_TOOLS.has(name)) return

      const pathVals = extractPathValues(exec.arguments)
      const isRead =
        name === 'read' ||
        name === 'read_file' ||
        name === 'read_image' ||
        name === 'list_dir' ||
        name === 'glob' ||
        name === 'grep' ||
        name === 'grep_search'
      const isWeb = name === 'web_search' || name === 'web_fetch'
      const edgeType = isRead ? 'READ' : (isWeb ? 'RETRIEVED' : 'USED_TOOL')
      const targetId = pathVals.length ? `file:${pathVals[0].slice(0, 180)}` : `native:${name}`

      const pending = opts.bridge
        .control('control_plane/fact_edge', {
          workspace_root: opts.workspaceRoot,
          source_id: opts.nodeId || opts.sessionId || opts.role,
          target_id: targetId,
          edge_type: edgeType,
          session_id: opts.sessionId,
          metadata: {
            role: opts.role,
            tool: name,
            paths: pathVals.slice(0, 4),
          },
        })
        .catch(() => {})
        .finally(() => {
          inFlight.delete(pending)
        })
      inFlight.add(pending)
    } catch {
      // DSH tools/result 契约要求观察者失败内聚
    }
  })

  const flush = async () => {
    while (inFlight.size > 0) {
      await Promise.allSettled([...inFlight])
    }
  }

  return async () => {
    try {
      dispose()
    } catch {}
    await flush()
  }
}
