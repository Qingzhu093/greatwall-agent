/**
 * Stage 1（Parse 0 启动对齐与初始化）确定性派发单元：
 * 1.1 固定统一核查一次 works_engineer（初始仪器就绪或确认空清单后置 stage1_works_checked=1）；
 * 1.2 外藏文献预建卡；
 * 1.3 后勤按需开枝；
 * 1.4 监察委 Parse 0 门禁放行进入 STAGE2_EVOLVE。
 *
 * 严格只依赖窄能力端口 `DispatchRuntimePort`，零 `._` 私有字段访问，可脱离真实宿主独立单测。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage1
 */

/**
 * 执行一轮 Stage 1 派发决策。
 * @param {any} port DispatchRuntimePort 公开运行时端口
 * @param {any} snap schedule_snapshot 数据
 * @param {AbortSignal} sig
 * @returns {Promise<{ handled: boolean, waitMs?: number }>}
 */
export async function dispatchStage1Step(port, snap, sig) {
  if (snap.stage !== 'STAGE1_PARSE0') {
    return { handled: false }
  }

  if (!snap.parse0_signed) {
    port.recordEvent('waiting_parse0_signature', {})
    return { handled: true, waitMs: 500 }
  }

  // 1.1 固定统一核查一次 works_engineer（初始仪器非空则逐台就绪；为空则确认无仪器后落标 stage1_works_checked=1）
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
          uiLabel: missingInsts.length > 0
            ? `[科研仪器科] Stage1 初始仪器锻造 (${missingInsts.length}项)`
            : '[科研仪器科] Stage1 初始核查确认',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 待就绪初始仪器清单\n${JSON.stringify(missingInsts, null, 2)}`,
          prompt: missingInsts.length > 0
            ? `Stage 1 初始仪器核查：请调用 get_works_engineering_queue(question_id="ALL")，为 Parse 0 声明且尚未激活的初始仪器 ${JSON.stringify(missingInsts)} 逐一编写脚本与校准集并调用 register_question_instrument 完成激活（请优先严格使用声明中的 instrument_id，不要随意增删 inst_ 前缀）。`
            : 'Stage 1 统一初始仪器核查：Parse 0 未声明初始仪器（如纯理论/推导课题）。请调用一次 get_works_engineering_queue(question_id="ALL") 确认当前无需锻造初始仪器后直接正常返回，控制面将自动标记 stage1_works_checked=1 推进后续流程。',
        })
        const checkRes = await port.control('control_plane/mark_stage1_works_checked', {
          workspace_root: port.workspaceRoot,
        })
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

  // 1.2 外藏文献预建卡
  if (Number(snap.external_literature_count || 0) === 0) {
    const s1Key = 'stage1:surveyor'
    const s1Fp = 'ext_count=0'
    if (!port.isBreakerOpen(s1Key, s1Fp)) {
      await port.launchGovTaskAndAwait('stage1:surveyor', async () => {
        await port.spawnAndRunAgent({
          role: 'library_surveyor',
          uiLabel: '[图书馆采编] 开局文献建卡',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}`,
          prompt: `Stage 1 开局外藏建设：请围绕 Parse 0 子题 ${JSON.stringify(snap.required_questions || [])} 的核心机理与背景文献，调研并发布至少 1 张高密度外藏卡片 [R001]（调 publish_external_literature_card；outcome="CARD_PUBLISHED"，support_scope 严格使用 5 项英文枚举之一，read_depth 使用英文枚举，abstract_md 长度 60–1500 字）。成功入库后即可收尾放行编排。`,
        })
        await port.evaluateBreakerAfterTask('library_surveyor', [{ key: s1Key, beforeFp: s1Fp }], (nextSnap) => {
          const m = new Map()
          if (Number(nextSnap?.external_literature_count || 0) === 0) m.set(s1Key, 'ext_count=0')
          return m
        })
      })
      return { handled: true }
    }
  }

  // 1.3 后勤按需开枝
  if (snap.questions_needing_branch?.length > 0) {
    const branchItems = snap.questions_needing_branch.map((q) => ({ key: `stage1:branch:${q}`, beforeFp: `need:${q}` }))
    const activeBranchItems = branchItems.filter((it) => !port.isBreakerOpen(it.key, it.beforeFp))
    if (activeBranchItems.length > 0) {
      await port.launchGovTaskAndAwait('stage1:logistics_init', async () => {
        await port.spawnAndRunAgent({
          role: 'logistics_coordinator',
          uiLabel: '[后勤总管] 开局按需开枝',
          shortTransaction: false,
          signal: sig,
          taskContextText: `### Parse 0 课题目标\n${snap.goal_and_completion_md || ''}\n### 子题解锁状态\n${JSON.stringify(snap.question_order_status || {}, null, 2)}`,
          prompt: `Stage 1 初始调度：请先调用 get_logistics_dashboard(question_id="ALL")，按课题本质（纯理论/数值/反例等）为已解锁子题 ${JSON.stringify(snap.questions_needing_branch)} 登记贴合机理的方法学派 (register_method_family) 并按需 fork_branch 开启初始分支（不强制固定学派数，禁止为凑数造伪学派）。`,
        })
        await port.evaluateBreakerAfterTask('logistics_coordinator', activeBranchItems, (nextSnap) =>
          new Map((nextSnap?.questions_needing_branch || []).map((q) => [`stage1:branch:${q}`, `need:${q}`])),
        )
      })
      return { handled: true }
    }
  }

  // 1.4 监察委 Parse 0 门禁放行
  const gateKey = 'stage1:gate'
  const gateFp = `stage:${snap.stage}`
  if (!port.isBreakerOpen(gateKey, gateFp)) {
    await port.launchGovTaskAndAwait('stage1:gate', async () => {
      await port.spawnAndRunAgent({
        role: 'supervisory_committee',
        uiLabel: '[监察委员会] Parse0 门禁',
        shortTransaction: false,
        signal: sig,
        prompt: '请调用 get_supervisory_audit_snapshot 核验 Parse 0 六项启动表单已签署与开局就绪，调用 record_compliance_check(stage="PARSE0_GATE", status="PASSED", blocking_questions=[], notes="Parse 0 合规放行") 进入 STAGE2_EVOLVE。',
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
