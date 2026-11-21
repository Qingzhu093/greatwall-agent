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
        stage = 'STAGE1_PARSE0',
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
          stage,
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
          stage: optsCompat.stage || 'STAGE1_PARSE0',
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
        '在 DeepSeek Harness 桌面会话中签署 Parse 0 或非阻塞操控长城科研共同体 V6-Up (v3.0) 后台异步事件池（init / start / pause / resume / stop / human_stop / status / intervene）。',
      parameters: {
        type: 'object',
        properties: {
          action: {
            type: 'string',
            enum: ['init', 'start', 'pause', 'resume', 'stop', 'human_stop', 'status', 'intervene'],
            description: 'init=签署Parse0六项表单; start=后台异步启动事件池; pause/resume/stop=暂停/恢复/停止; human_stop=写入人类叫停真源并允许PARTIAL_ON_HUMAN_STOP结项; status=查实时状态; intervene=定向纠偏',
          },
          workspace_root: {
            type: 'string',
            description: '科研工作区根目录绝对路径',
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
          max_concurrent_workers: {
            type: 'integer',
            description: '最大并发探索者槽位数（默认 6，硬上限 10）',
          },
          target_type: {
            type: 'string',
            enum: ['global', 'question', 'node', 'role'],
            description: 'intervene 干预对象类型',
          },
          target_id: {
            type: 'string',
            description: 'intervene 干预目标 ID（如 Q2、node_q2_003 或 ALL）',
          },
          directive: {
            type: 'string',
            description: 'intervene 下发的纠偏/指令内容，或 human_stop 的备注说明',
          },
          intervention_action: {
            type: 'string',
            enum: ['steer', 'requeue', 'unlock', 'abort_node'],
            description: 'intervene 具体操作，默认 steer',
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
        }

        if (act === 'init') {
          const initRes = await ctrl.initParse0(initPayload)
          return { ok: Boolean(initRes?.ok), action: act, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
        }
        if (act === 'start') {
          if (goalText || (Array.isArray(args.subquestions) && args.subquestions.length) || (Array.isArray(args.required_questions) && args.required_questions.length)) {
            await ctrl.initParse0(initPayload)
          }
          const startRes = await ctrl.orchestrator.startBackground({
            maxConcurrentWorkers: args.max_concurrent_workers ? Number(args.max_concurrent_workers) : null,
          })
          return { ok: true, action: act, ...startRes }
        }
        if (act === 'pause') {
          return { ok: true, action: act, ...ctrl.orchestrator.pauseBackground() }
        }
        if (act === 'resume') {
          return { ok: true, action: act, ...ctrl.orchestrator.resumeBackground() }
        }
        if (act === 'stop') {
          return { ok: true, action: act, ...(await ctrl.orchestrator.stopBackground('MCP_STOP')) }
        }
        if (act === 'human_stop') {
          return { ok: true, action: act, ...(await ctrl.orchestrator.humanStop(String(args.directive || 'MCP_HUMAN_STOP'))) }
        }
        if (act === 'intervene') {
          return {
            ok: true,
            action: act,
            ...(await ctrl.orchestrator.intervene({
              targetType: args.target_type || 'global',
              targetId: args.target_id || 'ALL',
              directive: args.directive || '',
              action: args.intervention_action || 'steer',
            })),
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
    dataDir: config.dataDir || '',
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
