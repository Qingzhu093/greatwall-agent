/**
 * 长城 V6-Up (v3.0) 实时轻量遥测导出器：`epoch_telemetry_summary.json`
 *
 * 在关键状态跳变、节点启停与错误时原子刷新 `$PLUGIN_DATA/workspaces/<ws_hash>/epoch_telemetry_summary.json`，
 * 实现 `greatwall_orchestrate(action="status")` 秒级诊断与冷恢复身份查询。
 * @module dsh-greatwall-v6up/telemetry
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export function computeWorkspaceHash(workspaceRoot) {
  let real = workspaceRoot
  try {
    real = fs.realpathSync(workspaceRoot)
  } catch {
    real = path.resolve(workspaceRoot)
  }
  const norm = process.platform === 'win32' ? path.normalize(real).toLowerCase() : path.normalize(real)
  return crypto.createHash('sha256').update(norm, 'utf8').digest('hex').slice(0, 16)
}

export function resolveTelemetryFilePath({ dataDir = '', workspaceRoot }) {
  const wsHash = computeWorkspaceHash(workspaceRoot)
  const base = dataDir
    ? path.resolve(dataDir)
    : path.join(
        process.env.GREATWALL_PLUGIN_DATA_DIR ||
          process.env.PLUGIN_DATA ||
          path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'greatwall-v6up'),
      )
  return path.join(base, 'workspaces', wsHash, 'epoch_telemetry_summary.json')
}

export class TelemetryCollector {
  constructor({ workspaceRoot, dataDir = '' }) {
    this.workspaceRoot = workspaceRoot
    this.filePath = resolveTelemetryFilePath({ dataDir, workspaceRoot })
    let persistedSessions = {}
    let persistedCounters = {}
    let persistedModelBinding = null
    let persistedStage = 'STAGE1_PARSE0'
    let persistedStartedAt = null
    let persistedRecentEvents = []
    try {
      if (fs.existsSync(this.filePath)) {
        const prev = JSON.parse(fs.readFileSync(this.filePath, 'utf8'))
        if (prev?.sessions && typeof prev.sessions === 'object') {
          persistedSessions = prev.sessions
        }
        if (prev?.countersByRole && typeof prev.countersByRole === 'object') {
          persistedCounters = prev.countersByRole
        }
        if (typeof prev?.stage === 'string' && prev.stage.trim()) {
          persistedStage = prev.stage.trim()
        }
        if (typeof prev?.startedAt === 'string' && prev.startedAt.trim()) {
          persistedStartedAt = prev.startedAt.trim()
        }
        if (Array.isArray(prev?.recentEvents)) {
          persistedRecentEvents = prev.recentEvents.slice(-80)
        }
        if (prev?.lastModelBinding?.provider && prev?.lastModelBinding?.model) {
          persistedModelBinding = prev.lastModelBinding
        } else if (Array.isArray(prev?.recentEvents)) {
          for (let i = prev.recentEvents.length - 1; i >= 0; i--) {
            const ev = prev.recentEvents[i]
            if (ev?.kind === 'model_binding_locked' && ev.provider && ev.provider !== '(none)' && ev.model && ev.model !== '(none)') {
              persistedModelBinding = {
                provider: String(ev.provider),
                model: String(ev.model),
                effectiveContextWindow: Number(ev.effectiveContextWindow || 0) || 0,
              }
              break
            }
          }
        }
      }
    } catch {}
    this.state = {
      schemaVersion: '3.0.0',
      workspaceRoot,
      updatedAt: new Date().toISOString(),
      orchestratorState: 'idle',
      stage: persistedStage,
      startedAt: persistedStartedAt,
      lastModelBinding: persistedModelBinding,
      activeExplorers: [],
      activeGovernance: [],
      countersByRole: persistedCounters,
      sessions: persistedSessions,
      recentEvents: persistedRecentEvents,
    }
  }

  setModelBinding(binding) {
    if (!binding?.provider || !binding?.model) return
    this.state.lastModelBinding = {
      provider: String(binding.provider),
      model: String(binding.model),
      effectiveContextWindow: Number(binding.effectiveContextWindow || 0) || 0,
    }
    this.flush()
  }

  setOrchestratorState(orchestratorState, stage = '') {
    this.state.orchestratorState = orchestratorState
    if (stage) this.state.stage = stage
    if (orchestratorState === 'running' && !this.state.startedAt) {
      this.state.startedAt = new Date().toISOString()
    }
    this.flush()
  }

  recordEvent(kind, detail = {}) {
    this.state.recentEvents.push({
      at: new Date().toISOString(),
      kind,
      ...detail,
    })
    if (this.state.recentEvents.length > 80) {
      this.state.recentEvents.splice(0, this.state.recentEvents.length - 80)
    }
    this.flush()
  }

  recordSessionStart({
    sessionId,
    role,
    questionId = '',
    nodeId = '',
    branchId = '',
    reviewId = '',
    deliveryId = '',
    worktreeAbsPath = '',
    sandboxAbsPath = '',
    workspaceRoot = '',
    crossCwd = false,
    shortTransaction = true,
    title = '',
  }) {
    this.state.sessions[sessionId] = {
      sessionId,
      role,
      questionId,
      nodeId,
      branchId,
      reviewId,
      deliveryId,
      worktreeAbsPath,
      sandboxAbsPath,
      workspaceRoot: workspaceRoot || this.workspaceRoot,
      crossCwd: Boolean(crossCwd),
      shortTransaction: Boolean(shortTransaction),
      readonly: false,
      title,
      status: 'running',
      startedAt: new Date().toISOString(),
      endedAt: null,
      pressureTokens: 0,
      turnEndReason: null,
      archived: false,
      archiveError: null,
    }
    const c = (this.state.countersByRole[role] ||= { total: 0, abnormalEnds: 0, archived: 0 })
    c.total += 1
    this.flush()
  }

  recordSessionEnd({
    sessionId,
    status = 'completed',
    turnEndReason = null,
    pressureTokens = null,
    archived = false,
    archiveError = null,
  }) {
    const rec = this.state.sessions[sessionId]
    if (!rec) return
    rec.status = status
    rec.endedAt = new Date().toISOString()
    if (turnEndReason !== null) rec.turnEndReason = turnEndReason
    if (typeof pressureTokens === 'number') rec.pressureTokens = pressureTokens
    const wasArchived = Boolean(rec.archived)
    if (archived) {
      rec.archived = true
      rec.archiveError = null
    } else if (archiveError) {
      rec.archived = false
      rec.archiveError = String(archiveError)
    }
    const c = (this.state.countersByRole[rec.role] ||= { total: 0, abnormalEnds: 0, archived: 0 })
    if (status === 'interrupted_unclaimed' || status === 'error') {
      c.abnormalEnds += 1
    }
    if (archived && !wasArchived) {
      c.archived += 1
    }
    this.flush()
  }

  markArchived(sessionId, { readonly = true } = {}) {
    const rec = this.state.sessions[sessionId]
    if (rec) {
      if (readonly) rec.readonly = true
      rec.archiveError = null
      if (!rec.archived) {
        rec.archived = true
        const c = this.state.countersByRole[rec.role]
        if (c) c.archived += 1
      }
      this.flush()
    }
  }

  markArchiveFailed(sessionId, errorMessage = '') {
    const rec = this.state.sessions[sessionId]
    if (rec) {
      rec.readonly = true
      rec.archived = false
      rec.archiveError = String(errorMessage || '宿主归档调用失败')
      this.flush()
    }
  }

  getSessionIdentity(sessionId) {
    if (!sessionId) return null
    if (this.state.sessions[sessionId]) return this.state.sessions[sessionId]
    try {
      if (fs.existsSync(this.filePath)) {
        const disk = JSON.parse(fs.readFileSync(this.filePath, 'utf8'))
        const rec = disk?.sessions?.[sessionId]
        if (rec) {
          this.state.sessions[sessionId] = rec
          return rec
        }
      }
    } catch {}
    return null
  }

  updateActiveSlots({ activeExplorers = [], activeGovernance = [], stage = '' }) {
    this.state.activeExplorers = activeExplorers
    this.state.activeGovernance = activeGovernance
    if (stage) this.state.stage = stage
    this.flush()
  }

  getSummary() {
    return {
      schemaVersion: this.state.schemaVersion,
      telemetryFile: this.filePath,
      orchestratorState: this.state.orchestratorState,
      stage: this.state.stage,
      startedAt: this.state.startedAt,
      updatedAt: this.state.updatedAt,
      activeExplorers: this.state.activeExplorers,
      activeGovernance: this.state.activeGovernance,
      countersByRole: this.state.countersByRole,
      recentEvents: this.state.recentEvents.slice(-15),
    }
  }

  flush() {
    try {
      this.state.updatedAt = new Date().toISOString()
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
      const tmp = `${this.filePath}.${process.pid}.tmp`
      fs.writeFileSync(tmp, JSON.stringify(this.state, null, 2), 'utf8')
      fs.renameSync(tmp, this.filePath)
    } catch {
      // 遥测写失败不得阻塞主控制流
    }
  }
}
