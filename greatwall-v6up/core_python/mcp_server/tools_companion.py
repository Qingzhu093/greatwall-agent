"""V6-Up (v2.2) lineage_companion（伴随助手）4 个窄工具（看板/37%问答解锁/Single-Writer DAG交接）。"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from evaluators.isolated_runner import (
    run_isolated_evaluation,
    sha256_canonical_json,
    sha256_file,
)

from .control_plane_service import (
    backup_retained_candidate_snapshot,
    extract_sanitized_code_diff_md,
    safe_resolve_in_worktree,
    scan_worktree_tools_manifest,
)
from .db_schema import (
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    sanitize_fts5_query,
    utc_now_iso,
)
from .mcp_core_helpers import (
    VALID_VERDICT_3STATE,
    build_tool_receipt,
    compute_clock_warnings_and_guidance,
    core_python_root,
    enforce_role_tool_permission,
    load_runtime_config,
    record_claim_edge,
    record_fact_edge,
    resolve_claimed_refs_list,
    sample_holiday_candidates_for_reflect37,
)
from .tools_explorer import _next_ticket_id

# ==============================================================================
# 角色 2：lineage_companion（4 个窄工具）
# ==============================================================================


def tool_get_companion_context(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    branch_id: str,
    node_id: str,
    mode: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_companion_context", session_id=session_id, node_id=node_id)
    mode_u = (mode or "").strip().upper()
    if mode_u not in ("PRE_SPAWN", "REFLECT_37", "HANDOFF_70"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法伴随模式 {mode!r}，仅限 PRE_SPAWN / REFLECT_37 / HANDOFF_70")

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != branch_id:
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")

    qid = str(node["question_id"])
    parent = (
        conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node["parent_node_id"],)).fetchone()
        if node["parent_node_id"]
        else None
    )
    obs_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT obs_id, obs_status, passed, metrics_json, details_text, linguistic_prediction, candidate_hash FROM observations WHERE node_id = ? ORDER BY created_at ASC",
            (node_id,),
        ).fetchall()
    ]
    l2_l3_hints = [
        {
            "entry_id": str(r["entry_id"]),
            "ledger_type": str(r["ledger_type"]),
            "title": str(r["title"]),
            "abstract_md": str(r["abstract_md"]),
        }
        for r in conn.execute(
            "SELECT entry_id, ledger_type, title, abstract_md FROM internal_research_ledger WHERE question_id = ? AND ledger_status = 'active' ORDER BY created_at DESC LIMIT 8",
            (qid,),
        ).fetchall()
    ]

    ep = conn.execute("SELECT goal_md, contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    q_contract = contracts.get(qid, {}) if isinstance(contracts, dict) else {}
    recent_errors = [
        {
            "obs_id": str(o["obs_id"]),
            "obs_status": str(o["obs_status"]),
            "details_text": str(o["details_text"] or ""),
        }
        for o in obs_rows
        if str(o.get("obs_status", "")) == "EXECUTION_ERROR" or not bool(o.get("passed"))
    ]

    data: dict[str, Any] = {
        "mode": mode_u,
        "node_id": node_id,
        "branch_id": branch_id,
        "question_id": qid,
        "epoch_goal_md": str(ep["goal_md"] or "") if ep else "",
        "question_contract": q_contract,
        "worktree_abs_path": str(node["worktree_abs_path"]),
        "retained_candidate_id": str(node["retained_candidate_id"] or ""),
        "retained_snapshot_abs_path": str(node["retained_snapshot_abs_path"] or ""),
        "current_briefing_md": str(node["briefing_snapshot_md"] or ""),
        "column_b_hypothesis_md": str(node["column_b_hypothesis_md"] or ""),
        "sanitized_code_diff_md": str(node["sanitized_code_diff_md"] or ""),
        "recent_errors": recent_errors,
        "node_observations": obs_rows,
        "internal_ledger_index_hints": l2_l3_hints,
        "worktree_tools_manifest": scan_worktree_tools_manifest(str(node["worktree_abs_path"])),
    }

    if mode_u == "PRE_SPAWN":
        fam = conn.execute(
            "SELECT mechanism_signature, orthogonal_contrast FROM method_families WHERE question_id = ? AND family_id = ?",
            (qid, node["family_id"]),
        ).fetchone()
        data["method_family"] = dict(fam) if fam else {"family_id": node["family_id"]}
        data["previous_briefing_md"] = str(parent["briefing_snapshot_md"] if parent else "")
        data["latest_ancestor_handoff"] = (
            {
                "node_id": str(parent["node_id"]),
                "column_a_facts_md": str(parent["column_a_facts_md"]),
                "column_b_hypothesis_md": str(parent["column_b_hypothesis_md"]),
                "will_md": str(parent["will_md"]),
            }
            if parent
            else None
        )
        guidance = "请基于旧看板与刚退场手记按五段预算 (<=2200字) 调用 save_lineage_briefing 合成新看板。"
    elif mode_u == "REFLECT_37":
        data["holiday_candidates"] = sample_holiday_candidates_for_reflect37(count=2)
        guidance = (
            "已从夜科学 1–28 题随机推送 2 道候选。请切换外部严格人类学者视角，围绕必查第 7 类 Attractor Tasks + 1 项症状类别 + 1 道夜科学追问进行 <=2 轮(每轮<=300字)短问答后调 record_reflection_and_unlock_pull。"
        )
    else:
        wt_path = Path(str(node["worktree_abs_path"]))
        files_on_disk = []
        if wt_path.is_dir():
            for f in sorted(wt_path.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    files_on_disk.append(f.relative_to(wt_path).as_posix())
        data["worktree_files"] = files_on_disk
        guidance = (
            "请扫描 worktree 文件与 [Obs###] 收据、打捞未提交的 [Local-Sweep] 失灵边界，调 submit_node_handoff 独家写入谱系 DAG（若零实测崩溃则设 is_zero_eval_crash=true）。"
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="get_companion_context",
        node_id=node_id,
        question_id=qid,
        next_step_guidance=guidance,
        data=data,
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
    enforce_role_tool_permission(conn, caller_role, "save_lineage_briefing", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, branch_id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != branch_id:
        raise FailClosedError(ERR_AUTH, f"节点 {node_id!r} 不属于分支 {branch_id!r}")

    secs = [
        ("sec1_mechanism", sec1_mechanism),
        ("sec2_verified_baseline", sec2_verified_baseline),
        ("sec3_bottleneck", sec3_bottleneck),
        ("sec4_dead_ends", sec4_dead_ends),
        ("sec5_immediate_will", sec5_immediate_will),
    ]
    for name, text in secs:
        cleaned = str(text or "").strip()
        if not cleaned or not cleaned.strip(".-_*# \t\r\n。，,；;"):
            raise FailClosedError(ERR_INVALID_INPUT, f"五段定额看板字段 {name!r} 不可为空或仅标点占位")

    cfg = load_runtime_config()
    max_chars = int(cfg.get("max_briefing_chars", 2200))
    total_raw_len = sum(len(str(t).strip()) for _, t in secs)
    if total_raw_len > max_chars:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"五段看板正文合计 {total_raw_len} 字符，超过 max_briefing_chars={max_chars}（严禁截断，请提炼压缩冗余形容词后重传，务必保住第4段历史死胡同与第5段科研遗嘱）",
        )

    composed = "\n\n".join(
        [
            f"### 1. 本学派核心机制\n{sec1_mechanism.strip()}",
            f"### 2. 已证实前提与 Retained Candidate\n{sec2_verified_baseline.strip()}",
            f"### 3. 当前悬而未决的核心矛盾\n{sec3_bottleneck.strip()}",
            f"### 4. 历代全量已踩反例与失灵边界\n{sec4_dead_ends.strip()}",
            f"### 5. 上代《科研遗嘱》待办最小鉴别实验\n{sec5_immediate_will.strip()}",
        ]
    )
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE lineage_nodes SET briefing_snapshot_md = ?, updated_at = ? WHERE node_id = ?",
            (composed, now, node_id),
        )
        record_fact_edge(
            conn, src_id=node_id, dst_id="tool:save_lineage_briefing", edge_type="USED_TOOL", metadata={"total_raw_len": total_raw_len}
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="save_lineage_briefing",
        node_id=node_id,
        question_id=str(node["question_id"]),
        next_step_guidance="五段增量看板已就绪，请立即结束本回合，控制面将启动新一代无状态探索者。",
        data={"node_id": node_id, "char_count": total_raw_len, "max_briefing_chars": max_chars},
    )


def tool_record_reflection_and_unlock_pull(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    selected_categories: list[str],
    holiday_prompt_id: int,
    turns: list[dict[str, str]],
    verdict_3state: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(
        conn, caller_role, "record_reflection_and_unlock_pull", session_id=session_id, node_id=node_id
    )
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")

    cfg = load_runtime_config()
    ctx_win = int(cfg.get("context_window_tokens", 500000))
    reflect_pct = float(cfg.get("context_reflect_hint_pct", 0.37))
    pressure_tokens = int(node["pressure_tokens"] or 0)
    pressure_ratio = pressure_tokens / float(max(1, ctx_win))
    if pressure_ratio + 1e-9 < reflect_pct:
        raise FailClosedError(
            ERR_LOCKED,
            f"37% 水位门禁拦截：节点 {node_id!r} 当前物理 Token 水位 {pressure_tokens}/{ctx_win} ({pressure_ratio:.1%}) < {reflect_pct:.0%}，禁止提前解锁内藏库！",
        )
    min_evals = int(cfg.get("min_evals_before_reflection", 1))
    if int(node["eval_count"] or 0) < min_evals:
        raise FailClosedError(
            ERR_LOCKED,
            f"节点 {node_id!r} 尚未完成至少 {min_evals} 次真实实验 (eval_count={node['eval_count']})，禁止空洞反思解锁！",
        )

    if not isinstance(selected_categories, list) or not selected_categories:
        raise FailClosedError(ERR_INVALID_INPUT, "selected_categories 必须包含至少第 7 类 Attractor Tasks")
    if not any("attractor" in str(c).lower() or "7" in str(c) for c in selected_categories):
        raise FailClosedError(ERR_INVALID_INPUT, "每次 37% 元反思必查第 7 类 Attractor Tasks（selected_categories 缺失）")

    if isinstance(holiday_prompt_id, bool) or not isinstance(holiday_prompt_id, int) or not (1 <= holiday_prompt_id <= 28):
        raise FailClosedError(ERR_INVALID_INPUT, "holiday_prompt_id 必须为 1–28 之间的整数（第 29 条专供全局停滞/监察委）")

    max_turns = int(cfg.get("reflection_max_turns", 2))
    max_turn_chars = int(cfg.get("reflection_max_chars_per_turn", 300))
    if not isinstance(turns, list) or len(turns) == 0 or len(turns) > max_turns:
        raise FailClosedError(ERR_INVALID_INPUT, f"turns 必须包含 1 到 {max_turns} 轮精简问答")

    for i, t in enumerate(turns):
        if not isinstance(t, dict) or not str(t.get("question", "")).strip() or not str(t.get("answer", "")).strip():
            raise FailClosedError(ERR_INVALID_INPUT, f"turns[{i}] 必须同时包含非空 question 与 answer")
        q_len = len(str(t["question"]).strip())
        a_len = len(str(t["answer"]).strip())
        if q_len > max_turn_chars or a_len > max_turn_chars:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"turns[{i}] 超出单轮 <= {max_turn_chars} 字硬限 (question={q_len}, answer={a_len})，严禁大作文拖垮探索窗口！",
            )

    if verdict_3state not in VALID_VERDICT_3STATE:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"verdict_3state 非法 {verdict_3state!r}，仅允许 {sorted(VALID_VERDICT_3STATE)}",
        )

    existing = json.loads(node["reflections_json"] or "[]")
    record = {
        "holiday_prompt_id": holiday_prompt_id,
        "selected_categories": selected_categories,
        "turns": turns,
        "verdict_3state": verdict_3state,
        "recorded_at": utc_now_iso(),
    }
    existing.append(record)
    now = utc_now_iso()

    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE lineage_nodes
            SET first_reflection_unlocked = 1,
                reflections_json = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (json.dumps(existing, ensure_ascii=False), now, node_id),
        )
        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id="tool:record_reflection_and_unlock_pull",
            edge_type="USED_TOOL",
            metadata={"holiday_prompt_id": holiday_prompt_id, "verdict_3state": verdict_3state},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="record_reflection_and_unlock_pull",
        node_id=node_id,
        question_id=str(node["question_id"]),
        next_step_guidance="37% 反思已落库且 first_reflection_unlocked=1 已激活！请结束回合交还探索者继续 37-70% 攻坚。",
        data={"node_id": node_id, "first_reflection_unlocked": 1, "verdict_3state": verdict_3state},
    )


def tool_submit_node_handoff(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    question_id: str,
    column_a_facts_md: str,
    column_b_hypothesis_md: str,
    will_md: str,
    obs_ids: list[str],
    candidate_rel_path: str | None = None,
    is_zero_eval_crash: bool = False,
    tool_pain_point: str | None = None,
) -> dict[str, Any]:
    """伴随助手独占 Single-Writer DAG 交接（自动抽脱敏 Diff + 双通道痛点单 + 零实测隔离入 scratch_log）。"""
    enforce_role_tool_permission(conn, caller_role, "submit_node_handoff", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != branch_id or str(node["question_id"]) != question_id:
        raise FailClosedError(ERR_AUTH, "branch_id 或 question_id 与节点注册记录不一致")

    now = utc_now_iso()
    has_pain_point = bool(pain_ticket := None)
    pain_text = str(tool_pain_point).strip() if tool_pain_point else ""

    # 无论成功还是崩溃，后端都提取脱敏核心代码 Diff
    sanitized_diff = extract_sanitized_code_diff_md(
        worktree_abs_path=str(node["worktree_abs_path"]),
        candidate_rel_path=candidate_rel_path,
        snapshot_abs_path=str(node["retained_snapshot_abs_path"] or ""),
        branch_id=branch_id,
        node_id=node_id,
    )

    if is_zero_eval_crash:
        # 边界反例 #2：零实测崩溃节点绝不污染主谱系 DAG，记入 scratch_log 并保留 CLOSED
        scratch = json.loads(node["scratch_log_json"] or "[]")
        scratch.append(
            {
                "type": "ZERO_EVAL_CRASH",
                "summary": (column_a_facts_md or "").strip(),
                "candidate_rel_path": candidate_rel_path,
                "recorded_at": now,
            }
        )
        with rw_immediate_tx(conn):
            if pain_text:
                pain_ticket = _next_ticket_id(conn)
                conn.execute(
                    """
                    INSERT INTO works_engineering_queue(
                        ticket_id, question_id, node_id, source_type, description_md, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'COMPANION_PAIN_POINT', ?, 'OPEN', ?, ?)
                    """,
                    (pain_ticket, question_id, node_id, pain_text, now, now),
                )
            conn.execute(
                """
                UPDATE lineage_nodes
                SET node_status = 'CLOSED',
                    scratch_log_json = ?,
                    sanitized_code_diff_md = ?,
                    updated_at = ?
                WHERE node_id = ?
                """,
                (json.dumps(scratch, ensure_ascii=False), sanitized_diff, now, node_id),
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="submit_node_handoff",
            node_id=node_id,
            question_id=question_id,
            next_step_guidance="零实测崩溃已隔离记录至 scratch_log（未污染主 DAG 与看板），控制面可直接重拉干净会话。",
            data={"node_id": node_id, "quarantined_to_scratch_log": True, "pain_ticket": pain_ticket},
        )

    cfg = load_runtime_config()
    max_handoff = int(cfg.get("max_handoff_chars", 2000))
    total_chars = len((column_a_facts_md or "").strip()) + len((column_b_hypothesis_md or "").strip()) + len((will_md or "").strip())
    if total_chars > max_handoff:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"A 栏 + B 栏 + 遗嘱合计 {total_chars} 字，超出 max_handoff_chars={max_handoff}，请提纯后重交",
        )
    if not (column_a_facts_md or "").strip() or not (column_b_hypothesis_md or "").strip() or not (will_md or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "column_a_facts_md、column_b_hypothesis_md 与 will_md 必须非空")

    verified_obs: list[str] = []
    for oid in obs_ids or []:
        row = conn.execute(
            "SELECT obs_id FROM observations WHERE obs_id = ? AND node_id = ?",
            (oid, node_id),
        ).fetchone()
        if row is None:
            raise FailClosedError(ERR_NOT_FOUND, f"声明绑定的实测 {oid!r} 不存在或不属于节点 {node_id!r}")
        verified_obs.append(str(row["obs_id"]))

    if not verified_obs:
        raise FailClosedError(ERR_INVALID_INPUT, "正式 DAG 交接必须绑定 >= 1 条真实 [Obs###]（零实测崩溃请设 is_zero_eval_crash=true）")

    with rw_immediate_tx(conn):
        if pain_text:
            pain_ticket = _next_ticket_id(conn)
            conn.execute(
                """
                INSERT INTO works_engineering_queue(
                    ticket_id, question_id, node_id, source_type, description_md, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'COMPANION_PAIN_POINT', ?, 'OPEN', ?, ?)
                """,
                (pain_ticket, question_id, node_id, pain_text, now, now),
            )
        conn.execute(
            """
            UPDATE lineage_nodes
            SET node_status = 'AWAITING_TRIAGE',
                column_a_facts_md = ?,
                column_b_hypothesis_md = ?,
                will_md = ?,
                sanitized_code_diff_md = ?,
                bound_obs_ids_json = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (
                column_a_facts_md.strip(),
                column_b_hypothesis_md.strip(),
                will_md.strip(),
                sanitized_diff,
                json.dumps(verified_obs, ensure_ascii=False),
                now,
                node_id,
            ),
        )
        conn.execute("DELETE FROM lineage_fts WHERE node_id = ?", (node_id,))
        conn.execute(
            "INSERT INTO lineage_fts(node_id, question_id, branch_id, column_a_facts_md) VALUES (?, ?, ?, ?)",
            (node_id, question_id, branch_id, column_a_facts_md.strip()),
        )
        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id="tool:submit_node_handoff",
            edge_type="USED_TOOL",
            metadata={"obs_count": len(verified_obs), "pain_ticket": pain_ticket, "session_id": session_id},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="submit_node_handoff",
        node_id=node_id,
        question_id=question_id,
        next_step_guidance=f"节点 {node_id} 已入库 DAG 并进入 AWAITING_TRIAGE（已提取脱敏 Diff），控制面将唤醒 logistics_coordinator 调 triage_node 完成裁决。",
        data={
            "node_id": node_id,
            "node_status": "AWAITING_TRIAGE",
            "bound_obs_ids": verified_obs,
            "sanitized_code_diff_len": len(sanitized_diff),
            "pain_ticket": pain_ticket,
        },
    )
