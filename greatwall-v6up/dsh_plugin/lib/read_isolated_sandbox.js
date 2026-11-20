/**
 * 方案 A 混合读写隔离沙箱与双保险 Guard（v2.2 零过程 .md 公文 + 物理跨脉盲视）。
 *
 * 结合 DSH 0.2.2-rc.3 原生 `agentCtx.tools.guard` / `tools/pre-execute`：
 * 1. `resolveCanonicalTarget`: 使用 `fs.realpathSync` 逐层解析最深存在祖先并拼接剩余段，
 *    彻底免疫 `..`、大小写、Windows 8.3 短名及符号链接/目录联结绕过；
 * 2. 保护边界：
 *    - 严禁非特权角色读写外部 `$PLUGIN_DATA`（含 `greatwall.db`）、`evaluators/anchors`、
 *      任何 `_hidden*` 文件及兄弟分支 Worktree（不在自己 `worktreeAbsPath` 内的其他 `worktrees/*`）；
 *    - 严禁 7 大角色用写文件或 Shell 重定向写入过程公文（`HANDOFF*.md`, `*_AUDIT.md`, `*_CLOSURE.md`, `REVIEW*.md`）；
 * 3. Exploration-Safe `pwsh` / `bash` Shell Guard：
 *    - 拦截命令字符串中的跨目录绝对路径、上跳 `..\\`/`../`、`$env:GREATWALL_*`、`greatwall.db`、
 *      `anchors`、`_hidden`、以及跨 worktree 访问；仅在本人 `worktreeAbsPath` 内放行科研计算执行！
 * 4. 可控环境 Env 隔离（供 `dsh` / 子进程清洗泄露路径）与可选只读/ACL 状态记录。
 * @module dsh-greatwall-v6up/read_isolated_sandbox
 */
import fs from 'node:fs'
import path from 'node:path'
import { ROLE_MCP_TOOLS } from './prompts.js'

const ALL_31_MCP_TOOLS = new Set(Object.values(ROLE_MCP_TOOLS).flat())

export const PROCESS_MD_FORBIDDEN_RE = /(?:^|[\\/])(?:HANDOFF[^\\/]*|REVIEW[^\\/]*|SUPERVISORY[^\\/]*|LINEAGE_BRIEFING[^\\/]*|.*_(?:AUDIT|CLOSURE|HANDOFF|BRIEFING|VERDICT|REPORT))\.md$/i

export const PROTECTED_TOKEN_RE = /(?:greatwall\.db(?:-wal|-shm)?|greatwall-v6up[\\/]workspaces|_hidden[a-z0-9_]*|evaluators[\\/]anchors|anchors[\\/]Q\d+|final_delivery|GREATWALL_DATA_DIR|GREATWALL_DB_PATH)/i

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

/**
 * 同步规范化（含最深存在祖先 realpathSync + 小写 Windows 归一化）。
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
 * 对 Shell 命令字符串执行逃逸与跨界访问静态审查。
 * @param {string} commandText
 * @param {{ role: string, worktreeCanon: string, workspaceCanon: string, protectedCanons: string[], readonly?: boolean }} opts
 * @returns {string | null} 若命中违规则返回拒绝原因，否则 null
 */
export function evaluateShellCommandGuard(commandText, opts) {
  if (opts.readonly) {
    return 'SANDBOX_VIOLATION: 该会话已结案进入只读保护态，禁止再执行任何 Shell 命令'
  }
  const cmd = String(commandText ?? '')
  if (!cmd.trim()) return null

  if (PROTECTED_TOKEN_RE.test(cmd)) {
    return 'SANDBOX_VIOLATION: Shell 命令严禁触及受保护数据库 (greatwall.db)、真值锚点 (anchors) 或隐藏资产'
  }

  // 严禁写出过程 .md 公文
  if (/\.(?:md)\b/i.test(cmd) && /(?:>|>>|Out-File|Set-Content|Add-Content|New-Item|tee)\b/i.test(cmd)) {
    if (PROCESS_MD_FORBIDDEN_RE.test(cmd) || /(?:HANDOFF|AUDIT|CLOSURE|BRIEFING)\.md/i.test(cmd)) {
      return 'NO_MD_DOSSIER_POLICY: 严禁使用 Shell 生成过程性 .md 公文，请调用对应 MCP 窄工具写库'
    }
  }

  if (opts.role === 'explorer') {
    // 禁止工作树上跳、家目录缩写或环境变量路径探测
    if (/(?:^|[\s"'`(=,;\\\/])\.\.(?:[\\/]|$|['"`\s;,)])/.test(cmd)) {
      return 'SANDBOX_VIOLATION: explorer 隔离区严禁使用上跳路径 (..)'
    }
    if (/~[\\/]|HOME\b|\$(?:env:)?(?:USERPROFILE|HOME|APPDATA|LOCALAPPDATA|TEMP|TMP|GREATWALL_|PLUGIN_DATA|DSH_HOME)/i.test(cmd)) {
      return 'SANDBOX_VIOLATION: explorer 严禁探测宿主敏感环境变量或用户主目录'
    }
    if (/\bsqlite3\b/i.test(cmd)) {
      return 'SANDBOX_VIOLATION: explorer 严禁直接调用 sqlite3 探测数据库'
    }
    // 检查兄弟 worktree 名称与受保护目录片段
    for (const prot of opts.protectedCanons || []) {
      const normalizedCmd = process.platform === 'win32' ? cmd.toLowerCase().replace(/\//g, '\\') : cmd
      const normalizedProt = process.platform === 'win32' ? prot.toLowerCase() : prot
      if (normalizedProt && normalizedCmd.includes(normalizedProt)) {
        return `SANDBOX_VIOLATION: explorer 严禁在 Shell 中引用受保护外部目录 (${prot})`
      }
    }
    // 扫描命令中出现的所有显式盘符/UNC绝对路径，必须全部位于本分支工作树或 Python 可执行路径白名单内
    const winAbsRe = /(?:[a-zA-Z]:[\\/]|\\\\)[^\s"'`;|><&()]+/g
    let m
    while ((m = winAbsRe.exec(cmd)) !== null) {
      const rawHit = m[0]
      const candidate = resolveCanonicalTarget(rawHit)
      const inOwnTree = isInsideRoot(candidate, opts.worktreeCanon)
      const isPythonOrTemp = /(?:python(?:\d+(?:\.\d+)*)?(?:\.exe)?|python3|uv(?:\.exe)?|\.venv)[\\/]?$/i.test(candidate) ||
        /[\\/]python\d*[\\/]python\.exe$/i.test(candidate)
      if (!inOwnTree && !isPythonOrTemp) {
        return `SANDBOX_VIOLATION: explorer 命令越界引用工作树外路径 (${rawHit})`
      }
    }
  }
  return null
}

/**
 * 在 DSH `setup(agentCtx, agent)` 或冷恢复 `agent/created` 内挂载方案 A 同步 Guard 与 `UNAUTHORIZED_TOOL_ATTEMPT` 审计记账。
 * @param {object} agentCtx
 * @param {object} opts
 * @param {string} opts.role
 * @param {string} opts.sessionId
 * @param {string} [opts.nodeId]
 * @param {string} opts.workspaceRoot
 * @param {string} [opts.worktreeAbsPath]
 * @param {string[]} [opts.protectedDirs]
 * @param {boolean} [opts.readonly=false]
 * @param {import('./mcp_bridge.js').GreatwallMcpBridge} [opts.bridge]
 * @returns {() => void}
 */
export function installRoleSandboxGuard(agentCtx, opts) {
  const role = String(opts.role || '')
  const readonly = Boolean(opts.readonly)
  const wsCanon = resolveCanonicalTarget(opts.workspaceRoot || process.cwd())
  const wtCanon = opts.worktreeAbsPath ? resolveCanonicalTarget(opts.worktreeAbsPath) : wsCanon
  const problemPackCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'problem_pack'))
  const anchorsCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'evaluators', 'anchors'))
  const finalDeliveryCanon = resolveCanonicalTarget(path.join(opts.workspaceRoot || process.cwd(), 'final_delivery'))

  const autoProtected = [
    anchorsCanon,
    finalDeliveryCanon,
    ...(opts.protectedDirs || []).filter(Boolean),
  ]
  const protectedCanons = [...new Set(autoProtected.map((d) => resolveCanonicalTarget(d)).filter(Boolean))]

  const reportUnauthorized = (toolName, reason, args) => {
    if (!opts.bridge) return
    void opts.bridge
      .control('control_plane/fact_edge', {
        workspace_root: opts.workspaceRoot,
        src_id: opts.nodeId || opts.sessionId || role,
        dst_id: `guard:${toolName}`,
        edge_type: 'UNAUTHORIZED_TOOL_ATTEMPT',
        metadata: {
          role,
          session_id: opts.sessionId,
          reason: String(reason).slice(0, 200),
          args_preview: JSON.stringify(args ?? {}).slice(0, 300),
        },
      })
      .catch(() => {})
  }

  /** @param {any} exec */
  const checkCall = (exec) => {
    const name = String(exec?.name || '')
    const args = exec?.arguments || {}

    if (readonly && (WRITE_TOOL_NAMES.has(name) || SHELL_TOOL_NAMES.has(name) || name.includes('write') || name.includes('edit'))) {
      return 'SANDBOX_VIOLATION: 该短事务会话已结案进入只读态，严禁再执行写入或终端操作'
    }

    // 自有 31 个 MCP 窄工具直接由 Python 控制面执行第二道 RBAC，这里放行
    if (ALL_31_MCP_TOOLS.has(name) || name.startsWith('greatwall_')) return undefined

    // 禁写过程 .md 公文（全局适用 7 角色）且禁止只读角色直接写磁盘
    if (WRITE_TOOL_NAMES.has(name) || name.includes('write') || name.includes('edit')) {
      if (role === 'library_surveyor' || role === 'lineage_companion' || role === 'logistics_coordinator' || role === 'supervisory_committee') {
        return `SANDBOX_VIOLATION: ${role} 严禁直接修改工作区文件`
      }
      for (const pVal of extractPathValues(args)) {
        if (PROCESS_MD_FORBIDDEN_RE.test(pVal)) {
          return 'NO_MD_DOSSIER_POLICY: V6-Up v2.2 严禁在磁盘撰写过程性 .md 公文（如 HANDOFF.md / *_AUDIT.md / *_CLOSURE.md），请直接写 SQLite 窄工具！'
        }
      }
    }

    // 路径隔离检查
    const baseForRel = (role === 'explorer' || role === 'lineage_companion') && opts.worktreeAbsPath
      ? opts.worktreeAbsPath
      : opts.workspaceRoot
    const pathVals = extractPathValues(args)
    for (const pVal of pathVals) {
      if (PROTECTED_TOKEN_RE.test(pVal)) {
        return `SANDBOX_VIOLATION: 角色 ${role} 严禁访问受保护资产 (${pVal})`
      }
      const canon = resolveCanonicalTarget(pVal, baseForRel)
      if (role !== 'works_engineer' && role !== 'supervisory_committee') {
        for (const prot of protectedCanons) {
          if (isInsideRoot(canon, prot)) {
            return `SANDBOX_VIOLATION: 禁止读写受保护外部数据区或真值锚点 (${pVal})`
          }
        }
      }
      if (role === 'explorer' || role === 'lineage_companion') {
        if (!isInsideRoot(canon, wtCanon)) {
          return `SANDBOX_VIOLATION: ${role} 仅限在配对隔离工作树 (${opts.worktreeAbsPath}) 内访问，禁止越界 ${pVal}`
        }
      } else if (role === 'logistics_coordinator') {
        // logistics_coordinator 仅可只读 problem_pack/ 与工作区根目录（严禁窥探 worktrees/ 与 evaluators/）
        const inProblemPack = isInsideRoot(canon, problemPackCanon)
        const isRootDir = canon === wsCanon
        if (!inProblemPack && !isRootDir) {
          return `SANDBOX_VIOLATION: logistics_coordinator 仅可只读 problem_pack/ 题面目录，禁止探视分支或评测代码 (${pVal})`
        }
      } else if (role === 'works_engineer' || role === 'library_surveyor') {
        if (!isInsideRoot(canon, wsCanon)) {
          return `SANDBOX_VIOLATION: ${role} 仅限在实验工作区内访问，禁止越界 ${pVal}`
        }
      }
    }

    // Shell 命令检查（DSH pwsh 的工作目录参数亦可覆盖，已在上面 pathVals 校验 args.cwd / args.workdir）
    if (SHELL_TOOL_NAMES.has(name) || typeof args?.command === 'string' || typeof args?.CommandLine === 'string') {
      const cmdStr = String(args?.command ?? args?.CommandLine ?? args?.script ?? '')
      const shellErr = evaluateShellCommandGuard(cmdStr, {
        role,
        readonly,
        worktreeCanon: wtCanon,
        workspaceCanon: wsCanon,
        protectedCanons,
      })
      if (shellErr) return shellErr
    }

    return undefined
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
