/**
 * 长城 V6-Up (v2.2) 单探索分支生命周期驱动（PairLifecycle）：
 *
 * 1. 开局全工程底座 Push（`goal_md`, `contracts`, `public_input_sample`, `tools/`, 看板与干预指令）；
 * 2. 37% 回合间隙真实两轮问答引擎（`companion` <-> `explorer.followup` 只读交互解锁）；
 * 3. 退场后正常 70% 黑匣子交接 (`submit_node_handoff`) 或异常 `turn/end` 转入打捞队列。
 * @module dsh-greatwall-v6up/pair_lifecycle
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { formatNodeSessionTitle } from './prompts.js'

export function scanLocalWorktreeTools(worktreeAbsPath) {
  const toolsDir = path.join(worktreeAbsPath, 'tools')
  if (!fs.existsSync(toolsDir)) return []
  const items = []
  try {
    for (const name of fs.readdirSync(toolsDir)) {
      if (!name.endsWith('.py') || name.startsWith('_')) continue
      const full = path.join(toolsDir, name)
      try {
        const raw = fs.readFileSync(full, 'utf8')
        const firstLine = raw.split(/\r?\n/).find((l) => l.trim().startsWith('def ') || l.trim().startsWith('"""')) || ''
        items.push({ relPath: `tools/${name}`, preview: firstLine.trim() })
      } catch {
        items.push({ relPath: `tools/${name}`, preview: '' })
      }
    }
  } catch {}
  return items
}

export async function runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal) {
  const compSid = `gw_comp_r37_${node.node_id}_${crypto.randomUUID().slice(0, 6)}`
  const compRes = await orchestrator.spawnAndRunAgent({
    role: 'lineage_companion',
    sessionId: compSid,
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: node.question_id,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: node.question_id, nodeId: node.node_id, suffix: '37%反思' }),
    shortTransaction: true,
    keepAliveAfterIdle: true,
    signal,
    taskContextText: `### Explorer 黑匣子外部轨迹摘要 (去思维链)\n${latestBlackbox}`,
    prompt: `已到达 37% Turn 间隙！请先调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="REFLECT_37")，若需要与探索者对话请直接提出第 1 轮极简尖锐追问（<=300字，结合 Attractor Tasks 与 1 道夜科学），等待探索者回答后再调 record_reflection_and_unlock_pull！`,
  })

  try {
    for (let round = 1; round <= 2; round++) {
      const unlockedAlready = compRes.turnSignals.some((s) => s.toolName === 'record_reflection_and_unlock_pull')
      if (unlockedAlready) break

      const questionText = compRes.lastAssistantText || '请对照 Attractor Tasks 与当前观测，简洁说明你的核心假设是否存在人为吸引子风险（<=300字）？'
      const expReply = await orchestrator.continueAliveAgent(
        expSessionId,
        `[伴随助手 37% 质询 Round ${round}]（请仅做纯文本简短只读作答 <=300 字，不要修改代码或运行耗时脚本）：\n${questionText}`,
        { signal },
      )
      const answerText = expReply.lastAssistantText || '已检查当前数据范围，暂无额外实验偏移。'
      const compNext = await orchestrator.continueAliveAgent(
        compSid,
        `[探索者 Round ${round} 回答]：\n${answerText}\n\n若还需追问最后 1 轮可继续提问（<=300字）；若证据已足请直接调用 record_reflection_and_unlock_pull 写入并解锁内藏 L3/L2！`,
        { signal },
      )
      compRes.lastAssistantText = compNext.lastAssistantText
    }
  } finally {
    await compRes.dispose()
  }
}

export async function driveExplorerCompanionPair(orchestrator, node, snap, expSessionId, { signal = null } = {}) {
  const qid = node.question_id || ''
  const qContract = (snap?.contracts || {})[qid] || {}
  const pubSample = qContract.public_input_sample || (snap?.public_input_samples || {})[qid] || {}
  const toolsManifest = scanLocalWorktreeTools(node.worktree_abs_path)
  const interventionsText = orchestrator._formatInterventionsForTarget('explorer', qid, node.node_id)

  const taskContextParts = [
    '## 当前分配工作区与工程底座',
    `- node_id: \`${node.node_id}\``,
    `- branch_id: \`${node.branch_id}\``,
    `- question_id: \`${qid}\``,
    `- worktree_abs_path: \`${node.worktree_abs_path}\``,
    snap?.goal_md ? `### 课题目标摘要 (goal_md)\n${snap.goal_md}` : '',
    Object.keys(qContract).length ? `### 子题契约 (contracts)\n\`\`\`json\n${JSON.stringify(qContract, null, 2)}\n\`\`\`` : '',
    Object.keys(pubSample).length
      ? `### 钩子公开测试输入规范 (run_isolated_eval 将自动注入此格式！严禁在代码中写死本地假数据 Fallback！)\n\`\`\`json\n${JSON.stringify(pubSample, null, 2)}\n\`\`\``
      : '⚠️ 严禁写死本地兜底测试集：run(public_input) 缺失期望键时请直接抛出 ValueError/TypeError！',
    toolsManifest.length ? `### 本工作树 tools/ 已有模块清单\n${JSON.stringify(toolsManifest, null, 2)}` : '',
    node.briefing_snapshot_md ? `### Lineage Briefing 五段看板\n${node.briefing_snapshot_md}` : '',
    interventionsText,
  ].filter(Boolean)

  const expRes = await orchestrator.spawnAndRunAgent({
    role: 'explorer',
    sessionId: expSessionId,
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: qid,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('explorer', { questionId: qid, nodeId: node.node_id }),
    shortTransaction: false,
    signal,
    taskContextText: taskContextParts.join('\n\n'),
    prompt: `请检视本工作树工具清单与公开输入规范，面向 ${qid} 设计最小改动候选并调用 run_isolated_eval 完成首轮实测（node_id="${node.node_id}", question_id="${qid}"）。`,
    keepAliveAfterIdle: true,
  })

  let latestBlackbox = expRes.blackboxSummary
  let interrupted = expRes.isAbnormalEnd
  let interruptReason = expRes.turnEndReason ? JSON.stringify(expRes.turnEndReason) : ''

  try {
    const hitReflect = expRes.turnSignals.some((s) => s.trigger === 'REFLECT_37') ||
      expRes.nativeThresholds.some((t) => t.trigger === 'REFLECT_37')
    const hitHandoff = expRes.turnSignals.some((s) => s.trigger === 'HANDOFF_70') ||
      expRes.nativeThresholds.some((t) => t.trigger === 'HANDOFF_70')

    if (!interrupted && hitReflect && !hitHandoff) {
      await runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal)

      const cont = await orchestrator.continueAliveAgent(
        expSessionId,
        '伴随助手已完成 37% 元反思并解锁内藏 L3/L2 与血脉图！请继续 37–70% 深度攻坚（可调 query_library_catalog(scope="ALL") 或 read_lineage_graph），运行 run_isolated_eval 获取更高精度观测。',
        { signal },
      )
      latestBlackbox = cont.blackboxSummary || latestBlackbox
      if (cont.isAbnormalEnd) {
        interrupted = true
        interruptReason = cont.turnEndReason ? JSON.stringify(cont.turnEndReason) : 'continued_aborted'
      }
    }
  } finally {
    await orchestrator.host.archiveSession(expSessionId, expRes.handle?.agent?.session)
    await expRes.dispose(interrupted ? 'interrupted_unclaimed' : 'completed', expRes.turnEndReason)
  }

  if (interrupted) {
    orchestrator._pendingSalvageNodes.set(node.node_id, {
      node,
      reason: interruptReason || 'abnormal_turn_end',
      blackboxSummary: latestBlackbox,
    })
    return
  }

  await orchestrator.spawnAndRunAgent({
    role: 'lineage_companion',
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: qid,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: qid, nodeId: node.node_id, suffix: '70%交接' }),
    shortTransaction: true,
    signal,
    taskContextText: `### Explorer 退场前黑匣子轨迹摘要\n${latestBlackbox}`,
    prompt: `探索者已安全退场，请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="HANDOFF_70")，扫描 worktree（只读 \`read\`/\`glob\`/\`grep\`）与实测 [Obs###]，调 submit_node_handoff 提交结构化两栏手记（若零实测崩溃则设 is_zero_eval_crash=true）。`,
  })
  orchestrator._handoffsSinceHeartbeat += 1
}
