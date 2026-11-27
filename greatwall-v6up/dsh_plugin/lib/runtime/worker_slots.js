/**
 * GreatWall v0.3 探索者槽位管理器（maxWorkers 普通槽 + 1 个固定人类优先保留槽）。
 *
 * 铁律：
 * - 普通后台自主探索分支仅可占用 `maxWorkers` 普通槽；
 * - 持有本次点名派工凭证的分支优先使用人类保留槽。
 * @module dsh-greatwall-v6up/runtime/worker_slots
 */

export function isHumanPriorityNode(node) {
  if (!node || typeof node !== 'object') return false
  if (Object.hasOwn(node, 'operator_named')) return node.operator_named === true
  return (
    String(node.branch_kind || '').toUpperCase() === 'HUMAN_SEEDED' ||
    Boolean(Number(node.human_modified || 0) === 1) ||
    Boolean(node.resumed_after_human)
  )
}

export class WorkerSlotAllocator {
  constructor(maxWorkers = 4, humanReserveSlots = 1) {
    this.maxWorkers = Math.max(1, Number(maxWorkers) || 4)
    this.humanReserveSlots = Math.max(0, Number(humanReserveSlots) ?? 1)
    /** @type {Map<string, { priority: 'normal' | 'human_reserve', acquiredAt: number }>} */
    this._active = new Map()
  }

  setMaxWorkers(n) {
    this.maxWorkers = Math.max(1, Number(n) || this.maxWorkers)
  }

  get totalCapacity() {
    return this.maxWorkers + this.humanReserveSlots
  }

  get activeCount() {
    return this._active.size
  }

  get normalActiveCount() {
    let c = 0
    for (const v of this._active.values()) {
      if (v.priority === 'normal') c += 1
    }
    return c
  }

  get humanReserveActiveCount() {
    let c = 0
    for (const v of this._active.values()) {
      if (v.priority === 'human_reserve') c += 1
    }
    return c
  }

  has(nodeId) {
    return this._active.has(nodeId)
  }

  canAcquire(node) {
    return Boolean(node?.node_id && !this.has(node.node_id) && this.availableTier(node))
  }

  availableTier(node) {
    if (node.slot_tier !== 'normal' && isHumanPriorityNode(node) && this.humanReserveActiveCount < this.humanReserveSlots) {
      return 'human_reserve'
    }
    return node.slot_tier !== 'human_reserve' && this.normalActiveCount < this.maxWorkers ? 'normal' : null
  }

  acquire(node) {
    if (!node?.node_id) return null
    const current = this._active.get(node.node_id)
    if (current) return current.priority
    const priority = this.availableTier(node)
    if (priority) this._active.set(node.node_id, { priority, acquiredAt: Date.now() })
    return priority
  }

  release(nodeId) {
    this._active.delete(nodeId)
  }

  snapshot() {
    return {
      maxWorkers: this.maxWorkers,
      humanReserveSlots: this.humanReserveSlots,
      activeTotal: this._active.size,
      normalActive: this.normalActiveCount,
      humanReserveActive: this.humanReserveActiveCount,
      freeNormalSlots: Math.max(0, this.maxWorkers - this.normalActiveCount),
      freeHumanReserveSlots: Math.max(0, this.humanReserveSlots - this.humanReserveActiveCount),
    }
  }
}
