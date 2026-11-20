/**
 * Skill pack loader — 读取并注册 core_python/skills/ 下的技能卡与 SKILL_LEDGER.json。
 * @module dsh-greatwall-v6up/skillpack
 */
import fs from 'node:fs'
import path from 'node:path'

export const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

export function parseSkillDocument(text) {
  const source = String(text ?? '')
  if (!source.startsWith('---')) return { ok: false, reason: 'NO_FRONTMATTER' }
  const end = source.indexOf('\n---', 3)
  if (end < 0) return { ok: false, reason: 'UNTERMINATED_FRONTMATTER' }
  const block = source.slice(3, end)
  const read = (key) => {
    const match = new RegExp('^' + key + ':\\s*(.*)$', 'm').exec(block)
    if (!match) return null
    const value = match[1].trim()
    if (value.startsWith('|') || value.startsWith('>')) return null
    return value.replace(/^['"]|['"]$/g, '')
  }
  const name = read('name')
  const description = read('description')
  if (!name) return { ok: false, reason: 'MISSING_NAME' }
  if (!description) return { ok: false, reason: 'MISSING_DESCRIPTION' }
  const body = source.slice(source.indexOf('\n', end + 1) + 1).replace(/^\s*\n/, '')
  return { ok: true, name, description, whenToUse: read('whenToUse') ?? read('when_to_use'), body }
}

export function loadSkillPack(skillsDir) {
  const skills = []
  const problems = []
  let entries
  try {
    entries = fs.readdirSync(skillsDir, { withFileTypes: true })
  } catch (error) {
    return { skills, problems: [{ dir: skillsDir, reason: 'SKILLS_DIR_UNREADABLE: ' + String(error?.message ?? error) }] }
  }
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory()) continue
    const file = path.join(skillsDir, entry.name, 'SKILL.md')
    if (!fs.existsSync(file)) {
      problems.push({ dir: entry.name, reason: 'NO_SKILL_MD' })
      continue
    }
    const parsed = parseSkillDocument(fs.readFileSync(file, 'utf8'))
    if (!parsed.ok) {
      problems.push({ dir: entry.name, reason: parsed.reason })
      continue
    }
    if (!SKILL_NAME_RE.test(parsed.name) || parsed.name !== entry.name) {
      problems.push({ dir: entry.name, reason: 'NAME_MISMATCH' })
      continue
    }
    skills.push({
      name: parsed.name,
      description: parsed.description,
      whenToUse: parsed.whenToUse,
      content: parsed.body,
      dir: entry.name,
    })
  }
  return { skills, problems }
}

export function loadSkillLedger(skillsDir) {
  const ledgerPath = path.join(skillsDir, 'SKILL_LEDGER.json')
  if (!fs.existsSync(ledgerPath)) return { schema_version: '2.2.0', skills: {} }
  try {
    return JSON.parse(fs.readFileSync(ledgerPath, 'utf8'))
  } catch {
    return { schema_version: '2.2.0', skills: {} }
  }
}

export function registerSkillPack(service, skills, options = {}) {
  const registered = []
  const failed = []
  for (const skill of skills) {
    try {
      service.register({
        name: skill.name,
        description: skill.description,
        content: skill.content,
        source: options.source ?? 'bundled',
        provider: options.provider ?? 'dsh-greatwall-v6up',
        invocation: {
          modelInvocable: options.modelInvocable !== false,
          userInvocable: options.userInvocable !== false,
        },
        ...(skill.whenToUse ? { whenToUse: skill.whenToUse } : {}),
      })
      registered.push(skill.name)
    } catch (error) {
      failed.push({ name: skill.name, message: String(error?.message ?? error) })
    }
  }
  return { registered, failed }
}
