/**
 * GreatWall v0.3 宏观大外环四拍脉冲确定性驱动器（WaveConferenceRunner，裁决 5）。
 *
 * 四拍严格顺序（全程支持宿主重启断点续跑）：
 * - 第 1 拍（代码硬对账）：Python 控制面已在 `check_and_open_wave_conference` 中确定性完成；
 *   若已封存参会助手 `< 2` 名，会议直接创建为 `SURVEY_REFRESHING`，跳过第 2 拍红蓝互辩；
 * - 第 2 拍（红蓝 2 轮互辩）：Node 侧按 Round 1 -> Round 2 顺序通过 `resumeOrSpawnAgent` 唤醒
 *   已封存 `gw-comp-<node_id>`（物理撤除档案写工具，仅挂 `submit_conference_statement`），
 *   结束后唤醒 `gw-chair-<conference_id>` 调用 `record_conference_minutes` 切至 `SURVEY_REFRESHING`；
 * - 第 3 拍（1500 字总览刷新）：拉起零外网 `library_chronicler` 调 `publish_living_survey` 切至 `ADJUDICATING`；
 * - 第 4 拍（宏观拍板）：原地 `resume` 同一 `gw-chair-<conference_id>` 读最新总览调 `submit_conference_verdict`；
 * - 会后清理：所有参会已封存助手与主席会话严格按「先 `dispose()`、再 `archiveSession()`」封存。
 * @module dsh-greatwall-v6up/orchestrator/wave_conference_runner
 */
import { SEALED_COMPANION_CONFERENCE_TOOLS, formatNodeSessionTitle } from '../prompts.js'

export class WaveConferenceRunner {
  constructor(port) {
    this.port = port
  }

  /**
   * 根据会议当前状态推进大外环（幂等可重入，支持重启后从任意一拍继续）。
   * @param {object} conf wave_conferences 表快照对象
   * @param {AbortSignal | null} signal
   */
  async advanceConference(conf, signal = null) {
    if (!conf?.conference_id) return { advanced: false, reason: 'missing_conference' }
    const cid = String(conf.conference_id)
    const qid = String(conf.question_id || '')
    const waveNo = Number(conf.wave_no || 1)
    const status = String(conf.status || '')
    const chairSid = String(conf.chair_session_id || `gw-chair-${cid}`)

    let participants = []
    try {
      participants = Array.isArray(conf.participant_nodes)
        ? conf.participant_nodes
        : JSON.parse(conf.participant_nodes_json || '[]')
    } catch {
      participants = []
    }

    // 第 2 拍：Round 1 交叉质询 -> Round 2 辩护补证 -> 主席落盘纪要
    if (status === 'ROUND_1_CRITIQUE' || status === 'ROUND_2_REBUTTAL') {
      const startRound = status === 'ROUND_1_CRITIQUE' ? 1 : 2
      for (let roundNo = startRound; roundNo <= 2; roundNo++) {
        if (signal?.aborted) return { advanced: false, reason: 'aborted' }
        for (const p of participants) {
          if (signal?.aborted) return { advanced: false, reason: 'aborted' }
          const nid = String(p.node_id || '')
          const bid = String(p.branch_id || '')
          const compSid = String(p.companion_session_id || `gw-comp-${nid}`)
          if (!nid) continue
          const roundLabel = roundNo === 1 ? 'Round 1（点对点红蓝质询）' : 'Round 2（直面质疑与互补方案）'
          await this.port.resumeOrSpawnAgent({
            role: 'lineage_companion',
            sessionId: compSid,
            nodeId: nid,
            branchId: bid,
            questionId: qid,
            cwd: p.worktree_abs_path || this.port.workspaceRoot,
            uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: qid, nodeId: nid, suffix: `圆桌W${waveNo}R${roundNo}` }),
            shortTransaction: true,
            archiveOnComplete: true,
            allowedMcpOverride: SEALED_COMPANION_CONFERENCE_TOOLS,
            signal,
            prompt: `【宏观大外环 Wave ${waveNo} · ${roundLabel}】你作为已封存节点 ${nid} 的代表参会（已物理撤除档案写权）。请先调 get_companion_context(branch_id="${bid}", node_id="${nid}", mode="CONFERENCE_PARTICIPANT") 阅读代码硬账本与已有发言，然后调用 submit_conference_statement(conference_id="${cid}", node_id="${nid}", round_no=${roundNo}, statement_md="...", target_node_ids=[...]) 提交直指核心分歧或互补点的简明发言。`,
          })
        }
      }

      // 2 轮交锋结束，由圆桌主席落盘纪要切 SURVEY_REFRESHING
      await this.port.resumeOrSpawnAgent({
        role: 'conference_chair',
        sessionId: chairSid,
        questionId: qid,
        uiLabel: `[圆桌主席] ${qid} Wave ${waveNo} 纪要`,
        shortTransaction: false,
        archiveOnComplete: false,
        signal,
        prompt: `【宏观大外环 Wave ${waveNo} · 第 2 拍纪要】请调用 get_conference_dossier(conference_id="${cid}") 审阅本波代码硬账本与 2 轮红蓝交锋，提炼核心共识、实质分歧与需验证假设，调用 record_conference_minutes(conference_id="${cid}", minutes_md="...") 落盘纪要以触发综述官刷新《子题全局总览》。`,
      })
      return { advanced: true, nextExpectedStatus: 'SURVEY_REFRESHING' }
    }

    // 第 3 拍：零外网 library_chronicler 刷新 <=1500 字《子题全局总览》切至 ADJUDICATING
    if (status === 'SURVEY_REFRESHING') {
      await this.port.spawnAndRunAgent({
        role: 'library_chronicler',
        questionId: qid,
        uiLabel: `[综述终稿官] ${qid} Wave ${waveNo} 总览`,
        shortTransaction: true,
        archiveOnComplete: true,
        signal,
        prompt: `【宏观大外环 Wave ${waveNo} · 第 3 拍刷新总览】请调用 get_chronicler_snapshot(question_id="${qid}", conference_id="${cid}")，结合硬账本、圆桌纪要与全量已审 L3/L2，调用 publish_living_survey(question_id="${qid}", conference_id="${cid}", ...) 发布 <=1500 字最新《子题全局总览与明确缺口导览》（严禁泄露他派私有未审思路）。`,
      })
      return { advanced: true, nextExpectedStatus: 'ADJUDICATING' }
    }

    // 第 4 拍：原地 resume 同一 gw-chair-<conference_id> 读最新总览后签发 6 类宏观调整单
    if (status === 'ADJUDICATING') {
      await this.port.resumeOrSpawnAgent({
        role: 'conference_chair',
        sessionId: chairSid,
        questionId: qid,
        uiLabel: `[圆桌主席] ${qid} Wave ${waveNo} 拍板`,
        shortTransaction: true,
        archiveOnComplete: true,
        signal,
        prompt: `【宏观大外环 Wave ${waveNo} · 第 4 拍宏观拍板】综述官已刷新最新《子题全局总览》！请先调用 get_conference_dossier(conference_id="${cid}") 仔细研读 latest_living_survey 中的 Explicit Gaps 与各分支保护期状态，然后调用 submit_conference_verdict(conference_id="${cid}", actions=[...], rationale_md="...") 签发宏观树结构调整单（严禁提前 RETIRE 保护期内分支）。`,
      })
      return { advanced: true, nextExpectedStatus: 'COMPLETED_OR_PENDING_HUMAN' }
    }

    return { advanced: false, reason: `status_${status}_no_action` }
  }
}
