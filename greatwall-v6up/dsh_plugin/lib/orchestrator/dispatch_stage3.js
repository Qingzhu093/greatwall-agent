/**
 * Stage 3 两步联合终核与退修闭环状态机派发单元：
 * - `stage3_revision_pending`：采编退修重导新版本交付包；
 * - `stage3_final_audit_pending`：盲审官在只读空白终核沙箱核验范围与复现；
 * - `stage3_supervisory_sign_pending`：监察委核验版本哈希绑定落签晋升 CLOSED_VERIFIED。
 *
 * 严格只依赖窄能力端口 `DispatchRuntimePort`，零 `._` 私有字段访问，可脱离真实宿主独立单测。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage3
 */
import crypto from 'node:crypto'

/**
 * 执行一轮 Stage 3 终局状态机派发。
 * @param {any} port DispatchRuntimePort 公开运行时端口
 * @param {any} snap schedule_snapshot 数据
 * @param {AbortSignal} sig
 * @returns {{ handled: boolean, dispatched: boolean, waitMs?: number }}
 */
export function dispatchStage3Step(port, snap, sig) {
  if (snap.stage3_revision_pending) {
    let dispatched = false
    const latestDid = snap.closure_state?.latest_delivery_id || ''
    const revNotes = snap.closure_state?.verifier_revision_notes || '请修正边界表述与复现一致性'
    const deliveryMode = snap.closure_state?.delivery_mode || (snap.human_stop_active ? 'PARTIAL_ON_HUMAN_STOP' : 'FULL')
    const revKey = `stage3:revise:${latestDid}`
    const revFp = `revise:${latestDid}`
    if (!port.isBreakerOpen(revKey, revFp)) {
      if (port.launchGovTask(revKey, async () => {
        await port.spawnAndRunAgent({
          role: 'library_surveyor',
          uiLabel: `[图书馆采编] Stage3 退修重导 ${latestDid}`,
          shortTransaction: false,
          signal: sig,
          taskContextText: `### 盲审终核退修意见 (${latestDid})\n${revNotes}`,
          prompt: `盲审官已将 Stage 3 交付包 ${latestDid} 退修 (REVISION_REQUESTED)！请逐条核查上述退修意见，调 get_survey_requests(question_id="ALL") 对齐最新 L3 范围与复现节点，修正论文后调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出全新版本交付包。`,
        })
        await port.evaluateBreakerAfterTask('library_surveyor', [{ key: revKey, beforeFp: revFp }], (nextSnap) => {
          const m = new Map()
          if (nextSnap?.stage3_revision_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
            m.set(revKey, revFp)
          }
          return m
        })
      })) {
        dispatched = true
      }
    }
    return { handled: true, dispatched, waitMs: 250 }
  }

  if (snap.stage3_final_audit_pending) {
    let dispatched = false
    const latestDid = snap.closure_state?.latest_delivery_id || ''
    const auditRevId = `STAGE3_FINAL_AUDIT:${latestDid}`
    const auditKey = `stage3:final_audit:${latestDid}`
    const auditFp = `audit:${latestDid}`
    if (!port.isBreakerOpen(auditKey, auditFp)) {
      if (port.launchGovTask(auditKey, async () => {
        const staged = await port.control('control_plane/stage_blind_sandbox', {
          workspace_root: port.workspaceRoot,
          review_id: auditRevId,
        })
        const sandboxPath = typeof port.assertValidBlindSandbox === 'function'
          ? port.assertValidBlindSandbox(staged, auditRevId)
          : (() => {
              const p = String(staged?.data?.sandbox_abs_path || '').trim()
              if (!staged?.ok || !p) {
                throw new Error(`BLIND_SANDBOX_STAGE_FAILED (${auditRevId}): ${staged?.error || '空沙箱路径'}`)
              }
              return p
            })()
        try {
          await port.spawnAndRunAgent({
            role: 'library_verifier',
            sessionId: `gw_ver_s3_${crypto.randomUUID().slice(0, 6)}`,
            reviewId: auditRevId,
            deliveryId: latestDid,
            sandboxAbsPath: sandboxPath,
            uiLabel: `[图书馆盲审] Stage3 终稿终核 ${latestDid}`,
            shortTransaction: true,
            signal: sig,
            taskContextText: `### 独立只读终核沙箱（含交付包副本与 verified_l3_scopes.json）\n- sandbox_abs_path: \`${sandboxPath}\``,
            prompt: `Stage 3 终稿独立核验：请在只读沙箱内对照 verified_l3_scopes.json 审阅 final_delivery/ 副本（版本 ${latestDid}），核对所有引用 [L3-###]/[Obs-###]/[R###] 溯源真实、范围未夸大后，调用 submit_stage2_unblind_verdict(review_id="${auditRevId}", final_verdict="ACCEPT" 或 "REVISE", title="...", abstract_md="...") 落库。`,
          })
        } finally {
          await port
            .control('control_plane/cleanup_blind_sandbox', {
              workspace_root: port.workspaceRoot,
              review_id: auditRevId,
            })
            .catch(() => {})
        }
        await port.evaluateBreakerAfterTask('library_verifier', [{ key: auditKey, beforeFp: auditFp }], (nextSnap) => {
          const m = new Map()
          if (nextSnap?.stage3_final_audit_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
            m.set(auditKey, auditFp)
          }
          return m
        })
      })) {
        dispatched = true
      }
    }
    return { handled: true, dispatched, waitMs: 250 }
  }

  if (snap.stage3_supervisory_sign_pending) {
    let dispatched = false
    const latestDid = snap.closure_state?.latest_delivery_id || ''
    const signKey = `stage3:sign:${latestDid}`
    const signFp = `sign:${latestDid}`
    if (!port.isBreakerOpen(signKey, signFp)) {
      if (port.launchGovTask(signKey, async () => {
        await port.spawnAndRunAgent({
          role: 'supervisory_committee',
          uiLabel: `[监察委员会] 联合终签 ${latestDid}`,
          shortTransaction: false,
          signal: sig,
          prompt: `盲审官已完成最新版交付包 (${latestDid}) 独立终核！请调用 get_supervisory_audit_snapshot 确认版本哈希匹配，调用 record_compliance_check(stage="CLOSURE_GATE", status="PASSED", blocking_questions=[], notes="三项版本匹配校验通过，正式结项") 晋升 CLOSED_VERIFIED。`,
        })
        await port.evaluateBreakerAfterTask('supervisory_committee', [{ key: signKey, beforeFp: signFp }], (nextSnap) => {
          const m = new Map()
          if (nextSnap?.stage3_supervisory_sign_pending && nextSnap?.closure_state?.latest_delivery_id === latestDid) {
            m.set(signKey, signFp)
          }
          return m
        })
      })) {
        dispatched = true
      }
    }
    return { handled: true, dispatched, waitMs: 250 }
  }

  return { handled: false, dispatched: false }
}
