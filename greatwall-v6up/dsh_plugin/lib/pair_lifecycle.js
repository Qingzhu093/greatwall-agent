/**
 * 长城 V6-Up (v3.0) 单探索节点生命周期驱动（PairLifecycle）：
 *
 * 严格落实 v3.0 两大核心协议：
 * 1. **单节点同会话伴随暂停续传**（`PRE_SPAWN` -> pause -> `REFLECT_37` -> pause -> `HANDOFF_70` -> dispose，绝不跨代常驻！
 *    仅在宿主重启/句柄丢失或 `<70%` 崩溃抢救时无状态冷启动兜底）；
 * 2. **70% 两步清醒交接**：
 *    - 第一步：将在线探索者动态切换至只读态 (`setSessionReadonly(expSessionId, true)`)，让清醒探索者执行最后 1 轮只读文本收官，
 *      亲笔输出客观总结与《科研遗嘱》，随后安全归档销毁探索者；
 *    - 第二步：续传同节点伴随会话，携探索者亲笔遗嘱与黑匣子轨迹摘要核对客观证据，独占单写 `submit_node_handoff`，
 *      完成后在 `finally` 中彻底销毁该节点伴随句柄。
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

/** 获取当前节点保活中的同会话伴随句柄（若未保活或已掉线则返回 null）。 */
function getLiveNodeCompanion(orchestrator, nodeId) {
  const map = orchestrator._nodeCompanionSessions
  if (!map || !nodeId) return null
  const handle = map.get(nodeId)
  if (!handle) return null
  if (!orchestrator.liveSessions?.has?.(handle.sessionId)) {
    map.delete(nodeId)
    return null
  }
  return handle
}

/** 彻底销毁指定节点的伴随会话句柄（严禁跨代常驻）。 */
export async function disposeNodeCompanion(orchestrator, nodeId, status = 'completed') {
  const map = orchestrator._nodeCompanionSessions
  if (!map || !nodeId) return
  const handle = map.get(nodeId)
  map.delete(nodeId)
  if (handle && typeof handle.dispose === 'function') {
    try {
      await handle.dispose(status)
    } catch {}
  }
}

/**
 * `PRE_SPAWN` 阶段：创建绑定该 `node_id` 的单节点伴随会话并写看板，随后挂起保活（`keepAliveAfterIdle: true`）
 * 以备同一节点的 `REFLECT_37` 与 `HANDOFF_70` 直接续传。
 */
export async function runPreSpawnBriefingWithCompanion(orchestrator, node, { signal = null } = {}) {
  const compSid = `gw_comp_${node.node_id}_${crypto.randomUUID().slice(0, 6)}`
  const compRes = await orchestrator.spawnAndRunAgent({
    role: 'lineage_companion',
    sessionId: compSid,
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: node.question_id,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: node.question_id, nodeId: node.node_id }),
    shortTransaction: true,
    keepAliveAfterIdle: true,
    signal,
    taskContextText: orchestrator._formatInterventionsForTarget('lineage_companion', node.question_id, node.node_id),
    prompt: `阶段 PRE_SPAWN：请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="PRE_SPAWN")，按五段滚动压缩预算 (<=2200字，不直接追加旧看板) 调用 save_lineage_briefing 写入本代初始看板；完成后挂起等待本节点的 37% 诊断与 70% 交接。`,
  })
  orchestrator._nodeCompanionSessions?.set?.(node.node_id, compRes)
  return compRes
}

/**
 * `REFLECT_37` 阶段：优先续传同节点伴随会话（句柄缺失时自动冷启动兜底），
 * 执行 `<=2` 轮专家诊断 + `<=2` 条编号指针指引并调 `record_reflection_and_unlock_pull`，完结后继续挂起等待 70%。
 */
export async function runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal) {
  let compHandle = getLiveNodeCompanion(orchestrator, node.node_id)
  const r37Prompt = `阶段 REFLECT_37（已到达 37% 回合间隙，无论 eval_count 是否为 0 均准时触发）！
### Explorer 黑匣子外部轨迹摘要 (去思维链)
${latestBlackbox}

请先调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="REFLECT_37") 获取本脉 dead_ends 摘要、同题 L3/L2 目录卡与夜科学题库，切换外部首席专家视角担任「临床诊断师 + 侦察兵」：
1. 必查第 7 类 Attractor Tasks + 1 项症状匹配类别；
2. 最多给探索者指出 <=2 条高信号馆藏编号指针（严禁整篇倒灌）；
3. 附 1 道尖锐夜科学启发性追问（<=300字），等待探索者只读作答后再调 record_reflection_and_unlock_pull 解锁内藏！`

  let lastCompText = ''
  if (compHandle) {
    const step = await orchestrator.continueAliveAgent(compHandle.sessionId, r37Prompt, { signal })
    lastCompText = step.lastAssistantText || ''
  } else {
    const compSid = `gw_comp_r37_${node.node_id}_${crypto.randomUUID().slice(0, 6)}`
    compHandle = await orchestrator.spawnAndRunAgent({
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
      taskContextText: orchestrator._formatInterventionsForTarget('lineage_companion', node.question_id, node.node_id),
      prompt: r37Prompt,
    })
    orchestrator._nodeCompanionSessions?.set?.(node.node_id, compHandle)
    lastCompText = compHandle.lastAssistantText || ''
  }

  const hasUnlockedSignal = () =>
    (compHandle.turnSignals || []).some(
      (s) => s.toolName === 'record_reflection_and_unlock_pull' && s.receipt?.ok !== false,
    )

  for (let round = 1; round <= 2; round++) {
    if (hasUnlockedSignal()) break

    const questionText = lastCompText || '请对照 Attractor Tasks 与当前推导/观测，简洁说明核心前提是否存在人为吸引子盲区（<=300字）？'
    const expReply = await orchestrator.continueAliveAgent(
      expSessionId,
      `[伴随助手 37% 专家诊断 Round ${round}]（请仅做纯文本简短只读作答 <=300 字，不要修改代码或运行耗时脚本）：\n${questionText}`,
      { signal },
    )
    const answerText = expReply.lastAssistantText || '已核查当前假设与证据边界，准备结合馆藏继续推进。'
    const compNext = await orchestrator.continueAliveAgent(
      compHandle.sessionId,
      `[探索者 Round ${round} 回答]：\n${answerText}\n\n若需最后 1 轮追问请简短提问（<=300字）；若诊断已明请立刻调用 record_reflection_and_unlock_pull 写入反思并置位解锁内藏 L3/L2！`,
      { signal },
    )
    lastCompText = compNext.lastAssistantText || ''
    if (compNext.turnSignals && compNext.turnSignals !== compHandle.turnSignals) {
      compHandle.turnSignals = compNext.turnSignals
    }
  }

  // 以真实工具成功回执或 SQLite 真源为准，严禁假解锁！
  let unlocked = hasUnlockedSignal()
  if (!unlocked && orchestrator.bridge?.control) {
    try {
      const checkRes = await orchestrator.bridge.control('control_plane/schedule_snapshot', {
        workspace_root: orchestrator.workspaceRoot,
      })
      const allNodes = [
        ...(checkRes?.data?.explorers_ready_to_run || []),
        ...(checkRes?.data?.explorers_needing_briefing || []),
      ]
      const matched = allNodes.find((n) => n?.node_id === node.node_id)
      if (matched && Boolean(matched.first_reflection_unlocked)) {
        unlocked = true
      }
    } catch {}
  }
  return { unlocked }
}

/**
 * 70% 交接或 `<70%` 崩溃抢救：优先续传同节点伴随会话（句柄缺失时冷启动 `HANDOFF_70` / `CRASH_RECOVERY` 兜底），
 * 独占单写 `submit_node_handoff`，并在 `finally` 彻底销毁该节点伴随会话（绝不跨代复用）。
 */
export async function runHandoffWithCompanion(
  orchestrator,
  node,
  {
    mode = 'HANDOFF_70',
    latestBlackbox = '',
    explorerWillText = '',
    interruptReason = '',
    signal = null,
  } = {},
) {
  const isCrash = mode === 'CRASH_RECOVERY'
  const compHandle = isCrash ? null : getLiveNodeCompanion(orchestrator, node.node_id)

  const promptBody = isCrash
    ? `阶段 CRASH_RECOVERY（探索者 ${node.node_id} 在 <70% 异常中断：${interruptReason || 'unknown'}）。
### 中断前黑匣子轨迹摘要
${latestBlackbox || '(无额外轨迹)'}

请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="CRASH_RECOVERY")，只读扫描 worktree 与已有 [Obs###]：
- 只要工作树存在任何有价值的纯数学推导草稿、反例构造或有效产物（即使 eval_count == 0），必须设 is_empty_crash=false、evidence_grade="ARTIFACT_ONLY" 或 "MEASURED" 抢救入 DAG；
- 仅在彻底空白无产物时设 is_empty_crash=true。请立即调 submit_node_handoff 落库。`
    : `阶段 HANDOFF_70（探索者已完成只读亲笔遗嘱收官并安全退场）。
### 探索者亲笔总结与《科研遗嘱》
${explorerWillText || '(探索者未输出额外遗嘱正文，请直接依据工作树与客观观测核对)'}

### 探索者退场前黑匣子轨迹摘要 (去思维链)
${latestBlackbox || '(无额外轨迹)'}

请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="HANDOFF_70")，将探索者亲笔总结与工作树 Diff、客观 [Obs###] 交叉核验，剥离自我合理化，写出严格 A/B 两栏分治（<2000字）、纯机理摘要（<100字）与结构化 dead_ends，独占单写 submit_node_handoff 落库！`

  try {
    if (compHandle) {
      await orchestrator.continueAliveAgent(compHandle.sessionId, promptBody, { signal })
    } else {
      await orchestrator.spawnAndRunAgent({
        role: 'lineage_companion',
        nodeId: node.node_id,
        branchId: node.branch_id,
        questionId: node.question_id,
        cwd: node.worktree_abs_path,
        uiLabel: formatNodeSessionTitle('lineage_companion', {
          questionId: node.question_id,
          nodeId: node.node_id,
          suffix: isCrash ? '崩溃抢救' : '70%交接',
        }),
        shortTransaction: true,
        signal,
        taskContextText: orchestrator._appendInterventions('', 'lineage_companion', node.question_id, node.node_id),
        prompt: promptBody,
      })
    }
  } finally {
    // 无论成功或异常，该节点伴随句柄必须随节点一同销毁，严禁跨代常驻！
    await disposeNodeCompanion(orchestrator, node.node_id, isCrash ? 'completed_crash_recovery' : 'completed')
  }
}

export async function driveExplorerCompanionPair(
  orchestrator,
  node,
  snap,
  expSessionId,
  { signal = null, maxExploreTurns = Infinity } = {},
) {
  const qid = node.question_id || ''
  const toolsManifest = scanLocalWorktreeTools(node.worktree_abs_path)
  const interventionsText = orchestrator._formatInterventionsForTarget('explorer', qid, node.node_id)
  const goalMd = snap?.goal_and_completion_md || ''

  const taskContextParts = [
    '## 当前分配工作区与任务契约',
    `- node_id: \`${node.node_id}\``,
    `- branch_id: \`${node.branch_id}\``,
    `- question_id: \`${qid}\``,
    `- worktree_abs_path: \`${node.worktree_abs_path}\``,
    goalMd ? `### Parse 0 课题目标与完成判据\n${goalMd}` : '',
    node.lane_assignment ? `### 五车道停滞分流专项任务 (Lane Assignment)\n${node.lane_assignment}` : '',
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
    prompt: `请面向子题 ${qid}（node_id="${node.node_id}"）开展首轮独立探索（0–37% 可自由查阅外部文献 [R###]，暂不可拉取内藏 L2/L3）：既可进行严格解析推导/反例构造，也可在已有科研仪器时调用 run_isolated_eval 获取客观观测。`,
    keepAliveAfterIdle: true,
  })

  let latestBlackbox = expRes.blackboxSummary
  let interrupted = expRes.isAbnormalEnd
  let interruptReason = expRes.turnEndReason ? JSON.stringify(expRes.turnEndReason) : ''
  let explorerWillText = ''
  let reflectedDone = Boolean(node.first_reflection_unlocked)
  let currentTurnSignals = expRes.turnSignals || []
  let currentNativeThresholds = expRes.nativeThresholds || []

  const hasTrigger = (name) =>
    currentTurnSignals.some((s) => s.trigger === name) ||
    currentNativeThresholds.some((t) => t.trigger === name)

  try {
    let turnsUsed = 1
    while (!interrupted) {
      const hitHandoff = hasTrigger('HANDOFF_70')
      const hitReflect = hasTrigger('REFLECT_37')

      if (hitHandoff) {
        break
      }

      if (hitReflect && !reflectedDone) {
        const refRes = await runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal)
        const actuallyUnlocked = Boolean(refRes?.unlocked)
        if (actuallyUnlocked) {
          reflectedDone = true
        }
        const postReflectPrompt = actuallyUnlocked
          ? '伴随助手已完成 37% 专家诊断并解锁内藏 L3/L2 与本脉 DAG！请按需定向调 query_library_catalog / get_library_entry / read_lineage_graph，推进 37–70% 深度攻坚。'
          : '37% 反思对话暂未完成服务端内藏解锁（内藏 L3/L2 仍处于锁定态，切勿强行调用内藏检索）。请先基于当前工作区与外藏 [R###] 继续推进实质研究，下个回合间隙将重新核验解锁。'
        const cont = await orchestrator.continueAliveAgent(expSessionId, postReflectPrompt, { signal })
        turnsUsed += 1
        latestBlackbox = cont.blackboxSummary || latestBlackbox
        currentTurnSignals = cont.turnSignals || currentTurnSignals
        currentNativeThresholds = cont.nativeThresholds || currentNativeThresholds
        if (cont.isAbnormalEnd) {
          interrupted = true
          interruptReason = cont.turnEndReason ? JSON.stringify(cont.turnEndReason) : 'continued_aborted'
        }
        continue
      }

      // 不跑到 70%（或触发 Cost Note）不准停工！绝不把普通短回合轮数上限伪装成 HANDOFF_70；
      // 仅在调用方显式指定有限安全熔断轮次且确实撞线时，按异常停滞中断转 CRASH_RECOVERY。
      if (Number.isFinite(maxExploreTurns) && turnsUsed >= maxExploreTurns) {
        interrupted = true
        interruptReason = `TURN_LIMIT_WITHOUT_HANDOFF_70:${turnsUsed}`
        break
      }
      const contPrompt = reflectedDone
        ? '当前上下文尚未达到 70% 交接水位（未满 70% 不准停工）：请继续深入验证、补齐反例/推导边界或运行高档位仪器观测。'
        : '当前上下文尚未达到 37% 反思水位（未满 70% 不准停工）：请继续深化推导、构造关键测试或调用科研仪器，推进至实质阶段性进展。'
      const cont = await orchestrator.continueAliveAgent(expSessionId, contPrompt, { signal })
      turnsUsed += 1
      latestBlackbox = cont.blackboxSummary || latestBlackbox
      currentTurnSignals = cont.turnSignals || currentTurnSignals
      currentNativeThresholds = cont.nativeThresholds || currentNativeThresholds
      if (cont.isAbnormalEnd) {
        interrupted = true
        interruptReason = cont.turnEndReason ? JSON.stringify(cont.turnEndReason) : 'continued_aborted'
      }
    }

    // 70% 两步清醒交接 · 第一步：将清醒探索者动态置为只读态，由其亲笔完成最后 1 轮文本总结与《科研遗嘱》
    if (!interrupted) {
      orchestrator.host?.setSessionReadonly?.(expSessionId, true)
      try {
        const willTurn = await orchestrator.continueAliveAgent(
          expSessionId,
          '【70% 清醒收官 · 只读文本回合】已触发安全交接窗口，当前会话已锁定为只读态（严禁修改文件、运行终端脚本或调用状态变更/评测工具）。请你亲笔用清晰简洁的文本写下：(1) 本代实际达成的客观进展与工件路径；(2) 已证实的死胡同或失败机制；(3) 留给下代探索者的具体《科研遗嘱》(Immediate Will)。写完即安全退场。',
          { signal },
        )
        explorerWillText = willTurn.lastAssistantText || ''
        latestBlackbox = willTurn.blackboxSummary || latestBlackbox
      } catch {
        // 若收官回合超时或中止，不影响后续伴随直接基于黑匣子与 worktree 交接
      }
      // 销毁探索者前将亲笔遗嘱持久化入 SQLite，失败时显式记告警不静默吞错
      if (orchestrator.bridge?.control) {
        try {
          const persistRes = await orchestrator.bridge.control('control_plane/record_pending_handoff', {
            workspace_root: orchestrator.workspaceRoot,
            node_id: node.node_id,
            mode: 'HANDOFF_70',
            explorer_will_md: explorerWillText,
            reason: 'HANDOFF_70',
          })
          if (!persistRes?.ok) {
            orchestrator.telemetry?.recordEvent?.('pending_handoff_persist_failed', {
              nodeId: node.node_id,
              mode: 'HANDOFF_70',
              error: persistRes?.error || 'unknown',
            })
          }
        } catch (err) {
          orchestrator.telemetry?.recordEvent?.('pending_handoff_persist_failed', {
            nodeId: node.node_id,
            mode: 'HANDOFF_70',
            error: String(err?.message || err),
          })
        }
      }
    } else if (orchestrator.bridge?.control) {
      try {
        const persistRes = await orchestrator.bridge.control('control_plane/record_pending_handoff', {
          workspace_root: orchestrator.workspaceRoot,
          node_id: node.node_id,
          mode: 'CRASH_RECOVERY',
          explorer_will_md: '',
          reason: interruptReason || 'abnormal_turn_end',
        })
        if (!persistRes?.ok) {
          orchestrator.telemetry?.recordEvent?.('pending_handoff_persist_failed', {
            nodeId: node.node_id,
            mode: 'CRASH_RECOVERY',
            error: persistRes?.error || 'unknown',
          })
        }
      } catch (err) {
        orchestrator.telemetry?.recordEvent?.('pending_handoff_persist_failed', {
          nodeId: node.node_id,
          mode: 'CRASH_RECOVERY',
          error: String(err?.message || err),
        })
      }
    }
  } finally {
    await orchestrator.host?.archiveSession?.(expSessionId, expRes.handle?.agent?.session)
    await expRes.dispose(interrupted ? 'interrupted_unclaimed' : 'completed', expRes.turnEndReason)
  }

  if (interrupted) {
    await disposeNodeCompanion(orchestrator, node.node_id, 'interrupted_explorer')
    orchestrator._pendingSalvageNodes.set(node.node_id, {
      node,
      reason: interruptReason || 'abnormal_turn_end',
      blackboxSummary: latestBlackbox,
    })
    return
  }

  // 70% 两步清醒交接 · 第二步：续传同节点伴随独占单写 submit_node_handoff，并在完成后销毁伴随
  await runHandoffWithCompanion(orchestrator, node, {
    mode: 'HANDOFF_70',
    latestBlackbox,
    explorerWillText,
    signal,
  })
  orchestrator._handoffsSinceHeartbeat += 1
}
