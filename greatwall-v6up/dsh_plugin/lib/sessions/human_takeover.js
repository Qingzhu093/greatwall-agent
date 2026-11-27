const TERMINAL_JOB_STATES = new Set(['completed', 'killed', 'failed'])

export class HumanTakeoverCoordinator {
  constructor({ ctx, bridge, workspaceRoot, telemetry }) {
    this.ctx = ctx
    this.bridge = bridge
    this.workspaceRoot = workspaceRoot
    this.telemetry = telemetry
  }

  async recordHumanChat(nodeId, sessionId, text) {
    const preview = text.slice(0, 200)
    const result = await this.bridge.control('control_plane/record_human_chat_detected', {
      workspace_root: this.workspaceRoot, node_id: nodeId, session_id: sessionId, message_preview: preview,
    })
    if (!result.ok) throw new Error(result.error)
    this.telemetry?.recordEvent('human_chat_detected', { nodeId, sessionId, preview })
  }

  async settleSessionJobs(sessionId, { reason, signal } = {}) {
    const jobs = this.ctx?.get?.('jobs') ?? this.ctx?.jobs
    if (!jobs || !sessionId) return []
    const active = (await jobs.list(sessionId)).filter((job) =>
      job.owner === sessionId && !TERMINAL_JOB_STATES.has(job.status))
    await Promise.all(active.map(async ({ id, status }) => {
      if (reason && status !== 'stopping') await jobs.kill(id, sessionId, `greatwall:${reason}`)
      let job = await jobs.wait(id, 10_000, sessionId, signal)
      while (!TERMINAL_JOB_STATES.has(job.status)) {
        if (reason) throw new Error(`会话作业 ${id} 仍在退出`)
        job = await jobs.wait(id, 10_000, sessionId, signal)
      }
    }))
    return active.map((job) => job.id)
  }

  async drainAndYieldNode({
    nodeId, sessionId, liveHandle, livePromise, graceSec = 0, keepSessionForHuman = true,
    reason = 'PAUSE_REQUESTED', expectedGeneration, isCurrent = () => true, signal,
  }) {
    if (graceSec && livePromise) {
      let timer
      try {
        await Promise.race([
          livePromise.catch(() => {}),
          new Promise((resolve) => { timer = setTimeout(resolve, graceSec * 1000) }),
        ])
      } finally {
        clearTimeout(timer)
      }
    }
    if (!(await isCurrent())) return { stale: true }

    const agent = liveHandle?.agent
    agent?.cancel?.({ kind: 'hook', reason })
    const killedJobIds = await this.settleSessionJobs(sessionId, { reason, signal })
    await agent?.whenIdle?.()
    if (keepSessionForHuman) {
      const result = await this.bridge.control('control_plane/mark_node_yielded', {
        workspace_root: this.workspaceRoot, node_id: nodeId, expected_generation: expectedGeneration,
        details: { sessionId, killedJobIds, reason },
      })
      if (!result.ok) throw new Error(result.error)
    }
    return { killedJobIds }
  }
}
