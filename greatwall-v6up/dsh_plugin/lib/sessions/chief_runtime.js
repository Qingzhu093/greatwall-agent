/**
 * GreatWall v0.3 Superagent (`gw_chief`) 运行时管理器、弹性现况锚点卡与原生 Action Card 适配器。
 *
 * 核心设计（裁决 1）：
 * 1. **弹性字数「全院现况锚点卡」**：字数预算 `min(hardCap, max(500, 240 + 120 * subproblems.length))`（默认硬封顶 1500 字），
 *    在 `dsh-compaction-basic` 自动压缩后通过 `systemPrompt.context` 动态重注实现零断链；
 * 2. **两阶段高信噪比事件过滤**：95% 常规探索进展止步于 DB+UI，仅 5 类高信噪比事件入收件箱并自然批处理；
 * 3. **双端确认（DSH 原生 Action Card + 右侧 UI 待拍板卡）**：优先注册 RC5 `@deepseek-ai/dsh-action-cards` (`greatwall_proposal`)，
 *    人类在聊天窗一键点击即走 `controlService.execute({ caller: 'human_ui', action: 'approve_proposal' })`，乐观锁防重。
 * @module dsh-greatwall-v6up/sessions/chief_runtime
 */
import { computeWorkspaceHash } from '../telemetry.js'

export const HIGH_SIGNAL_CHIEF_EVENTS = Object.freeze(new Set([
  'MILESTONE',
  'SUBPROBLEM_SOLVED',
  'PENDING_HUMAN_PROPOSAL',
  'WAVE_CONFERENCE_PENDING_APPROVAL',
  'BLOCK_ALERT',
  'ALL_BRANCHES_BLOCKED',
  'EXPLORER_HANDBACK',
  'HUMAN_WORKTREE_RECONCILED',
  'INTERNAL_SURVEY_ARRIVED',
]))

/**
 * 根据子题数分配现况卡字数（充分利用硬上限，避免 4 题时仅 720 字导致尾部高优告警被截断）。
 */
export function computeChiefAnchorBudgetChars(subproblemCount = 1, hardCapChars = 2400) {
  return Math.min(hardCapChars, Math.max(1200, 600 + 200 * subproblemCount))
}

/**
 * 构造实时「全院现况锚点卡」（纯确定性快照投影，防长会话压缩后记忆断链）。
 */
export function buildChiefAnchorCard(snap, { hardCapChars, recentEvents = [], liveRuntime = null } = {}) {
  if (!snap || !snap.initialized) {
    return '[全院现况锚点卡] 课题尚未初始化 Parse 0 契约。'
  }
  const subs = Array.isArray(snap.subproblem_runtime_state)
    ? snap.subproblem_runtime_state
    : Object.values(snap.subproblem_states || {})
  const maxChars = computeChiefAnchorBudgetChars(subs.length, hardCapChars)
  const pendingProps = Array.isArray(snap.pending_proposals) ? snap.pending_proposals : []
  const activeWaves = Array.isArray(snap.active_wave_conferences)
    ? snap.active_wave_conferences
    : (Array.isArray(snap.active_conferences) ? snap.active_conferences : [])

  const poolTag = liveRuntime?.poolState ? ` | pool=${liveRuntime.poolState}` : ''
  const lines = [
    `[全院现况锚点卡] stage=${snap.stage || 'UNKNOWN'}${poolTag} | mode=${snap.autonomy_mode || 'WAVE_CONFIRM'} | spec=v${Number(snap.latest_spec_revision || 0)} | 外藏=${Number(snap.external_literature_count || 0)}卡 | closure=${snap.closure_state?.status || 'OPEN'}`,
  ]
  const nowMs = Date.now()
  const reconciliation = recentEvents.findLast((event) => {
    if (event.eventType !== 'HUMAN_WORKTREE_RECONCILED') return false
    const ts = Date.parse(event.receivedAt || '')
    return Number.isNaN(ts) || (nowMs - ts) <= 90_000
  })?.payload
  if (reconciliation) {
    const note = reconciliation.note ? ` · ${reconciliation.note.slice(0, 100)}` : ''
    lines.push(`人工交还 ${reconciliation.node_id} · 工件${reconciliation.artifact_dirty ? '有改动' : '未改动'}${note}`)
  }
  const ledger = snap.operator_slot_ledger
  if (ledger) {
    lines.push(`席位 执行=${ledger.working.length} 收尾占用=${ledger.draining.length} 停驻/人工=${ledger.hibernated_or_human.length}`)
  }
  // 高优决策信号前置（待拍板提案 / 活跃圆桌 / 转办 / 最新高信噪比通报），确保绝不被尾部截断
  if (pendingProps.length > 0) {
    const pText = pendingProps.slice(0, 6).map((p) => `${p.proposal_id}:${p.action_type}(${p.target_id})`).join(', ')
    lines.push(`待拍板提案(${pendingProps.length}): ${pText}`)
  }
  if (activeWaves.length > 0) {
    const wText = activeWaves.slice(0, 4).map((w) => `${w.conference_id}:${w.question_id}[${w.status}]`).join(', ')
    lines.push(`活跃圆桌: ${wText}`)
  }
  if (ledger) {
    for (const handback of (snap.handbacks || []).slice(0, 2)) {
      lines.push(`转办 ${handback.handback_id} ${handback.question_id} ${handback.origin_human_mandate ? '有人类授权' : '待人类确认'}`)
    }
  }
  if (Array.isArray(recentEvents) && recentEvents.length > 0) {
    const eText = recentEvents.slice(-4).map((e) => `${e.eventType}(${e.payload?.question_id || e.payload?.proposal_id || e.payload?.node_id || e.payload?.survey_req_id || ''})`).join('; ')
    lines.push(`最新高信噪比通报(${recentEvents.length}): ${eText}`)
  }
  const runningExps = Array.isArray(liveRuntime?.runningExplorers) ? liveRuntime.runningExplorers : []
  const runningGovs = Array.isArray(liveRuntime?.runningGovernanceTasks) ? liveRuntime.runningGovernanceTasks : []
  if (runningExps.length > 0) {
    const expTxt = runningExps
      .slice(0, 8)
      .map((e) => `${e.nodeId}(${e.questionId},已跑${e.elapsedSec}s,sid=${e.sessionId})`)
      .join(', ')
    lines.push(`实时活跃探索者(${runningExps.length}，正在执行中非卡死): ${expTxt}`)
  } else if (liveRuntime) {
    lines.push(`实时活跃探索者(0)${runningGovs.length > 0 ? ` | 治理任务(${runningGovs.length}): ${runningGovs.slice(0, 4).join(',')}` : ''}`)
  }
  for (const s of subs) {
    const baseTxt = s.baseline_entry_id ? `基线=${s.baseline_entry_id}` : '基线=无'
    const solved = s.solved_entry_id ? `解=${s.solved_entry_id}` : '未通关'
    const blk = s.block_reason_code ? ` 阻塞=${s.block_reason_code}` : ''
    lines.push(
      `- ${s.question_id}: ${s.dispatch_state}${s.dispatch_policy ? '/' + s.dispatch_policy : ''}(v${Number(s.active_spec_revision || 0)}) ${baseTxt} ${solved} W${Number(s.completed_waves || 0)}${blk}`,
    )
  }
  if (ledger) {
    for (const arrangement of (snap.active_arrangements || []).slice(-3)) {
      const summary = arrangement.summary_md || Object.entries(arrangement.patch || {}).map(([key, value]) => `${key}=${value}`).join(' ')
      const until = arrangement.expires_at || (arrangement.ends_on_kind === 'AFTER_INFLIGHT_BATCH' ? '在途批次结束' : '手动撤销')
      lines.push(`安排 v${arrangement.arrangement_version} ${arrangement.target_id} 至${until} · ${summary.slice(0, 80)}`)
    }
    for (const op of (snap.operation_receipts || []).slice(0, 2)) {
      lines.push(`回执 ${op.op_id} ${op.status}`)
    }
  }
  if (snap.pinned_notes?.length) {
    lines.push(...snap.pinned_notes.map((note) => `置顶 ${note.question_id}: ${note.content_md}`))
  }
  const full = lines.join('\n')
  return full.length <= maxChars ? full : `${full.slice(0, Math.max(0, maxChars - 1))}…`
}

export class ChiefEventInbox {
  constructor({ maxQueue = 32 } = {}) {
    this.maxQueue = maxQueue
    /** @type {Array<{ receivedAt: string, eventType: string, payload: object }>} */
    this._queue = []
  }

  /** 过滤低信噪比常规事件，仅放行 5 类高信噪比事件入收件箱。 */
  ingest(eventObj) {
    const p = eventObj?.payload || eventObj || {}
    const evType = String(p.event_type || p.event_category || p.reason || '').trim().toUpperCase()
    const matched = [...HIGH_SIGNAL_CHIEF_EVENTS].some((k) => evType.includes(k))
    if (!matched) return { accepted: false, reason: 'low_signal_filtered' }
    this._queue.push({
      receivedAt: new Date().toISOString(),
      eventType: evType,
      payload: p,
    })
    if (this._queue.length > this.maxQueue) {
      this._queue.splice(0, this._queue.length - this.maxQueue)
    }
    return { accepted: true, queueSize: this._queue.length }
  }

  drainBatch() {
    return this._queue.splice(0, this._queue.length)
  }

  peekCount() {
    return this._queue.length
  }
}

export function buildChiefSessionId(workspaceRoot, epochId = 1) {
  return `gw-chief-${computeWorkspaceHash(workspaceRoot)}${epochId > 1 ? `-e${epochId}` : ''}`
}

/**
 * 向 DSH 0.2.2-rc.5 原生 `actionCards` 服务注册 `greatwall_proposal` 交互卡片（裁决 1）。
 * 无宿主 `actionCards` 服务时安全返回空 disposer，自动平滑降级为右侧 UI 待拍板卡。
 */
export function registerProposalActionCard(ctx, controlService, { logger = console } = {}) {
  const safeGet = (holder, name) => {
    try {
      return typeof holder?.get === 'function' ? holder.get(name) : null
    } catch {
      return null
    }
  }
  const safeProp = (holder, name) => {
    try {
      return holder?.[name] || null
    } catch {
      return null
    }
  }
  const getSvc = () =>
    safeGet(ctx, 'actionCards') ||
    safeGet(safeProp(ctx, 'root'), 'actionCards') ||
    safeProp(ctx, 'actionCards') ||
    null

  const svc = getSvc()
  if (!svc || typeof svc.register !== 'function') {
    return { registered: false, dispose: () => {} }
  }

  try {
    const unreg = svc.register({
      kind: 'greatwall_proposal',
      title: '长城科研控制提案确认',
      async handleAction(actionEvent) {
        const proposalId = String(actionEvent?.proposalId || actionEvent?.data?.proposal_id || '').trim()
        const workspaceRoot = String(actionEvent?.workspaceRoot || actionEvent?.data?.workspace_root || '').trim()
        const decision = String(actionEvent?.decision || actionEvent?.action || 'APPROVE').trim().toUpperCase()
        return controlService.execute({
          caller: 'human_ui',
          action: 'approve_proposal',
          workspaceRoot,
          payload: {
            proposal_id: proposalId,
            decision: decision === 'REJECT' ? 'REJECT' : 'APPROVE',
            approved_by_source: 'action_card_human',
          },
        })
      },
    })
    return {
      registered: true,
      dispose: typeof unreg === 'function' ? unreg : () => {},
    }
  } catch (err) {
    logger?.warn?.('[dsh-greatwall-v6up] registerProposalActionCard fallback:', String(err?.message || err))
    return { registered: false, dispose: () => {} }
  }
}

/**
 * 按需拉起或从磁盘 resume 持久 `gw_chief` 会话，并挂载每步动态刷新的弹性现况锚点卡与高信噪比收件箱消费器。
 */
export function chiefAnchorProvider(controller, initial, { hardCapChars, chiefInbox = controller.chiefInbox } = {}) {
  let latestAnchorText
  let recentEvents = []
  const render = (snap) => {
    recentEvents = [...recentEvents, ...(chiefInbox?.drainBatch() || [])].slice(-8)

    // 剔除已经过时/已结案的 PENDING_HUMAN_PROPOSAL 通报，避免锚点卡残留已批准提案 ID
    const livePendingPropIds = new Set((snap?.pending_proposals || []).map((p) => p.proposal_id))
    recentEvents = recentEvents.filter((ev) => {
      if (ev?.eventType === 'PENDING_HUMAN_PROPOSAL' && ev?.payload?.proposal_id) {
        return livePendingPropIds.has(ev.payload.proposal_id)
      }
      return true
    })

    const orch = controller?.orchestrator
    const nowMs = Date.now()
    const liveRuntime = orch
      ? {
          poolState: orch._poolState || 'idle',
          runningExplorers: [...(orch._runningExplorers?.values?.() || [])].map((e) => ({
            nodeId: e.node?.node_id || '',
            questionId: e.node?.question_id || '',
            sessionId: e.sessionId || '',
            elapsedSec: Math.max(0, Math.round((nowMs - Number(e.startedAt || nowMs)) / 1000)),
          })),
          runningGovernanceTasks: [...(orch._runningGov?.keys?.() || [])],
        }
      : null

    latestAnchorText = buildChiefAnchorCard(snap, { hardCapChars, recentEvents, liveRuntime })
  }
  render(initial)
  return {
    get drainedEventsCount() { return recentEvents.length },
    extraContextProvider: () => latestAnchorText,
    onBeforeStep: async () => {
      const snapshot = await controller.scheduleSnapshot()
      if (snapshot.ok) render(snapshot.data)
    },
  }
}

export async function ensureChiefSession(controller, { hardCapChars, chiefInbox, signal = null } = {}) {
  const initial = await controller.scheduleSnapshot()
  if (!initial.ok) throw new Error(initial.error || '无法读取科研总控快照')
  const epochId = Number(initial.data.epoch_id ?? 1)
  if (controller.adoptedChief?.epochId === epochId) {
    return { sessionId: controller.adoptedChief.sessionId, drainedEventsCount: 0 }
  }
  const chiefSid = buildChiefSessionId(controller.workspaceRoot, epochId)
  const anchor = chiefAnchorProvider(controller, initial.data, { hardCapChars, chiefInbox })
  const res = await controller.orchestrator.resumeOrSpawnAgent({
    role: 'gw_chief',
    sessionId: chiefSid,
    questionId: 'ALL',
    uiLabel: '[科研总控] gw-chief',
    shortTransaction: false,
    keepAliveAfterIdle: true,
    archiveOnComplete: false,
    extraContextProvider: anchor.extraContextProvider,
    onBeforeStep: anchor.onBeforeStep,
    signal,
  })
  controller.chiefSessionId = chiefSid
  return { ...res, drainedEventsCount: anchor.drainedEventsCount, latestAnchorText: anchor.extraContextProvider() }
}
