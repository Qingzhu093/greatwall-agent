/**
 * 子会话能力挂载单元（从 AgentSessionHost 拆出，专注工具裁剪、沙箱 Guard、FactLog、物理时钟与 Prompt 拼装）。
 *
 * 严格遵循 RC5 规范：
 * - 移除了 RC5 中已不存在的 `agentCtx.tools.presentAs('native')` 空转调用（由 Preset 声明 `@deepseek-ai/dsh-tool-executor-native` 承担）；
 * - 所有注册项的 disposer 统一压入 `cleanupFns`，确保会话结束或插件卸载时彻底释放。
 * @module dsh-greatwall-v6up/host/capability_mount
 */
import path from 'node:path'
import { ROLE_MCP_TOOLS, resolvePlatformAllowedTools } from '../prompts.js'
import { installRoleSandboxGuard } from '../read_isolated_sandbox.js'
import { installFactLogMiddleware } from '../fact_log_middleware.js'
import { installLiveClockObservers, registerScopedMcpTools } from '../clock_and_turn_gap.js'

/**
 * 为指定角色的子会话挂载受限原生工具、双向沙箱 Guard、FactLog、物理时钟、白名单 Prompt 与窄 MCP 工具。
 * @param {object} hostDeps
 * @param {any} hostDeps.rootCtx
 * @param {any} hostDeps.bridge
 * @param {string} hostDeps.workspaceRoot
 * @param {Record<string, string>} hostDeps.rolePrompts
 * @param {string[]} hostDeps.protectedDirs
 * @param {string[]} hostDeps.sharedInputPaths
 * @param {number} hostDeps.effectiveContextWindow
 * @param {(sessionId: string, flag: boolean) => void} hostDeps.setSessionReadonly
 * @param {(sessionId: string) => boolean} hostDeps.isSessionReadonly
 * @param {any} agentCtx
 * @param {any} agent
 * @param {object} mountOpts
 */
export function mountCapabilitiesOnAgentSession(
  hostDeps,
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

  const inherited = agentCtx.tools?.schemas?.(agent)?.map((s) => s.name) || []
  if (inherited.length > 0 && typeof agentCtx.tools?.restrict === 'function') {
    let restrictDispose = null
    if (allowNative.length === 0) {
      restrictDispose = agentCtx.tools.restrict({ deny: inherited })
    } else {
      const allowSet = new Set(allowNative)
      const matchedAllow = inherited.filter((n) => allowSet.has(n))
      if (matchedAllow.length > 0) {
        restrictDispose = agentCtx.tools.restrict({ allow: matchedAllow })
      } else {
        restrictDispose = agentCtx.tools.restrict({ deny: inherited })
      }
    }
    if (typeof restrictDispose === 'function') cleanupFns.push(restrictDispose)
  }

  const effWorktree = (role === 'explorer' || role === 'lineage_companion') && cwd
    ? path.resolve(cwd)
    : hostDeps.workspaceRoot
  const effSandbox = role === 'library_verifier' && sandboxAbsPath ? path.resolve(sandboxAbsPath) : ''
  hostDeps.setSessionReadonly(agent.id, Boolean(readonly))

  cleanupFns.push(
    installRoleSandboxGuard(agentCtx, {
      role,
      sessionId: agent.id,
      nodeId,
      workspaceRoot: hostDeps.workspaceRoot,
      worktreeAbsPath: effWorktree,
      sandboxAbsPath: effSandbox,
      protectedDirs: hostDeps.protectedDirs,
      sharedInputPaths: hostDeps.sharedInputPaths,
      readonly: () => Boolean(readonly) || hostDeps.isSessionReadonly(agent.id),
      bridge: hostDeps.bridge,
    }),
  )

  cleanupFns.push(
    installFactLogMiddleware(agentCtx, {
      workspaceRoot: hostDeps.workspaceRoot,
      role,
      sessionId: agent.id,
      nodeId,
      bridge: hostDeps.bridge,
    }),
  )

  cleanupFns.push(
    installLiveClockObservers({
      rootCtx: hostDeps.rootCtx,
      agentCtx,
      agent,
      bridge: hostDeps.bridge,
      workspaceRoot: hostDeps.workspaceRoot,
      nodeId,
      role,
      contextWindowTokens: hostDeps.effectiveContextWindow,
      onNativeThresholdHit,
    }),
  )

  const rolePromptText = hostDeps.rolePrompts?.[role] || `# Role: ${role}`
  cleanupFns.push(
    agentCtx.systemPrompt.section({
      name: `greatwall:contract:${role}`,
      order: 10,
      text: rolePromptText,
      interpolate: false,
    }),
  )

  if (taskContextText) {
    cleanupFns.push(
      agentCtx.systemPrompt.context({
        name: `greatwall:task:${agent.id}`,
        order: 20,
        text: taskContextText,
        required: true,
        interpolate: false,
      }),
    )
  }

  cleanupFns.push(
    agentCtx.on('system-prompt/assemble', async (assembly, _assembleCtx, next) => {
      const out = await next()
      if (Array.isArray(out?.sections)) {
        // 严格白名单：仅保留 harness:identity、本插件 greatwall:* 角色契约与本 Preset 自带 tool-* 说明，挡住全局第三方插件 section 污染
        out.sections = out.sections.filter((sec) => {
          const nm = String(sec?.name || '')
          if (nm === 'tool-fs:guidance') return false
          return nm === 'harness:identity' || nm.startsWith('greatwall:') || nm.startsWith('tool-')
        })
      }
      return out
    }),
  )

  if (mcpToolNames.length > 0 && toolSchemas.length > 0) {
    cleanupFns.push(
      registerScopedMcpTools({
        rootCtx: hostDeps.rootCtx,
        agentCtx,
        agent,
        bridge: hostDeps.bridge,
        toolSchemas,
        allowedToolNames: mcpToolNames,
        role,
        workspaceRoot: hostDeps.workspaceRoot,
        nodeId,
        contextWindowTokens: hostDeps.effectiveContextWindow,
        onTurnSignal: (sig) => turnSignals.push(sig),
      }),
    )
  }
}
