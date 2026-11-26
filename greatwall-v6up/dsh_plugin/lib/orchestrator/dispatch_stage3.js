/**
 * GreatWall v0.3 Stage 3 终稿退修与一步冻结包终签派发单元（裁决 3）。
 *
 * - `stage3_revision_pending`：派回零外网 `library_chronicler` 修正并重导新版本冻结包；
 * - `stage3_final_audit_pending`：派发 `library_verifier` 在只读沙箱核查外部不可变冻结包，
 *   签发 `ACCEPT` 即在单写者短锁内**一步原子结项 (`CLOSED_VERIFIED`)**，彻底取消原二次监察委放行。
 * @module dsh-greatwall-v6up/orchestrator/dispatch_stage3
 */
import crypto from 'node:crypto'

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
          role: 'library_chronicler',
          uiLabel: `[综述终稿官] Stage3 退修重导 ${latestDid}`,
          shortTransaction: false,
          signal: sig,
          taskContextText: `### 盲审终核退修意见 (${latestDid})\n${revNotes}`,
          prompt: `盲审官已将 Stage 3 冻结包 ${latestDid} 退修 (REVISION_REQUESTED)！请先调 get_chronicler_snapshot(question_id="ALL") 对齐全部 L3 精确边界，修正总报告后调用 export_stage3_final_delivery(delivery_mode="${deliveryMode}", ...) 导出全新不可变冻结包。`,
        })
        await port.evaluateBreakerAfterTask('library_chronicler', [{ key: revKey, beforeFp: revFp }], (nextSnap) => {
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
          : String(staged?.data?.sandbox_abs_path || '').trim()
        if (!sandboxPath) {
          throw new Error(`BLIND_SANDBOX_STAGE_FAILED (${auditRevId}): ${staged?.error || '空沙箱路径'}`)
        }
        try {
          await port.spawnAndRunAgent({
            role: 'library_verifier',
            sessionId: `gw_ver_s3_${crypto.randomUUID().slice(0, 6)}`,
            reviewId: auditRevId,
            deliveryId: latestDid,
            sandboxAbsPath: sandboxPath,
            uiLabel: `[图书馆盲审] Stage3 冻结包一步终签 ${latestDid}`,
            shortTransaction: true,
            signal: sig,
            taskContextText: `### 独立只读冻结包终核沙箱\n- sandbox_abs_path: \`${sandboxPath}\``,
            prompt: `Stage 3 冻结包终核：请先调 get_unblinded_manuscript_and_peers(review_id="${auditRevId}")，在只读沙箱内核对不可变冻结包 (${latestDid}) 未夸大任何 L3 范围且复现脚本一致后，调用 submit_stage2_unblind_verdict(review_id="${auditRevId}", final_verdict="ACCEPT" 或 "REVISE")——ACCEPT 将直接一步原子结项 CLOSED_VERIFIED！`,
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

  return { handled: false, dispatched: false }
}
