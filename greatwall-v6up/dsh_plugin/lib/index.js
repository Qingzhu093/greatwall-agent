/**
 * dsh-greatwall-v6up v2.2 —— DSH Cordis 插件主入口（100% 原生 API 对齐版）。
 *
 * - 零 `@deepseek-ai/*` 静态 import，彻底兼容外部 `link:` 插件挂载；
 * - 注册科研主技能卡与技能台账读取；
 * - 对宿主暴露 `ctx.greatwall` 服务对象，驱动 `GreatwallMcpBridge` + `GreatwallOrchestrator`（`ctx.agents.create()` + `tools.restrict/guard/register` + `sessionProjections(['contextPressure'])` / `tokenMeter.measure()` + `sessionQuery` 黑匣子 + `exec.concludeTurn()` 回合间隙顺序控制流）。
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

  // 0. 安装兼容本地 preset 文件，并在 0.2.2-rc.3 AgentPresetRegistry 可用时幂等热注册 5 套声明式预设（与 cordis.patch.yml 互为双保险）
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

  // 1. 按需向 DSH 技能系统注册 `core_python/skills/` 学术主流程 SOP（使用 ctx.get 安全读取可选服务）
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

  /**
   * 创建一个绑定特定科研工作区的 V6-Up v2.2 独立运行控制器（包含持久化 Single-Writer Python MCP 桥 + DSH External Orchestrator）。
   */
  function createSessionController(opts = {}) {
    const workspaceRoot = path.resolve(opts.workspaceRoot || process.cwd())
    const dataDir = opts.dataDir || config.dataDir || ''
    const bridge = new GreatwallMcpBridge({
      corePythonRoot: coreRoot,
      workspaceRoot,
      dataDir,
      pythonBin: opts.pythonBin || config.pythonBin,
      requestTimeoutMs: opts.requestTimeoutMs ?? config.requestTimeoutMs ?? 60_000,
    })
    // 自动将当前工作区的隔离 DB 与 eval_artifacts 根目录注入方案 A protectedDirs
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
      async initEpoch({ goalMd = '', requiredQuestions = ['Q1'], contracts = {}, stage = 'STAGE1_PARSE0', epochId = 1 } = {}) {
        return bridge.control('control_plane/init_epoch', {
          workspace_root: workspaceRoot,
          goal_md: goalMd,
          required_questions: requiredQuestions,
          contracts,
          stage,
          epoch_id: epochId,
        })
      },
      async scheduleSnapshot(maxConcurrentWorkers = null) {
        return bridge.control('control_plane/schedule_snapshot', {
          workspace_root: workspaceRoot,
          ...(maxConcurrentWorkers ? { max_concurrent_workers: maxConcurrentWorkers } : {}),
        })
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

  // 2. 向 DSH 主对话注册真异步调度入口工具 `greatwall_orchestrate`（不绑 exec.signal，彻底免疫 600s 连坐误杀）
  let disposeEntryTool = () => {}
  if (ctx?.tools && typeof ctx.tools.register === 'function') {
    disposeEntryTool = ctx.tools.register({
      name: 'greatwall_orchestrate',
      description:
        '在 DeepSeek Harness 桌面会话中初始化或非阻塞操控长城科研共同体 V6-Up (v2.2) 后台异步事件池（start 1秒返回、status/pause/resume/stop/intervene）。',
      parameters: {
        type: 'object',
        properties: {
          action: {
            type: 'string',
            enum: ['init', 'start', 'pause', 'resume', 'stop', 'status', 'intervene'],
            description: 'init=初始化纪元; start=后台异步启动调度事件池(1s返回); pause/resume/stop=暂停/恢复/停止; status=查看实时状态与遥测; intervene=下发人类纠偏干预指令',
          },
          workspace_root: {
            type: 'string',
            description: '科研工作区根目录绝对路径',
          },
          goal_md: {
            type: 'string',
            description: '课题总目标与必答子题描述（init 或 start 时可选注入）',
          },
          required_questions: {
            type: 'array',
            items: { type: 'string' },
            description: '必答子题列表，如 ["Q1", "Q2", "Q3", "Q4"]',
          },
          contracts: {
            type: 'object',
            description: '各子题契约字典，支持 depends_on_questions 与 public_input_sample',
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
            description: 'intervene 下发的纠偏/指令内容',
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
        if (act === 'init') {
          const initRes = await ctrl.initEpoch({
            goalMd: String(args.goal_md || ''),
            requiredQuestions: Array.isArray(args.required_questions) && args.required_questions.length
              ? args.required_questions
              : ['Q1'],
            contracts: args.contracts && typeof args.contracts === 'object' ? args.contracts : {},
          })
          return { ok: Boolean(initRes?.ok), action: act, init: initRes, status: await ctrl.orchestrator.getControlStatus() }
        }
        if (act === 'start') {
          if (args.goal_md || (Array.isArray(args.required_questions) && args.required_questions.length)) {
            await ctrl.initEpoch({
              goalMd: String(args.goal_md || ''),
              requiredQuestions: Array.isArray(args.required_questions) && args.required_questions.length
                ? args.required_questions
                : ['Q1'],
              contracts: args.contracts && typeof args.contracts === 'object' ? args.contracts : {},
            })
          }
          // 注意：严禁传入调用方的 exec.signal！后台池使用独立 _loopAbortController 免受 600s 墙钟连坐
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
    version: '2.2.0',
    pluginRoot: PLUGIN_ROOT,
    corePythonRoot: coreRoot,
    config,
    canonicalRoles: CANONICAL_ROLES,
    roleEffortMap: ROLE_EFFORT_MAP,
    roleMcpTools: ROLE_MCP_TOOLS,
    roleNativeAllowTools: ROLE_NATIVE_ALLOW_TOOLS,
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

  // 安全停机清理所有持久化 Python MCP 进程与保活子智能体
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
