/**
 * 长城 V6-Up (v3.0) 单条待办项级熔断器、探索者合法性过滤与客观指纹构造器。
 *
 * 纯逻辑模块（零 DSH 运行时依赖），可独立毫秒级单测。
 * @module dsh-greatwall-v6up/orchestrator/circuit_breaker
 */

/**
 * 单条待办项级无客观进展熔断器（对齐 09 §2.2 第 6 条）：
 * - 同一条待办项连续 `maxStalledRuns`（默认 2）次被调度后客观指纹毫无变化，才仅挂起该单项；
 * - 若该项取得任何可核验客观进展（指纹变化）或离队，计数立刻归零；
 * - 同队列其他健康待办项完全不受影响；外部状态改变或人工 `resume` 时自动复位。
 */
export class GovernanceItemCircuitBreaker {
  constructor(maxStalledRuns = 2) {
    this.maxStalledRuns = Math.max(1, Number(maxStalledRuns) || 2)
    /** @type {Map<string, { stalledCount: number, lastFingerprint: string, broken: boolean, brokenAt: string | null }>} */
    this._items = new Map()
  }

  /**
   * 依据最新快照指纹判断某项是否已被熔断；若外部状态变化（指纹不同）则自动复位解除熔断！
   * @param {string} itemKey
   * @param {string} currentFingerprint
   */
  isBroken(itemKey, currentFingerprint) {
    const rec = this._items.get(itemKey)
    if (!rec) return false
    if (rec.lastFingerprint && currentFingerprint && rec.lastFingerprint !== currentFingerprint) {
      this._items.delete(itemKey)
      return false
    }
    return rec.broken
  }

  /**
   * 在某批待办项执行完毕并拉取新快照后，按单条项逐一评估是否取得客观进展。
   * @param {Array<{ key: string, beforeFp: string }>} dispatchedItems
   * @param {Map<string, string>} afterFpMap 仍在队列中的待办项最新指纹表（不在表中表示已出队完成）
   * @returns {Array<{ key: string, stalledCount: number, newlyBroken: boolean }>}
   */
  evaluateBatch(dispatchedItems, afterFpMap) {
    const results = []
    for (const { key, beforeFp } of dispatchedItems || []) {
      if (!afterFpMap.has(key)) {
        this._items.delete(key)
        continue
      }
      const afterFp = String(afterFpMap.get(key) || '')
      if (afterFp !== String(beforeFp || '')) {
        // 虽未出队但已产生可核验客观进展，计数清零绝不误熔断
        this._items.set(key, {
          stalledCount: 0,
          lastFingerprint: afterFp,
          broken: false,
          brokenAt: null,
        })
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
      if (rec.broken) {
        out.push({ key, stalledCount: rec.stalledCount, brokenAt: rec.brokenAt })
      }
    }
    return out
  }
}

/**
 * 纯函数过滤本轮合法可派发的探索者节点（严格实施 `triage_locked_branches` 防抢跑与 `human_stop_active` 拦截，
 * 且遵循无人值守红灯策略：`ambiguous_spec_alerts` 绝不阻塞继续派单）。
 * @param {any} snap
 * @param {Set<string>} runningExplorerIds
 * @param {number} [slotCapOverride]
 */
export function selectDispatchableExplorers(snap, runningExplorerIds = new Set(), slotCapOverride = null) {
  if (!snap || snap.human_stop_active || snap.closure_gate?.closure_allowed) return []
  const slotCap = Math.max(1, Number(slotCapOverride || snap.slot_cap || 6))
  const lockedBranches = new Set(snap.triage_locked_branches || [])
  const candidates = []
  let occupied = runningExplorerIds.size
  for (const node of snap.explorers_ready_to_run || []) {
    if (occupied >= slotCap) break
    if (!node || !node.node_id) continue
    if (runningExplorerIds.has(node.node_id)) continue
    if (node.branch_id && lockedBranches.has(node.branch_id)) continue
    candidates.push(node)
    occupied += 1
  }
  return candidates
}

/** 为快照中各治理队列的每一条独立待办构造可核验客观指纹映射（严格单条隔离，不受同队列他项进出影响）。 */
export function buildWorksItemFingerprints(snap) {
  const map = new Map()
  const instFpById = new Map()
  for (const s of snap?.active_instruments_fingerprint || []) {
    const id = String(s || '').split(':', 1)[0]
    if (id) instFpById.set(id, String(s))
  }
  for (const inst of snap?.unhealthy_instruments || []) {
    const k = `works:inst:${inst.instrument_id}`
    map.set(k, `inst:v${inst.version}:err=${inst.consecutive_error_count}:${inst.updated_at || ''}`)
  }
  for (const t of snap?.open_works_tickets || []) {
    const k = `works:ticket:${t.ticket_id}`
    // 仅绑定本工单自身状态及其直接关联的单个 instrument_id，严禁受其他无关仪器变动干扰
    const boundInstFp = t.instrument_id ? (instFpById.get(String(t.instrument_id)) || '') : ''
    map.set(k, `tkt:${t.updated_at || ''}:${t.payload_json || ''}|inst=${boundInstFp}`)
  }
  for (const rv of snap?.pending_revalidation || []) {
    const k = `works:reval:${rv.queue_id}`
    map.set(k, `reval:${rv.obs_id}:v${rv.target_version}:${rv.updated_at || ''}`)
  }
  return map
}

export function buildSurveyItemFingerprints(snap) {
  const map = new Map()
  for (const r of snap?.pending_surveys || []) {
    const id = r.req_id || r.request_id
    if (!id) continue
    // 仅绑定单条查新单自身状态，严禁被同批其他查新单入卡计数重置计数
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
