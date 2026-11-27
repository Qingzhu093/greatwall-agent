/**
 * GreatWall v0.3 子会话能力挂载单元（工具裁剪、沙箱 Guard、FactLog、物理时钟、动态锚点与窄 MCP 工具）。
 * @module dsh-greatwall-v6up/host/capability_mount
 */
import path from 'node:path'
import { ROLE_MCP_TOOLS, resolvePlatformAllowedTools } from '../prompts.js'
import { installRoleSandboxGuard } from '../read_isolated_sandbox.js'
import { installFactLogMiddleware } from '../fact_log_middleware.js'
import { installLiveClockObservers, registerScopedMcpTools } from '../clock_and_turn_gap.js'
import { buildBlackboxTrajectorySummary } from '../blackbox_projection.js'

const ZERO_NATIVE_ROLES = new Set([
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
    onBeforeStep = null,
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

  // 支持 gw_chief 每次对话动态注入弹性字数「全院现况锚点卡」（防压缩断链）与每步前实时刷新
  if (typeof onBeforeStep === 'function' && typeof agentCtx.on === 'function') {
    try {
      const disposePreStep = agentCtx.on('agent/pre-step', async (payload, next) => {
        try {
          await onBeforeStep(agent, payload)
        } catch {}
        return typeof next === 'function' ? next() : undefined
      })
      if (typeof disposePreStep === 'function') cleanupFns.push(disposePreStep)
    } catch {}
  }

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

  // 裁决一：为 gw_chief 挂载只读 Watchdog 实时轨迹工具（Inline & Spill，默认 <=3200 字，杜绝盲判在跑探索者为卡死）
  if (role === 'gw_chief' && !readonly && typeof agentCtx.tools?.register === 'function') {
    const disposeActivityTool = agentCtx.tools.register({
      name: 'chief_get_node_recent_activity',
      description: '只读 Watchdog 工具：查看某个在跑或历史探索者/伴随会话最近 5-8 步黑盒行动摘要（最近调用的工具、耗时与实时活跃状态），遵循 Inline & Spill 绝不灌爆主窗。',
      parameters: {
        type: 'object',
        properties: {
          session_id: { type: 'string', description: '目标会话 ID（如 gw-exp-node_q1_xxx），可从锚点卡或 chief_trace_entity 获取' },
          node_id: { type: 'string', description: '可选：目标节点 ID（若未填 session_id，自动拼接 gw-exp-<node_id>）' },
          max_chars: { type: 'integer', description: '可选：摘要最大字符数（默认 3200，上限 6000）' },
        },
        additionalProperties: false,
      },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_a, val) {
          return [{ type: 'text', text: JSON.stringify(val) }]
        },
      },
      async execute(args) {
        const sid = String(args?.session_id || (args?.node_id ? `gw-exp-${String(args.node_id).trim()}` : '')).trim()
        if (!sid) return { ok: false, error: '必须提供 session_id 或 node_id' }
        const maxChars = Math.min(6000, Math.max(800, Number(args?.max_chars || 3200)))
        const liveEntry = hostDeps.liveSessions?.get?.(sid) || null
        let summary = ''
        try {
          summary = await buildBlackboxTrajectorySummary(hostDeps.rootCtx, sid, maxChars)
        } catch (err) {
          summary = `(提取轨迹异常: ${String(err?.message || err)})`
        }
        return {
          ok: true,
          session_id: sid,
          is_live_running: Boolean(liveEntry),
          elapsed_sec: liveEntry ? Math.max(0, Math.round((Date.now() - Number(liveEntry.startedAt || Date.now())) / 1000)) : null,
          role: liveEntry?.role || null,
          recent_activity_summary: summary || '(该会话暂无已落盘轨迹事件)',
        }
      },
    })
    if (typeof disposeActivityTool === 'function') cleanupFns.push(disposeActivityTool)
  }
}
