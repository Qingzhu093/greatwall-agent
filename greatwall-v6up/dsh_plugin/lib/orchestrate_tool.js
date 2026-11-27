/**
 * GreatWall v0.3 极简主控薄入口工具 `greatwall_orchestrate`（裁决 1）。
 *
 * 仅保留 `init / start / status / stop` 4 个薄动作供 CLI Headless 自动化测试与冷启动拉起使用；
 * 日常人机协同、改题、停单题、审批圆桌与 45% 人工接管统一走 `gw_chief` 独立 Preset + 人类显式落签。
 * @module dsh-greatwall-v6up/orchestrate_tool
 */

export const ORCHESTRATE_TOOL_SCHEMA = Object.freeze({
  type: 'object',
  properties: {
    action: {
      type: 'string',
      enum: ['init', 'start', 'status', 'stop'],
      description: 'init=签署 Parse 0 启动契约; start=锁定显式模型并拉起异步事件池; status=只读查询实时全院态势骨架; stop=停止事件池并释放子进程',
    },
    workspace_root: {
      type: 'string',
      description: '科研工作区根目录绝对路径',
    },
    provider: { type: 'string', description: '可选：显式锁定模型提供商 ID' },
    model: { type: 'string', description: '可选：显式锁定模型 ID' },
    effective_context_window: { type: 'integer', description: '可选：显式上下文窗口上限' },
    goal_and_completion_md: { type: 'string', description: 'Parse 0 课题总目标与完成判据（init 时必填）' },
    goal_md: { type: 'string', description: 'goal_and_completion_md 兼容字段' },
    subquestions: { type: 'array', items: { type: 'string' }, description: '必答子题列表，如 ["Q1","Q2"]' },
    required_questions: { type: 'array', items: { type: 'string' }, description: 'subquestions 兼容字段' },
    question_order: { type: 'array', items: { type: 'string' }, description: '可选：跨题推进顺序' },
    initial_instruments: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instrument_id: { type: 'string', description: '仪器唯一编号，如 inst_q1' },
          question_id: { type: 'string', description: '所属子题 ID 或 ALL' },
          instrument_type: { type: 'string', description: 'VERDICT / PROBE / ENV' },
          script_rel_path: { type: 'string', description: '已有仪器脚本相对路径（可选）' },
          description: { type: 'string', description: '仪器用途说明' },
        },
        additionalProperties: true,
      },
      description: '可选：初始科研仪器清单（无现成脚本可传 []，由工造司在 Stage 1 锻造）',
    },
    seed_families: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          family_id: { type: 'string', description: '学派唯一编号' },
          question_id: { type: 'string', description: '所属子题 ID' },
          mechanism_signature: { type: 'string', description: '核心方法学派简述' },
          seed_prompt: { type: 'string', description: '可选：开枝先验提示' },
        },
        additionalProperties: true,
      },
      description: '可选：种子方法学派（可传 [] 由后勤动态登记）',
    },
    total_budget: {
      type: 'object',
      properties: {
        max_total_handoffs: { type: 'integer', description: '全院总交班班次上限' },
        max_official_evals: { type: 'integer', description: '全院正式评测次数上限' },
        max_total_tokens: { type: 'integer', description: '全院总 Token 预算上限' },
      },
      additionalProperties: true,
      description: '可选：总预算约束',
    },
    min_commitment_window_sec: { type: 'integer', description: '可选：最短投入时间窗（秒）' },
    delivery_spec_md: { type: 'string', description: '可选：最终交付规范' },
    shared_inputs_rel_paths: { type: 'array', items: { type: 'string' }, description: '可选：公开输入相对路径' },
    autonomy_mode: { type: 'string', enum: ['WAVE_CONFIRM', 'AUTOPILOT'], description: '可选：自主档位（默认 WAVE_CONFIRM）' },
    max_concurrent_workers: { type: 'integer', description: '可选：并发探索者普通槽位数（不含 +1 人类保留槽）' },
  },
  required: ['action', 'workspace_root'],
})

function buildNextStepGuidance(action, raw = {}) {
  const st = raw.status && typeof raw.status === 'object' ? raw.status : raw
  if (raw.blocked === 'NEED_PARSE0_SIGNATURE') {
    return '尚未签署 Parse 0：请先调用 greatwall_orchestrate(action="init", workspace_root=..., goal_and_completion_md=..., subquestions=...) 落盘后再调用 start。'
  }
  if (raw.blocked) {
    return `启动受阻 (${raw.blocked})：${String(raw.error || st.lastError || '').slice(0, 240)}`
  }
  if (!raw.ok && raw.error) {
    return `操作未成功：${String(raw.error).slice(0, 240)}`
  }
  if (action === 'init') {
    return 'Parse 0 契约已落盘。请立即调用 greatwall_orchestrate(action="start", workspace_root=...) 启动后台科研事件池。'
  }
  if (action === 'start') {
    return '后台科研事件池已非阻塞启动。请向人类简报绑定模型与阶段，并提醒后续可在右侧长城面板或「长城 · 科研总控 (gw-chief)」对话中查账、审批提案与暂停接管；启动总控无需死等轮询。'
  }
  if (action === 'stop') {
    return '后台事件池已停止并释放活跃子会话与实例锁。'
  }
  if (st.closureStatus === 'CLOSED_VERIFIED' || st.stage === 'CLOSED_VERIFIED') {
    return '课题已通过终局核签 (CLOSED_VERIFIED)，最终交付物位于工作区 final_delivery/。'
  }
  if (Number(st.pendingProposalsCount || 0) > 0) {
    return `当前有 ${st.pendingProposalsCount} 条待人类拍板提案，请提醒人类在右侧长城面板或 gw-chief 确认。`
  }
  return '后台运行状态已返回；深度溯源或提案决策请通过右侧长城面板或 gw-chief 进行。'
}

/**
 * 面向大模型工具出口的 Inline & Spill 轻量骨架投影：
 * 彻底剔除仅供内部调度与 UI 使用的巨型 `snapshot` 与全量 `telemetry.sessions`，
 * 完整保留每道子题核心状态行（零子题信息丢失），从源头避免触发 DSH 8,192 字符截断。
 * @param {object} rawRes
 */
export function projectOrchestrateResultForAgent(rawRes = {}) {
  const raw = rawRes && typeof rawRes === 'object' ? rawRes : {}
  const action = String(raw.action || '')
  const st = raw.status && typeof raw.status === 'object' ? raw.status : {}
  const subList = Array.isArray(st.subproblemStates) ? st.subproblemStates : []

  const compactSubproblems = subList.map((q) => ({
    question_id: String(q?.question_id || ''),
    desired_state: String(q?.desired_state || 'ACTIVE'),
    dispatch_state: String(q?.dispatch_state || 'DISPATCHING'),
    active_spec_revision: Number(q?.active_spec_revision || 0),
    completed_waves: Number(q?.completed_waves || 0),
    spent_tokens: Number(q?.spent_tokens || 0),
    ...(q?.solved_entry_id ? { solved_entry_id: String(q.solved_entry_id) } : {}),
    ...(q?.block_reason_code ? { block_reason_code: String(q.block_reason_code) } : {}),
  }))

  const binding = raw.modelBinding || st.modelBinding || null
  const compactBinding = binding
    ? {
        ok: Boolean(binding.ok),
        provider: binding.provider || null,
        model: binding.model || null,
        ...(st.effectiveContextWindow ? { effectiveContextWindow: Number(st.effectiveContextWindow) } : {}),
      }
    : null

  const out = {
    ok: Boolean(raw.ok),
    action,
    ...(raw.started !== undefined ? { started: Boolean(raw.started) } : {}),
    ...(raw.alreadyRunning !== undefined ? { alreadyRunning: Boolean(raw.alreadyRunning) } : {}),
    ...(raw.resumed !== undefined ? { resumed: Boolean(raw.resumed) } : {}),
    ...(raw.stopped !== undefined ? { stopped: Boolean(raw.stopped) } : {}),
    ...(raw.blocked ? { blocked: String(raw.blocked) } : {}),
    ...(raw.error ? { error: String(raw.error).slice(0, 600) } : {}),
    poolState: st.poolState ?? raw.state ?? null,
    kernelAlive: st.kernelAlive ?? null,
    initialized: st.initialized ?? null,
    stage: st.stage ?? null,
    autonomyMode: st.autonomyMode ?? 'WAVE_CONFIRM',
    closureStatus: st.closureStatus ?? 'OPEN',
    humanStopActive: Boolean(st.humanStopActive),
    latestSpecRevision: Number(st.latestSpecRevision || 0),
    runningExplorersCount: Number(st.runningExplorersCount || 0),
    runningExplorers: Array.isArray(st.runningExplorers)
      ? st.runningExplorers.map((e) => ({ nodeId: e.nodeId, questionId: e.questionId }))
      : [],
    runningGovernanceTasks: Array.isArray(st.runningGovernanceTasks) ? st.runningGovernanceTasks : [],
    pendingProposalsCount: Number(st.pendingProposalsCount || 0),
    pendingHandoffNodes: Array.isArray(st.pendingHandoffNodes) ? st.pendingHandoffNodes : [],
    closureAllowed: Boolean(st.closureAllowed),
    subproblemStates: compactSubproblems,
    ...(compactBinding ? { modelBinding: compactBinding } : {}),
    ...(st.lastError ? { lastError: String(st.lastError).slice(0, 600) } : {}),
    next_step_guidance: buildNextStepGuidance(action, raw),
  }

  return out
}

export function registerOrchestrateTool(ctx, controlService) {
  if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
    return () => {}
  }
  const dispose = ctx.tools.register({
    name: 'greatwall_orchestrate',
    description:
      'GreatWall v0.3 极简编排器冷启动与 Headless 薄入口：仅提供 init / start / status / stop 4 个基础动作（已废除 pause/resume/abort_node）；日常科研调度与人机协同请使用右侧长城面板或「长城 · 科研总控 (gw-chief)」。',
    parameters: ORCHESTRATE_TOOL_SCHEMA,
    output: {
      schema: { type: 'object', additionalProperties: true },
      render(_args, value) {
        return [{ type: 'text', text: JSON.stringify(value) }]
      },
    },
    async execute(args, exec) {
      const rawRes = await controlService.execute({
        caller: 'agent_tool',
        action: String(args.action || ''),
        workspaceRoot: String(args.workspace_root || ''),
        payload: args,
        callerAgent: exec?.agent || null,
      })
      return projectOrchestrateResultForAgent(rawRes)
    },
  })
  return typeof dispose === 'function' ? dispose : () => {}
}
