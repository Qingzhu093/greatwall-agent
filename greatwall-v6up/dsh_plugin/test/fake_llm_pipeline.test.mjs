/**
 * 长城 V6-Up (v3.0) L2 零费用假模型全链路沙盘测试（秒级闭环，驱动真实核心组件）：
 *
 * 真实组件：
 * - GreatwallOrchestrator + AgentSessionHost + PairLifecycle + Clock & TurnGap + ReadIsolatedSandbox
 * - GreatwallMcpBridge -> 真实 Python stdio MCP Server -> 真实 SQLite WAL (17表 + 3触发器 + 32窄工具)
 * - 真实 Worktree 目录、公开 inputs/ 挂载、空白盲审沙箱与 final_delivery/ 五件套导出
 *
 * 仅将 LLM 文本/工具调用决策替换为确定性 Scripted Stub，零 API 费用、零网络依赖，按数据库结构化结果强断言！
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { GreatwallMcpBridge } from '../lib/mcp_bridge.js'
import { GreatwallOrchestrator } from '../lib/orchestrator.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CORE_PYTHON_ROOT = path.resolve(__dirname, '..', '..', 'core_python')

/**
 * 轻量真实接口 Stub DSH Context：
 * 完整支持 ctx.agents.create / agentCtx.tools.register / agentCtx.on('tools/execute' | 'tools/result' | 'agent/pre-step')
 * / ctx.sessionProjections.snapshot(['contextPressure'])，确保真实沙箱 Guard 与真实实时时钟钩子 100% 生效！
 */
function createScriptedDshContext({ modelWindow = 272_000, onAgentTurn }) {
  const sessions = new Map()
  const pressureBySession = new Map()
  const workingDirBySession = new Map()

  const ctx = {
    sessions,
    workingDirectory: {
      async set(agentOrSession, dir) {
        const id = agentOrSession?.session?.id || agentOrSession?.id
        if (id && dir) workingDirBySession.set(id, dir)
      },
      get(agentOrSession) {
        const id = agentOrSession?.session?.id || agentOrSession?.id
        return (id && workingDirBySession.get(id)) || agentOrSession?.session?.header?.cwd || ''
      },
    },
    llm: {
      async resolveModelInfo() {
        return { contextWindow: modelWindow, reasoning: { efforts: [{ id: 'low' }, { id: 'medium' }, { id: 'high' }] } }
      },
    },
    sessionProjections: {
      snapshot(session) {
        const p = pressureBySession.get(session?.id) || { projectedTokens: 0, contextWindow: modelWindow }
        return { values: { contextPressure: p } }
      },
    },
    agents: {
      async create(createOpts) {
        const sid = createOpts.sessionId
        const registeredTools = new Map()
        const toolGuards = []
        const hooks = {
          'tools/execute': [],
          'tools/result': [],
          'agent/pre-step': [],
          'system-prompt/assemble': [],
        }
        const messages = []
        const events = []
        let cancelled = false
        let currentIdlePromise = Promise.resolve()

        // 预置最小原生文件读写工具，使真实沙箱 Guard 拦截可实测触发
        const nativeRead = {
          name: 'read',
          execute: async (args) => ({ ok: true, content: fs.readFileSync(args.file_path, 'utf8') }),
        }
        const nativeWrite = {
          name: 'write',
          execute: async (args) => {
            fs.mkdirSync(path.dirname(args.file_path), { recursive: true })
            fs.writeFileSync(args.file_path, String(args.content || ''), 'utf8')
            return { ok: true }
          },
        }
        const nativeShellName = process.platform === 'win32' ? 'pwsh' : 'bash'
        const nativeShell = {
          name: nativeShellName,
          execute: async (args) => ({ ok: true, stdout: `ran:${args.command}` }),
        }
        for (const t of [nativeRead, nativeWrite, nativeShell]) {
          registeredTools.set(t.name, t)
        }

        const session = {
          id: sid,
          header: { cwd: createOpts.meta?.cwd || '' },
          snapshotEvents: () => [...events],
          deriveMessages: () => [...messages],
          append: (type, data) => events.push({ type, data }),
        }
        sessions.set(sid, session)
        pressureBySession.set(sid, { projectedTokens: 0, contextWindow: modelWindow })

        const agent = {
          id: sid,
          options: createOpts.agentOptions || {},
          session,
          cancel(reason) {
            assert.ok(['user', 'parent', 'disposed', 'hook'].includes(reason.kind), 'invalid DSH cancel cause')
            if (reason.kind === 'hook') assert.equal(typeof reason.reason, 'string')
            cancelled = true
            events.push({ type: 'turn/end', data: { reason: { kind: 'aborted', reason } } })
          },
          followup(msg) {
            const promptText = msg?.content?.map((c) => c.text).join('\n') || ''
            messages.push({ role: 'user', content: promptText })
            cancelled = false

            const runTool = async (name, args) => {
              const tool = registeredTools.get(name)
              if (!tool) return { ok: false, error: `TOOL_NOT_REGISTERED:${name}` }
              const execCtx = {
                name,
                arguments: args,
                agent,
                concluded: false,
                concludeTurn() {
                  this.concluded = true
                },
              }
              // 1. 先穿过全部真实 agentCtx.tools.guard(fn)（即真实 installRoleSandboxGuard 双向沙箱）
              for (const gfn of toolGuards) {
                const denial = await gfn({ name, arguments: args })
                if (denial) {
                  return { ok: false, error: typeof denial === 'string' ? denial : JSON.stringify(denial) }
                }
              }
              // 2. 再依次穿过全部真实 tools/execute 中间件
              let idx = 0
              const dispatchExec = async () => {
                if (idx < hooks['tools/execute'].length) {
                  const fn = hooks['tools/execute'][idx++]
                  return fn(execCtx, dispatchExec)
                }
                return tool.execute(args, execCtx)
              }
              let result
              try {
                result = await dispatchExec()
              } catch (err) {
                result = { ok: false, error: String(err?.message || err) }
              }
              for (const fn of hooks['tools/result']) {
                try {
                  await fn({ name, arguments: args, result })
                } catch {}
              }
              return result
            }

            const runPreStep = async () => {
              let idx = 0
              const next = async () => {
                if (idx < hooks['agent/pre-step'].length) {
                  const fn = hooks['agent/pre-step'][idx++]
                  return fn({}, next)
                }
              }
              await next()
            }

            currentIdlePromise = (async () => {
              const api = {
                sessionId: sid,
                cwd: workingDirBySession.get(sid) || createOpts.meta?.cwd || '',
                agentOptions: createOpts.agentOptions || {},
                promptText,
                callTool: runTool,
                triggerPreStep: runPreStep,
                setPressureTokens: (tok) => {
                  pressureBySession.set(sid, { projectedTokens: tok, contextWindow: modelWindow })
                },
                isCancelled: () => cancelled,
              }
              const reply = await onAgentTurn(api)
              if (reply) {
                messages.push({ role: 'assistant', content: String(reply) })
              }
              if (!cancelled) {
                events.push({ type: 'turn/end', data: { reason: { kind: 'stop' } } })
              }
            })()
          },
          whenIdle() {
            return currentIdlePromise
          },
        }

        const agentCtx = {
          tools: {
            presentAs: () => () => {},
            schemas: () => [...registeredTools.values()].map((t) => ({ name: t.name })),
            restrict({ allow, deny } = {}) {
              if (Array.isArray(deny)) {
                for (const d of deny) registeredTools.delete(d)
              }
              if (Array.isArray(allow)) {
                const allowSet = new Set(allow)
                for (const k of [...registeredTools.keys()]) {
                  if (!allowSet.has(k)) registeredTools.delete(k)
                }
              }
            },
            register(def) {
              registeredTools.set(def.name, def)
              return () => registeredTools.delete(def.name)
            },
            guard(fn) {
              toolGuards.push(fn)
              return () => {
                const i = toolGuards.indexOf(fn)
                if (i >= 0) toolGuards.splice(i, 1)
              }
            },
          },
          systemPrompt: {
            section: () => () => {},
            context: () => () => {},
          },
          on(evName, fn) {
            if (hooks[evName]) hooks[evName].push(fn)
            return () => {
              if (!hooks[evName]) return
              const i = hooks[evName].indexOf(fn)
              if (i >= 0) hooks[evName].splice(i, 1)
            }
          },
        }

        if (typeof createOpts.setup === 'function') {
          await createOpts.setup(agentCtx, agent)
        }

        return {
          agent,
          async dispose() {
            sessions.delete(sid)
            pressureBySession.delete(sid)
          },
        }
      },
    },
  }
  return ctx
}

test('L2 剧本 1：零费用假模型全链路沙盘（272k 自适应窗口 + 公开 inputs/ + 双向沙箱 + 盲审终核 -> CLOSED_VERIFIED）', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_l2_e2e_'))
  const ws = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'plugin_data')
  fs.mkdirSync(path.join(ws, 'problem_pack'), { recursive: true })
  fs.writeFileSync(path.join(ws, 'problem_pack', 'problem.md'), '# 2026 测试课题：最小覆盖圆上界证明\n', 'utf8')
  fs.mkdirSync(path.join(ws, '_hidden_calibrations'), { recursive: true })
  fs.writeFileSync(path.join(ws, '_hidden_calibrations', 'secret.json'), '{"secret":true}', 'utf8')

  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: ws, dataDir })
  const auditTrail = {
    worksStage1Called: 0,
    explorerReadonlyWriteBlocked: false,
    explorerHiddenReadBlocked: false,
    verifierDbReadBlocked: false,
    verifierSawPublicInput: false,
    explorerSawPublicInput: false,
    companionSessionIds: new Set(),
    boundModelsSeen: new Set(),
  }

  let expStep = 0
  let createdNodeId = ''
  let createdBranchId = ''

  const ctx = createScriptedDshContext({
    modelWindow: 272_000,
    async onAgentTurn(api) {
      auditTrail.boundModelsSeen.add(`${api.agentOptions.provider}/${api.agentOptions.model}`)
      const sid = api.sessionId
      if (process.env.DEBUG_L2) console.error('[L2-1]', sid, api.promptText.slice(0, 60))

      // 1) 工造司：Stage 1 固定统一核查确认
      if (sid.startsWith('gw_works_engineer_')) {
        auditTrail.worksStage1Called += 1
        await api.callTool('get_works_engineering_queue', { question_id: 'ALL' })
        return '已确认无初始仪器需求，Stage 1 核查完成。'
      }

      // 2a) 对外文献采编：Stage 1 建外藏 [R001]
      if (sid.startsWith('gw_external_surveyor_')) {
        const pub = await api.callTool('publish_external_literature_card', {
          outcome: 'CARD_PUBLISHED',
          ref_id: 'R001',
          question_id: 'Q1',
          title: 'Jung 覆盖圆经典定理参考卡',
          abstract_md: '欧氏平面上任意直径为 d 的有限点集，其最小覆盖圆半径不超过 d/sqrt(3)，当且仅当三个支撑点构成正三角形时取等。本卡为外部参考先验。',
          exact_preconditions_md: '欧氏平面有限非空点集',
          formulas_or_operators_md: 'R_min <= d / sqrt(3)',
          read_depth: 'full_text',
          support_scope: 'DIRECT_PROOF_OR_EXACT_MEASUREMENT',
          source_citation: 'Jung (1901)',
        })
        assert.equal(pub.ok, true, JSON.stringify(pub))
        return '外藏卡 R001 已入库。'
      }

      // 2b) 对内综述与终稿官：Stage 3 导出五件套与外部不可变冻结目录
      if (sid.startsWith('gw_library_chronicler_')) {
        const l3s = ['L3-001']
        const exp = await api.callTool('export_stage3_final_delivery', {
          delivery_mode: 'FULL',
          formal_paper_md: '# 最小覆盖圆上界完整证明报告\n\n基于经独立空白沙箱实测核验的定理 L3-001，我们在欧氏平面任意有限点集上严格证明了 Jung 上界并附带可复现验证脚本。\n',
          selected_l3_ids_by_question: { Q1: l3s },
          remaining_gaps_by_question: { Q1: '无剩余断点，Q1 已全部闭合。' },
          reproduction_candidate_nodes: [createdNodeId],
        })
        assert.equal(exp.ok, true, JSON.stringify(exp))
        return 'Stage 3 五件套已导出并冻结。'
      }

      // 3) 后勤总管：Stage 1 开枝 / Stage 2 分诊送盲审
      if (sid.startsWith('gw_logistics_coordinator_')) {
        const dash = await api.callTool('get_logistics_dashboard', { question_id: 'ALL' })
        if ((dash?.data?.awaiting_triage || []).length > 0) {
          for (const tn of dash.data.awaiting_triage) {
            const tr = await api.callTool('triage_node', {
              node_id: tn.node_id,
              assigned_family_id: 'fam_q1_jung',
              triage_level: 'LEVEL_1',
              action: 'SUBMIT_BLIND_REVIEW',
              rationale: '解析证明与复核脚本完整齐备，送独立空白沙箱盲审。',
            })
            assert.equal(tr.ok, true, JSON.stringify(tr))
          }
          return '分诊并送盲审完成。'
        }
        await api.callTool('register_method_family', {
          question_id: 'Q1',
          family_id: 'fam_q1_jung',
          mechanism_signature: 'Helly定理+正三角形支撑点极值分析',
          orthogonal_contrast: '对比纯数值网格逼近',
        })
        const fb = await api.callTool('fork_branch', {
          question_id: 'Q1',
          fork_mode: 'orthogonal',
          target_family_id: 'fam_q1_jung',
        })
        assert.equal(fb.ok, true, JSON.stringify(fb))
        createdNodeId = fb.data.node_id
        createdBranchId = fb.data.branch_id
        return '初始学派与分支已建立。'
      }

      // 4) 监察委员会：Stage 1 Parse0 门禁 / Stage 2 心跳 / Stage 3 联合终签
      if (sid.startsWith('gw_supervisory_committee_')) {
        await api.callTool('get_supervisory_audit_snapshot', {})
        if (api.promptText.includes('PARSE0_GATE')) {
          const r = await api.callTool('record_compliance_check', {
            stage: 'PARSE0_GATE',
            status: 'PASSED',
            blocking_questions: [],
            notes: 'Parse 0 全部就绪，放行进入 Stage 2。',
          })
          assert.equal(r.ok, true, JSON.stringify(r))
        } else if (api.promptText.includes('CLOSURE_GATE')) {
          const r = await api.callTool('record_compliance_check', {
            stage: 'CLOSURE_GATE',
            status: 'PASSED',
            blocking_questions: [],
            notes: '盲审终核与哈希匹配校验通过，晋升 CLOSED_VERIFIED。',
          })
          assert.equal(r.ok, true, JSON.stringify(r))
        } else {
          await api.callTool('record_compliance_check', {
            stage: 'STAGE2_HEARTBEAT',
            status: 'PASSED',
            blocking_questions: [],
            notes: 'Stage 2 心跳审计正常。',
          })
        }
        return '监察委记录完成。'
      }

      // 5) 单节点确定性会话 ID 伴随：PRE_SPAWN -> REFLECT_37 -> HANDOFF_70
      if (sid.startsWith('gw-comp-') || sid.startsWith('gw_comp_')) {
        auditTrail.companionSessionIds.add(sid)
        if (api.promptText.includes('阶段 PRE_SPAWN')) {
          await api.callTool('get_companion_context', { branch_id: createdBranchId, node_id: createdNodeId, mode: 'PRE_SPAWN' })
          const sb = await api.callTool('save_lineage_briefing', {
            branch_id: createdBranchId,
            node_id: createdNodeId,
            sec1_mechanism: '用 Helly 定理归约到三点支撑情形。',
            sec2_verified_baseline: '外藏 R001 已就绪。',
            sec3_bottleneck: '需构造数值复核脚本并核验钝角/锐角边界。',
            sec4_dead_ends: '暂无历史死胡同。',
            sec5_immediate_will: '写出 proof_check.py 并验证极值三角形。',
          })
          assert.equal(sb.ok, true, JSON.stringify(sb))
          return '行前看板已落库。'
        }
        if (api.promptText.includes('阶段 REFLECT_37')) {
          const r37 = await api.callTool('get_companion_context', { branch_id: createdBranchId, node_id: createdNodeId, mode: 'REFLECT_37' })
          assert.equal(r37.ok, true, JSON.stringify(r37))
          assert.equal(r37.state_snapshot.effective_context_window, 272_000, 'Python 与 JS 必须共享 272k 有效窗口')
          return '诊断：请核验锐角三角形支撑边界是否无遗漏（<=300字）？'
        }
        if (api.promptText.includes('探索者 Round 1')) {
          const unl = await api.callTool('record_reflection_and_unlock_pull', {
            node_id: createdNodeId,
            selected_categories: ['C08_ATTRACTOR_TRAP'],
            turns: [{ question: '钝角情形是否已覆盖？', answer: '已用直径圆直接覆盖钝角情形，仅锐角需 Jung 上界。' }],
            verdict_3state: 'SUFFICIENT_EVIDENCE',
          })
          assert.equal(unl.ok, true, JSON.stringify(unl))
          return '37% 元反思完成并已解锁内藏。'
        }
        if (api.promptText.includes('阶段 HANDOFF_70')) {
          await api.callTool('get_companion_context', { branch_id: createdBranchId, node_id: createdNodeId, mode: 'HANDOFF_70' })
          const ho = await api.callTool('submit_node_handoff', {
            node_id: createdNodeId,
            branch_id: createdBranchId,
            question_id: 'Q1',
            mechanism_summary: 'Helly三点归约+锐钝角分情况Jung上界证明',
            evidence_grade: 'ARTIFACT_ONLY',
            column_a_facts_md: 'A栏：利用 Helly 定理将平面有限点集最小覆盖圆归约至至多三个支撑点；钝角情形半径为 d/2，锐角情形由正弦定理证得 R <= d/sqrt(3)，并附可运行脚本 proof_check.py 复核。',
            column_b_hypothesis_md: 'B栏：已完整覆盖 Q1 全部情形。',
            will_md: '建议直接送盲审验证 proof_check.py。',
            obs_ids: [],
            dead_ends: [],
            candidate_rel_path: 'proof_check.py',
            is_empty_crash: false,
            holiday_bet_outcome: { outcome: 'UNTESTED', note_md: '本班完成了证明，另一个经验假设留待测试。' },
          })
          assert.equal(ho.ok, true, JSON.stringify(ho))
          return '70% 交接单已落库。'
        }
      }

      // 6) 探索者：验证公开 inputs/ 可读 + _hidden 越界被拦 + 272k 窗口 37% -> 70% + 70% 只读禁写
      if (sid.startsWith('gw-exp-') || sid.startsWith('gw_exp_')) {
        if (api.promptText.includes('52% 暂停编程反思')) {
          for (const [name, args] of [
            ['write', { file_path: path.join(api.cwd, 'holiday_probe.py'), content: 'x=1' }],
            [process.platform === 'win32' ? 'pwsh' : 'bash', { command: 'echo example' }],
            ['run_isolated_eval', {}],
          ]) {
            const blocked = await api.callTool(name, args)
            assert.match(blocked.error, /52% 夜科学/)
          }
          const bet = await api.callTool('submit_holiday_bet', {
            node_id: createdNodeId,
            anomaly_or_analogy_md: '锐角退化边界的形状变化近似两个极值条件交换主导地位的现象，值得作配对比较。',
            testable_hypothesis_md: '在固定最长边的三角形族上，角度越过直角阈值时最优支撑点数发生改变。',
            falsification_experiment_md: '对直角阈值两侧生成等尺度配对样本，若得到同样的支撑点数即可否定假设。',
          })
          assert.equal(bet.ok, true, JSON.stringify(bet))
          const resumedWrite = await api.callTool('write', { file_path: path.join(api.cwd, 'holiday_probe.py'), content: 'x=1' })
          assert.equal(resumedWrite.ok, true, JSON.stringify(resumedWrite))
          auditTrail.holidayUnlockedInTurn = true
          return '已记录可证伪赌注并恢复工具。'
        }
        if (api.promptText.includes('70% 清醒收官')) {
          // 实测 70% 只读态尝试写文件被真实沙箱 Guard 拦截！
          const badW = await api.callTool('write', { file_path: path.join(api.cwd, 'forbidden_edit.py'), content: 'x=1' })
          if (!badW?.ok && String(badW?.error || '').includes('只读态')) {
            auditTrail.explorerReadonlyWriteBlocked = true
          }
          return '亲笔遗嘱：proof_check.py 与完整分情况证明已完成，请交伴随核验落库。READY_FOR_HANDOFF'
        }
        if (api.promptText.includes('伴随助手 37% 专家诊断')) {
          return '钝角三角形外接圆直接以最长边为直径，锐角情形正弦定理给出紧上界 d/sqrt(3)。'
        }
        expStep += 1
        if (expStep === 1) {
          // 实测：读工作树内挂载的公开 inputs/problem_pack/problem.md 成功
          const pubRead = await api.callTool('read', { file_path: path.join(api.cwd, 'inputs', 'problem_pack', 'problem.md') })
          if (pubRead?.ok && String(pubRead.content || '').includes('最小覆盖圆')) {
            auditTrail.explorerSawPublicInput = true
          }
          // 实测：越界读 _hidden_calibrations/secret.json 必须被真实双向沙箱拦截！
          const secRead = await api.callTool('read', { file_path: path.join(ws, '_hidden_calibrations', 'secret.json') })
          if (!secRead?.ok && String(secRead?.error || '').includes('SANDBOX_VIOLATION')) {
            auditTrail.explorerHiddenReadBlocked = true
          }
          // 写出候选验证脚本
          await api.callTool('write', {
            file_path: path.join(api.cwd, 'proof_check.py'),
            content: 'import math\nassert abs(1/math.sqrt(3) - 0.577350269) < 1e-6\nprint("OK")\n',
          })
          // 将上下文推进至 102,000 / 272,000 = 37.5%（触发 REFLECT_37！）
          api.setPressureTokens(102_000)
          await api.triggerPreStep()
          return '已推进至 37.5% (102k/272k)，等待反思。'
        }
        // 先跨过停码水位，恢复后再进入清醒交班。
        await api.callTool('query_library_catalog', { node_id: createdNodeId, question_id: 'Q1', scope: 'ALL', keyword: 'Jung' })
        if (expStep === 2) {
          api.setPressureTokens(142_000)
          await api.triggerPreStep()
          return '已跨过 52% 水位。'
        }
        api.setPressureTokens(191_000)
        await api.triggerPreStep()
        return '已推进至 70.2% (191k/272k)，准备清醒收官。'
      }

      // 7) 图书馆盲审官：空白沙箱 Stage 1 + Stage 2 与 Stage 3 一步原子终签
      if (sid.startsWith('gw_ver_') || sid.startsWith('gw_library_verifier_')) {
        if (api.promptText.includes('STAGE3_FINAL_AUDIT:')) {
          const m = api.promptText.match(/STAGE3_FINAL_AUDIT:[a-zA-Z0-9_-]+/)
          const auditRevId = m ? m[0] : ''
          const ub = await api.callTool('get_unblinded_manuscript_and_peers', { review_id: auditRevId })
          assert.equal(ub.ok, true, JSON.stringify(ub))
          const sv = await api.callTool('submit_stage2_unblind_verdict', {
            review_id: auditRevId,
            final_verdict: 'ACCEPT',
          novelty_score: 8, significance_score: 8,
            title: 'Stage 3 终核通过',
            abstract_md: '已对照 verified_l3_scopes.json 核验五件套报告与复现脚本一致，无任何边界夸大。',
          })
          assert.equal(sv.ok, true, JSON.stringify(sv))
          return 'Stage 3 终核已落签 ACCEPT。'
        }
        const m = api.promptText.match(/rev_\d+/)
        const revId = m ? m[0] : 'rev_001'
        const bm = await api.callTool('get_blind_manuscript', { review_id: revId })
        assert.equal(bm.ok, true, JSON.stringify(bm))
        // 实测：盲审沙箱内挂载了只读 inputs/problem_pack/problem.md
        const sbRead = await api.callTool('read', { file_path: path.join(bm.data.blind_sandbox_abs_path, 'inputs', 'problem_pack', 'problem.md') })
        if (sbRead?.ok && String(sbRead.content || '').includes('最小覆盖圆')) {
          auditTrail.verifierSawPublicInput = true
        }
        // 实测：盲审官尝试读 greatwall.db 必须被真实沙箱 Guard 拦截！
        const dbAttempt = await api.callTool('read', { file_path: path.join(dataDir, 'greatwall.db') })
        if (!dbAttempt?.ok && String(dbAttempt?.error || '').includes('SANDBOX_VIOLATION')) {
          auditTrail.verifierDbReadBlocked = true
        }
        const s1 = await api.callTool('submit_stage1_blind_ledger', {
          review_id: revId,
          question_id: 'Q1',
          ledger_items: [{ claim: 'Jung 上界成立', evidence_location_and_quote: 'proof_check.py 实跑通过', is_verified: true }],
          stage1_verdict: 'PASS',
          rigor_score: 8,
        })
        assert.equal(s1.ok, true, JSON.stringify(s1))
        const ub = await api.callTool('get_unblinded_manuscript_and_peers', { review_id: revId })
        assert.equal(ub.ok, true, JSON.stringify(ub))
        const s2 = await api.callTool('submit_stage2_unblind_verdict', {
          review_id: revId,
          final_verdict: 'ACCEPT',
          novelty_score: 8, significance_score: 8,
          l3_entry_kind: 'POS_THEOREM',
          goal_coverage: 'FULL_GOAL',
          is_equivalent_reduction: false,
          title: '欧氏平面最小覆盖圆 Jung 上界定理',
          abstract_md: '经空白盲审沙箱独立核验，证明了欧氏平面上任意直径为 d 的有限点集其最小覆盖圆半径不超过 d/sqrt(3) 且脚本验证通过。',
          exact_verified_scope_md: '欧氏平面 R^2 上所有直径有限的非空有限点集（spec_revision=v0）',
        })
        assert.equal(s2.ok, true, JSON.stringify(s2))
        return '盲审 Stage 1 + 2 终判 ACCEPT 入库 L3。'
      }

      return 'ok'
    },
  })

  try {
    const initRes = await bridge.control('control_plane/init_parse0', {
      workspace_root: ws,
      goal_and_completion_md: '证明平面有限点集最小覆盖圆半径 Jung 上界',
      subquestions: ['Q1'],
      initial_instruments: [],
    })
    assert.equal(initRes.ok, true)

    const orch = new GreatwallOrchestrator({
      ctx,
      bridge,
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: ws,
      dataDir,
      protectedDirs: [dataDir],
      defaultAgentOptions: { provider: 'deepseek-account', model: 'deepseek-flash' },
    })
    // 加速测试心跳轮询，无需空等 250ms
    orch._waitWakeOrTimeout = async () => new Promise((r) => setTimeout(r, 15))
    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(new Error('L2_TEST_TIMEOUT')), 4000)
    const runRes = await orch.runUntilClosed({ maxConcurrentWorkers: 2, signal: ac.signal }).finally(() => clearTimeout(timer))
    assert.equal(
      runRes.closed,
      true,
      `全链路应推进至 CLOSED_VERIFIED，实得 stage=${runRes.snapshot?.stage}, events=${JSON.stringify(orch.telemetry.state.recentEvents.slice(-8))}`,
    )
    assert.equal(runRes.snapshot.stage, 'CLOSED_VERIFIED')
    assert.equal(runRes.snapshot.closure_state.status, 'CLOSED_VERIFIED')
    assert.equal(runRes.snapshot.stage1_works_checked, true, 'Stage 1 必须完成工造司统一核查')
    assert.equal(auditTrail.worksStage1Called, 1, 'Stage 1 工造司应恰好拉起核查 1 次')
    assert.equal(auditTrail.companionSessionIds.size, 1, '单节点伴随 PRE_SPAWN->37%->70% 必须复用同 1 个 sessionId')
    assert.equal(auditTrail.explorerSawPublicInput, true, '探索者必须开箱只读 worktree/inputs/ 公开题面')
    assert.equal(auditTrail.verifierSawPublicInput, true, '盲审官必须开箱只读 blind_sandbox/inputs/ 公开题面')
    assert.equal(auditTrail.explorerHiddenReadBlocked, true, '探索者越界读 _hidden_calibrations 必须被双向沙箱阻断')
    assert.equal(auditTrail.verifierDbReadBlocked, true, '盲审官越界读 greatwall.db 必须被双向沙箱阻断')
    assert.equal(auditTrail.explorerReadonlyWriteBlocked, true, '70% 收官只读态探索者写文件必须被 Guard 阻断')
    assert.equal(auditTrail.holidayUnlockedInTurn, true, '52% 赌注落库后同一回合必须立即恢复写入')
    assert.deepEqual([...auditTrail.boundModelsSeen], ['deepseek-account/deepseek-flash'], '全链路全部子会话必须严格锁死绑定模型')
    assert.ok(fs.existsSync(path.join(ws, 'final_delivery', '01_formal_report.md')), '必须生成 Stage 3 交付报告')
    await orch.disposeAll()
  } finally {
    await bridge.dispose()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})

test('L2 剧本 2：第五轮全故障回归（缺绑定拒启、无解查新不造伪卡、单待办熔断不连坐健康工单、abortNode 1轮退槽与 rulings 升级）', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'gw_l2_reg_'))
  const ws = path.join(tmpRoot, 'ws')
  const dataDir = path.join(tmpRoot, 'plugin_data')
  fs.mkdirSync(ws, { recursive: true })
  const bridge = new GreatwallMcpBridge({ corePythonRoot: CORE_PYTHON_ROOT, workspaceRoot: ws, dataDir })

  try {
    // 1. 验证 Orchestrator 彻底移除了 intervene() 且无绑定必拒启 MISSING_MODEL_BINDING
    const unBoundOrch = new GreatwallOrchestrator({
      ctx: {},
      bridge,
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: ws,
      dataDir,
    })
    assert.equal(typeof unBoundOrch.intervene, 'undefined', '运行时 steer/intervene 必须彻底移除')
    const blocked = await unBoundOrch.startBackground()
    assert.equal(blocked.started, false)
    assert.equal(blocked.blocked, 'MISSING_MODEL_BINDING')

    // 2. 初始化数据库并手工构造：
    //    - 1 条无解查新单（期望 UNAVAILABLE_REPORT 结案且零伪 [R###] 卡）
    //    - 2 条工造司 OPEN 工单：tkt_stuck（工造司不解决，连续 2 次后应单条熔断）+ tkt_healthy（第 1 次就调 resolve_works_ticket 结案，绝不被连坐！）
    await bridge.control('control_plane/init_parse0', {
      workspace_root: ws,
      goal_and_completion_md: '第五轮全故障回归沙盘',
      subquestions: ['Q1'],
      stage: 'STAGE2_EVOLVE',
    })
    await bridge.callTool('register_method_family', {
      question_id: 'Q1', family_id: 'fam_r5', mechanism_signature: 'sig', orthogonal_contrast: 'ctrl',
    }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 'log_init' })
    const fb = await bridge.callTool('fork_branch', {
      question_id: 'Q1', fork_mode: 'orthogonal', target_family_id: 'fam_r5',
    }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 'log_init' })
    const nid = fb.data.node_id
    const bid = fb.data.branch_id

    // 制造 1 条查新请求 + 2 条工造司痛点工单（通过 2 个已完成节点的 handoff 写入）
    const sreq = await bridge.callTool('request_literature_survey', {
      node_id: nid, question_id: 'Q1', topic_query: '不存在的私密数据包', reason: '测无解查新',
    }, { workspaceRoot: ws, role: 'explorer', sessionId: 'exp_init' })
    const reqId = sreq.data.req_id

    const fbA = await bridge.callTool('fork_branch', { question_id: 'Q1', fork_mode: 'lateral', target_family_id: 'fam_r5' }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 'log_init' })
    const fbB = await bridge.callTool('fork_branch', { question_id: 'Q1', fork_mode: 'lateral', target_family_id: 'fam_r5' }, { workspaceRoot: ws, role: 'logistics_coordinator', sessionId: 'log_init' })
    await bridge.callTool('submit_node_handoff', {
      node_id: fbA.data.node_id, branch_id: fbA.data.branch_id, question_id: 'Q1',
      mechanism_summary: '测试工单A', evidence_grade: 'ARTIFACT_ONLY',
      column_a_facts_md: 'A栏内容用于生成工单A', column_b_hypothesis_md: 'B栏', will_md: '遗嘱',
      obs_ids: [], dead_ends: [], is_empty_crash: false, tool_pain_point: 'HEALTHY_TICKET_CAN_RESOLVE',
    }, { workspaceRoot: ws, role: 'lineage_companion', sessionId: 'cA' })
    await bridge.callTool('submit_node_handoff', {
      node_id: fbB.data.node_id, branch_id: fbB.data.branch_id, question_id: 'Q1',
      mechanism_summary: '测试工单B', evidence_grade: 'ARTIFACT_ONLY',
      column_a_facts_md: 'A栏内容用于生成工单B', column_b_hypothesis_md: 'B栏', will_md: '遗嘱',
      obs_ids: [], dead_ends: [], is_empty_crash: false, tool_pain_point: 'STUCK_TICKET_NO_PROGRESS',
    }, { workspaceRoot: ws, role: 'lineage_companion', sessionId: 'cB' })

    // 给主节点写看板使其可直接运行，并故意在探索者跑 1 轮后执行 abortNode
    const brfRes = await bridge.callTool('save_lineage_briefing', {
      branch_id: bid, node_id: nid,
      sec1_mechanism: '回归测试核心机制',
      sec2_verified_baseline: '基线就绪',
      sec3_bottleneck: '当前瓶颈',
      sec4_dead_ends: '暂无死胡同',
      sec5_immediate_will: '首轮验证后待外部中止',
    }, { workspaceRoot: ws, role: 'lineage_companion', sessionId: 'cMain' })
    assert.equal(brfRes.ok, true, JSON.stringify(brfRes))

    let worksRuns = 0
    let worksRunsAfterResume = 0
    let resumedAfterAbort = false
    let surveyorRuns = 0
    let expTurns = 0
    let orchRef = null

    const ctx = createScriptedDshContext({
      modelWindow: 272_000,
      async onAgentTurn(api) {
        const sid = api.sessionId
        if (sid.startsWith('gw_external_surveyor_')) {
          surveyorRuns += 1
          const res = await api.callTool('publish_external_literature_card', {
            outcome: 'UNAVAILABLE_REPORT',
            question_id: 'Q1',
            fulfilled_request_ids: [reqId],
            unavailable_reason_md: '经核实该私密数据包客观不存在，按规约无卡结案为 CLOSED_UNAVAILABLE。',
          })
          assert.equal(res.ok, true, JSON.stringify(res))
          return '已无卡结案'
        }
        if (sid.startsWith('gw_works_engineer_')) {
          worksRuns += 1
          if (resumedAfterAbort) worksRunsAfterResume += 1
          const q = await api.callTool('get_works_engineering_queue', { question_id: 'ALL' })
          for (const t of q.data.engineering_tickets || []) {
            if (t.status === 'OPEN' && String(t.payload_json || '').includes('HEALTHY_TICKET_CAN_RESOLVE')) {
              await api.callTool('resolve_works_ticket', {
                ticket_id: t.ticket_id,
                resolution: 'RESOLVED',
                resolution_note: '健康工单已正常处理结案。',
              })
            }
            // STUCK_TICKET_NO_PROGRESS 故意不处理，测试连续 2 次后单条熔断停止拉起 works_engineer！
          }
          return '工造司巡检完毕'
        }
        if (sid.startsWith('gw_logistics_coordinator_')) {
          // 故意把 fbA / fbB 置于 BLOCKED_L4B 避免额外派生
          const dash = await api.callTool('get_logistics_dashboard', { question_id: 'ALL' })
          for (const tn of dash.data.awaiting_triage || []) {
            await api.callTool('triage_node', {
              node_id: tn.node_id, assigned_family_id: 'fam_r5', triage_level: 'LEVEL_4B',
              action: 'PAUSE_TO_READY_QUEUE', rationale: '暂挂', reopen_condition: '待定',
            })
          }
          return '后勤分诊完成'
        }
        if (sid.startsWith('gw-exp-') || sid.startsWith('gw_exp_')) {
          expTurns += 1
          if (expTurns === 1 && orchRef) {
            // 探索者刚跑完第 1 轮，控制面执行确定性 pause -> 放补充裁决草稿 -> abortNode -> resume（裁决 4：只读检测草稿、绝不静默升版）！
            orchRef.pauseBackground()
            fs.mkdirSync(path.join(ws, 'rulings'), { recursive: true })
            fs.writeFileSync(path.join(ws, 'rulings', 'ruling_v1.md'), '# 补充裁决 v1\n请改用新约束。\n', 'utf8')
            await orchRef.abortNode(nid, 'SWITCH_TO_RULING_V1')
            assert.equal(api.isCancelled(), true, 'abortNode 应向 DSH 发送有效取消原因')
            const resumeRes = await orchRef.resumeBackground()
            assert.equal(resumeRes?.draftNotice?.unapproved_draft_detected, true, 'resume 应只读提示未审批磁盘草稿')
            resumedAfterAbort = true
          }
          return '探索者一轮结束'
        }
        return 'ok'
      },
    })

    const orch = new GreatwallOrchestrator({
      ctx,
      bridge,
      corePythonRoot: CORE_PYTHON_ROOT,
      workspaceRoot: ws,
      dataDir,
      protectedDirs: [dataDir],
      defaultAgentOptions: { provider: 'deepseek-account', model: 'deepseek-flash' },
    })
    orchRef = orch
    orch._waitWakeOrTimeout = async () => new Promise((r) => setTimeout(r, 15))

    const ac2 = new AbortController()
    const timer2 = setTimeout(() => ac2.abort(new Error('L2_TEST2_TIMEOUT')), 4000)
    await orch.runUntilClosed({ maxConcurrentWorkers: 2, signal: ac2.signal }).finally(() => clearTimeout(timer2))
    const st = await orch.getControlStatus()

    assert.equal(surveyorRuns, 1, '无解查新单结案后绝不再重复唤醒馆员')
    assert.equal(st.snapshot.external_literature_count, 0, '无解查新严禁造伪 [R###] 卡！')
    assert.equal(st.snapshot.pending_surveys.length, 0, '无解查新单必须离开 PENDING 队列')
    // resumeBackground() 按设计会复位熔断器计数；并发调度下工造司可能在 resume 前跑 1 次（复位后再跑 2 次=3）或全部在 resume 后跑 2 次熔断（=2）
    assert.ok(
      worksRunsAfterResume <= 2 && worksRuns >= 2 && worksRuns <= 3,
      `停滞工单在 resume 复位后最多再跑 2 次即应单条熔断止血，实得 worksRuns=${worksRuns}, afterResume=${worksRunsAfterResume}`,
    )
    assert.equal(st.snapshot.open_works_tickets.length, 1, '健康工单已结案，仅剩卡死工单留在 OPEN 且已被单条熔断')
    assert.ok(st.circuitBrokenItems.some((b) => b.key.startsWith('works:ticket:')), '控制面状态必须显式暴露单待办熔断告警')
    assert.equal(expTurns, 1, 'abortNode 后在线探索者必须在下轮前立刻退槽，严禁僵尸续推！')
    assert.equal(st.latestSpecRevision, 0, '裁决 4：未审批的磁盘 rulings 草稿绝不得静默自动升版')

    await orch.disposeAll()
  } finally {
    await bridge.dispose()
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  }
})
