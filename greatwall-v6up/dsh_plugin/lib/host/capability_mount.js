/**
 * GreatWall v0.3 子会话能力挂载单元（工具裁剪、沙箱 Guard、FactLog、物理时钟、动态锚点与窄 MCP 工具）。
 * @module dsh-greatwall-v6up/host/capability_mount
 */
import path from 'node:path'
import { ROLE_MCP_TOOLS, resolvePlatformAllowedTools } from '../prompts.js'
import { installRoleSandboxGuard } from '../read_isolated_sandbox.js'
import { installFactLogMiddleware } from '../fact_log_middleware.js'
import { installLiveClockObservers, registerScopedMcpTools } from '../clock_and_turn_gap.js'

const ZERO_NATIVE_ROLES = new Set([
  'gw_chief',
  'logistics_coordinator',
  'supervisory_committee',
  'library_chronicler',
  'conference_chair',
])

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
    extraContextProvider = null,
    allowedMcpOverride = null,
    readonly = false,
    cleanupFns = [],
    turnSignals = [],
    onNativeThresholdHit = null,
  },
) {
  const allowNative = readonly
    ? (ZERO_NATIVE_ROLES.has(role) || role === 'external_surveyor' ? [] : ['read', 'glob', 'grep'])
    : resolvePlatformAllowedTools(role, process.platform)

  const mcpToolNames = readonly
    ? []
    : (Array.isArray(allowedMcpOverride) ? allowedMcpOverride : (ROLE_MCP_TOOLS[role] || []))

  const inherited = agentCtx.tools?.schemas?.(agent)?.map((s) => s.name) || []
  if (inherited.length > 0 && typeof agentCtx.tools?.restrict === 'function') {
    let restrictDispose = null
    if (allowNative.length === 0) {
      restrictDispose = agentCtx.tools.restrict({ deny: inherited })
    } else {
      const allowSet = new Set(allowNative)
      const matchedAllow = inherited.filter((n) => allowSet.has(n))
      restrictDispose = matchedAllow.length > 0
        ? agentCtx.tools.restrict({ allow: matchedAllow })
        : agentCtx.tools.restrict({ deny: inherited })
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

  // 支持 gw_chief 每次对话动态注入弹性字数「全院现况锚点卡」（防压缩断链）
  if (typeof extraContextProvider === 'function' && typeof agentCtx.systemPrompt?.context === 'function') {
    cleanupFns.push(
      agentCtx.systemPrompt.context({
        name: `greatwall:anchor:${role}`,
        order: 15,
        text: () => extraContextProvider(agent),
        required: true,
        interpolate: false,
      }),
    )
  }

  cleanupFns.push(
    agentCtx.on('system-prompt/assemble', async (assembly, _assembleCtx, next) => {
      const out = await next()
      if (Array.isArray(out?.sections)) {
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
