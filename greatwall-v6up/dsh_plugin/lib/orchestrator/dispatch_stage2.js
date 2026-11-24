/**
 * Stage 2 高并发探索与五类治理角色协调派发单元：
 * 0. 待交接/崩溃抢救单源恢复；
 * 1. PRE_SPAWN 同节点伴随写看板并挂起保活；
 * 2. 外藏查新请求响应；
 * 3. 科研仪器科熔断修复 / 痛点工单 / Stage B 离线重评；
 * 4. 后勤总管分诊 / 无豁免聚拢分流 / 孤儿返工续接 / 缺编补齐；
 * 5. 图书馆盲审官空白沙箱两阶段实测；
 * 6. 停滞五车道重排；
 * 7. 监察委周期心跳审计；
 * 8. Stage 2 结题门禁放行与 Stage 3 导出；
 * 9. 探索者并发槽位派发。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage2
 */
import {
  buildReviewItemFingerprints,
  buildSurveyItemFingerprints,
  buildTriageItemFingerprints,
  buildWorksItemFingerprints,
  selectDispatchableExplorers,
} from './circuit_breaker.js'
import {
  runHandoffWithCompanion,
  runPreSpawnBriefingWithCompanion,
} from '../pair_lifecycle.js'

/**
 * 0. SQLite 单真源待交接/崩溃抢救恢复（彻底取消内存双账本）。
 * @param {any} orch
 * @param {any} snap
 * @param {AbortSignal} sig
 * @returns {boolean}
 */
export function dispatchPendingHandoffRecoveries(orch, snap, sig) {
  let dispatchedSomething = false
  for (const pnode of snap.pending_handoff_nodes || []) {
    if (orch._runningExplorers.has(pnode.node_id)) continue
    const recKey = `recover:${pnode.node_id}`
    const recFp = `${pnode.pending_handoff_mode}:${pnode.updated_at || ''}`
    if (orch._itemBreaker.isBroken(recKey, recFp)) continue
    const persistedWill = String(pnode.will_md || pnode.explorer_will_md || '').trim()
    const effMode =
      pnode.pending_handoff_mode === 'HANDOFF_70' && persistedWill
        ? 'HANDOFF_70'
        : 'CRASH_RECOVERY'
    const effReason =
      pnode.pending_handoff_mode === 'HANDOFF_70' && !persistedWill
        ? 'host_restart_before_will_persisted'
        : (pnode.pending_handoff_reason || 'host_restart_recovery')

    if (orch._launchGovTask(`recover_handoff:${pnode.node_id}`, async () => {
      await runHandoffWithCompanion(orch, pnode, {
        mode: effMode,
        explorerWillText: persistedWill,
        interruptReason: effReason,
        signal: sig,
      })
      orch._handoffsSinceHeartbeat += 1
      await orch._evaluateBreakerAfterTask(
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
  return dispatchedSomething
}

/**
 * 执行一轮 Stage 2 治理与探索并发派发。
 * @param {any} orch
 * @param {any} snap
 * @param {AbortSignal} sig
 * @param {number | null} maxConcurrentWorkers
 * @returns {Promise<{ dispatched: boolean, continueImmediate?: boolean }>}
 */
export async function dispatchStage2Step(orch, snap, sig, maxConcurrentWorkers = null) {
  let dispatchedSomething = false
  const closureSt = snap?.closure_state?.status || 'OPEN'

  // 1) PRE_SPAWN 同节点伴随写看板并挂起保活（受 slot_cap 约束 + 单节点防自旋熔断）
  const effSlotCap = Math.max(1, Number(maxConcurrentWorkers || snap.slot_cap || 6))
  const runningBriefings = [...orch._runningGov.keys()].filter((k) => k.startsWith('brief:')).length
  const readyWaitingCount = (snap.explorers_ready_to_run || []).filter((n) => !orch._runningExplorers.has(n.node_id)).length
  let availBriefSlots = Math.max(0, effSlotCap - orch._runningExplorers.size - runningBriefings - readyWaitingCount)
  for (const node of snap.explorers_needing_briefing || []) {
    if (availBriefSlots <= 0) break
    const bKey = `brief:${node.node_id}`
    const bFp = `brief:${node.node_id}:${node.updated_at || ''}`
    if (orch._itemBreaker.isBroken(bKey, bFp)) continue
    if (orch._launchGovTask(bKey, async () => {
      await runPreSpawnBriefingWithCompanion(orch, node, { signal: sig })
      await orch._evaluateBreakerAfterTask('lineage_companion', [{ key: bKey, beforeFp: bFp }], (nextSnap) =>
        new Map((nextSnap?.explorers_needing_briefing || []).map((n) => [`brief:${n.node_id}`, `brief:${n.node_id}:${n.updated_at || ''}`])),
      )
    })) {
      dispatchedSomething = true
      availBriefSlots -= 1
    }
  }

  // 2) 外藏查新需求响应（单条查新请求级熔断，不连坐健康查新单）
  const surveyFpMap = buildSurveyItemFingerprints(snap)
  const activeSurveyItems = []
  for (const [k, fp] of surveyFpMap.entries()) {
    if (!orch._itemBreaker.isBroken(k, fp)) {
      activeSurveyItems.push({ key: k, beforeFp: fp, reqId: k.slice('survey:'.length) })
    }
  }
  if (activeSurveyItems.length > 0) {
    const reqIds = activeSurveyItems.map((it) => it.reqId)
    if (orch._launchGovTask('survey:pending', async () => {
      await orch.spawnAndRunAgent({
        role: 'library_surveyor',
        uiLabel: `[图书馆采编] 响应查新 (${reqIds.length}单)`,
        shortTransaction: false,
        signal: sig,
        prompt: `待采编外部文献请求 ${JSON.stringify(reqIds)} 已就绪，请先调 get_survey_requests(question_id="ALL") 查看问题与检索词：若找到真实来源，调 publish_external_literature_card(outcome="CARD_PUBLISHED", ..., fulfilled_request_ids=...) 写入外藏卡片 [R###]；若确认资料客观不存在或违背合规边界，严禁造伪卡，请调 publish_external_literature_card(outcome="UNAVAILABLE_REPORT", question_id=..., fulfilled_request_ids=..., unavailable_reason_md=...) 诚实结案为 CLOSED_UNAVAILABLE。`,
      })
      await orch._evaluateBreakerAfterTask('library_surveyor', activeSurveyItems, buildSurveyItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 3) 科研仪器科：熔断修复 / 痛点工单 / Stage B 离线重评（按单条待办项独立熔断，不连坐健康工单）
  const worksFpMap = buildWorksItemFingerprints(snap)
  const activeWorksItems = []
  for (const [k, fp] of worksFpMap.entries()) {
    if (!orch._itemBreaker.isBroken(k, fp)) {
      activeWorksItems.push({ key: k, beforeFp: fp })
    }
  }
  if (activeWorksItems.length > 0) {
    const unhealthyInsts = (snap.unhealthy_instruments || []).filter(
      (i) => !orch._itemBreaker.isBroken(`works:inst:${i.instrument_id}`, worksFpMap.get(`works:inst:${i.instrument_id}`) || ''),
    )
    const activeTickets = (snap.open_works_tickets || []).filter(
      (t) => !orch._itemBreaker.isBroken(`works:ticket:${t.ticket_id}`, worksFpMap.get(`works:ticket:${t.ticket_id}`) || ''),
    )
    if (orch._launchGovTask('works:queue', async () => {
      await orch.spawnAndRunAgent({
        role: 'works_engineer',
        uiLabel: unhealthyInsts.length > 0
          ? `[科研仪器科] 仪器熔断修复 (${unhealthyInsts.map((i) => i.instrument_id).join(',')})`
          : `[科研仪器科] 工单与重评 (${activeWorksItems.length}项)`,
        shortTransaction: false,
        signal: sig,
        taskContextText: [
          unhealthyInsts.length > 0 ? `### 连续报错熔断仪器清单\n${JSON.stringify(unhealthyInsts, null, 2)}` : '',
          activeTickets.length > 0 ? `### 本次需处置工单 ID 列表\n${JSON.stringify(activeTickets.map((t) => t.ticket_id))}` : '',
        ].filter(Boolean).join('\n\n'),
        prompt: '请调用 get_works_engineering_queue(question_id="ALL") 检查熔断仪器、痛点工单与 pending_revalidation 队列：对故障或需升版仪器调用 upgrade_instrument_with_calibration（或 register_question_instrument）；对待重评旧观测调 recompute_stage_b_only；对每条已处理或无需改动的工单必须显式调用 resolve_works_ticket(ticket_id, resolution="RESOLVED"|"WONTFIX"|"DUPLICATE", resolution_note) 结案！',
      })
      await orch._evaluateBreakerAfterTask('works_engineer', activeWorksItems, buildWorksItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 4) 后勤总管：分诊 AWAITING_TRIAGE + 无豁免聚拢分流 + 已解锁无分支子题派单 + 孤儿盲审返工单续接 + 缺编正交学派补齐
  const triageFpMap = buildTriageItemFingerprints(snap)
  const activeTriageItems = []
  for (const [k, fp] of triageFpMap.entries()) {
    if (!orch._itemBreaker.isBroken(k, fp)) {
      activeTriageItems.push({ key: k, beforeFp: fp })
    }
  }
  const concAlerts = (snap.family_concentration_alerts || []).filter(
    (a) => !orch._itemBreaker.isBroken(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`),
  )
  const needQs = (snap.questions_needing_branch || []).filter(
    (q) => !orch._itemBreaker.isBroken(`need_branch:${q}`, `need:${q}`),
  )
  const orphanedRevs = (snap.orphaned_blind_review_revisions || []).filter(
    (r) => !orch._itemBreaker.isBroken(`orphan_rev:${r.review_id}`, `orphan:${r.review_id}:${r.source_node_id}`),
  )
  const understaffedQs = (snap.understaffed_questions || []).filter(
    (u) => !orch._itemBreaker.isBroken(
      `understaffed:${u.question_id}`,
      `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}`,
    ),
  )
  const supAlert = snap.active_supervisory_alert || null
  const logisticsItems = [
    ...activeTriageItems,
    ...concAlerts.map((a) => ({
      key: `conc:${a.question_id}:${a.family_id}`,
      beforeFp: `cnt=${a.branch_count_in_family}/${a.total_active_branches}`,
    })),
    ...needQs.map((q) => ({ key: `need_branch:${q}`, beforeFp: `need:${q}` })),
    ...orphanedRevs.map((r) => ({
      key: `orphan_rev:${r.review_id}`,
      beforeFp: `orphan:${r.review_id}:${r.source_node_id}`,
    })),
    ...understaffedQs.map((u) => ({
      key: `understaffed:${u.question_id}`,
      beforeFp: `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}`,
    })),
  ]
  if (logisticsItems.length > 0) {
    const triageCount = activeTriageItems.length
    const uiActionLabel = triageCount > 0
      ? `分诊(${triageCount})`
      : (orphanedRevs.length > 0
          ? `续接盲审返工(${orphanedRevs.map((r) => r.review_id).join(',')})`
          : (concAlerts.length > 0
              ? '正交分流'
              : (understaffedQs.length > 0
                  ? `补齐正交分支(${understaffedQs.map((u) => u.question_id).join(',')})`
                  : `派单(${needQs.join(',')})`)))
    if (orch._launchGovTask('logistics:triage', async () => {
      await orch.spawnAndRunAgent({
        role: 'logistics_coordinator',
        uiLabel: `[后勤总管] ${uiActionLabel}`,
        shortTransaction: false,
        signal: sig,
        taskContextText: [
          supAlert ? `### [监察委员会合规告警与纠偏指令] (${supAlert.alert_id})\n${supAlert.notes || ''}` : '',
          concAlerts.length > 0 ? `### 学派聚拢红线告警 (>=2 且 >50%，无高产豁免)\n${JSON.stringify(concAlerts, null, 2)}` : '',
          orphanedRevs.length > 0 ? `### 孤儿盲审返工单（原分支已被中止/断代，必须用 fork_branch 继承快照与返工单！）\n${JSON.stringify(orphanedRevs, null, 2)}` : '',
          understaffedQs.length > 0 ? `### 正交学派断代缺编告警（单线独苗退化，请补齐多 Worktree 并行探索）\n${JSON.stringify(understaffedQs, null, 2)}` : '',
          snap.latest_spec_revision > 0 ? `### 最新公开裁决版本 v${snap.latest_spec_revision}\n${snap.latest_ruling_summary_md || ''}` : '',
        ].filter(Boolean).join('\n\n'),
        prompt: [
          '请调用 get_logistics_dashboard(question_id="ALL") 查看全卷待分诊节点、方法学派分布、断代分支（stalled_or_aborted_branches）、孤儿盲审返工单（orphaned_blind_review_revisions）、最新公开裁决版本与并发槽位利用率（slot_utilization）：',
          triageCount > 0 ? `- 现有 ${triageCount} 个节点处于 AWAITING_TRIAGE（其分支已被硬锁禁止抢跑），请逐一调用 triage_node 做出裁决（注意：LEVEL_2 原地修补不得跨学派吞并消灭原正交学派；发现特异新侧面可判 LEVEL_3 / SPAWN_PROTECTED 派生受保护新 Worktree）；` : '',
          orphanedRevs.length > 0 ? `- 存在 ${orphanedRevs.length} 条孤儿盲审返工单（${orphanedRevs.map((r) => `${r.review_id} -> parent_node_id="${r.source_node_id}", target_family_id="${r.family_id}"`).join('; ')}）：请立即调用 fork_branch(question_id=..., parent_node_id=..., fork_mode="lateral", target_family_id=...) 继承其快照与返工单继续冲刺二次盲审！` : '',
          understaffedQs.length > 0 ? `- 子题 ${understaffedQs.map((u) => `${u.question_id}(缺编学派: ${(u.missing_active_family_ids || []).join(',')})`).join('; ')} 发生单线独苗退化且有空闲并发槽位：请调用 fork_branch(fork_mode="orthogonal" | "lateral") 补齐缺编正交学派的探索 Worktree！` : '',
          concAlerts.length > 0 ? `- 触发学派聚拢红线告警（>=2 分支且占比 >50%，严禁高产豁免），请立即登记新正交学派并通过 fork_branch(fork_mode="orthogonal") 分流！` : '',
          needQs.length > 0 ? `- 子题 ${needQs.join(', ')} 尚无活跃探索分支，请按需开枝。` : '',
        ].filter(Boolean).join('\n'),
      })
      orch._handoffsSinceHeartbeat += Math.max(1, triageCount)
      await orch._evaluateBreakerAfterTask('logistics_coordinator', logisticsItems, (nextSnap) => {
        const m = buildTriageItemFingerprints(nextSnap)
        for (const a of nextSnap?.family_concentration_alerts || []) {
          m.set(`conc:${a.question_id}:${a.family_id}`, `cnt=${a.branch_count_in_family}/${a.total_active_branches}`)
        }
        for (const q of nextSnap?.questions_needing_branch || []) {
          m.set(`need_branch:${q}`, `need:${q}`)
        }
        for (const r of nextSnap?.orphaned_blind_review_revisions || []) {
          m.set(`orphan_rev:${r.review_id}`, `orphan:${r.review_id}:${r.source_node_id}`)
        }
        for (const u of nextSnap?.understaffed_questions || []) {
          m.set(`understaffed:${u.question_id}`, `active=${u.active_branch_count}:missing=${(u.missing_active_family_ids || []).join(',')}`)
        }
        return m
      })
    })) {
      dispatchedSomething = true
    }
  }

  // 5) 图书馆盲审官：独立空白沙箱两阶段盲审（单审稿单独立熔断）
  const reviewFpMap = buildReviewItemFingerprints(snap)
  for (const rev of snap.pending_reviews || []) {
    const rKey = `review:${rev.review_id}`
    const rFp = reviewFpMap.get(rKey) || `rev:${rev.review_id}:${rev.review_status}`
    if (orch._itemBreaker.isBroken(rKey, rFp)) continue
    if (orch._launchGovTask(rKey, async () => {
      await orch._runBlindReviewWithSandbox(rev, sig)
      await orch._evaluateBreakerAfterTask('library_verifier', [{ key: rKey, beforeFp: rFp }], buildReviewItemFingerprints)
    })) {
      dispatchedSomething = true
    }
  }

  // 6) 停滞五车道重排
  if (snap.stagnation_triggered) {
    const stagKey = 'logistics:stagnation'
    const stagFp = 'stagnation:1'
    if (!orch._itemBreaker.isBroken(stagKey, stagFp)) {
      if (orch._launchGovTask(stagKey, async () => {
        await orch.spawnAndRunAgent({
          role: 'logistics_coordinator',
          uiLabel: '[后勤总管] 停滞五车道重排',
          shortTransaction: false,
          signal: sig,
          prompt: '连续无 L1 产出停滞看门狗已触发！请立即调用 get_logistics_dashboard 与 dispatch_stagnation_five_lanes 执行五车道正交重排。',
        })
        await orch._evaluateBreakerAfterTask('logistics_coordinator', [{ key: stagKey, beforeFp: stagFp }], (nextSnap) => {
          const m = new Map()
          if (nextSnap?.stagnation_triggered) m.set(stagKey, stagFp)
          return m
        })
      })) {
        dispatchedSomething = true
      }
    }
  }

  // 7) 监察委周期心跳审计（有新交接/分诊/节点中止进展时按频次或 3 分钟节律触发；单线长跑期每 10 分钟保底巡检一次，0 探索者闲置时绝不空转）
  const nowMs = Date.now()
  const hasActiveExploration = orch._runningExplorers.size > 0
  if (
    snap.stage === 'STAGE2_EVOLVE' &&
    (orch._handoffsSinceHeartbeat >= 3 ||
      (orch._handoffsSinceHeartbeat > 0 && orch._lastHeartbeatAt > 0 && nowMs - orch._lastHeartbeatAt > 180_000) ||
      (hasActiveExploration && orch._lastHeartbeatAt > 0 && nowMs - orch._lastHeartbeatAt > 600_000))
  ) {
    if (orch._launchGovTask('supervisory:heartbeat', async () => {
      orch._handoffsSinceHeartbeat = 0
      orch._lastHeartbeatAt = Date.now()
      await orch.spawnAndRunAgent({
        role: 'supervisory_committee',
        uiLabel: '[监察委员会] Stage2 心跳审计',
        shortTransaction: false,
        signal: sig,
        prompt: '执行 STAGE2_HEARTBEAT 周期审计：请调 get_supervisory_audit_snapshot 核对流程合规、watchdog_anomalies（孤儿盲审返工单、单线独苗退化/正交学派缺编、Probe 失败率、仪器熔断）、聚拢告警與最新公开裁决版本；若 watchdog_anomalies 非空请调 record_compliance_check(stage="STAGE2_HEARTBEAT", status="ALERT", blocking_questions=..., notes=...) 触发闭环纠偏，否则调 status="PASSED" 或 "ALERT_AMBIGUOUS_SPEC" 落库。',
      })
    })) {
      dispatchedSomething = true
    }
  }
  if (orch._lastHeartbeatAt === 0) orch._lastHeartbeatAt = nowMs

  // 8) 检查 Stage 2 结题放行
  if (
    snap.closure_gate?.closure_allowed &&
    snap.stage === 'STAGE2_EVOLVE' &&
    closureSt === 'OPEN' &&
    orch._runningExplorers.size === 0 &&
    !orch._runningGov.has('stage3:export')
  ) {
    const deliveryMode = snap.closure_gate?.mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
    const expKey = `stage3:export:${deliveryMode}`
    const expFp = `export:${deliveryMode}:OPEN`
    if (!orch._itemBreaker.isBroken(expKey, expFp)) {
      dispatchedSomething = true
      await orch._launchGovTaskAndAwaitIfSync('stage3:export', async () => {
        await orch.spawnAndRunAgent({
          role: 'library_surveyor',
          uiLabel: `[图书馆采编] Stage3 五件套导出 (${deliveryMode})`,
          shortTransaction: false,
          signal: sig,
          prompt: `Stage 2 结题门禁已放行 (delivery_mode="${deliveryMode}")！请调用 get_survey_requests(question_id="ALL") 获取全卷已审 L3_VERIFIED 列表与溯源信息，严禁混入未过盲审草稿，撰写正式综合论文并调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出 final_delivery 五件套，进入两步联合终核。`,
        })
        await orch._evaluateBreakerAfterTask('library_surveyor', [{ key: expKey, beforeFp: expFp }], (nextSnap) => {
          const m = new Map()
          if ((nextSnap?.closure_state?.status || 'OPEN') === 'OPEN' && nextSnap?.stage === 'STAGE2_EVOLVE') {
            m.set(expKey, expFp)
          }
          return m
        })
      })
      return { dispatched: true, continueImmediate: true }
    }
  }

  // 9) 探索者并发派发（严守 triage_locked_branches 防抢跑、human_stop_active 与 closure_gate 收口停新派）
  const runningIds = new Set(orch._runningExplorers.keys())
  const readyNodes = selectDispatchableExplorers(snap, runningIds, maxConcurrentWorkers)
  for (const node of readyNodes) {
    dispatchedSomething = true
    orch._launchExplorerWorker(node, snap, sig)
  }

  return { dispatched: dispatchedSomething }
}
