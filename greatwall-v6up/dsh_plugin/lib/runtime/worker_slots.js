/**
 * GreatWall v0.3 探索者槽位管理器（maxWorkers 普通槽 + 1 个固定人类优先保留槽）。
 *
 * 铁律：
 * - 普通后台自主探索分支仅可占用 `maxWorkers` 普通槽；
 * - 人类交还托管的分支（`human_modified=1`）或人类种子分支（`branch_kind='HUMAN_SEEDED'`）
 *   允许动用 `+1` 人类优先保留槽，确保人类刚动过手的研究枝条永远毫秒级优先启动、不被满载池饿死。
 * @module dsh-greatwall-v6up/runtime/worker_slots
 */

export function isHumanPriorityNode(node) {
  if (!node || typeof node !== 'object') return false
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
    if (!node?.node_id) return false
    if (this._active.has(node.node_id)) return false
    if (this.normalActiveCount < this.maxWorkers) return true
    if (isHumanPriorityNode(node) && this.humanReserveActiveCount < this.humanReserveSlots) {
      return true
    }
    return false
  }

  acquire(node) {
    if (!node?.node_id) return null
    if (this._active.has(node.node_id)) return this._active.get(node.node_id).priority
    if (this.normalActiveCount < this.maxWorkers) {
      this._active.set(node.node_id, { priority: 'normal', acquiredAt: Date.now() })
      return 'normal'
    }
    if (isHumanPriorityNode(node) && this.humanReserveActiveCount < this.humanReserveSlots) {
      this._active.set(node.node_id, { priority: 'human_reserve', acquiredAt: Date.now() })
      return 'human_reserve'
    }
    return null
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
