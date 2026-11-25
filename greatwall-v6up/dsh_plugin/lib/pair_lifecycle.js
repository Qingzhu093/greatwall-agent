/**
 * 长城 V6-Up (v3.0) 单探索节点生命周期驱动（PairLifecycle）：
 *
 * 严格落实 v3.0 顶层核心协议：
 * 1. **单节点同会话伴随暂停续传**（`PRE_SPAWN` -> pause -> `REFLECT_37` -> pause -> `HANDOFF_70` -> dispose，绝不跨代常驻！
 *    仅在宿主重启/句柄丢失或 `<70%` 崩溃抢救时从 SQLite 单真源冷启动兜底）；
 * 2. **防僵尸探索者实时核查**：每轮续推前校验 SQLite 实时 `node_status`，节点一旦处于非活跃态（如 `abort_node` / 外部关闭 / 结项），
 *    立刻停止续推并同时销毁探索者与私有伴随句柄，绝不占槽烧钱；
 * 3. **硬性跑满 `37% -> 70%` 与两步清醒交接（无 Cost Note / 无提前逃跑后门）**：
 *    - 第一步：将在线探索者动态切换至只读态 (`setSessionReadonly(expSessionId, true)`)，亲笔输出客观总结与《科研遗嘱》，
 *      **先可靠持久化至 SQLite `lineage_nodes.will_md` / `pending_handoff_mode='HANDOFF_70'` 后再销毁探索者句柄**；
 *    - 第二步：续传同节点伴随会话核对客观证据，独占单写 `submit_node_handoff`，并在 `finally` 中彻底销毁该节点伴随句柄。
 * @module dsh-greatwall-v6up/pair_lifecycle
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { syncLivePressureToDb } from './clock_and_turn_gap.js'
import { formatNodeSessionTitle } from './prompts.js'

const ACTIVE_EXPLORE_STATUSES = new Set(['EXPLORING', 'ACTIVE_REVISING'])

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

export function scanLocalWorktreePublicInputs(worktreeAbsPath) {
  const inputsDir = path.join(worktreeAbsPath, 'inputs')
  if (!fs.existsSync(inputsDir)) return []
  const found = []
  const walk = (dir, prefix = 'inputs') => {
    try {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const rel = `${prefix}/${entry.name}`
        if (entry.isDirectory()) {
          if (found.length < 30) walk(path.join(dir, entry.name), rel)
        } else if (entry.isFile()) {
          found.push(rel)
          if (found.length >= 30) return
        }
      }
    } catch {}
  }
  walk(inputsDir)
  return found
}

/** 获取当前节点保活中的同会话伴随句柄（若未保活或已掉线则返回 null）。 */
function getLiveNodeCompanion(port, nodeId) {
  if (!port || !nodeId) return null
  return typeof port.getLiveCompanion === 'function' ? port.getLiveCompanion(nodeId) : null
}

/** 彻底销毁指定节点的伴随会话句柄（严禁跨代常驻）。 */
export async function disposeNodeCompanion(port, nodeId, status = 'completed') {
  if (!port || !nodeId) return
  if (typeof port.disposeCompanion === 'function') {
    await port.disposeCompanion(nodeId, status)
  }
}

/**
 * `PRE_SPAWN` 阶段：创建绑定该 `node_id` 的单节点伴随会话并写看板，随后挂起保活（`keepAliveAfterIdle: true`）
 * 以备同一节点的 `REFLECT_37` 与 `HANDOFF_70` 直接续传。
 */
export async function runPreSpawnBriefingWithCompanion(port, node, { signal = null } = {}) {
  const compSid = `gw_comp_${node.node_id}_${crypto.randomUUID().slice(0, 6)}`
  const compRes = await port.spawnAndRunAgent({
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
    prompt: `阶段 PRE_SPAWN：请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="PRE_SPAWN")，按五段滚动压缩预算 (<=2200字，不直接追加旧看板) 调用 save_lineage_briefing 写入本代初始看板；完成后挂起等待本节点的 37% 诊断与 70% 交接。`,
  })
  port.setLiveCompanion?.(node.node_id, compRes)
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
      prompt: r37Prompt,
    })
    orchestrator.setLiveCompanion?.(node.node_id, compHandle)
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

  // 以真实工具成功回执或 SQLite 真源为准，严禁假解锁
  let unlocked = hasUnlockedSignal()
  if (!unlocked && typeof orchestrator.control === 'function') {
    try {
      const checkRes = await orchestrator.control('control_plane/schedule_snapshot', {
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
  const effectiveWill = String(explorerWillText || node?.will_md || node?.explorer_will_md || '').trim()

  const promptBody = isCrash
    ? `阶段 CRASH_RECOVERY（探索者 ${node.node_id} 在 <70% 异常中断或未落库亲笔遗嘱即重启：${interruptReason || 'unknown'}）。
### 中断前黑匣子轨迹摘要
${latestBlackbox || '(无额外轨迹，亲笔遗嘱原文缺失，请直接以工作树工件与客观观测为准)'}

请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="CRASH_RECOVERY")，只读扫描 worktree 与已有 [Obs###]：
- 只要工作树存在任何有价值的纯数学推导草稿、反例构造或有效产物（即使 eval_count == 0），必须设 is_empty_crash=false、evidence_grade="ARTIFACT_ONLY" 或 "MEASURED" 抢救入 DAG；
- 仅在彻底空白无产物时设 is_empty_crash=true。请立即调 submit_node_handoff 落库。`
    : `阶段 HANDOFF_70（探索者已完成只读亲笔遗嘱收官并安全退场）。
### 探索者亲笔总结与《科研遗嘱》
${effectiveWill || '(探索者未输出额外遗嘱正文，请直接依据工作树与客观观测核对)'}

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
        prompt: promptBody,
      })
    }
  } finally {
    // 无论成功或异常，该节点伴随句柄必须随节点一同销毁，严禁跨代常驻
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
  const publicInputsList = scanLocalWorktreePublicInputs(node.worktree_abs_path)
  const goalMd = snap?.goal_and_completion_md || ''
  const specRev = Number(node.spec_revision ?? snap?.latest_spec_revision ?? 0)
  const effWindow = Number(
    (typeof orchestrator.getEffectiveContextWindow === 'function'
      ? orchestrator.getEffectiveContextWindow()
      : 0) ||
      node.effective_context_window ||
      500_000,
  )
  const availableInstruments = (snap?.active_instruments || []).filter(
    (inst) =>
      inst &&
      inst.health_status !== 'UNHEALTHY' &&
      (String(inst.question_id || '') === String(qid) || String(inst.question_id || '') === 'ALL'),
  )
  const instrumentsMd = availableInstruments.length
    ? availableInstruments
        .map((inst) => {
          let hintText = ''
          try {
            const specObj = typeof inst.default_spec_json === 'string'
              ? JSON.parse(inst.default_spec_json || '{}')
              : (inst.default_spec_json || {})
            const hint = specObj?.interface_hint || specObj?.entry_point || specObj?.expected_format
            if (hint) hintText = ` | 接口约定: ${String(hint).slice(0, 260)}`
          } catch {}
          return `- \`${inst.instrument_id}\` (v${inst.version}, role=${inst.instrument_role}, schema=${inst.artifact_schema || 'python_run'}, q=${inst.question_id})${hintText}`
        })
        .join('\n')
    : ''

  const taskContextParts = [
    '## 当前分配工作区与任务契约',
    `- node_id: \`${node.node_id}\``,
    `- branch_id: \`${node.branch_id}\``,
    `- question_id: \`${qid}\``,
    `- spec_revision: \`v${specRev}\``,
    `- effective_context_window: \`${effWindow}\` tokens (37% 反思 / 70% 硬交接)`,
    `- worktree_abs_path: \`${node.worktree_abs_path}\``,
    '- 工程执行守则：自测脚本请先小样本快跑控制在 30–60 秒内再分级放大（防 600s 终端硬超时）；命令与文件读写请基于当前 worktree 根目录使用相对路径，勿用 `../` 越界。',
    goalMd ? `### Parse 0 课题目标与完成判据\n${goalMd}` : '',
    instrumentsMd
      ? `### 本子题已激活科研仪器清单 (run_isolated_eval 可直接调用)\n${instrumentsMd}`
      : '',
    publicInputsList.length
      ? `### 只读公开题面与裁决文档目录 (inputs/)\n${publicInputsList.map((p) => `- \`${p}\``).join('\n')}`
      : '',
    node.lane_assignment ? `### 五车道停滞分流专项任务 (Lane Assignment)\n${node.lane_assignment}` : '',
    toolsManifest.length ? `### 本工作树 tools/ 已有模块清单\n${JSON.stringify(toolsManifest, null, 2)}` : '',
    node.briefing_snapshot_md ? `### Lineage Briefing 五段看板\n${node.briefing_snapshot_md}` : '',
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
    prompt: `请面向子题 ${qid}（node_id="${node.node_id}"，口径 v${specRev}）开展首轮独立探索（0–37% 可自由查阅 inputs/ 公开题面与外藏 [R###]，暂不可拉取内藏 L2/L3）：既可进行严格解析推导/反例构造，也可在已有科研仪器时调用 run_isolated_eval 获取客观观测。`,
    keepAliveAfterIdle: true,
  })

  let latestBlackbox = expRes.blackboxSummary
  let interrupted = expRes.isAbnormalEnd
  let interruptReason = expRes.turnEndReason ? JSON.stringify(expRes.turnEndReason) : ''
  let terminatedExternally = false
  let externalTermReason = ''
  let explorerWillText = ''
  let reflectedDone = Boolean(node.first_reflection_unlocked)
  let currentTurnSignals = expRes.turnSignals || []
  let currentNativeThresholds = expRes.nativeThresholds || []

  const hasTrigger = (name) =>
    currentTurnSignals.some((s) => s.trigger === name) ||
    currentNativeThresholds.some((t) => t.trigger === name)

  /**
   * 防僵尸核查：每轮续推前检查 SQLite 实时 `node_status` 与外部控制面状态。
   * 一旦节点在 DB 中已被置为 CLOSED/SEALED/AWAITING_TRIAGE/PENDING_REVIEW/BLOCKED_L4B 或发生外部中止，
   * 立即退场销毁探索者与伴随句柄，绝不占槽续推！
   */
  const checkNodeStillActiveInDb = async () => {
    const isStopped = typeof orchestrator.isPoolStopped === 'function'
      ? orchestrator.isPoolStopped()
      : false
    if (signal?.aborted || isStopped) {
      terminatedExternally = true
      externalTermReason = 'POOL_STOPPED_OR_ABORTED'
      return false
    }
    if (hasTrigger('NODE_TERMINATED')) {
      terminatedExternally = true
      externalTermReason = 'NODE_TERMINATED_SIGNAL'
      return false
    }
    const controlBridge = orchestrator.bridge || (typeof orchestrator.control === 'function' ? { control: orchestrator.control } : null)
    if (!controlBridge) return true
    try {
      const syncRes = await syncLivePressureToDb(
        orchestrator.ctx,
        expRes.handle?.agent,
        controlBridge,
        orchestrator.workspaceRoot,
        node.node_id,
        effWindow,
      )
      const rowData = syncRes?.data ?? syncRes ?? {}
      const liveStatus = String(rowData.node_status || '')
      if (liveStatus && !ACTIVE_EXPLORE_STATUSES.has(liveStatus)) {
        terminatedExternally = true
        externalTermReason = `DB_NODE_STATUS:${liveStatus}`
        orchestrator.recordEvent?.('explorer_terminated_by_db_status', {
          nodeId: node.node_id,
          nodeStatus: liveStatus,
        })
        return false
      }
      if (rowData.first_reflection_unlocked) {
        reflectedDone = true
      }
      if (rowData.trigger === 'HANDOFF_70' && !hasTrigger('HANDOFF_70')) {
        currentNativeThresholds.push({ trigger: 'HANDOFF_70', pressurePct: rowData.pressure_pct, sourceHook: 'db_sync' })
      } else if (rowData.trigger === 'REFLECT_37' && !reflectedDone && !hasTrigger('REFLECT_37')) {
        currentNativeThresholds.push({ trigger: 'REFLECT_37', pressurePct: rowData.pressure_pct, sourceHook: 'db_sync' })
      }
    } catch {}
    return true
  }

  try {
    let turnsUsed = 1
    while (!interrupted) {
      const stillActive = await checkNodeStillActiveInDb()
      if (!stillActive) {
        break
      }

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
        // 反思完毕后再次核查节点活跃性，防止反思期间外部 abort_node
        if (!(await checkNodeStillActiveInDb())) break

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

      // 硬性跑满 70%（不设提前逃跑或 Cost Note 后门）；仅在测试显式指定有限安全上限时按异常中断转 CRASH_RECOVERY
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

    // 外部终态/中止：不写假交接、不入崩溃抢救，直接交由 finally 释放探索者与伴随句柄
    if (terminatedExternally) {
      return
    }

    // 70% 两步清醒交接 · 第一步：切只读 -> 亲笔立遗嘱 -> 必须先持久化至 SQLite will_md，再销毁探索者句柄
    const callControl = typeof orchestrator.control === 'function'
      ? (method, params) => orchestrator.control(method, params)
      : null
    if (!interrupted) {
      if (typeof orchestrator.setSessionReadonly !== 'function') {
        throw new Error('RUNTIME_PORT_CONTRACT_ERROR: 缺少必需的 setSessionReadonly 能力，无法执行 70% 只读遗嘱收官')
      }
      orchestrator.setSessionReadonly(expSessionId, true)
      try {
        const willTurn = await orchestrator.continueAliveAgent(
          expSessionId,
          '【70% 清醒收官 · 只读文本回合】已触发安全交接窗口，当前会话已锁定为只读态（严禁修改文件、运行终端脚本或调用状态变更/评测工具）。请你亲笔用清晰简洁的文本写下：(1) 本代实际达成的客观进展与工件路径；(2) 已证实的死胡同或失败机制；(3) 留给下代探索者的具体《科研遗嘱》(Immediate Will)。写完即安全退场。',
          { signal },
        )
        explorerWillText = willTurn.lastAssistantText || ''
        latestBlackbox = willTurn.blackboxSummary || latestBlackbox
      } catch {
        // 收官回合超时时仍保留已有黑匣子供伴随兜底
      }
      if (callControl) {
        try {
          const persistRes = await callControl('control_plane/record_pending_handoff', {
            workspace_root: orchestrator.workspaceRoot,
            node_id: node.node_id,
            mode: 'HANDOFF_70',
            explorer_will_md: explorerWillText,
            reason: 'HANDOFF_70',
          })
          if (!persistRes?.ok) {
            orchestrator.recordEvent?.('pending_handoff_persist_failed', {
              nodeId: node.node_id,
              mode: 'HANDOFF_70',
              error: persistRes?.error || 'unknown',
            })
          }
        } catch (err) {
          orchestrator.recordEvent?.('pending_handoff_persist_failed', {
            nodeId: node.node_id,
            mode: 'HANDOFF_70',
            error: String(err?.message || err),
          })
        }
      }
    } else if (callControl) {
      // <70% 异常中断：唯一真源直接落 SQLite `pending_handoff_mode='CRASH_RECOVERY'`，取消内存双账本
      try {
        const persistRes = await callControl('control_plane/record_pending_handoff', {
          workspace_root: orchestrator.workspaceRoot,
          node_id: node.node_id,
          mode: 'CRASH_RECOVERY',
          explorer_will_md: '',
          reason: interruptReason || 'abnormal_turn_end',
        })
        if (!persistRes?.ok) {
          orchestrator.recordEvent?.('pending_handoff_persist_failed', {
            nodeId: node.node_id,
            mode: 'CRASH_RECOVERY',
            error: persistRes?.error || 'unknown',
          })
        }
      } catch (err) {
        orchestrator.recordEvent?.('pending_handoff_persist_failed', {
          nodeId: node.node_id,
          mode: 'CRASH_RECOVERY',
          error: String(err?.message || err),
        })
      }
    }
  } finally {
    // 由 expRes.dispose 统一按 RC5 顺序：先 handle.dispose() 解除活跃占用，再调用原生 archiveSession 并写入真实归档状态
    await expRes.dispose(
      terminatedExternally ? 'terminated_external' : (interrupted ? 'interrupted_unclaimed' : 'completed'),
      terminatedExternally ? { kind: 'terminated_external', reason: externalTermReason } : expRes.turnEndReason,
      { archive: true },
    )
    if (terminatedExternally || interrupted) {
      await disposeNodeCompanion(
        orchestrator,
        node.node_id,
        terminatedExternally ? 'terminated_external' : 'interrupted_explorer',
      )
    }
  }

  if (terminatedExternally || interrupted) {
    return
  }

  // 70% 两步清醒交接 · 第二步：续传同节点伴随独占单写 submit_node_handoff，并在完成后销毁伴随
  await runHandoffWithCompanion(orchestrator, node, {
    mode: 'HANDOFF_70',
    latestBlackbox,
    explorerWillText,
    signal,
  })
  orchestrator.recordHandoffCompleted?.(1)
}
