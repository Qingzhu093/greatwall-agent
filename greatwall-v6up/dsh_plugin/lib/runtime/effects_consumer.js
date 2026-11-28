/**
 * GreatWall v0.3 Outbox (`runtime_effects`) 租约消费者。
 *
 * 核心不变量：
 * 1. 按 `ownerInstanceId` 批量领取 PENDING 或租约已过期的崩溃残留 RUNNING 副作用；
 * 2. 消费期间维持租约续租（默认每 20s 续 60s），严禁并发双执行；
 * 3. `NOTIFY_POLICY_CHANGED` 通过 `agent.inject()` 温和热注入在途探索者，绝不强杀旧口径在途分支；
 * 4. `DRAIN_AND_STOP_NODE` / `CANCEL_NODE_SESSION` 与 `humanTakeover` 联动安全让权；
 * 5. `NOTIFY_CHIEF` 路由至 `ChiefRuntime` 高信噪比事件收件箱。
 * @module dsh-greatwall-v6up/runtime/effects_consumer
 */

const CONTROL_SLOW_KINDS = ['DRAIN_AND_STOP_NODE']
const WORK_SLOW_KINDS = ['REFRESH_LIVING_SURVEY', 'RUN_WAVE_CONFERENCE', 'RUN_INTERNAL_SURVEY']
const SLOW_KINDS = [...CONTROL_SLOW_KINDS, ...WORK_SLOW_KINDS]
const FAST_KINDS = [
  'NOTIFY_CHIEF', 'CANCEL_NODE_SESSION', 'NOTIFY_POLICY_CHANGED',
  'WAKE_BLOCKED_BRANCH', 'SPAWN_PAIR', 'DELIVER_BRANCH_NOTE', 'DELIVER_HANDBACK_RECEIPT',
]

export class RuntimeEffectsConsumer {
  constructor({
    bridge,
    workspaceRoot,
    ownerInstanceId,
    handlers = {},
    leaseSec = 60,
    renewIntervalMs = 20_000,
    telemetry = null,
  }) {
    this.bridge = bridge
    this.workspaceRoot = workspaceRoot
    this.ownerInstanceId = ownerInstanceId
    this.handlers = handlers
    this.leaseSec = Math.max(15, Number(leaseSec) || 60)
    this.renewIntervalMs = Math.max(5_000, Number(renewIntervalMs) || 20_000)
    this.telemetry = telemetry
    this._draining = false
    this._inflight = new Map()
  }

  /** 拉取并处理一批到期或崩溃过期的 Outbox 副作用。暂停态下仅消费快控制与撤回类副作用，不新拉重型 LLM 任务。 */
  async drainOnce({ limit = 12, signal = null, paused = false } = {}) {
    if (this._draining || signal?.aborted) return { claimedCount: 0 }
    this._draining = true
    try {
      const slowKinds = paused ? CONTROL_SLOW_KINDS : SLOW_KINDS
      const [fast, slow] = await Promise.all([
        this._claimLane(FAST_KINDS, limit, signal),
        this._claimLane(slowKinds, 6, signal),
      ])
      return { claimedCount: fast + slow }
    } finally {
      this._draining = false
    }
  }

  async _claimLane(kinds, limit, signal) {
    const running = [...this._inflight.values()].filter((e) => kinds.includes(e.kind)).length
    if (running >= limit) return 0
    const response = await this.bridge.control('control_plane/claim_runtime_effects', {
      workspace_root: this.workspaceRoot, owner_instance_id: this.ownerInstanceId,
      lease_sec: this.leaseSec, limit: limit - running, kinds,
    })
    const items = response?.data?.claimed || []
    for (const effect of items) {
      if (this._inflight.has(effect.seq)) continue
      const prior = [...this._inflight.values()].filter((e) => e.target === effect.target_id && e.type === effect.target_type && [
        'DRAIN_AND_STOP_NODE', 'CANCEL_NODE_SESSION',
      ].includes(e.kind) && ['DRAIN_AND_STOP_NODE', 'CANCEL_NODE_SESSION'].includes(effect.kind))
      const task = Promise.allSettled(prior.map((e) => e.task))
        .then(() => this._executeSingleEffect(effect, signal))
        .finally(() => this._inflight.delete(effect.seq))
      this._inflight.set(effect.seq, { kind: effect.kind, type: effect.target_type, target: effect.target_id, task })
    }
    return items.length
  }

  async whenIdle() {
    await Promise.allSettled([...this._inflight.values()].map((e) => e.task))
  }

  async _executeSingleEffect(eff, signal) {
    const seq = Number(eff.seq)
    const kind = String(eff.kind || '').toUpperCase()
    const fence = eff.effect_key ? {
      effect_key: eff.effect_key, target_generation: eff.target_generation, claim_attempt: eff.attempts,
    } : {}
    const payload = eff.payload && typeof eff.payload === 'object' ? eff.payload : {}
    let renewTimer = setInterval(() => {
      void this.bridge
        .control('control_plane/renew_runtime_effect_lease', {
          workspace_root: this.workspaceRoot,
          seq,
          owner_instance_id: this.ownerInstanceId,
          lease_sec: this.leaseSec,
        })
        .catch(() => {})
    }, this.renewIntervalMs)
    if (typeof renewTimer?.unref === 'function') renewTimer.unref()

    try {
      const handler = this.handlers[kind]
      let externalHandleId = eff.external_handle_id || ''
      if (typeof handler === 'function') {
        const res = await handler(eff, payload, { signal })
        if (res?.externalHandleId) externalHandleId = String(res.externalHandleId)
        if (res?.retryDelaySec > 0) {
          await this.bridge.control('control_plane/complete_runtime_effect', {
            workspace_root: this.workspaceRoot,
            seq,
            owner_instance_id: this.ownerInstanceId,
            ...fence,
            status: 'PENDING',
            retry_delay_sec: Number(res.retryDelaySec),
            last_error: String(res.reason || 'deferred_retry'),
            external_handle_id: externalHandleId,
          })
          return
        }
      }
      await this.bridge.control('control_plane/complete_runtime_effect', {
        workspace_root: this.workspaceRoot,
        seq,
        owner_instance_id: this.ownerInstanceId,
        ...fence,
        status: 'DONE',
        external_handle_id: externalHandleId,
      })
      this.telemetry?.recordEvent?.('runtime_effect_done', { seq, kind, targetId: eff.target_id })
    } catch (err) {
      const msg = String(err?.message || err)
      const attempts = Number(eff.attempts || 1)
      const shouldRetry = !signal?.aborted && attempts < 3
      await this.bridge
        .control('control_plane/complete_runtime_effect', {
          workspace_root: this.workspaceRoot,
          seq,
          owner_instance_id: this.ownerInstanceId,
          ...fence,
          status: shouldRetry ? 'PENDING' : 'FAILED',
          retry_delay_sec: shouldRetry ? 15 * attempts : 0,
          last_error: msg.slice(0, 600),
        })
        .catch(() => {})
      this.telemetry?.recordEvent?.('runtime_effect_error', { seq, kind, targetId: eff.target_id, error: msg })
    } finally {
      clearInterval(renewTimer)
      renewTimer = null
    }
  }
}

export async function runInternalSurvey(spawnAndRunAgent, effect, { survey_req_id: surveyId }, { signal }) {
  if (effect.survey_status === 'FULFILLED') return
  const result = await spawnAndRunAgent({
    role: 'library_chronicler', questionId: effect.target_id,
    uiLabel: `[院内专题综述] ${effect.target_id} ${surveyId}`,
    shortTransaction: true, archiveOnComplete: true, signal,
    prompt: `请调用 get_internal_survey_task(survey_req_id="${surveyId}")，按需用 get_chronicler_snapshot 精读。只综合证据、逐段标明编号、保留适用条件、不替探索者下达路线指令，调用 publish_internal_survey_report 发布 200–4000 字报告。`,
  })
  if (!result.turnSignals.some(({ toolName, receipt }) => toolName === 'publish_internal_survey_report' && receipt.ok)) {
    throw new Error(`专题综述 ${surveyId} 会话结束时未提交报告`)
  }
  return { externalHandleId: result.sessionId }
}
