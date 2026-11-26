/**
 * GreatWall v0.3 八套专用 DSH Agent Presets 单源解析与注册器（覆盖全院 10 大角色）。
 * 唯一权威声明来源：`dsh_plugin/cordis.patch.yml`。
 * @module dsh-greatwall-v6up/presets
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const BUNDLE_PATCH_PATH = path.resolve(__dirname, '..', 'cordis.patch.yml')

export const ROLE_TO_PRESET = Object.freeze({
  gw_chief: 'greatwall-chief',
  explorer: 'greatwall-explorer',
  library_verifier: 'greatwall-verifier',
  lineage_companion: 'greatwall-companion',
  works_engineer: 'greatwall-works',
  external_surveyor: 'greatwall-external-surveyor',
  library_chronicler: 'greatwall-chronicler',
  conference_chair: 'greatwall-db-only',
  logistics_coordinator: 'greatwall-db-only',
  supervisory_committee: 'greatwall-db-only',
})

function parseYamlScalar(rawVal, platform) {
  const s = String(rawVal ?? '').trim()
  if (s === 'true') return true
  if (s === 'false') return false
  if (s === 'null') return null
  if (/^-?\d+(\.\d+)?$/.test(s)) return Number(s)
  if (s.startsWith('!!js ')) {
    const expr = s.slice(5).trim()
    if (expr === "process.platform === 'win32'") return platform === 'win32'
    if (expr === "process.platform !== 'win32'") return platform !== 'win32'
    throw new Error(`不支持的 cordis.patch.yml !!js 表达式: ${expr}`)
  }
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) {
    return s.slice(1, -1).replace(/''/g, "'")
  }
  return s
}

/**
 * 零依赖从 `cordis.patch.yml` 解析全部 `@deepseek-ai/dsh-agent-preset` 声明。
 * @param {string} [platform]
 * @param {string} [bundlePath]
 */
export function loadBundlePresetConfigs(platform = process.platform, bundlePath = BUNDLE_PATCH_PATH) {
  const raw = fs.readFileSync(bundlePath, 'utf8')
  if (raw.includes('{{cwd}}')) {
    throw new Error('cordis.patch.yml 严禁包含 {{cwd}} 模板变量')
  }
  const lines = raw.split(/\r?\n/)
  const presets = []
  let inPresetBlock = false
  let curPreset = null
  let inPlugins = false
  let curPlugin = null
  let inPluginConfig = false

  const flushPlugin = () => {
    if (curPlugin && curPreset) curPreset.plugins.push(curPlugin)
    curPlugin = null
    inPluginConfig = false
  }

  const flushPreset = () => {
    flushPlugin()
    if (curPreset && curPreset.id) presets.push(curPreset)
    curPreset = null
    inPresetBlock = false
    inPlugins = false
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const indent = line.length - line.trimStart().length

    if (indent === 4 && trimmed.startsWith('- ')) {
      flushPreset()
      continue
    }
    if (indent === 6 && trimmed.startsWith('name:')) {
      const val = parseYamlScalar(trimmed.slice(5), platform)
      if (val === '@deepseek-ai/dsh-agent-preset') {
        inPresetBlock = true
        curPreset = { id: '', name: '', description: '', order: 0, plugins: [] }
      } else {
        inPresetBlock = false
        curPreset = null
      }
      continue
    }
    if (!inPresetBlock || !curPreset) continue

    if (indent === 8 && !inPlugins) {
      const sep = trimmed.indexOf(':')
      if (sep < 0) continue
      const key = trimmed.slice(0, sep).trim()
      const rest = trimmed.slice(sep + 1).trim()
      if (key === 'plugins') {
        inPlugins = true
      } else if (key === 'id' || key === 'name' || key === 'description' || key === 'order') {
        curPreset[key] = parseYamlScalar(rest, platform)
      }
      continue
    }

    if (inPlugins) {
      if (indent === 10 && trimmed.startsWith('- ')) {
        flushPlugin()
        curPlugin = {}
        const kv = trimmed.slice(2).trim()
        const sep = kv.indexOf(':')
        if (sep > 0) {
          curPlugin[kv.slice(0, sep).trim()] = parseYamlScalar(kv.slice(sep + 1), platform)
        }
        continue
      }
      if (indent === 12 && curPlugin) {
        const sep = trimmed.indexOf(':')
        if (sep < 0) continue
        const key = trimmed.slice(0, sep).trim()
        const rest = trimmed.slice(sep + 1).trim()
        if (key === 'config') {
          curPlugin.config = {}
          inPluginConfig = true
        } else {
          inPluginConfig = false
          curPlugin[key] = parseYamlScalar(rest, platform)
        }
        continue
      }
      if (indent === 14 && curPlugin && inPluginConfig) {
        const sep = trimmed.indexOf(':')
        if (sep < 0) continue
        const key = trimmed.slice(0, sep).trim()
        const rest = trimmed.slice(sep + 1).trim()
        curPlugin.config[key] = parseYamlScalar(rest, platform)
      }
    }
  }
  flushPreset()
  return presets
}

export function buildDeclarativePresetConfigs(platform = process.platform) {
  return loadBundlePresetConfigs(platform)
}

export async function registerPresetsOnRegistry(
  ctx,
  agentPresetsSvc = null,
  { logger = console, targetId = '', platform = process.platform } = {},
) {
  const rootSvc = typeof ctx?.root?.get === 'function' ? ctx.root.get('agentPresets') : null
  const svc = rootSvc || agentPresetsSvc || (typeof ctx?.get === 'function' ? ctx.get('agentPresets') : null)
  if (!svc || typeof svc.register !== 'function') {
    return {
      registered: [],
      alreadyReady: [],
      errors: [],
      unregisters: [],
      skipped: true,
      async disposeAll() {},
    }
  }

  const defs = buildDeclarativePresetConfigs(platform).filter((d) => !targetId || d.id === targetId)
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

export function ensurePresetsInstalled() {
  return buildDeclarativePresetConfigs().map((d) => d.id)
}
