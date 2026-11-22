/**
 * 长城 V6-Up (v3.0) 六套子角色专用 DSH Agent Presets 管理与注册器。
 *
 * 全面对齐 DSH 0.2.2-rc.3 与 v3.0 沙箱平权矩阵：
 * - `greatwall-explorer`  : 读写 fs + search + 平台 Shell（探索者，锁在分支 worktree）
 * - `greatwall-verifier`  : 只读 fs + search + 平台 Shell（盲审官，锁在独立空白盲审沙箱，禁写/禁外网/禁 DB）
 * - `greatwall-companion` : 只读 fs + search（伴随助手，单节点暂停续传）
 * - `greatwall-works`     : 读写 fs + search + 平台 Shell（科研仪器科，锁在 evaluators/ & skills/）
 * - `greatwall-surveyor`  : 只读 fs + search + web（采编馆员）
 * - `greatwall-db-only`   : 物理 0 原生工具（后勤总管 & 监察委员会，纯 DB 状态机驱动）
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
  library_surveyor: 'greatwall-surveyor',
  logistics_coordinator: 'greatwall-db-only',
  supervisory_committee: 'greatwall-db-only',
})

function buildShellPlugins(platform = process.platform) {
  return [
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

function buildPersonaPlugin(prefix) {
  return {
    id: 'persona',
    name: '@deepseek-ai/dsh-persona',
    config: {
      prefix,
      complete: false,
      includeRuntimeContext: false,
    },
  }
}

function buildReadOnlyFsPlugins() {
  return [
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

function buildReadWriteFsPlugins() {
  return [
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
  ]
}

/**
 * 构建对齐 DSH 0.2.2-rc.3 `@deepseek-ai/dsh-agent-preset` 声明结构的 6 套预设配置数组。
 * @param {string} [platform]
 */
export function buildDeclarativePresetConfigs(platform = process.platform) {
  return [
    {
      id: 'greatwall-explorer',
      name: '长城 · 探索者 (Explorer)',
      description: '隔离分支探索与科研求解预设（无 ptc / 无压缩 / 无网络 / 无 cwd 模板）',
      order: 50,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up scientific explorer operating strictly inside your assigned branch worktree.'),
        ...buildReadWriteFsPlugins(),
        ...buildShellPlugins(platform),
      ],
    },
    {
      id: 'greatwall-verifier',
      name: '长城 · 隔离沙箱盲审官 (Verifier)',
      description: '独立空白盲审沙箱跑证预设（只读 fs + 平台 Shell，物理禁写/禁 DB/禁外网）',
      order: 51,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up Library Verifier executing two-stage blind verification inside an isolated blank sandbox.'),
        ...buildReadOnlyFsPlugins(),
        ...buildShellPlugins(platform),
      ],
    },
    {
      id: 'greatwall-companion',
      name: '长城 · 伴随助手 (Companion)',
      description: '单节点同会话暂停续传只读伴随预设（看板、37% 诊断反思与 70% 单写交接）',
      order: 52,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up Lineage Companion managing bounded briefing, 37% expert diagnosis, and objective two-column handoff.'),
        ...buildReadOnlyFsPlugins(),
      ],
    },
    {
      id: 'greatwall-works',
      name: '长城 · 科研仪器科 (Works)',
      description: '三档四态科研仪器、校准集与共享探针锻造预设（禁触探索者 worktrees/）',
      order: 53,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up Works Engineer forging domain-agnostic verification instruments, calibration suites, and shared probes.'),
        ...buildReadWriteFsPlugins(),
        ...buildShellPlugins(platform),
      ],
    },
    {
      id: 'greatwall-surveyor',
      name: '长城 · 采编馆员 (Surveyor)',
      description: '外藏文献检索建卡与 Stage 3 五件套终稿汇编预设（只读 fs + web）',
      order: 54,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up Library Surveyor managing external literature cards and Stage 3 delivery synthesis.'),
        ...buildReadOnlyFsPlugins(),
        {
          id: 'tool-web',
          name: '@deepseek-ai/dsh-tool-web',
          config: { fetch: true, searchTimeoutMs: 60000 },
        },
      ],
    },
    {
      id: 'greatwall-db-only',
      name: '长城 · 纯 DB 治理态 (DB-Only)',
      description: '后勤总管与监察委员会专用零原生工具预设（纯 SQLite 状态机窄工具驱动）',
      order: 55,
      plugins: [
        buildPersonaPlugin('You are a GreatWall V6-Up DB-only governance role operating exclusively via narrow SQLite MCP tools.'),
      ],
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
    cordisYml: `# GreatWall V6-Up v3.0 Explorer Preset (isolated branch compute, no compaction/skill-fs/ptc/web/subagent)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up scientific explorer operating strictly inside your assigned branch worktree.
    complete: false
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
    meta: { name: '长城 · 隔离沙箱盲审官 (Verifier)', description: '独立空白盲审沙箱跑证预设（只读 fs + 平台 Shell，禁写/禁 DB/禁外网）', order: 51 },
    cordisYml: `# GreatWall V6-Up v3.0 Verifier Isolated Sandbox Preset (read-only fs + platform shell locked to blank sandbox)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Library Verifier executing two-stage blind verification inside an isolated blank sandbox.
    complete: false
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

${buildYamlShellEntries()}
`,
  },
  'greatwall-companion': {
    meta: { name: '长城 · 伴随助手 (Companion)', description: '单节点同会话暂停续传只读伴随预设（看板、37% 反思与 70% 单写交接）', order: 52 },
    cordisYml: `# GreatWall V6-Up v3.0 Companion Preset (read-only fs locked to paired worktree + 4 narrow MCP tools)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Lineage Companion managing bounded briefing, 37% expert diagnosis, and objective two-column handoff.
    complete: false
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
    meta: { name: '长城 · 科研仪器科 (Works)', description: '三档四态科研仪器、校准集与共享探针锻造预设', order: 53 },
    cordisYml: `# GreatWall V6-Up v3.0 Works Engineer Preset (evaluators/skills + platform shell + fs; forbids worktrees/)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Works Engineer forging domain-agnostic verification instruments, calibration suites, and shared probes.
    complete: false
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
  'greatwall-surveyor': {
    meta: { name: '长城 · 采编馆员 (Surveyor)', description: '外藏文献检索建卡与 Stage 3 五件套终稿汇编预设', order: 54 },
    cordisYml: `# GreatWall V6-Up v3.0 Library Surveyor Preset (read-only fs + search + web)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up Library Surveyor managing external literature cards and Stage 3 delivery synthesis.
    complete: false
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
  'greatwall-db-only': {
    meta: { name: '长城 · 纯 DB 治理态 (DB-Only)', description: '后勤总管与监察委员会专用零原生工具预设', order: 55 },
    cordisYml: `# GreatWall V6-Up v3.0 DB-Only Governance Preset (zero native tools; pure SQLite MCP tools)
- id: persona
  name: '@deepseek-ai/dsh-persona'
  config:
    prefix: You are a GreatWall V6-Up DB-only governance role operating exclusively via narrow SQLite MCP tools.
    complete: false
    includeRuntimeContext: false
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
 * 向 0.2.2-rc.3 `@deepseek-ai/dsh-agent-preset-registry` 运行时幂等注册缺失的 6 套预设。
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
 * 写入本地 `presets/`（版本可控）与兼容老式 `.agent-presets/`，并清理已退役的 v2.2 `greatwall-governance`。
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
  for (const rootDir of roots) {
    try {
      const legacy = path.join(rootDir, 'greatwall-governance')
      if (fs.existsSync(legacy)) fs.rmSync(legacy, { recursive: true, force: true })
    } catch {}
  }
  return installedIds
}
