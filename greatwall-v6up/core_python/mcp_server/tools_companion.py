"""长城 V6-Up (v3.0) lineage_companion（一对一分身伴随助手）4 个单一职责窄工具。"""

from __future__ import annotations

import json
import random
import sqlite3
import uuid
from typing import Any

from .control_plane_service import extract_sanitized_code_diff_md
from .db_schema import (
    ALLOWED_COMPANION_MODES,
    ALLOWED_DEAD_END_CATEGORIES,
    ALLOWED_EVIDENCE_GRADES,
    ALLOWED_VERDICT_3STATE,
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    build_tool_receipt,
    enforce_role_tool_permission,
    load_holiday_prompts,
    load_runtime_config,
    record_fact_edge,
    resolve_effective_context_window,
)


def tool_get_companion_context(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    branch_id: str,
    node_id: str,
    mode: str,
) -> dict[str, Any]:
    """按阶段严格隔离返回伴随上下文：
    - PRE_SPAWN: 仅旧看板、上代手记与活跃 REVISE 异议（严禁下发 37% 专属目录摘要！）
    - REFLECT_37: 同步返本脉 lineage_dead_ends 摘要 + 同题 L3/L2 目录卡摘要 + 1-2 道夜科学题
    - HANDOFF_70 / CRASH_RECOVERY: 返回当前节点观测、诊断日志与快照路径。
    """
    enforce_role_tool_permission(conn, caller_role, "get_companion_context", session_id=session_id, node_id=node_id)
    mode_u = str(mode or "").strip().upper()
    if mode_u not in ALLOWED_COMPANION_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法伴随模式 {mode!r}，仅限 {sorted(ALLOWED_COMPANION_MODES)}")

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")

    qid = str(node["question_id"])
    prev_briefing = conn.execute(
        "SELECT * FROM lineage_briefings WHERE branch_id = ? ORDER BY created_at DESC LIMIT 1",
        (branch_id,),
    ).fetchone()
    parent_node = (
        conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node["parent_node_id"],)).fetchone()
        if node["parent_node_id"]
        else None
    )
    dead_ends_total = int(
        conn.execute("SELECT COUNT(*) AS cnt FROM lineage_dead_ends WHERE branch_id = ?", (branch_id,)).fetchone()["cnt"] or 0
    )

    if mode_u == "PRE_SPAWN":
        # 严守隔离铁律：PRE_SPAWN 严禁下发 37% 专属的 L3/L2 馆藏目录卡摘要或全量 dead_ends 列表！
        active_instruments = [
            {
                "instrument_id": str(r["instrument_id"]),
                "version": int(r["version"]),
                "question_id": str(r["question_id"]),
                "instrument_role": str(r["instrument_role"]),
                "artifact_schema": str(r["artifact_schema"] or "python_run"),
                "health_status": str(r["health_status"]),
            }
            for r in conn.execute(
                """
                SELECT instrument_id, version, question_id, instrument_role, artifact_schema, health_status
                FROM instruments
                WHERE is_active = 1 AND health_status = 'HEALTHY' AND (question_id = ? OR question_id = 'ALL')
                ORDER BY instrument_id, version
                """,
                (qid,),
            ).fetchall()
        ]
        payload: dict[str, Any] = {
            "mode": "PRE_SPAWN",
            "node_id": node_id,
            "branch_id": branch_id,
            "question_id": qid,
            "generation": int(node["generation"]),
            "node_status": str(node["node_status"]),
            "active_instruments": active_instruments,
            "previous_briefing": dict(prev_briefing) if prev_briefing else None,
            "latest_parent_handoff": (
                {
                    "node_id": str(parent_node["node_id"]),
                    "mechanism_summary": str(parent_node["mechanism_summary"] or ""),
                    "evidence_grade": str(parent_node["evidence_grade"]),
                    "column_a_facts_md": str(parent_node["column_a_facts_md"] or ""),
                    "will_md": str(parent_node["will_md"] or ""),
                }
                if parent_node
                else None
            ),
            "active_revision_requests": json.loads(node["last_revision_requests_json"] or "[]"),
            "retained_snapshot_abs_path": node["retained_snapshot_abs_path"],
            "lineage_dead_ends_count": dead_ends_total,
        }
        return build_tool_receipt(
            conn=conn,
            tool_name="get_companion_context",
            question_id=qid,
            node_id=node_id,
            next_step_guidance="请执行定额滚动重写 Rewrite_<=2200(旧看板, 上代最新手记) 并调 save_lineage_briefing（总长 <= 2200 字，段 5 整体替换最新遗嘱）。",
            data=payload,
        )

    if mode_u == "REFLECT_37":
        cfg = load_runtime_config()
        win = resolve_effective_context_window(conn, node_window=node["effective_context_window"], cfg=cfg)
        reflect_pct = float(cfg.get("context_reflect_hint_pct", 0.37))
        cur_tokens = int(node["pressure_tokens"] or 0)
        if cur_tokens / float(win) < reflect_pct:
            raise FailClosedError(
                ERR_LOCKED,
                f"当前上下文水位 {cur_tokens}/{win} ({cur_tokens / win:.1%}) 未达到 {reflect_pct:.0%} 阈值，严禁提前拉取 REFLECT_37 专属馆藏目录与死胡同摘要！",
            )
        all_prompts = [p for p in load_holiday_prompts() if p.get("scope") == "reflect_37"]
        sampled = random.sample(all_prompts, k=min(2, len(all_prompts))) if all_prompts else []

        # 37% 专属情报前置扫描：本脉 lineage_dead_ends 摘要 + 同题中央图书馆 L3/L2 目录卡摘要
        dead_ends_summary = [
            {
                "dead_end_id": str(r["dead_end_id"]),
                "category": str(r["category"]),
                "scope_condition_md": str(r["scope_condition_md"])[:200],
                "failure_mechanism_md": str(r["failure_mechanism_md"])[:240],
            }
            for r in conn.execute(
                "SELECT dead_end_id, category, scope_condition_md, failure_mechanism_md FROM lineage_dead_ends WHERE branch_id = ? ORDER BY created_at DESC LIMIT 12",
                (branch_id,),
            ).fetchall()
        ]
        library_catalog_preview = [
            {
                "entry_id": str(r["entry_id"]),
                "ledger_type": str(r["ledger_type"]),
                "l3_entry_kind": r["l3_entry_kind"],
                "l2_category": r["l2_category"],
                "title": str(r["title"]),
                "abstract_preview": str(r["abstract_md"])[:240],
            }
            for r in conn.execute(
                """
                SELECT entry_id, ledger_type, l3_entry_kind, l2_category, title, abstract_md
                FROM internal_research_ledger
                WHERE is_active = 1 AND question_id = ?
                ORDER BY created_at DESC LIMIT 20
                """,
                (qid,),
            ).fetchall()
        ]
        obs_rows = [
            {
                "obs_id": str(r["obs_id"]),
                "instrument_id": str(r["instrument_id"]),
                "instrument_version": int(r["instrument_version"]),
                "obs_status": str(r["obs_status"]),
                "tracks": json.loads(r["tracks_json"] or "{}"),
            }
            for r in conn.execute(
                "SELECT obs_id, instrument_id, instrument_version, obs_status, tracks_json FROM observations WHERE node_id = ? ORDER BY created_at ASC",
                (node_id,),
            ).fetchall()
        ]

        return build_tool_receipt(
            conn=conn,
            tool_name="get_companion_context",
            question_id=qid,
            node_id=node_id,
            next_step_guidance="请切换外部严苛专家视角（临床诊断师 + 情报员），给盲区诊断、最多 2 条相关 L2/L3 或死胡同编号指针与 1 道夜科学追问（严禁给代码/排序/配额！），完成 <=2 轮后调 record_reflection_and_unlock_pull。",
            data={
                "mode": "REFLECT_37",
                "node_id": node_id,
                "branch_id": branch_id,
                "question_id": qid,
                "pressure_tokens": int(node["pressure_tokens"] or 0),
                "observations": obs_rows,
                "lineage_dead_ends_summary": dead_ends_summary,
                "central_library_l3_l2_catalog_preview": library_catalog_preview,
                "sampled_holiday_prompts": sampled,
            },
        )

    # HANDOFF_70 / CRASH_RECOVERY
    obs_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT obs_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text, created_at FROM observations WHERE node_id = ? ORDER BY created_at ASC",
            (node_id,),
        ).fetchall()
    ]
    probes = [
        dict(r)
        for r in conn.execute(
            "SELECT probe_id, instrument_id, status, tracks_json, details_text, created_at FROM probe_diagnostic_logs WHERE node_id = ? ORDER BY created_at DESC LIMIT 15",
            (node_id,),
        ).fetchall()
    ]
    return build_tool_receipt(
        conn=conn,
        tool_name="get_companion_context",
        question_id=qid,
        node_id=node_id,
        next_step_guidance="请对照探索者亲笔遗嘱（如有）、Worktree Diff 与客观 [Obs###] 写 <2000 字 A/B 双栏手记、<100 字纯 mechanism_summary 与结构化 dead_ends，调 submit_node_handoff 落库。",
        data={
            "mode": mode_u,
            "node_id": node_id,
            "branch_id": branch_id,
            "question_id": qid,
            "worktree_abs_path": str(node["worktree_abs_path"]),
            "retained_snapshot_abs_path": node["retained_snapshot_abs_path"],
            "explorer_will_md": str(node["will_md"] or node["explorer_will_md"] or ""),
            "pending_handoff_mode": node["pending_handoff_mode"],
            "pending_handoff_reason": str(node["pending_handoff_reason"] or ""),
            "observations": obs_rows,
            "probe_diagnostic_logs": probes,
            "reflections": json.loads(node["reflections_json"] or "[]"),
        },
    )


def tool_save_lineage_briefing(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    branch_id: str,
    node_id: str,
    sec1_mechanism: str,
    sec2_verified_baseline: str,
    sec3_bottleneck: str,
    sec4_dead_ends: str,
    sec5_immediate_will: str,
) -> dict[str, Any]:
    """定额滚动重压缩看板：唯一硬限制为五段非空且总长 <= 2200 字（五段配比仅软参考，严禁切片截断）。"""
    enforce_role_tool_permission(conn, caller_role, "save_lineage_briefing", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, branch_id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")

    sections = {
        "sec1_mechanism": str(sec1_mechanism or "").strip(),
        "sec2_verified_baseline": str(sec2_verified_baseline or "").strip(),
        "sec3_bottleneck": str(sec3_bottleneck or "").strip(),
        "sec4_dead_ends": str(sec4_dead_ends or "").strip(),
        "sec5_immediate_will": str(sec5_immediate_will or "").strip(),
    }
    for name, text in sections.items():
        if not text or len(text) < 2:
            raise FailClosedError(ERR_INVALID_INPUT, f"看板段落 {name!r} 不可为空或仅标点占位")

    cfg = load_runtime_config()
    max_total = int(cfg.get("max_briefing_chars", 2200))
    total_chars = sum(len(v) for v in sections.values())
    if total_chars > max_total:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"定额滚动重写看板总字数超限：{total_chars} > {max_total} 字！严禁静默切片，请按压缩规则（替换旧遗嘱、折叠旧过程、旧死胡同下沉至 lineage_dead_ends）精简后重写。",
        )

    bid = f"brf_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO lineage_briefings(
                briefing_id, branch_id, node_id,
                sec1_mechanism, sec2_verified_baseline, sec3_bottleneck, sec4_dead_ends, sec5_immediate_will,
                total_chars, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bid,
                branch_id,
                node_id,
                sections["sec1_mechanism"],
                sections["sec2_verified_baseline"],
                sections["sec3_bottleneck"],
                sections["sec4_dead_ends"],
                sections["sec5_immediate_will"],
                total_chars,
                now,
            ),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="save_lineage_briefing",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance=f"看板 {bid} 已落库（总长 {total_chars}/{max_total} 字），伴随暂停挂起，探索者现已就绪启动。",
        data={"briefing_id": bid, "total_chars": total_chars, "max_briefing_chars": max_total},
    )


def tool_record_reflection_and_unlock_pull(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    selected_categories: list[str],
    holiday_prompt_id: int,
    turns: list[dict[str, Any]],
    verdict_3state: str,
) -> dict[str, Any]:
    """记录 37% 元反思并当场置位 `first_reflection_unlocked = 1`（v3.0 彻底废除 `eval_count >= 1` 门槛！）。"""
    enforce_role_tool_permission(conn, caller_role, "record_reflection_and_unlock_pull", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")

    cfg = load_runtime_config()
    window = resolve_effective_context_window(conn, node_window=node["effective_context_window"], cfg=cfg)
    reflect_pct = float(cfg.get("context_reflect_hint_pct", 0.37))
    pressure = int(node["pressure_tokens"] or 0)
    if pressure / float(max(1, window)) < reflect_pct:
        raise FailClosedError(
            ERR_LOCKED,
            f"当前上下文水位 {pressure}/{window} ({pressure/window:.1%}) 未达到 {reflect_pct:.0%} 反思阈值，严禁提前解锁内藏！",
        )

    if not isinstance(selected_categories, list) or not selected_categories:
        raise FailClosedError(ERR_INVALID_INPUT, "selected_categories 必须包含至少第 7 类 Attractor Tasks")
    has_attractor = any("7" in str(c) or "attractor" in str(c).lower() for c in selected_categories)
    if not has_attractor:
        raise FailClosedError(ERR_INVALID_INPUT, "每次 37% 元反思必查第 7 类 Attractor Tasks（selected_categories 缺失）")

    if isinstance(holiday_prompt_id, bool) or not isinstance(holiday_prompt_id, int) or not (1 <= holiday_prompt_id <= 28):
        raise FailClosedError(ERR_INVALID_INPUT, "holiday_prompt_id 必须为 1–28 之间的整数（第 29 条专供全局停滞/监察委）")

    max_turns = int(cfg.get("reflection_max_turns", 2))
    max_chars_turn = int(cfg.get("reflection_max_chars_per_turn", 300))
    if not isinstance(turns, list) or len(turns) == 0 or len(turns) > max_turns:
        raise FailClosedError(ERR_INVALID_INPUT, f"turns 必须包含 1 到 {max_turns} 轮精简问答")
    for idx, t in enumerate(turns):
        if not isinstance(t, dict) or not str(t.get("question", "")).strip() or not str(t.get("answer", "")).strip():
            raise FailClosedError(ERR_INVALID_INPUT, f"turns[{idx}] 必须同时包含非空 question 与 answer")
        if len(str(t["question"]).strip()) > max_chars_turn or len(str(t["answer"]).strip()) > max_chars_turn:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"turns[{idx}] 问答超出每轮 <= {max_chars_turn} 字精简约束",
            )

    verdict_u = str(verdict_3state or "").strip().upper()
    if verdict_u not in ALLOWED_VERDICT_3STATE:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 verdict_3state={verdict_3state!r}，仅允许 {sorted(ALLOWED_VERDICT_3STATE)}")

    existing = json.loads(node["reflections_json"] or "[]")
    now = utc_now_iso()
    existing.append(
        {
            "at": now,
            "selected_categories": [str(c) for c in selected_categories],
            "holiday_prompt_id": holiday_prompt_id,
            "turns": turns,
            "verdict_3state": verdict_u,
        }
    )

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET first_reflection_unlocked = 1, reflections_json = ?, updated_at = ?
            WHERE node_id = ?
            """,
            (json.dumps(existing, ensure_ascii=False), now, node_id),
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="record_reflection_and_unlock_pull",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance="37% 元反思已落库并当场置位 first_reflection_unlocked = 1！伴随暂停挂起，探索者已解锁全馆 L3/L2 与本脉 DAG/dead_ends。",
        data={"node_id": node_id, "first_reflection_unlocked": 1, "verdict_3state": verdict_u},
    )


def tool_submit_node_handoff(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    question_id: str,
    mechanism_summary: str,
    evidence_grade: str,
    column_a_facts_md: str,
    column_b_hypothesis_md: str,
    will_md: str,
    obs_ids: list[str] | None = None,
    dead_ends: list[dict[str, Any]] | None = None,
    candidate_rel_path: str | None = None,
    is_empty_crash: bool = False,
    tool_pain_point: str | None = None,
) -> dict[str, Any]:
    """伴随助手独占单写 DAG 页与 `lineage_dead_ends` 只追加表（v3.0 支持纯推导 ARTIFACT_ONLY 与空崩溃分流）。"""
    enforce_role_tool_permission(conn, caller_role, "submit_node_handoff", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id) or str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_AUTH, "branch_id 或 question_id 与节点注册记录不一致")

    # 严禁静默吞稿：仅当已交接且提交内容与已落库内容一致时才幂等跳过；
    # 若节点早已被关停/中止却试图写入截然不同的新成果，显式报错 ERR_LOCKED！
    cur_status = str(node["node_status"])
    if cur_status in ("AWAITING_TRIAGE", "PENDING_REVIEW", "BLOCKED_L4B", "SEALED", "CLOSED"):
        norm_obs = json.dumps([str(o).strip() for o in (obs_ids or []) if str(o).strip()], ensure_ascii=False)
        same_content = (
            str(node["mechanism_summary"] or "").strip() == str(mechanism_summary or "").strip()
            and str(node["evidence_grade"] or "").strip().upper() == str(evidence_grade or "").strip().upper()
            and str(node["column_a_facts_md"] or "").strip() == str(column_a_facts_md or "").strip()
            and str(node["column_b_hypothesis_md"] or "").strip() == str(column_b_hypothesis_md or "").strip()
            and str(node["will_md"] or "").strip() == str(will_md or "").strip()
            and str(node["candidate_rel_path"] or "").strip() == str(candidate_rel_path or "").strip()
            and str(node["bound_obs_ids_json"] or "[]") == norm_obs
        )
        if same_content:
            return build_tool_receipt(
                conn=conn,
                tool_name="submit_node_handoff",
                question_id=question_id,
                node_id=node_id,
                next_step_guidance=f"节点 {node_id} 已于此前提交相同交接内容（当前状态 {cur_status}），幂等跳过重复写入。",
                data={"node_id": node_id, "node_status": cur_status, "idempotent_skip": True},
            )
        raise FailClosedError(
            ERR_LOCKED,
            f"节点 {node_id!r} 已处于终态/锁态 ({cur_status})，拒绝静默覆盖或丢弃新交接成果；请勿在已关闭节点上重复提交，由后勤/编排器在新节点推进。",
        )

    now = utc_now_iso()

    # 仅真正一字未产空崩溃（is_empty_crash=True）才进 scratch_log 而不进正式 DAG
    if bool(is_empty_crash):
        scratch = json.loads(node["scratch_log_json"] or "[]")
        scratch.append(
            {
                "at": now,
                "reason": "empty_crash",
                "summary": str(column_a_facts_md or will_md or "empty crash")[:400],
            }
        )
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE lineage_nodes SET node_status = 'CLOSED', evidence_grade = 'NONE', pending_handoff_mode = NULL, pending_handoff_reason = '', scratch_log_json = ?, updated_at = ? WHERE node_id = ?",
                (json.dumps(scratch, ensure_ascii=False), now, node_id),
            )
            if tool_pain_point and str(tool_pain_point).strip():
                _enqueue_pain_point(conn, question_id, node_id, str(tool_pain_point).strip(), now)
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_node_handoff",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance="一字未产空崩溃已记入 scratch_log 并关闭该代节点，避免空白记录污染谱系 DAG。",
            data={"node_id": node_id, "node_status": "CLOSED", "is_empty_crash": True},
        )

    mech = str(mechanism_summary or "").strip()
    if not mech or len(mech) >= 100:
        raise FailClosedError(ERR_INVALID_INPUT, f"mechanism_summary 必填且必须 < 100 字的纯核心机制（实收 {len(mech)} 字，严禁写分数或冗长叙述）")

    grade = str(evidence_grade or "").strip().upper()
    if grade not in ALLOWED_EVIDENCE_GRADES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 evidence_grade={evidence_grade!r}，仅允许 {sorted(ALLOWED_EVIDENCE_GRADES)}")

    col_a = str(column_a_facts_md or "").strip()
    col_b = str(column_b_hypothesis_md or "").strip()
    will = str(will_md or "").strip()
    if not col_a or not col_b or not will:
        raise FailClosedError(ERR_INVALID_INPUT, "column_a_facts_md、column_b_hypothesis_md 与 will_md 必须非空")

    cfg = load_runtime_config()
    max_handoff = int(cfg.get("max_handoff_chars", 2000))
    total_note_chars = len(col_a) + len(col_b) + len(will)
    if total_note_chars > max_handoff:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"交接手记总字数超限：{total_note_chars} > {max_handoff} 字，请精简去废话后提交。",
        )

    clean_obs_ids = [str(o).strip() for o in (obs_ids or []) if str(o).strip()]
    for oid in clean_obs_ids:
        row = conn.execute("SELECT obs_id, node_id FROM observations WHERE obs_id = ?", (oid,)).fetchone()
        if row is None or str(row["node_id"]) != node_id:
            raise FailClosedError(ERR_NOT_FOUND, f"声明绑定的正式观测 {oid!r} 不存在或不属于节点 {node_id!r}（严禁将 probe 日志混入 obs_ids）")
    if grade == "MEASURED" and not clean_obs_ids:
        raise FailClosedError(ERR_INVALID_INPUT, "evidence_grade='MEASURED' 时必须绑定至少 1 条真实 [Obs###]（纯推导/反例脚本请设 ARTIFACT_ONLY）")

    # 校验并整理只追加的 dead_ends
    clean_dead_ends: list[dict[str, Any]] = []
    for idx, de in enumerate(dead_ends or []):
        if not isinstance(de, dict):
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}] 必须为对象")
        cat = str(de.get("category") or "").strip().upper()
        if cat not in ALLOWED_DEAD_END_CATEGORIES:
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}].category={cat!r} 非法，仅允许 {sorted(ALLOWED_DEAD_END_CATEGORIES)}")
        scope_md = str(de.get("scope_condition_md") or "").strip()
        fail_md = str(de.get("failure_mechanism_md") or "").strip()
        if not scope_md or not fail_md:
            raise FailClosedError(ERR_INVALID_INPUT, f"dead_ends[{idx}] 必须包含非空 scope_condition_md 与 failure_mechanism_md")
        clean_dead_ends.append(
            {
                "category": cat,
                "scope_condition_md": scope_md,
                "failure_mechanism_md": fail_md,
                "bound_obs_id": str(de["bound_obs_id"]).strip() if de.get("bound_obs_id") else None,
            }
        )

    sanitized_diff = extract_sanitized_code_diff_md(
        worktree_abs_path=str(node["worktree_abs_path"]),
        candidate_rel_path=candidate_rel_path,
        previous_snapshot_abs_path=node["retained_snapshot_abs_path"],
    )

    inserted_dead_end_ids: list[str] = []
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = 'AWAITING_TRIAGE',
                mechanism_summary = ?,
                evidence_grade = ?,
                column_a_facts_md = ?,
                column_b_hypothesis_md = ?,
                will_md = ?,
                sanitized_code_diff_md = ?,
                candidate_rel_path = ?,
                bound_obs_ids_json = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                mech,
                grade,
                col_a,
                col_b,
                will,
                sanitized_diff,
                candidate_rel_path,
                json.dumps(clean_obs_ids, ensure_ascii=False),
                now,
                node_id,
            ),
        )
        conn.execute(
            "UPDATE lineage_nodes SET pending_handoff_mode = NULL, pending_handoff_reason = '' WHERE node_id = ?",
            (node_id,),
        )
        for de in clean_dead_ends:
            de_id = f"de_{uuid.uuid4().hex[:10]}"
            conn.execute(
                """
                INSERT INTO lineage_dead_ends(
                    dead_end_id, question_id, branch_id, node_id, category,
                    scope_condition_md, failure_mechanism_md, bound_obs_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    de_id,
                    question_id,
                    branch_id,
                    node_id,
                    de["category"],
                    de["scope_condition_md"],
                    de["failure_mechanism_md"],
                    de["bound_obs_id"],
                    now,
                ),
            )
            inserted_dead_end_ids.append(de_id)
        if tool_pain_point and str(tool_pain_point).strip():
            _enqueue_pain_point(conn, question_id, node_id, str(tool_pain_point).strip(), now)
        record_fact_edge(
            conn,
            source_id=node_id,
            target_id="submit_node_handoff",
            edge_type="USED_TOOL",
            session_id=session_id,
            metadata={"role": caller_role, "evidence_grade": grade},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_node_handoff",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance=f"节点 {node_id} 正式 DAG 页已落库并置为 AWAITING_TRIAGE（同步追加 {len(inserted_dead_end_ids)} 条 dead_ends），等待后勤总管分诊。",
        data={
            "node_id": node_id,
            "node_status": "AWAITING_TRIAGE",
            "evidence_grade": grade,
            "inserted_dead_end_ids": inserted_dead_end_ids,
            "has_sanitized_diff": bool(sanitized_diff),
        },
    )


def _enqueue_pain_point(conn: sqlite3.Connection, question_id: str, node_id: str, text: str, now: str) -> None:
    tid = f"tkt_{uuid.uuid4().hex[:10]}"
    conn.execute(
        """
        INSERT INTO works_engineering_queue(ticket_id, question_id, ticket_type, instrument_id, payload_json, status, created_at, updated_at)
        VALUES (?, ?, 'PAIN_POINT', NULL, ?, 'OPEN', ?, ?)
        """,
        (tid, question_id, json.dumps({"node_id": node_id, "description": text}, ensure_ascii=False), now, now),
    )
