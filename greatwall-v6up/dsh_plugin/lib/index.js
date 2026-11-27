/**
 * dsh-greatwall-v6up v0.3 —— DSH 0.2.2-rc.5 Cordis 插件纯装配主入口。
 *
 * 职责极度聚焦：
 * - 导出动态探测 Schemastery / Standard Schema v1 回退的 `Config`；
 * - 幂等补注册 8 套单源 Preset（覆盖全院 10 大角色，含 `greatwall-chief`）；
 * - 注册 `core_python/skills/` SOP、极简 4 动作 `greatwall_orchestrate`、原生 `greatwall_proposal` Action Card 与控制台 HTTP 路由；
 * - 插件停用/卸载时完整回收全部技能、Preset、Action Card、路由、活跃子会话、实例锁与 Python 子进程。
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
import { CONFIG_SCHEMA_BACKEND, Config, DEFAULT_PLUGIN_CONFIG, resolvePluginConfig } from './config.js'
import { loadSkillLedger, loadSkillPack, registerSkillPack } from './skillpack.js'
import { GreatwallControlService } from './control_service.js'
import { registerOrchestrateTool } from './orchestrate_tool.js'
import { registerGreatwallConsoleRoutes } from './console_routes.js'
import { registerProposalActionCard } from './sessions/chief_runtime.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const PLUGIN_ROOT = path.resolve(__dirname, '..')
export const CORE_PYTHON_ROOT = path.resolve(PLUGIN_ROOT, '..', 'core_python')

export const name = 'dsh-greatwall-v6up'
export const inject = ['tools', 'systemPrompt', 'agents', 'sessionProjections', 'tokenMeter', 'sessionQuery']
export { CONFIG_SCHEMA_BACKEND, Config, DEFAULT_PLUGIN_CONFIG, resolvePluginConfig }

export function apply(ctx, rawConfig = {}) {
  const logger = ctx?.logger?.(name) ?? console
  const config = resolvePluginConfig(rawConfig, CORE_PYTHON_ROOT)
  const coreRoot = config.corePythonRoot
  const skillsDir = path.join(coreRoot, 'skills')

  let disposeSkills = () => {}
  const skillsSvc = ctx?.get?.('skills')
  if (skillsSvc && typeof skillsSvc.register === 'function') {
    const { skills, problems } = loadSkillPack(skillsDir)
    if (problems.length) logger.warn?.('[dsh-greatwall-v6up] skillpack warnings:', problems)
    const { registered, failed, disposeAll } = registerSkillPack(skillsSvc, skills, { provider: name })
    disposeSkills = disposeAll
    if (failed.length) logger.warn?.('[dsh-greatwall-v6up] skillpack registration failures:', failed)
    else if (registered.length) logger.info?.(`[dsh-greatwall-v6up] registered skills: ${registered.join(', ')}`)
  }

  const controlService = new GreatwallControlService({ ctx, config, logger })
  const disposeAdoption = ctx.on?.('agent/created', ({ agent, source }) => {
    return controlService.adoptManualChief(agent, source)
  })

  const disposeEntryTool = registerOrchestrateTool(ctx, controlService)
  const actionCardReg = registerProposalActionCard(ctx, controlService, { logger })
  const disposeConsoleRoutes = registerGreatwallConsoleRoutes(ctx, {
    activeControllersByWs: controlService.activeControllersByWs,
    controlService,
    corePythonRoot: coreRoot,
    dataDir: config.dataDir || '',
    pythonBin: config.pythonBin || '',
    logger,
  })

  const serviceApi = {
    version: '0.3.0-alpha.3',
    pluginRoot: PLUGIN_ROOT,
    corePythonRoot: coreRoot,
    config,
    configSchemaBackend: CONFIG_SCHEMA_BACKEND,
    actionCardRegistered: actionCardReg.registered,
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
    try { disposeAdoption?.() } catch {}
    try { disposeEntryTool() } catch {}
    try { actionCardReg.dispose() } catch {}
    try { disposeConsoleRoutes() } catch {}
    try { disposeSkills() } catch {}
    try { await controlService.disposeAll() } catch {}
  }

  if (typeof ctx?.effect === 'function') {
    ctx.effect(() => () => cleanupAll(), 'greatwall:pluginLifecycle')
  } else {
    ctx?.on?.('dispose', cleanupAll)
  }

  return serviceApi
}
