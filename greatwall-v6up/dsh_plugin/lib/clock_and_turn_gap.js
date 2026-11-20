/**
 * DSH 原生 TokenMeter 500k 物理时钟与 `concludeTurn()` 回合间隙控制流（v2.2）。
 *
 * 100% 使用本机核准的 DSH `0.2.2-rc.3` 原生 API：
 * - 优先从 `ctx.sessionProjections.snapshot(agent.session, ['contextPressure'])` 读取 `projectedTokens ?? pressureTokens`
 * - 降级调用 `ctx.tokenMeter.measure(agent.session).totalTokens`（绝不虚构不存在的方法）
 * - 以 Single-Writer 控制面原子同步回 `lineage_nodes.pressure_tokens`（500,000 分母）
 * - 在 `agentCtx.tools.register` 注册的 MCP 工具体内调用 `exec.concludeTurn()`：
 *   当 `explorer` 的 `run_isolated_eval` 返回 `clock_signal.trigger` (`REFLECT_37` / `HANDOFF_70`)
 *   或当收官工具（`record_reflection_and_unlock_pull`, `submit_node_handoff`, `submit_stage1_blind_ledger(REJECT)`,
 *   `submit_stage2_unblind_verdict`, `export_stage3_final_delivery`, `record_compliance_check`）成功落库时，
 *   立即让当前 Turn 干净完结（`whenIdle()` 返回），由外层编排器在回合间隙顺序唤醒下一角色！
 * @module dsh-greatwall-v6up/clock_and_turn_gap
 */
import { TURN_CONCLUDING_TOOLS } from './prompts.js'

/**
 * 采样指定 Agent Session 当前上下文 Token 压力水位。
 * @param {object} ctx DSH Cordis Context
 * @param {object} agent DSH Live Agent（含 `agent.session`）
 * @returns {{ pressureTokens: number, contextWindow: number, source: string }}
 */
export function sampleAgentContextPressure(ctx, agent, defaultWindow = 500_000) {
  let pressureTokens = 0
  let contextWindow = defaultWindow
  let source = 'none'

  const session = agent?.session
  if (!session) {
    return { pressureTokens, contextWindow, source }
  }

  // 1. 首选真实 DSH 0.2.2-rc.3 sessionProjections(['contextPressure'])
  try {
    const snap = ctx?.sessionProjections?.snapshot?.(session, ['contextPressure'])
    const cp = snap?.values?.contextPressure
    if (cp && typeof cp === 'object') {
      const cand = cp.projectedTokens ?? cp.pressureTokens
      if (typeof cand === 'number' && Number.isFinite(cand) && cand >= 0) {
        pressureTokens = Math.round(cand)
        source = 'sessionProjections.contextPressure'
      }
      if (typeof cp.contextWindow === 'number' && Number.isFinite(cp.contextWindow) && cp.contextWindow > 0) {
        contextWindow = Math.round(cp.contextWindow)
      }
    }
  } catch {}

  // 2. Step 0 或尚未累积 contextPressure 时回退 tokenMeter.measure(session)
  if (pressureTokens === 0 && typeof ctx?.tokenMeter?.measure === 'function') {
    try {
      const m = ctx.tokenMeter.measure(session)
      const total = Number(m?.totalTokens ?? m?.inputTokens ?? 0)
      if (Number.isFinite(total) && total > 0) {
        pressureTokens = Math.round(total)
        source = 'tokenMeter.measure'
      }
    } catch {}
  }

  return { pressureTokens, contextWindow, source }
}

/**
 * 将当前压力水位同步到 Python SQLite 单一真相时钟字段。
 * @param {object} ctx
 * @param {object} agent
 * @param {import('./mcp_bridge.js').GreatwallMcpBridge} bridge
 * @param {string} workspaceRoot
 * @param {string} nodeId
 */
export async function syncLivePressureToDb(ctx, agent, bridge, workspaceRoot, nodeId) {
  if (!nodeId || !bridge) return null
  const sample = sampleAgentContextPressure(ctx, agent)
  try {
    return await bridge.control('control_plane/sync_pressure', {
      workspace_root: workspaceRoot,
      node_id: nodeId,
      pressure_tokens: sample.pressureTokens,
    })
  } catch {
    return null
  }
}

/**
 * 消除探索者连调几十次原生工具 (`read`/`edit`/`pwsh` 等) 期间 500k 时钟冻结的盲区：
 * 将 `syncLivePressureToDb` 与 37% / 70% 水位检查同时挂载到 `agent/pre-step` 与全部工具的 `tools/result`！
 * @param {object} params
 */
export function installLiveClockObservers({
  rootCtx,
  agentCtx,
  agent,
  bridge,
  workspaceRoot,
  nodeId = '',
  role,
  onNativeThresholdHit,
}) {
  if (role !== 'explorer' || !nodeId || !bridge) {
    return () => {}
  }
  const disposers = []
  let lastTriggerEmitted = ''

  const checkAndSync = async (sourceHook) => {
    const syncRes = await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId)
    const sample = sampleAgentContextPressure(rootCtx, agent)
    const pct = sample.pressureTokens / Math.max(1, sample.contextWindow || 500_000)
    const rowData = syncRes?.data ?? syncRes ?? {}
    const evalCount = Number(rowData.eval_count ?? 0)
    const unlocked = Boolean(rowData.first_reflection_unlocked)

    if (pct >= 0.70 && lastTriggerEmitted !== 'HANDOFF_70') {
      lastTriggerEmitted = 'HANDOFF_70'
      onNativeThresholdHit?.({ trigger: 'HANDOFF_70', pressurePct: pct, sourceHook, evalCount })
    } else if (pct >= 0.37 && !unlocked && evalCount >= 1 && !lastTriggerEmitted) {
      lastTriggerEmitted = 'REFLECT_37'
      onNativeThresholdHit?.({ trigger: 'REFLECT_37', pressurePct: pct, sourceHook, evalCount })
    }
  }

  try {
    const dResult = agentCtx.on('tools/result', (exec) => {
      const tname = String(exec?.name || '')
      // `run_isolated_eval` 已在自身执行体做同步与 concludeTurn，其余原生工具与检索工具走这里实时追帧
      if (tname && tname !== 'run_isolated_eval') {
        void checkAndSync(`tools/result:${tname}`)
      }
    })
    if (typeof dResult === 'function') disposers.push(dResult)
  } catch {}

  try {
    const dStep = agentCtx.on('agent/pre-step', async (_payload, next) => {
      await checkAndSync('agent/pre-step')
      return next()
    })
    if (typeof dStep === 'function') disposers.push(dStep)
  } catch {}

  return () => {
    for (const d of disposers) {
      try {
        d()
      } catch {}
    }
  }
}

/**
 * 为指定角色的 DSH Agent 注册其专属 3–5 个 MCP 窄工具，并内嵌：
 * - 调用前自动同步最新 Token 压力（仅 `explorer` 带 `nodeId` 时）
 * - `tools.register` 严格输出 Schema + text 渲染
 * - Turn 间隙 `exec.concludeTurn()` 精准状态切换事件通知
 * @param {object} params
 */
export function registerScopedMcpTools({
  rootCtx,
  agentCtx,
  agent,
  bridge,
  toolSchemas,
  allowedToolNames,
  role,
  workspaceRoot,
  nodeId = '',
  onTurnSignal,
}) {
  const disposers = []
  const allowedSet = new Set(allowedToolNames || [])
  const schemaByName = new Map((toolSchemas || []).map((t) => [t.name, t]))

  for (const toolName of allowedSet) {
    const schemaDef = schemaByName.get(toolName)
    if (!schemaDef) continue

    const disposeTool = agentCtx.tools.register({
      name: toolName,
      description: String(schemaDef.description || `Greatwall MCP tool: ${toolName}`),
      parameters: schemaDef.inputSchema || { type: 'object', properties: {} },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value) {
          return [{ type: 'text', text: JSON.stringify(value) }]
        },
      },
      async execute(args, exec) {
        // 探索者每次发起评估/查询前同步最新 DSH Token 水位，确保 SQLite 时钟严格与 LLM Context 一致
        if (role === 'explorer' && nodeId) {
          await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId)
        }

        const res = await bridge.callTool(toolName, args, {
          workspaceRoot,
          role,
          sessionId: agent.id,
        })

        // 捕捉 Turn 间隙信号，在安全边界调用 exec.concludeTurn()
        if (role === 'explorer' && toolName === 'run_isolated_eval' && res?.ok) {
          // 再次采样本轮刚产生的消耗并同步
          if (nodeId) {
            await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId)
          }
          const trigger = res?.data?.clock_signal?.trigger
          if (trigger === 'REFLECT_37' || trigger === 'HANDOFF_70') {
            exec.concludeTurn()
            if (typeof onTurnSignal === 'function') {
              onTurnSignal({ role, nodeId, sessionId: agent.id, toolName, trigger, receipt: res })
            }
          }
        } else if (res?.ok && TURN_CONCLUDING_TOOLS.has(toolName)) {
          // Stage 1 PASS 不直接结题（紧接着要调 Stage 2），只有 REJECT 短路或非 submit_stage1_blind_ledger 才结束
          const shouldConclude =
            toolName !== 'submit_stage1_blind_ledger' ||
            String(res?.data?.stage1_verdict || '').toUpperCase() === 'REJECT'
          if (shouldConclude) {
            exec.concludeTurn()
            if (typeof onTurnSignal === 'function') {
              onTurnSignal({ role, nodeId, sessionId: agent.id, toolName, trigger: 'ROLE_TASK_DONE', receipt: res })
            }
          }
        }

        return res && typeof res === 'object' ? res : { ok: false, error: 'Invalid MCP tool response' }
      },
    })
    disposers.push(disposeTool)
  }

  return () => {
    for (const d of disposers) {
      try {
        d()
      } catch {}
    }
  }
}
