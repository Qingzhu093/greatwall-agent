/**
 * GreatWall v0.3 八套专用 DSH Agent Presets 单源声明（覆盖全院 10 大角色）。
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
    return s
  }
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) {
    return s.slice(1, -1).replace(/''/g, "'")
  }
  return s
}

// DSH parses the manifest at runtime. Doctor reads the mapping and list structure
// of this bundle without evaluating host-dependent expressions.
function readBundleBlock(lines, start, platform) {
  const { indent, text } = lines[start]
  const list = text === '-'
  const block = list ? [] : {}
  let index = start
  while (lines[index]?.indent === indent) {
    const { text } = lines[index++]
    if (list) {
      const [entry, next] = readBundleBlock(lines, index, platform)
      block.push(entry)
      index = next
      continue
    }
    const colon = text.indexOf(':')
    if (colon < 1) throw new Error('预设声明的字段缺少冒号')
    const key = text.slice(0, colon)
    const value = text.slice(colon + 1).trim()
    if (!value && lines[index]?.indent > indent) {
      const [child, next] = readBundleBlock(lines, index, platform)
      block[key] = child
      index = next
    } else {
      block[key] = parseYamlScalar(value, platform)
    }
  }
  return [block, index]
}

export function loadBundlePresetConfigs(platform = process.platform, bundlePath = BUNDLE_PATCH_PATH) {
  const raw = fs.readFileSync(bundlePath, 'utf8')
  if (raw.includes('{{cwd}}')) throw new Error('cordis.patch.yml 严禁包含 {{cwd}} 模板变量')
  const lines = raw.split(/\r?\n/).flatMap((line) => {
    const text = line.trim()
    if (!text || text.startsWith('#')) return []
    const indent = line.length - line.trimStart().length
    return text.startsWith('- ')
      ? [{ indent, text: '-' }, { indent: indent + 2, text: text.slice(2) }]
      : [{ indent, text }]
  })
  if (!lines.length) return []
  const [patches] = readBundleBlock(lines, 0, platform)
  return patches.flatMap((patch) => patch.insert || [])
    .filter((row) => row.name === '@deepseek-ai/dsh-agent-preset')
    .map((row) => row.config)
}
