/**
 * GreatWall v0.3 全院 10 角色双向隔离读写沙箱与同步 Guard。
 *
 * 物理权限红线：
 * 1. `explorer`：锁在本人 `worktreeAbsPath`，`.greatwall_donors/` 与 `inputs/` 只读禁改；支持 70% 动态只读锁；
 * 2. `library_verifier`：锁在独立空白盲审沙箱 `sandboxAbsPath`，物理禁写、禁网、禁读 `greatwall.db` / 原 `worktrees/`；
 * 3. `works_engineer`：仅限实验工作区，严禁修改 `worktrees/`；
 * 4. `external_surveyor`：唯一可联网，严禁读写任何本地文件或调用 Shell（物理零院内成果泄露）；
 * 5. `gw_chief` / `library_chronicler` / `conference_chair` / `logistics_coordinator` / `supervisory_committee`：物理 0 原生工具兜底拦截；
 * 6. 全局禁写过程性 `.md` 公文（`HANDOFF*.md`, `*_AUDIT.md`, `*_CLOSURE.md`, `REVIEW*.md`）。
 * @module dsh-greatwall-v6up/read_isolated_sandbox
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { ALL_MCP_TOOLS } from './prompts.js'

export const PUBLIC_INPUT_DEFAULT_DIRS = Object.freeze([
  'source_materials',
  'problem_pack',
  'inputs',
  'data',
  'rulings',
  'attachments',
  '附件',
])

export const PUBLIC_INPUT_TOP_EXTS = new Set([
  '.md', '.txt', '.pdf', '.doc', '.docx', '.csv', '.tsv', '.json', '.yaml', '.yml', '.xlsx',
])

export const FORBIDDEN_PUBLIC_DIR_NAMES = new Set([
  'worktrees', 'evaluators', 'final_delivery', 'logs', 'paper', 'simulator',
  '.git', '.venv', 'venv', 'node_modules', '__pycache__', '.dsh',
])

export const READONLY_FS_TOOL_NAMES = new Set(['read', 'glob', 'grep', 'read_image', 'read_file'])

export const PROCESS_MD_FORBIDDEN_RE = /(?:^|[\\/])(?:HANDOFF[^\\/]*|REVIEW[^\\/]*|SUPERVISORY[^\\/]*|LINEAGE_BRIEFING[^\\/]*|.*_(?:AUDIT|CLOSURE|HANDOFF|BRIEFING|VERDICT|REPORT))\.md$/i

export const PROTECTED_TOKEN_RE = /(?:greatwall\.db(?:-wal|-shm)?|greatwall-v6up[\\/]workspaces|_hidden_calibrations|_hidden[a-z0-9_]*|eval_artifacts|blind_sandboxes|frozen_deliveries|final_delivery|GREATWALL_DATA_DIR|GREATWALL_DB_PATH|GREATWALL_PLUGIN_DATA_DIR|PLUGIN_DATA)/i

export const VERIFIER_NETWORK_CMD_RE = /\b(?:curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|Start-BitsTransfer|nslookup|dig|nc|ncat|telnet|ssh|scp|ftp|urllib|requests|httpx|aiohttp|http\.client|socket\.create_connection)\b/i

/** 全部写类 MCP 窄工具集合（与 Python tool_registry.py READONLY_BLOCKED_MCP_TOOLS 100% 同步）。 */
export const READONLY_BLOCKED_MCP_TOOLS = new Set([
  'chief_propose_control_action',
  'run_isolated_eval',
  'request_literature_survey',
  'handback_to_chief',
  'save_lineage_briefing',
  'record_reflection_and_unlock_pull',
  'submit_node_handoff',
  'submit_conference_statement',
  'register_method_family',
  'triage_node',
  'fork_branch',
  'publish_external_literature_card',
  'publish_living_survey',
  'export_stage3_final_delivery',
  'record_conference_minutes',
  'submit_conference_verdict',
  'submit_stage1_blind_ledger',
  'submit_stage2_unblind_verdict',
  'propose_salvaged_lemma',
  'register_question_instrument',
  'upgrade_instrument_with_calibration',
  'recompute_stage_b_only',
  'update_skill_ledger',
  'resolve_works_ticket',
  'record_compliance_check',
  'register_saved_graph_query',
])

export const WRITE_TOOL_NAMES = new Set([
  'write', 'edit', 'write_file', 'edit_file', 'create_file',
  'replace_file_content', 'multi_replace_file_content', 'str_replace_editor',
])

export const PATH_ARG_KEYS = ['file_path', 'path', 'target_file', 'file', 'dir', 'directory', 'cwd', 'workdir', 'workingDirectory', 'target_path']
export const SHELL_TOOL_NAMES = new Set(['pwsh', 'bash', 'shell', 'run_command'])

const SHELL_WRITE_RE = /(?:>|>>|\bOut-File\b|\bSet-Content\b|\bAdd-Content\b|\bNew-Item\b|\bRemove-Item\b|\bMove-Item\b|\bCopy-Item\b|\btee\b|\brm\s|\bmv\s|\bcp\s|\btouch\s|\bmkdir\s)/i
const ZERO_NATIVE_ROLES = new Set([
  'gw_chief',
  'logistics_coordinator',
  'supervisory_committee',
  'library_chronicler',
  'conference_chair',
])
const NO_SHELL_ROLES = new Set([
  ...ZERO_NATIVE_ROLES,
  'lineage_companion',
  'external_surveyor',
])

export function resolveCanonicalTarget(targetPath, baseDir = '') {
  const raw = String(targetPath ?? '').trim()
  if (!raw || raw.includes('\0')) return ''
  const abs = path.isAbsolute(raw) ? raw : path.resolve(baseDir || process.cwd(), raw)
  const parts = []
  let cur = path.resolve(abs)
  while (true) {
    try {
      const real = fs.realpathSync(cur)
      const joined = parts.length ? path.join(real, ...parts.reverse()) : real
      return process.platform === 'win32' ? path.normalize(joined).toLowerCase() : path.normalize(joined)
    } catch {
      const parent = path.dirname(cur)
      if (parent === cur) {
        return process.platform === 'win32' ? path.normalize(abs).toLowerCase() : path.normalize(abs)
      }
      parts.push(path.basename(cur))
      cur = parent
    }
  }
}

export function isInsideRoot(canonicalTarget, canonicalRoot) {
  if (!canonicalTarget || !canonicalRoot) return false
  if (canonicalTarget === canonicalRoot) return true
  const prefix = canonicalRoot.endsWith(path.sep) ? canonicalRoot : canonicalRoot + path.sep
  return canonicalTarget.startsWith(prefix)
}

export function extractPathValues(args) {
  if (!args || typeof args !== 'object') return []
  const found = []
  for (const key of PATH_ARG_KEYS) {
    const val = args[key]
    if (typeof val === 'string' && val.trim()) found.push(val.trim())
  }
  return found
}

function maskOwnSandboxInCommand(cmd, sandboxCanon) {
  if (!cmd || !sandboxCanon) return cmd
  const trimmed = sandboxCanon.replace(/[\\/]+$/, '')
  if (!trimmed) return cmd
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\\|\\\//g, '[\\\\/]')
  const flags = process.platform === 'win32' ? 'gi' : 'g'
  const ownRe = new RegExp(`${escaped}(?=[\\\\/"'\\s,;)|&>]|$)`, flags)
  return cmd.replace(ownRe, '<OWN_SANDBOX>')
}

export function evaluateShellCommandGuard(commandText, opts) {
  const role = String(opts.role || '')
  if (opts.readonly) {
    return 'SANDBOX_VIOLATION: 该会话已进入只读保护态（70% 遗嘱收官或结案归档），禁止再执行任何 Shell 命令'
  }
  if (NO_SHELL_ROLES.has(role)) {
    return `SANDBOX_VIOLATION: 角色 ${role} 无终端执行权限`
  }

  const cmd = String(commandText ?? '')
  if (!cmd.trim()) return null

  if (PROTECTED_TOKEN_RE.test(cmd)) {
    return 'SANDBOX_VIOLATION: Shell 命令严禁触及受保护数据库、隐藏校准集或外部不可变冻结资产'
  }
  if (/\.greatwall_donors\b/i.test(cmd) && SHELL_WRITE_RE.test(cmd)) {
    return 'SANDBOX_VIOLATION: .greatwall_donors/ 为只读双供体参考挂载目录，严禁写入或修改'
  }
  if (/\.(?:md)\b/i.test(cmd) && SHELL_WRITE_RE.test(cmd)) {
    if (PROCESS_MD_FORBIDDEN_RE.test(cmd) || /(?:HANDOFF|AUDIT|CLOSURE|BRIEFING)\.md/i.test(cmd)) {
      return 'NO_MD_DOSSIER_POLICY: 严禁使用 Shell 生成过程性 .md 公文，请调用对应 MCP 窄工具写库'
    }
  }

  if (role === 'explorer' || role === 'library_verifier') {
    if (/(?:^|[\s"'`(=,;\\\/])\.\.(?:[\\/]|$|['"`\s;,)])/.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 隔离区严禁使用上跳路径 (..)，请基于当前根目录使用相对路径`
    }
    if (/~[\\/]|HOME\b|\$(?:env:)?(?:USERPROFILE|HOME|APPDATA|LOCALAPPDATA|TEMP|TMP|GREATWALL_|PLUGIN_DATA|DSH_HOME)/i.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 严禁探测宿主敏感环境变量或用户主目录`
    }
    if (/\bsqlite3\b/i.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 严禁直接调用 sqlite3 探测数据库`
    }
    if (role === 'library_verifier') {
      if (VERIFIER_NETWORK_CMD_RE.test(cmd)) {
        return 'SANDBOX_VIOLATION: library_verifier 盲审沙箱物理断网，严禁发起任何网络请求'
      }
      if (/\bworktrees\b/i.test(cmd)) {
        return 'SANDBOX_VIOLATION: library_verifier 严禁访问原探索分支 worktrees/ 目录'
      }
    }

    const maskedCmd = maskOwnSandboxInCommand(cmd, opts.sandboxCanon)
    const normalizedMasked = process.platform === 'win32'
      ? maskedCmd.toLowerCase().replace(/\//g, '\\')
      : maskedCmd

    const denyCanons = [
      ...(opts.protectedCanons || []),
      ...(opts.worktreesCanon ? [opts.worktreesCanon] : []),
      ...(opts.evaluatorsCanon ? [opts.evaluatorsCanon] : []),
    ]
    for (const prot of denyCanons) {
      const normalizedProt = process.platform === 'win32' ? String(prot || '').toLowerCase() : String(prot || '')
      if (normalizedProt && normalizedMasked.includes(normalizedProt)) {
        return `SANDBOX_VIOLATION: ${role} 严禁在 Shell 中引用受保护或他脉外部目录 (${prot})`
      }
    }

    const absRe = process.platform === 'win32'
      ? /"((?:[a-zA-Z]:[\\/]|\\\\)[^"]+)"|'((?:[a-zA-Z]:[\\/]|\\\\)[^']+)'|(?:^|[\s`(=,;])((?:[a-zA-Z]:[\\/]|\\\\)[^\s"'`;|><&()]+)/g
      : /"(\/[^"]+)"|'(\/[^']+)'|(?:^|[\s`(=,;])(\/[^\s"'`;|><&()]+)/g
    let m
    while ((m = absRe.exec(maskedCmd)) !== null) {
      const rawHit = m[1] || m[2] || m[3]
      if (!rawHit) continue
      const candidate = resolveCanonicalTarget(rawHit)
      const inOwnSandbox = isInsideRoot(candidate, opts.sandboxCanon)
      const isRuntimeBin = /(?:python(?:\d+(?:\.\d+)*)?(?:\.exe)?|python3|uv(?:\.exe)?|lean(?:\.exe)?|node(?:\.exe)?|\.venv)[\\/]?$/i.test(candidate) ||
        /[\\/](?:usr[\\/]bin|bin|python\d*)[\\/][^\\/]+$/i.test(candidate)
      if (!inOwnSandbox && !isRuntimeBin) {
        return `SANDBOX_VIOLATION: ${role} 命令越界引用沙箱外路径 (${rawHit})`
      }
    }
  } else if (role === 'works_engineer') {
    if (/\bworktrees[\\/]/i.test(cmd) && SHELL_WRITE_RE.test(cmd)) {
      return 'SANDBOX_VIOLATION: works_engineer 严禁修改探索者分支工作树 worktrees/'
    }
  }

  return null
}

export function createSandboxCallEvaluator(opts) {
  const role = String(opts.role || '')
  const getReadonly = typeof opts.readonly === 'function' ? opts.readonly : () => Boolean(opts.readonly)
  const wsCanon = resolveCanonicalTarget(opts.workspaceRoot || process.cwd())
  const worktreesCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'worktrees'))
  const evaluatorsCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'evaluators'))
  const hiddenCalCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'evaluators', '_hidden_calibrations'))
  const finalDeliveryCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'final_delivery'))

  const effectiveSandboxDir = role === 'library_verifier'
    ? (opts.sandboxAbsPath || opts.worktreeAbsPath || '')
    : ((role === 'explorer' || role === 'lineage_companion') && opts.worktreeAbsPath ? opts.worktreeAbsPath : opts.workspaceRoot)
  const sandboxCanon = effectiveSandboxDir ? resolveCanonicalTarget(effectiveSandboxDir) : ''

  const publicDirCanons = [
    ...PUBLIC_INPUT_DEFAULT_DIRS.map((d) => resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), d))),
    ...(Array.isArray(opts.sharedInputPaths) ? opts.sharedInputPaths : [])
      .filter(Boolean)
      .map((rel) => resolveCanonicalTarget(rel, opts.workspaceRoot || process.cwd()))
      .filter((c) => isInsideRoot(c, wsCanon)),
  ].filter(Boolean)

  const dshSpillPrefixCanon = resolveCanonicalTarget(path.join(os.tmpdir(), 'dsh-spill-'))
  const isAllowedDshSpillRead = (canon) => Boolean(dshSpillPrefixCanon && canon && canon.startsWith(dshSpillPrefixCanon))

  const isAllowedPublicRead = (canon) => {
    if (!canon || !wsCanon || !isInsideRoot(canon, wsCanon)) return false
    const relFromWs = path.relative(wsCanon, canon)
    if (!relFromWs || relFromWs.startsWith('..')) return false
    const parts = relFromWs.split(/[\\/]+/).filter(Boolean)
    if (parts.some((p) => FORBIDDEN_PUBLIC_DIR_NAMES.has(p.toLowerCase()) || p.toLowerCase().startsWith('_hidden') || p.toLowerCase().startsWith('greatwall.db'))) {
      return false
    }
    if (publicDirCanons.some((pub) => isInsideRoot(canon, pub))) return true
    if (parts.length === 1) {
      const ext = path.extname(parts[0]).toLowerCase()
      if (PUBLIC_INPUT_TOP_EXTS.has(ext)) return true
    }
    return false
  }

  const autoProtected = [hiddenCalCanon, finalDeliveryCanon, ...(opts.protectedDirs || []).filter(Boolean)]
  if (role === 'library_verifier') autoProtected.push(worktreesCanon)
  const protectedCanons = [...new Set(autoProtected.map((d) => resolveCanonicalTarget(d)).filter(Boolean))]

  return function evaluateToolCall(exec) {
    const name = String(exec?.name || '')
    const args = exec?.arguments || {}
    const isReadonlyNow = Boolean(getReadonly())

    const isWriteTool = WRITE_TOOL_NAMES.has(name) || name.includes('write') || name.includes('edit')
    const isShellTool = SHELL_TOOL_NAMES.has(name) || typeof args?.command === 'string' || typeof args?.CommandLine === 'string'

    if (isReadonlyNow && (isWriteTool || isShellTool || READONLY_BLOCKED_MCP_TOOLS.has(name))) {
      return `SANDBOX_VIOLATION: 该会话已处于只读态（70% 遗嘱或已封存/归档），严禁调用写入、终端或状态变更工具 (${name})`
    }

    if (ALL_MCP_TOOLS.has(name) || name.startsWith('greatwall_')) {
      return undefined
    }

    // 物理 0 原生工具角色二次兜底
    if (ZERO_NATIVE_ROLES.has(role)) {
      return `SANDBOX_VIOLATION: ${role} 为物理零原生工具角色，禁止调用原生工具 ${name}`
    }

    // external_surveyor 仅允许联网搜索工具，物理禁止任何本地文件或 Shell 访问（防院内成果泄露）
    if (role === 'external_surveyor') {
      if (name === 'web_search' || name === 'web_fetch') return undefined
      return `SANDBOX_VIOLATION: external_surveyor 仅允许 web_search / web_fetch，严禁接触本地磁盘或终端 (${name})`
    }

    if (role === 'library_verifier' && !sandboxCanon) {
      return `SANDBOX_VIOLATION: library_verifier 缺少有效独立盲审沙箱路径，禁止调用原生工具 ${name}`
    }

    if (isWriteTool) {
      if (role === 'lineage_companion' || role === 'library_verifier') {
        return `SANDBOX_VIOLATION: ${role} 严禁修改磁盘文件 (${name})`
      }
      for (const pVal of extractPathValues(args)) {
        if (PROCESS_MD_FORBIDDEN_RE.test(pVal)) {
          return 'NO_MD_DOSSIER_POLICY: 严禁在磁盘撰写过程性 .md 公文（如 HANDOFF.md / *_AUDIT.md / *_CLOSURE.md），请直接写 SQLite 窄工具！'
        }
      }
    }

    const baseForRel = effectiveSandboxDir || opts.workspaceRoot
    const pathVals = extractPathValues(args)
    for (const pVal of pathVals) {
      const canon = resolveCanonicalTarget(pVal, baseForRel)
      const isVerifierOwnSandbox = role === 'library_verifier' && Boolean(sandboxCanon) && isInsideRoot(canon, sandboxCanon)
      if (PROTECTED_TOKEN_RE.test(pVal)) {
        const isCalForWorks = role === 'works_engineer' && /_hidden_calibrations/i.test(pVal) && !/greatwall\.db/i.test(pVal)
        const isDbOrHidden = /(?:greatwall\.db(?:-wal|-shm)?|_hidden_calibrations|frozen_deliveries|GREATWALL_DATA_DIR|GREATWALL_DB_PATH|GREATWALL_PLUGIN_DATA_DIR)/i.test(pVal)
        if (!isCalForWorks && !(isVerifierOwnSandbox && !isDbOrHidden)) {
          return `SANDBOX_VIOLATION: 角色 ${role} 严禁访问受保护资产 (${pVal})`
        }
      }
      if (role !== 'works_engineer') {
        for (const prot of protectedCanons) {
          if (isVerifierOwnSandbox) continue
          if (isInsideRoot(canon, prot)) {
            return `SANDBOX_VIOLATION: 禁止访问受保护外部数据区或隐藏资产 (${pVal})`
          }
        }
      }

      const isPureReadTool = !isWriteTool && !isShellTool && READONLY_FS_TOOL_NAMES.has(name)
      const isPublicOrSpillRead = isPureReadTool && (isAllowedPublicRead(canon) || isAllowedDshSpillRead(canon))
      const isSpillOnlyRead = isPureReadTool && isAllowedDshSpillRead(canon)
      const worktreeInputsCanon = sandboxCanon ? path.join(sandboxCanon, 'inputs') : ''
      const worktreeDonorsCanon = sandboxCanon ? path.join(sandboxCanon, '.greatwall_donors') : ''

      if (role === 'explorer' || role === 'lineage_companion') {
        if (isWriteTool && worktreeInputsCanon && isInsideRoot(canon, worktreeInputsCanon)) {
          return `SANDBOX_VIOLATION: ${role} 严禁修改只读公开输入挂载目录 (${pVal})`
        }
        if (isWriteTool && worktreeDonorsCanon && isInsideRoot(canon, worktreeDonorsCanon)) {
          return `SANDBOX_VIOLATION: ${role} 严禁修改只读双供体源码挂载目录 .greatwall_donors/ (${pVal})`
        }
        if ((!sandboxCanon || !isInsideRoot(canon, sandboxCanon)) && !isPublicOrSpillRead) {
          return `SANDBOX_VIOLATION: ${role} 仅限在配对隔离工作树 (${effectiveSandboxDir}) 与公开只读输入区内访问，禁止越界 ${pVal}`
        }
      } else if (role === 'library_verifier') {
        if ((!sandboxCanon || !isInsideRoot(canon, sandboxCanon)) && !isSpillOnlyRead) {
          return `SANDBOX_VIOLATION: library_verifier 仅限在独立空白盲审沙箱 (${effectiveSandboxDir}) 内只读跑证，禁止越界 ${pVal}`
        }
      } else if (role === 'works_engineer') {
        if (!isInsideRoot(canon, wsCanon) && !isPublicOrSpillRead) {
          return `SANDBOX_VIOLATION: works_engineer 仅限在实验工作区内访问，禁止越界 ${pVal}`
        }
        if (isWriteTool && isInsideRoot(canon, worktreesCanon)) {
          return `SANDBOX_VIOLATION: works_engineer 严禁修改探索者分支工作树 (${pVal})`
        }
      }
    }

    if (isShellTool) {
      const cmdStr = String(args?.command ?? args?.CommandLine ?? args?.script ?? '')
      const shellErr = evaluateShellCommandGuard(cmdStr, {
        role,
        readonly: isReadonlyNow,
        sandboxCanon,
        workspaceCanon: wsCanon,
        worktreesCanon,
        evaluatorsCanon,
        protectedCanons: role === 'library_verifier'
          ? protectedCanons.filter((p) => !isInsideRoot(sandboxCanon, p))
          : protectedCanons,
      })
      if (shellErr) return shellErr
    }

    return undefined
  }
}

export function installRoleSandboxGuard(agentCtx, opts) {
  const role = String(opts.role || '')
  const checkCall = createSandboxCallEvaluator(opts)

  const reportUnauthorized = (toolName, reason, args) => {
    if (!opts.bridge) return
    void opts.bridge
      .control('control_plane/fact_edge', {
        workspace_root: opts.workspaceRoot,
        source_id: opts.nodeId || opts.sessionId || role,
        target_id: `guard:${toolName}`,
        edge_type: 'USED_TOOL',
        session_id: opts.sessionId,
        metadata: {
          unauthorized: true,
          role,
          reason: String(reason).slice(0, 200),
          args_preview: JSON.stringify(args ?? {}).slice(0, 300),
        },
      })
      .catch(() => {})
  }

  const disposeGuard = agentCtx.tools.guard((exec) => {
    const reason = checkCall(exec)
    if (reason) {
      reportUnauthorized(exec?.name || 'unknown', reason, exec?.arguments)
      return reason
    }
    return undefined
  })

  return () => {
    try { disposeGuard() } catch {}
  }
}
