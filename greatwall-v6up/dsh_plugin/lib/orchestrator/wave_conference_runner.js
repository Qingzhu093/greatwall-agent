/**
 * GreatWall v0.3 宏观大外环四拍脉冲确定性驱动器（WaveConferenceRunner，裁决 5）。
 *
 * 四拍严格顺序（全程支持宿主重启断点续跑）：
 * - 第 1 拍（代码硬对账）：Python 控制面已在 `check_and_open_wave_conference` 中确定性完成；
 *   若已封存参会助手 `< 2` 名，会议直接创建为 `SURVEY_REFRESHING`，跳过第 2 拍红蓝互辩；
 * - 第 2 拍（红蓝 2 轮互辩）：Node 侧按 Round 1 -> Round 2 顺序通过 `resumeOrSpawnAgent` 唤醒
 *   已封存 `gw-comp-<node_id>`（物理撤除档案写工具，仅挂 `submit_conference_statement`），
 *   结束后唤醒 `gw-chair-<conference_id>` 调用 `record_conference_minutes` 切至 `SURVEY_REFRESHING`；
 * - 第 3 拍：零外网 `library_chronicler` 刷新总览后，会议才进入 `ADJUDICATING`；
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

    const participants = conf.participant_nodes ?? JSON.parse(conf.participant_nodes_json ?? '[]')
    const agenda = JSON.parse(conf.agenda_json ?? '{}')
    const ledger = JSON.parse(conf.critiques_ledger_json ?? '[]')
    const agendaText = [
      ...(agenda.questions ?? []), agenda.human_agenda_md, agenda.streetlight_warning,
    ].filter(Boolean).join('\n')

    const maxRounds = Math.max(2, Math.min(4, Number(agenda.discussion_rounds || 2)))

    if (status === 'ROUND_1_CRITIQUE' || status === 'ROUND_2_REBUTTAL') {
      const startRound = status === 'ROUND_1_CRITIQUE' ? 1 : 2
      for (let roundNo = startRound; roundNo <= maxRounds; roundNo++) {
        if (signal?.aborted) return { advanced: false, reason: 'aborted' }
        const alreadySpoken = new Set(ledger.filter((item) => item.round === roundNo).map((item) => item.node_id))
        const speechRules = roundNo === 1
          ? '使用 PROPOSE_AND_SELF_AUDIT，列实证底座、自查失效范围，将未验证模块放入 unverified_ideas。'
          : `阅读前面各轮全部发言。选择 CRITIQUE_SEAM、ENDORSE_AND_OFFER、WARN_STREETLIGHT 或 CONFIRM_TAKEAWAY。${participants.length >= 2 ? 'target_node_ids 必须点名至少一位其他参会者。' : ''}`
        const roundResults = await Promise.all(participants.filter((p) => !alreadySpoken.has(p.node_id)).map((p) => {
          const nid = p.node_id
          const bid = p.branch_id
          const compSid = p.companion_session_id || `gw-comp-${nid}`
          return this.port.resumeOrSpawnAgent({
            role: 'lineage_companion',
            sessionId: compSid,
            nodeId: nid,
            branchId: bid,
            questionId: qid,
            uiLabel: formatNodeSessionTitle('lineage_companion', { questionId: qid, nodeId: nid, suffix: `圆桌W${waveNo}R${roundNo}` }),
            shortTransaction: true,
            archiveOnComplete: roundNo >= maxRounds,
            allowedMcpOverride: SEALED_COMPANION_CONFERENCE_TOOLS,
            signal,
            prompt: `【Wave ${waveNo} 同行研讨 · 第 ${roundNo}/${maxRounds} 轮】\n${agendaText}\n以封存节点 ${nid} 代表参会。调用 get_companion_context(branch_id="${bid}", node_id="${nid}", mode="CONFERENCE_PARTICIPANT") 阅读硬账本和已提交的发言。调用 submit_conference_statement(conference_id="${cid}", node_id="${nid}", round_no=${roundNo}, ...)，最多 1200 字。${speechRules}`,
          })
        }))
        if (roundResults.some((r) => r?.isAbnormalEnd)) {
          return { advanced: false, reason: `round_${roundNo}_abnormal_end` }
        }
      }

      // 上半场多轮交锋结束，由圆桌主席落盘纪要切 SURVEY_REFRESHING
      await this.port.resumeOrSpawnAgent({
        role: 'conference_chair',
        sessionId: chairSid,
        questionId: qid,
        uiLabel: `[圆桌主席] ${qid} Wave ${waveNo} 纪要`,
        shortTransaction: false,
        archiveOnComplete: false,
        signal,
        prompt: `【宏观大外环 Wave ${waveNo} · 上半场纪要】请调用 get_conference_dossier(conference_id="${cid}") 审阅本波代码硬账本与全部 ${maxRounds} 轮同行发言，提炼证据共识、接口风险与承重缺口，调用 record_conference_minutes(conference_id="${cid}", minutes_md="...") 提交不超过 6000 字的纪要以触发综述官刷新《子题全局总览》。`,
      })
      return { advanced: true, nextExpectedStatus: 'SURVEY_REFRESHING' }
    }

    // 第 3 拍总览发布后圆桌才能进入 ADJUDICATING。
    if (status === 'SURVEY_REFRESHING') {
      await this.port.spawnAndRunAgent({
        role: 'library_chronicler',
        questionId: qid,
        uiLabel: `[综述终稿官] ${qid} Wave ${waveNo} 总览`,
        shortTransaction: true,
        archiveOnComplete: true,
        signal,
        prompt: `【宏观大外环 Wave ${waveNo} · 第 3 拍刷新总览】请调用 get_chronicler_snapshot(question_id="${qid}", conference_id="${cid}")，结合硬账本、圆桌纪要与全量已审 L3/L2，调用 publish_living_survey(question_id="${qid}", conference_id="${cid}", ...) 发布不超过 4000 字核心四栏。第四栏只录承重缺口，边缘争议移入独立 marginal_notes_md 附栏。`,
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
        prompt: `【宏观大外环 Wave ${waveNo} · 第 4 拍宏观拍板】综述官已刷新最新《子题全局总览》！请先调用 get_conference_dossier(conference_id="${cid}") 仔细研读 latest_living_survey 中的 Explicit Gaps 与各分支保护期状态，然后调用 submit_conference_verdict(conference_id="${cid}", actions=[...], rationale_md="...") 使用 action_type 签发宏观调整单。按需点名跨脉供体与嫁接目标，或选择组合核验、饱和止盈。尊重成长保护期。`,
      })
      return { advanced: true, nextExpectedStatus: 'COMPLETED_OR_PENDING_HUMAN' }
    }

    return { advanced: false, reason: `status_${status}_no_action` }
  }
}
