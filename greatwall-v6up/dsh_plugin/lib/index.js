/**
 * dsh-greatwall-v6up v3.0 —— DSH Cordis 插件主入口（100% 原生 API 对齐版）。
 *
 * - 零 `@deepseek-ai/*` 静态 import，兼容外部 `link:` 插件挂载；
 * - 注册 6 套极净角色 Preset 与核心科研技能包；
 * - 暴露 `ctx.greatwall` 服务与 `greatwall_orchestrate` 真异步控制入口（含 Parse 0 六项启动表单与 `human_stop` 合法叫停真源）。
 * @module dsh-greatwall-v6up
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CANONICAL_ROLES,
  ROLE_EFFORT_MAP,
  ROLE_MCP_TOOLS,
  ROLE_NATIVE_ALLOW_TOOLS,
  loadCoreRuntimeConfig,
  loadRolePrompts,
  resolvePlatformAllowedTools,
} from './prompts.js'
import { loadSkillLedger, loadSkillPack, registerSkillPack } from './skillpack.js'
import { GreatwallMcpBridge } from './mcp_bridge.js'
import { GreatwallOrchestrator } from './orchestrator.js'
import { ensurePresetsInstalled, registerPresetsOnRegistry } from './presets.js'
import { resolveTelemetryFilePath } from './telemetry.js'
import { registerGreatwallConsoleRoutes } from './console_routes.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const PLUGIN_ROOT = path.resolve(__dirname, '..')
export const CORE_PYTHON_ROOT = path.resolve(PLUGIN_ROOT, '..', 'core_python')

export const name = 'dsh-greatwall-v6up'

export const inject = ['tools', 'systemPrompt', 'agents', 'sessionProjections', 'tokenMeter', 'sessionQuery']

/**
 * Cordis 插件激活入口。
 * @param {any} ctx
 * @param {Record<string, any>} [config]
 */
export function apply(ctx, config = {}) {
  const logger = ctx?.logger?.(name) ?? console
  const coreRoot = config.corePythonRoot ? path.resolve(config.corePythonRoot) : CORE_PYTHON_ROOT
  const skillsDir = path.join(coreRoot, 'skills')

  // 0. 写入本地 6 套预设并在 AgentPresetRegistry 可用时幂等热注册
  try {
    ensurePresetsInstalled({ localPresetsDir: path.join(PLUGIN_ROOT, 'presets') })
  } catch (err) {
    logger.warn?.('[dsh-greatwall-v6up] preset install warning:', err?.message || err)
  }

  let disposeRegisteredPresets = () => {}
  if (typeof ctx?.inject === 'function') {
    const disposeApInject = ctx.inject(['agentPresets'], (apCtx) => {
      const regHandle = registerPresetsOnRegistry(apCtx, apCtx.agentPresets, { logger })
      return () => {
        void regHandle.then((h) => h?.disposeAll?.()).catch(() => {})
      }
    })
    if (typeof disposeApInject === 'function') {
      disposeRegisteredPresets = disposeApInject
    }
  }

  // 1. 注册 `core_python/skills/` 学术主流程 SOP
  const skillsSvc = ctx?.get?.('skills')
  if (skillsSvc && typeof skillsSvc.register === 'function') {
    const { skills, problems } = loadSkillPack(skillsDir)
    if (problems.length) {
      logger.warn?.('[dsh-greatwall-v6up] skillpack warnings:', problems)
    }
    const { registered, failed } = registerSkillPack(skillsSvc, skills, { provider: name })
    if (failed.length) {
      logger.warn?.('[dsh-greatwall-v6up] skillpack registration failures:', failed)
    } else if (registered.length) {
      logger.info?.(`[dsh-greatwall-v6up] registered skills: ${registered.join(', ')}`)
    }
  }

  /** @type {Set<{ dispose: () => Promise<void> }>} */
  const controllers = new Set()
  /** @type {Map<string, any>} */
  const activeControllersByWs = new Map()

  /** 创建一个绑定特定科研工作区的 V6-Up v3.0 独立运行控制器。 */
  function createSessionController(opts = {}) {
    const workspaceRoot = path.resolve(opts.workspaceRoot || process.cwd())
    const dataDir = opts.dataDir || config.dataDir || ''
    const bridge = new GreatwallMcpBridge({
      corePythonRoot: coreRoot,
      workspaceRoot,
      dataDir,
      pythonBin: opts.pythonBin || config.pythonBin,
      requestTimeoutMs: opts.requestTimeoutMs ?? config.requestTimeoutMs ?? 60_000,
      longToolTimeoutMs: opts.longToolTimeoutMs ?? config.longToolTimeoutMs ?? 300_000,
    })
    const wsDataRoot = path.dirname(resolveTelemetryFilePath({ dataDir, workspaceRoot }))
    const protectedDirs = [...new Set([wsDataRoot, ...(opts.protectedDirs || [])])]

    const orchestrator = new GreatwallOrchestrator({
      ctx,
      bridge,
      corePythonRoot: coreRoot,
      workspaceRoot,
      dataDir,
      parentAgent: opts.parentAgent || null,
      defaultAgentOptions: opts.defaultAgentOptions || config.defaultAgentOptions || {},
      protectedDirs,
    })

    const controller = {
      workspaceRoot,
      corePythonRoot: coreRoot,
      bridge,
      orchestrator,
      async initParse0({
        goalAndCompletionMd = '',
        goalMd = '',
        subquestions = ['Q1'],
        questionOrder = [],
        initialInstruments = [],
        seedFamilies = [],
        totalBudget = {},
        minCommitmentWindowSec = 0,
        deliverySpecMd = '',
        sharedInputsRelPaths = [],
        stage = null,
        epochId = 1,
      } = {}) {
        return bridge.control('control_plane/init_parse0', {
          workspace_root: workspaceRoot,
          goal_and_completion_md: goalAndCompletionMd || goalMd,
          subquestions,
          question_order: questionOrder,
          initial_instruments: initialInstruments,
          seed_families: seedFamilies,
          total_budget: totalBudget,
          min_commitment_window_sec: minCommitmentWindowSec,
          delivery_spec_md: deliverySpecMd,
          shared_inputs_rel_paths: sharedInputsRelPaths,
          ...(stage ? { stage } : {}),
          epoch_id: epochId,
        })
      },
      async initEpoch(optsCompat = {}) {
        return controller.initParse0({
          goalAndCompletionMd: optsCompat.goalAndCompletionMd || optsCompat.goalMd || '',
          subquestions: optsCompat.subquestions || optsCompat.requiredQuestions || ['Q1'],
          questionOrder: optsCompat.questionOrder || [],
          minCommitmentWindowSec: optsCompat.minCommitmentWindowSec || 0,
          deliverySpecMd: optsCompat.deliverySpecMd || '',
          stage: optsCompat.stage || null,
          epochId: optsCompat.epochId || 1,
        })
      },
      async scheduleSnapshot(maxConcurrentWorkers = null) {
        return bridge.control('control_plane/schedule_snapshot', {
          workspace_root: workspaceRoot,
          ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
        })
      },
      async humanStop(note = 'HUMAN_UI_OR_CLI_STOP') {
        return orchestrator.humanStop(note)
      },
      async runUntilClosed(runOpts = {}) {
        return orchestrator.runUntilClosed(runOpts)
      },
      async dispose() {
        controllers.delete(controller)
        activeControllersByWs.delete(normalizedKey)
        await orchestrator.disposeAll()
        await bridge.dispose()
      },
    }

    const normalizedKey = workspaceRoot.toLowerCase()
    controllers.add(controller)
    activeControllersByWs.set(normalizedKey, controller)
    return controller
  }

  // 2. 向 DSH 主对话注册真异步调度入口工具 `greatwall_orchestrate`
  let disposeEntryTool = () => {}
  if (ctx?.tools && typeof ctx.tools.register === 'function') {
    disposeEntryTool = ctx.tools.register({
      name: 'greatwall_orchestrate',
      description:
        '在 DeepSeek Harness 桌面会话中签署 Parse 0 或非阻塞操控长城科研共同体 V6-Up (v3.0) 后台异步事件池（init / start / pause / resume / stop / human_stop / abort_node / submit_works_ticket / sync_rulings / inspect / status）。',
      parameters: {
        type: 'object',
        properties: {
          action: {
            type: 'string',
            enum: ['init', 'start', 'pause', 'resume', 'stop', 'human_stop', 'abort_node', 'submit_works_ticket', 'sync_rulings', 'inspect', 'status'],
            description: 'init=签署Parse0六项表单; start=锁定模型绑定并异步启动事件池; pause/resume/stop=暂停/恢复并同步rulings/停止; human_stop=写入人类叫停真源; abort_node=确定性中止单节点; submit_works_ticket=向科研仪器科签发正式工单并立刻唤醒工造司修复/升级仪器; sync_rulings=同步工作区rulings补充裁决; inspect=深度只读透视仪器/工单/谱系/盲审/监察状态; status=查实时状态',
          },
          workspace_root: {
            type: 'string',
            description: '科研工作区根目录绝对路径',
          },
          provider: {
            type: 'string',
            description: '可选：显式锁定模型提供商 ID（如 deepseek-account）；缺省自动继承主控当前选中模型',
          },
          model: {
            type: 'string',
            description: '可选：显式锁定模型 ID（如 deepseek-flash）；缺省自动继承主控当前选中模型，无法解析将拒启',
          },
          effective_context_window: {
            type: 'integer',
            description: '可选：显式上下文窗口上限（最终按 min(500000, model_physical_window) 取值）',
          },
          context_window_tokens: {
            type: 'integer',
            description: 'effective_context_window 兼容字段',
          },
          goal_and_completion_md: {
            type: 'string',
            description: 'Parse 0 第 1 项：课题总目标与明确完成判据（兼容 goal_md）',
          },
          goal_md: {
            type: 'string',
            description: '课题总目标兼容字段（等同 goal_and_completion_md）',
          },
          subquestions: {
            type: 'array',
            items: { type: 'string' },
            description: 'Parse 0 第 2 项：必答子题列表（兼容 required_questions），如 ["Q1","Q2"]',
          },
          required_questions: {
            type: 'array',
            items: { type: 'string' },
            description: '子题列表兼容字段（等同 subquestions）',
          },
          question_order: {
            type: 'array',
            items: { type: 'string' },
            description: '可选：跨题推进顺序提示（如 ["Q1","Q2"]）',
          },
          initial_instruments: {
            type: 'array',
            items: { type: 'object' },
            description: 'Parse 0 第 3 项：初始科研仪器清单（纯理论题可留空数组）',
          },
          seed_families: {
            type: 'array',
            items: { type: 'object' },
            description: 'Parse 0 第 4 项：种子方法学派提示（可留空数组由后勤动态建档）',
          },
          total_budget: {
            type: 'object',
            description: 'Parse 0 第 5 项：总预算约束，如 {"max_total_handoffs": 30, "max_official_evals": 100}',
          },
          min_commitment_window_sec: {
            type: 'integer',
            description: 'Parse 0 最短投入时间窗口（秒，默认 0；未满窗口前禁止提前收工，除非控制面执行 human_stop）',
          },
          delivery_spec_md: {
            type: 'string',
            description: 'Parse 0 最终交付物形态规范（如论文格式、复现脚本或形式化内核要求）',
          },
          shared_inputs_rel_paths: {
            type: 'array',
            items: { type: 'string' },
            description: '可选：额外声明的工作区公开题面/输入数据/裁决文档相对路径（自动只读挂载至沙箱 inputs/）',
          },
          max_concurrent_workers: {
            type: 'integer',
            description: '最大并发探索者槽位数（默认 6，硬上限 10）',
          },
          node_id: {
            type: 'string',
            description: 'abort_node 要中止的目标节点 ID，或 inspect 要深度查看的节点 ID（如 node_q1_xxxx）',
          },
          reason: {
            type: 'string',
            description: 'abort_node 中止原因、human_stop 备注说明，或 submit_works_ticket 问题描述兼容字段',
          },
          question_id: {
            type: 'string',
            description: 'submit_works_ticket 目标子题编号（如 Q1 / Q3 / ALL，默认 ALL）',
          },
          ticket_type: {
            type: 'string',
            enum: ['INSTRUMENT_ERROR', 'PAIN_POINT', 'DUPLICATE_TOOL', 'EXPLOIT'],
            description: 'submit_works_ticket 工单类型（默认 INSTRUMENT_ERROR）',
          },
          instrument_id: {
            type: 'string',
            description: 'submit_works_ticket 可选：指定故障或需升级的仪器 ID（如 inst_surrogate_simulator）',
          },
          description: {
            type: 'string',
            description: 'submit_works_ticket 必填：仪器缺陷、校准问题或改造需求详细说明',
          },
          refresh_active_worktrees: {
            type: 'boolean',
            description: 'sync_rulings 可选：是否同时刷新在线探索者的 inputs/rulings/（默认 false，仅升版 spec_revision）',
          },
        },
        required: ['action', 'workspace_root'],
      },
      output: {
        schema: { type: 'object', additionalProperties: true },
        render(_args, value) {
          return [{ type: 'text', text: JSON.stringify(value) }]
        },
      },
      async execute(args, exec) {
        const ws = path.resolve(String(args.workspace_root))
        const key = ws.toLowerCase()
        let ctrl = activeControllersByWs.get(key)
        if (!ctrl) {
          const callerOpts = exec?.agent?.options || {}
          ctrl = createSessionController({
            workspaceRoot: ws,
            parentAgent: exec?.agent || null,
            defaultAgentOptions: {
              ...(callerOpts.provider ? { provider: callerOpts.provider } : {}),
              ...(callerOpts.model ? { model: callerOpts.model } : {}),
              ...(callerOpts.reasoningEffort ? { reasoningEffort: callerOpts.reasoningEffort } : {}),
            },
          })
        } else if (exec?.agent) {
          ctrl.orchestrator.parentAgent = exec.agent
          if (ctrl.orchestrator.host) ctrl.orchestrator.host.parentAgent = exec.agent
        }
        const act = String(args.action)
        const goalText = String(args.goal_and_completion_md || args.goal_md || '')
        const subQs = Array.isArray(args.subquestions) && args.subquestions.length
          ? args.subquestions
          : (Array.isArray(args.required_questions) && args.required_questions.length ? args.required_questions : ['Q1'])

        const initPayload = {
          goalAndCompletionMd: goalText,
          subquestions: subQs,
          questionOrder: Array.isArray(args.question_order) ? args.question_order : [],
          initialInstruments: Array.isArray(args.initial_instruments) ? args.initial_instruments : [],
          seedFamilies: Array.isArray(args.seed_families) ? args.seed_families : [],
          totalBudget: args.total_budget && typeof args.total_budget === 'object' ? args.total_budget : {},
          minCommitmentWindowSec: Number(args.min_commitment_window_sec || 0),
          deliverySpecMd: String(args.delivery_spec_md || ''),
          sharedInputsRelPaths: Array.isArray(args.shared_inputs_rel_paths) ? args.shared_inputs_rel_paths : [],
        }

        if (act === 'init') {
          const initRes = await ctrl.initParse0(initPayload)
          return { ok: Boolean(initRes?.ok), action: act, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
        }
        if (act === 'start') {
          const hasInlineInit = Boolean(
            goalText ||
              (Array.isArray(args.subquestions) && args.subquestions.length) ||
              (Array.isArray(args.required_questions) && args.required_questions.length),
          )
          // start 只在尚未启动且未签署 Parse 0 的首次冷启动时顺手立项；运行中或已签过契约时绝不借 start 悄悄覆写契约
          if (hasInlineInit && !ctrl.orchestrator._backgroundTask) {
            const preSnap = await ctrl.scheduleSnapshot()
            if (preSnap?.ok && !preSnap?.data?.parse0_signed) {
              const initRes = await ctrl.initParse0(initPayload)
              if (!initRes?.ok) {
                return { ok: false, action: act, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
              }
            }
          }
          const explicitAgentOpts = {}
          if (args.provider) explicitAgentOpts.provider = String(args.provider).trim()
          if (args.model) explicitAgentOpts.model = String(args.model).trim()
          const expWin = Number(args.effective_context_window || args.context_window_tokens || 0)
          if (Number.isFinite(expWin) && expWin > 0) explicitAgentOpts.effectiveContextWindow = expWin

          const startRes = await ctrl.orchestrator.startBackground({
            maxConcurrentWorkers: args.max_concurrent_workers ? Number(args.max_concurrent_workers) : null,
            agentOptions: explicitAgentOpts,
            callerAgent: exec?.agent || null,
          })
          return { ok: Boolean(startRes?.started), action: act, ...startRes }
        }
        if (act === 'pause') {
          return { ok: true, action: act, ...ctrl.orchestrator.pauseBackground() }
        }
        if (act === 'resume') {
          return { ok: true, action: act, ...(await ctrl.orchestrator.resumeBackground()) }
        }
        if (act === 'stop') {
          const stopRes = await ctrl.orchestrator.stopBackground('MCP_STOP')
          await ctrl.bridge.closeIdleChild?.()
          return { ok: true, action: act, ...stopRes }
        }
        if (act === 'human_stop') {
          return { ok: true, action: act, ...(await ctrl.orchestrator.humanStop(String(args.reason || 'MCP_HUMAN_STOP'))) }
        }
        if (act === 'abort_node') {
          const res = await ctrl.orchestrator.abortNode(
            String(args.node_id || ''),
            String(args.reason || 'MCP_ABORT_NODE'),
          )
          return { ok: Boolean(res?.aborted), action: act, ...res }
        }
        if (act === 'submit_works_ticket') {
          const res = await ctrl.orchestrator.submitWorksTicket({
            questionId: String(args.question_id || 'ALL'),
            ticketType: String(args.ticket_type || 'INSTRUMENT_ERROR'),
            instrumentId: args.instrument_id ? String(args.instrument_id) : null,
            description: String(args.description || args.reason || ''),
            source: 'main_controller',
          })
          return { ok: Boolean(res?.submitted), action: act, ...res }
        }
        if (act === 'sync_rulings') {
          const res = await ctrl.orchestrator.syncPublicRulings(Boolean(args.refresh_active_worktrees))
          return { ok: Boolean(res?.synced), action: act, ...res }
        }
        if (act === 'inspect') {
          const insp = await ctrl.bridge.control('control_plane/ui_inspector', {
            workspace_root: ws,
            ...(args.node_id ? { selected_node_id: String(args.node_id) } : {}),
          })
          return {
            ok: Boolean(insp?.ok),
            action: act,
            inspector: insp?.data || null,
            error: insp?.ok ? null : (insp?.error || 'inspect failed'),
          }
        }
        if (act === 'status') {
          return {
            ok: true,
            action: act,
            ...(await ctrl.orchestrator.getControlStatus()),
          }
        }
        return { ok: false, error: `未知 action: ${act}` }
      },
    })
  }

  const serviceApi = {
    version: '3.0.0',
    pluginRoot: PLUGIN_ROOT,
    corePythonRoot: coreRoot,
    config,
    canonicalRoles: CANONICAL_ROLES,
    roleEffortMap: ROLE_EFFORT_MAP,
    roleMcpTools: ROLE_MCP_TOOLS,
    roleNativeAllowTools: ROLE_NATIVE_ALLOW_TOOLS,
    resolvePlatformAllowedTools,
    loadRuntimeConfig: () => loadCoreRuntimeConfig(coreRoot),
    loadRolePrompts: () => loadRolePrompts(coreRoot),
    loadSkillLedger: () => loadSkillLedger(skillsDir),
    createSessionController,
  }

  ctx.provide?.('greatwall', serviceApi, true)
  try {
    ctx.set?.('greatwall', serviceApi)
  } catch {
    ctx.greatwall = serviceApi
  }

  const disposeConsoleRoutes = registerGreatwallConsoleRoutes(ctx, {
    activeControllersByWs,
    corePythonRoot: coreRoot,
    dataDir: config.dataDir || '',
    pythonBin: config.pythonBin || '',
    logger,
  })

  ctx.on?.('dispose', async () => {
    try { disposeEntryTool() } catch {}
    try { disposeConsoleRoutes() } catch {}
    try { disposeRegisteredPresets() } catch {}
    activeControllersByWs.clear()
    const active = [...controllers]
    await Promise.allSettled(active.map((c) => c.dispose()))
  })

  return serviceApi
}
