/**
 * 长城 V6-Up (v3.0) 编排器公开窄能力端口工厂与盲审沙箱强校验助手。
 *
 * 将端口构造与盲审沙箱 Fail-Closed 校验从 orchestrator.js 独立抽离，保持主编排器简洁聚焦。
 * @module dsh-greatwall-v6up/orchestrator/runtime_port
 */
import fs from 'node:fs'
import path from 'node:path'

/**
 * 强校验盲审空白沙箱 staging 结果（Fail-Closed）：
 * 绝不允许在 staging 失败、空路径、目录缺失或回退到主工作区时拉起 library_verifier。
 */
export function assertValidBlindSandboxResult(staged, reviewId, workspaceRoot, telemetry = null) {
  const sandboxRaw = String(staged?.data?.sandbox_abs_path || '').trim()
  if (!staged?.ok || !sandboxRaw) {
    const reason = String(staged?.error || 'stage_blind_sandbox 返回失败或空沙箱路径')
    telemetry?.recordEvent?.('blind_sandbox_stage_failed', { reviewId, reason })
    throw new Error(`BLIND_SANDBOX_STAGE_FAILED (${reviewId}): ${reason}`)
  }
  const resolvedSb = path.resolve(sandboxRaw)
  const resolvedWs = path.resolve(workspaceRoot)
  const sbLower = resolvedSb.toLowerCase()
  const wsLower = resolvedWs.toLowerCase()
  if (sbLower === wsLower || wsLower.startsWith(sbLower + path.sep)) {
    telemetry?.recordEvent?.('blind_sandbox_stage_failed', {
      reviewId,
      reason: 'sandbox_points_to_workspace_root',
      sandboxPath: resolvedSb,
    })
    throw new Error(`BLIND_SANDBOX_ISOLATION_VIOLATION (${reviewId}): 盲审沙箱路径不可指向主工作区 (${resolvedSb})`)
  }
  if (!fs.existsSync(resolvedSb) || !fs.statSync(resolvedSb).isDirectory()) {
    telemetry?.recordEvent?.('blind_sandbox_stage_failed', {
      reviewId,
      reason: 'sandbox_dir_missing',
      sandboxPath: resolvedSb,
    })
    throw new Error(`BLIND_SANDBOX_MISSING (${reviewId}): 盲审沙箱目录不存在 (${resolvedSb})`)
  }
  return resolvedSb
}

/**
 * 构造窄能力公开运行时端口（供 dispatch_stage1/2/3 与 pair_lifecycle 消费，零 ._ 访问）。
 * @param {any} orch GreatwallOrchestrator 实例
 */
export function buildDispatchRuntimePort(orch) {
  return {
    workspaceRoot: orch.workspaceRoot,
    ctx: orch.ctx,
    bridge: orch.bridge,
    isPoolStopped: () => orch.isPoolStopped(),
    getEffectiveContextWindow: () => orch.getEffectiveContextWindow(),
    isExplorerRunning: (nodeId) => orch.isExplorerRunning(nodeId),
    getRunningExplorerCount: () => orch.getRunningExplorerCount(),
    getRunningExplorerIds: () => orch.getRunningExplorerIds(),
    getAvailableBriefSlots: (snap, maxWorkers) => orch.getAvailableBriefSlots(snap, maxWorkers),
    isGovTaskRunning: (taskKey) => orch.isGovTaskRunning(taskKey),
    isBreakerOpen: (key, fp) => orch.isBreakerOpen(key, fp),
    launchGovTask: (taskKey, runner) => orch.launchGovTask(taskKey, runner),
    launchGovTaskAndAwait: (taskKey, runner) => orch.launchGovTaskAndAwait(taskKey, runner),
    evaluateBreakerAfterTask: (roleLabel, items, extractAfterMap) =>
      orch.evaluateBreakerAfterTask(roleLabel, items, extractAfterMap),
    launchExplorer: (node, snap, sig) => orch.launchExplorer(node, snap, sig),
    runBlindReview: (rev, sig) => orch.runBlindReview(rev, sig),
    assertValidBlindSandbox: (staged, reviewId) => orch.assertValidBlindSandbox(staged, reviewId),
    recordHandoffCompleted: (delta) => orch.recordHandoffCompleted(delta),
    shouldTriggerHeartbeat: (nowMs) => orch.shouldTriggerHeartbeat(nowMs),
    markHeartbeatFired: (nowMs) => orch.markHeartbeatFired(nowMs),
    initHeartbeatClockIfNeeded: (nowMs) => orch.initHeartbeatClockIfNeeded(nowMs),
    getLiveCompanion: (nodeId) => orch.getLiveCompanion(nodeId),
    setLiveCompanion: (nodeId, handle) => orch.setLiveCompanion(nodeId, handle),
    disposeCompanion: (nodeId, status) => orch.disposeCompanion(nodeId, status),
    setSessionReadonly: (sid, flag) => orch.setSessionReadonly(sid, flag),
    archiveSession: (sid, sess) => orch.archiveSession(sid, sess),
    spawnAndRunAgent: (opts) => orch.spawnAndRunAgent(opts),
    continueAliveAgent: (sid, prompt, opts) => orch.continueAliveAgent(sid, prompt, opts),
    control: (method, params, opts) => orch.control(method, params, opts),
    recordEvent: (name, detail) => orch.recordEvent(name, detail),
  }
}
