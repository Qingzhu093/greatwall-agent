"""Single-Writer 外部控制面核心服务：

职责（严格对齐《09》§3–§4 与《agent_kb/01–04》）：
1. Worktree 与 Retained Candidate 物理快照备份与回滚恢复；
2. 脱敏代码 Diff 提取（剥离作者路径与分支身份，存入 DB `sanitized_code_diff_md` 供零磁盘盲审）；
3. `<worktree>/tools/*.py` AST 自动扫描清单生成（What it does / Interface / What it does NOT do）；
4. Question-Fair 公平槽位调度快照（默认 6 槽，硬上限 10）与 Stage 状态机事件扫描；
5. Stage 3 终局五件套导出（`final_delivery/`）。
"""

from __future__ import annotations

import ast
import difflib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from evaluators.isolated_runner import probe_domain_hook_protocol

from .db_schema import (
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import core_python_root, load_runtime_config

_SENSITIVE_COMMENT_RE = re.compile(
    r"\b(?:branch|node|session|explorer|author)_[a-zA-Z0-9_-]+\b"
)


def init_epoch_workspace(
    conn: sqlite3.Connection,
    goal_md: str = "",
    required_questions: list[str] | None = None,
    contracts: dict[str, Any] | None = None,
    stage: str = "STAGE1_PARSE0",
    epoch_id: int = 1,
) -> dict[str, Any]:
    """初始化或更新 active epoch_config（单写者控制面调用）。"""
    qs = [str(q).strip() for q in (required_questions or ["Q1"]) if str(q).strip()]
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO epoch_config(
                config_id, epoch_id, goal_md, required_questions_json, contracts_json, stage, consecutive_non_l1_handoffs, updated_at
            ) VALUES ('active', ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(config_id) DO UPDATE SET
                epoch_id = excluded.epoch_id,
                goal_md = CASE WHEN excluded.goal_md != '' THEN excluded.goal_md ELSE epoch_config.goal_md END,
                required_questions_json = excluded.required_questions_json,
                contracts_json = excluded.contracts_json,
                stage = excluded.stage,
                updated_at = excluded.updated_at
            """,
            (
                int(epoch_id),
                goal_md,
                json.dumps(qs, ensure_ascii=False),
                json.dumps(contracts or {}, ensure_ascii=False),
                stage,
                now,
            ),
        )
    return {
        "epoch_id": int(epoch_id),
        "required_questions": qs,
        "stage": stage,
    }


def sync_session_pressure(conn: sqlite3.Connection, node_id: str, pressure_tokens: int) -> dict[str, Any]:
    """原子同步 DSH TokenMeter 采样结果到 SQLite `lineage_nodes.pressure_tokens`（单一时钟数据源）。"""
    pt = max(0, int(pressure_tokens))
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        cur = conn.execute(
            "UPDATE lineage_nodes SET pressure_tokens = ?, updated_at = ? WHERE node_id = ?",
            (pt, now, node_id),
        )
        if cur.rowcount == 0:
            raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在，无法同步 pressure_tokens")
    row = conn.execute(
        "SELECT eval_count, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    cfg = load_runtime_config()
    window = int(cfg["context_window_tokens"])
    return {
        "node_id": node_id,
        "pressure_tokens": pt,
        "pressure_pct": round(pt / float(window), 4),
        "eval_count": int(row["eval_count"]) if row else 0,
        "first_reflection_unlocked": int(row["first_reflection_unlocked"]) if row else 0,
    }


def safe_resolve_in_worktree(worktree_abs_path: str, rel_path: str) -> Path:
    """安全将相对路径解析至指定 worktree 内部，防符号链接与 ../ 越界。"""
    if not worktree_abs_path or not rel_path or "\x00" in rel_path:
        raise FailClosedError(ERR_INVALID_INPUT, f"工作树路径或相对路径非法: {rel_path!r}")
    wt = Path(os.path.realpath(worktree_abs_path))
    target = Path(os.path.realpath(wt / rel_path))
    try:
        target.relative_to(wt)
    except ValueError as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"路径逃逸出节点 worktree 边界: {rel_path!r}") from exc
    return target


def backup_retained_candidate_snapshot(
    paths: dict[str, Any],
    branch_id: str,
    node_id: str,
    worktree_abs_path: str,
    candidate_rel_path: str,
) -> str:
    """将物理候选脚本与分支 tools/ 备份到受控 snapshots 目录，返回快照目录绝对路径。"""
    cand_file = safe_resolve_in_worktree(worktree_abs_path, candidate_rel_path)
    if not cand_file.is_file():
        return ""
    snap_dir = Path(paths["snapshots_dir"]) / branch_id / node_id
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    wt = Path(os.path.realpath(worktree_abs_path))
    rel = cand_file.relative_to(wt)
    dest_cand = snap_dir / rel
    dest_cand.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cand_file, dest_cand)

    tools_src = wt / "tools"
    if tools_src.is_dir():
        shutil.copytree(tools_src, snap_dir / "tools", dirs_exist_ok=True)

    meta = {
        "branch_id": branch_id,
        "node_id": node_id,
        "candidate_rel_path": rel.as_posix(),
        "saved_at": utc_now_iso(),
    }
    (snap_dir / "_snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(snap_dir)


def restore_retained_candidate_snapshot(
    worktree_abs_path: str, snapshot_abs_path: str
) -> list[str]:
    """Level 2 原地修补时从物理快照将工作区文件强制回滚到最后健康基线。"""
    if not snapshot_abs_path:
        return []
    snap_dir = Path(snapshot_abs_path)
    if not snap_dir.is_dir():
        return []
    wt = Path(worktree_abs_path)
    wt.mkdir(parents=True, exist_ok=True)
    restored: list[str] = []
    for item in snap_dir.rglob("*"):
        if not item.is_file() or item.name == "_snapshot_meta.json":
            continue
        rel = item.relative_to(snap_dir)
        dest = wt / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        restored.append(rel.as_posix())
    return restored


def _sanitize_code_text(raw_text: str, worktree_abs_path: str, branch_id: str, node_id: str) -> str:
    text = raw_text
    if worktree_abs_path:
        text = text.replace(worktree_abs_path, "<WORKTREE>")
        text = text.replace(worktree_abs_path.replace("\\", "/"), "<WORKTREE>")
    if branch_id:
        text = text.replace(branch_id, "<ANONYMOUS_BRANCH>")
    if node_id:
        text = text.replace(node_id, "<ANONYMOUS_NODE>")
    text = _SENSITIVE_COMMENT_RE.sub("<REDACTED_ID>", text)
    return text


def extract_sanitized_code_diff_md(
    worktree_abs_path: str,
    candidate_rel_path: str | None,
    snapshot_abs_path: str = "",
    branch_id: str = "",
    node_id: str = "",
) -> str:
    """提取候选脚本相对最近快照的脱敏核心 Diff（无快照时输出脱敏代码正文），供 Stage 1 零磁盘盲审。"""
    if not candidate_rel_path or not worktree_abs_path:
        return "（本节点未附带候选代码文件）"
    try:
        cand_file = safe_resolve_in_worktree(worktree_abs_path, candidate_rel_path)
    except FailClosedError:
        return "（候选路径越界或无效，已拦截）"
    if not cand_file.is_file():
        return f"（未找到候选文件 `{Path(candidate_rel_path).name}`）"

    new_lines = cand_file.read_text(encoding="utf-8", errors="replace").splitlines()
    old_lines: list[str] = []
    if snapshot_abs_path:
        snap_dir = Path(snapshot_abs_path)
        meta_file = snap_dir / "_snapshot_meta.json"
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                old_rel = meta.get("candidate_rel_path") or candidate_rel_path
                old_cand = snap_dir / old_rel
                if old_cand.is_file():
                    old_lines = old_cand.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                old_lines = []

    if old_lines and old_lines != new_lines:
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{Path(candidate_rel_path).name}",
                tofile=f"b/{Path(candidate_rel_path).name}",
                lineterm="",
            )
        )
        raw_md = "```diff\n" + "\n".join(diff_lines) + "\n```"
    else:
        raw_md = "```python\n" + "\n".join(new_lines) + "\n```"

    return _sanitize_code_text(raw_md, worktree_abs_path, branch_id, node_id)


def scan_worktree_tools_manifest(worktree_abs_path: str) -> list[dict[str, Any]]:
    """自动扫描 `<worktree>/tools/*.py` 生成高信噪比可用模块清单 Push 给探索者。"""
    tools_dir = Path(worktree_abs_path) / "tools"
    if not tools_dir.is_dir():
        return []
    manifest: list[dict[str, Any]] = []
    for py_file in sorted(tools_dir.rglob("*.py")):
        if py_file.name.startswith("_") or "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(Path(worktree_abs_path)).as_posix()
        src = py_file.read_text(encoding="utf-8", errors="replace")
        mod_doc = ""
        exports: list[str] = []
        try:
            tree = ast.parse(src, filename=str(py_file))
            mod_doc = (ast.get_docstring(tree) or "").strip()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                    fn_doc = (ast.get_docstring(node) or "").strip().splitlines()[0] if ast.get_docstring(node) else ""
                    args_sig = ", ".join(a.arg for a in node.args.args)
                    exports.append(f"{node.name}({args_sig})" + (f" — {fn_doc}" if fn_doc else ""))
        except SyntaxError:
            mod_doc = "（语法解析失败）"
        manifest.append(
            {
                "rel_path": rel,
                "docstring": mod_doc or "无 docstring（建议补充 What it does / Interface / What it does NOT do）",
                "exports": exports,
            }
        )
    return manifest


def check_stage2_closure_gate_data(conn: sqlite3.Connection) -> dict[str, Any]:
    """硬锁核检：确保 epoch_config 中所有必答子题在 internal_research_ledger 均拥有 >= 1 条 active L3_VERIFIED。"""
    cfg = load_runtime_config()
    min_l3 = int(cfg.get("hard_lock_closure_min_l3_verified_per_question", 1))
    ep = conn.execute("SELECT * FROM epoch_config WHERE config_id = 'active'").fetchone()
    req_qs = json.loads(ep["required_questions_json"]) if ep else []

    rows = conn.execute(
        """
        SELECT question_id, COUNT(*) AS l3_count
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active'
        GROUP BY question_id
        """
    ).fetchall()
    counts_by_q = {str(r["question_id"]): int(r["l3_count"]) for r in rows}

    if not req_qs:
        req_qs = sorted(
            {
                *(str(r["question_id"]) for r in conn.execute("SELECT DISTINCT question_id FROM domain_hooks_by_question").fetchall()),
                *counts_by_q.keys(),
            }
        )

    zero_l3_questions = [q for q in req_qs if counts_by_q.get(q, 0) < min_l3]
    pending_reviews = conn.execute(
        "SELECT review_id, question_id, review_status FROM review_queue WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')"
    ).fetchall()
    pending_reval = conn.execute(
        "SELECT queue_id, obs_id, question_id FROM pending_revalidation_queue WHERE status = 'PENDING'"
    ).fetchall()

    passed = bool(req_qs) and len(zero_l3_questions) == 0 and len(pending_reval) == 0
    return {
        "closure_allowed": passed,
        "gate_code": "GATE_PASSED" if passed else ("GATE_BLOCKED_ZERO_L3" if zero_l3_questions else "GATE_BLOCKED_PENDING_REVAL"),
        "required_questions": req_qs,
        "l3_counts_by_question": {q: counts_by_q.get(q, 0) for q in req_qs},
        "blocking_questions_zero_l3": zero_l3_questions,
        "pending_reviews": [dict(r) for r in pending_reviews],
        "pending_revalidation": [dict(r) for r in pending_reval],
    }


def get_question_dependency_status(
    conn: sqlite3.Connection,
    contracts: dict[str, Any] | None = None,
    required_questions: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """计算各子题前置依赖状态：前置子题至少具备 1 条 active L3_VERIFIED 方为已满足。"""
    if contracts is None or required_questions is None:
        ep = conn.execute("SELECT required_questions_json, contracts_json FROM epoch_config WHERE config_id = 'active'").fetchone()
        if contracts is None:
            contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
        if required_questions is None:
            required_questions = json.loads(ep["required_questions_json"]) if ep and ep["required_questions_json"] else []

    active_l3_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            "SELECT question_id, COUNT(*) AS cnt FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active' GROUP BY question_id"
        ).fetchall()
    }
    fam_deps: dict[str, set[str]] = {}
    for row in conn.execute("SELECT question_id, depends_on_questions_json FROM method_families").fetchall():
        q = str(row["question_id"])
        deps_raw = json.loads(row["depends_on_questions_json"] or "[]")
        if isinstance(deps_raw, list):
            fam_deps.setdefault(q, set()).update(str(d).strip() for d in deps_raw if str(d).strip())

    all_qs = list(dict.fromkeys([*(required_questions or []), *(contracts.keys() if isinstance(contracts, dict) else [])]))
    status_map: dict[str, dict[str, Any]] = {}
    for q in all_qs:
        q_c = contracts.get(q, {}) if isinstance(contracts, dict) else {}
        c_deps = q_c.get("depends_on_questions") if isinstance(q_c, dict) else []
        deps = sorted({*(str(d).strip() for d in (c_deps or []) if str(d).strip() and str(d).strip() != q), *(d for d in fam_deps.get(q, set()) if d != q)})
        unmet = [d for d in deps if active_l3_counts.get(d, 0) < 1]
        status_map[q] = {
            "depends_on_questions": deps,
            "unmet_dependencies": unmet,
            "unlocked": len(unmet) == 0,
            "active_l3_count": active_l3_counts.get(q, 0),
        }
    return status_map


def _resolve_ws_hint(conn: sqlite3.Connection, workspace_root: str) -> Path | None:
    """尽最大努力获取当前工作区物理根，供控制面健康探针定位钩子文件。"""
    if str(workspace_root or "").strip():
        p = Path(os.path.realpath(workspace_root))
        if p.is_dir():
            return p
    row = conn.execute(
        "SELECT worktree_abs_path FROM lineage_nodes WHERE worktree_abs_path IS NOT NULL AND worktree_abs_path != '' LIMIT 1"
    ).fetchone()
    if row:
        wt = Path(os.path.realpath(str(row["worktree_abs_path"])))
        for cand in [wt, *wt.parents]:
            if (cand / "evaluators").is_dir() or (cand / "baselines").is_dir():
                return cand
    return None


def _scan_invalid_protocol_hooks(
    conn: sqlite3.Connection,
    hooks: list[sqlite3.Row],
    workspace_root: str = "",
) -> list[dict[str, Any]]:
    """探测已注册钩子的签名与返回值协议健康度，识别协议损坏或触发熔断的子题钩子。"""
    ws_hint = _resolve_ws_hint(conn, workspace_root)
    core_root = core_python_root()
    invalid: list[dict[str, Any]] = []

    for r in hooks:
        qid = str(r["question_id"])
        hook_rel = str(r["hook_rel_path"] or "")
        base_rel = str(r["baseline_rel_path"] or "")
        hook_sha = str(r["hook_sha256"] or "")
        pub_sample = json.loads(r["public_input_sample_json"] or "{}")
        if not isinstance(pub_sample, dict):
            pub_sample = {}

        reason = ""
        hook_file: Path | None = None
        if ws_hint and hook_rel:
            c1 = Path(os.path.realpath(ws_hint / hook_rel))
            if c1.is_file():
                hook_file = c1
        if hook_file is None and hook_rel:
            c2 = Path(os.path.realpath(core_root / hook_rel))
            if c2.is_file():
                hook_file = c2

        base_file: Path | None = None
        if ws_hint and base_rel:
            b1 = Path(os.path.realpath(ws_hint / base_rel))
            if b1.is_file():
                base_file = b1
        if base_file is None and base_rel:
            b2 = Path(os.path.realpath(core_root / base_rel))
            if b2.is_file():
                base_file = b2

        if hook_file is not None:
            ok, err = probe_domain_hook_protocol(hook_file, sample_payload=pub_sample, baseline_path=base_file)
            if not ok:
                reason = err
        elif ws_hint is not None:
            reason = f"找不到已注册钩子文件: {hook_rel!r}"

        if not reason:
            obs_rows = conn.execute(
                "SELECT obs_status, metrics_json, details_text, domain_hook_sha256 FROM observations WHERE question_id = ?",
                (qid,),
            ).fetchall()
            valid_total = sum(1 for o in obs_rows if str(o["obs_status"]) == "VALID")
            proto_fails = [
                o for o in obs_rows
                if str(o["domain_hook_sha256"] or "") == hook_sha
                and str(o["obs_status"]) in ("INVALIDATED", "EXECUTION_ERROR")
                and (
                    str(o["metrics_json"] or "").strip() in ("", "{}")
                    or "evaluate" in str(o["details_text"] or "").lower()
                    or "hook" in str(o["details_text"] or "").lower()
                    or "protocol" in str(o["details_text"] or "").lower()
                )
            ]
            if valid_total == 0 and len(proto_fails) >= 2:
                reason = f"协议熔断：子题 {qid} 在当前钩子下 0 VALID 且已有 {len(proto_fails)} 次协议/空指标失败"

        if reason:
            invalid.append({"question_id": qid, "hook_rel_path": hook_rel, "reason": reason})

    return invalid


def schedule_control_plane_snapshot(
    conn: sqlite3.Connection,
    max_concurrent_workers: int | None = None,
    workspace_root: str = "",
) -> dict[str, Any]:
    """为 DSH External Orchestrator 生成 Question-Fair 确定性事件调度快照。"""
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))

    ep = conn.execute("SELECT * FROM epoch_config WHERE config_id = 'active'").fetchone()
    req_qs = json.loads(ep["required_questions_json"]) if ep else []
    contracts = json.loads(ep["contracts_json"]) if ep and ep["contracts_json"] else {}
    goal_md = str(ep["goal_md"] or "") if ep else ""
    stage = str(ep["stage"]) if ep else "STAGE1_PARSE0"
    non_l1 = int(ep["consecutive_non_l1_handoffs"]) if ep else 0

    hooks = conn.execute(
        "SELECT question_id, hook_rel_path, baseline_rel_path, hook_sha256, fidelity_max_error_pct, public_input_sample_json FROM domain_hooks_by_question"
    ).fetchall()
    hook_map = {str(r["question_id"]): float(r["fidelity_max_error_pct"]) for r in hooks}
    public_samples_by_q = {
        str(r["question_id"]): json.loads(r["public_input_sample_json"] or "{}")
        for r in hooks
    }
    invalid_protocol_hooks = _scan_invalid_protocol_hooks(conn, hooks, workspace_root=workspace_root)
    broken_qids = [h["question_id"] for h in invalid_protocol_hooks]
    max_err = float(cfg.get("simulator_fidelity_max_error_pct", 5.0))
    missing_hooks = [
        q for q in req_qs
        if q not in hook_map or hook_map[q] >= max_err or (stage == "STAGE1_PARSE0" and q in broken_qids)
    ]
    dep_status = get_question_dependency_status(conn, contracts=contracts, required_questions=req_qs)

    active_exploring = conn.execute(
        "SELECT node_id, question_id, branch_id, family_id, briefing_snapshot_md, worktree_abs_path, pressure_tokens, eval_count, first_reflection_unlocked FROM lineage_nodes WHERE node_status = 'EXPLORING' ORDER BY created_at ASC"
    ).fetchall()
    awaiting_triage = conn.execute(
        "SELECT node_id, question_id, branch_id, family_id FROM lineage_nodes WHERE node_status = 'AWAITING_TRIAGE' ORDER BY updated_at ASC"
    ).fetchall()
    blind_reviews = conn.execute(
        "SELECT review_id, question_id, review_status, proposer_session_id, source_type FROM review_queue WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND') ORDER BY created_at ASC"
    ).fetchall()
    pending_surveys = conn.execute(
        "SELECT request_id, question_id, topic_query, reason FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC"
    ).fetchall()
    open_works = conn.execute(
        "SELECT ticket_id, question_id, node_id, source_type, description_md FROM works_engineering_queue WHERE status = 'OPEN' ORDER BY created_at ASC"
    ).fetchall()
    pending_reval = conn.execute(
        "SELECT queue_id, obs_id, question_id FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at ASC"
    ).fetchall()
    external_lit_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM external_literature_cards").fetchone()["cnt"] or 0)

    # Question-Fair 公平排序：前置依赖未满足的节点暂不浪费一线槽位
    need_briefing = [
        dict(r)
        for r in active_exploring
        if not str(r["briefing_snapshot_md"] or "").strip()
        and dep_status.get(str(r["question_id"]), {}).get("unlocked", True)
    ]
    ready_candidates = [dict(r) for r in active_exploring if str(r["briefing_snapshot_md"] or "").strip()]
    ready_to_run = [r for r in ready_candidates if dep_status.get(str(r["question_id"]), {}).get("unlocked", True)]
    blocked_by_dep = [r for r in ready_candidates if not dep_status.get(str(r["question_id"]), {}).get("unlocked", True)]
    active_counts_by_q: dict[str, int] = {q: 0 for q in req_qs}
    for r in ready_to_run:
        q = str(r["question_id"])
        active_counts_by_q[q] = active_counts_by_q.get(q, 0) + 1
    ready_to_run.sort(key=lambda r: (active_counts_by_q.get(str(r["question_id"]), 0), r["node_id"]))

    # 统计依赖已解锁但既无 active L3 也无在研/待分诊/待盲审单的子题，用于自动通知后勤开枝派单
    l3_q_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            "SELECT question_id, COUNT(*) AS cnt FROM internal_research_ledger WHERE ledger_type = 'L3_VERIFIED' AND ledger_status = 'active' GROUP BY question_id"
        ).fetchall()
    }
    in_flight_qs = {
        *(str(r["question_id"]) for r in active_exploring),
        *(str(r["question_id"]) for r in awaiting_triage),
        *(str(r["question_id"]) for r in blind_reviews),
    }
    questions_needing_branch = [
        q for q in req_qs
        if dep_status.get(q, {}).get("unlocked", True)
        and l3_q_counts.get(q, 0) == 0
        and q not in in_flight_qs
    ]

    return {
        "stage": stage,
        "goal_md": goal_md,
        "required_questions": req_qs,
        "contracts": contracts,
        "question_dependencies": dep_status,
        "questions_needing_branch": questions_needing_branch,
        "public_input_samples": public_samples_by_q,
        "external_literature_count": external_lit_count,
        "slot_cap": slot_cap,
        "missing_hooks_or_fidelity": missing_hooks,
        "invalid_protocol_hooks": invalid_protocol_hooks,
        "protocol_broken_questions": broken_qids,
        "pending_surveys": [dict(r) for r in pending_surveys],
        "open_works_tickets": [dict(r) for r in open_works],
        "pending_revalidation": [dict(r) for r in pending_reval],
        "awaiting_triage": [dict(r) for r in awaiting_triage],
        "pending_reviews": [dict(r) for r in blind_reviews],
        "explorers_needing_briefing": need_briefing,
        "explorers_ready_to_run": ready_to_run[:slot_cap],
        "blocked_by_dependency_nodes": blocked_by_dep,
        "stagnation_triggered": non_l1 >= int(cfg.get("stagnation_consecutive_non_l1_handoffs", 8)),
        "closure_gate": check_stage2_closure_gate_data(conn),
    }


def export_stage3_deliverables(
    conn: sqlite3.Connection,
    workspace_root: str,
    formal_paper_md: str,
    selected_l3_ids_by_question: dict[str, list[str]],
    reproduction_candidate_nodes: list[str],
) -> dict[str, Any]:
    """在 `check_stage2_closure_gate()` 全绿后，安全导出 `<workspace>/final_delivery/` 五件套。"""
    gate = check_stage2_closure_gate_data(conn)
    if not gate["closure_allowed"]:
        raise FailClosedError(
            ERR_LOCKED,
            f"结题硬锁阻断 ({gate['gate_code']}): 存在未达标 L3_VERIFIED>=1 的必答子题 {gate['blocking_questions_zero_l3']} 或未清重评队列",
        )

    if not formal_paper_md or len(formal_paper_md.strip()) < 50:
        raise FailClosedError(ERR_INVALID_INPUT, "formal_paper_md 内容过短，严禁空壳成文")

    selected_flat: list[str] = []
    for qid in gate["required_questions"]:
        q_l3s = selected_l3_ids_by_question.get(qid) or []
        if not q_l3s:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"selected_l3_ids_by_question 缺少子题 {qid} 的已证实 L3 条目",
            )
        for eid in q_l3s:
            row = conn.execute(
                "SELECT entry_id FROM internal_research_ledger WHERE entry_id = ? AND question_id = ? AND ledger_type = 'L3_VERIFIED' AND ledger_status = 'active'",
                (eid, qid),
            ).fetchone()
            if row is None:
                raise FailClosedError(
                    ERR_NOT_FOUND,
                    f"条目 {eid!r} 并非子题 {qid} 的有效 active L3_VERIFIED 黄金结论",
                )
            selected_flat.append(str(eid))

    ws = Path(os.path.realpath(workspace_root))
    delivery_dir = ws / "final_delivery"
    repro_dir = delivery_dir / "02_reproduction_suite"
    repro_dir.mkdir(parents=True, exist_ok=True)

    # 1. 01_formal_paper.md
    paper_path = delivery_dir / "01_formal_paper.md"
    paper_path.write_text(formal_paper_md.strip() + "\n", encoding="utf-8")

    # 2. 02_reproduction_suite/
    repro_manifest: list[dict[str, Any]] = []
    for nid in reproduction_candidate_nodes:
        node = conn.execute(
            "SELECT node_id, question_id, branch_id, worktree_abs_path, retained_snapshot_abs_path FROM lineage_nodes WHERE node_id = ?",
            (nid,),
        ).fetchone()
        if node is None:
            raise FailClosedError(ERR_NOT_FOUND, f"复现节点 {nid!r} 不存在")
        node_out = repro_dir / str(node["question_id"]) / str(node["node_id"])
        node_out.mkdir(parents=True, exist_ok=True)
        copied_files: list[str] = []
        snap = str(node["retained_snapshot_abs_path"] or "")
        src_dir = Path(snap) if (snap and Path(snap).is_dir()) else Path(str(node["worktree_abs_path"]))
        if src_dir.is_dir():
            for pyf in src_dir.rglob("*.py"):
                if "__pycache__" in pyf.parts or pyf.name.startswith("_hidden"):
                    continue
                rel = pyf.relative_to(src_dir)
                dest = node_out / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pyf, dest)
                copied_files.append(rel.as_posix())
        repro_manifest.append(
            {
                "node_id": str(node["node_id"]),
                "question_id": str(node["question_id"]),
                "copied_files": copied_files,
            }
        )
    (repro_dir / "MANIFEST.json").write_text(
        json.dumps(repro_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 3. 03_barrier_proofs.json (L2 失败与阻碍雷达)
    l2_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT entry_id, question_id, source_type, method_family_id, title, abstract_md, exact_refuted_scope_md, body_proof_or_code_md, created_at FROM internal_research_ledger WHERE ledger_type = 'L2_FAILURE_RECORD' ORDER BY created_at ASC"
        ).fetchall()
    ]
    barrier_path = delivery_dir / "03_barrier_proofs.json"
    barrier_path.write_text(json.dumps(l2_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. 04_lineage_dag.json
    dag_rows = [
        {
            "node_id": r["node_id"],
            "question_id": r["question_id"],
            "branch_id": r["branch_id"],
            "family_id": r["family_id"],
            "parent_node_id": r["parent_node_id"],
            "generation": r["generation"],
            "node_status": r["node_status"],
            "triage_level": r["triage_level"],
            "retained_candidate_id": r["retained_candidate_id"],
        }
        for r in conn.execute("SELECT * FROM lineage_nodes ORDER BY created_at ASC").fetchall()
    ]
    dag_path = delivery_dir / "04_lineage_dag.json"
    dag_path.write_text(json.dumps(dag_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5. 05_last_will_and_proposals.json
    wills_rows = [
        {
            "node_id": r["node_id"],
            "question_id": r["question_id"],
            "will_md": r["will_md"],
            "reopen_condition": r["reopen_condition"],
        }
        for r in conn.execute(
            "SELECT node_id, question_id, will_md, reopen_condition FROM lineage_nodes WHERE will_md != '' OR reopen_condition != '' ORDER BY created_at ASC"
        ).fetchall()
    ]
    pollination_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT review_id, question_id, cross_pollinate_json FROM review_queue WHERE cross_pollinate_json IS NOT NULL"
        ).fetchall()
    ]
    wills_path = delivery_dir / "05_last_will_and_proposals.json"
    wills_path.write_text(
        json.dumps(
            {"wills": wills_rows, "cross_pollinate_nominations": pollination_rows, "selected_l3_ids": selected_flat},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            "UPDATE epoch_config SET stage = 'STAGE3_CONSOLIDATE', updated_at = ? WHERE config_id = 'active'",
            (now,),
        )

    return {
        "delivery_dir": str(delivery_dir),
        "five_piece_files": [
            "01_formal_paper.md",
            "02_reproduction_suite/MANIFEST.json",
            "03_barrier_proofs.json",
            "04_lineage_dag.json",
            "05_last_will_and_proposals.json",
        ],
        "selected_l3_ids": selected_flat,
        "trigger_final_audit_roles": ["library_verifier", "supervisory_committee"],
    }
