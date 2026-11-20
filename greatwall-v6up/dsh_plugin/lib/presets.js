/**
 * 长城 V6-Up (v2.2) 五套子角色专用 DSH Agent Presets 管理与注册器。
 *
 * 全面兼容 DSH 0.2.2-rc.3 真实架构：
 * - DSH 0.2.2-rc.3 已废弃 `~/.dsh/.agent-presets/`，改由 `@deepseek-ai/dsh-agent-preset-registry`
 *   通过 `cordis.patch.yml` 中的 `@deepseek-ai/dsh-agent-preset` 声明或 `agentPresets.register(def)` 托管；
 * - 保留用户桌面主控默认预设不变（不创建剥夺工具的 greatwall-control）；
 * - 5 套内部工作预设彻底剔除 standard/ptc 污染（无 compaction-basic / skill-filesystem / ptc / subagent / goal），且严禁使用模板变量；
 * - 支持冷恢复时按 `header.agentPreset` 调 `presets.mount()` 自动恢复作用域与完整原生工具集。
 * @module dsh-greatwall-v6up/presets
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const ROLE_TO_PRESET = Object.freeze({
  explorer: 'greatwall-explorer',
  library_verifier: 'greatwall-verifier',
  lineage_companion: 'greatwall-companion',
  works_engineer: 'greatwall-works',
  logistics_coordinator: 'greatwall-governance',
  library_surveyor: 'greatwall-governance',
  supervisory_committee: 'greatwall-governance',
})

function buildExplorerPlugins(platform = process.platform) {
  return [
    {
      id: 'persona',
      name: '@deepseek-ai/dsh-persona',
      config: {
        prefix: 'You are a GreatWall V6-Up scientific explorer operating strictly inside your assigned branch worktree.',
        complete: true,
        includeRuntimeContext: false,
      },
    },
    {
      id: 'tool-fs',
      name: '@deepseek-ai/dsh-tool-fs',
      config: { applyPatch: false },
    },
    {
      id: 'tool-fs-search',
      name: '@deepseek-ai/dsh-tool-fs-search',
      config: { sampleOverCapGlobResults: false },
    },
    {
      id: 'tool-bash',
      name: '@deepseek-ai/dsh-tool-bash',
      disabled: platform === 'win32',
    },
    {
      id: 'tool-pwsh',
      name: '@deepseek-ai/dsh-tool-pwsh',
      disabled: platform !== 'win32',
    },
  ]
}

function buildVerifierPlugins() {
  return [
    {
      id: 'persona',
      name: '@deepseek-ai/dsh-persona',
      config: {
        prefix: 'You are a GreatWall V6-Up zero-disk cleanroom Library Verifier executing two-stage blind review.',
        complete: true,
        includeRuntimeContext: false,
      },
    },
  ]
}

function buildCompanionPlugins() {
  return [
    {
      id: 'persona',
      name: '@deepseek-ai/dsh-persona',
      config: {
        prefix: 'You are a GreatWall V6-Up Lineage Companion managing blackbox handoff, 37% Socratic reflection, and lineage briefing.',
        complete: true,
        includeRuntimeContext: false,
      },
    },
    {
      id: 'tool-fs',
      name: '@deepseek-ai/dsh-tool-fs',
      config: { write: false, edit: false, applyPatch: false },
    },
    {
      id: 'tool-fs-search',
      name: '@deepseek-ai/dsh-tool-fs-search',
      config: { sampleOverCapGlobResults: false },
    },
  ]
}

function buildWorksPlugins(platform = process.platform) {
  return [
    {
      id: 'persona',
      name: '@deepseek-ai/dsh-persona',
      config: {
        prefix: 'You are a GreatWall V6-Up Works Engineer forging verification hooks, isolated baselines, and shared diagnostic probes.',
        complete: true,
        includeRuntimeContext: false,
      },
    },
    {
      id: 'tool-fs',
      name: '@deepseek-ai/dsh-tool-fs',
      config: { applyPatch: false },
    },
    {
      id: 'tool-fs-search',
      name: '@deepseek-ai/dsh-tool-fs-search',
      config: { sampleOverCapGlobResults: false },
    },
    {
      id: 'tool-bash',
      name: '@deepseek-ai/dsh-tool-bash',
      disabled: platform === 'win32',
    },
    {
      id: 'tool-pwsh',
      name: '@deepseek-ai/dsh-tool-pwsh',
      disabled: platform !== 'win32',
    },
  ]
}

function buildGovernancePlugins() {
  return [
    {
      id: 'persona',
      name: '@deepseek-ai/dsh-persona',
      config: {
        prefix: 'You are a GreatWall V6-Up Governance or Library Survey node strictly following narrow role authorization.',
        complete: true,
        includeRuntimeContext: false,
      },
    },
    {
      id: 'tool-fs',
      name: '@deepseek-ai/dsh-tool-fs',
      config: { write: false, edit: false, applyPatch: false },
    },
    {
      id: 'tool-fs-search',
      name: '@deepseek-ai/dsh-tool-fs-search',
      config: { sampleOverCapGlobResults: false },
    },
    {
      id: 'tool-web',
      name: '@deepseek-ai/dsh-tool-web',
      config: { fetch: true, searchTimeoutMs: 60000 },
    },
  ]
}

/**
 * 构建对齐 DSH 0.2.2-rc.3 `@deepseek-ai/dsh-agent-preset` 声明结构的 5 套预设配置数组。
 * @param {string} [platform]
 */
export function buildDeclarativePresetConfigs(platform = process.platform) {
  return [
    {
      id: 'greatwall-explorer',
      name: '长城 · 探索者 (Explorer)',
      description: '隔离分支探索与科研求解预设（无 ptc / 无压缩 / 无网络 / 无 cwd 模板）',
      order: 50,
      plugins: buildExplorerPlugins(platform),
    },
    {
      id: 'greatwall-verifier',
      name: '长城 · 盲审净室 (Verifier)',
      description: '物理零磁盘零终端零网络盲审预设',
      order: 51,
      plugins: buildVerifierPlugins(),
    },
    {
      id: 'greatwall-companion',
      name: '长城 · 伴随助手 (Companion)',
      description: '单向只读配对工作树预设（含 37% 反思与交接）',
      order: 52,
      plugins: buildCompanionPlugins(),
    },
    {
      id: 'greatwall-works',
      name: '长城 · 工造司 (Works)',
      description: '验证钩子、隔离基线与 B 档探针锻造预设',
      order: 53,
      plugins: buildWorksPlugins(platform),
    },
    {
      id: 'greatwall-governance',
      name: '长城 · 治理与查新 (Governance)',
      description: '后勤、查新采编与监察委共用底座（运行期二次精准裁剪权限）',
      order: 54,
      plugins: buildGovernancePlugins(),
    },
  ]
}

function buildYamlShellEntries() {
  return `- id: tool-bash
  name: '@deepseek-ai/dsh-tool-bash'
  disabled: !!js process.platform === 'win32'

- id: tool-pwsh
  name: '@deepseek-ai/dsh-tool-pwsh'
  disabled: !!js process.platform !== 'win32'`
}

export const PRESET_DEFINITIONS = Object.freeze({
  'greatwall-explorer': {
    meta: { name: '长城 · 探索者 (Explorer)', description: '隔离分支探索与科研求解预设（无 ptc / 无压缩 / 无网络）', order: 50 },
    cordisYml: `# GreatWall V6-Up Explorer Preset (isolated branch compute, no compaction/skill-fs/ptc/web/subagent)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up scientific explorer operating strictly inside your assigned branch worktree.
    complete: true
    includeRuntimeContext: false

- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
  config:
    applyPatch: false

- id: tool-fs-search
  name: '@deepseek-ai/dsh-tool-fs-search'
  config:
    sampleOverCapGlobResults: false

${buildYamlShellEntries()}
`,
  },
  'greatwall-verifier': {
    meta: { name: '长城 · 盲审净室 (Verifier)', description: '物理零磁盘零终端零网络盲审预设', order: 51 },
    cordisYml: `# GreatWall V6-Up Verifier Cleanroom Preset (zero disk, zero shell, zero web — pure DB blind review)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up zero-disk cleanroom Library Verifier executing two-stage blind review.
    complete: true
    includeRuntimeContext: false
`,
  },
  'greatwall-companion': {
    meta: { name: '长城 · 伴随助手 (Companion)', description: '单向只读配对工作树预设（含 37% 反思与交接）', order: 52 },
    cordisYml: `# GreatWall V6-Up Companion Preset (read-only fs locked to paired worktree + 4 narrow MCP tools)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Lineage Companion managing blackbox handoff, 37% Socratic reflection, and lineage briefing.
    complete: true
    includeRuntimeContext: false

- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
  config:
    write: false
    edit: false
    applyPatch: false

- id: tool-fs-search
  name: '@deepseek-ai/dsh-tool-fs-search'
  config:
    sampleOverCapGlobResults: false
`,
  },
  'greatwall-works': {
    meta: { name: '长城 · 工造司 (Works)', description: '验证钩子、隔离基线与 B 档探针锻造预设', order: 53 },
    cordisYml: `# GreatWall V6-Up Works Engineer Preset (evaluators/baselines/skills + pwsh + fs)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Works Engineer forging verification hooks, isolated baselines, and shared diagnostic probes.
    complete: true
    includeRuntimeContext: false

- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
  config:
    applyPatch: false

- id: tool-fs-search
  name: '@deepseek-ai/dsh-tool-fs-search'
  config:
    sampleOverCapGlobResults: false

${buildYamlShellEntries()}
`,
  },
  'greatwall-governance': {
    meta: { name: '长城 · 治理与查新 (Governance)', description: '后勤、查新采编与监察委共用底座（运行期二次精准裁剪权限）', order: 54 },
    cordisYml: `# GreatWall V6-Up Governance & Survey Preset (fs-ro + search + web, further constrained per role via tools.restrict & guard)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Governance or Library Survey node strictly following narrow role authorization.
    complete: true
    includeRuntimeContext: false

- id: tool-fs
  name: '@deepseek-ai/dsh-tool-fs'
  config:
    write: false
    edit: false
    applyPatch: false

- id: tool-fs-search
  name: '@deepseek-ai/dsh-tool-fs-search'
  config:
    sampleOverCapGlobResults: false

- id: tool-web
  name: '@deepseek-ai/dsh-tool-web'
  config:
    fetch: true
    searchTimeoutMs: 60000
`,
  },
})

function writeIfChanged(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  if (fs.existsSync(filePath)) {
    const cur = fs.readFileSync(filePath, 'utf8')
    if (cur === content) return false
  }
  fs.writeFileSync(filePath, content, 'utf8')
  return true
}

/**
 * 向 0.2.2-rc.3 `@deepseek-ai/dsh-agent-preset-registry` 运行时幂等注册缺失的 5 套预设（与 cordis.patch.yml 互为双保险）。
 * @param {any} ctx
 * @param {any} [agentPresetsSvc]
 * @param {{ logger?: any, targetId?: string }} [opts]
 */
export async function registerPresetsOnRegistry(ctx, agentPresetsSvc = null, { logger = console, targetId = '' } = {}) {
  const rootSvc = typeof ctx?.root?.get === 'function' ? ctx.root.get('agentPresets') : null
  const svc = rootSvc || agentPresetsSvc || (typeof ctx?.get === 'function' ? ctx.get('agentPresets') : null)
  if (!svc || typeof svc.register !== 'function') {
    return { registered: [], alreadyReady: [], errors: [], unregisters: [], skipped: true }
  }

  const defs = buildDeclarativePresetConfigs().filter((d) => !targetId || d.id === targetId)
  const registered = []
  const alreadyReady = []
  const errors = []
  const unregisters = []

  for (const def of defs) {
    let resolved = null
    try {
      resolved = await svc.resolve(def.id)
    } catch {}
    if (resolved && !resolved.broken) {
      alreadyReady.push(def.id)
      continue
    }
    if (resolved?.broken) {
      errors.push({ id: def.id, error: `已有声明但处于 broken 状态: ${resolved.broken}` })
      continue
    }

    try {
      const unreg = await svc.register(def)
      if (typeof unreg === 'function') unregisters.push(unreg)
      const verified = await svc.resolve(def.id)
      if (verified?.broken) {
        errors.push({ id: def.id, error: `注册后处于 broken 状态: ${verified.broken}` })
      } else {
        registered.push(def.id)
      }
    } catch (err) {
      const msg = String(err?.message || err)
      if (msg.includes('Duplicate agent preset')) {
        alreadyReady.push(def.id)
      } else {
        logger?.warn?.(`[dsh-greatwall-v6up] register preset ${def.id} failed:`, msg)
        errors.push({ id: def.id, error: msg })
      }
    }
  }

  return {
    registered,
    alreadyReady,
    errors,
    unregisters,
    skipped: false,
    async disposeAll() {
      for (const fn of unregisters.splice(0)) {
        try {
          await fn()
        } catch {}
      }
    },
  }
}

/**
 * 写入本地 `presets/`（版本可控）与兼容老式 `.agent-presets/`。
 */
export function ensurePresetsInstalled({ dshHome = '', localPresetsDir = '' } = {}) {
  const effDshHome = dshHome || process.env.DSH_HOME || path.join(os.homedir(), '.dsh')
  const roots = [path.join(effDshHome, '.agent-presets')]
  if (localPresetsDir) roots.push(localPresetsDir)

  const installedIds = []
  for (const [id, def] of Object.entries(PRESET_DEFINITIONS)) {
    if (def.cordisYml.includes('{{cwd}}')) {
      throw new Error(`Preset ${id} 严禁包含 {{cwd}} 模板变量`)
    }
    const presetYml = `name: ${def.meta.name}\ndescription: ${def.meta.description}\norder: ${def.meta.order}\n`
    for (const rootDir of roots) {
      const dir = path.join(rootDir, id)
      writeIfChanged(path.join(dir, 'agent.cordis.yml'), def.cordisYml)
      writeIfChanged(path.join(dir, 'preset.yml'), presetYml)
    }
    installedIds.push(id)
  }
  return installedIds
}
