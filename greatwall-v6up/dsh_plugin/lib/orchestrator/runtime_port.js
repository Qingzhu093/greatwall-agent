/**
 * GreatWall v0.3 编排器公开窄能力端口工厂与盲审沙箱强校验助手。
 * @module dsh-greatwall-v6up/orchestrator/runtime_port
 */
import fs from 'node:fs'
import path from 'node:path'

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
    telemetry?.recordEvent?.('blind_sandbox_stage_failed', { reviewId, reason: 'sandbox_points_to_workspace_root', sandboxPath: resolvedSb })
    throw new Error(`BLIND_SANDBOX_ISOLATION_VIOLATION (${reviewId}): 盲审沙箱路径不可指向主工作区 (${resolvedSb})`)
  }
  if (!fs.existsSync(resolvedSb) || !fs.statSync(resolvedSb).isDirectory()) {
    telemetry?.recordEvent?.('blind_sandbox_stage_failed', { reviewId, reason: 'sandbox_dir_missing', sandboxPath: resolvedSb })
    throw new Error(`BLIND_SANDBOX_MISSING (${reviewId}): 盲审沙箱目录不存在 (${resolvedSb})`)
  }
  return resolvedSb
}

export function buildDispatchRuntimePort(orch) {
  return {
    workspaceRoot: orch.workspaceRoot,
    ctx: orch.ctx,
    bridge: orch.bridge,
    slotAllocator: orch.slotAllocator,
    isPoolStopped: () => orch.isPoolStopped(),
    isPoolPaused: () => orch.isPoolPaused(),
    getEffectiveContextWindow: () => orch.getEffectiveContextWindow(),
    isExplorerRunning: (nodeId) => orch.isExplorerRunning(nodeId),
    getRunningExplorerCount: () => orch.getRunningExplorerCount(),
    getRunningExplorerIds: () => orch.getRunningExplorerIds(),
    getAvailableBriefSlots: (snap, maxWorkers) => orch.getAvailableBriefSlots(snap, maxWorkers),
    isGovTaskRunning: (taskKey) => orch.isGovTaskRunning(taskKey),
    isBreakerOpen: (key, fp) => orch.isBreakerOpen(key, fp),
    launchGovTask: (taskKey, runner) => orch.launchGovTask(taskKey, runner),
    evaluateBreakerAfterTask: (roleLabel, items, extractAfterMap) =>
      orch.evaluateBreakerAfterTask(roleLabel, items, extractAfterMap),
    launchExplorer: (node, snap, sig) => orch.launchExplorer(node, snap, sig),
    runBlindReview: (rev, sig) => orch.runBlindReview(rev, sig),
    advanceWaveConference: (conf, sig) => orch.advanceWaveConference(conf, sig),
    assertValidBlindSandbox: (staged, reviewId) => orch.assertValidBlindSandbox(staged, reviewId),
    getLiveCompanion: (nodeId) => orch.getLiveCompanion(nodeId),
    setLiveCompanion: (nodeId, handle) => orch.setLiveCompanion(nodeId, handle),
    disposeCompanion: (nodeId, status) => orch.disposeCompanion(nodeId, status),
    settleSessionJobs: (sessionId, opts) => orch.humanTakeover.settleSessionJobs(sessionId, opts),
    setSessionReadonly: (sid, flag) => orch.setSessionReadonly(sid, flag),
    archiveSession: (sid, sess) => orch.archiveSession(sid, sess),
    spawnAndRunAgent: (opts) => orch.spawnAndRunAgent(opts),
    resumeOrSpawnAgent: (opts) => orch.resumeOrSpawnAgent(opts),
    continueAliveAgent: (sid, prompt, opts) => orch.continueAliveAgent(sid, prompt, opts),
    control: (method, params, opts) => orch.control(method, params, opts),
    recordEvent: (name, detail) => orch.recordEvent(name, detail),
  }
}
