/**
 * 持久化 Single-Writer Python MCP 桥接客户端（Stdio JSON-RPC 2.0 / NDJSON）。
 * 维护单个长期常驻的 `python -u -m mcp_server.greatwall_core_mcp` 子进程，
 * 确保 SQLite WAL 写入经统一排队无并发锁冲突，并从 Python 获取权威 31 工具 JSON Schema。
 * @module dsh-greatwall-v6up/mcp_bridge
 */
import { spawn } from 'node:child_process'
import { createInterface } from 'node:readline'
import path from 'node:path'

export class GreatwallMcpBridge {
  /**
   * @param {object} opts
   * @param {string} opts.corePythonRoot
   * @param {string} [opts.workspaceRoot]
   * @param {string} [opts.pythonBin]
   * @param {string} [opts.dataDir]
   * @param {number} [opts.requestTimeoutMs]
   */
  constructor(opts) {
    this.corePythonRoot = path.resolve(opts.corePythonRoot)
    this.workspaceRoot = opts.workspaceRoot ? path.resolve(opts.workspaceRoot) : ''
    this.pythonBin = opts.pythonBin || process.env.GREATWALL_PYTHON || 'python'
    this.dataDir = opts.dataDir || ''
    this.requestTimeoutMs = Number(opts.requestTimeoutMs ?? 60_000)

    /** @type {import('node:child_process').ChildProcessWithoutNullStreams | null} */
    this._proc = null
    /** @type {ReturnType<typeof createInterface> | null} */
    this._rl = null
    this._nextId = 1
    /** @type {Map<number, { resolve: Function, reject: Function, timer: NodeJS.Timeout }>} */
    this._pending = new Map()
    /** @type {Promise<void> | null} */
    this._initPromise = null
    this._disposed = false
    this._stderrTail = []
    /** @type {Array<object> | null} */
    this._cachedToolSchemas = null
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
    const env = {
      ...process.env,
      PYTHONPATH: this.corePythonRoot + (process.env.PYTHONPATH ? path.delimiter + process.env.PYTHONPATH : ''),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUTF8: '1',
    }
    if (this.workspaceRoot) env.GREATWALL_WORKSPACE_ROOT = this.workspaceRoot
    if (this.dataDir) {
      env.PLUGIN_DATA = this.dataDir
      env.GREATWALL_DATA_DIR = this.dataDir
    }

    const child = spawn(this.pythonBin, ['-u', '-m', 'mcp_server.greatwall_core_mcp'], {
      cwd: this.corePythonRoot,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    })
    this._proc = child
    this._stderrTail = []

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
      this._pending.delete(id)
      clearTimeout(entry.timer)
      if (msg.error) {
        const err = new Error(String(msg.error?.message ?? 'MCP JSON-RPC Error'))
        err.code = msg.error?.code
        entry.reject(err)
      } else {
        entry.resolve(msg.result)
      }
    })

    child.on('exit', (code, signal) => {
      const stderrSummary = this._stderrTail.join('').slice(-600)
      for (const [id, entry] of this._pending.entries()) {
        clearTimeout(entry.timer)
        entry.reject(new Error(`Python MCP 进程退出 (code=${code}, signal=${signal}): ${stderrSummary}`))
        this._pending.delete(id)
      }
      if (this._proc === child) {
        this._proc = null
        this._rl = null
        this._initPromise = null
      }
    })

    await this._rpc('initialize', {})
  }

  /**
   * @param {string} method
   * @param {object} params
   * @param {number} [timeoutMs]
   * @returns {Promise<any>}
   */
  async _rpc(method, params, timeoutMs = this.requestTimeoutMs) {
    if (!this._proc || !this._proc.stdin.writable) {
      throw new Error('Python MCP 管道不可写')
    }
    const id = this._nextId++
    const payload = JSON.stringify({ jsonrpc: '2.0', id, method, params: params ?? {} }) + '\n'
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this._pending.delete(id)
        reject(new Error(`MCP 请求超时 (${method}, ${timeoutMs}ms)`))
      }, timeoutMs)
      this._pending.set(id, { resolve, reject, timer })
      this._proc.stdin.write(payload, 'utf8', (writeErr) => {
        if (writeErr) {
          this._pending.delete(id)
          clearTimeout(timer)
          reject(writeErr)
        }
      })
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
   * @param {string} name
   * @param {object} args
   * @param {{ workspaceRoot?: string, role: string, sessionId: string }} trustedCtx
   */
  async callTool(name, args, trustedCtx) {
    await this.ensureStarted()
    const cleanArgs = args && typeof args === 'object' ? { ...args } : {}
    delete cleanArgs._meta
    delete cleanArgs.caller_role
    delete cleanArgs.role
    delete cleanArgs.session_id
    delete cleanArgs.workspace_root
    const mergedArgs = {
      ...cleanArgs,
      _meta: {
        workspace_root: trustedCtx.workspaceRoot || this.workspaceRoot,
        caller_role: trustedCtx.role,
        session_id: trustedCtx.sessionId,
      },
    }
    const rpcRes = await this._rpc('tools/call', { name, arguments: mergedArgs })
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
   * @param {'control_plane/init_epoch'|'control_plane/schedule_snapshot'|'control_plane/sync_pressure'|'control_plane/fact_edge'} method
   * @param {object} params
   */
  async control(method, params) {
    await this.ensureStarted()
    const merged = {
      workspace_root: this.workspaceRoot,
      ...(params && typeof params === 'object' ? params : {}),
    }
    return this._rpc(method, merged)
  }

  async dispose() {
    this._disposed = true
    for (const [id, entry] of this._pending.entries()) {
      clearTimeout(entry.timer)
      entry.reject(new Error('GreatwallMcpBridge disposed'))
      this._pending.delete(id)
    }
    if (this._rl) {
      this._rl.close()
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
}
