"""图书馆宏观大外环引擎（第 1 拍代码硬对账 -> 第 2 拍圆桌对抗 -> 第 3 拍总览 -> 第 4 拍树结构调整落地）。

严格落实顶层裁决 5：
- 波次节拍：`completed_nodes_since_last_conference >= max(2, active_branches * 2)`；
- 已封存参会助手 < 2 名时跳过第 2 拍红蓝互辩，直入 `SURVEY_REFRESHING`；
- 旁路双供体合体（`SPAWN_SYNTHESIS`）绝不污染原纯血分支，次供体快照只读挂载至 `.greatwall_donors/<node_id>/`；
- 冷静裁剪（`HIBERNATE`）严守 2 班岗成长保护期与时间线单调复核（刚过审新 L3 的分支自动跳过不误裁）。
"""

from __future__ import annotations

from contextlib import nullcontext
import json
import sqlite3
import uuid
from typing import Any

from ..db.enums import ALLOWED_CONFERENCE_SPEECH_ACTS
from ..db_schema import (
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from ..mcp_core_helpers import load_runtime_config
from .effects_outbox import enqueue_runtime_effect
from .proposals import create_control_proposal
from .snapshot_queries import fetch_streetlight_warning_questions
from .subproblem_locks import evaluate_subproblem_locks, get_subproblem_active_spec_revision
from .operator_policy import active_arrangements, effective_policy
from .wave_verdict_actions import PreparedBranch, execute_wave_phases, prepare_wave_growth, validate_wave_actions


_WORKSHOP_QUESTIONS = (
    "拼图覆盖核对：馆藏与实证覆盖哪些子域，剩下哪些承重缺口？",
    "接口排雷与嫁接：前提、坐标系和退化边界在哪里断裂，怎样修补？",
    "反路灯自省：哪些边缘争论应停止投入，是否具备组合完备或饱和止盈条件？",
)


def build_wave_hard_ledger(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    """第 1 拍：纯 Python 代码拉取铁面《本波硬账本》（所有未过空白沙箱宣称零权重）。"""
    qid = str(question_id)
    qrow = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    active_rev = int(qrow["active_spec_revision"] or 0) if qrow else 0

    active_branches = [
        dict(r)
        for r in conn.execute(
            """
            SELECT branch_id, family_id, branch_kind, MAX(generation) AS latest_gen,
                   MIN(protection_generations_left) AS protection_left
            FROM lineage_nodes
            WHERE question_id = ?
              AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
              AND control_state NOT IN ('HIBERNATED','DRAIN_AFTER_TURN')
            GROUP BY branch_id
            """,
            (qid,),
        ).fetchall()
    ]
    l3_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, l3_entry_kind, goal_coverage, publish_tier, verified_spec_revision, title, created_at,
                   author_family_id, exact_verified_scope_md, rigor_score, novelty_score, significance_score, overall_score
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
            ORDER BY created_at DESC, entry_id DESC
            """,
            (qid,),
        ).fetchall()
    ]
    l2_rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, l2_category, title, exact_refuted_scope_md, created_at
            FROM internal_research_ledger
            WHERE question_id = ? AND ledger_type = 'L2_FAILURE_RECORD' AND is_active = 1
            ORDER BY created_at DESC
            """,
            (qid,),
        ).fetchall()
    ]
    open_gaps = [
        dict(r)
        for r in conn.execute(
            "SELECT gap_id, blocked_node_id, formal_statement_md, created_at FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN' AND gap_tier = 'LOAD_BEARING' ORDER BY created_at ASC",
            (qid,),
        ).fetchall()
    ]
    instruments = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, instrument_role, health_status FROM instruments WHERE is_active = 1 AND (question_id = ? OR question_id = 'ALL')",
            (qid,),
        ).fetchall()
    ]

    return {
        "question_id": qid,
        "active_spec_revision": active_rev,
        "completed_waves": int(qrow["completed_waves"] or 0) if qrow else 0,
        "completed_nodes_since_last_conference": int(qrow["completed_nodes_since_last_conference"] or 0) if qrow else 0,
        "completed_nodes_since_last_l3": int(qrow["completed_nodes_since_last_l3"] or 0) if qrow else 0,
        "spent_tokens": int(qrow["spent_tokens"] or 0) if qrow else 0,
        "question_token_budget": int(qrow["question_token_budget"] or 0) if qrow else 0,
        "active_branches": active_branches,
        "verified_l3_count": len(l3_rows),
        "verified_l3": l3_rows,
        "streetlight_warning": "STREETLIGHT_WARNING" if qid in fetch_streetlight_warning_questions(conn) else None,
        "refuted_l2_count": len(l2_rows),
        "refuted_l2": l2_rows,
        "open_lemma_gaps": open_gaps,
        "active_instruments": instruments,
    }


def _collect_sealed_conference_participants(conn: sqlite3.Connection, question_id: str) -> list[dict[str, Any]]:
    """收集各活跃分支及本波刚封存结案（非休眠裁撤）分支最近一代已封存交班记录的伴随助手。"""
    qid = str(question_id)
    last_conf = conn.execute(
        """
        SELECT created_at FROM wave_conferences
        WHERE question_id = ? AND status = 'COMPLETED'
        ORDER BY created_at DESC LIMIT 1
        """,
        (qid,),
    ).fetchone()
    last_conf_at = str(last_conf["created_at"] or "") if last_conf else ""
    branch_rows = conn.execute(
        """
        SELECT DISTINCT branch_id
        FROM lineage_nodes
        WHERE question_id = ?
          AND control_state NOT IN ('HIBERNATED','DRAIN_AFTER_TURN')
          AND (
              node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B')
              OR (
                  node_status = 'SEALED'
                  AND briefing_sealed_at IS NOT NULL
                  AND (? = '' OR briefing_sealed_at > ?)
              )
          )
        ORDER BY branch_id
        """,
        (qid, last_conf_at, last_conf_at),
    ).fetchall()
    participants: list[dict[str, Any]] = []
    for br in branch_rows:
        bid = str(br["branch_id"])
        sealed = conn.execute(
            """
            SELECT node_id, branch_id, family_id, generation, branch_kind, companion_session_id,
                   briefing_sealed_at, mechanism_summary, evidence_grade, column_a_facts_md, bound_obs_ids_json
            FROM lineage_nodes
            WHERE question_id = ? AND branch_id = ? AND briefing_sealed_at IS NOT NULL
            ORDER BY generation DESC, created_at DESC LIMIT 1
            """,
            (qid, bid),
        ).fetchone()
        if sealed is None:
            continue
        live_in_flight = conn.execute(
            "SELECT node_id, generation FROM lineage_nodes WHERE branch_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING') ORDER BY generation DESC LIMIT 1",
            (bid,),
        ).fetchone()
        participants.append(
            {
                "branch_id": bid,
                "node_id": str(sealed["node_id"]),
                "family_id": str(sealed["family_id"] or ""),
                "generation": int(sealed["generation"] or 1),
                "branch_kind": str(sealed["branch_kind"] or "PURE"),
                "companion_session_id": str(sealed["companion_session_id"] or f"gw-comp-{sealed['node_id']}"),
                "mechanism_summary": sealed["mechanism_summary"],
                "column_a_facts_md": sealed["column_a_facts_md"],
                "observations": [dict(row) for row in conn.execute(
                    """
                    SELECT obs_id, obs_status, tracks_json FROM observations
                    WHERE obs_id IN (SELECT value FROM json_each(?)) ORDER BY obs_id
                    """, (sealed["bound_obs_ids_json"],),
                )],
                "evidence_grade": str(sealed["evidence_grade"] or "NONE"),
                "slow_branch_snapshot": bool(live_in_flight and str(live_in_flight["node_id"]) != str(sealed["node_id"])),
                "in_flight_generation": int(live_in_flight["generation"]) if live_in_flight else None,
            }
        )
    return participants


def check_and_open_wave_conference(
    conn: sqlite3.Connection, *, question_id: str, force: bool = False,
    human_agenda_md: str = "", discussion_rounds: int | None = None,
) -> dict[str, Any] | None:
    """检查子题是否达到宏观大外环触发节拍；达标则原子建会并决定进 ROUND_1_CRITIQUE 或跳过互辩直入 SURVEY_REFRESHING。"""
    qid = str(question_id)
    qrow = conn.execute("SELECT * FROM subproblem_runtime_state WHERE question_id = ?", (qid,)).fetchone()
    if qrow is None:
        return None
    dstate = str(qrow["dispatch_state"])
    if not force and dstate != "DISPATCHING":
        return None
    if force and dstate in ("CLOSED", "STOPPED_SOLVED"):
        return None

    # 已有进行中的会议时不重复开会
    in_flight = conn.execute(
        """
        SELECT conference_id, status FROM wave_conferences
        WHERE question_id = ? AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')
        LIMIT 1
        """,
        (qid,),
    ).fetchone()
    if in_flight is not None:
        return None

    cfg = load_runtime_config()
    mult = int(cfg.get("wave_conference_branch_multiplier", 2))
    min_nodes = int(cfg.get("wave_conference_min_completed_nodes", 2))
    raw_rounds = cfg.get("wave_conference_discussion_rounds", 2) if discussion_rounds is None else discussion_rounds
    try:
        max_rounds = int(raw_rounds)
    except (TypeError, ValueError) as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"discussion_rounds 须为 2–4 的整数，实收 {raw_rounds!r}") from exc
    if not 2 <= max_rounds <= 4:
        raise FailClosedError(ERR_INVALID_INPUT, f"discussion_rounds 须在 2–4 轮之间，实收 {max_rounds}")

    active_branch_cnt = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT branch_id) AS cnt FROM lineage_nodes
            WHERE question_id = ? AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE','PENDING_REVIEW')
            """,
            (qid,),
        ).fetchone()["cnt"]
        or 0
    )
    threshold = max(min_nodes, active_branch_cnt * max(1, mult))
    completed_since = int(qrow["completed_nodes_since_last_conference"] or 0)
    if not force and completed_since < threshold:
        return None

    participants = _collect_sealed_conference_participants(conn, qid)
    # 裁决 5：已封存参会助手 < 2 名时跳过第 2 拍红蓝互辩，直入 SURVEY_REFRESHING
    init_status = "ROUND_1_CRITIQUE" if len(participants) >= 2 else "SURVEY_REFRESHING"
    # 独立递增会议序号（与成功完成波次 completed_waves 解耦，驳回 CANCELLED/失败 FAILED 后再开会绝不撞 UNIQUE(question_id, wave_no)）
    max_seq_row = conn.execute(
        "SELECT COALESCE(MAX(wave_no), 0) AS max_no FROM wave_conferences WHERE question_id = ?",
        (qid,),
    ).fetchone()
    wave_no = max(int(qrow["completed_waves"] or 0), int(max_seq_row["max_no"] or 0)) + 1
    conf_id = f"wc_{qid.lower()}_w{wave_no}_{uuid.uuid4().hex[:6]}"
    chair_sid = f"gw-chair-{conf_id}"
    now = utc_now_iso()

    hard_ledger = build_wave_hard_ledger(conn, qid)
    agenda = {
        "questions": list(_WORKSHOP_QUESTIONS),
        "human_agenda_md": human_agenda_md,
        "discussion_rounds": max_rounds,
        "streetlight_warning": hard_ledger["streetlight_warning"],
        "hard_ledger": hard_ledger,
    }
    with rw_immediate_tx(conn):
        if conn.execute(
            """
            SELECT 1 FROM wave_conferences WHERE question_id = ?
              AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED') LIMIT 1
            """, (qid,),
        ).fetchone() is not None:
            return None
        conn.execute(
            """
            INSERT INTO wave_conferences(
                conference_id, question_id, wave_no, status, participant_nodes_json,
                agenda_json, human_agenda_md, critiques_ledger_json, minutes_md, chair_session_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
            """,
            (
                conf_id,
                qid,
                wave_no,
                init_status,
                json.dumps(participants, ensure_ascii=False),
                json.dumps(agenda, ensure_ascii=False),
                human_agenda_md,
                "" if init_status == "ROUND_1_CRITIQUE" else "（本波已封存分支不足 2 条，跳过多方互辩直入总览刷新与宏观开拓）",
                chair_sid,
                now,
            ),
        )
        conn.execute(
            "UPDATE subproblem_runtime_state SET completed_nodes_since_last_conference = 0, updated_at = ? WHERE question_id = ?",
            (now, qid),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"wave:{conf_id}",
            kind="RUN_WAVE_CONFERENCE" if init_status == "ROUND_1_CRITIQUE" else "REFRESH_LIVING_SURVEY",
            target_type="QUESTION",
            target_id=qid,
            target_generation=int(qrow["dispatch_generation"] or 1),
            external_handle_id=chair_sid,
            payload={"conference_id": conf_id, "wave_no": wave_no, "initial_status": init_status},
        )

    return {
        "opened": True,
        "conference_id": conf_id,
        "question_id": qid,
        "wave_no": wave_no,
        "status": init_status,
        "participant_count": len(participants),
        "discussion_rounds": max_rounds,
        "chair_session_id": chair_sid,
    }


def append_conference_statement(
    conn: sqlite3.Connection,
    *,
    conference_id: str,
    node_id: str,
    round_no: int,
    statement_md: str,
    target_node_ids: list[str] | None = None,
    speech_act: str = "PROPOSE_AND_SELF_AUDIT",
    unverified_ideas: list[str] | None = None,
) -> dict[str, Any]:
    clean_stmt = statement_md.strip()
    ideas = [f"[UNVERIFIED] {idea.strip()}" for idea in (unverified_ideas or []) if idea.strip()]
    total_chars = len(clean_stmt) + sum(map(len, ideas))
    if len(clean_stmt) < 20 or total_chars > 1200:
        raise FailClosedError(ERR_INVALID_INPUT, f"圆桌发言当前 {total_chars} 字，正文至少 20 字、总长上限 1200 字")
    if type(round_no) is not int or not 1 <= round_no <= 4:
        raise FailClosedError(ERR_INVALID_INPUT, "圆桌轮次须为 1–4 的整数")
    if speech_act not in ALLOWED_CONFERENCE_SPEECH_ACTS or (round_no == 1) != (speech_act == "PROPOSE_AND_SELF_AUDIT"):
        raise FailClosedError(ERR_INVALID_INPUT, f"第 {round_no} 轮不允许 speech_act={speech_act!r}")
    targets = list(dict.fromkeys(target_node_ids or []))
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (conference_id,)).fetchone()
        if conf is None:
            raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
        agenda = json.loads(conf["agenda_json"] or "{}")
        max_rounds = max(2, min(4, int(agenda.get("discussion_rounds") or 2)))
        if round_no > max_rounds:
            raise FailClosedError(ERR_INVALID_INPUT, f"本场圆桌上半场共设 {max_rounds} 轮，不接受第 {round_no} 轮发言")
        expected_status = "ROUND_1_CRITIQUE" if round_no == 1 else "ROUND_2_REBUTTAL"
        if conf["status"] != expected_status:
            raise FailClosedError(ERR_LOCKED, f"会议当前为 {conf['status']}，不接受第 {round_no} 轮发言")
        participants = json.loads(conf["participant_nodes_json"])
        valid = {p["node_id"] for p in participants}
        if node_id not in valid:
            raise FailClosedError(ERR_LOCKED, f"节点 {node_id!r} 不在本次圆桌参会名单中")
        if round_no >= 2 and len(valid) >= 2 and not targets:
            raise FailClosedError(ERR_INVALID_INPUT, f"第 {round_no} 轮须点名至少一位参会同行：target_node_ids")
        if set(targets) - (valid - {node_id}):
            raise FailClosedError(ERR_INVALID_INPUT, "圆桌只能点名回应其他参会节点")
        ledger = json.loads(conf["critiques_ledger_json"])
        if round_no > 2 and not any(item["round"] == round_no - 1 for item in ledger):
            raise FailClosedError(ERR_LOCKED, f"第 {round_no - 1} 轮尚无发言，不可跳过直接进入第 {round_no} 轮")
        if any(item["round"] == round_no and item["node_id"] == node_id for item in ledger):
            raise FailClosedError(ERR_LOCKED, "该节点本轮已提交发言")
        ledger.append({
            "round": round_no, "node_id": node_id, "target_node_ids": targets, "speech_act": speech_act,
            "statement_md": clean_stmt, "unverified_ideas": ideas, "at": now,
        })
        complete_r1 = round_no == 1 and valid <= {item["node_id"] for item in ledger if item["round"] == 1}
        next_status = "ROUND_2_REBUTTAL" if complete_r1 else conf["status"]
        conn.execute(
            "UPDATE wave_conferences SET critiques_ledger_json = ?, status = ? WHERE conference_id = ?",
            (json.dumps(ledger, ensure_ascii=False), next_status, conference_id),
        )
    return {
        "conference_id": conference_id, "round": round_no, "discussion_rounds": max_rounds,
        "status": next_status, "total_statements": len(ledger),
    }


def execute_approved_wave_verdict(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    conference_id: str,
    prepared_growth: dict[int, PreparedBranch] | None = None,
) -> dict[str, Any]:
    """先腾槽，再开枝合体，最后执行工单与收敛。"""
    staging = (
        prepare_wave_growth(conn, workspace_root, conference_id)
        if prepared_growth is None else nullcontext(prepared_growth)
    )
    now = utc_now_iso()
    with staging as prepared, rw_immediate_tx(conn):
        conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (conference_id,)).fetchone()
        if conf is None:
            raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
        if conf["status"] not in ("ADJUDICATING", "PENDING_HUMAN_APPROVAL"):
            raise FailClosedError(ERR_CONFLICT, f"会议 {conference_id!r} 当前状态为 {conf['status']}，无法执行裁决")
        qid = conf["question_id"]
        actions = json.loads(conf["verdict_json"])["actions"]
        validate_wave_actions(actions)
        executed, skipped = execute_wave_phases(conn, conf, actions, prepared, now)
        conn.execute(
            "UPDATE wave_conferences SET status = 'COMPLETED', completed_at = ? WHERE conference_id = ?",
            (now, str(conference_id)),
        )
        conn.execute(
            "UPDATE subproblem_runtime_state SET completed_waves = completed_waves + 1, updated_at = ? WHERE question_id = ?",
            (now, qid),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"chief:wave_done:{conference_id}",
            kind="NOTIFY_CHIEF",
            target_type="QUESTION",
            target_id=qid,
            payload={
                "event_category": "MILESTONE",
                "conference_id": str(conference_id),
                "question_id": qid,
                "executed_count": len(executed),
                "skipped_count": len(skipped),
            },
        )

    # 递增 completed_waves 后立即结算停工锁（锁三 max_waves 保险丝）
    lock_eval = evaluate_subproblem_locks(conn, question_id=qid)
    return {
        "conference_id": str(conference_id),
        "question_id": qid,
        "status": "COMPLETED",
        "executed": executed,
        "skipped": skipped,
        "subproblem_lock_eval": lock_eval,
    }


def mark_wave_conference_failed(
    conn: sqlite3.Connection,
    *,
    conference_id: str,
    reason: str = "CIRCUIT_BREAKER_STALLED",
) -> dict[str, Any]:
    """将无进展/熔断的圆桌会议落库标记为 FAILED 并释放子题开会锁，同时通知 gw-chief。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    cur_status = str(conf["status"])
    if cur_status in ("COMPLETED", "CANCELLED", "EXPIRED", "FAILED"):
        return {"conference_id": str(conference_id), "status": cur_status, "already_terminal": True}
    now = utc_now_iso()
    qid = str(conf["question_id"])
    note = str(reason or "CIRCUIT_BREAKER_STALLED")
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE wave_conferences
            SET status = 'FAILED',
                completed_at = ?
            WHERE conference_id = ? AND status NOT IN ('COMPLETED','CANCELLED','EXPIRED','FAILED')
            """,
            (now, str(conference_id)),
        )
        enqueue_runtime_effect(
            conn,
            effect_key=f"chief:wave_fail:{conference_id}",
            kind="NOTIFY_CHIEF",
            target_type="QUESTION",
            target_id=qid,
            payload={
                "event_category": "BLOCK_ALERT",
                "conference_id": str(conference_id),
                "question_id": qid,
                "reason": "WAVE_CONFERENCE_FAILED",
                "detail": note,
            },
        )
    return {"conference_id": str(conference_id), "question_id": qid, "status": "FAILED", "reason": note}


def submit_wave_verdict_decision(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    conference_id: str,
    verdict_payload: dict[str, Any],
    rationale_md: str,
) -> dict[str, Any]:
    """第 4 拍裁决落地分流：WAVE_CONFIRM 或含 PAUSE_FOR_HUMAN 强制挂待人类拍板；AUTOPILOT 低风险动作自动落地。"""
    conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (str(conference_id),)).fetchone()
    if conf is None:
        raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
    if str(conf["status"]) != "ADJUDICATING":
        raise FailClosedError(ERR_LOCKED, f"会议 {conference_id!r} 状态为 {conf['status']}，仅 ADJUDICATING 可提交裁决")

    actions = verdict_payload.get("actions") if isinstance(verdict_payload, dict) else None
    validate_wave_actions(actions)

    p0 = conn.execute("SELECT autonomy_mode FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    baseline_autonomy = str(p0["autonomy_mode"] or "WAVE_CONFIRM") if p0 else "WAVE_CONFIRM"
    autonomy = effective_policy(active_arrangements(conn)).get("autonomy_mode", baseline_autonomy)
    has_high_risk_pause = any(a["action_type"] == "PAUSE_FOR_HUMAN" for a in actions)
    need_human = autonomy != "AUTOPILOT" or has_high_risk_pause

    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE wave_conferences SET verdict_json = ? WHERE conference_id = ?",
            (json.dumps(verdict_payload, ensure_ascii=False), str(conference_id)),
        )
        if need_human:
            conn.execute(
                "UPDATE wave_conferences SET status = 'PENDING_HUMAN_APPROVAL' WHERE conference_id = ?",
                (str(conference_id),),
            )
            prop = create_control_proposal(
                conn,
                proposed_by="conference_chair",
                action_type="APPROVE_WAVE_VERDICT",
                target_id=str(conference_id),
                payload={"conference_id": str(conference_id), "question_id": str(conf["question_id"]), "actions": actions},
                rationale_md=rationale_md or f"子题 {conf['question_id']} 第 {conf['wave_no']} 波宏观大外环调整建议",
            )
            enqueue_runtime_effect(
                conn,
                effect_key=f"chief:wave_approval:{conference_id}",
                kind="NOTIFY_CHIEF",
                target_type="QUESTION",
                target_id=str(conf["question_id"]),
                payload={
                    "event_category": "MILESTONE",
                    "conference_id": str(conference_id),
                    "proposal_id": prop["proposal_id"],
                    "requires_human_approval": True,
                },
            )
            return {
                "conference_id": str(conference_id),
                "status": "PENDING_HUMAN_APPROVAL",
                "proposal_id": prop["proposal_id"],
                "autonomy_mode": autonomy,
            }

    return execute_approved_wave_verdict(conn, workspace_root=workspace_root, conference_id=str(conference_id))
