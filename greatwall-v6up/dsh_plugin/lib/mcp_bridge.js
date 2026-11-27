/**
 * 持久化 Single-Writer Python MCP 桥接客户端（Stdio JSON-RPC 2.0 / NDJSON，v3.0）。
 *
 * - 维护常驻的 `python -u -m core_python.mcp_server.greatwall_core_mcp` 子进程；
 * - 全故障收口：监听 `spawn error`、`stdin error`、`exit`、超时与 `AbortSignal`，每条请求严格单次结算；
 * - 端到端真取消：当 `signal` 触发或超时时立即向 Python 发送 `$/cancelRequest` 通知，避免僵尸算力与幽灵写入。
 * @module dsh-greatwall-v6up/mcp_bridge
 */
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import path from 'node:path'

/** 需要长超时的重计算/跨进程校准与恢复工具清单。 */
export const LONG_RUNNING_MCP_TOOLS = Object.freeze(new Set([
  'run_isolated_eval',
  'register_question_instrument',
  'upgrade_instrument_with_calibration',
  'recompute_stage_b_only',
  'export_stage3_final_delivery',
]))

export const LONG_RUNNING_CONTROL_METHODS = Object.freeze(new Set([
  'control_plane/recover_heavy_jobs',
  'control_plane/operator_finish_node_jobs',
]))

function createAbortError(message = 'MCP 请求已取消') {
  const err = new Error(message)
  err.name = 'AbortError'
  err.code = 'ABORT_ERR'
  return err
}

export class GreatwallMcpBridge {
  /**
   * @param {object} opts
   * @param {string} opts.corePythonRoot
   * @param {string} [opts.workspaceRoot]
   * @param {string} [opts.pythonBin]
   * @param {string} [opts.dataDir]
   * @param {number} [opts.requestTimeoutMs] 常规窄工具超时（默认 60s）
   * @param {number} [opts.longToolTimeoutMs] 仪器评测/校准/重评长超时（默认 300s）
   */
  constructor(opts) {
    this.corePythonRoot = path.resolve(opts.corePythonRoot)
    this.projectRoot = path.dirname(this.corePythonRoot)
    this.workspaceRoot = opts.workspaceRoot ? path.resolve(opts.workspaceRoot) : ''
    this.pythonBin = opts.pythonBin || process.env.GREATWALL_PYTHON || 'python'
    this.dataDir = opts.dataDir || ''
    this.requestTimeoutMs = Number(opts.requestTimeoutMs ?? 60_000)
    this.longToolTimeoutMs = Number(opts.longToolTimeoutMs ?? 300_000)

    /** @type {import('node:child_process').ChildProcessWithoutNullStreams | null} */
    this._proc = null
    /** @type {ReturnType<typeof createInterface> | null} */
    this._rl = null
    this._nextId = 1
    /** @type {Map<number, { settle: (err: any, val?: any) => void, child: any }>} */
    this._pending = new Map()
    /** @type {Promise<void> | null} */
    this._initPromise = null
    this._disposed = false
    this._stderrTail = []
    /** @type {Array<object> | null} */
    this._cachedToolSchemas = null
    /** @type {Record<string, any> | null} */
    this._cachedContracts = null
  }

  /** 根据工具名与参数（如 tier）解析分层超时毫秒数。 */
  resolveToolTimeoutMs(name, args = {}) {
    if (name === 'run_isolated_eval' && String(args?.tier || '').toLowerCase() === 'probe') {
      return this.requestTimeoutMs
    }
    if (LONG_RUNNING_MCP_TOOLS.has(name)) {
      return Math.max(this.requestTimeoutMs, this.longToolTimeoutMs)
    }
    return this.requestTimeoutMs
  }

  /** 根据控制面原语解析分层超时毫秒数。 */
  resolveControlTimeoutMs(method) {
    if (LONG_RUNNING_CONTROL_METHODS.has(method)) {
      return Math.max(this.requestTimeoutMs, this.longToolTimeoutMs)
    }
    return this.requestTimeoutMs
  }

  _rejectPendingForChild(child, err) {
    for (const [id, entry] of [...this._pending.entries()]) {
      if (!child || entry.child === child) {
        entry.settle(err)
      }
    }
  }

  _detachChild(child) {
    if (this._proc === child) {
      this._proc = null
      if (this._rl) {
        try { this._rl.close() } catch {}
        this._rl = null
      }
      this._initPromise = null
    }
  }

  _sendCancelNotification(id, child = this._proc) {
    if (!child || child.killed || !child.stdin?.writable) return
    try {
      const payload = JSON.stringify({ jsonrpc: '2.0', method: '$/cancelRequest', params: { id } }) + '\n'
      child.stdin.write(payload, 'utf8', () => {})
    } catch {}
  }

  async ensureStarted() {
    if (this._disposed) {
      throw new Error('GreatwallMcpBridge 已关闭，无法重新启动')
    }
    if (this._proc && !this._proc.killed && this._proc.exitCode === null) {
      if (this._initPromise) await this._initPromise
      return
    }
    this._initPromise = this._spawnAndInitialize()
    try {
      await this._initPromise
    } catch (err) {
      this._initPromise = null
      throw err
    }
  }

  async _spawnAndInitialize() {
    const pyPathParts = [this.projectRoot, this.corePythonRoot]
    if (process.env.PYTHONPATH) pyPathParts.push(process.env.PYTHONPATH)
    const env = {
      ...process.env,
      PYTHONPATH: pyPathParts.join(path.delimiter),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    }
    if (this.workspaceRoot) env.GREATWALL_WORKSPACE_ROOT = this.workspaceRoot
    if (this.dataDir) {
      env.PLUGIN_DATA = this.dataDir
      env.GREATWALL_DATA_DIR = this.dataDir
      env.GREATWALL_PLUGIN_DATA_DIR = this.dataDir
    }

    const child = spawn(this.pythonBin, ['-u', '-m', 'core_python.mcp_server.greatwall_core_mcp'], {
      cwd: this.projectRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })
    this._proc = child
    this._stderrTail = []

    child.on('error', (spawnErr) => {
      const err = new Error(`Python MCP 进程启动失败 (${this.pythonBin}): ${spawnErr?.message || spawnErr}`)
      err.code = spawnErr?.code || 'MCP_SPAWN_ERROR'
      this._rejectPendingForChild(child, err)
      this._detachChild(child)
    })

    child.stdin.on('error', (stdinErr) => {
      const err = new Error(`Python MCP stdin 管道写入异常: ${stdinErr?.message || stdinErr}`)
      err.code = stdinErr?.code || 'MCP_STDIN_ERROR'
      this._rejectPendingForChild(child, err)
    })

    child.stderr.on('data', (chunk) => {
      const text = chunk.toString('utf8')
      this._stderrTail.push(text)
      if (this._stderrTail.length > 20) this._stderrTail.shift()
    })

    const rl = createInterface({ input: child.stdout, crlfDelay: Infinity })
    this._rl = rl
    rl.on('line', (line) => {
      const trimmed = line.trim()
      if (!trimmed) return
      let msg
      try {
        msg = JSON.parse(trimmed)
      } catch {
        return
      }
      const id = msg?.id
      if (typeof id !== 'number') return
      const entry = this._pending.get(id)
      if (!entry) return
      if (msg.error) {
        const err = new Error(String(msg.error?.message ?? 'MCP JSON-RPC Error'))
        err.code = msg.error?.code
        entry.settle(err)
      } else {
        entry.settle(null, msg.result)
      }
    })

    child.on('exit', (code, signal) => {
      const stderrSummary = this._stderrTail.join('').slice(-600)
      const err = new Error(`Python MCP 进程退出 (code=${code}, signal=${signal}): ${stderrSummary}`)
      err.code = 'MCP_PROCESS_EXITED'
      this._rejectPendingForChild(child, err)
      this._detachChild(child)
    })

    await this._rpc('initialize', {})
  }

  /**
   * @param {string} method
   * @param {object} params
   * @param {number} [timeoutMs]
   * @param {{ signal?: AbortSignal | null }} [opts]
   * @returns {Promise<any>}
   */
  async _rpc(method, params, timeoutMs = this.requestTimeoutMs, { signal = null } = {}) {
    if (signal?.aborted) {
      throw createAbortError(`MCP 请求在发送前已取消 (${method})`)
    }
    const child = this._proc
    if (!child || !child.stdin?.writable) {
      throw new Error('Python MCP 管道不可写')
    }
    const id = this._nextId++
    const payload = JSON.stringify({ jsonrpc: '2.0', id, method, params: params ?? {} }) + '\n'
    return new Promise((resolve, reject) => {
      let settled = false
      let timer = null

      const onAbort = () => {
        this._sendCancelNotification(id, child)
        settle(createAbortError(`MCP 请求已取消 (${method})`))
      }

      const settle = (err, val) => {
        if (settled) return
        settled = true
        this._pending.delete(id)
        if (timer) clearTimeout(timer)
        if (signal) {
          try { signal.removeEventListener('abort', onAbort) } catch {}
        }
        if (err) reject(err)
        else resolve(val)
      }

      timer = setTimeout(() => {
        this._sendCancelNotification(id, child)
        const err = new Error(`MCP 请求超时 (${method}, ${timeoutMs}ms)`)
        err.code = 'MCP_TIMEOUT'
        settle(err)
      }, timeoutMs)

      if (signal) {
        if (signal.aborted) {
          onAbort()
          return
        }
        signal.addEventListener('abort', onAbort, { once: true })
      }

      this._pending.set(id, { settle, child })
      try {
        child.stdin.write(payload, 'utf8', (writeErr) => {
          if (writeErr) settle(writeErr)
        })
      } catch (syncErr) {
        settle(syncErr)
      }
    })
  }

  /** @returns {Promise<Array<{ name: string, description: string, inputSchema: object }>>} */
  async listTools(forceRefresh = false) {
    if (this._cachedToolSchemas && !forceRefresh) return this._cachedToolSchemas
    await this.ensureStarted()
    const res = await this._rpc('tools/list', {})
    const tools = Array.isArray(res?.tools) ? res.tools : []
    this._cachedToolSchemas = tools
    return tools
  }

  /**
   * 拉取 Python 权威单一契约源（`tool_registry.py`）导出的角色工具表、只读拦截表与超时标记。
   * @param {boolean} [forceRefresh=false]
   * @returns {Promise<Record<string, any> | null>}
   */
  async describeContracts(forceRefresh = false) {
    if (this._cachedContracts && !forceRefresh) return this._cachedContracts
    await this.ensureStarted()
    const res = await this._rpc('control_plane/describe_contracts', {})
    const data = res?.ok && res?.data ? res.data : null
    if (data) this._cachedContracts = data
    return data
  }

  /**
   * 调用 32 窄工具（剥离模型伪造字段，双通道注入可信宿主 `_meta` 并应用分级超时与取消信号）。
   * @param {string} name
   * @param {object} args
   * @param {{ workspaceRoot?: string, role: string, sessionId: string, signal?: AbortSignal | null }} trustedCtx
   */
  async callTool(name, args, trustedCtx) {
    if (trustedCtx?.signal?.aborted) {
      throw createAbortError(`工具 ${name} 调用前已取消`)
    }
    await this.ensureStarted()
    const cleanArgs = args && typeof args === 'object' ? { ...args } : {}
    delete cleanArgs._meta
    delete cleanArgs.caller_role
    delete cleanArgs.role
    delete cleanArgs.session_id
    delete cleanArgs.workspace_root

    const meta = {
      workspace_root: trustedCtx.workspaceRoot || this.workspaceRoot,
      caller_role: trustedCtx.role,
      session_id: trustedCtx.sessionId,
      session_epoch_id: trustedCtx.sessionEpochId,
      human_rpc_id: trustedCtx.humanMandate?.rpcId || '',
      human_message: trustedCtx.humanMandate?.text || '',
    }
    const timeoutMs = this.resolveToolTimeoutMs(name, cleanArgs)
    const rpcRes = await this._rpc(
      'tools/call',
      { name, arguments: { ...cleanArgs, _meta: meta }, _meta: meta },
      timeoutMs,
      { signal: trustedCtx?.signal || null },
    )
    const textBlock = Array.isArray(rpcRes?.content) ? rpcRes.content.find((c) => c?.type === 'text') : null
    if (textBlock && typeof textBlock.text === 'string') {
      try {
        return JSON.parse(textBlock.text)
      } catch {
        return { ok: !rpcRes?.isError, rawText: textBlock.text }
      }
    }
    return rpcRes
  }

  /**
   * 调用 Single-Writer 内部控制面原语（非模型工具）。
   * @param {string} method
   * @param {object} [params]
   * @param {{ signal?: AbortSignal | null, timeoutMs?: number }} [opts]
   */
  async control(method, params = {}, opts = {}) {
    if (opts?.signal?.aborted) {
      throw createAbortError(`控制面调用 ${method} 在发送前已取消`)
    }
    await this.ensureStarted()
    const merged = {
      workspace_root: this.workspaceRoot,
      ...(params && typeof params === 'object' ? params : {}),
    }
    const timeoutMs = Number(opts?.timeoutMs || 0) || this.resolveControlTimeoutMs(method)
    return this._rpc(method, merged, timeoutMs, { signal: opts?.signal || null })
  }

  /** 关闭当前常驻子进程以释放系统资源（不设 _disposed，后续有 RPC 时按需自动重启）。 */
  async closeIdleChild() {
    const closeErr = new Error('GreatwallMcpBridge closed')
    closeErr.code = 'MCP_BRIDGE_CLOSED'
    this._rejectPendingForChild(null, closeErr)
    this._initPromise = null
    if (this._rl) {
      try { this._rl.close() } catch {}
      this._rl = null
    }
    if (this._proc) {
      const child = this._proc
      this._proc = null
      try {
        child.stdin.end()
      } catch {}
      await new Promise((resolve) => {
        const killTimer = setTimeout(() => {
          try {
            child.kill('SIGTERM')
          } catch {}
          resolve()
        }, 800)
        child.once('exit', () => {
          clearTimeout(killTimer)
          resolve()
        })
      })
    }
  }

  async dispose() {
    this._disposed = true
    await this.closeIdleChild()
  }
}
