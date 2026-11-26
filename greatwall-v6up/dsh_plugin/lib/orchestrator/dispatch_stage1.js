/**
 * GreatWall v0.3 Stage 1（Parse 0 启动对齐）派发单元：
 * 1.1 `works_engineer` 初始仪器锻造/核查确认；
 * 1.2 `external_surveyor` 外藏文献预建卡（物理零院内泄露）；
 * 1.3 `logistics_coordinator` 开局按需建首批正交学派与初始分支；
 * 1.4 `supervisory_committee` 签发 `PARSE0_GATE(PASSED)` 推进至 `STAGE2_EVOLVE`。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage1
 */

export async function dispatchStage1Step(port, snap, sig) {
  if (snap.stage !== 'STAGE1_PARSE0') return { handled: false }

  if (!snap.parse0_signed) {
    port.recordEvent('waiting_parse0_signature', {})
    return { handled: true, waitMs: 500 }
  }

  // 1.1 科研仪器科初始仪器就绪核查
  if (!snap.stage1_works_checked) {
    const missingInsts = snap.missing_initial_instruments || []
    const stage1WorksItems = missingInsts.length > 0
      ? missingInsts.map((m, idx) => ({
          key: `works:stage1:${m.instrument_id || m.id || idx}`,
          beforeFp: `missing:${JSON.stringify(m)}|insts=${JSON.stringify(snap.active_instruments_fingerprint || [])}`,
        }))
      : [{ key: 'works:stage1:empty_check', beforeFp: 'unchecked:empty' }]
    const activeStage1Items = stage1WorksItems.filter((it) => !port.isBreakerOpen(it.key, it.beforeFp))

    if (activeStage1Items.length > 0) {
      await port.launchGovTaskAndAwait('stage1:works_check', async () => {
        await port.spawnAndRunAgent({
          role: 'works_engineer',
          uiLabel: missingInsts.length > 0 ? `[科研仪器科] 初始仪器锻造 (${missingInsts.length}项)` : '[科研仪器科] Stage1 核查',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 待就绪初始仪器清单\n${JSON.stringify(missingInsts, null, 2)}`,
          prompt: missingInsts.length > 0
            ? `Stage 1 初始仪器核查：请调 get_works_engineering_queue(question_id="ALL")，为声明的初始仪器 ${JSON.stringify(missingInsts)} 逐一编写脚本与校准集并调 register_question_instrument 完成激活。`
            : 'Stage 1 初始仪器核查：Parse 0 未声明初始仪器。请调一次 get_works_engineering_queue(question_id="ALL") 确认后返回，控制面将自动标记 stage1_works_checked=1。',
        })
        const checkRes = await port.control('control_plane/mark_stage1_works_checked', { workspace_root: port.workspaceRoot })
        if (!checkRes?.data?.stage1_works_checked) {
          await port.evaluateBreakerAfterTask('works_engineer', activeStage1Items, (nextSnap) => {
            const m = new Map()
            if (!nextSnap?.stage1_works_checked) {
              const rem = nextSnap?.missing_initial_instruments || []
              if (rem.length > 0) {
                rem.forEach((x, i) => m.set(
                  `works:stage1:${x.instrument_id || x.id || i}`,
                  `missing:${JSON.stringify(x)}|insts=${JSON.stringify(nextSnap.active_instruments_fingerprint || [])}`,
                ))
              } else {
                m.set('works:stage1:empty_check', 'unchecked:empty')
              }
            }
            return m
          })
        }
      })
      return { handled: true }
    }
  }

  // 1.2 对外采编员 external_surveyor 预建外藏参考卡 [R001]（仅限外部公开知识）
  if (Number(snap.external_literature_count || 0) === 0) {
    const s1Key = 'stage1:external_surveyor'
    const s1Fp = 'ext_count=0'
    if (!port.isBreakerOpen(s1Key, s1Fp)) {
      await port.launchGovTaskAndAwait('stage1:external_surveyor', async () => {
        await port.spawnAndRunAgent({
          role: 'external_surveyor',
          uiLabel: '[对外采编] 开局外藏文献建卡',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### 公开研究课题背景\n${snap.goal_and_completion_md || ''}`,
          prompt: `Stage 1 开局外藏建设：请围绕子题 ${JSON.stringify(snap.required_questions || [])} 的公开背景与标准定理，联网调研并调 publish_external_literature_card(outcome="CARD_PUBLISHED", ...) 发布至少 1 张带诚实阅读深度标注的外藏参考卡 [R001]。`,
        })
        await port.evaluateBreakerAfterTask('external_surveyor', [{ key: s1Key, beforeFp: s1Fp }], (nextSnap) => {
          const m = new Map()
          if (Number(nextSnap?.external_literature_count || 0) === 0) m.set(s1Key, 'ext_count=0')
          return m
        })
      })
      return { handled: true }
    }
  }

  // 1.3 后勤总管开局登记首批正交学派并开启初始探索分支
  if (snap.questions_needing_branch?.length > 0) {
    const branchItems = snap.questions_needing_branch.map((q) => ({ key: `stage1:branch:${q}`, beforeFp: `need:${q}` }))
    const activeBranchItems = branchItems.filter((it) => !port.isBreakerOpen(it.key, it.beforeFp))
    if (activeBranchItems.length > 0) {
      await port.launchGovTaskAndAwait('stage1:logistics_init', async () => {
        await port.spawnAndRunAgent({
          role: 'logistics_coordinator',
          uiLabel: '[后勤总管] 开局正交学派建枝',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 子题解锁状态\n${JSON.stringify(snap.question_order_status || {}, null, 2)}`,
          prompt: `Stage 1 初始调度：请先调用 get_logistics_dashboard(question_id="ALL")，为已解锁子题 ${JSON.stringify(snap.questions_needing_branch)} 登记贴合机理的正交学派 (register_method_family) 并按需 fork_branch 开启初始分支。`,
        })
        await port.evaluateBreakerAfterTask('logistics_coordinator', activeBranchItems, (nextSnap) =>
          new Map((nextSnap?.questions_needing_branch || []).map((q) => [`stage1:branch:${q}`, `need:${q}`])),
        )
      })
      return { handled: true }
    }
  }

  // 1.4 监察委员会签发 PARSE0_GATE 放行进入 STAGE2_EVOLVE
  const gateKey = 'stage1:gate'
  const gateFp = `stage:${snap.stage}`
  if (!port.isBreakerOpen(gateKey, gateFp)) {
    await port.launchGovTaskAndAwait('stage1:gate', async () => {
      await port.spawnAndRunAgent({
        role: 'supervisory_committee',
        uiLabel: '[监察委员会] Parse0 立项门禁',
        shortTransaction: false,
        signal: sig,
        prompt: '请调用 get_supervisory_audit_snapshot 核验 Parse 0 契约与开局就绪，调用 record_compliance_check(stage="PARSE0_GATE", status="PASSED", blocking_questions=[], notes="Parse 0 合规放行") 进入 STAGE2_EVOLVE。',
      })
      await port.evaluateBreakerAfterTask('supervisory_committee', [{ key: gateKey, beforeFp: gateFp }], (nextSnap) => {
        const m = new Map()
        if (nextSnap?.stage === 'STAGE1_PARSE0') m.set(gateKey, `stage:${nextSnap.stage}`)
        return m
      })
    })
    return { handled: true }
  }

  return { handled: false }
}
