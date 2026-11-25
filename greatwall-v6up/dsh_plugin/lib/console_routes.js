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
    return null
  }
  if (activeControllersByWs.size === 1) {
    return activeControllersByWs.values().next().value
  }
  for (const ctrl of activeControllersByWs.values()) {
    const state = typeof ctrl?.orchestrator?.getPoolState === 'function'
      ? ctrl.orchestrator.getPoolState()
      : ctrl?.orchestrator?.poolState
    if (state === 'running') return ctrl
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
      crossCwd: Boolean(s.crossCwd),
      archived: Boolean(s.archived),
      archiveError: s.archiveError || null,
      traceText,
    })
  }
  return out
}

/**
 * 提取全部治理与盲审会话列表（含未绑定 nodeId 的 library_verifier，关联 reviewId/deliveryId 供前端一键直达原生对话）。
 */
export function extractGovernanceSessions(telemetryState) {
  if (!telemetryState?.sessions) return []
  return Object.values(telemetryState.sessions)
    .filter((s) => s && s.sessionId && s.role !== 'explorer')
    .sort((a, b) => String(b.startedAt || '').localeCompare(String(a.startedAt || '')))
    .slice(0, 40)
    .map((s) => ({
      sessionId: String(s.sessionId),
      role: s.role || 'unknown',
      title: s.title || s.role || String(s.sessionId),
      status: s.status || 'completed',
      questionId: s.questionId || '',
      nodeId: s.nodeId || '',
      reviewId: s.reviewId || '',
      deliveryId: s.deliveryId || '',
      crossCwd: Boolean(s.crossCwd),
      archived: Boolean(s.archived),
      archiveError: s.archiveError || null,
      startedAt: s.startedAt || null,
      endedAt: s.endedAt || null,
    }))
}

export function registerGreatwallConsoleRoutes(
  ctx,
  {
    activeControllersByWs,
    controlService = null,
    corePythonRoot = DEFAULT_CORE_PYTHON_ROOT,
    dataDir = '',
    pythonBin = '',
    logger = console,
  },
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

          // 显式指定了 workspaceRoot 时严格按该工作区读取，禁止回退显示其他在线工作区或历史 diskList[0]！
          const ctrl = pickController({
            activeControllersByWs,
            reqWorkspaceRoot: reqWs,
            sessionCwd,
            allowFallback: !reqWs,
          })
          const diskList = scanKnownTelemetryFiles(dataDir)
          const knownWorkspaces = [
            ...new Set([
              ...Array.from(activeControllersByWs.values()).map((c) => c.workspaceRoot),
              ...diskList.map((d) => String(d.data.workspaceRoot)),
              ...(sessionCwd ? [sessionCwd] : []),
              ...(reqWs ? [path.resolve(reqWs)] : []),
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
            const governanceSessions = extractGovernanceSessions(tState)
            return Response.json(
              {
                ok: true,
                source: 'live_controller',
                workspaceRoot: ctrl.workspaceRoot,
                knownWorkspaces,
                status,
                inspector,
                nodeConversations,
                governanceSessions,
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

          const targetWs = reqWs
            ? path.resolve(reqWs)
            : (sessionCwd || diskList[0]?.data?.workspaceRoot || '')
          const diskData = reqWs
            ? readDiskTelemetry(targetWs, dataDir)
            : (readDiskTelemetry(targetWs, dataDir) || diskList[0]?.data || null)
          let inspector = null
          if (targetWs) {
            try {
              const roBridge = getOrCreateReadonlyBridge(targetWs)
              const inspRes = await roBridge.control('control_plane/ui_inspector', {
                workspace_root: targetWs,
                selected_node_id: selectedNodeId || null,
                selected_worktree_rel_file: selectedFileRel || null,
              })
              inspector = inspRes?.data || null
            } catch {}
          }
          const activeNid = selectedNodeId || inspector?.selected_node_detail?.node_id || ''
          const nodeConversations = await extractNodeConversations(connCtx, diskData, activeNid)
          const governanceSessions = extractGovernanceSessions(diskData)
          const snap = inspector?.snapshot || null
          return Response.json(
            {
              ok: true,
              source: diskData || snap?.initialized ? 'disk_telemetry' : 'empty',
              workspaceRoot: targetWs,
              knownWorkspaces,
              inspector,
              nodeConversations,
              governanceSessions,
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

          if (!controlService || typeof controlService.execute !== 'function') {
            return Response.json(
              { ok: false, error: '插件控制服务未就绪，无法处理控制台写操作。' },
              { status: 500 },
            )
          }

          const ctrl = pickController({
            activeControllersByWs,
            reqWorkspaceRoot: reqWs,
            sessionCwd,
            allowFallback: false,
          })
          // 仅 action === 'init' 且显式指定目标工作区时允许自动创建控制器；其余写操作无匹配控制器一律 409 拒绝
          const resolvedInitWs = action === 'init' ? (reqWs || sessionCwd) : ''
          if (!ctrl && !resolvedInitWs) {
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

          const res = await controlService.execute({
            caller: 'human_ui',
            action,
            workspaceRoot: ctrl ? ctrl.workspaceRoot : path.resolve(resolvedInitWs),
            controller: ctrl || null,
            payload: body,
          })
          const errText = String(res?.error || '')
          const statusCode =
            res?.ok === false && (errText.includes('无权') || errText.includes('未知 action'))
              ? 400
              : 200
          return Response.json(res, { status: statusCode })
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
