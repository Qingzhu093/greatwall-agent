"""控制面子域 3：Parse 0 立项、初始仪器核查、上下文压力同步、节点中止、人工叫停与工单提交。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ..db_schema import (
    ALLOWED_AUTONOMY_MODES,
    ALLOWED_WORKS_TICKET_TYPES,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from ..mcp_core_helpers import (
    compute_clock_signal,
    load_runtime_config,
    resolve_effective_context_window,
)
from .subproblem_locks import ensure_subproblem_rows

_ALLOWED_WORKS_TICKET_TYPES = set(ALLOWED_WORKS_TICKET_TYPES)


def _canonical_instrument_key(iid: str) -> str:
    """将仪器 ID 归一化（去空白、小写、剥离常见 `inst_` 前缀），避免 Parse 0 声明 `foo` 而工造司注册 `inst_foo` 导致假缺失。"""
    s = str(iid or "").strip().lower()
    if s.startswith("inst_"):
        s = s[5:]
    return s


def compute_missing_initial_instruments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """对比 Parse 0 `initial_instruments_json` 与 `instruments` 活跃表，返回尚未注册激活的初始仪器清单。"""
    p0 = conn.execute("SELECT initial_instruments_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    if p0 is None:
        return []
    try:
        items = json.loads(p0["initial_instruments_json"] or "[]")
    except Exception:
        items = []
    if not isinstance(items, list) or not items:
        return []
    active_rows = conn.execute(
        "SELECT instrument_id, question_id, instrument_role FROM instruments WHERE is_active = 1"
    ).fetchall()
    active_ids = {str(r["instrument_id"]) for r in active_rows}
    active_canonical = {_canonical_instrument_key(str(r["instrument_id"])) for r in active_rows}

    def _is_registered(target_id: str) -> bool:
        if not target_id:
            return False
        if target_id in active_ids:
            return True
        canon = _canonical_instrument_key(target_id)
        return bool(canon and canon in active_canonical)

    missing: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, str):
            iid = raw.strip()
            if iid and not _is_registered(iid):
                missing.append({"instrument_id": iid})
        elif isinstance(raw, dict):
            iid = str(raw.get("instrument_id") or raw.get("id") or "").strip()
            if iid:
                if not _is_registered(iid):
                    missing.append(raw)
            else:
                # 未指定 ID 时，要求该子题至少存在 1 台活跃仪器
                qid = str(raw.get("question_id") or "Q1").strip()
                role = str(raw.get("instrument_role") or "").strip().upper()
                matched = any(
                    str(r["question_id"]) in (qid, "ALL") and (not role or str(r["instrument_role"]) == role)
                    for r in active_rows
                )
                if not matched:
                    missing.append(raw)
    return missing


def mark_stage1_works_checked(conn: sqlite3.Connection) -> dict[str, Any]:
    """核验 Stage 1 初始仪器客观就绪状态（全部已激活或初始清单为空）后，原子落标 `stage1_works_checked = 1`。"""
    p0 = conn.execute("SELECT contract_id, stage1_works_checked FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    if p0 is None:
        raise FailClosedError(ERR_NOT_FOUND, "尚未初始化 Parse 0 契约，无法标记 Stage 1 工造司核查完成")
    missing = compute_missing_initial_instruments(conn)
    if missing:
        return {
            "stage1_works_checked": False,
            "missing_initial_instruments": missing,
        }
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE parse0_contract SET stage1_works_checked = 1, updated_at = ? WHERE contract_id = 'active'",
            (now,),
        )
    return {
        "stage1_works_checked": True,
        "missing_initial_instruments": [],
    }


def _parse_iso_utc(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        clean = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def init_parse0_contract(
    conn: sqlite3.Connection,
    *,
    goal_and_completion_md: str = "",
    subquestions: list[str] | None = None,
    question_order: list[str] | None = None,
    initial_instruments: list[dict[str, Any]] | None = None,
    seed_families: list[dict[str, Any]] | None = None,
    total_budget: dict[str, Any] | None = None,
    min_commitment_window_sec: int = 0,
    delivery_spec_md: str = "",
    shared_inputs_rel_paths: list[str] | None = None,
    stage: str | None = None,
    epoch_id: int = 1,
    human_signed_at: str | None = None,
    autonomy_mode: str = "WAVE_CONFIRM",
) -> dict[str, Any]:
    """写入或更新 active Parse 0 六项启动契约表单（同事务自动初始化 subproblem_runtime_state）。"""
    clean_goal = str(goal_and_completion_md or "").strip()
    if not clean_goal:
        raise FailClosedError(ERR_INVALID_INPUT, "Parse 0 第 1 项 goal_and_completion_md 不可为空")
    qs: list[str] = []
    for q in (subquestions or ["Q1"]):
        val = (q.get("question_id") or q.get("id") or "") if isinstance(q, dict) else q
        s = str(val).strip()
        if s and s not in qs:
            qs.append(s)
    if not qs:
        raise FailClosedError(ERR_INVALID_INPUT, "Parse 0 第 2 项 subquestions 至少须包含 1 个非空子题标识")
    order_list = [str(q).strip() for q in (question_order or []) if str(q).strip()]
    clean_shared_inputs = [str(p).strip().replace("\\", "/") for p in (shared_inputs_rel_paths or []) if str(p).strip()]
    eff_autonomy = str(autonomy_mode or "WAVE_CONFIRM").strip().upper()
    if eff_autonomy not in ALLOWED_AUTONOMY_MODES:
        eff_autonomy = "WAVE_CONFIRM"
    now = utc_now_iso()
    signed_ts = str(human_signed_at or now)
    explicit_stage = stage if stage in ("STAGE1_PARSE0", "STAGE2_EVOLVE", "STAGE3_CONSOLIDATE", "CLOSED_VERIFIED") else None
    insert_stage = explicit_stage or "STAGE1_PARSE0"
    stage_update_sql = "stage = excluded.stage," if explicit_stage is not None else ""

    with rw_immediate_tx(conn):
        conn.execute(
            f"""
            INSERT INTO parse0_contract(
                contract_id, goal_and_completion_md, subquestions_json, question_order_json,
                initial_instruments_json, seed_families_json, total_budget_json,
                min_commitment_window_sec, delivery_spec_md, shared_inputs_json, autonomy_mode,
                human_signed_at, stage, consecutive_non_l1_handoffs, epoch_id, created_at, updated_at
            ) VALUES ('active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(contract_id) DO UPDATE SET
                goal_and_completion_md = excluded.goal_and_completion_md,
                subquestions_json = excluded.subquestions_json,
                question_order_json = excluded.question_order_json,
                initial_instruments_json = excluded.initial_instruments_json,
                seed_families_json = excluded.seed_families_json,
                total_budget_json = excluded.total_budget_json,
                min_commitment_window_sec = excluded.min_commitment_window_sec,
                delivery_spec_md = excluded.delivery_spec_md,
                shared_inputs_json = excluded.shared_inputs_json,
                autonomy_mode = excluded.autonomy_mode,
                human_signed_at = excluded.human_signed_at,
                {stage_update_sql}
                epoch_id = excluded.epoch_id,
                updated_at = excluded.updated_at
            """,
            (
                str(goal_and_completion_md or ""),
                json.dumps(qs, ensure_ascii=False),
                json.dumps(order_list, ensure_ascii=False),
                json.dumps(initial_instruments or [], ensure_ascii=False),
                json.dumps(seed_families or [], ensure_ascii=False),
                json.dumps(total_budget or {}, ensure_ascii=False),
                max(0, int(min_commitment_window_sec or 0)),
                str(delivery_spec_md or ""),
                json.dumps(clean_shared_inputs, ensure_ascii=False),
                eff_autonomy,
                signed_ts,
                insert_stage,
                int(epoch_id or 1),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO project_closure_state(id, status, verifier_final_audit_passed, updated_at)
            VALUES (1, 'OPEN', 0, ?)
            """,
            (now,),
        )
        cur_row = conn.execute("SELECT stage, latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'").fetchone()
        eff_stage = str(cur_row["stage"]) if cur_row else insert_stage
        cur_rev = int(cur_row["latest_spec_revision"] or 0) if cur_row else 0
        ensure_subproblem_rows(
            conn,
            qs,
            min_commitment_sec=max(0, int(min_commitment_window_sec or 0)),
            total_budget=total_budget,
            active_spec_revision=cur_rev,
            started_at=signed_ts,
        )

    return {
        "contract_id": "active",
        "subquestions": qs,
        "question_order": order_list,
        "shared_inputs_rel_paths": clean_shared_inputs,
        "min_commitment_window_sec": max(0, int(min_commitment_window_sec or 0)),
        "autonomy_mode": eff_autonomy,
        "stage": eff_stage,
        "human_signed_at": signed_ts,
        "epoch_id": int(epoch_id or 1),
    }


def record_human_stop(conn: sqlite3.Connection, *, note: str = "HUMAN_UI_OR_CLI_STOP") -> dict[str, Any]:
    """控制面唯一合法入口：由人类通过 UI/CLI 触发，写入不可伪造的 `human_stop_requested_at`。"""
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO project_closure_state(id, status, verifier_final_audit_passed, human_stop_requested_at, updated_at)
            VALUES (1, 'OPEN', 0, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                human_stop_requested_at = COALESCE(project_closure_state.human_stop_requested_at, excluded.human_stop_requested_at),
                updated_at = excluded.updated_at
            """,
            (now, now),
        )
        aid = f"ca_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO compliance_alerts(alert_id, stage, status, blocking_questions_json, notes, created_at)
            VALUES (?, 'CLOSURE_GATE', 'ALERT', '[]', ?, ?)
            """,
            (aid, f"控制面记录人类紧急叫停: {note}", now),
        )
    row = conn.execute("SELECT human_stop_requested_at, status FROM project_closure_state WHERE id = 1").fetchone()
    return {
        "human_stop_requested_at": str(row["human_stop_requested_at"]),
        "closure_status": str(row["status"]),
    }


def record_pending_handoff(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    mode: str,
    explorer_will_md: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """持久化探索者亲笔遗嘱（同步写入 will_md 与 explorer_will_md）与待伴随交接/抢救标记，确保宿主重启后从 SQLite 无损接续。"""
    mode_u = str(mode or "HANDOFF_70").strip().upper()
    if mode_u not in ("HANDOFF_70", "CRASH_RECOVERY"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 pending_handoff_mode={mode!r}")
    node = conn.execute("SELECT node_id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    now = utc_now_iso()
    will_text = str(explorer_will_md or "")
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET will_md = CASE WHEN ? != '' THEN ? ELSE will_md END,
                explorer_will_md = ?,
                pending_handoff_mode = ?,
                pending_handoff_reason = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (will_text, will_text, will_text, mode_u, str(reason or "")[:500], now, node_id),
        )
    return {
        "node_id": node_id,
        "pending_handoff_mode": mode_u,
        "explorer_will_chars": len(will_text),
    }


def sync_session_pressure(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    pressure_tokens: int,
    effective_context_window: int | None = None,
    context_window_tokens: int | None = None,
) -> dict[str, Any]:
    """将宿主 DSH TokenMeter 采样的真实压力水位与模型有效窗口 W = min(360k, model_window) 同步至 SQLite，并返回实时 node_status 与 control_state。"""
    row = conn.execute(
        """
        SELECT node_id, question_id, node_status, control_state, control_generation, pressure_tokens,
               personal_turn_active, human_modified, artifact_dirty_since_last_obs,
               first_reflection_unlocked, effective_context_window, pending_handoff_reason, holiday_completed
        FROM lineage_nodes
        WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在，无法同步 pressure_tokens")
    pt = max(0, int(pressure_tokens))
    raw_explicit = effective_context_window if effective_context_window is not None else context_window_tokens
    explicit_win = int(raw_explicit) if (raw_explicit and int(raw_explicit) > 0) else None
    eff_win = resolve_effective_context_window(
        conn,
        node_window=row["effective_context_window"],
        explicit_window=explicit_win,
    )
    if row["pressure_tokens"] != pt or (explicit_win is not None and row["effective_context_window"] != eff_win):
        with rw_immediate_tx(conn):
            conn.execute(
                """UPDATE lineage_nodes SET pressure_tokens=?, effective_context_window=COALESCE(?,effective_context_window),
                   updated_at=? WHERE node_id=?""",
                (pt, eff_win if explicit_win is not None else None, utc_now_iso(), node_id),
            )
    qrow = conn.execute(
        "SELECT dispatch_state, desired_state FROM subproblem_runtime_state WHERE question_id = ?",
        (str(row["question_id"]),),
    ).fetchone()
    p0_stop = conn.execute(
        "SELECT human_stop_requested_at FROM project_closure_state WHERE id = 1"
    ).fetchone()
    sig = compute_clock_signal(pt, int(row["first_reflection_unlocked"] or 0), effective_context_window=eff_win)
    return {
        "node_id": node_id,
        "question_id": str(row["question_id"]),
        "node_status": str(row["node_status"]),
        "control_state": str(row["control_state"] or "AUTO_RUNNING"),
        "pending_handoff_reason": row["pending_handoff_reason"],
        "holiday_completed": bool(row["holiday_completed"]),
        "control_generation": int(row["control_generation"] or 1),
        "personal_turn_active": bool(int(row["personal_turn_active"] or 0)),
        "human_modified": bool(int(row["human_modified"] or 0)),
        "artifact_dirty_since_last_obs": bool(int(row["artifact_dirty_since_last_obs"] or 0)),
        "subproblem_dispatch_state": str(qrow["dispatch_state"]) if qrow else "DISPATCHING",
        "human_stop_active": bool(p0_stop and str(p0_stop["human_stop_requested_at"] or "").strip()),
        **sig,
    }


def abort_lineage_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    reason: str = "ABORTED_BY_CONTROLLER",
) -> dict[str, Any]:
    """控制面精准中止指定探索节点：原子落库为 CLOSED 并清空待交接标记，释放槽位且杜绝重派。"""
    row = conn.execute(
        "SELECT node_id, question_id, branch_id, node_status, scratch_log_json FROM lineage_nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在，无法中止")
    prev_status = str(row["node_status"])
    now = utc_now_iso()
    clean_reason = str(reason or "ABORTED_BY_CONTROLLER").strip()[:400]
    try:
        scratch = json.loads(row["scratch_log_json"] or "[]")
        if not isinstance(scratch, list):
            scratch = []
    except Exception:
        scratch = []
    scratch.append({"at": now, "kind": "ABORT_NODE", "prev_status": prev_status, "reason": clean_reason})
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = 'CLOSED',
                pending_handoff_mode = NULL,
                pending_handoff_reason = ?,
                scratch_log_json = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (f"ABORTED_BY_CONTROLLER: {clean_reason}", json.dumps(scratch, ensure_ascii=False), now, node_id),
        )
    return {
        "node_id": node_id,
        "question_id": str(row["question_id"]),
        "branch_id": str(row["branch_id"]),
        "prev_status": prev_status,
        "node_status": "CLOSED",
        "reason": clean_reason,
    }


def submit_works_ticket(
    conn: sqlite3.Connection,
    *,
    question_id: str = "ALL",
    ticket_type: str = "INSTRUMENT_ERROR",
    instrument_id: str | None = None,
    description: str = "",
    source: str = "main_controller",
    reporter_session_id: str = "",
) -> dict[str, Any]:
    """向科研仪器科（works_engineering_queue）签发正式 OPEN 工单，内置三道防洪阀：

    1. **同键 OPEN 幂等合并**：同 (question_id, ticket_type, instrument_id) 已有 OPEN 工单时直接合并附加报告，绝不重复刷单；
    2. **单会话限额**：非人类/非总控角色每会话最多新开 2 张工单，防止单个探索者刷爆队列；
    3. **全院 OPEN 队列软上限**：OPEN 总数 >= 8 时拦截非总控/非人类的低优工单（PAIN_POINT / DUPLICATE_TOOL）。
    """
    desc = str(description or "").strip()
    if not desc:
        raise FailClosedError(ERR_INVALID_INPUT, "工单描述 description 不能为空")
    qid = str(question_id or "ALL").strip() or "ALL"
    ttype = str(ticket_type or "INSTRUMENT_ERROR").strip().upper()
    if ttype not in _ALLOWED_WORKS_TICKET_TYPES:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"不支持的工单类型 {ttype!r}，允许值: {sorted(_ALLOWED_WORKS_TICKET_TYPES)}",
        )
    iid = str(instrument_id).strip() if instrument_id else None
    src = str(source or "main_controller").strip() or "main_controller"
    sid = str(reporter_session_id or "").strip()
    is_privileged = src in ("main_controller", "human_ui", "gw_chief_human", "branch_handback", "chief_direct")
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        # 防洪阀 1：同键 OPEN 幂等合并（防多分支对同一仪器重复刷单）
        existing = conn.execute(
            """
            SELECT ticket_id, payload_json, created_at
            FROM works_engineering_queue
            WHERE status = 'OPEN'
              AND question_id = ?
              AND ticket_type = ?
              AND COALESCE(instrument_id, '') = COALESCE(?, '')
            ORDER BY created_at ASC LIMIT 1
            """,
            (qid, ttype, iid),
        ).fetchone()
        if existing is not None:
            try:
                old_payload = json.loads(existing["payload_json"] or "{}")
            except Exception:
                old_payload = {}
            extras = list(old_payload.get("additional_reports") or [])
            # 完整保留每一条补充报修正文（绝不截断），前端/展示层再按需折叠，确保工造司可按原描述完整复现
            if len(extras) < 20:
                extras.append({"source": src, "session_id": sid, "description": desc, "at": now})
            old_payload["additional_reports"] = extras
            old_payload["report_count"] = int(old_payload.get("report_count") or 1) + 1
            conn.execute(
                "UPDATE works_engineering_queue SET payload_json = ?, updated_at = ? WHERE ticket_id = ?",
                (json.dumps(old_payload, ensure_ascii=False), now, existing["ticket_id"]),
            )
            return {
                "ticket_id": str(existing["ticket_id"]),
                "question_id": qid,
                "ticket_type": ttype,
                "instrument_id": iid,
                "status": "OPEN",
                "source": src,
                "description": desc,
                "deduplicated": True,
                "report_count": old_payload["report_count"],
                "created_at": str(existing["created_at"]),
            }

        if not is_privileged:
            # 防洪阀 2：按在途未结案（status='OPEN'）做背压——每会话最多 2 张在途工单，结案即自动释放
            if sid:
                open_mine = [
                    str(r["ticket_id"])
                    for r in conn.execute(
                        """
                        SELECT ticket_id FROM works_engineering_queue
                        WHERE status = 'OPEN'
                          AND json_extract(payload_json, '$.reporter_session_id') = ?
                        ORDER BY created_at ASC
                        """,
                        (sid,),
                    ).fetchall()
                ]
                if len(open_mine) >= 2:
                    raise FailClosedError(
                        ERR_INVALID_INPUT,
                        f"你提交的工单（{', '.join(open_mine)}）正在由工造司处理中，请耐心等待结案后再提新单；当前请先在本地继续推进（补充同类问题可直接传相同 instrument_id 合并附加说明）。",
                    )
            # 防洪阀 3：全院 OPEN 队列 >= 8 时拦截非高优工单
            open_cnt = conn.execute(
                "SELECT COUNT(*) FROM works_engineering_queue WHERE status = 'OPEN'"
            ).fetchone()[0]
            if int(open_cnt or 0) >= 8 and ttype not in ("EXPLOIT", "INSTRUMENT_ERROR"):
                raise FailClosedError(
                    ERR_INVALID_INPUT,
                    f"工造司当前队列较忙（待处理 {open_cnt} 张），请耐心等待现有工单消化后再提低优 {ttype} 工单；紧急缺陷请标 INSTRUMENT_ERROR 或上报 gw_chief。",
                )

        tid = f"tkt_{uuid.uuid4().hex[:10]}"
        payload = {
            "source": src,
            "reporter_session_id": sid,
            "description": desc,
            "instrument_id": iid,
            "report_count": 1,
            "submitted_at": now,
        }
        conn.execute(
            """
            INSERT INTO works_engineering_queue(
                ticket_id, question_id, ticket_type, instrument_id,
                payload_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?)
            """,
            (tid, qid, ttype, iid, json.dumps(payload, ensure_ascii=False), now, now),
        )
    return {
        "ticket_id": tid,
        "question_id": qid,
        "ticket_type": ttype,
        "instrument_id": iid,
        "status": "OPEN",
        "source": src,
        "description": desc,
        "deduplicated": False,
        "report_count": 1,
        "created_at": now,
    }


def cancel_works_ticket(
    conn: sqlite3.Connection,
    *,
    ticket_id: str,
    reason: str = "",
    actor: str = "gw_chief_human",
) -> dict[str, Any]:
    """撤回/取消尚未结案的 OPEN 工单（置为 WONTFIX 并留痕），供总控或人类在误派时及时止损。"""
    tid = str(ticket_id or "").strip()
    if not tid:
        raise FailClosedError(ERR_INVALID_INPUT, "ticket_id 不能为空")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        row = conn.execute(
            "SELECT ticket_id, status, payload_json FROM works_engineering_queue WHERE ticket_id = ?",
            (tid,),
        ).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"工单 {tid!r} 不存在")
        if str(row["status"]) != "OPEN":
            raise FailClosedError(ERR_INVALID_INPUT, f"工单 {tid!r} 当前状态为 {row['status']}，仅 OPEN 工单可撤回")
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        payload["resolution"] = "WONTFIX"
        payload["cancelled_by"] = actor
        payload["cancel_reason"] = str(reason or "人类/总控主动撤单").strip()
        payload["cancelled_at"] = now
        conn.execute(
            "UPDATE works_engineering_queue SET status = 'RESOLVED', payload_json = ?, updated_at = ? WHERE ticket_id = ?",
            (json.dumps(payload, ensure_ascii=False), now, tid),
        )
    return {"ticket_id": tid, "status": "RESOLVED", "resolution": "WONTFIX", "cancel_reason": payload["cancel_reason"]}


def pass_stage1_parse0_gate(conn: sqlite3.Connection) -> dict[str, Any]:
    """裁决五：确定性 Stage 1 -> Stage 2 放行门禁（取代原 supervisory_committee 空壳角色）。

    校验 Parse 0 契约已签、初始仪器已核查 (`stage1_works_checked=1`) 且首批分支已开枝，
    满足条件后在单写者事务内毫秒级推进至 `STAGE2_EVOLVE` 并落盘 `compliance_alerts` 审计留痕。
    """
    p0 = conn.execute(
        "SELECT stage, human_signed_at, goal_and_completion_md, stage1_works_checked FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    if p0 is None:
        return {"passed": False, "stage": "STAGE1_PARSE0", "reason": "parse0_not_initialized"}
    if str(p0["stage"] or "") != "STAGE1_PARSE0":
        return {"passed": True, "stage": str(p0["stage"]), "already_advanced": True}
    if not str(p0["human_signed_at"] or "").strip() or not str(p0["goal_and_completion_md"] or "").strip():
        return {"passed": False, "stage": "STAGE1_PARSE0", "reason": "parse0_unsigned_or_empty_goal"}
    if int(p0["stage1_works_checked"] or 0) != 1:
        return {"passed": False, "stage": "STAGE1_PARSE0", "reason": "stage1_works_not_checked"}
    branch_cnt = conn.execute("SELECT COUNT(*) AS cnt FROM lineage_nodes").fetchone()
    if int(branch_cnt["cnt"] or 0) <= 0:
        return {"passed": False, "stage": "STAGE1_PARSE0", "reason": "no_initial_branch_spawned"}

    now = utc_now_iso()
    aid = f"ca_{uuid.uuid4().hex[:10]}"
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active' AND stage = 'STAGE1_PARSE0'",
            (now,),
        )
        conn.execute(
            """
            INSERT INTO compliance_alerts(alert_id, stage, status, blocking_questions_json, notes, created_at)
            VALUES (?, 'PARSE0_GATE', 'PASSED', '[]', ?, ?)
            """,
            (aid, "确定性门禁放行：Parse 0 已签、初始仪器已核查、首批正交分支已就位，推进至 STAGE2_EVOLVE。", now),
        )
    return {
        "passed": True,
        "stage": "STAGE2_EVOLVE",
        "alert_id": aid,
        "deterministic": True,
    }

