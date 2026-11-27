/**
 * GreatWall v0.3 Stage 2 并发探索与科研工程调度派发单元：
 * - 彻底移除原五车道停滞重排与 supervisory_committee 周期性心跳审计（裁决 3 / 裁决 6）；
 * - 接入宏观大外环四拍脉冲 `WaveConferenceRunner`（裁决 5）；
 * - 外藏查新派发给 `external_surveyor`，Stage 3 导出派发给零外网 `library_chronicler`；
 * - 探索者派发支持 `maxWorkers` 普通槽 + `+1` 人类优先保留槽。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage2
 */
import {
  buildReviewItemFingerprints,
  buildSurveyItemFingerprints,
  buildTriageItemFingerprints,
  buildWaveConferenceFingerprints,
  buildWorksItemFingerprints,
  selectDispatchableExplorers,
} from './circuit_breaker.js'
import {
  runHandoffWithCompanion,
  runPreSpawnBriefingWithCompanion,
} from '../pair_lifecycle.js'

export function dispatchPendingHandoffRecoveries(port, snap, sig) {
  let dispatchedSomething = false
  for (const pnode of snap.pending_handoff_nodes || []) {
    if (port.isExplorerRunning(pnode.node_id)) continue
    const recKey = `recover:${pnode.node_id}`
    const recFp = `${pnode.pending_handoff_mode}:${pnode.updated_at || ''}`
    if (port.isBreakerOpen(recKey, recFp)) continue
    const persistedWill = String(pnode.will_md || pnode.explorer_will_md || '').trim()
    const effMode = pnode.pending_handoff_mode === 'HANDOFF_70' && persistedWill ? 'HANDOFF_70' : 'CRASH_RECOVERY'
    const effReason = pnode.pending_handoff_mode === 'HANDOFF_70' && !persistedWill
      ? 'host_restart_before_will_persisted'
      : (pnode.pending_handoff_reason || 'host_restart_recovery')

    if (port.launchGovTask(`recover_handoff:${pnode.node_id}`, async () => {
      await runHandoffWithCompanion(port, pnode, {
        mode: effMode,
        explorerWillText: persistedWill,
        interruptReason: effReason,
        signal: sig,
      })
      await port.evaluateBreakerAfterTask(
        'lineage_companion',
        [{ key: recKey, beforeFp: recFp }],
        (nextSnap) => new Map(
          (nextSnap?.pending_handoff_nodes || []).map((n) => [
            `recover:${n.node_id}`,
            `${n.pending_handoff_mode}:${n.updated_at || ''}`,
          ]),
        ),
      )
    })) {
      dispatchedSomething = true
    }
  }

  // 人类显式授权提前交班且已退出探索循环的节点（EARLY_HANDOFF_READY）：直接由伴随助手走 HANDOFF_70 封存收口
  for (const enode of snap.early_handoff_nodes || []) {
    if (!enode?.node_id || port.isExplorerRunning(enode.node_id)) continue
    const ehKey = `early_handoff:${enode.node_id}`
    const ehFp = `early:${enode.node_id}:${enode.control_generation || 1}:${enode.updated_at || ''}`
    if (port.isBreakerOpen(ehKey, ehFp)) continue
    if (port.launchGovTask(ehKey, async () => {
      const persistedWill = String(enode.will_md || enode.explorer_will_md || '').trim()
      await port.control('control_plane/record_pending_handoff', {
        workspace_root: port.workspaceRoot,
        node_id: enode.node_id,
        mode: 'HANDOFF_70',
        explorer_will_md: persistedWill || '（人类已从暂停接管态显式授权提前交班封存，请以工作树工件与最新正式观测收据为准）',
        reason: 'EARLY_HANDOFF_AUTHORIZED',
      }).catch(() => {})
      await runHandoffWithCompanion(port, enode, {
        mode: 'HANDOFF_70',
        explorerWillText: persistedWill || '（人类已从暂停接管态显式授权提前交班封存）',
        interruptReason: 'EARLY_HANDOFF_AUTHORIZED',
        signal: sig,
      })
      await port.evaluateBreakerAfterTask(
        'lineage_companion',
        [{ key: ehKey, beforeFp: ehFp }],
        (nextSnap) => new Map(
          (nextSnap?.early_handoff_nodes || []).map((n) => [
            `early_handoff:${n.node_id}`,
            `early:${n.node_id}:${n.control_generation || 1}:${n.updated_at || ''}`,
          ]),
        ),
      )
    })) {
      dispatchedSomething = true
    }
  }
  return dispatchedSomething
}

export async function dispatchStage2Step(port, snap, sig, maxConcurrentWorkers = null) {
  let dispatchedSomething = false
  const closureSt = snap?.closure_state?.status || 'OPEN'

  // 1) PRE_SPAWN 同节点确定性伴随写看板
  let availBriefSlots = port.getAvailableBriefSlots(snap, maxConcurrentWorkers)
  for (const node of snap.explorers_needing_briefing || []) {
    if (availBriefSlots <= 0) break
    const bKey = `brief:${node.node_id}`
    const bFp = `brief:${node.node_id}:${node.updated_at || ''}`
    if (port.isBreakerOpen(bKey, bFp)) continue
    if (port.launchGovTask(bKey, async () => {
      await runPreSpawnBriefingWithCompanion(port, node, { signal: sig })
      await port.evaluateBreakerAfterTask('lineage_companion', [{ key: bKey, beforeFp: bFp }], (nextSnap) =>
        new Map((nextSnap?.explorers_needing_briefing || []).map((n) => [`brief:${n.node_id}`, `brief:${n.node_id}:${n.updated_at || ''}`])),
      )
    })) {
      dispatchedSomething = true
      availBriefSlots -= 1
    }
  }

  // 2) 对外文献查新请求响应（external_surveyor，物理零院内泄露）
  const surveyFpMap = buildSurveyItemFingerprints(snap)
  const activeSurveyItems = []
  for (const [k, fp] of surveyFpMap.entries()) {
    if (!port.isBreakerOpen(k, fp)) activeSurveyItems.push({ key: k, beforeFp: fp, reqId: k.slice('survey:'.length) })
  }
  if (activeSurveyItems.length > 0) {
    const reqIds = activeSurveyItems.map((it) => it.reqId)
    if (port.launchGovTask('survey:pending', async () => {
      await port.spawnAndRunAgent({
        role: 'external_surveyor',
        uiLabel: `[对外采编] 响应查新 (${reqIds.length}单)`,
        shortTransaction: false,
        signal: sig,
        prompt: `待采编外部查新单 ${JSON.stringify(reqIds)} 已就绪，请先调 get_survey_requests(question_id="ALL")：找到真实来源则调 publish_external_literature_card(outcome="CARD_PUBLISHED", ...) 入库 [R###]；客观无解则调 outcome="UNAVAILABLE_REPORT" 诚实结案，严禁造伪卡。`,
      })
      await port.evaluateBreakerAfterTask('external_surveyor', activeSurveyItems, buildSurveyItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 3) 科研仪器科：熔断修复 / 痛点 / 反作弊 EXPLOIT / 鉴别仪器 DISCRIMINATOR / Stage B 离线重评
  const worksFpMap = buildWorksItemFingerprints(snap)
  const activeWorksItems = []
  for (const [k, fp] of worksFpMap.entries()) {
    if (!port.isBreakerOpen(k, fp)) activeWorksItems.push({ key: k, beforeFp: fp })
  }
  if (activeWorksItems.length > 0) {
    const unhealthyInsts = (snap.unhealthy_instruments || []).filter(
      (i) => !port.isBreakerOpen(`works:inst:${i.instrument_id}`, worksFpMap.get(`works:inst:${i.instrument_id}`) || ''),
    )
    const activeTickets = (snap.open_works_tickets || []).filter(
      (t) => !port.isBreakerOpen(`works:ticket:${t.ticket_id}`, worksFpMap.get(`works:ticket:${t.ticket_id}`) || ''),
    )
    if (port.launchGovTask('works:queue', async () => {
      await port.spawnAndRunAgent({
        role: 'works_engineer',
        uiLabel: unhealthyInsts.length > 0
          ? `[科研仪器科] 熔断抢修 (${unhealthyInsts.map((i) => i.instrument_id).join(',')})`
          : `[科研仪器科] 工单与重评 (${activeWorksItems.length}项)`,
        shortTransaction: false,
        signal: sig,
        taskContextText: [
          unhealthyInsts.length > 0 ? `### 连续报错熔断仪器\n${JSON.stringify(unhealthyInsts, null, 2)}` : '',
          activeTickets.length > 0 ? `### 需处置工单列表\n${JSON.stringify(activeTickets.map((t) => ({ ticket_id: t.ticket_id, type: t.ticket_type })))}` : '',
        ].filter(Boolean).join('\n\n'),
        prompt: '请调 get_works_engineering_queue(question_id="ALL") 处理熔断仪器、EXPLOIT/DISCRIMINATOR/PAIN_POINT 工单与 pending_revalidation 队列；每条处理完毕的工单须显式调用 resolve_works_ticket 结案。',
      })
      await port.evaluateBreakerAfterTask('works_engineer', activeWorksItems, buildWorksItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 4) 按需唤起无状态后勤总管（仅疑难 AWAITING_TRIAGE / 聚拢告警 / 孤儿返工 / 缺编补齐 / 开枝）
  const triageFpMap = buildTriageItemFingerprints(snap)
  const activeTriageItems = []
  for (const [k, fp] of triageFpMap.entries()) {
    if (!port.isBreakerOpen(k, fp)) activeTriageItems.push({ key: k, beforeFp: fp })
  }
  const concAlerts = (snap.family_concentration_alerts || []).filter(
    (a) => !port.isBreakerOpen(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`),
  )
  const needQs = (snap.questions_needing_branch || []).filter((q) => !port.isBreakerOpen(`need_branch:${q}`, `need:${q}`))
  const orphanedRevs = (snap.orphaned_blind_review_revisions || []).filter(
    (r) => !port.isBreakerOpen(`orphan_rev:${r.review_id}`, `orphan:${r.review_id}:${r.source_node_id}`),
  )
  const understaffedQs = (snap.understaffed_questions || []).filter(
    (u) => !port.isBreakerOpen(`understaffed:${u.question_id}`, `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}`),
  )

  const logisticsItems = [
    ...activeTriageItems,
    ...concAlerts.map((a) => ({ key: `conc:${a.question_id}:${a.family_id}`, beforeFp: `cnt=${a.branch_count_in_family}/${a.total_active_branches}` })),
    ...needQs.map((q) => ({ key: `need_branch:${q}`, beforeFp: `need:${q}` })),
    ...orphanedRevs.map((r) => ({ key: `orphan_rev:${r.review_id}`, beforeFp: `orphan:${r.review_id}:${r.source_node_id}` })),
    ...understaffedQs.map((u) => ({ key: `understaffed:${u.question_id}`, beforeFp: `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}` })),
  ]
  if (logisticsItems.length > 0) {
    if (port.launchGovTask('logistics:triage', async () => {
      await port.spawnAndRunAgent({
        role: 'logistics_coordinator',
        uiLabel: `[后勤总管] 治理分诊 (${logisticsItems.length}项)`,
        shortTransaction: false,
        signal: sig,
        taskContextText: [
          concAlerts.length > 0 ? `### 学派聚拢告警 (>50%)\n${JSON.stringify(concAlerts, null, 2)}` : '',
          orphanedRevs.length > 0 ? `### 孤儿盲审返工单\n${JSON.stringify(orphanedRevs, null, 2)}` : '',
          understaffedQs.length > 0 ? `### 缺编正交学派\n${JSON.stringify(understaffedQs, null, 2)}` : '',
        ].filter(Boolean).join('\n\n'),
        prompt: '请调用 get_logistics_dashboard(question_id="ALL")，处理疑难 AWAITING_TRIAGE 节点（triage_node）、孤儿盲审返工单（fork_branch lateral）、>50% 学派聚拢正交分流（fork_branch orthogonal）或空缺子题开枝。',
      })
      await port.evaluateBreakerAfterTask('logistics_coordinator', logisticsItems, (nextSnap) => {
        const m = buildTriageItemFingerprints(nextSnap)
        for (const a of nextSnap?.family_concentration_alerts || []) m.set(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`)
        for (const q of nextSnap?.questions_needing_branch || []) m.set(`need_branch:${q}`, `need:${q}`)
        for (const r of nextSnap?.orphaned_blind_review_revisions || []) m.set(`orphan_rev:${r.review_id}`, `orphan:${r.review_id}:${r.source_node_id}`)
        for (const u of nextSnap?.understaffed_questions || []) m.set(`understaffed:${u.question_id}`, `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}`)
        return m
      })
    })) {
      dispatchedSomething = true
    }
  }

  // 5) 独立空白沙箱两阶段盲审（含 LOCAL_LEMMA_SUBMISSION 一次性盲审）
  const reviewFpMap = buildReviewItemFingerprints(snap)
  for (const rev of snap.pending_reviews || []) {
    const rKey = `review:${rev.review_id}`
    const rFp = reviewFpMap.get(rKey) || `rev:${rev.review_id}:${rev.review_status}`
    if (port.isBreakerOpen(rKey, rFp)) continue
    if (port.launchGovTask(rKey, async () => {
      await port.runBlindReview(rev, sig)
      await port.evaluateBreakerAfterTask('library_verifier', [{ key: rKey, beforeFp: rFp }], buildReviewItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 6) 宏观大外环四拍脉冲推进（ROUND_1 -> ROUND_2 -> SURVEY_REFRESHING -> ADJUDICATING）
  const waveFpMap = buildWaveConferenceFingerprints(snap)
  const activeWaves = Array.isArray(snap.active_wave_conferences)
    ? snap.active_wave_conferences
    : (Array.isArray(snap.active_conferences) ? snap.active_conferences : [])
  for (const conf of activeWaves) {
    if (!conf?.conference_id) continue
    if (!['ROUND_1_CRITIQUE', 'ROUND_2_REBUTTAL', 'SURVEY_REFRESHING', 'ADJUDICATING'].includes(String(conf.status || ''))) {
      continue
    }
    const wKey = `wave:${conf.conference_id}`
    const wFp = waveFpMap.get(wKey) || `wave:${conf.conference_id}:${conf.status}`
    if (port.isBreakerOpen(wKey, wFp)) continue
    if (port.launchGovTask(wKey, async () => {
      await port.advanceWaveConference(conf, sig)
      const evals = await port.evaluateBreakerAfterTask('conference_chair', [{ key: wKey, beforeFp: wFp }], buildWaveConferenceFingerprints)
      if (Array.isArray(evals) && evals.some((ev) => ev?.key === wKey && ev?.newlyBroken)) {
        await port.control('control_plane/fail_wave_conference', {
          workspace_root: port.workspaceRoot,
          conference_id: conf.conference_id,
          reason: `WAVE_STALLED_CIRCUIT_BROKEN:${conf.status}`,
        }).catch(() => {})
      }
    })) {
      dispatchedSomething = true
    }
  }

  // 7) Stage 2 结题门禁放行 -> 零外网 library_chronicler 导出并锁定 Stage 3 冻结五件套
  if (
    snap.closure_gate?.closure_allowed &&
    snap.stage === 'STAGE2_EVOLVE' &&
    closureSt === 'OPEN' &&
    port.getRunningExplorerCount() === 0 &&
    !(snap.operator_slot_ledger?.draining?.length || 0) &&
    !port.isGovTaskRunning('stage3:export')
  ) {
    const deliveryMode = snap.closure_gate?.mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
    const expKey = `stage3:export:${deliveryMode}`
    const expFp = `export:${deliveryMode}:OPEN`
    if (!port.isBreakerOpen(expKey, expFp)) {
      dispatchedSomething = true
      port.launchGovTask('stage3:export', async () => {
        await port.spawnAndRunAgent({
          role: 'library_chronicler',
          uiLabel: `[综述终稿官] Stage3 冻结五件套导出 (${deliveryMode})`,
          shortTransaction: false,
          signal: sig,
          prompt: `Stage 2 结题门禁已放行 (delivery_mode="${deliveryMode}")！请调用 get_chronicler_snapshot(question_id="ALL") 获取全卷已审 L3_VERIFIED 列表与复现节点，严格在各 L3 exact_verified_scope_md 范围内撰写正式总报告，调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出并锁定外部不可变冻结包。`,
        })
        await port.evaluateBreakerAfterTask('library_chronicler', [{ key: expKey, beforeFp: expFp }], (nextSnap) => {
          const m = new Map()
          if ((nextSnap?.closure_state?.status || 'OPEN') === 'OPEN' && nextSnap?.stage === 'STAGE2_EVOLVE') m.set(expKey, expFp)
          return m
        })
      })
      return { dispatched: true, continueImmediate: true }
    }
  }

  // 8) 探索者并发槽位派发（maxWorkers 普通槽 + 1 个固定人类优先保留槽）
  const dispatchable = selectDispatchableExplorers(snap, port.getRunningExplorerIds(), maxConcurrentWorkers, {
    slotAllocator: port.slotAllocator,
  })
  for (const node of dispatchable) {
    port.launchExplorer(node, snap, sig)
    dispatchedSomething = true
  }

  return { dispatched: dispatchedSomething }
}
