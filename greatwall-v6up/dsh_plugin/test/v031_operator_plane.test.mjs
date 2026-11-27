import assert from 'node:assert/strict'
import test from 'node:test'
import { RuntimeEffectsConsumer } from '../lib/runtime/effects_consumer.js'
import { watchHumanMandate } from '../lib/sessions/human_mandate.js'
import { readChiefTranscript } from '../lib/sessions/chief_transcript.js'
import { dispatchStage1Step } from '../lib/orchestrator/dispatch_stage1.js'

test('operator Outbox delivers a fast notice before any slow drain finishes', async () => {
  let release
  const slow = new Promise((resolve) => { release = resolve })
  const seen = []
  const done = []
  const claimed = new Set()
  const effects = [
    { seq: 1, kind: 'DRAIN_AND_STOP_NODE', target_id: 'N1', target_type: 'NODE', effect_key: 'drain:N1:g2', target_generation: 2, attempts: 1 },
    { seq: 2, kind: 'NOTIFY_POLICY_CHANGED', target_id: 'N1', target_type: 'NODE', effect_key: 'policy:N1:v2', target_generation: 2, attempts: 1 },
  ]
  const bridge = {
    async control(method, params) {
      if (method.endsWith('/claim_runtime_effects')) {
        const ready = effects.filter((e) => params.kinds.includes(e.kind) && !claimed.has(e.seq))
        ready.forEach((e) => claimed.add(e.seq))
        return { data: { claimed: ready } }
      }
      if (method.endsWith('/complete_runtime_effect')) done.push(params)
      return { ok: true }
    },
  }
  const consumer = new RuntimeEffectsConsumer({
    bridge, workspaceRoot: 'ws', ownerInstanceId: 'host', handlers: {
      DRAIN_AND_STOP_NODE: async () => { seen.push('drain'); await slow },
      NOTIFY_POLICY_CHANGED: async () => { seen.push('notice') },
    },
  })
  await consumer.drainOnce()
  await new Promise(setImmediate)
  assert.ok(seen.includes('drain'))
  assert.ok(seen.includes('notice'))
  assert.deepEqual(done.map((p) => p.seq), [2])
  await consumer.drainOnce()
  release()
  await consumer.whenIdle()
  assert.deepEqual(done.map((p) => p.seq), [2, 1])
  assert.equal(done[1].target_generation, 2)
  assert.equal(done[1].claim_attempt, 1)
})

test('operator mandate is restricted to a live human turn', () => {
  let emit
  const session = { id: 'chief' }
  const gate = watchHumanMandate({ on(event, listener) {
    assert.equal(event, 'session/event')
    emit = listener
    return () => { emit = null }
  } }, session)
  const user = { type: 'user/message', data: { source: { kind: 'user', rpcId: 'ui-1' }, content: [{ type: 'text', text: '暂停 Q1' }] } }
  emit({ id: 'other' }, user)
  emit(session, { type: 'user/message', data: { source: { kind: 'user' }, content: user.data.content } })
  assert.equal(gate.current(), null)
  emit(session, user)
  assert.deepEqual(gate.current(), { rpcId: 'ui-1', text: '暂停 Q1' })
  emit(session, { type: 'turn/end' })
  assert.equal(gate.current(), null)
  emit(session, { type: 'user/message', data: { source: { kind: 'user', origin: 'ui' }, content: [{ type: 'text', text: '只停新派' }] } })
  assert.equal(gate.current()?.text, '只停新派')
  assert.ok(gate.current()?.rpcId?.startsWith('ui-turn:'))
  emit(session, { type: 'turn/end' })
  assert.equal(gate.current(), null)
  gate.dispose()
  assert.equal(emit, null)
})

test('Stage 1 waits for the instrument check without awaiting its model turn', async () => {
  const running = new Set()
  const seen = []
  const port = {
    isGovTaskRunning: (key) => running.has(key),
    isBreakerOpen: () => false,
    recordEvent() {},
    launchGovTask(key) { seen.push(key); running.add(key) },
  }
  const snap = { stage: 'STAGE1_PARSE0', parse0_signed: true, external_literature_count: 0 }
  assert.equal((await dispatchStage1Step(port, snap, null)).handled, true)
  assert.equal((await dispatchStage1Step(port, snap, null)).waitMs, 300)
  assert.deepEqual(seen, ['stage1:works_check'])
})

test('chief transcript pagination keeps surrogate pairs and omits reasoning blocks', async () => {
  const messages = [{ role: 'assistant', content: [{ type: 'text', text: '甲😃乙'.repeat(16) }, { type: 'thinking', text: 'hidden' }] }]
  const ctx = { get: () => ({ get: () => ({ deriveMessages: () => messages }) }) }
  let offset = 0
  let combined = ''
  for (let page = 0; offset !== null && page < 40; page++) {
    const result = await readChiefTranscript(ctx, 'gw-exp-n1', { resource: 'node/n1/transcript', limit: 13, offset })
    const previous = offset
    offset = result.data.next_offset
    if (offset !== null) assert.ok(offset > previous)
    combined += result.data.text
  }
  assert.equal(offset, null)
  assert.equal(combined, '[assistant]\n' + '甲😃乙'.repeat(16))
})

