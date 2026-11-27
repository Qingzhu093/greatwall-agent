/**
 * DSH 原生 TokenMeter 500k 物理时钟与 `concludeTurn()` 回合间隙控制流（v3.0）。
 *
 * 核心升级（对齐 09 §5.2 & agent_kb/05）：
 * 1. 彻底废除 `evalCount >= 1` 反思锁：`pct >= 0.37 && !unlocked` 立即触发 `REFLECT_37`，
 *    保障纯数学推导与零仪器探索节点同样准时获得 37% 诊断反思与内藏解锁；
 * 2. `pct >= 0.70` 触发 `HANDOFF_70`，进入探索者只读亲笔遗嘱 + 伴随单写交接两步闭环；
 * 3. `submit_stage1_blind_ledger` 在 `REVISE` 或 `REFUTED` 时立刻 `exec.concludeTurn()`，
 *    `PASS` 或 `PARTIAL_PASS` 时保留回合继续解盲执行 Stage 2。
 * @module dsh-greatwall-v6up/clock_and_turn_gap
 */
import { TURN_CONCLUDING_TOOLS } from './prompts.js'
import { normalizeSchemaForDsh } from './bridge/dsh_schema_adapter.js'
import { watchHumanMandate } from './sessions/human_mandate.js'
import { readChiefTranscript } from './sessions/chief_transcript.js'

const DIRECT_CHIEF_TOOLS = new Set(['chief_operate', 'chief_send_branch_note', 'chief_seed_branch'])

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
        const measured = Math.round(cp.contextWindow)
        // 取真实模型窗口与显式安全上限的较小值，绝不用 500k 覆盖 272k 模型真实窗口
        contextWindow = defaultWindow > 0 ? Math.min(defaultWindow, measured) : measured
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
 * 将当前压力水位与真实有效上下文窗口同步到 Python SQLite 单一真相时钟字段，并带回实时 node_status。
 */
export async function syncLivePressureToDb(
  ctx,
  agent,
  bridge,
  workspaceRoot,
  nodeId,
  defaultWindow = 500_000,
  { signal = null } = {},
) {
  if (!nodeId || !bridge) return null
  if (signal?.aborted) return null
  const sample = sampleAgentContextPressure(ctx, agent, defaultWindow)
  try {
    return await bridge.control(
      'control_plane/sync_pressure',
      {
        workspace_root: workspaceRoot,
        node_id: nodeId,
        pressure_tokens: sample.pressureTokens,
        effective_context_window: sample.contextWindow,
      },
      { signal },
    )
  } catch (err) {
    if (signal?.aborted || err?.name === 'AbortError' || err?.code === 'ABORT_ERR') {
      throw err
    }
    return null
  }
}

/**
 * 实时追帧观测器：在探索者连续调用原生工具（`read`/`edit`/`pwsh`）期间同步动态真实上下文时钟，
 * 并在纯推导/零仪器场景下照常准时触发 37% 反思、70% 交接或外部终态中止收束。
 */
export function installLiveClockObservers({
  rootCtx,
  agentCtx,
  agent,
  bridge,
  workspaceRoot,
  nodeId = '',
  role,
  contextWindowTokens = 500_000,
  onNativeThresholdHit,
}) {
  if (role !== 'explorer' || !nodeId || !bridge) {
    return () => {}
  }
  const disposers = []
  let lastTriggerEmitted = ''
  let lastSyncAtMs = 0
  const THROTTLE_MS = 15_000

  const checkAndSync = async (sourceHook, { force = false } = {}) => {
    const nowMs = Date.now()
    const sample = sampleAgentContextPressure(rootCtx, agent, contextWindowTokens)
    const estPct = sample.pressureTokens / Math.max(1, sample.contextWindow || contextWindowTokens || 500_000)
    // 裁决五：每步工具调用间隙按 >=15s 节流写库（跨 37%/70% 阈值或 force 时立即写），避免争抢单写者锁同时消除长回合盲区
    if (!force && nowMs - lastSyncAtMs < THROTTLE_MS && estPct < 0.37) {
      return
    }
    lastSyncAtMs = nowMs
    const syncRes = await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId, contextWindowTokens)
    const rowData = syncRes?.data ?? syncRes ?? {}
    const nodeStatus = String(rowData.node_status || '')
    if (nodeStatus && nodeStatus !== 'EXPLORING' && nodeStatus !== 'ACTIVE_REVISING') {
      if (lastTriggerEmitted !== 'NODE_TERMINATED') {
        lastTriggerEmitted = 'NODE_TERMINATED'
        onNativeThresholdHit?.({ trigger: 'NODE_TERMINATED', nodeStatus, sourceHook })
      }
      return
    }
    const unlocked = Boolean(rowData.first_reflection_unlocked)
    const effWindow = Number(rowData.effective_context_window || rowData.context_window_tokens || sample.contextWindow || contextWindowTokens || 500_000)

    const { pressurePct, trigger } = evaluateContextClockTrigger({
      pressureTokens: sample.pressureTokens,
      contextWindow: effWindow,
      firstReflectionUnlocked: unlocked,
    })

    if (trigger === 'HANDOFF_70' && lastTriggerEmitted !== 'HANDOFF_70') {
      lastTriggerEmitted = 'HANDOFF_70'
      onNativeThresholdHit?.({ trigger: 'HANDOFF_70', pressurePct, sourceHook })
    } else if (trigger === 'REFLECT_37' && !lastTriggerEmitted) {
      lastTriggerEmitted = 'REFLECT_37'
      onNativeThresholdHit?.({ trigger: 'REFLECT_37', pressurePct, sourceHook })
    }
    return rowData
  }

  try {
    const dResult = agentCtx.on('tools/result', (exec) => {
      const tname = String(exec?.name || '')
      if (tname && tname !== 'run_isolated_eval') {
        void checkAndSync(`tools/result:${tname}`, { force: false })
      }
    })
    if (typeof dResult === 'function') disposers.push(dResult)
  } catch {}

  try {
    const dStep = agentCtx.on('agent/pre-step', async (_payload, next) => {
      const node = await checkAndSync('agent/pre-step', { force: true })
      if (node?.control_state === 'DRAIN_AFTER_TURN') return { kind: 'reject' }
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
  contextWindowTokens = 500_000,
  onTurnSignal,
  sessionEpochId = 1,
  onOperatorReceipt = null,
  onHumanMessage,
}) {
  const disposers = []
  const gate = ['explorer', 'gw_chief'].includes(role) ? watchHumanMandate(rootCtx, agent.session, onHumanMessage) : null
  if (gate) disposers.push(() => gate.dispose())
  if (role === 'gw_chief' && typeof agentCtx.tools?.guard === 'function') {
    disposers.push(agentCtx.tools.guard((call) => {
      if (!DIRECT_CHIEF_TOOLS.has(call?.name) || gate.current()) return undefined
      const handback = call.arguments?.handback_id
      if (call.name === 'chief_operate' && typeof handback === 'string' && handback.trim()) return undefined
      return 'ERR_AUTH: 请由人在科研总控会话直接下令，或提供待核销的分支转办单。'
    }))
  }
  const allowedSet = new Set(allowedToolNames || [])
  const schemaByName = new Map((toolSchemas || []).map((t) => [t.name, t]))

  for (const toolName of allowedSet) {
    const schemaDef = schemaByName.get(toolName)
    if (!schemaDef) continue

    const normalizedParams = normalizeSchemaForDsh(
      schemaDef.inputSchema || { type: 'object', properties: {} },
      { toolName },
    )
    // DSH 工具定义级协作超时 >= 内层 bridge 分级最大合法超时，避免外层误杀合法 official/heavy 计算
    const declaredTimeoutMs = typeof bridge?.resolveToolTimeoutMs === 'function'
      ? bridge.resolveToolTimeoutMs(toolName, { tier: 'heavy' })
      : 60_000

    const disposeTool = agentCtx.tools.register({
      name: toolName,
      description: String(schemaDef.description || `Greatwall MCP tool: ${toolName}`),
      parameters: normalizedParams,
      timeoutMs: declaredTimeoutMs,
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value) {
          return [{ type: 'text', text: JSON.stringify(value) }]
        },
      },
      async execute(args, exec) {
        const execSignal = exec?.signal || null
        if (role === 'explorer' && nodeId) {
          await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId, contextWindowTokens, {
            signal: execSignal,
          })
        }

        // 基础设施/RPC/取消/超时故障由 bridge.callTool 直接 throw，交由 DSH 管线如实记录工具失败；
        // 科研/制度返回（{ ok: false, error_code, ... }）保留为结构化 JSON 收据供模型消费自纠。
        let res = await bridge.callTool(toolName, args, {
          workspaceRoot,
          role,
          sessionId: agent.id,
          sessionEpochId,
          humanMandate: gate?.current(),
          signal: execSignal,
        })

        if (toolName === 'chief_read' && res?.data?.session_id) {
          res = await readChiefTranscript(rootCtx, res.data.session_id, args)
        }

        if (!res || typeof res !== 'object') {
          throw new Error(`MCP 工具 ${toolName} 返回非法非对象响应`)
        }

        if (res.ok && (DIRECT_CHIEF_TOOLS.has(toolName) || toolName === 'handback_to_chief')) {
          onOperatorReceipt?.(toolName)
        }

        if (role === 'explorer' && toolName === 'run_isolated_eval' && res?.ok) {
          if (nodeId) {
            await syncLivePressureToDb(rootCtx, agent, bridge, workspaceRoot, nodeId, contextWindowTokens, {
              signal: execSignal,
            })
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

        return res
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
