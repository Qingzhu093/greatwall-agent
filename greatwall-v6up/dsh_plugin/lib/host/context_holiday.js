/** 夜科学回合在宿主只读保护下运行，实际完成轮数由内核持久化。 */
export async function runContextHoliday(port, nodeId, sessionId, threshold, signal) {
  const identity = { workspace_root: port.workspaceRoot, node_id: nodeId }
  port.setSessionReadonly(sessionId, true, 'HOLIDAY_52')
  try {
    const start = await port.control('control_plane/begin_context_holiday', { ...identity, threshold }, { signal })
    if (!start.ok) throw new Error(start.error)
    if (start.data.holiday_completed) return null
    let lastReply = null
    for (let turn = start.data.turns_completed + 1; turn <= 2; turn++) {
      const prompt = turn === 1
        ? `【52% 暂停编程反思】本阶段暂停写码、Shell 和评测。请放空审视当前主线的反常现象或跨领域类比。\n${start.data.prompt}\n若已形成可证伪假设，可用 submit_holiday_bet 登记（恢复后优先服务原主线收官或做轻量探针，来不及完整实测的重大新假设可在 70% 标为 UNTESTED 留给下一代）。`
        : '【反思第 2 回合】将思考收敛为一个可证伪的假设或改进点。调用 submit_holiday_bet 说明反常/类比、可检验假设及证伪实验；恢复后请兼顾原主线收口，不必为了测新假设丢弃原工作。'
      lastReply = await port.continueAliveAgent(sessionId, prompt, { signal })
      if (lastReply.isAbnormalEnd) return lastReply
      const progress = await port.control(
        'control_plane/advance_context_holiday', { ...identity, completed_turn: turn }, { signal },
      )
      if (!progress.ok) throw new Error(progress.error)
      if (progress.data.holiday_completed) break
    }
    return lastReply
  } finally {
    port.setSessionReadonly(sessionId, false)
  }
}
