/**
 * GreatWall v0.3 Superagent (`gw_chief`) 运行时管理器、弹性现况锚点卡与原生 Action Card 适配器。
 *
 * 核心设计（裁决 1）：
 * 1. **弹性字数「全院现况锚点卡」**：字数预算 `min(hardCap, max(400, 180 + 100 * subproblems.length))`（默认硬封顶 1200 字），
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
]))

/**
 * 计算弹性现况锚点卡字数上限：max(400, 180 + 100 * 子题数)，受 hardCapChars（默认 1200）封顶。
 */
export function computeChiefAnchorBudgetChars(subproblemCount = 1, hardCapChars = 1200) {
  const n = Math.max(1, Number(subproblemCount) || 1)
  const cap = Math.max(400, Number(hardCapChars) || 1200)
  return Math.min(cap, Math.max(400, 180 + 100 * n))
}

/**
 * 构造实时「全院现况锚点卡」（纯确定性快照投影，防长会话压缩后记忆断链）。
 */
export function buildChiefAnchorCard(snap, { hardCapChars = 1200, recentEvents = [] } = {}) {
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

  const lines = [
    `[全院现况锚点卡] stage=${snap.stage || 'UNKNOWN'} | mode=${snap.autonomy_mode || 'WAVE_CONFIRM'} | spec=v${Number(snap.latest_spec_revision || 0)} | closure=${snap.closure_state?.status || 'OPEN'}`,
  ]
  for (const s of subs) {
    const baseTxt = s.baseline_entry_id ? `基线=${s.baseline_entry_id}` : '基线=无'
    const solved = s.solved_entry_id ? `解=${s.solved_entry_id}` : '未通关'
    const blk = s.block_reason_code ? ` 阻塞=${s.block_reason_code}` : ''
    lines.push(
      `- ${s.question_id}: ${s.dispatch_state}(v${Number(s.active_spec_revision || 0)}) ${baseTxt} ${solved} W${Number(s.completed_waves || 0)}${blk}`,
    )
  }
  if (pendingProps.length > 0) {
    const pText = pendingProps.slice(0, 6).map((p) => `${p.proposal_id}:${p.action_type}(${p.target_id})`).join(', ')
    lines.push(`待拍板提案(${pendingProps.length}): ${pText}`)
  }
  if (activeWaves.length > 0) {
    const wText = activeWaves.slice(0, 4).map((w) => `${w.conference_id}:${w.question_id}[${w.status}]`).join(', ')
    lines.push(`活跃圆桌: ${wText}`)
  }
  if (Array.isArray(recentEvents) && recentEvents.length > 0) {
    const eText = recentEvents.slice(-4).map((e) => `${e.eventType}(${e.payload?.question_id || e.payload?.proposal_id || e.payload?.node_id || ''})`).join('; ')
    lines.push(`最新高信噪比通报(${recentEvents.length}): ${eText}`)
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

export function buildChiefSessionId(workspaceRoot) {
  return `gw-chief-${computeWorkspaceHash(workspaceRoot)}`
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
export async function ensureChiefSession(
  controller,
  { prompt = '', hardCapChars = 1200, chiefInbox = null, signal = null } = {},
) {
  const ws = controller.workspaceRoot
  const chiefSid = buildChiefSessionId(ws)
  let latestAnchorText = '[全院现况锚点卡] 加载中…'
  const recentDrainedEvents = []

  const refreshAnchorAndDrainInbox = async () => {
    let snapData = null
    try {
      const snapRes = await controller.scheduleSnapshot()
      if (snapRes?.ok && snapRes?.data) snapData = snapRes.data
    } catch {}

    if (chiefInbox && typeof chiefInbox.drainBatch === 'function') {
      const drained = chiefInbox.drainBatch()
      if (Array.isArray(drained) && drained.length > 0) {
        recentDrainedEvents.push(...drained)
        if (recentDrainedEvents.length > 8) {
          recentDrainedEvents.splice(0, recentDrainedEvents.length - 8)
        }
      }
    }

    // 剔除已经过时/已结案的 PENDING_HUMAN_PROPOSAL 通报，避免锚点卡残留已批准提案 ID
    const livePendingPropIds = new Set((snapData?.pending_proposals || []).map((p) => String(p?.proposal_id || '')))
    const filteredEvents = recentDrainedEvents.filter((ev) => {
      if (ev?.eventType === 'PENDING_HUMAN_PROPOSAL' && ev?.payload?.proposal_id) {
        return livePendingPropIds.has(String(ev.payload.proposal_id))
      }
      return true
    })

    if (snapData) {
      latestAnchorText = buildChiefAnchorCard(snapData, {
        hardCapChars,
        recentEvents: filteredEvents,
      })
    }
    return latestAnchorText
  }
  await refreshAnchorAndDrainInbox()

  const inboxDigest = recentDrainedEvents.length > 0
    ? `\n\n### 待审阅的高信噪比系统通报 (${recentDrainedEvents.length} 条)\n${recentDrainedEvents.map((e) => `- [${e.eventType}] ${JSON.stringify(e.payload)}`).join('\n')}`
    : ''

  const effectivePrompt =
    (prompt || '请调用 chief_get_overview_snapshot(question_id="ALL")，用三段简明汇报当前进度：1) 正在做什么；2) 卡在哪里与待拍板项；3) 已证实基线。') +
    inboxDigest

  const res = await controller.orchestrator.resumeOrSpawnAgent({
    role: 'gw_chief',
    sessionId: chiefSid,
    questionId: 'ALL',
    uiLabel: '[科研总控] gw-chief',
    shortTransaction: false,
    keepAliveAfterIdle: true,
    archiveOnComplete: false,
    extraContextProvider: () => latestAnchorText,
    onBeforeStep: () => refreshAnchorAndDrainInbox(),
    signal,
    prompt: effectivePrompt,
  })
  return {
    ...res,
    drainedEventsCount: recentDrainedEvents.length,
    latestAnchorText,
  }
}
