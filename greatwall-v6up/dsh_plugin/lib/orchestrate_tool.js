/**
 * 主控 Agent 侧工具 `greatwall_orchestrate` 声明与薄适配器。
 *
 * 所有控制逻辑统一委托给 `GreatwallControlService`（One Operation, Two Callers），
 * 本文件仅负责向 DSH `ctx.tools` 注册参数 Schema 与解包调用参数。
 * @module dsh-greatwall-v6up/orchestrate_tool
 */

export const ORCHESTRATE_TOOL_SCHEMA = Object.freeze({
  type: 'object',
  properties: {
    action: {
      type: 'string',
      enum: [
        'init',
        'start',
        'pause',
        'resume',
        'stop',
        'human_stop',
        'abort_node',
        'submit_works_ticket',
        'sync_rulings',
        'inspect',
        'status',
      ],
      description:
        'init=签署Parse0六项表单; start=锁定模型绑定并异步启动事件池; pause/resume/stop=暂停/恢复并同步rulings/停止; human_stop=写入人类叫停真源; abort_node=确定性中止单节点; submit_works_ticket=向科研仪器科签发正式工单并立刻唤醒工造司修复/升级仪器; sync_rulings=同步工作区rulings补充裁决; inspect=深度只读透视仪器/工单/谱系/盲审/监察状态; status=查实时状态',
    },
    workspace_root: {
      type: 'string',
      description: '科研工作区根目录绝对路径',
    },
    provider: {
      type: 'string',
      description: '可选：显式锁定模型提供商 ID（如 deepseek-account）；缺省自动继承主控当前选中模型',
    },
    model: {
      type: 'string',
      description: '可选：显式锁定模型 ID（如 deepseek-flash）；缺省自动继承主控当前选中模型，无法解析将拒启',
    },
    effective_context_window: {
      type: 'integer',
      description: '可选：显式上下文窗口上限（最终按 min(500000, model_physical_window) 取值）',
    },
    context_window_tokens: {
      type: 'integer',
      description: 'effective_context_window 兼容字段',
    },
    goal_and_completion_md: {
      type: 'string',
      description: 'Parse 0 第 1 项：课题总目标与明确完成判据（兼容 goal_md）',
    },
    goal_md: {
      type: 'string',
      description: '课题总目标兼容字段（等同 goal_and_completion_md）',
    },
    subquestions: {
      type: 'array',
      items: { type: 'string' },
      description: 'Parse 0 第 2 项：必答子题列表（兼容 required_questions），如 ["Q1","Q2"]',
    },
    required_questions: {
      type: 'array',
      items: { type: 'string' },
      description: '子题列表兼容字段（等同 subquestions）',
    },
    question_order: {
      type: 'array',
      items: { type: 'string' },
      description: '可选：跨题推进顺序提示（如 ["Q1","Q2"]）',
    },
    initial_instruments: {
      type: 'array',
      items: { type: 'object' },
      description: 'Parse 0 第 3 项：初始科研仪器清单（纯理论题可留空数组）',
    },
    seed_families: {
      type: 'array',
      items: { type: 'object' },
      description: 'Parse 0 第 4 项：种子方法学派提示（可留空数组由后勤动态建档）',
    },
    total_budget: {
      type: 'object',
      description: 'Parse 0 第 5 项：总预算约束，如 {"max_total_handoffs": 30, "max_official_evals": 100}',
    },
    min_commitment_window_sec: {
      type: 'integer',
      description: 'Parse 0 最短投入时间窗口（秒，默认 0；未满窗口前禁止提前收工，除非控制面执行 human_stop）',
    },
    delivery_spec_md: {
      type: 'string',
      description: 'Parse 0 最终交付物形态规范（如论文格式、复现脚本或形式化内核要求）',
    },
    shared_inputs_rel_paths: {
      type: 'array',
      items: { type: 'string' },
      description: '可选：额外声明的工作区公开题面/输入数据/裁决文档相对路径（自动只读挂载至沙箱 inputs/）',
    },
    max_concurrent_workers: {
      type: 'integer',
      description: '最大并发探索者槽位数（默认 6，硬上限 10）',
    },
    node_id: {
      type: 'string',
      description: 'abort_node 要中止的目标节点 ID，或 inspect 要深度查看的节点 ID（如 node_q1_xxxx）',
    },
    reason: {
      type: 'string',
      description: 'abort_node 中止原因、human_stop 备注说明，或 submit_works_ticket 问题描述兼容字段',
    },
    question_id: {
      type: 'string',
      description: 'submit_works_ticket 目标子题编号（如 Q1 / Q3 / ALL，默认 ALL）',
    },
    ticket_type: {
      type: 'string',
      enum: ['INSTRUMENT_ERROR', 'PAIN_POINT', 'DUPLICATE_TOOL', 'EXPLOIT'],
      description: 'submit_works_ticket 工单类型（默认 INSTRUMENT_ERROR）',
    },
    instrument_id: {
      type: 'string',
      description: 'submit_works_ticket 可选：指定故障或需升级的仪器 ID（如 inst_surrogate_simulator）',
    },
    description: {
      type: 'string',
      description: 'submit_works_ticket 必填：仪器缺陷、校准问题或改造需求详细说明',
    },
    refresh_active_worktrees: {
      type: 'boolean',
      description: 'sync_rulings 可选：是否同时刷新在线探索者的 inputs/rulings/（默认 false，仅升版 spec_revision）',
    },
  },
  required: ['action', 'workspace_root'],
})

/**
 * 向主控 DSH `ctx.tools` 注册 `greatwall_orchestrate` 工具。
 * @param {any} ctx
 * @param {import('./control_service.js').GreatwallControlService} controlService
 * @returns {() => void} disposer
 */
export function registerOrchestrateTool(ctx, controlService) {
  if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
    return () => {}
  }
  const dispose = ctx.tools.register({
    name: 'greatwall_orchestrate',
    description:
      '长城 V6-Up (v3.0) 科研共同体外部无状态异步编排器主控入口：init(签署Parse 0六项启动表单) / start(锁定显式模型绑定与自适应窗口并启动事件池) / pause / resume(自动同步工作区rulings补充裁决) / stop / human_stop(人类叫停真源) / abort_node(确定性精准中止单节点) / submit_works_ticket(向科研仪器科正式发工单并立刻唤醒修仪器) / sync_rulings(同步公开补充裁决) / inspect(深度透视仪器/工单/谱系/盲审状态) / status。',
    parameters: ORCHESTRATE_TOOL_SCHEMA,
    output: {
      schema: { type: 'object', additionalProperties: true },
      render(_args, value) {
        return [{ type: 'text', text: JSON.stringify(value) }]
      },
    },
    async execute(args, exec) {
      return controlService.execute({
        caller: 'agent_tool',
        action: String(args.action || ''),
        workspaceRoot: String(args.workspace_root || ''),
        payload: args,
        callerAgent: exec?.agent || null,
      })
    },
  })
  return typeof dispose === 'function' ? dispose : () => {}
}
