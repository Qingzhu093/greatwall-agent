/**
 * dsh-greatwall-v6up v3.0 —— DSH 0.2.2-rc.5 Cordis 插件纯装配主入口。
 *
 * 职责极度聚焦（零业务分发逻辑堆砌）：
 * - 导出真接线 Config 元数据与 `resolvePluginConfig`（剔除未消费的假旋钮）；
 * - 在 `agentPresets` 可用时按需幂等补注册单源 Preset（不再向宿主机写 `~/.dsh/.agent-presets/`）；
 * - 注册 `core_python/skills/` 学术主流程 SOP 并托管其 disposer；
 * - 创建统一控制服务 `GreatwallControlService`（One Operation, Two Callers），分别挂载主控工具与 HTTP 控制台路由；
 * - 在插件停用/卸载时完整回收全部技能、Preset、工具、路由、活跃子会话与 Python 子进程。
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
import { Config, DEFAULT_PLUGIN_CONFIG, resolvePluginConfig } from './config.js'
import { loadSkillLedger, loadSkillPack, registerSkillPack } from './skillpack.js'
import { registerPresetsOnRegistry } from './presets.js'
import { GreatwallControlService } from './control_service.js'
import { registerOrchestrateTool } from './orchestrate_tool.js'
import { registerGreatwallConsoleRoutes } from './console_routes.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const PLUGIN_ROOT = path.resolve(__dirname, '..')
export const CORE_PYTHON_ROOT = path.resolve(PLUGIN_ROOT, '..', 'core_python')

export const name = 'dsh-greatwall-v6up'
export const inject = ['tools', 'systemPrompt', 'agents', 'sessionProjections', 'tokenMeter', 'sessionQuery']
export { Config, DEFAULT_PLUGIN_CONFIG, resolvePluginConfig }

/**
 * Cordis 插件激活入口。
 * @param {any} ctx
 * @param {Record<string, any>} [rawConfig]
 */
export function apply(ctx, rawConfig = {}) {
  const logger = ctx?.logger?.(name) ?? console
  const config = resolvePluginConfig(rawConfig, CORE_PYTHON_ROOT)
  const coreRoot = config.corePythonRoot
  const skillsDir = path.join(coreRoot, 'skills')

  // 1. 幂等热注册单源 Preset（当宿主未由 cordis.patch.yml 预挂载时补齐），注销句柄全量托管
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

  // 2. 注册 `core_python/skills/` 学术主流程 SOP（回收全部 skill disposers）
  let disposeSkills = () => {}
  const skillsSvc = ctx?.get?.('skills')
  if (skillsSvc && typeof skillsSvc.register === 'function') {
    const { skills, problems } = loadSkillPack(skillsDir)
    if (problems.length) {
      logger.warn?.('[dsh-greatwall-v6up] skillpack warnings:', problems)
    }
    const { registered, failed, disposeAll } = registerSkillPack(skillsSvc, skills, { provider: name })
    disposeSkills = disposeAll
    if (failed.length) {
      logger.warn?.('[dsh-greatwall-v6up] skillpack registration failures:', failed)
    } else if (registered.length) {
      logger.info?.(`[dsh-greatwall-v6up] registered skills: ${registered.join(', ')}`)
    }
  }

  // 3. 统一控制服务（One Operation, Two Callers）
  const controlService = new GreatwallControlService({ ctx, config, logger })

  // 4. 注册主控工具与控制台 HTTP 路由（共同调用 controlService）
  const disposeEntryTool = registerOrchestrateTool(ctx, controlService)
  const disposeConsoleRoutes = registerGreatwallConsoleRoutes(ctx, {
    activeControllersByWs: controlService.activeControllersByWs,
    controlService,
    corePythonRoot: coreRoot,
    dataDir: config.dataDir || '',
    pythonBin: config.pythonBin || '',
    logger,
  })

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
    controlService,
    createSessionController: (opts) => controlService.createSessionController(opts),
  }

  ctx?.provide?.('greatwall', serviceApi, true)
  try {
    ctx?.set?.('greatwall', serviceApi)
  } catch {
    if (ctx && typeof ctx === 'object') ctx.greatwall = serviceApi
  }

  const cleanupAll = async () => {
    try { disposeEntryTool() } catch {}
    try { disposeConsoleRoutes() } catch {}
    try { disposeSkills() } catch {}
    try { disposeRegisteredPresets() } catch {}
    try {
      await controlService.disposeAll()
    } catch {}
  }

  if (typeof ctx?.effect === 'function') {
    // 直接返回 cleanupAll() Promise，令 Cordis 4.1.0 runDisposable 真正等待异步子进程与子会话清理完毕
    ctx.effect(() => () => cleanupAll(), 'greatwall:pluginLifecycle')
  } else {
    ctx?.on?.('dispose', cleanupAll)
  }

  return serviceApi
}
