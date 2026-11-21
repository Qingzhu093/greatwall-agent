/**
 * 长城 V6-Up (v3.0) 右侧栏「长城控制台」服务端鉴权 HTTP 路由：
 *
 * 通过 DSH 原生 `ctx.connection.fetch.register(...)`（处于 Connection 鉴权围栏内）暴露：
 * - GET  /api/greatwall.status  : 获取活跃或磁盘历史工作区的实时编排状态、子题 L3 进度、红灯告警与节点遥测；
 * - POST /api/greatwall.control : 在 UI 面板直接执行 pause / resume / stop / human_stop / intervene 节点定向纠偏。
 * @module dsh-greatwall-v6up/console_routes
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { computeWorkspaceHash } from './telemetry.js'

const STATUS_PATH = '/api/greatwall.status'
const CONTROL_PATH = '/api/greatwall.control'

function resolveTelemetryBaseDir(dataDir = '') {
  if (dataDir) return path.resolve(dataDir)
  return process.env.PLUGIN_DATA || path.join(process.env.DSH_HOME || path.join(os.homedir(), '.dsh'), 'greatwall-v6up')
}

function scanKnownTelemetryFiles(dataDir = '') {
  const wsParent = path.join(resolveTelemetryBaseDir(dataDir), 'workspaces')
  const items = []
  try {
    if (!fs.existsSync(wsParent)) return items
    for (const entry of fs.readdirSync(wsParent, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue
      const f = path.join(wsParent, entry.name, 'epoch_telemetry_summary.json')
      if (!fs.existsSync(f)) continue
      try {
        const parsed = JSON.parse(fs.readFileSync(f, 'utf8'))
        if (parsed && typeof parsed === 'object' && parsed.workspaceRoot) {
          items.push({ file: f, hash: entry.name, data: parsed })
        }
      } catch {}
    }
  } catch {}
  items.sort((a, b) => String(b.data?.updatedAt || '').localeCompare(String(a.data?.updatedAt || '')))
  return items
}

function resolveSessionCwd(ctx, sessionId) {
  if (!sessionId) return ''
  try {
    const sess = typeof ctx?.get === 'function' ? ctx.get('sessions')?.get?.(sessionId) : ctx?.sessions?.get?.(sessionId)
    return sess?.header?.cwd ? path.resolve(String(sess.header.cwd)) : ''
  } catch {
    return ''
  }
}

export function pickController({ activeControllersByWs, reqWorkspaceRoot = '', sessionCwd = '', allowFallback = true }) {
  const explicit = String(reqWorkspaceRoot || '').trim()
  if (explicit) {
    const foundExplicit = activeControllersByWs.get(path.resolve(explicit).toLowerCase())
    if (foundExplicit) return foundExplicit
    // 写控制操作（stop / human_stop / pause / intervene）显式指定工作区不匹配时严禁回退误杀隔壁工作区！
    if (!allowFallback) return null
  }
  if (sessionCwd) {
    const foundCwd = activeControllersByWs.get(path.resolve(sessionCwd).toLowerCase())
    if (foundCwd) return foundCwd
  }
  if (!allowFallback) {
    return activeControllersByWs.size === 1 ? activeControllersByWs.values().next().value : null
  }
  if (activeControllersByWs.size === 1) {
    return activeControllersByWs.values().next().value
  }
  for (const ctrl of activeControllersByWs.values()) {
    if (ctrl?.orchestrator?._poolState === 'running') return ctrl
  }
  return activeControllersByWs.values().next().value || null
}

function readDiskTelemetry(workspaceRoot, dataDir = '') {
  if (!workspaceRoot) return null
  const hash = computeWorkspaceHash(workspaceRoot)
  const file = path.join(resolveTelemetryBaseDir(dataDir), 'workspaces', hash, 'epoch_telemetry_summary.json')
  try {
    if (!fs.existsSync(file)) return null
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}

export function registerGreatwallConsoleRoutes(ctx, { activeControllersByWs, dataDir = '', logger = console }) {
  if (!ctx) return () => {}

  let mountedDisposer = null
  const mountOnConnection = (connCtx, connObj) => {
    const fetchReg = connObj?.fetch || connCtx?.connection?.fetch
    if (!fetchReg || typeof fetchReg.register !== 'function' || mountedDisposer) return () => {}

    const unregStatus = fetchReg.register({
      path: STATUS_PATH,
      methods: ['GET'],
      requestBody: 'buffered',
      fetch: async (request) => {
        try {
          const url = new URL(request.url)
          const reqWs = (url.searchParams.get('workspaceRoot') || '').trim()
          const sessionId = (url.searchParams.get('sessionId') || '').trim()
          const sessionCwd = resolveSessionCwd(connCtx, sessionId)

          const ctrl = pickController({
            activeControllersByWs,
            reqWorkspaceRoot: reqWs,
            sessionCwd,
          })
          const diskList = scanKnownTelemetryFiles(dataDir)
          const knownWorkspaces = [
            ...new Set([
              ...Array.from(activeControllersByWs.values()).map((c) => c.workspaceRoot),
              ...diskList.map((d) => String(d.data.workspaceRoot)),
              ...(sessionCwd ? [sessionCwd] : []),
            ]),
          ]

          if (ctrl) {
            const status = await ctrl.orchestrator.getControlStatus()
            const tState = ctrl.orchestrator.telemetry?.state || {}
            return Response.json(
              {
                ok: true,
                source: 'live_controller',
                workspaceRoot: ctrl.workspaceRoot,
                knownWorkspaces,
                status,
                telemetryState: {
                  orchestratorState: tState.orchestratorState || status.state,
                  stage: tState.stage || status.stage,
                  startedAt: tState.startedAt || null,
                  updatedAt: tState.updatedAt || null,
                  interventions: tState.interventions || [],
                  countersByRole: tState.countersByRole || {},
                  sessions: tState.sessions || {},
                  recentEvents: tState.recentEvents || [],
                },
              },
              { headers: { 'cache-control': 'no-store' } },
            )
          }

          const fallbackWs = reqWs || sessionCwd || diskList[0]?.data?.workspaceRoot || ''
          const diskData = readDiskTelemetry(fallbackWs, dataDir) || diskList[0]?.data || null
          return Response.json(
            {
              ok: true,
              source: diskData ? 'disk_telemetry' : 'empty',
              workspaceRoot: fallbackWs,
              knownWorkspaces,
              status: diskData
                ? {
                    state: diskData.orchestratorState || 'idle',
                    stage: diskData.stage || 'STAGE1_PARSE0',
                    runningExplorers: diskData.activeExplorers || [],
                    runningGovernanceTasks: diskData.activeGovernance || [],
                    snapshot: null,
                  }
                : null,
              telemetryState: diskData,
            },
            { headers: { 'cache-control': 'no-store' } },
          )
        } catch (err) {
          logger.warn?.('[dsh-greatwall-v6up] /api/greatwall.status error:', err?.message || err)
          return Response.json({ ok: false, error: String(err?.message || err) }, { status: 500 })
        }
      },
    })

    const unregControl = fetchReg.register({
      path: CONTROL_PATH,
      methods: ['POST'],
      requestBody: 'buffered',
      fetch: async (request) => {
        try {
          const body = await request.json().catch(() => ({}))
          const action = String(body?.action || '').trim()
          const reqWs = String(body?.workspaceRoot || '').trim()
          const sessionId = String(body?.sessionId || '').trim()
          const sessionCwd = resolveSessionCwd(connCtx, sessionId)

          const ctrl = pickController({
            activeControllersByWs,
            reqWorkspaceRoot: reqWs,
            sessionCwd,
            allowFallback: false,
          })
          if (!ctrl) {
            return Response.json(
              {
                ok: false,
                error: reqWs
                  ? `未找到目标工作区 (${reqWs}) 对应的活跃长城控制器，已拒绝回退以防误操作其他工作区。`
                  : '当前暂无运行中的长城编排控制器。请先在主控对话中调用 greatwall_orchestrate(action="start", ...) 启动任务。',
              },
              { status: 409 },
            )
          }

          if (action === 'pause') {
            return Response.json({ ok: true, action, ...(ctrl.orchestrator.pauseBackground()) })
          }
          if (action === 'resume') {
            return Response.json({ ok: true, action, ...(ctrl.orchestrator.resumeBackground()) })
          }
          if (action === 'stop') {
            return Response.json({ ok: true, action, ...(await ctrl.orchestrator.stopBackground('UI_CONSOLE_STOP')) })
          }
          if (action === 'human_stop') {
            return Response.json({
              ok: true,
              action,
              ...(await ctrl.orchestrator.humanStop(String(body?.note || body?.directive || 'UI_CONSOLE_HUMAN_STOP'))),
            })
          }
          if (action === 'intervene') {
            const res = await ctrl.orchestrator.intervene({
              targetType: String(body?.targetType || 'global'),
              targetId: String(body?.targetId || 'ALL'),
              directive: String(body?.directive || ''),
              action: String(body?.interventionAction || 'steer'),
            })
            return Response.json({ ok: true, action, ...res })
          }
          return Response.json({ ok: false, error: `不支持的控制台动作: ${action}` }, { status: 400 })
        } catch (err) {
          logger.warn?.('[dsh-greatwall-v6up] /api/greatwall.control error:', err?.message || err)
          return Response.json({ ok: false, error: String(err?.message || err) }, { status: 500 })
        }
      },
    })

    const cleanup = () => {
      mountedDisposer = null
      try { unregStatus?.() } catch {}
      try { unregControl?.() } catch {}
    }
    mountedDisposer = cleanup
    return cleanup
  }

  let existingConn = null
  try {
    existingConn = typeof ctx.get === 'function' ? ctx.get('connection') : ctx.connection
  } catch {}
  if (existingConn?.fetch) {
    mountOnConnection(ctx, existingConn)
  }

  let injectDisposer = null
  if (!mountedDisposer && typeof ctx.inject === 'function') {
    injectDisposer = ctx.inject(['connection'], (connCtx) => {
      let c = null
      try {
        c = typeof connCtx.get === 'function' ? connCtx.get('connection') : connCtx.connection
      } catch {}
      return mountOnConnection(connCtx, c)
    })
  }

  return () => {
    try { mountedDisposer?.() } catch {}
    try { typeof injectDisposer === 'function' && injectDisposer() } catch {}
  }
}
