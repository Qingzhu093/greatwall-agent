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
      description: 'init=签署 Parse 0 启动契约; start=锁定显式模型并拉起异步事件池; status=只读查询实时全院态势; stop=停止事件池并释放子进程',
    },
    workspace_root: {
      type: 'string',
      description: '科研工作区根目录绝对路径',
    },
    provider: { type: 'string', description: '可选：显式锁定模型提供商 ID' },
    model: { type: 'string', description: '可选：显式锁定模型 ID' },
    effective_context_window: { type: 'integer', description: '可选：显式上下文窗口上限' },
    goal_and_completion_md: { type: 'string', description: 'Parse 0 课题总目标与完成判据' },
    goal_md: { type: 'string', description: 'goal_and_completion_md 兼容字段' },
    subquestions: { type: 'array', items: { type: 'string' }, description: '必答子题列表，如 ["Q1","Q2"]' },
    required_questions: { type: 'array', items: { type: 'string' }, description: 'subquestions 兼容字段' },
    question_order: { type: 'array', items: { type: 'string' }, description: '可选：跨题推进顺序' },
    initial_instruments: { type: 'array', items: { type: 'object' }, description: '可选：初始科研仪器清单' },
    seed_families: { type: 'array', items: { type: 'object' }, description: '可选：种子方法学派' },
    total_budget: { type: 'object', description: '可选：总预算约束' },
    min_commitment_window_sec: { type: 'integer', description: '可选：最短投入时间窗（秒）' },
    delivery_spec_md: { type: 'string', description: '可选：最终交付规范' },
    shared_inputs_rel_paths: { type: 'array', items: { type: 'string' }, description: '可选：公开输入相对路径' },
    autonomy_mode: { type: 'string', enum: ['WAVE_CONFIRM', 'AUTOPILOT'], description: '可选：自主档位（默认 WAVE_CONFIRM）' },
    max_concurrent_workers: { type: 'integer', description: '可选：并发探索者普通槽位数（不含 +1 人类保留槽）' },
  },
  required: ['action', 'workspace_root'],
})

export function registerOrchestrateTool(ctx, controlService) {
  if (!ctx?.tools || typeof ctx.tools.register !== 'function') {
    return () => {}
  }
  const dispose = ctx.tools.register({
    name: 'greatwall_orchestrate',
    description:
      'GreatWall v0.3 极简编排器冷启动与 Headless 薄入口：仅提供 init / start / status / stop 4 个基础动作；日常科研调度与人机协同请使用独立 Preset「长城 · 科研总控 (gw-chief)」。',
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
