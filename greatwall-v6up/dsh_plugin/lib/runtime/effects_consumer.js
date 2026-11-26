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
  }

  /** 拉取并处理一批到期或崩溃过期的 Outbox 副作用。 */
  async drainOnce({ limit = 12, signal = null } = {}) {
    if (this._draining || signal?.aborted) return { claimedCount: 0, handledCount: 0 }
    this._draining = true
    let claimedCount = 0
    let handledCount = 0
    try {
      const claimRes = await this.bridge.control('control_plane/claim_runtime_effects', {
        workspace_root: this.workspaceRoot,
        owner_instance_id: this.ownerInstanceId,
        lease_sec: this.leaseSec,
        limit,
      })
      const items = Array.isArray(claimRes?.data?.claimed) ? claimRes.data.claimed : []
      claimedCount = items.length
      for (const eff of items) {
        if (signal?.aborted) break
        await this._executeSingleEffect(eff, signal)
        handledCount += 1
      }
      return { claimedCount, handledCount }
    } finally {
      this._draining = false
    }
  }

  async _executeSingleEffect(eff, signal) {
    const seq = Number(eff.seq)
    const kind = String(eff.kind || '').toUpperCase()
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
