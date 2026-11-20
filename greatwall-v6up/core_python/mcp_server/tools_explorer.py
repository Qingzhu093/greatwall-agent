"""V6-Up (v2.2) explorer（探索者）5 个窄工具及安全隔离评测原语。"""
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


_SQL_WRITE_FORBIDDEN_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


def _next_obs_id(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT obs_id FROM observations WHERE obs_id LIKE 'Obs-%'").fetchall()
    max_num = 0
    for r in rows:
        tail = str(r["obs_id"])[4:]
        if tail.isdigit():
            max_num = max(max_num, int(tail))
    idx = max(max_num + 1, len(rows) + 1)
    while True:
        cand = f"Obs-{idx:03d}"
        if conn.execute("SELECT 1 FROM observations WHERE obs_id = ?", (cand,)).fetchone() is None:
            return cand
        idx += 1


def _next_ticket_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT COUNT(*) AS cnt FROM works_engineering_queue").fetchone()
    idx = int(row["cnt"] or 0) + 1
    return f"wt_{idx:03d}_{uuid.uuid4().hex[:6]}"


def _resolve_hook_path(workspace_root: str, rel_path: str) -> Path:
    """与工造司 register_question_domain_hook 完全一致的跨工作区/内置仓路径解析。"""
    ws = Path(os.path.realpath(workspace_root))
    cand1 = Path(os.path.realpath(ws / rel_path))
    if cand1.is_file():
        return cand1
    cand2 = Path(os.path.realpath(core_python_root() / rel_path))
    if cand2.is_file():
        return cand2
    raise FailClosedError(ERR_NOT_FOUND, f"找不到子题验证钩子 {rel_path!r}（已检查工作区与 core_python）")


def tool_run_isolated_eval(
    conn: sqlite3.Connection,
    workspace_root: str,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    candidate_rel_path: str,
    linguistic_prediction: str,
    declared_refs: list[Any] | None = None,
    evaluator_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "run_isolated_eval", session_id=session_id, node_id=node_id)

    pred = (linguistic_prediction or "").strip()
    if len(pred) < 5:
        raise FailClosedError(
            ERR_INVALID_INPUT,
            "run_isolated_eval 必须在运行前提交明确的事前预测 linguistic_prediction（预期趋势、量级或待推翻假设）",
        )

    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["node_status"]) != "EXPLORING":
        raise FailClosedError(
            ERR_LOCKED,
            f"节点 {node_id!r} 当前状态为 {node['node_status']}，非 EXPLORING 态禁止提交新实验",
        )
    if str(node["question_id"]) != question_id:
        raise FailClosedError(
            ERR_AUTH,
            f"子题边界违例：节点 {node_id!r} 绑定子题 {node['question_id']!r}，禁止越界运行 {question_id!r}",
        )

    worktree_abs = str(node["worktree_abs_path"])
    cand_file = safe_resolve_in_worktree(worktree_abs, candidate_rel_path)
    if not cand_file.is_file():
        raise FailClosedError(ERR_NOT_FOUND, f"候选脚本不存在: {candidate_rel_path!r}")

    cfg = load_runtime_config()
    hook_row = conn.execute(
        "SELECT * FROM domain_hooks_by_question WHERE question_id = ?",
        (question_id,),
    ).fetchone()

    ep = conn.execute("SELECT epoch_id, contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
    epoch_id = int(ep["epoch_id"]) if ep else 1
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    q_contract = contracts.get(question_id) if isinstance(contracts, dict) else {}
    if not isinstance(q_contract, dict):
        q_contract = {}

    if hook_row is not None:
        max_err = float(cfg.get("simulator_fidelity_max_error_pct", 5.0))
        if float(hook_row["fidelity_max_error_pct"]) >= max_err:
            raise FailClosedError(
                ERR_LOCKED,
                f"子题 {question_id} 仿真器保真误差 {hook_row['fidelity_max_error_pct']}% >= {max_err}%，Stage 2 评测已熔断",
            )
        hook_abs = str(_resolve_hook_path(workspace_root, str(hook_row["hook_rel_path"])))
        hook_sha = str(hook_row["hook_sha256"])
        eval_epoch_ver = int(hook_row["eval_epoch_version"])
    elif q_contract.get("allow_generic_eval") is True:
        hook_abs = ""
        hook_sha = "generic"
        eval_epoch_ver = 1
    else:
        raise FailClosedError(
            ERR_LOCKED,
            f"子题 {question_id} 尚未在 domain_hooks_by_question 注册独立验证钩子（P10 门禁阻断裸跑）",
        )

    base_spec = dict(q_contract.get("evaluator_spec") or {})
    if isinstance(evaluator_spec, dict):
        base_spec.update(evaluator_spec)
    # 自动注入工造/Parse 0 注册的公开样例契约，消灭开局盲猜 public_input 导致的连环 no_cases 失败
    if not base_spec.get("public_input"):
        hook_pub_raw = hook_row["public_input_sample_json"] if hook_row is not None and "public_input_sample_json" in hook_row.keys() else "{}"
        hook_pub = json.loads(hook_pub_raw or "{}")
        contract_pub = q_contract.get("public_input_sample")
        if isinstance(hook_pub, dict) and hook_pub:
            base_spec["public_input"] = hook_pub
        elif isinstance(contract_pub, dict) and contract_pub:
            base_spec["public_input"] = contract_pub
    if hook_abs:
        base_spec["domain_hook_path"] = hook_abs

    cand_hash = sha256_file(cand_file)
    spec_for_hash = {k: v for k, v in base_spec.items() if k != "domain_hook_path"}
    spec_hash = sha256_canonical_json(spec_for_hash)

    # 三元复合幂等键检查：(candidate_hash, spec_hash, domain_hook_sha256)
    cached = conn.execute(
        """
        SELECT * FROM observations
        WHERE node_id = ? AND candidate_hash = ? AND spec_hash = ? AND domain_hook_sha256 = ?
          AND obs_status IN ('VALID', 'MEASURED_NON_IMPROVEMENT', 'EXECUTION_ERROR')
        ORDER BY created_at DESC LIMIT 1
        """,
        (node_id, cand_hash, spec_hash, hook_sha),
    ).fetchone()
    if cached is not None:
        warnings, guidance, signal = compute_clock_warnings_and_guidance(
            conn, node_id, new_score=cached["comparable_rank_score"]
        )
        return build_tool_receipt(
            conn=conn,
            tool_name="run_isolated_eval",
            node_id=node_id,
            question_id=question_id,
            warnings=[*warnings, "[_idempotent_hit] 命中三元复合幂等缓存，未重复运行 Stage A"],
            next_step_guidance=guidance,
            data={
                "obs_id": cached["obs_id"],
                "idempotent_hit": True,
                "obs_status": cached["obs_status"],
                "passed": bool(cached["passed"]),
                "metrics": json.loads(cached["metrics_json"] or "{}"),
                "details": cached["details_text"],
                "stage_a_artifact_path": cached["stage_a_artifact_path"],
                "clock_signal": signal,
            },
        )

    # 校验声明引用（先检查解锁态 + 外键存在性）
    resolved_refs = resolve_claimed_refs_list(conn, list(declared_refs or []))
    unlocked = int(node["first_reflection_unlocked"] or 0) == 1
    if not unlocked:
        for r in resolved_refs:
            if r["ref_kind"] in ("l3_verified", "l2_failure_record", "lineage_node"):
                raise FailClosedError(
                    ERR_LOCKED,
                    f"0-37% 净室独思期尚未解锁内藏 L3/L2 或谱系 DAG，禁止提前引用 {r['dst_id']!r}",
                )

    run_claim_id = f"rc_{uuid.uuid4().hex[:12]}"
    paths = resolve_storage_paths(workspace_root)
    stage_a_file = Path(paths["eval_artifacts_dir"]) / run_claim_id / "stage_a_output.json"

    eval_res = run_isolated_evaluation(
        candidate_path=str(cand_file),
        domain="generic" if not hook_abs else question_id,
        evaluator_spec=base_spec,
        output_dir=str(paths["outputs_dir"]),
        stage_a_output_path=str(stage_a_file),
        worktree_root=worktree_abs,
    )

    obs_status = str(eval_res["obs_status"])
    passed = 1 if eval_res.get("passed") else 0
    metrics = eval_res.get("metrics") or {}
    details = str(eval_res.get("details") or "")
    rank_score = eval_res.get("comparable_rank_score")
    now = utc_now_iso()

    auto_pain_ticket: str | None = None
    retained_snapshot_path = str(node["retained_snapshot_abs_path"] or "")

    with rw_immediate_tx(conn):
        obs_id = _next_obs_id(conn)
        conn.execute(
            """
            INSERT INTO observations(
                obs_id, epoch_id, question_id, branch_id, node_id, run_claim_id,
                candidate_hash, spec_hash, domain_hook_sha256, eval_epoch_version,
                stage_a_artifact_path, obs_status, passed, metrics_json, details_text,
                linguistic_prediction, validity_reason, comparable_rank_score,
                evaluator_spec_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs_id,
                epoch_id,
                question_id,
                str(node["branch_id"]),
                node_id,
                run_claim_id,
                cand_hash,
                spec_hash,
                hook_sha,
                eval_epoch_ver,
                str(eval_res.get("stage_a_artifact_path") or ""),
                obs_status,
                passed,
                json.dumps(metrics, ensure_ascii=False),
                details,
                pred,
                str(eval_res.get("failure_category") or ""),
                rank_score,
                json.dumps(base_spec, ensure_ascii=False),
                now,
                now,
            ),
        )

        for ref in resolved_refs:
            record_claim_edge(
                conn,
                src_id=obs_id,
                dst_id=ref["dst_id"],
                edge_type=ref["edge_type"],
                metadata={"node_id": node_id, "question_id": question_id},
            )
        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id="tool:run_isolated_eval",
            edge_type="USED_TOOL",
            metadata={"obs_id": obs_id, "session_id": session_id, "obs_status": obs_status},
        )

        consec_err = int(node["consecutive_exec_errors"] or 0)
        retained_cid = str(node["retained_candidate_id"] or "")
        if obs_status == "VALID" and passed == 1:
            consec_err = 0
            retained_cid = cand_hash
            retained_snapshot_path = backup_retained_candidate_snapshot(
                paths, str(node["branch_id"]), node_id, worktree_abs, candidate_rel_path
            )
        elif obs_status == "EXECUTION_ERROR":
            consec_err += 1
            if consec_err >= 2:
                auto_pain_ticket = _next_ticket_id(conn)
                conn.execute(
                    """
                    INSERT INTO works_engineering_queue(
                        ticket_id, question_id, node_id, source_type, description_md, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'AUTO_CONSECUTIVE_ERRORS', ?, 'OPEN', ?, ?)
                    """,
                    (
                        auto_pain_ticket,
                        question_id,
                        node_id,
                        f"节点 {node_id} 连续 {consec_err} 次 EXECUTION_ERROR (最新 {obs_id}: {eval_res.get('failure_category')})，请排查环境/钩子瓶颈",
                        now,
                        now,
                    ),
                )
        else:
            consec_err = 0

        conn.execute(
            """
            UPDATE lineage_nodes
            SET eval_count = eval_count + 1,
                consecutive_exec_errors = ?,
                retained_candidate_id = ?,
                retained_snapshot_abs_path = ?,
                updated_at = ?
            WHERE node_id = ?
            """,
            (consec_err, retained_cid, retained_snapshot_path, now, node_id),
        )

    warnings, guidance, signal = compute_clock_warnings_and_guidance(
        conn, node_id, new_score=rank_score if obs_status == "VALID" else None
    )
    if auto_pain_ticket:
        warnings.append(
            f"[AUTO_PAIN_TICKET:{auto_pain_ticket}] 连续 EXECUTION_ERROR >= 2，已自动排入工造司痛点队列，建议回退 Retained Candidate 修复而非换向"
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="run_isolated_eval",
        node_id=node_id,
        question_id=question_id,
        warnings=warnings,
        next_step_guidance=guidance,
        data={
            "obs_id": obs_id,
            "idempotent_hit": False,
            "obs_status": obs_status,
            "passed": bool(passed),
            "metrics": metrics,
            "details": details,
            "comparable_rank_score": rank_score,
            "failure_category": str(eval_res.get("failure_category") or ""),
            "stage_a_artifact_path": str(eval_res.get("stage_a_artifact_path") or ""),
            "retained_candidate_id": retained_cid,
            "retained_snapshot_abs_path": retained_snapshot_path,
            "auto_pain_ticket": auto_pain_ticket,
            "clock_signal": signal,
        },
    )


def tool_query_library_catalog(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    scope: str = "ALL",
    keyword: str = "",
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "query_library_catalog", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = int(node["first_reflection_unlocked"] or 0) == 1

    scope_u = (scope or "ALL").strip().upper()
    if scope_u not in ("EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "ALL"):
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 scope: {scope!r}，仅允许 ['ALL', 'EXTERNAL_R', 'INTERNAL_L2', 'INTERNAL_L3']",
        )

    cards: list[dict[str, Any]] = []
    kw = (keyword or "").strip()

    # 左翼外藏 [R###] 从 0% 起全程开放
    if scope_u in ("EXTERNAL_R", "ALL"):
        fts = sanitize_fts5_query(kw, ["title", "abstract_md", "exact_preconditions_md"]) if kw else None
        if fts:
            rows = conn.execute(
                """
                SELECT e.ref_id, e.question_id, e.title, e.abstract_md, e.exact_preconditions_md, e.read_depth, e.support_scope
                FROM external_literature_fts f
                JOIN external_literature_cards e ON f.ref_id = e.ref_id
                WHERE external_literature_fts MATCH ?
                  AND (e.question_id = ? OR e.question_id = 'GLOBAL')
                LIMIT 15
                """,
                (fts, question_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ref_id, question_id, title, abstract_md, exact_preconditions_md, read_depth, support_scope
                FROM external_literature_cards
                WHERE (question_id = ? OR question_id = 'GLOBAL')
                ORDER BY created_at DESC LIMIT 15
                """,
                (question_id,),
            ).fetchall()
        for r in rows:
            cards.append(
                {
                    "entry_id": str(r["ref_id"]),
                    "wing": "EXTERNAL_R",
                    "question_id": str(r["question_id"]),
                    "title": str(r["title"]),
                    "abstract_md": str(r["abstract_md"]),
                    "preconditions": str(r["exact_preconditions_md"]),
                    "read_depth": str(r["read_depth"]),
                    "support_scope": str(r["support_scope"]),
                }
            )

    # 右翼内藏 L3/L2 在 first_reflection_unlocked == 1 后开放
    if unlocked and scope_u in ("INTERNAL_L3", "INTERNAL_L2", "ALL"):
        types_want = []
        if scope_u in ("INTERNAL_L3", "ALL"):
            types_want.append("L3_VERIFIED")
        if scope_u in ("INTERNAL_L2", "ALL"):
            types_want.append("L2_FAILURE_RECORD")
        placeholders = ",".join("?" for _ in types_want)
        fts_int = sanitize_fts5_query(kw, ["title", "abstract_md", "exact_verified_scope_md", "exact_refuted_scope_md"]) if kw else None
        if fts_int:
            rows = conn.execute(
                f"""
                SELECT l.entry_id, l.question_id, l.ledger_type, l.title, l.abstract_md,
                       l.exact_verified_scope_md, l.exact_refuted_scope_md, l.ledger_status
                FROM internal_ledger_fts f
                JOIN internal_research_ledger l ON f.entry_id = l.entry_id
                WHERE internal_ledger_fts MATCH ?
                  AND l.ledger_type IN ({placeholders})
                  AND l.ledger_status = 'active'
                  AND (l.question_id = ? OR ? = 'ALL')
                LIMIT 15
                """,
                (fts_int, *types_want, question_id, question_id),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT entry_id, question_id, ledger_type, title, abstract_md,
                       exact_verified_scope_md, exact_refuted_scope_md, ledger_status
                FROM internal_research_ledger
                WHERE ledger_type IN ({placeholders})
                  AND ledger_status = 'active'
                  AND (question_id = ? OR ? = 'ALL')
                ORDER BY created_at DESC LIMIT 15
                """,
                (*types_want, question_id, question_id),
            ).fetchall()
        for r in rows:
            ltype = str(r["ledger_type"])
            cards.append(
                {
                    "entry_id": str(r["entry_id"]),
                    "wing": "INTERNAL_L3" if ltype == "L3_VERIFIED" else "INTERNAL_L2",
                    "question_id": str(r["question_id"]),
                    "title": str(r["title"]),
                    "abstract_md": str(r["abstract_md"]),
                    "scope_summary": str(
                        r["exact_verified_scope_md"] if ltype == "L3_VERIFIED" else r["exact_refuted_scope_md"]
                    ),
                }
            )

    with rw_immediate_tx(conn):
        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id=f"catalog:{scope_u}:{question_id}",
            edge_type="RETRIEVED",
            metadata={"session_id": session_id, "keyword": kw, "unlocked": unlocked, "returned": len(cards)},
        )

    if not unlocked:
        guidance = (
            "0-37% 期间仅返回外藏 [R###] 基础文献/算子卡；看中卡片请调 get_library_entry 拉取详情，缺外部资料可调 request_literature_survey。内藏 L3/L2 将在 37% 反思后当场解锁。"
        )
    else:
        guidance = (
            "已返回全馆匹配目录卡（外藏 [R###] + 内藏 L3/L2）。看中条目请按 entry_id 调 get_library_entry 并确保在引用前真实阅读（计入 FACT_LOG）。"
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="query_library_catalog",
        node_id=node_id,
        question_id=question_id,
        next_step_guidance=guidance,
        data={"unlocked_internal": unlocked, "cards": cards, "count": len(cards)},
    )


def tool_get_library_entry(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    entry_id: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "get_library_entry", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = int(node["first_reflection_unlocked"] or 0) == 1

    ext = conn.execute("SELECT * FROM external_literature_cards WHERE ref_id = ?", (entry_id,)).fetchone()
    if ext is not None:
        with rw_immediate_tx(conn):
            record_fact_edge(conn, src_id=node_id, dst_id=str(ext["ref_id"]), edge_type="READ", metadata={"session_id": session_id})
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            node_id=node_id,
            question_id=str(node["question_id"]),
            next_step_guidance="已登记 FACT_LOG 阅读凭证，你现在可以在 run_isolated_eval 的 declared_refs 中合法引用该条目 ID。",
            data={"wing": "EXTERNAL_R", "entry": dict(ext)},
        )

    intl = conn.execute("SELECT * FROM internal_research_ledger WHERE entry_id = ?", (entry_id,)).fetchone()
    if intl is not None:
        if not unlocked:
            raise FailClosedError(
                ERR_LOCKED,
                f"0-37% 净室独思期暂锁内藏账本，禁止读取 {entry_id!r}；完成首测与 37% 反思后当场解锁",
            )
        with rw_immediate_tx(conn):
            record_fact_edge(conn, src_id=node_id, dst_id=str(intl["entry_id"]), edge_type="READ", metadata={"session_id": session_id})
        d = dict(intl)
        # 盲态保护：绝不向他者暴露原作者方法学派身份
        d.pop("method_family_id", None)
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            node_id=node_id,
            question_id=str(node["question_id"]),
            next_step_guidance="已登记 FACT_LOG 阅读凭证，你现在可以在 run_isolated_eval 的 declared_refs 中合法引用该内藏条目 ID。",
            data={"wing": str(d["ledger_type"]), "entry": d},
        )

    raise FailClosedError(ERR_NOT_FOUND, f"图书馆条目 {entry_id!r} 不存在")


def tool_request_literature_survey(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    topic_query: str,
    reason: str,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "request_literature_survey", session_id=session_id, node_id=node_id)
    if not (topic_query or "").strip() or not (reason or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "topic_query 与 reason 均不能为空")
    req_id = f"sr_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO survey_requests(request_id, node_id, question_id, topic_query, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (req_id, node_id, question_id, topic_query.strip(), reason.strip(), now, now),
        )
        record_fact_edge(
            conn, src_id=node_id, dst_id=f"survey:{req_id}", edge_type="USED_TOOL", metadata={"topic": topic_query}
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="request_literature_survey",
        node_id=node_id,
        question_id=question_id,
        next_step_guidance="委托查新单已入队，控制面将唤醒 library_surveyor 采编新 [R###] 卡片，你可继续推进本地实验。",
        data={"request_id": req_id, "status": "PENDING"},
    )


def tool_read_lineage_graph(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    target_node_id: str | None = None,
    saved_query_name: str | None = None,
) -> dict[str, Any]:
    enforce_role_tool_permission(conn, caller_role, "read_lineage_graph", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != branch_id:
        raise FailClosedError(ERR_AUTH, f"分支声明不匹配：节点 {node_id!r} 属 {node['branch_id']!r} 而非 {branch_id!r}")
    if int(node["first_reflection_unlocked"] or 0) == 0:
        raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期暂锁本脉深层谱系 DAG，完成 37% 短反思后立即开放")

    qid = str(node["question_id"])
    payload: dict[str, Any] = {}

    if target_node_id:
        tgt = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (target_node_id,)).fetchone()
        if tgt is None:
            raise FailClosedError(ERR_NOT_FOUND, f"目标谱系节点 {target_node_id!r} 不存在")
        if str(tgt["branch_id"]) != branch_id:
            # 允许查直接祖先链节点，禁止查他门派兄弟/敌脉私有节点
            anc_rows = conn.execute(
                """
                WITH RECURSIVE anc AS (
                    SELECT node_id, parent_node_id FROM lineage_nodes WHERE node_id = ?
                    UNION ALL
                    SELECT p.node_id, p.parent_node_id FROM lineage_nodes p JOIN anc ON anc.parent_node_id = p.node_id
                )
                SELECT node_id FROM anc
                """,
                (node_id,),
            ).fetchall()
            anc_ids = {str(r["node_id"]) for r in anc_rows}
            if str(target_node_id) not in anc_ids:
                raise FailClosedError(
                    ERR_AUTH,
                    f"跨门派隔离阻断：禁止 {branch_id!r} 偷窥他脉节点 {target_node_id!r} 的私有谱系手记",
                )
        obs = conn.execute(
            "SELECT obs_id, obs_status, passed, metrics_json, details_text, linguistic_prediction FROM observations WHERE node_id = ? ORDER BY created_at ASC",
            (target_node_id,),
        ).fetchall()
        payload["target_node"] = {
            "node_id": str(tgt["node_id"]),
            "branch_id": str(tgt["branch_id"]),
            "generation": int(tgt["generation"]),
            "column_a_facts_md": str(tgt["column_a_facts_md"]),
            "column_b_hypothesis_md": str(tgt["column_b_hypothesis_md"]),
            "will_md": str(tgt["will_md"]),
            "observations": [dict(o) for o in obs],
        }

    elif saved_query_name:
        qrow = conn.execute(
            "SELECT * FROM saved_graph_queries WHERE query_name = ?",
            (saved_query_name,),
        ).fetchone()
        if qrow is None:
            raise FailClosedError(ERR_NOT_FOUND, f"已保存查询视图 {saved_query_name!r} 不存在")
        sql = str(qrow["sql_select"]).strip()
        if _SQL_WRITE_FORBIDDEN_RE.search(sql) or not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            raise FailClosedError(ERR_AUTH, "非法非只读 SQL 视图")
        sql_l = sql.lower()
        # 拍板 5：面向探索者强校验租户隔离 —— 禁查盲审表/合规私密表，若涉私有节点/观测表必须显式绑定 :branch_id 参数
        if any(tbl in sql_l for tbl in ("review_queue", "compliance_alerts", "works_engineering_queue")):
            raise FailClosedError(ERR_AUTH, "租户隔离阻断：探索者禁止执行涉及盲审/合规内部表的 SQL 视图")
        touches_private = ("lineage_nodes" in sql_l) or ("observations" in sql_l)
        if touches_private and ":branch_id" not in sql:
            raise FailClosedError(
                ERR_AUTH,
                "租户隔离阻断：涉及 lineage_nodes 或 observations 的共享视图面向探索者时必须强制包含 `:branch_id` 参数过滤",
            )
        rows = conn.execute(sql, {"branch_id": branch_id, "question_id": qid}).fetchall()
        with rw_immediate_tx(conn):
            conn.execute(
                "UPDATE saved_graph_queries SET usage_count = usage_count + 1 WHERE query_name = ?",
                (saved_query_name,),
            )
        payload["saved_query_rows"] = [dict(r) for r in rows[:50]]

    else:
        anc_rows = conn.execute(
            """
            WITH RECURSIVE anc(node_id, parent_node_id, branch_id, generation, triage_level, column_a_facts_md, will_md, lvl) AS (
                SELECT node_id, parent_node_id, branch_id, generation, triage_level, column_a_facts_md, will_md, 0
                FROM lineage_nodes WHERE node_id = ?
                UNION ALL
                SELECT p.node_id, p.parent_node_id, p.branch_id, p.generation, p.triage_level, p.column_a_facts_md, p.will_md, anc.lvl + 1
                FROM lineage_nodes p JOIN anc ON anc.parent_node_id = p.node_id
            )
            SELECT node_id, generation, triage_level, substr(column_a_facts_md, 1, 280) AS col_a_preview, will_md
            FROM anc ORDER BY generation ASC
            """,
            (node_id,),
        ).fetchall()
        payload["ancestors"] = [dict(r) for r in anc_rows]

    with rw_immediate_tx(conn):
        record_fact_edge(
            conn,
            src_id=node_id,
            dst_id=f"dag:{target_node_id or saved_query_name or branch_id}",
            edge_type="READ",
            metadata={"session_id": session_id},
        )

    return build_tool_receipt(
        conn=conn,
        tool_name="read_lineage_graph",
        node_id=node_id,
        question_id=qid,
        next_step_guidance="已拉取本脉谱系 DAG 祖先上下文。如需细看某代完整手记与指标，请传入 target_node_id。",
        data=payload,
    )


