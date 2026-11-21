/**
 * DSH 原生 TokenMeter 500k 物理时钟与 `concludeTurn()` 回合间隙控制流（v3.0）。
 *
 * 核心升级（对齐 09 §5.2 & agent_kb/05）：
 * 1. 彻底废除 `evalCount >= 1` 反思锁：`pct >= 0.37 && !unlocked` 立即触发 `REFLECT_37`，
 *    保障纯数学推导与零仪器探索节点同样准时获得 37% 诊断反思与内藏解锁；
 * 2. `pct >= 0.70` 触发 `HANDOFF_70`，进入探索者只读亲笔遗嘱 + 伴随单写交接两步闭环；
 * 3. `submit_stage1_blind_ledger` 在 `REVISE` 或 `REFUTED` 时立刻 `exec.concludeTurn()`，
 *    `PASS` 时保留回合继续解盲执行 Stage 2。
 * @module dsh-greatwall-v6up/clock_and_turn_gap
 */
import { TURN_CONCLUDING_TOOLS } from './prompts.js'

/**
 * 采样指定 Agent Session 当前上下文 Token 压力水位。
 * @param {object} ctx DSH Cordis Context
 * @param {object} agent DSH Live Agent（含 `agent.session`）
 * @param {number} [defaultWindow=500000]
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
 * 纯函数计算当前上下文水位触发器（v3.0：无 `evalCount >= 1` 限制！）。
 * @param {{ pressureTokens: number, contextWindow?: number, firstReflectionUnlocked?: boolean, reflectPct?: number, handoffPct?: number }} params
 * @returns {{ pressurePct: number, trigger: 'HANDOFF_70' | 'REFLECT_37' | null }}
 */
export function evaluateContextClockTrigger({
  pressureTokens,
  contextWindow = 500_000,
  firstReflectionUnlocked = false,
  reflectPct = 0.37,
  handoffPct = 0.70,
}) {
  const denom = Math.max(1, Number(contextWindow) || 500_000)
  const pct = Math.max(0, Number(pressureTokens) || 0) / denom
  if (pct >= handoffPct) {
    return { pressurePct: pct, trigger: 'HANDOFF_70' }
  }
  if (pct >= reflectPct && !firstReflectionUnlocked) {
    return { pressurePct: pct, trigger: 'REFLECT_37' }
  }
  return { pressurePct: pct, trigger: null }
}

/**
 * 将当前压力水位同步到 Python SQLite 单一真相时钟字段。
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
 * 实时追帧观测器：在探索者连续调用原生工具（`read`/`edit`/`pwsh`）期间同步 500k 时钟，
 * 并在纯推导/零仪器场景下照常准时触发 37% 反思与 70% 交接。
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
    const rowData = syncRes?.data ?? syncRes ?? {}
    const unlocked = Boolean(rowData.first_reflection_unlocked)

    const { pressurePct, trigger } = evaluateContextClockTrigger({
      pressureTokens: sample.pressureTokens,
      contextWindow: sample.contextWindow || 500_000,
      firstReflectionUnlocked: unlocked,
    })

    if (trigger === 'HANDOFF_70' && lastTriggerEmitted !== 'HANDOFF_70') {
      lastTriggerEmitted = 'HANDOFF_70'
      onNativeThresholdHit?.({ trigger: 'HANDOFF_70', pressurePct, sourceHook })
    } else if (trigger === 'REFLECT_37' && !lastTriggerEmitted) {
      lastTriggerEmitted = 'REFLECT_37'
      onNativeThresholdHit?.({ trigger: 'REFLECT_37', pressurePct, sourceHook })
    }
  }

  try {
    const dResult = agentCtx.on('tools/result', (exec) => {
      const tname = String(exec?.name || '')
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
 * 判断某个窄工具成功返回后是否应当在当前 Turn 边界优雅收尾 (`exec.concludeTurn()`)。
 * @param {string} toolName
 * @param {any} res
 */
export function shouldConcludeTurnAfterTool(toolName, res) {
  if (!res?.ok) return false
  if (toolName === 'run_isolated_eval') {
    const trigger = res?.data?.clock_signal?.trigger
    return trigger === 'REFLECT_37' || trigger === 'HANDOFF_70'
  }
  if (!TURN_CONCLUDING_TOOLS.has(toolName)) return false
  if (toolName === 'submit_stage1_blind_ledger') {
    const v = String(res?.data?.stage1_verdict || '').toUpperCase()
    return v === 'REVISE' || v === 'REFUTED'
  }
  return true
}

/**
 * 为指定角色的 DSH Agent 注册其专属 3–5 个 MCP 窄工具。
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
        if (role === 'explorer' && nodeId) {
          await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId)
        }

        const res = await bridge.callTool(toolName, args, {
          workspaceRoot,
          role,
          sessionId: agent.id,
        })

        if (role === 'explorer' && toolName === 'run_isolated_eval' && res?.ok) {
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
        } else if (shouldConcludeTurnAfterTool(toolName, res)) {
          exec.concludeTurn()
          if (typeof onTurnSignal === 'function') {
            onTurnSignal({ role, nodeId, sessionId: agent.id, toolName, trigger: 'ROLE_TASK_DONE', receipt: res })
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
