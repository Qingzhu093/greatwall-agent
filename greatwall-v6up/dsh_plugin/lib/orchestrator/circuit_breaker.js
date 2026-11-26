/**
 * GreatWall v0.3 单条待办项级熔断器、探索者合法性过滤（+1 人类优先槽）与客观指纹构造器。
 * @module dsh-greatwall-v6up/orchestrator/circuit_breaker
 */
import { isHumanPriorityNode } from '../runtime/worker_slots.js'

export class GovernanceItemCircuitBreaker {
  constructor(maxStalledRuns = 2) {
    this.maxStalledRuns = Math.max(1, Number(maxStalledRuns) || 2)
    this._items = new Map()
  }

  isBroken(itemKey, currentFingerprint) {
    const rec = this._items.get(itemKey)
    if (!rec) return false
    if (rec.lastFingerprint && currentFingerprint && rec.lastFingerprint !== currentFingerprint) {
      this._items.delete(itemKey)
      return false
    }
    return rec.broken
  }

  evaluateBatch(dispatchedItems, afterFpMap) {
    const results = []
    for (const { key, beforeFp } of dispatchedItems || []) {
      if (!afterFpMap.has(key)) {
        this._items.delete(key)
        continue
      }
      const afterFp = String(afterFpMap.get(key) || '')
      if (afterFp !== String(beforeFp || '')) {
        this._items.set(key, { stalledCount: 0, lastFingerprint: afterFp, broken: false, brokenAt: null })
        results.push({ key, stalledCount: 0, newlyBroken: false })
        continue
      }
      const prev = this._items.get(key)
      const nextCount = (prev?.stalledCount || 0) + 1
      const wasBroken = Boolean(prev?.broken)
      const nowBroken = nextCount >= this.maxStalledRuns
      this._items.set(key, {
        stalledCount: nextCount,
        lastFingerprint: afterFp,
        broken: nowBroken,
        brokenAt: nowBroken ? (prev?.brokenAt || new Date().toISOString()) : null,
      })
      results.push({ key, stalledCount: nextCount, newlyBroken: nowBroken && !wasBroken })
    }
    return results
  }

  resetAll() {
    this._items.clear()
  }

  getBrokenItems() {
    const out = []
    for (const [key, rec] of this._items.entries()) {
      if (rec.broken) out.push({ key, stalledCount: rec.stalledCount, brokenAt: rec.brokenAt })
    }
    return out
  }
}

/**
 * 纯函数过滤本轮合法可派发的探索者节点：
 * - 遵守 `triage_locked_branches`、`human_stop_active` 与子题停工锁（`subproblem_dispatch_states`）；
 * - 跳过 `control_state` 处于 `PAUSE_DRAINING / HUMAN_ACTIVE` 的人工接管节点；
 * - 人类优先节点（`HUMAN_SEEDED` / `human_modified`）排序置前并可额外使用 `+1` 人类保留槽位。
 */
export function selectDispatchableExplorers(
  snap,
  runningExplorerIds = new Set(),
  slotCapOverride = null,
  { humanReserveSlots = 1, slotAllocator = null } = {},
) {
  if (!snap || snap.human_stop_active || snap.closure_gate?.closure_allowed) return []
  const slotCap = Math.max(1, Number(slotCapOverride || snap.slot_cap || 6))
  const lockedBranches = new Set(snap.triage_locked_branches || [])
  const rawSubs = Array.isArray(snap.subproblem_runtime_state)
    ? snap.subproblem_runtime_state
    : Object.values(snap.subproblem_states || {})
  const subStates = new Map(rawSubs.filter((s) => s?.question_id).map((s) => [s.question_id, s.dispatch_state]))

  const rawReady = (snap.explorers_ready_to_run || []).filter((node) => {
    if (!node || !node.node_id) return false
    if (runningExplorerIds.has(node.node_id)) return false
    if (node.branch_id && lockedBranches.has(node.branch_id)) return false
    const cs = String(node.control_state || 'AUTO_RUNNING')
    if (cs === 'PAUSE_DRAINING' || cs === 'HUMAN_ACTIVE') return false
    const qState = subStates.get(node.question_id)
    if (qState && qState !== 'DISPATCHING') return false
    return true
  })

  // 人类刚动过手或种下的种子枝优先排前
  rawReady.sort((a, b) => Number(isHumanPriorityNode(b)) - Number(isHumanPriorityNode(a)))

  const candidates = []
  let normalOccupied = runningExplorerIds.size
  let humanReserveUsed = 0

  for (const node of rawReady) {
    if (slotAllocator) {
      if (!slotAllocator.canAcquire(node)) continue
      candidates.push(node)
      continue
    }
    if (normalOccupied < slotCap) {
      candidates.push(node)
      normalOccupied += 1
    } else if (isHumanPriorityNode(node) && humanReserveUsed < humanReserveSlots) {
      candidates.push(node)
      humanReserveUsed += 1
    }
  }
  return candidates
}

export function buildWorksItemFingerprints(snap) {
  const map = new Map()
  const instFpById = new Map()
  for (const s of snap?.active_instruments_fingerprint || []) {
    const id = String(s || '').split(':', 1)[0]
    if (id) instFpById.set(id, String(s))
  }
  for (const inst of snap?.unhealthy_instruments || []) {
    map.set(`works:inst:${inst.instrument_id}`, `inst:v${inst.version}:err=${inst.consecutive_error_count}:${inst.updated_at || ''}`)
  }
  for (const t of snap?.open_works_tickets || []) {
    const boundInstFp = t.instrument_id ? (instFpById.get(String(t.instrument_id)) || '') : ''
    map.set(`works:ticket:${t.ticket_id}`, `tkt:${t.updated_at || ''}:${t.payload_json || ''}|inst=${boundInstFp}`)
  }
  for (const rv of snap?.pending_revalidation || []) {
    map.set(`works:reval:${rv.queue_id}`, `reval:${rv.obs_id}:v${rv.target_version}:${rv.updated_at || ''}`)
  }
  return map
}

export function buildSurveyItemFingerprints(snap) {
  const map = new Map()
  for (const r of snap?.pending_surveys || []) {
    const id = r.req_id || r.request_id
    if (!id) continue
    map.set(`survey:${id}`, `req:${id}:${r.status || 'PENDING'}`)
  }
  return map
}

export function buildTriageItemFingerprints(snap) {
  const map = new Map()
  for (const n of snap?.awaiting_triage || []) {
    if (!n?.node_id) continue
    map.set(`triage:${n.node_id}`, `triage:${n.node_id}:${n.family_id || ''}:${n.evidence_grade || ''}`)
  }
  return map
}

export function buildReviewItemFingerprints(snap) {
  const map = new Map()
  for (const r of snap?.pending_reviews || []) {
    if (!r?.review_id) continue
    map.set(`review:${r.review_id}`, `rev:${r.review_id}:${r.review_status || ''}`)
  }
  return map
}

export function buildWaveConferenceFingerprints(snap) {
  const map = new Map()
  const confs = Array.isArray(snap?.active_wave_conferences)
    ? snap.active_wave_conferences
    : (Array.isArray(snap?.active_conferences) ? snap.active_conferences : [])
  for (const c of confs) {
    if (!c?.conference_id) continue
    map.set(`wave:${c.conference_id}`, `wave:${c.conference_id}:${c.status || ''}:${c.linked_survey_id || ''}`)
  }
  return map
}
