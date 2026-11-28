/**
 * GreatWall v0.3 单探索节点生命周期驱动（PairLifecycle）。
 *
 * v0.3 核心演进：
 * 1. 伴随会话使用确定性 ID (`gw-comp-<node_id>`) 按需通过 `resumeOrSpawnAgent` 从磁盘唤醒，不再强依赖内存常驻；
 * 2. 45% 人工接管保护：每轮续推前检查 `control_state`（`PAUSE_DRAINING / HUMAN_ACTIVE` 时立即优雅让权退出，绝不抢麦、绝不误报崩溃交班！）；
 * 3. 支持 `EARLY_HANDOFF_READY`（人类显式授权后合法提前进入两步清醒交班）；
 * 4. 注入 `.greatwall_donors/` 只读双供体目录清单（杂交分支 `SYNTHESIS`）与最新口径提示，彻底移除旧五车道。
 * @module dsh-greatwall-v6up/pair_lifecycle
 */
import { runContextHoliday } from './host/context_holiday.js'
import fs from 'node:fs'
import path from 'node:path'
import { sampleAgentContextPressure, syncLivePressureToDb } from './clock_and_turn_gap.js'
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

export function scanReadonlyDonorMounts(worktreeAbsPath) {
  const donorsDir = path.join(worktreeAbsPath, '.greatwall_donors')
  if (!fs.existsSync(donorsDir)) return []
  try {
    return fs.readdirSync(donorsDir, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => `.greatwall_donors/${e.name}`)
  } catch {
    return []
  }
}

function resolveCompanionSessionId(node) {
  return String(node?.companion_session_id || `gw-comp-${node?.node_id || 'unknown'}`)
}

export async function disposeNodeCompanion(port, nodeId, status = 'completed') {
  if (!port || !nodeId) return
  if (typeof port.disposeCompanion === 'function') {
    await port.disposeCompanion(nodeId, status)
  }
}

/** PRE_SPAWN：确定性会话 ID `gw-comp-<node_id>` 写看板，写完即可释句柄归档（后续阶段原生 resume 唤醒）。 */
export async function runPreSpawnBriefingWithCompanion(port, node, { signal = null } = {}) {
  const compSid = resolveCompanionSessionId(node)
  const runner = typeof port.resumeOrSpawnAgent === 'function' ? port.resumeOrSpawnAgent : port.spawnAndRunAgent
  const compRes = await runner({
    role: 'lineage_companion',
    sessionId: compSid,
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: node.question_id,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: node.question_id, nodeId: node.node_id }),
    shortTransaction: true,
    keepAliveAfterIdle: false,
    archiveOnComplete: false,
    signal,
    prompt: `阶段 PRE_SPAWN：请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="PRE_SPAWN")。消化本脉 latest_wave_takeaways、退修反馈和专题综述。融合分支先读 DONOR_MANIFEST.md。自主重写五段看板，合计不超过 5000 字，调用 save_lineage_briefing。`,
  })
  return compRes
}

/** REFLECT_37：按确定性 `gw-comp-<node_id>` 原生 resume 执行 <=2 轮诊断并当场解锁内藏。 */
export async function runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal) {
  const compSid = resolveCompanionSessionId(node)
  const r37Prompt = `阶段 REFLECT_37（已到达 37% 回合间隙，无论 eval_count 是否为 0 均准时触发）！
### Explorer 黑匣子外部轨迹摘要 (去思维链)
${latestBlackbox}

请先调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="REFLECT_37") 获取本脉死胡同、同题目录卡与 C01–C11 元反思目录。对症选择 1–2 类、给出至多 2 条证据编号，并提出最多两轮诊断问题。每轮应答不超过 500 字。完成后用 record_reflection_and_unlock_pull 解锁内藏、总览与专题综述。`

  const runner = typeof orchestrator.resumeOrSpawnAgent === 'function'
    ? orchestrator.resumeOrSpawnAgent
    : orchestrator.spawnAndRunAgent
  const compHandle = await runner({
    role: 'lineage_companion',
    sessionId: compSid,
    nodeId: node.node_id,
    branchId: node.branch_id,
    questionId: node.question_id,
    cwd: node.worktree_abs_path,
    uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: node.question_id, nodeId: node.node_id, suffix: '37%反思' }),
    shortTransaction: true,
    keepAliveAfterIdle: true,
    archiveOnComplete: false,
    signal,
    prompt: r37Prompt,
  })
  orchestrator.setLiveCompanion?.(node.node_id, compHandle)

  let lastCompText = compHandle.lastAssistantText || ''
  const hasUnlockedSignal = () =>
    (compHandle.turnSignals || []).some(
      (s) => s.toolName === 'record_reflection_and_unlock_pull' && s.receipt?.ok !== false,
    )

  try {
    for (let round = 1; round <= 2; round++) {
      if (hasUnlockedSignal()) break
      if (!lastCompText.trim()) break
      const questionText = lastCompText
      const expReply = await orchestrator.continueAliveAgent(
        expSessionId,
        `[伴随助手 37% 专家诊断 Round ${round}]（请用不超过 500 字的纯文本回答）：\n${questionText}`,
        { signal },
      )
      const answerText = expReply.lastAssistantText
      if (!answerText?.trim()) break
      const compNext = await orchestrator.continueAliveAgent(
        compHandle.sessionId,
        `[探索者 Round ${round} 回答]：\n${answerText}\n\n若诊断已明请立刻调用 record_reflection_and_unlock_pull 写入反思并置位解锁内藏！`,
        { signal },
      )
      lastCompText = compNext.lastAssistantText || ''
      if (compNext.turnSignals && compNext.turnSignals !== compHandle.turnSignals) {
        compHandle.turnSignals = compNext.turnSignals
      }
    }
  } finally {
    await disposeNodeCompanion(orchestrator, node.node_id, 'completed')
  }

  let unlocked = hasUnlockedSignal()
  if (!unlocked && typeof orchestrator.control === 'function') {
    try {
      const checkRes = await orchestrator.control('control_plane/schedule_snapshot', { workspace_root: orchestrator.workspaceRoot })
      const allNodes = [
        ...(checkRes?.data?.explorers_ready_to_run || []),
        ...(checkRes?.data?.explorers_needing_briefing || []),
      ]
      const matched = allNodes.find((n) => n?.node_id === node.node_id)
      if (matched && Boolean(matched.first_reflection_unlocked)) unlocked = true
    } catch {}
  }
  return { unlocked }
}

/** HANDOFF_70 / CRASH_RECOVERY：按确定性 `gw-comp-<node_id>` 原生 resume 提交封存交班并支持确定性直落。 */
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
  const compSid = resolveCompanionSessionId(node)
  const effectiveWill = String(explorerWillText || node?.will_md || node?.explorer_will_md || '').trim()

  const promptBody = isCrash
    ? `阶段 CRASH_RECOVERY（探索者 ${node.node_id} 在 <70% 异常中断：${interruptReason || 'unknown'}）。
### 中断前黑匣子轨迹摘要
${latestBlackbox || '(无额外轨迹，请直接以工作树工件与客观观测为准)'}

请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="CRASH_RECOVERY")，只要存在有价值的推导或产物即设 is_empty_crash=false 抢救入 DAG，否则设 is_empty_crash=true，调 submit_node_handoff 落库封存。`
    : `阶段 HANDOFF_70（探索者已完成只读亲笔遗嘱收官并退场）。
### 探索者亲笔总结与《科研遗嘱》
${effectiveWill || '(请直接依据工作树与客观观测核对)'}

### 探索者退场前黑匣子轨迹摘要
${latestBlackbox || '(无额外轨迹)'}

请调用 get_companion_context(branch_id="${node.branch_id}", node_id="${node.node_id}", mode="HANDOFF_70")，A/B 双栏和遗嘱合计不超过 5000 字，mechanism_summary 少于 100 字。有夜科学赌注时用 holiday_bet_outcome 按观测核销。成熟的阶段稿用 manuscript_submissions 非阻塞送审。调用 submit_node_handoff 封存落库。`

  const runner = typeof orchestrator.resumeOrSpawnAgent === 'function'
    ? orchestrator.resumeOrSpawnAgent
    : orchestrator.spawnAndRunAgent
  try {
    await runner({
      role: 'lineage_companion',
      sessionId: compSid,
      nodeId: node.node_id,
      branchId: node.branch_id,
      questionId: node.question_id,
      cwd: node.worktree_abs_path,
      uiLabel: formatNodeSessionTitle('lineage_companion', {
        questionId: node.question_id,
        nodeId: node.node_id,
        suffix: isCrash ? '崩溃抢救' : '70%封存交班',
      }),
      shortTransaction: true,
      archiveOnComplete: true,
      signal,
      prompt: promptBody,
    })
  } finally {
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
  const donorMounts = scanReadonlyDonorMounts(node.worktree_abs_path)
  const goalMd = snap?.goal_and_completion_md || ''
  const specRev = Number(node.spec_revision ?? snap?.latest_spec_revision ?? 0)
  const effWindow = Number(
    (typeof orchestrator.getEffectiveContextWindow === 'function' ? orchestrator.getEffectiveContextWindow() : 0) ||
      node.effective_context_window ||
      360_000,
  )
  const availableInstruments = (snap?.active_instruments || []).filter(
    (inst) => inst && inst.health_status !== 'UNHEALTHY' && (String(inst.question_id || '') === String(qid) || String(inst.question_id || '') === 'ALL'),
  )
  const instrumentsMd = availableInstruments.length
    ? availableInstruments
        .map((inst) => {
          let hint = ''
          try {
            const spec = typeof inst.default_spec_json === 'string'
              ? JSON.parse(inst.default_spec_json || '{}')
              : (inst.default_spec_json || {})
            if (spec && typeof spec.interface_hint === 'string' && spec.interface_hint.trim()) {
              hint = ` | 接口约定: ${spec.interface_hint.trim()}`
            }
          } catch {}
          return `- \`${inst.instrument_id}\` (v${inst.version}, role=${inst.instrument_role}, schema=${inst.artifact_schema || 'python_run'}, q=${inst.question_id})${hint}`
        })
        .join('\n')
    : ''

  const taskContextParts = [
    '## 当前分配工作区与任务契约',
    `- node_id: \`${node.node_id}\``,
    `- branch_id: \`${node.branch_id}\``,
    `- question_id: \`${qid}\``,
    `- branch_kind: \`${node.branch_kind || 'PURE'}\``,
    `- spec_revision: \`v${specRev}\``,
    `- effective_context_window: \`${effWindow}\` tokens (37% 反思解锁 / 70% 清醒交班)`,
    `- worktree_abs_path: \`${node.worktree_abs_path}\``,
    '- 越界退回守则：若人类在聊天窗提出改题/停他枝/结题等全局诉求，立即调用 `handback_to_chief` 原样退回总控，绝不越权执行。',
    goalMd ? `### Parse 0 课题目标与完成判据\n${goalMd}` : '',
    instrumentsMd ? `### 本子题已激活科研仪器清单\n${instrumentsMd}` : '',
    publicInputsList.length ? `### 只读公开题面与裁决文档目录 (inputs/)\n${publicInputsList.map((p) => `- \`${p}\``).join('\n')}` : '',
    donorMounts.length ? `### 只读次供体源码挂载目录（严禁修改，仅供借鉴融合）\n${donorMounts.map((d) => `- \`${d}\``).join('\n')}` : '',
    toolsManifest.length ? `### 本工作树 tools/ 已有模块清单\n${JSON.stringify(toolsManifest, null, 2)}` : '',
    node.branch_kind === 'HUMAN_SEEDED' ? '### 人类研究蓝图\n请先完整读取 inputs/human_seed_blueprint.md，再按当前任务验证其中的推导。' : '',
    node.briefing_snapshot_md ? `### Lineage Briefing 五段看板\n${node.briefing_snapshot_md}` : '',
  ].filter(Boolean)

  const runner = typeof orchestrator.resumeOrSpawnAgent === 'function'
    ? orchestrator.resumeOrSpawnAgent
    : orchestrator.spawnAndRunAgent

  const expRes = await runner({
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
    prompt: `请面向子题 ${qid}（node_id="${node.node_id}"，口径 v${specRev}）开展探索（0–37% 可查阅 inputs/ 与外藏 [R###]，37% 元反思后解锁内藏 L2/L3 与《子题全局总览》）。`,
    keepAliveAfterIdle: true,
  })

  let latestBlackbox = expRes.blackboxSummary
  let interrupted = expRes.isAbnormalEnd
  let lastTurnEndReason = expRes.turnEndReason || null
  let interruptReason = expRes.turnEndReason ? JSON.stringify(expRes.turnEndReason) : ''
  let terminatedExternally = false
  let yieldedToHuman = false
  let pausedByHost = false
  let finishCurrentTurn = false
  let waveHibernateReason = ''
  let earlyHandoffAuthorized = false
  let explorerWillText = ''
  let reflectedDone = Boolean(node.first_reflection_unlocked)
  const holidayPct = orchestrator.getContextHolidayPct?.() ?? 0.52
  let holidayDue = false
  let currentTurnSignals = expRes.turnSignals || []
  let currentNativeThresholds = expRes.nativeThresholds || []
  // 续跑同一历史会话时，以节点已记账水位作为基线，仅增量累加本次新增 Token
  let lastAccountedTokens = Math.max(0, Number(node.pressure_tokens || 0))

  const hasTrigger = (name) =>
    currentTurnSignals.some((s) => s.trigger === name) ||
    currentNativeThresholds.some((t) => t.trigger === name)

  const checkNodeControlAndStatus = async () => {
    const isStopped = typeof orchestrator.isPoolStopped === 'function' ? orchestrator.isPoolStopped() : false
    if (signal?.aborted || isStopped || hasTrigger('NODE_TERMINATED')) {
      terminatedExternally = true
      return false
    }
    const isPaused = typeof orchestrator.isPoolPaused === 'function' ? orchestrator.isPoolPaused() : false
    if (isPaused) {
      pausedByHost = true
      orchestrator.recordEvent?.('explorer_paused_by_host', { nodeId: node.node_id, reason: 'pool_paused' })
      return false
    }
    const controlBridge = orchestrator.bridge || (typeof orchestrator.control === 'function' ? { control: orchestrator.control } : null)
    if (!controlBridge) return true
    try {
      const sample = sampleAgentContextPressure(orchestrator.ctx, expRes.handle?.agent, effWindow)
      const curTokens = Math.max(0, Number(sample?.pressureTokens || 0))
      if (qid && curTokens > lastAccountedTokens) {
        const delta = curTokens - lastAccountedTokens
        lastAccountedTokens = curTokens
        await controlBridge.control('control_plane/record_subproblem_tokens', {
          workspace_root: orchestrator.workspaceRoot,
          question_id: qid,
          delta_tokens: delta,
        }).catch(() => {})
      }

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
        return false
      }
      if (rowData.human_stop_active) {
        pausedByHost = true
        orchestrator.recordEvent?.('explorer_paused_by_host', { nodeId: node.node_id, reason: 'human_stop_active' })
        return false
      }
      const subState = String(rowData.subproblem_dispatch_state || '')
      if (subState && subState !== 'DISPATCHING') {
        pausedByHost = true
        orchestrator.recordEvent?.('explorer_paused_by_host', { nodeId: node.node_id, reason: `subproblem_${subState}` })
        return false
      }
      const ctrlState = String(rowData.control_state || 'AUTO_RUNNING')
      if (ctrlState === 'DRAIN_AFTER_TURN' && rowData.pending_handoff_reason?.startsWith('HIBERNATED_BY_WAVE_CONFERENCE')) {
        waveHibernateReason = rowData.pending_handoff_reason
        finishCurrentTurn = true
        return true
      }
      if (ctrlState === 'PAUSE_DRAINING' || ctrlState === 'HUMAN_ACTIVE') {
        yieldedToHuman = true
        orchestrator.recordEvent?.('explorer_yielded_to_human', { nodeId: node.node_id, controlState: ctrlState })
        return false
      }
      if (ctrlState === 'DRAIN_AFTER_TURN' || ctrlState === 'HIBERNATED') {
        finishCurrentTurn = ctrlState === 'DRAIN_AFTER_TURN'
        pausedByHost = true
        return false
      }
      if (ctrlState === 'EARLY_HANDOFF_READY') {
        earlyHandoffAuthorized = true
        return true
      }
      if (rowData.first_reflection_unlocked) reflectedDone = true
      holidayDue = reflectedDone && rowData.holiday_completed === false
        && rowData.pressure_tokens / rowData.effective_context_window >= holidayPct
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
      const stillActive = await checkNodeControlAndStatus()
      if (!stillActive) break
      if (earlyHandoffAuthorized || waveHibernateReason) break
      if (holidayDue) {
        const holidayReply = await runContextHoliday(orchestrator, node.node_id, expSessionId, holidayPct, signal)
        if (holidayReply) {
          latestBlackbox = holidayReply.blackboxSummary || latestBlackbox
          lastTurnEndReason = holidayReply.turnEndReason ?? lastTurnEndReason
          currentTurnSignals = holidayReply.turnSignals || currentTurnSignals
          currentNativeThresholds = holidayReply.nativeThresholds || currentNativeThresholds
          if (holidayReply.isAbnormalEnd) {
            interrupted = true
            interruptReason = JSON.stringify(holidayReply.turnEndReason)
          }
        }
        continue
      }
      if (hasTrigger('HANDOFF_70')) break

      if (hasTrigger('REFLECT_37') && !reflectedDone) {
        const refRes = await runReflect37SocraticDialogue(orchestrator, node, expSessionId, latestBlackbox, signal)
        if (refRes?.unlocked) reflectedDone = true
        if (!(await checkNodeControlAndStatus())) break
        if (earlyHandoffAuthorized) break
        if (holidayDue) continue

        const postReflectPrompt = reflectedDone
          ? '伴随助手已完成 37% 专家诊断并解锁内藏 L3/L2、《子题全局总览》与本脉 DAG！请按需调 get_living_survey / query_library_catalog 推进 37–70% 深度攻坚。'
          : '37% 反思对话暂未完成服务端内藏解锁，请先基于当前工作区与外藏继续推进实质研究。'
        const cont = await orchestrator.continueAliveAgent(expSessionId, postReflectPrompt, { signal })
        turnsUsed += 1
        latestBlackbox = cont.blackboxSummary || latestBlackbox
        lastTurnEndReason = cont.turnEndReason ?? lastTurnEndReason
        currentTurnSignals = cont.turnSignals || currentTurnSignals
        currentNativeThresholds = cont.nativeThresholds || currentNativeThresholds
        if (cont.isAbnormalEnd) {
          interrupted = true
          interruptReason = cont.turnEndReason ? JSON.stringify(cont.turnEndReason) : 'continued_aborted'
        }
        continue
      }

      if (Number.isFinite(maxExploreTurns) && turnsUsed >= maxExploreTurns) {
        interrupted = true
        interruptReason = `TURN_LIMIT_WITHOUT_HANDOFF_70:${turnsUsed}`
        break
      }
      const contPrompt = reflectedDone
        ? '当前上下文尚未达到 70% 交接水位：请继续深化验证、补齐边界或运行高档位仪器观测。'
        : '当前上下文尚未达到 37% 反思水位：请继续深化推导、构造关键测试或调用科研仪器。'
      const cont = await orchestrator.continueAliveAgent(expSessionId, contPrompt, { signal })
      turnsUsed += 1
      latestBlackbox = cont.blackboxSummary || latestBlackbox
      lastTurnEndReason = cont.turnEndReason ?? lastTurnEndReason
      currentTurnSignals = cont.turnSignals || currentTurnSignals
      currentNativeThresholds = cont.nativeThresholds || currentNativeThresholds
      if (cont.isAbnormalEnd) {
        interrupted = true
        interruptReason = cont.turnEndReason ? JSON.stringify(cont.turnEndReason) : 'continued_aborted'
      }
    }

    // 若在途回合被取消/中断，进入崩溃善后前必须复核一次控制态，避免把人类暂停接管误判为 CRASH_RECOVERY
    if (interrupted && !(terminatedExternally || yieldedToHuman || pausedByHost)) {
      await checkNodeControlAndStatus()
    }
    if (terminatedExternally || yieldedToHuman || pausedByHost) return

    const callControl = typeof orchestrator.control === 'function'
      ? (method, params) => orchestrator.control(method, params)
      : null

    if (!interrupted) {
      if (typeof orchestrator.setSessionReadonly !== 'function') {
        throw new Error('RUNTIME_PORT_CONTRACT_ERROR: 缺少必需的 setSessionReadonly 能力')
      }
      orchestrator.setSessionReadonly(expSessionId, true)
      try {
        const willTurn = await orchestrator.continueAliveAgent(
          expSessionId,
          waveHibernateReason
            ? '【圆桌休眠 · 只读交班】请简要列出已完成的客观事实、绑定观测编号及一句科研遗嘱，留给封存伴随。'
            : earlyHandoffAuthorized
            ? '【人类授权提前交班 · 只读文本回合】已锁定只读态，请亲笔总结本代客观成果、死胡同与《科研遗嘱》，写完即退场。'
            : '【70% 清醒收官 · 只读文本回合】已锁定只读态（严禁改码/跑脚本/调写工具），请亲笔总结：(1) 客观进展与工件路径；(2) 已证实死胡同；(3) 留给下代的《科研遗嘱》。',
          { signal },
        )
        explorerWillText = willTurn.lastAssistantText || ''
        latestBlackbox = willTurn.blackboxSummary || latestBlackbox
        lastTurnEndReason = willTurn.turnEndReason ?? lastTurnEndReason
      } catch {}
      if (callControl) {
        await callControl('control_plane/record_pending_handoff', {
          workspace_root: orchestrator.workspaceRoot,
          node_id: node.node_id,
          mode: 'HANDOFF_70',
          explorer_will_md: explorerWillText,
          reason: waveHibernateReason || (earlyHandoffAuthorized ? 'EARLY_HANDOFF_AUTHORIZED' : 'HANDOFF_70'),
        }).catch(() => {})
      }
    } else if (callControl) {
      await callControl('control_plane/record_pending_handoff', {
        workspace_root: orchestrator.workspaceRoot,
        node_id: node.node_id,
        mode: 'CRASH_RECOVERY',
        explorer_will_md: '',
        reason: interruptReason || 'abnormal_end',
      }).catch(() => {})
    }
  } finally {
    // 若已让权给人类对话（HUMAN_ACTIVE）或宿主暂停，保留磁盘会话不归档，也不触发崩溃交班
    const keepUnarchived = yieldedToHuman || pausedByHost
    const disposeStatus = yieldedToHuman
      ? 'yielded_to_human'
      : (pausedByHost ? 'paused_by_host' : (terminatedExternally ? 'terminated_external' : (interrupted ? 'interrupted_unclaimed' : 'completed')))
    try {
      if (finishCurrentTurn) await orchestrator.settleSessionJobs(expSessionId, { signal })
    } finally {
      await expRes.dispose(disposeStatus, lastTurnEndReason, { archive: keepUnarchived ? false : undefined })
    }
    if (terminatedExternally) {
      await disposeNodeCompanion(orchestrator, node.node_id, 'terminated_external')
    }
  }

  if (terminatedExternally || yieldedToHuman || pausedByHost) return

  await runHandoffWithCompanion(orchestrator, node, {
    mode: interrupted ? 'CRASH_RECOVERY' : 'HANDOFF_70',
    latestBlackbox,
    explorerWillText,
    interruptReason,
    signal,
  })
}
