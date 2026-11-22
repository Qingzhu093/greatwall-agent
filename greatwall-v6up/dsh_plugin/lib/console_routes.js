/**
 * 长城 V6-Up (v3.0) 右侧栏「长城科研指挥舱」服务端鉴权 HTTP 路由：
 *
 * 通过 DSH 原生 `ctx.connection.fetch.register(...)`（处于 Connection 鉴权围栏内）暴露：
 * - GET  /api/greatwall.status  : 获取活跃或磁盘历史工作区的实时编排状态、谱系 DAG Flow、五段看板/37%元反思/70%遗嘱、跨 cwd 对话流、Worktree 文件树与源码预览；
 * - POST /api/greatwall.control : 在 UI 面板直接执行 pause / resume / stop / human_stop / abort_node 节点定向纠偏。
 * @module dsh-greatwall-v6up/console_routes
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildBlackboxTrajectorySummary } from './blackbox_projection.js'
import { GreatwallMcpBridge } from './mcp_bridge.js'
import { computeWorkspaceHash } from './telemetry.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DEFAULT_CORE_PYTHON_ROOT = path.resolve(__dirname, '..', '..', 'core_python')

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

async function extractNodeConversations(ctx, telemetryState, selectedNodeId) {
  if (!selectedNodeId || !telemetryState?.sessions) return []
  const matched = Object.values(telemetryState.sessions)
    .filter((s) => s && String(s.nodeId || '') === String(selectedNodeId))
    .sort((a, b) => String(a.startedAt || '').localeCompare(String(b.startedAt || '')))
  const out = []
  for (const s of matched.slice(-6)) {
    const sid = String(s.sessionId || '')
    if (!sid) continue
    let traceText = ''
    try {
      traceText = await buildBlackboxTrajectorySummary(ctx, sid, 6400)
    } catch {
      traceText = '(无法提取该会话轨迹)'
    }
    out.push({
      sessionId: sid,
      role: s.role || 'explorer',
      title: s.title || s.role || sid,
      status: s.status || 'completed',
      startedAt: s.startedAt || null,
      endedAt: s.endedAt || null,
      pressureTokens: Number(s.pressureTokens || 0),
      traceText,
    })
  }
  return out
}

export function registerGreatwallConsoleRoutes(
  ctx,
  { activeControllersByWs, corePythonRoot = DEFAULT_CORE_PYTHON_ROOT, dataDir = '', pythonBin = '', logger = console },
) {
  if (!ctx) return () => {}

  /** @type {Map<string, GreatwallMcpBridge>} */
  const readonlyBridgesByWs = new Map()
  const getOrCreateReadonlyBridge = (wsRoot) => {
    const norm = path.resolve(wsRoot).toLowerCase()
    let b = readonlyBridgesByWs.get(norm)
    if (!b) {
      b = new GreatwallMcpBridge({
        corePythonRoot: corePythonRoot || DEFAULT_CORE_PYTHON_ROOT,
        workspaceRoot: path.resolve(wsRoot),
        dataDir,
        pythonBin: pythonBin || undefined,
        requestTimeoutMs: 25_000,
      })
      readonlyBridgesByWs.set(norm, b)
    }
    return b
  }

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
          const selectedNodeId = (url.searchParams.get('selectedNodeId') || '').trim()
          const selectedFileRel = (url.searchParams.get('selectedFile') || '').trim()
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
            let inspector = null
            try {
              const inspRes = await ctrl.bridge.control('control_plane/ui_inspector', {
                workspace_root: ctrl.workspaceRoot,
                selected_node_id: selectedNodeId || null,
                selected_worktree_rel_file: selectedFileRel || null,
              })
              inspector = inspRes?.data || null
            } catch {}
            const activeNid = selectedNodeId || inspector?.selected_node_detail?.node_id || ''
            const nodeConversations = await extractNodeConversations(connCtx, tState, activeNid)
            return Response.json(
              {
                ok: true,
                source: 'live_controller',
                workspaceRoot: ctrl.workspaceRoot,
                knownWorkspaces,
                status,
                inspector,
                nodeConversations,
                telemetryState: {
                  orchestratorState: tState.orchestratorState || status.state,
                  stage: tState.stage || status.stage,
                  startedAt: tState.startedAt || null,
                  updatedAt: tState.updatedAt || null,
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
          let inspector = null
          if (fallbackWs) {
            try {
              const roBridge = getOrCreateReadonlyBridge(fallbackWs)
              const inspRes = await roBridge.control('control_plane/ui_inspector', {
                workspace_root: fallbackWs,
                selected_node_id: selectedNodeId || null,
                selected_worktree_rel_file: selectedFileRel || null,
              })
              inspector = inspRes?.data || null
            } catch {}
          }
          const activeNid = selectedNodeId || inspector?.selected_node_detail?.node_id || ''
          const nodeConversations = await extractNodeConversations(connCtx, diskData, activeNid)
          const snap = inspector?.snapshot || null
          return Response.json(
            {
              ok: true,
              source: diskData || snap?.initialized ? 'disk_telemetry' : 'empty',
              workspaceRoot: fallbackWs,
              knownWorkspaces,
              inspector,
              nodeConversations,
              status: diskData || snap
                ? {
                    poolState: diskData?.orchestratorState || 'archived',
                    state: diskData?.orchestratorState || 'archived',
                    kernelAlive: Boolean(snap),
                    initialized: Boolean(snap?.initialized),
                    stage: snap?.stage || diskData?.stage || 'STAGE1_PARSE0',
                    closureStatus: snap?.closure_state?.status || 'OPEN',
                    latestSpecRevision: Number(snap?.latest_spec_revision || 0),
                    runningExplorers: diskData?.activeExplorers || [],
                    runningGovernanceTasks: diskData?.activeGovernance || [],
                    snapshot: snap,
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
            return Response.json({ ok: true, action, ...(await ctrl.orchestrator.resumeBackground()) })
          }
          if (action === 'stop') {
            const stopRes = await ctrl.orchestrator.stopBackground('UI_CONSOLE_STOP')
            await ctrl.bridge?.closeIdleChild?.()
            return Response.json({ ok: true, action, ...stopRes })
          }
          if (action === 'human_stop') {
            return Response.json({
              ok: true,
              action,
              ...(await ctrl.orchestrator.humanStop(String(body?.note || body?.reason || 'UI_CONSOLE_HUMAN_STOP'))),
            })
          }
          if (action === 'abort_node') {
            const res = await ctrl.orchestrator.abortNode(
              String(body?.nodeId || body?.node_id || body?.targetId || ''),
              String(body?.reason || 'UI_CONSOLE_ABORT_NODE'),
            )
            return Response.json({ ok: Boolean(res?.aborted), action, ...res })
          }
          if (action === 'submit_works_ticket') {
            const res = await ctrl.orchestrator.submitWorksTicket({
              questionId: String(body?.questionId || body?.question_id || 'ALL'),
              ticketType: String(body?.ticketType || body?.ticket_type || 'INSTRUMENT_ERROR'),
              instrumentId: body?.instrumentId || body?.instrument_id || null,
              description: String(body?.description || body?.reason || ''),
              source: String(body?.source || 'ui_console'),
            })
            return Response.json({ ok: Boolean(res?.submitted), action, ...res })
          }
          if (action === 'sync_rulings') {
            const res = await ctrl.orchestrator.syncPublicRulings(Boolean(body?.refreshActiveWorktrees || body?.refresh_active_worktrees))
            return Response.json({ ok: Boolean(res?.synced), action, ...res })
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
    for (const b of readonlyBridgesByWs.values()) {
      void b.dispose().catch(() => {})
    }
    readonlyBridgesByWs.clear()
  }
}
