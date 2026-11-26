/**
 * GreatWall v0.3 单机单实例互斥锁（host.lock，防止同一工作区被双活插件实例并发抢单）。
 * @module dsh-greatwall-v6up/runtime/instance_lock
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

function isProcessAlive(pid) {
  const n = Number(pid)
  if (!Number.isInteger(n) || n <= 0) return false
  try {
    process.kill(n, 0)
    return true
  } catch (err) {
    return err?.code === 'EPERM'
  }
}

export class WorkspaceInstanceLock {
  constructor(lockFilePath, { ownerId = '' } = {}) {
    this.lockFilePath = path.resolve(lockFilePath)
    this.ownerId = ownerId || `dsh_${process.pid}_${crypto.randomUUID().slice(0, 8)}`
    this._acquired = false
  }

  get acquired() {
    return this._acquired
  }

  acquire() {
    if (this._acquired) return { ok: true, ownerId: this.ownerId }
    fs.mkdirSync(path.dirname(this.lockFilePath), { recursive: true })
    const payload = JSON.stringify(
      {
        ownerId: this.ownerId,
        pid: process.pid,
        acquiredAt: new Date().toISOString(),
      },
      null,
      2,
    )

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const fd = fs.openSync(this.lockFilePath, 'wx')
        try {
          fs.writeFileSync(fd, payload, 'utf8')
        } finally {
          fs.closeSync(fd)
        }
        this._acquired = true
        return { ok: true, ownerId: this.ownerId }
      } catch (err) {
        if (err?.code !== 'EEXIST') {
          return { ok: false, error: `无法创建实例锁: ${err?.message || err}` }
        }
        // 检查锁文件内 PID 是否已经死亡（陈旧锁自动回收）
        try {
          const existing = JSON.parse(fs.readFileSync(this.lockFilePath, 'utf8'))
          if (existing?.ownerId === this.ownerId) {
            this._acquired = true
            return { ok: true, ownerId: this.ownerId }
          }
          if (existing?.pid && isProcessAlive(existing.pid)) {
            return {
              ok: false,
              error: `工作区已被另一活跃 GreatWall 实例持有 (pid=${existing.pid}, owner=${existing.ownerId})`,
              holder: existing,
            }
          }
          fs.unlinkSync(this.lockFilePath)
        } catch {
          try {
            fs.unlinkSync(this.lockFilePath)
          } catch {}
        }
      }
    }
    return { ok: false, error: '实例锁抢占竞争失败，请稍后重试' }
  }

  release() {
    if (!this._acquired) return
    this._acquired = false
    try {
      const existing = JSON.parse(fs.readFileSync(this.lockFilePath, 'utf8'))
      if (existing?.ownerId === this.ownerId) {
        fs.unlinkSync(this.lockFilePath)
      }
    } catch {}
  }
}
