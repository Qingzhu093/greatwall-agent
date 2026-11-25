/**
 * 长城 V6-Up (v3.0) 双隔离读写沙箱与同步 Guard（探索 Worktree + 独立空白盲审沙箱 + 动态只读态）。
 *
 * 严格落实 09 第四/五章沙箱边界：
 * 1. `resolveCanonicalTarget`: `fs.realpathSync` 逐层解析最深存在祖先并规范化路径，防 `..` / 大小写 / 符号链接绕过；
 * 2. 探索者 (`explorer`)：锁在本人 `worktreeAbsPath`，支持动态 `isReadonly()` 回调（70% 亲笔遗嘱回合瞬时锁写与 Shell）；
 * 3. 盲审官 (`library_verifier`)：锁在独立现建空白盲审沙箱 `blind_sandbox_<review_id>/`，开放只读 fs + 平台 Shell，
 *    物理禁写、禁外网、禁读 `greatwall.db` / `_hidden_calibrations` / 原 `worktrees/` / B 栏假设；
 * 4. 科研仪器科 (`works_engineer`)：仅允许读写工作区内 `evaluators/`、`skills/` 与配置，**严禁修改 `worktrees/`**；
 * 5. 纯 DB 角色 (`logistics_coordinator`、`supervisory_committee`)：物理 0 原生工具，Guard 二次兜底拦截任何磁盘与 Shell；
 * 6. 全局禁写过程性 `.md` 公文（`HANDOFF*.md`, `*_AUDIT.md`, `*_CLOSURE.md`, `REVIEW*.md`）。
 * @module dsh-greatwall-v6up/read_isolated_sandbox
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { ALL_31_MCP_TOOLS } from './prompts.js'

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
  '.md',
  '.txt',
  '.pdf',
  '.doc',
  '.docx',
  '.csv',
  '.tsv',
  '.json',
  '.yaml',
  '.yml',
  '.xlsx',
])

export const FORBIDDEN_PUBLIC_DIR_NAMES = new Set([
  'worktrees',
  'evaluators',
  'final_delivery',
  'logs',
  'paper',
  'simulator',
  '.git',
  '.venv',
  'venv',
  'node_modules',
  '__pycache__',
  '.dsh',
])

export const READONLY_FS_TOOL_NAMES = new Set(['read', 'glob', 'grep', 'read_image', 'read_file'])

export const PROCESS_MD_FORBIDDEN_RE = /(?:^|[\\/])(?:HANDOFF[^\\/]*|REVIEW[^\\/]*|SUPERVISORY[^\\/]*|LINEAGE_BRIEFING[^\\/]*|.*_(?:AUDIT|CLOSURE|HANDOFF|BRIEFING|VERDICT|REPORT))\.md$/i

export const PROTECTED_TOKEN_RE = /(?:greatwall\.db(?:-wal|-shm)?|greatwall-v6up[\\/]workspaces|_hidden_calibrations|_hidden[a-z0-9_]*|eval_artifacts|blind_sandboxes|final_delivery|GREATWALL_DATA_DIR|GREATWALL_DB_PATH|GREATWALL_PLUGIN_DATA_DIR|PLUGIN_DATA)/i

export const VERIFIER_NETWORK_CMD_RE = /\b(?:curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|Start-BitsTransfer|nslookup|dig|nc|ncat|telnet|ssh|scp|ftp|urllib|requests|httpx|aiohttp|http\.client|socket\.create_connection)\b/i

export const READONLY_BLOCKED_MCP_TOOLS = new Set([
  'run_isolated_eval',
  'request_literature_survey',
  'save_lineage_briefing',
  'record_reflection_and_unlock_pull',
  'submit_node_handoff',
  'register_method_family',
  'triage_node',
  'fork_branch',
  'dispatch_stagnation_five_lanes',
  'publish_external_literature_card',
  'export_stage3_final_delivery',
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
  'write',
  'edit',
  'write_file',
  'edit_file',
  'create_file',
  'replace_file_content',
  'multi_replace_file_content',
  'str_replace_editor',
])

export const PATH_ARG_KEYS = ['file_path', 'path', 'target_file', 'file', 'dir', 'directory', 'cwd', 'workdir', 'workingDirectory', 'target_path']

export const SHELL_TOOL_NAMES = new Set(['pwsh', 'bash', 'shell', 'run_command'])

const SHELL_WRITE_RE = /(?:>|>>|\bOut-File\b|\bSet-Content\b|\bAdd-Content\b|\bNew-Item\b|\bRemove-Item\b|\bMove-Item\b|\bCopy-Item\b|\btee\b|\brm\s|\bmv\s|\bcp\s|\btouch\s|\bmkdir\s)/i

/**
 * 同步规范化（含最深存在祖先 realpathSync + Windows 小写归一化）。
 * @param {string} targetPath
 * @param {string} [baseDir]
 */
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

/**
 * 提取工具参数中所有候选路径字段。
 * @param {unknown} args
 * @returns {string[]}
 */
export function extractPathValues(args) {
  if (!args || typeof args !== 'object') return []
  const found = []
  for (const key of PATH_ARG_KEYS) {
    const val = args[key]
    if (typeof val === 'string' && val.trim()) found.push(val.trim())
  }
  return found
}

/**
 * 将命令字符串中指向当前隔离沙箱自身规范路径的片段替换为 `<OWN_SANDBOX>`，
 * 使用右边界断言严防前缀碰撞（如 `b_q1_1` 绝不误匹配同辈 `b_q1_10`），
 * 彻底根治 Windows 含空格路径（如 `D:\Documents\deepseek harness\...`）的正则截断误杀。
 * @param {string} cmd
 * @param {string} sandboxCanon
 */
function maskOwnSandboxInCommand(cmd, sandboxCanon) {
  if (!cmd || !sandboxCanon) return cmd
  const trimmed = sandboxCanon.replace(/[\\/]+$/, '')
  if (!trimmed) return cmd
  // 允许命令中混用 / 或 \，Win32 下忽略大小写
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\\|\\\//g, '[\\\\/]')
  const flags = process.platform === 'win32' ? 'gi' : 'g'
  const ownRe = new RegExp(`${escaped}(?=[\\\\/"'\\s,;)|&>]|$)`, flags)
  return cmd.replace(ownRe, '<OWN_SANDBOX>')
}

/**
 * 对 Shell 命令字符串执行逃逸、越权与外网静态审查。
 * @param {string} commandText
 * @param {{ role: string, sandboxCanon: string, workspaceCanon: string, worktreesCanon?: string, evaluatorsCanon?: string, protectedCanons?: string[], readonly?: boolean }} opts
 * @returns {string | null} 若命中违规则返回拒绝原因，否则 null
 */
export function evaluateShellCommandGuard(commandText, opts) {
  const role = String(opts.role || '')
  if (opts.readonly) {
    return 'SANDBOX_VIOLATION: 该会话已进入只读保护态（含 70% 遗嘱收官或结案归档），禁止再执行任何 Shell 命令'
  }
  if (role === 'logistics_coordinator' || role === 'supervisory_committee' || role === 'lineage_companion' || role === 'library_surveyor') {
    return `SANDBOX_VIOLATION: 角色 ${role} 无终端执行权限`
  }

  const cmd = String(commandText ?? '')
  if (!cmd.trim()) return null

  if (PROTECTED_TOKEN_RE.test(cmd)) {
    return 'SANDBOX_VIOLATION: Shell 命令严禁触及受保护数据库 (greatwall.db)、隐藏校准集 (_hidden_calibrations) 或外部控制面资产'
  }

  // 全局禁写过程 .md 公文
  if (/\.(?:md)\b/i.test(cmd) && SHELL_WRITE_RE.test(cmd)) {
    if (PROCESS_MD_FORBIDDEN_RE.test(cmd) || /(?:HANDOFF|AUDIT|CLOSURE|BRIEFING)\.md/i.test(cmd)) {
      return 'NO_MD_DOSSIER_POLICY: 严禁使用 Shell 生成过程性 .md 公文，请调用对应 MCP 窄工具写库'
    }
  }

  // 探索者与盲审官：同属严格单目录隔离沙箱
  if (role === 'explorer' || role === 'library_verifier') {
    if (/(?:^|[\s"'`(=,;\\\/])\.\.(?:[\\/]|$|['"`\s;,)])/.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 隔离区严禁使用上跳路径 (..)，请基于当前工作树根目录使用相对路径（如 reports/...）`
    }
    if (/~[\\/]|HOME\b|\$(?:env:)?(?:USERPROFILE|HOME|APPDATA|LOCALAPPDATA|TEMP|TMP|GREATWALL_|PLUGIN_DATA|DSH_HOME)/i.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 严禁探测宿主敏感环境变量或用户主目录`
    }
    if (/\bsqlite3\b/i.test(cmd)) {
      return `SANDBOX_VIOLATION: ${role} 严禁直接调用 sqlite3 探测数据库`
    }
    if (role === 'library_verifier') {
      if (VERIFIER_NETWORK_CMD_RE.test(cmd)) {
        return 'SANDBOX_VIOLATION: library_verifier 盲审沙箱物理断网，严禁发起任何网络命令或 HTTP/Socket 请求'
      }
      if (/\bworktrees\b/i.test(cmd)) {
        return 'SANDBOX_VIOLATION: library_verifier 严禁访问原探索分支 worktrees/ 目录'
      }
    }

    // 先带边界消去自身沙箱路径，确保含空格的合法自身路径零误杀，同时精准暴露同辈他脉 worktree 与外部禁区
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

    // 扫描消去自身沙箱后仍残留的显式绝对路径（优先匹配成对引号内含空格路径，再匹配无引号路径）
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
    // 工造司严禁修改或篡改探索者 worktrees/
    if (/\bworktrees[\\/]/i.test(cmd) && SHELL_WRITE_RE.test(cmd)) {
      return 'SANDBOX_VIOLATION: works_engineer 严禁修改探索者分支工作树 worktrees/'
    }
  }

  return null
}

/**
 * 构建纯规则评估器（供运行时 Guard 与单元测试直接复用，无需 mock DSH 容器）。
 * @param {object} opts
 * @param {string} opts.role
 * @param {string} opts.workspaceRoot
 * @param {string} [opts.worktreeAbsPath]
 * @param {string} [opts.sandboxAbsPath]
 * @param {string[]} [opts.protectedDirs]
 * @param {boolean | (() => boolean)} [opts.readonly=false]
 */
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

  // F6: 公开题面、公开输入与《补充裁决文档》统一只读可见（严禁越界到 worktrees/_hidden*/evaluators/final_delivery）
  const publicDirCanons = [
    ...PUBLIC_INPUT_DEFAULT_DIRS.map((d) => resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), d))),
    ...(Array.isArray(opts.sharedInputPaths) ? opts.sharedInputPaths : [])
      .filter(Boolean)
      .map((rel) => resolveCanonicalTarget(rel, opts.workspaceRoot || process.cwd()))
      .filter((c) => isInsideRoot(c, wsCanon)),
  ].filter(Boolean)

  // F7: 允许纯只读工具读取 DSH 系统临时溢出文件 os.tmpdir()/dsh-spill-*
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
    // 工作区顶层公开文档文件（如 B题.pdf、补充裁决.md 等）
    if (parts.length === 1) {
      const ext = path.extname(parts[0]).toLowerCase()
      if (PUBLIC_INPUT_TOP_EXTS.has(ext)) return true
    }
    return false
  }

  const autoProtected = [
    hiddenCalCanon,
    finalDeliveryCanon,
    ...(opts.protectedDirs || []).filter(Boolean),
  ]
  if (role === 'library_verifier') {
    autoProtected.push(worktreesCanon)
  }
  const protectedCanons = [...new Set(autoProtected.map((d) => resolveCanonicalTarget(d)).filter(Boolean))]

  /** @param {{ name?: string, arguments?: Record<string, any> }} exec */
  return function evaluateToolCall(exec) {
    const name = String(exec?.name || '')
    const args = exec?.arguments || {}
    const isReadonlyNow = Boolean(getReadonly())

    const isWriteTool = WRITE_TOOL_NAMES.has(name) || name.includes('write') || name.includes('edit')
    const isShellTool = SHELL_TOOL_NAMES.has(name) || typeof args?.command === 'string' || typeof args?.CommandLine === 'string'

    // 只读态强门禁必须早于 MCP 放行：70% 亲笔遗嘱回合同步禁掉写文件、Shell 与任何写/评测 MCP 工具！
    if (isReadonlyNow && (isWriteTool || isShellTool || READONLY_BLOCKED_MCP_TOOLS.has(name))) {
      return `SANDBOX_VIOLATION: 该会话已处于只读态（70% 亲笔遗嘱或已归档），严禁调用写入、终端或状态变更工具 (${name})`
    }

    // 31 个 Python MCP 窄工具与控制面工具由 Python RBAC 管控，非只读冲突时放行
    if (ALL_31_MCP_TOOLS.has(name) || name.startsWith('greatwall_')) {
      return undefined
    }

    // 纯 DB 角色：物理 0 原生工具（Guard 二次兜底）
    if (role === 'logistics_coordinator' || role === 'supervisory_committee') {
      return `SANDBOX_VIOLATION: ${role} 为纯 DB 治理角色（0 原生工具），禁止调用原生工具 ${name}`
    }

    // 盲审官缺失有效隔离沙箱时绝对 Fail-Closed，严禁回退主工作区
    if (role === 'library_verifier' && !sandboxCanon) {
      return `SANDBOX_VIOLATION: library_verifier 缺少有效独立盲审沙箱路径，禁止调用原生工具 ${name} 以防越界访问主工作区`
    }

    // 禁写过程 .md 公文 + 严禁只读角色修改磁盘
    if (isWriteTool) {
      if (role === 'library_surveyor' || role === 'lineage_companion' || role === 'library_verifier') {
        return `SANDBOX_VIOLATION: ${role} 严禁修改磁盘文件 (${name})`
      }
      for (const pVal of extractPathValues(args)) {
        if (PROCESS_MD_FORBIDDEN_RE.test(pVal)) {
          return 'NO_MD_DOSSIER_POLICY: V6-Up v3.0 严禁在磁盘撰写过程性 .md 公文（如 HANDOFF.md / *_AUDIT.md / *_CLOSURE.md），请直接写 SQLite 窄工具！'
        }
      }
    }

    // 路径隔离检查
    const baseForRel = effectiveSandboxDir || opts.workspaceRoot
    const pathVals = extractPathValues(args)
    for (const pVal of pathVals) {
      const canon = resolveCanonicalTarget(pVal, baseForRel)
      const isVerifierOwnSandbox = role === 'library_verifier' && Boolean(sandboxCanon) && isInsideRoot(canon, sandboxCanon)
      if (PROTECTED_TOKEN_RE.test(pVal)) {
        const isCalForWorks = role === 'works_engineer' && /_hidden_calibrations/i.test(pVal) && !/greatwall\.db/i.test(pVal)
        const isDbOrHidden = /(?:greatwall\.db(?:-wal|-shm)?|_hidden_calibrations|GREATWALL_DATA_DIR|GREATWALL_DB_PATH|GREATWALL_PLUGIN_DATA_DIR)/i.test(pVal)
        if (!isCalForWorks && !(isVerifierOwnSandbox && !isDbOrHidden)) {
          return `SANDBOX_VIOLATION: 角色 ${role} 严禁访问受保护资产 (${pVal})`
        }
      }
      if (role !== 'works_engineer') {
        for (const prot of protectedCanons) {
          if (isVerifierOwnSandbox) {
            continue
          }
          if (isInsideRoot(canon, prot)) {
            return `SANDBOX_VIOLATION: 禁止访问受保护外部数据区或隐藏资产 (${pVal})`
          }
        }
      }

      const isPureReadTool = !isWriteTool && !isShellTool && READONLY_FS_TOOL_NAMES.has(name)
      const isPublicOrSpillRead = isPureReadTool && (isAllowedPublicRead(canon) || isAllowedDshSpillRead(canon))
      const isSpillOnlyRead = isPureReadTool && isAllowedDshSpillRead(canon)
      const worktreeInputsCanon = sandboxCanon ? path.join(sandboxCanon, 'inputs') : ''

      if (role === 'explorer' || role === 'lineage_companion') {
        if (isWriteTool && worktreeInputsCanon && isInsideRoot(canon, worktreeInputsCanon)) {
          return `SANDBOX_VIOLATION: ${role} 严禁修改只读公开输入挂载目录 (${pVal})`
        }
        if ((!sandboxCanon || !isInsideRoot(canon, sandboxCanon)) && !isPublicOrSpillRead) {
          return `SANDBOX_VIOLATION: ${role} 仅限在配对隔离工作树 (${effectiveSandboxDir}) 与公开只读输入区内访问，禁止越界 ${pVal}`
        }
      } else if (role === 'library_verifier') {
        // 盲审沙箱已精准拷贝手稿绑定 spec_revision 的 inputs/，严禁直接读取主工作区公开目录（防止旧手稿盲审偷看事后新裁决 rulings/）
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
      } else if (role === 'library_surveyor') {
        if (!isInsideRoot(canon, wsCanon) && !isPublicOrSpillRead) {
          return `SANDBOX_VIOLATION: library_surveyor 仅限在实验工作区内只读访问，禁止越界 ${pVal}`
        }
      }
    }

    // Shell 命令审查
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

/**
 * 在 DSH `setup(agentCtx, agent)` 或冷恢复 `agent/created` 内挂载双隔离同步 Guard。
 * @param {object} agentCtx
 * @param {object} opts
 */
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
    try {
      disposeGuard()
    } catch {}
  }
}
