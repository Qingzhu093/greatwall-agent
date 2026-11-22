"""长城 V6-Up (v3.0) Single-Writer 外部控制面核心服务。

严格落实《09》第二、三、四章及《agent_kb/01–04》核心职责：
1. Parse 0 六项启动表单初始化（`init_parse0_contract`）与控制面专属人类紧急叫停写入（`record_human_stop`）；
2. Worktree 与 Retained Candidate 物理快照备份与还原、脱敏代码 Diff 提取、`<worktree>/tools/` AST 清单扫描；
3. 空白盲审临时沙箱（`blind_sandbox_<review_id>/`）现建、精准脱敏拷入与审毕清理；
4. 两级公平并发调度快照（先子题、再学派）、`AWAITING_TRIAGE` 防抢跑、分支级确定性 `requires`、`>=2 && >50%` 无豁免聚拢检测（纯查 SQLite `<50ms`，绝不动态跑 Python 仪器！）；
5. 重型异步作业（`async_eval_jobs`）现场冻结、重启幂等恢复与仅扣一次预算执行；
6. 双段式终局门禁（`FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP` + 强校验控制面 `human_stop_requested_at`）与五件套导出（生成确定性 `delivery_id` / `delivery_sha256` 并重置 `verifier_final_audit_passed = 0`）。
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..evaluators.isolated_runner import (
    run_isolated_instrument,
    sha256_bytes,
    sha256_file,
)

from .db_schema import (
    ALLOWED_DELIVERY_MODES,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .mcp_core_helpers import (
    compute_clock_signal,
    load_runtime_config,
    next_prefixed_id,
    record_declared_refs,
    resolve_effective_context_window,
)

_SENSITIVE_COMMENT_RE = re.compile(
    r"\b(?:branch|node|session|explorer|author)_[a-zA-Z0-9_-]+\b"
)

_PUBLIC_INPUT_DEFAULT_DIRS = (
    "source_materials",
    "problem_pack",
    "inputs",
    "data",
    "rulings",
    "attachments",
    "附件",
)
_PUBLIC_INPUT_TOP_EXTS = frozenset(
    {".md", ".txt", ".pdf", ".doc", ".docx", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xlsx"}
)
_FORBIDDEN_SHARED_NAMES = frozenset(
    {
        "worktrees",
        "evaluators",
        "final_delivery",
        "logs",
        "paper",
        "simulator",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".dsh",
        ".pytest_cache",
        ".mypy_cache",
    }
)


def _is_forbidden_public_path(rel_parts: tuple[str, ...]) -> bool:
    for part in rel_parts:
        low = part.lower()
        if low in _FORBIDDEN_SHARED_NAMES:
            return True
        if low.startswith("_hidden") or low.startswith("greatwall.db"):
            return True
    return False


def discover_public_input_entries(
    workspace_root: str,
    explicit_rel_paths: list[str] | None = None,
) -> list[str]:
    """发现工作区公开题面、输入数据与《补充裁决文档》（严格排除 worktrees/_hidden*/evaluators/final_delivery 等隔离目录）。"""
    ws = Path(os.path.realpath(workspace_root or ""))
    if not ws.is_dir():
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add_rel(rel_posix: str) -> None:
        norm = rel_posix.strip().strip("/")
        if not norm or norm in seen:
            return
        seen.add(norm)
        found.append(norm)

    # 1. 显式声明的公开输入 / 裁决文档路径
    for raw in explicit_rel_paths or []:
        rel_str = str(raw or "").strip().replace("\\", "/")
        if not rel_str or "\x00" in rel_str:
            continue
        try:
            cand = Path(os.path.realpath(ws / rel_str))
            rel = cand.relative_to(ws)
        except Exception:
            continue
        if not cand.exists() or not rel.parts or _is_forbidden_public_path(rel.parts):
            continue
        _add_rel(rel.as_posix())

    # 2. 自动探测常规公开输入目录与工作区顶层公开文档
    for dname in _PUBLIC_INPUT_DEFAULT_DIRS:
        dpath = ws / dname
        if dpath.is_dir() and not _is_forbidden_public_path((dname,)):
            _add_rel(dname)

    try:
        for child in sorted(ws.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_file():
                continue
            if _is_forbidden_public_path((child.name,)):
                continue
            if child.suffix.lower() in _PUBLIC_INPUT_TOP_EXTS:
                _add_rel(child.name)
    except OSError:
        pass

    return found


def sync_public_inputs_to_worktree(
    workspace_root: str,
    target_root: str | Path,
    explicit_rel_paths: list[str] | None = None,
    *,
    rulings_revision_dir: Path | None = None,
    skip_live_rulings: bool = False,
) -> list[str]:
    """将公开题面、公开输入与《补充裁决文档》同步到目标沙箱/工作树的 `inputs/` 目录。"""
    ws = Path(os.path.realpath(workspace_root or ""))
    tgt_base = Path(os.path.realpath(str(target_root)))
    if not ws.is_dir() or not tgt_base.is_dir():
        return []
    entries = discover_public_input_entries(str(ws), explicit_rel_paths)
    inputs_dir = tgt_base / "inputs"
    mounted: list[str] = []

    if entries or (rulings_revision_dir and rulings_revision_dir.is_dir()):
        inputs_dir.mkdir(parents=True, exist_ok=True)

    for rel_posix in entries:
        if skip_live_rulings and (rel_posix == "rulings" or rel_posix.startswith("rulings/")):
            continue
        src = ws / rel_posix
        if not src.exists():
            continue
        # 若来源本身就是工作区顶层的 `inputs/`，展开其子项避免出现 `inputs/inputs/...`
        dst = inputs_dir if rel_posix == "inputs" else (inputs_dir / rel_posix)
        try:
            if src.is_dir():
                for fp in sorted(src.rglob("*")):
                    if not fp.is_file():
                        continue
                    rel_sub = fp.relative_to(src)
                    if _is_forbidden_public_path(rel_sub.parts):
                        continue
                    out_fp = dst / rel_sub
                    out_fp.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fp, out_fp)
                    mounted.append(out_fp.relative_to(tgt_base).as_posix())
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                mounted.append(dst.relative_to(tgt_base).as_posix())
        except OSError:
            continue

    # 若指定历史裁决快照目录（用于旧 spec_revision 手稿盲审），只挂载该版本对应的 rulings/
    if rulings_revision_dir and rulings_revision_dir.is_dir():
        dst_rulings = inputs_dir / "rulings"
        for fp in sorted(rulings_revision_dir.rglob("*")):
            if not fp.is_file():
                continue
            rel_sub = fp.relative_to(rulings_revision_dir)
            out_fp = dst_rulings / rel_sub
            out_fp.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(fp, out_fp)
                mounted.append(out_fp.relative_to(tgt_base).as_posix())
            except OSError:
                continue

    return mounted


def sync_public_rulings(conn: sqlite3.Connection, *, workspace_root: str) -> dict[str, Any]:
    """轻量检测工作区 `rulings/` 公开补充裁决文档变动：仅在文件指纹变化时递增 `latest_spec_revision` 并留存版本快照。"""
    p0 = conn.execute(
        "SELECT latest_spec_revision, latest_ruling_summary_md, ruling_fingerprint_sha256 FROM parse0_contract WHERE contract_id = 'active'"
    ).fetchone()
    if p0 is None:
        return {"changed": False, "latest_spec_revision": 0, "latest_ruling_summary_md": ""}

    cur_rev = int(p0["latest_spec_revision"] or 0)
    cur_fp = str(p0["ruling_fingerprint_sha256"] or "")
    cur_summary = str(p0["latest_ruling_summary_md"] or "")

    ws = Path(os.path.realpath(workspace_root or ""))
    rulings_dir = ws / "rulings"
    files: list[Path] = []
    if rulings_dir.is_dir():
        files = sorted(
            (p for p in rulings_dir.rglob("*") if p.is_file() and not _is_forbidden_public_path(p.relative_to(rulings_dir).parts)),
            key=lambda p: p.relative_to(rulings_dir).as_posix(),
        )

    if not files and not cur_fp:
        return {"changed": False, "latest_spec_revision": cur_rev, "latest_ruling_summary_md": cur_summary}

    h = hashlib.sha256()
    summary_parts: list[str] = []
    for fp in files:
        rel = fp.relative_to(rulings_dir).as_posix()
        file_sha = sha256_file(fp)
        h.update(f"{rel}:{file_sha}\n".encode("utf-8"))
        try:
            snippet = fp.read_text(encoding="utf-8", errors="replace").strip().replace("\r\n", "\n")[:260]
        except OSError:
            snippet = ""
        summary_parts.append(f"- `{rel}`: {snippet}")
    new_fp = h.hexdigest() if files else ""

    if new_fp == cur_fp:
        return {"changed": False, "latest_spec_revision": cur_rev, "latest_ruling_summary_md": cur_summary}

    new_rev = cur_rev + 1
    new_summary = ("\n".join(summary_parts))[:1200] if summary_parts else "(rulings/ 目录已清空)"
    paths = resolve_storage_paths(workspace_root)
    rev_snap_dir = paths["ruling_revisions_dir"] / f"v{new_rev}"
    if rev_snap_dir.exists():
        shutil.rmtree(rev_snap_dir, ignore_errors=True)
    rev_snap_dir.mkdir(parents=True, exist_ok=True)
    for fp in files:
        rel = fp.relative_to(rulings_dir)
        dst = rev_snap_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(fp, dst)
        except OSError:
            pass

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE parse0_contract
            SET latest_spec_revision = ?, latest_ruling_summary_md = ?, ruling_fingerprint_sha256 = ?, updated_at = ?
            WHERE contract_id = 'active'
            """,
            (new_rev, new_summary, new_fp, now),
        )
    return {
        "changed": True,
        "latest_spec_revision": new_rev,
        "latest_ruling_summary_md": new_summary,
        "ruling_files": [fp.relative_to(rulings_dir).as_posix() for fp in files],
    }


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
    missing: list[dict[str, Any]] = []
    for raw in items:
        if isinstance(raw, str):
            iid = raw.strip()
            if iid and iid not in active_ids:
                missing.append({"instrument_id": iid})
        elif isinstance(raw, dict):
            iid = str(raw.get("instrument_id") or raw.get("id") or "").strip()
            if iid:
                if iid not in active_ids:
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
) -> dict[str, Any]:
    """写入或更新 active Parse 0 六项启动契约表单（单写者控制面调用；更新已有契约时默认保留当前 stage 不倒退）。"""
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
                min_commitment_window_sec, delivery_spec_md, shared_inputs_json, human_signed_at,
                stage, consecutive_non_l1_handoffs, epoch_id, created_at, updated_at
            ) VALUES ('active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
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
        cur_row = conn.execute("SELECT stage FROM parse0_contract WHERE contract_id = 'active'").fetchone()
        eff_stage = str(cur_row["stage"]) if cur_row else insert_stage

    return {
        "contract_id": "active",
        "subquestions": qs,
        "question_order": order_list,
        "shared_inputs_rel_paths": clean_shared_inputs,
        "min_commitment_window_sec": max(0, int(min_commitment_window_sec or 0)),
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
    """将宿主 DSH TokenMeter 采样的真实压力水位与模型有效窗口 W = min(500k, model_window) 同步至 SQLite，并返回实时 node_status。"""
    row = conn.execute(
        "SELECT node_id, node_status, first_reflection_unlocked, effective_context_window FROM lineage_nodes WHERE node_id = ?",
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
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        if explicit_win is not None:
            conn.execute(
                "UPDATE lineage_nodes SET pressure_tokens = ?, effective_context_window = ?, updated_at = ? WHERE node_id = ?",
                (pt, eff_win, now, node_id),
            )
        else:
            conn.execute(
                "UPDATE lineage_nodes SET pressure_tokens = ?, updated_at = ? WHERE node_id = ?",
                (pt, now, node_id),
            )
    sig = compute_clock_signal(pt, int(row["first_reflection_unlocked"] or 0), effective_context_window=eff_win)
    return {"node_id": node_id, "node_status": str(row["node_status"]), **sig}


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


def safe_resolve_in_worktree(worktree_abs_path: str, rel_path: str) -> Path:
    """规范化解析分支工作树内相对路径，杜绝 `..` 逃逸与空字节。"""
    raw = str(rel_path or "").strip()
    if not raw or "\x00" in raw or not str(worktree_abs_path or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, f"工作树路径或相对路径非法: {rel_path!r}")
    wt_root = Path(os.path.realpath(worktree_abs_path))
    target = Path(os.path.realpath(wt_root / raw))
    try:
        target.relative_to(wt_root)
    except ValueError as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"路径逃逸出节点 worktree 边界: {rel_path!r}") from exc
    return target


def backup_retained_candidate_snapshot(
    *,
    workspace_root: str,
    branch_id: str,
    worktree_abs_path: str,
    candidate_rel_path: str | None = None,
) -> str:
    """将分支当前最佳候选及 `<worktree>/tools/` 物理快照备份至 `$PLUGIN_DATA/.../snapshots/<branch_id>/retained_candidate/`。"""
    paths = resolve_storage_paths(workspace_root)
    snap_dir = paths["snapshots_dir"] / branch_id / "retained_candidate"
    if snap_dir.exists():
        shutil.rmtree(snap_dir, ignore_errors=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    wt = Path(os.path.realpath(worktree_abs_path))
    if wt.is_dir():
        if candidate_rel_path:
            src = safe_resolve_in_worktree(worktree_abs_path, candidate_rel_path)
            if src.is_file():
                dst = snap_dir / Path(candidate_rel_path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        else:
            for item in wt.iterdir():
                if item.name in (".git", "__pycache__", ".venv", "inputs"):
                    continue
                dst = snap_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"), dirs_exist_ok=True)
                elif item.is_file():
                    shutil.copy2(item, dst)
        tools_src = wt / "tools"
        if tools_src.is_dir():
            shutil.copytree(
                tools_src,
                snap_dir / "tools",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )
    return str(snap_dir)


def restore_retained_candidate_snapshot(snapshot_abs_path: str, worktree_abs_path: str) -> bool:
    """从物理快照还原分支工作区（用于 LEVEL_2 原地修补或回退健康祖先）。"""
    snap = Path(snapshot_abs_path)
    wt = Path(worktree_abs_path)
    if not snap.is_dir() or not wt.is_dir():
        return False
    for item in snap.rglob("*"):
        if item.is_file():
            rel = item.relative_to(snap)
            dst = wt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst)
    return True


def extract_sanitized_code_diff_md(
    *,
    worktree_abs_path: str,
    candidate_rel_path: str | None,
    previous_snapshot_abs_path: str | None = None,
) -> str:
    """提取脱敏代码 Diff 或候选核心源码片段（剥离作者/分支/节点身份词）。"""
    if not candidate_rel_path or not worktree_abs_path:
        return ""
    try:
        cur_file = safe_resolve_in_worktree(worktree_abs_path, candidate_rel_path)
    except FailClosedError:
        return ""
    if not cur_file.is_file():
        return ""

    cur_text = cur_file.read_text(encoding="utf-8", errors="replace")
    prev_text = ""
    if previous_snapshot_abs_path:
        prev_file = Path(previous_snapshot_abs_path) / Path(candidate_rel_path)
        if prev_file.is_file():
            prev_text = prev_file.read_text(encoding="utf-8", errors="replace")

    if prev_text:
        diff_lines = list(
            difflib.unified_diff(
                prev_text.splitlines(),
                cur_text.splitlines(),
                fromfile=f"a/{candidate_rel_path}",
                tofile=f"b/{candidate_rel_path}",
                lineterm="",
            )
        )
        raw_out = "\n".join(diff_lines)
    else:
        raw_out = f"### File: {candidate_rel_path}\n```\n{cur_text}\n```"

    return _SENSITIVE_COMMENT_RE.sub("<REDACTED_ID>", raw_out)


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


def stage_blind_review_sandbox(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    review_id: str,
) -> dict[str, Any]:
    """为 `library_verifier` 现建独立空白盲审沙箱 `blind_sandbox_<review_id>/`，仅拷贝授权脱敏材料。

    支持两种模式：
    1. 常规审稿 `rev_###`：只拷贝 A 栏文本、脱敏候选脚本/证明/反例文件及关联 `[Obs###]` JSON（严禁 B 栏/DB/隐藏集/原 Worktree）；
    2. Stage 3 终核 `STAGE3_FINAL_AUDIT:<delivery_id>`：只读拷贝 `<workspace>/final_delivery/` 五件套及被引 L3 边界清单。
    """
    paths = resolve_storage_paths(workspace_root)
    safe_rev = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(review_id))
    sandbox_dir = paths["blind_sandboxes_dir"] / f"blind_sandbox_{safe_rev}"
    if sandbox_dir.exists():
        _rmtree_force(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    staged_files: list[str] = []

    if str(review_id).startswith("STAGE3_FINAL_AUDIT:"):
        delivery_dir = Path(os.path.realpath(workspace_root)) / "final_delivery"
        if delivery_dir.is_dir():
            dst = sandbox_dir / "final_delivery"
            shutil.copytree(delivery_dir, dst, dirs_exist_ok=True)
            for fp in sorted(dst.rglob("*")):
                if fp.is_file():
                    staged_files.append(fp.relative_to(sandbox_dir).as_posix())
        # 同时导出所有活跃 L3 的原始 exact_verified_scope_md 供核查是否夸大
        l3_rows = conn.execute(
            """
            SELECT entry_id, question_id, l3_entry_kind, goal_coverage, title, exact_verified_scope_md, exact_refuted_scope_md
            FROM internal_research_ledger
            WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
            ORDER BY question_id, entry_id
            """
        ).fetchall()
        scope_file = sandbox_dir / "verified_l3_scopes.json"
        scope_file.write_text(
            json.dumps([dict(r) for r in l3_rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        staged_files.append("verified_l3_scopes.json")
        _set_tree_readonly(sandbox_dir, True)
        return {"sandbox_abs_path": str(sandbox_dir), "staged_files": staged_files}

    rev = conn.execute("SELECT * FROM review_queue WHERE review_id = ?", (review_id,)).fetchone()
    if rev is None:
        raise FailClosedError(ERR_NOT_FOUND, f"盲审单 {review_id!r} 不存在")

    # 1. 仅写脱敏后的 A 栏手稿（绝不放 B 栏、作者 ID 或分支 ID）
    col_a = _SENSITIVE_COMMENT_RE.sub("<REDACTED_ID>", str(rev["column_a_snapshot_md"] or ""))
    (sandbox_dir / "manuscript_column_a.md").write_text(
        f"# {rev['manuscript_title']}\n\n{col_a}\n",
        encoding="utf-8",
    )
    staged_files.append("manuscript_column_a.md")

    # 2. 拷入脱敏代码/证明/反例文件（若有）及分支 tools/（脱敏剔除敏感标识）
    node = conn.execute(
        "SELECT worktree_abs_path, retained_snapshot_abs_path, candidate_rel_path FROM lineage_nodes WHERE node_id = ?",
        (rev["source_node_id"],),
    ).fetchone()
    art_rel = str(rev["artifact_rel_path"] or (node["candidate_rel_path"] if node else "") or "").strip()
    if node is not None and art_rel:
        src_base = Path(str(node["retained_snapshot_abs_path"] or ""))
        if not src_base.is_dir():
            src_base = Path(str(node["worktree_abs_path"] or ""))
        if src_base.is_dir():
            cand_src = src_base / art_rel
            if cand_src.is_file():
                dst = sandbox_dir / art_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                raw = cand_src.read_text(encoding="utf-8", errors="replace")
                dst.write_text(_SENSITIVE_COMMENT_RE.sub("<REDACTED_ID>", raw), encoding="utf-8")
                staged_files.append(Path(art_rel).as_posix())
            tools_src = src_base / "tools"
            if tools_src.is_dir():
                for tf in sorted(tools_src.rglob("*.py")):
                    if "__pycache__" in tf.parts:
                        continue
                    rel_t = tf.relative_to(src_base)
                    dst_t = sandbox_dir / rel_t
                    dst_t.parent.mkdir(parents=True, exist_ok=True)
                    dst_t.write_text(
                        _SENSITIVE_COMMENT_RE.sub("<REDACTED_ID>", tf.read_text(encoding="utf-8", errors="replace")),
                        encoding="utf-8",
                    )
                    staged_files.append(rel_t.as_posix())

    # 3. 拷入绑定 [Obs###] 脱敏客观收据 JSON
    obs_ids = json.loads(rev["bound_obs_ids_json"] or "[]")
    obs_records: list[dict[str, Any]] = []
    if obs_ids:
        ph = ",".join("?" for _ in obs_ids)
        rows = conn.execute(
            f"""
            SELECT obs_id, question_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text, created_at
            FROM observations
            WHERE obs_id IN ({ph})
            ORDER BY obs_id
            """,
            tuple(obs_ids),
        ).fetchall()
        for r in rows:
            obs_records.append(
                {
                    "obs_id": str(r["obs_id"]),
                    "question_id": str(r["question_id"]),
                    "instrument_id": str(r["instrument_id"]),
                    "instrument_version": int(r["instrument_version"]),
                    "tier": str(r["tier"]),
                    "obs_status": str(r["obs_status"]),
                    "tracks": json.loads(r["tracks_json"] or "{}"),
                    "details": str(r["details_text"] or ""),
                    "created_at": str(r["created_at"]),
                }
            )
    (sandbox_dir / "observations.json").write_text(
        json.dumps(obs_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    staged_files.append("observations.json")

    # 4. 只读拷入公开题面、公开输入与手稿绑定 `spec_revision` 的《补充裁决文档》至 inputs/
    #    （若手稿绑定旧口径 vK < latest_spec_revision，挂载历史快照 ruling_revisions/vK/，绝不把事后新裁决混进旧手稿盲审！）
    try:
        p0 = conn.execute(
            "SELECT shared_inputs_json, latest_spec_revision FROM parse0_contract WHERE contract_id = 'active'"
        ).fetchone()
        shared_rels = json.loads(p0["shared_inputs_json"] or "[]") if p0 else []
        latest_spec_rev = int(p0["latest_spec_revision"] or 0) if p0 else 0
    except Exception:
        shared_rels = []
        latest_spec_rev = 0
    rev_spec = int(rev["spec_revision"] or 0) if "spec_revision" in rev.keys() else 0
    if rev_spec < latest_spec_rev:
        hist_dir = paths["ruling_revisions_dir"] / f"v{rev_spec}" if rev_spec > 0 else None
        mounted_inputs = sync_public_inputs_to_worktree(
            workspace_root,
            sandbox_dir,
            shared_rels,
            rulings_revision_dir=hist_dir,
            skip_live_rulings=True,
        )
    else:
        mounted_inputs = sync_public_inputs_to_worktree(workspace_root, sandbox_dir, shared_rels)
    staged_files.extend(mounted_inputs)

    _set_tree_readonly(sandbox_dir, True)

    return {"sandbox_abs_path": str(sandbox_dir), "staged_files": staged_files}


def _set_tree_readonly(root: Path, readonly: bool) -> None:
    """轻量设置/恢复目录内文件只读属性（不触及复杂 OS ACL，跨平台零报错）。"""
    if not root.exists():
        return
    mode = 0o444 if readonly else 0o666
    for fp in root.rglob("*"):
        if fp.is_file():
            try:
                os.chmod(fp, mode)
            except OSError:
                pass


def _rmtree_force(root: Path) -> None:
    if not root.exists():
        return
    _set_tree_readonly(root, False)
    shutil.rmtree(root, ignore_errors=True)


def cleanup_blind_review_sandbox(workspace_root: str, review_id: str) -> dict[str, Any]:
    """审毕彻底销毁临时空白盲审沙箱目录。"""
    paths = resolve_storage_paths(workspace_root)
    safe_rev = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(review_id))
    sandbox_dir = paths["blind_sandboxes_dir"] / f"blind_sandbox_{safe_rev}"
    existed = sandbox_dir.exists()
    if existed:
        _rmtree_force(sandbox_dir)
    return {"cleaned": existed, "removed": existed and not sandbox_dir.exists(), "sandbox_abs_path": str(sandbox_dir)}


def check_branch_requires_satisfied(conn: sqlite3.Connection, requires_list: list[str]) -> tuple[bool, list[str]]:
    """分支级确定性前置检查（仅支持 `L3-###` 与 `OBS:<instrument_id>:PASS`；只锁单分支，绝不跨分支并集）。"""
    unmet: list[str] = []
    for raw_req in requires_list or []:
        req = str(raw_req or "").strip()
        if not req:
            continue
        if req.startswith("L3-"):
            row = conn.execute(
                "SELECT 1 FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1",
                (req,),
            ).fetchone()
            if row is None:
                unmet.append(req)
        elif req.startswith("OBS:") and req.endswith(":PASS"):
            inst_id = req[len("OBS:"):-len(":PASS")].strip()
            active_inst = conn.execute(
                "SELECT version FROM instruments WHERE instrument_id = ? AND is_active = 1 ORDER BY version DESC LIMIT 1",
                (inst_id,),
            ).fetchone()
            if active_inst is not None:
                row = conn.execute(
                    "SELECT 1 FROM observations WHERE instrument_id = ? AND instrument_version = ? AND obs_status = 'VALID_PASS' LIMIT 1",
                    (inst_id, int(active_inst["version"])),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT 1 FROM observations WHERE instrument_id = ? AND obs_status = 'VALID_PASS' LIMIT 1",
                    (inst_id,),
                ).fetchone()
            if row is None:
                unmet.append(req)
        else:
            unmet.append(req)
    return len(unmet) == 0, unmet


def get_question_order_status(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """计算可选全局策略题序 `question_order` 解锁态（默认空 = 全子题并发推进）。"""
    p0 = conn.execute("SELECT subquestions_json, question_order_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else ["Q1"]
    q_order = json.loads(p0["question_order_json"]) if p0 else []

    full_l3_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            """
            SELECT question_id, COUNT(*) AS cnt
            FROM internal_research_ledger
            WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1 AND goal_coverage = 'FULL_GOAL'
            GROUP BY question_id
            """
        ).fetchall()
    }
    any_l3_counts = {
        str(r["question_id"]): int(r["cnt"] or 0)
        for r in conn.execute(
            """
            SELECT question_id, COUNT(*) AS cnt
            FROM internal_research_ledger
            WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
            GROUP BY question_id
            """
        ).fetchall()
    }

    status_map: dict[str, dict[str, Any]] = {}
    for q in req_qs:
        unmet_prev: list[str] = []
        if q in q_order:
            idx = q_order.index(q)
            for prev_q in q_order[:idx]:
                if full_l3_counts.get(prev_q, 0) < 1:
                    unmet_prev.append(prev_q)
        status_map[q] = {
            "unmet_order_questions": unmet_prev,
            "unlocked": len(unmet_prev) == 0,
            "full_goal_l3_count": full_l3_counts.get(q, 0),
            "total_l3_count": any_l3_counts.get(q, 0),
        }
    return status_map


def compute_family_concentration_alerts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """无豁免刚性聚拢检测：`branch_count_in_family >= 2 && share > 0.50` 立即告警（严禁高产豁免）。"""
    cfg = load_runtime_config()
    min_branches = int(cfg.get("family_concentration_min_branches_in_family", 2))
    share_threshold = float(cfg.get("family_concentration_share_threshold", 0.50))

    # 统计每个子题每个活跃分支（取每分支最新状态处于 EXPLORING/ACTIVE_REVISING/AWAITING_TRIAGE/PENDING_REVIEW 的活跃脉）
    rows = conn.execute(
        """
        SELECT question_id, branch_id, family_id
        FROM lineage_nodes
        WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
        GROUP BY question_id, branch_id
        """
    ).fetchall()

    by_q: dict[str, dict[str, set[str]]] = {}
    for r in rows:
        q = str(r["question_id"])
        b = str(r["branch_id"])
        fam = str(r["family_id"] or "unclassified")
        by_q.setdefault(q, {}).setdefault(fam, set()).add(b)

    alerts: list[dict[str, Any]] = []
    for q, fam_map in sorted(by_q.items()):
        total_active = sum(len(bs) for bs in fam_map.values())
        if total_active < min_branches:
            continue
        for fam, bs in sorted(fam_map.items()):
            cnt = len(bs)
            share = cnt / float(total_active)
            if cnt >= min_branches and share > share_threshold:
                alerts.append(
                    {
                        "question_id": q,
                        "family_id": fam,
                        "branch_count_in_family": cnt,
                        "total_active_branches": total_active,
                        "share": round(share, 4),
                        "branches": sorted(bs),
                    }
                )
    return alerts


def check_stage2_closure_gate_data(
    conn: sqlite3.Connection,
    *,
    mode: str = "FULL",
    human_aborted: bool = False,
) -> dict[str, Any]:
    """CDC 双段式终局门禁核验（严格验证 `FULL_GOAL`、`min_commitment_window` 与控制面真源 `human_stop_requested_at`）。"""
    eff_mode = str(mode or "FULL").strip().upper()
    if eff_mode not in ALLOWED_DELIVERY_MODES:
        raise FailClosedError(ERR_INVALID_INPUT, f"非法结题模式 mode={mode!r}，仅允许 {sorted(ALLOWED_DELIVERY_MODES)}")

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    min_window_sec = int(p0["min_commitment_window_sec"] or 0) if p0 else 0
    signed_dt = _parse_iso_utc(str(p0["human_signed_at"])) if p0 else None
    elapsed_sec = 0.0
    if signed_dt is not None:
        elapsed_sec = max(0.0, (datetime.now(timezone.utc) - signed_dt).total_seconds())

    closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    human_stop_ts = str(closure["human_stop_requested_at"] or "").strip() if closure else ""

    full_rows = conn.execute(
        """
        SELECT question_id, COUNT(*) AS cnt
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1 AND goal_coverage = 'FULL_GOAL'
        GROUP BY question_id
        """
    ).fetchall()
    full_counts = {str(r["question_id"]): int(r["cnt"] or 0) for r in full_rows}

    all_l3_rows = conn.execute(
        """
        SELECT question_id, COUNT(*) AS cnt
        FROM internal_research_ledger
        WHERE ledger_type = 'L3_VERIFIED' AND is_active = 1
        GROUP BY question_id
        """
    ).fetchall()
    all_l3_counts = {str(r["question_id"]): int(r["cnt"] or 0) for r in all_l3_rows}

    blocking_qs = [q for q in req_qs if full_counts.get(q, 0) < 1]
    pending_reval = conn.execute(
        "SELECT queue_id, obs_id, question_id FROM pending_revalidation_queue WHERE status = 'PENDING'"
    ).fetchall()
    pending_reviews = conn.execute(
        "SELECT review_id, question_id, review_status FROM review_queue WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')"
    ).fetchall()

    window_satisfied = elapsed_sec >= float(min_window_sec)
    # 计算总预算耗尽状态（依据 Parse 0 total_budget_json 配置的上限，未配置默认不视为耗尽）
    total_budget = json.loads(p0["total_budget_json"] or "{}") if p0 else {}
    if not isinstance(total_budget, dict):
        total_budget = {}
    used_handoffs = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM lineage_nodes
            WHERE node_status IN ('AWAITING_TRIAGE','PENDING_REVIEW','BLOCKED_L4B','SEALED','CLOSED')
               OR (column_a_facts_md IS NOT NULL AND TRIM(column_a_facts_md) != '')
            """
        ).fetchone()["cnt"]
        or 0
    )
    used_official_evals = int(
        conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM observations
            WHERE tier IN ('official','heavy') AND revalidated_from_obs_id IS NULL
            """
        ).fetchone()["cnt"]
        or 0
    )
    max_handoffs = total_budget.get("max_total_handoffs")
    max_evals = total_budget.get("max_official_evals")
    max_wall_clock = total_budget.get("max_wall_clock_sec")
    budget_exhausted = False
    if isinstance(max_handoffs, (int, float)) and max_handoffs > 0 and used_handoffs >= int(max_handoffs):
        budget_exhausted = True
    if isinstance(max_evals, (int, float)) and max_evals > 0 and used_official_evals >= int(max_evals):
        budget_exhausted = True
    if isinstance(max_wall_clock, (int, float)) and max_wall_clock > 0 and elapsed_sec >= float(max_wall_clock):
        budget_exhausted = True

    closure_allowed = False
    gate_code = "GATE_BLOCKED"

    if eff_mode == "PARTIAL_ON_HUMAN_STOP" or human_aborted:
        # 严格校验控制面真实写入的 human_stop_requested_at，绝不轻信 Agent 伪造 human_aborted=true！
        if not human_stop_ts:
            closure_allowed = False
            gate_code = "HUMAN_STOP_NOT_RECORDED"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_HUMAN_STOP"
    elif eff_mode == "PARTIAL_ON_BUDGET":
        if not window_satisfied:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_MIN_COMMITMENT_WINDOW"
        elif not budget_exhausted:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_BUDGET_NOT_EXHAUSTED"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_PARTIAL_BUDGET"
    else:  # FULL
        if not req_qs:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_NO_CONTRACT"
        elif blocking_qs:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_MISSING_FULL_GOAL_L3"
        elif pending_reval:
            closure_allowed = False
            gate_code = "GATE_BLOCKED_PENDING_REVAL"
        else:
            closure_allowed = True
            gate_code = "GATE_PASSED_FULL"

    return {
        "mode": eff_mode,
        "closure_allowed": closure_allowed,
        "gate_code": gate_code,
        "required_questions": req_qs,
        "full_goal_l3_counts": {q: full_counts.get(q, 0) for q in req_qs},
        "total_l3_counts": {q: all_l3_counts.get(q, 0) for q in req_qs},
        "blocking_questions_missing_full_goal": blocking_qs,
        "min_commitment_window_sec": min_window_sec,
        "elapsed_sec": round(elapsed_sec, 2),
        "commitment_window_satisfied": window_satisfied,
        "budget_exhausted": budget_exhausted,
        "budget_usage": {"used_handoffs": used_handoffs, "used_official_evals": used_official_evals, "limits": total_budget},
        "human_stop_requested_at": human_stop_ts or None,
        "pending_reviews": [dict(r) for r in pending_reviews],
        "pending_revalidation": [dict(r) for r in pending_reval],
    }


def schedule_control_plane_snapshot(
    conn: sqlite3.Connection,
    max_concurrent_workers: int | None = None,
    *,
    workspace_root: str = "",
) -> dict[str, Any]:
    """纯查 SQLite（<50ms，零写盘零哈希副作用）生成两级公平调度快照（严禁在此轮询中动态导入/运行任何 Python 仪器！）。"""
    _ = workspace_root
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))

    p0 = conn.execute("SELECT * FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    req_qs = json.loads(p0["subquestions_json"]) if p0 else []
    q_order = json.loads(p0["question_order_json"]) if p0 else []
    initial_instruments = json.loads(p0["initial_instruments_json"] or "[]") if p0 else []
    shared_inputs = json.loads(p0["shared_inputs_json"] or "[]") if (p0 and "shared_inputs_json" in p0.keys()) else []
    stage1_works_checked = bool(int(p0["stage1_works_checked"] or 0)) if (p0 and "stage1_works_checked" in p0.keys()) else False
    latest_spec_revision = int(p0["latest_spec_revision"] or 0) if (p0 and "latest_spec_revision" in p0.keys()) else 0
    latest_ruling_summary_md = str(p0["latest_ruling_summary_md"] or "") if (p0 and "latest_ruling_summary_md" in p0.keys()) else ""
    missing_initial_instruments = compute_missing_initial_instruments(conn) if p0 else []
    goal_md = str(p0["goal_and_completion_md"] or "") if p0 else ""
    stage = str(p0["stage"]) if p0 else "STAGE1_PARSE0"
    non_l1 = int(p0["consecutive_non_l1_handoffs"] or 0) if p0 else 0
    has_parse0_signed = bool(p0 and str(p0["human_signed_at"] or "").strip() and goal_md.strip())

    closure_row = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    closure_state = dict(closure_row) if closure_row else {
        "status": "OPEN",
        "verifier_final_audit_passed": 0,
        "human_stop_requested_at": None,
        "latest_delivery_id": None,
        "latest_delivery_sha256": None,
    }
    human_stop_active = bool(closure_state.get("human_stop_requested_at"))

    order_status = get_question_order_status(conn)

    # 查询待分诊分支集合（AWAITING_TRIAGE 硬锁：同分支有待分诊节点时严禁抢跑启动下代）
    awaiting_triage = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, evidence_grade, mechanism_summary
            FROM lineage_nodes
            WHERE node_status = 'AWAITING_TRIAGE'
            ORDER BY updated_at ASC
            """
        ).fetchall()
    ]
    triage_locked_branches = {str(r["branch_id"]) for r in awaiting_triage}

    active_nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, node_status,
                   worktree_abs_path, requires_json, premise_revoked, pressure_tokens,
                   effective_context_window, spec_revision,
                   first_reflection_unlocked, last_revision_requests_json, lane_assignment,
                   will_md, explorer_will_md, pending_handoff_mode, pending_handoff_reason, updated_at
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]

    # 批量取回各节点最新一条五段看板正文并格式化为 briefing_snapshot_md（确保探索者 100% 收到正文）
    latest_briefings: dict[str, str] = {}
    for br in conn.execute(
        """
        SELECT node_id, sec1_mechanism, sec2_verified_baseline, sec3_bottleneck,
               sec4_dead_ends, sec5_immediate_will, created_at
        FROM lineage_briefings
        ORDER BY created_at ASC
        """
    ).fetchall():
        bnid = str(br["node_id"])
        latest_briefings[bnid] = "\n\n".join(
            [
                f"#### 1. 核心机制\n{br['sec1_mechanism']}",
                f"#### 2. 已证实基线与返工要求\n{br['sec2_verified_baseline']}",
                f"#### 3. 当前瓶颈\n{br['sec3_bottleneck']}",
                f"#### 4. 关键死胡同\n{br['sec4_dead_ends']}",
                f"#### 5. 本代首要遗嘱 (Immediate Will)\n{br['sec5_immediate_will']}",
            ]
        )

    need_briefing: list[dict[str, Any]] = []
    ready_to_run: list[dict[str, Any]] = []
    pending_handoff_nodes: list[dict[str, Any]] = []
    blocked_by_requires: list[dict[str, Any]] = []

    for node in active_nodes:
        nid = str(node["node_id"])
        bid = str(node["branch_id"])
        qid = str(node["question_id"])
        # 若探索者已写完遗嘱或异常中断等待伴随落库，归入待伴随恢复队列，严禁重复派发探索者
        if node.get("pending_handoff_mode"):
            pending_handoff_nodes.append(node)
            continue
        # AWAITING_TRIAGE 同分支防抢跑硬锁
        if bid in triage_locked_branches:
            continue
        # 策略题序未解锁
        if not order_status.get(qid, {}).get("unlocked", True):
            blocked_by_requires.append({**node, "blocked_reason": "question_order_locked"})
            continue
        # 分支级确定性 requires（仅锁本分支）
        reqs = json.loads(node.get("requires_json") or "[]")
        sat, unmet = check_branch_requires_satisfied(conn, reqs)
        if not sat:
            blocked_by_requires.append({**node, "unmet_requires": unmet})
            continue
        if nid not in latest_briefings:
            need_briefing.append(node)
        else:
            ready_to_run.append({**node, "briefing_snapshot_md": latest_briefings[nid]})

    # 两级公平排序：先按子题活跃数均衡，再在子题内按学派活跃数均衡
    q_counts: dict[str, int] = {}
    qf_counts: dict[tuple[str, str], int] = {}
    for r in ready_to_run:
        q = str(r["question_id"])
        f = str(r["family_id"] or "unclassified")
        q_counts[q] = q_counts.get(q, 0) + 1
        qf_counts[(q, f)] = qf_counts.get((q, f), 0) + 1
    ready_to_run.sort(
        key=lambda r: (
            q_counts.get(str(r["question_id"]), 0),
            qf_counts.get((str(r["question_id"]), str(r["family_id"] or "unclassified")), 0),
            str(r["node_id"]),
        )
    )

    blind_reviews = [
        dict(r)
        for r in conn.execute(
            """
            SELECT review_id, question_id, source_node_id, source_type, review_status, proposer_session_id
            FROM review_queue
            WHERE review_status IN ('STAGE1_BLIND', 'STAGE2_UNBLIND')
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    pending_surveys = [
        dict(r)
        for r in conn.execute(
            "SELECT req_id, question_id, node_id, topic_query, reason FROM survey_requests WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    open_works = [
        dict(r)
        for r in conn.execute(
            "SELECT ticket_id, question_id, ticket_type, instrument_id, payload_json, updated_at FROM works_engineering_queue WHERE status = 'OPEN' ORDER BY created_at ASC"
        ).fetchall()
    ]
    pending_reval = [
        dict(r)
        for r in conn.execute(
            "SELECT queue_id, obs_id, question_id, target_instrument_id, target_version, updated_at FROM pending_revalidation_queue WHERE status = 'PENDING' ORDER BY created_at ASC"
        ).fetchall()
    ]
    unhealthy_instruments = [
        dict(r)
        for r in conn.execute(
            "SELECT instrument_id, version, question_id, instrument_role, consecutive_error_count, updated_at FROM instruments WHERE is_active = 1 AND health_status = 'UNHEALTHY'"
        ).fetchall()
    ]
    active_instruments = [
        dict(r)
        for r in conn.execute(
            """
            SELECT instrument_id, version, question_id, instrument_role,
                   artifact_schema, health_status, default_spec_json, updated_at
            FROM instruments
            WHERE is_active = 1
            ORDER BY instrument_id, version
            """
        ).fetchall()
    ]
    active_instruments_fingerprint = [
        f"{r['instrument_id']}:v{r['version']}:{r['health_status']}:{r['updated_at']}"
        for r in active_instruments
    ]
    ambiguous_alerts = [
        dict(r)
        for r in conn.execute(
            "SELECT alert_id, stage, notes, created_at FROM compliance_alerts WHERE status = 'ALERT_AMBIGUOUS_SPEC' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    ]
    external_lit_count = int(conn.execute("SELECT COUNT(*) AS cnt FROM external_literature_cards").fetchone()["cnt"] or 0)
    family_concentration_alerts = compute_family_concentration_alerts(conn)

    # 判断已解锁但既无 FULL_GOAL L3 也无在研/待分诊/待盲审节点的子题
    in_flight_qs = {
        *(str(r["question_id"]) for r in active_nodes),
        *(str(r["question_id"]) for r in awaiting_triage),
        *(str(r["question_id"]) for r in blind_reviews),
    }
    questions_needing_branch = [
        q for q in req_qs
        if order_status.get(q, {}).get("unlocked", True)
        and order_status.get(q, {}).get("full_goal_l3_count", 0) == 0
        and q not in in_flight_qs
    ]

    # Stage 3 两步联合终核待办检测（DELIVERY_EXPORTED 且尚未通过匹配当前版本的终核）
    latest_did = str(closure_state.get("latest_delivery_id") or "")
    latest_sha = str(closure_state.get("latest_delivery_sha256") or "")
    audited_did = str(closure_state.get("verifier_audited_delivery_id") or "")
    audited_sha = str(closure_state.get("verifier_audited_delivery_sha256") or "")
    verifier_matched = (
        int(closure_state.get("verifier_final_audit_passed") or 0) == 1
        and bool(latest_did)
        and audited_did == latest_did
        and audited_sha == latest_sha
    )
    stage3_revision_pending = closure_state.get("status") == "REVISION_REQUESTED"
    stage3_final_audit_pending = (
        closure_state.get("status") == "DELIVERY_EXPORTED"
        and bool(latest_did)
        and not verifier_matched
    )
    stage3_supervisory_sign_pending = (
        closure_state.get("status") == "DELIVERY_EXPORTED"
        and verifier_matched
    )

    if human_stop_active:
        closure_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_HUMAN_STOP", human_aborted=True)
    else:
        closure_gate = check_stage2_closure_gate_data(conn, mode="FULL", human_aborted=False)
        if not closure_gate["closure_allowed"] and closure_gate.get("budget_exhausted"):
            budget_gate = check_stage2_closure_gate_data(conn, mode="PARTIAL_ON_BUDGET", human_aborted=False)
            if budget_gate["closure_allowed"]:
                closure_gate = budget_gate

    stop_new_dispatch = bool(human_stop_active or closure_gate.get("closure_allowed"))

    return {
        "initialized": True,
        "stage": stage,
        "parse0_signed": has_parse0_signed,
        "stage1_works_checked": stage1_works_checked,
        "initial_instruments": initial_instruments,
        "missing_initial_instruments": missing_initial_instruments,
        "latest_spec_revision": latest_spec_revision,
        "latest_ruling_summary_md": latest_ruling_summary_md,
        "goal_and_completion_md": goal_md,
        "required_questions": req_qs,
        "question_order": q_order,
        "shared_inputs_rel_paths": shared_inputs,
        "question_order_status": order_status,
        "questions_needing_branch": questions_needing_branch,
        "external_literature_count": external_lit_count,
        "active_instruments": active_instruments,
        "active_instruments_fingerprint": active_instruments_fingerprint,
        "slot_cap": slot_cap,
        "triage_locked_branches": sorted(triage_locked_branches),
        "family_concentration_alerts": family_concentration_alerts,
        "ambiguous_spec_alerts": ambiguous_alerts,
        "unhealthy_instruments": unhealthy_instruments,
        "pending_surveys": pending_surveys,
        "open_works_tickets": open_works,
        "pending_revalidation": pending_reval,
        "awaiting_triage": awaiting_triage,
        "pending_reviews": blind_reviews,
        "pending_handoff_nodes": pending_handoff_nodes,
        "explorers_needing_briefing": [] if stop_new_dispatch else need_briefing,
        "explorers_ready_to_run": [] if stop_new_dispatch else ready_to_run[:slot_cap],
        "blocked_by_requires_nodes": blocked_by_requires,
        "stagnation_triggered": non_l1 >= int(cfg.get("stagnation_consecutive_non_l1_handoffs", 8)),
        "human_stop_active": human_stop_active,
        "closure_state": closure_state,
        "closure_gate": closure_gate,
        "stage3_revision_pending": stage3_revision_pending,
        "stage3_final_audit_pending": stage3_final_audit_pending,
        "stage3_supervisory_sign_pending": stage3_supervisory_sign_pending,
    }


def uninitialized_schedule_snapshot(max_concurrent_workers: int | None = None) -> dict[str, Any]:
    """工作区尚未建库时返回的纯只读空快照（零写盘、零建目录、零建库）。"""
    cfg = load_runtime_config()
    hard_cap = int(cfg.get("max_concurrent_workers_hard_cap", 10))
    wanted = int(max_concurrent_workers or cfg.get("max_concurrent_workers", 6))
    slot_cap = max(1, min(hard_cap, wanted))
    return {
        "initialized": False,
        "stage": "STAGE1_PARSE0",
        "parse0_signed": False,
        "stage1_works_checked": False,
        "initial_instruments": [],
        "missing_initial_instruments": [],
        "latest_spec_revision": 0,
        "latest_ruling_summary_md": "",
        "goal_and_completion_md": "",
        "required_questions": [],
        "question_order": [],
        "shared_inputs_rel_paths": [],
        "question_order_status": {},
        "questions_needing_branch": [],
        "external_literature_count": 0,
        "active_instruments": [],
        "active_instruments_fingerprint": [],
        "slot_cap": slot_cap,
        "triage_locked_branches": [],
        "family_concentration_alerts": [],
        "ambiguous_spec_alerts": [],
        "unhealthy_instruments": [],
        "pending_surveys": [],
        "open_works_tickets": [],
        "pending_revalidation": [],
        "awaiting_triage": [],
        "pending_reviews": [],
        "pending_handoff_nodes": [],
        "explorers_needing_briefing": [],
        "explorers_ready_to_run": [],
        "blocked_by_requires_nodes": [],
        "stagnation_triggered": False,
        "human_stop_active": False,
        "closure_state": {"status": "OPEN"},
        "closure_gate": {
            "mode": "FULL",
            "closure_allowed": False,
            "gate_code": "GATE_BLOCKED_NO_CONTRACT",
            "required_questions": [],
            "full_goal_l3_counts": {},
            "total_l3_counts": {},
            "blocking_questions_missing_full_goal": [],
            "min_commitment_window_sec": 0,
            "elapsed_sec": 0.0,
            "commitment_window_satisfied": True,
            "budget_exhausted": False,
            "budget_usage": {"used_handoffs": 0, "used_official_evals": 0, "limits": {}},
            "human_stop_requested_at": None,
            "pending_reviews": [],
            "pending_revalidation": [],
        },
        "stage3_revision_pending": False,
        "stage3_final_audit_pending": False,
        "stage3_supervisory_sign_pending": False,
    }


def compute_delivery_dir_sha256(delivery_dir: Path) -> str:
    """对 `<workspace>/final_delivery/` 全套五件套文件计算确定性整包 SHA-256（公开复用给终签实时核验）。"""
    h = hashlib.sha256()
    files = sorted(
        (p for p in delivery_dir.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(delivery_dir).as_posix(),
    )
    for fp in files:
        rel = fp.relative_to(delivery_dir).as_posix().encode("utf-8")
        h.update(rel + b"\x00")
        h.update(sha256_file(fp).encode("ascii") + b"\n")
    return h.hexdigest()


_compute_delivery_sha256 = compute_delivery_dir_sha256


def export_stage3_deliverables(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    delivery_mode: str,
    formal_paper_md: str,
    selected_l3_ids_by_question: dict[str, list[str]],
    remaining_gaps_by_question: dict[str, str],
    reproduction_candidate_nodes: list[str],
) -> dict[str, Any]:
    """导出 Stage 3 五件套，生成绑定版本 `(delivery_id, delivery_sha256)` 并置 `DELIVERY_EXPORTED`（重置终核签字）。"""
    # 0. 已正式联合终签 CLOSED_VERIFIED 的项目严禁重新导出或倒退结项状态！
    closure_row = conn.execute("SELECT status FROM project_closure_state WHERE id = 1").fetchone()
    if closure_row is not None and str(closure_row["status"]) == "CLOSED_VERIFIED":
        raise FailClosedError(
            ERR_LOCKED,
            "项目已通过联合终核晋升 CLOSED_VERIFIED，严禁重新导出覆写已签发交付包或倒退结项状态！",
        )

    mode_u = str(delivery_mode or "FULL").strip().upper()
    gate = check_stage2_closure_gate_data(
        conn,
        mode=mode_u,
        human_aborted=(mode_u == "PARTIAL_ON_HUMAN_STOP"),
    )
    if not gate["closure_allowed"]:
        raise FailClosedError(
            ERR_LOCKED,
            f"终局导出门禁拒止 ({gate['gate_code']}): mode={mode_u} 未满足结题放行条件！",
        )
    if not formal_paper_md or len(formal_paper_md.strip()) < 50:
        raise FailClosedError(ERR_INVALID_INPUT, "formal_paper_md 内容过短，严禁空壳成文")

    required_qs = list(gate.get("required_questions") or [])
    required_q_set = set(required_qs)
    sel_map = selected_l3_ids_by_question if isinstance(selected_l3_ids_by_question, dict) else {}

    # 强校验所有选中引用均为已入库活跃 L3_VERIFIED，且严格归属对应子题（防串题、防假子题、防空壳 FULL 导出）
    all_selected_l3: list[str] = []
    full_goal_covered_qs: set[str] = set()
    for qid, l3_list in sel_map.items():
        qid_s = str(qid).strip()
        if required_q_set and qid_s not in required_q_set:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"selected_l3_ids_by_question 包含未在 Parse 0 登记的非法子题 {qid_s!r}（合法子题：{required_qs}）",
            )
        if not isinstance(l3_list, list):
            raise FailClosedError(ERR_INVALID_INPUT, f"selected_l3_ids_by_question[{qid_s!r}] 必须为列表")
        for lid in l3_list:
            row = conn.execute(
                "SELECT entry_id, question_id, goal_coverage FROM internal_research_ledger WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1",
                (str(lid),),
            ).fetchone()
            if row is None:
                raise FailClosedError(
                    ERR_INVALID_INPUT,
                    f"严禁混入未通过两阶段盲审的草稿或无效条目: {lid!r} 不是活跃的 L3_VERIFIED！",
                )
            if str(row["question_id"]) != qid_s:
                raise FailClosedError(
                    ERR_INVALID_INPUT,
                    f"成果串题拦截：条目 {lid!r} 实际归属子题 {row['question_id']!r}，不可登记在 {qid_s!r} 名下！",
                )
            if str(row["goal_coverage"] or "") == "FULL_GOAL":
                full_goal_covered_qs.add(qid_s)
            all_selected_l3.append(str(lid))

    if mode_u == "FULL":
        missing_in_pkg = [q for q in required_qs if q not in full_goal_covered_qs]
        if missing_in_pkg:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"FULL 交付包漏交核心成果：子题 {missing_in_pkg} 未在 selected_l3_ids_by_question 中收录至少 1 条 goal_coverage='FULL_GOAL' 的活跃 L3！",
            )

    # 提前校验全部复现节点存在，杜绝写到一半报错污染旧版交付包
    repro_nodes_rows: list[sqlite3.Row] = []
    for nid in reproduction_candidate_nodes or []:
        node = conn.execute(
            "SELECT node_id, question_id, branch_id, worktree_abs_path, retained_snapshot_abs_path, candidate_rel_path FROM lineage_nodes WHERE node_id = ?",
            (str(nid),),
        ).fetchone()
        if node is None:
            raise FailClosedError(ERR_NOT_FOUND, f"复现节点 {nid!r} 不存在")
        repro_nodes_rows.append(node)

    ws_root = Path(os.path.realpath(workspace_root))
    delivery_dir = ws_root / "final_delivery"
    staging_dir = ws_root / f".final_delivery_staging_{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    repro_dir = staging_dir / "reproduction_suite"
    repro_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 正式研究报告
        (staging_dir / "01_formal_report.md").write_text(formal_paper_md.strip() + "\n", encoding="utf-8")

        # 2. 最小可运行复现套件（按 <question_id>_<node_id>/ 隔离，连同分支 tools/ 依赖完整复制）
        repro_manifest: list[dict[str, Any]] = []
        for node in repro_nodes_rows:
            src_base = Path(str(node["retained_snapshot_abs_path"] or ""))
            if not src_base.is_dir():
                src_base = Path(str(node["worktree_abs_path"] or ""))
            art_rel = str(node["candidate_rel_path"] or "").strip()
            node_bundle_dir = repro_dir / f"{node['question_id']}_{node['node_id']}"
            copied_rel = ""
            copied_tools: list[str] = []
            if src_base.is_dir() and art_rel:
                src_f = src_base / art_rel
                if src_f.is_file():
                    dst_f = node_bundle_dir / Path(art_rel)
                    dst_f.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_f, dst_f)
                    copied_rel = dst_f.relative_to(staging_dir).as_posix()
                else:
                    raise FailClosedError(
                        ERR_NOT_FOUND,
                        f"复现节点 {node['node_id']!r} 声明的入口工件 {art_rel!r} 在快照与工作树中均已缺失，拒绝导出空壳复现清单！",
                    )
                tools_src = src_base / "tools"
                if tools_src.is_dir():
                    for tf in sorted(tools_src.rglob("*")):
                        if not tf.is_file() or "__pycache__" in tf.parts or tf.suffix == ".pyc":
                            continue
                        rel_t = tf.relative_to(src_base)
                        dst_t = node_bundle_dir / rel_t
                        dst_t.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(tf, dst_t)
                        copied_tools.append(dst_t.relative_to(staging_dir).as_posix())
            elif art_rel:
                raise FailClosedError(
                    ERR_NOT_FOUND,
                    f"复现节点 {node['node_id']!r} 找不到快照或工作树目录，无法交付入口工件 {art_rel!r}！",
                )
            repro_manifest.append(
                {
                    "node_id": str(node["node_id"]),
                    "question_id": str(node["question_id"]),
                    "copied_artifact": copied_rel,
                    "copied_tools": copied_tools,
                }
            )
        (repro_dir / "manifest.json").write_text(json.dumps(repro_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        # 3. 阻碍证明与否定清单（L2 + L3 负向反例/障碍）
        neg_rows = conn.execute(
            """
            SELECT entry_id, question_id, ledger_type, l3_entry_kind, l2_category, title, exact_verified_scope_md, exact_refuted_scope_md
            FROM internal_research_ledger
            WHERE ledger_type = 'L2_FAILURE_RECORD' OR l3_entry_kind IN ('NEG_COUNTEREXAMPLE', 'BARRIER_PROOF')
            ORDER BY question_id, entry_id
            """
        ).fetchall()
        (staging_dir / "03_barriers_and_refutations.json").write_text(
            json.dumps([dict(r) for r in neg_rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 4. 谱系探索路线图
        dag_rows = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, node_status, evidence_grade, mechanism_summary
            FROM lineage_nodes
            ORDER BY question_id, branch_id, generation
            """
        ).fetchall()
        (staging_dir / "04_lineage_roadmap.json").write_text(
            json.dumps([dict(r) for r in dag_rows], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 5. 后续研究断点笔记（精确 Remaining Gaps）
        gaps_md_lines = [f"# 后续研究精确剩余断点（交付模式：{mode_u}）\n"]
        for qid, gap in (remaining_gaps_by_question or {}).items():
            gaps_md_lines.append(f"## {qid}\n{str(gap or '无剩余断点').strip()}\n")
        (staging_dir / "05_remaining_gaps_and_notes.md").write_text("\n".join(gaps_md_lines), encoding="utf-8")

        # 写入版本清单并在 staging 目录计算整包确定性 SHA-256
        delivery_id = f"deliv_{uuid.uuid4().hex[:10]}"
        meta_manifest = {
            "delivery_id": delivery_id,
            "delivery_mode": mode_u,
            "selected_l3_ids_by_question": selected_l3_ids_by_question,
            "remaining_gaps_by_question": remaining_gaps_by_question,
            "reproduction_candidate_nodes": reproduction_candidate_nodes,
        }
        (staging_dir / "delivery_manifest.json").write_text(
            json.dumps(meta_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        delivery_sha256 = compute_delivery_dir_sha256(staging_dir)

        # 全量构建并哈希成功后，再原子切换替换旧 final_delivery/
        backup_old = ws_root / f".final_delivery_old_{uuid.uuid4().hex[:6]}"
        had_old = delivery_dir.exists()
        if had_old:
            delivery_dir.rename(backup_old)
        try:
            staging_dir.rename(delivery_dir)
        except Exception:
            if had_old and backup_old.exists() and not delivery_dir.exists():
                backup_old.rename(delivery_dir)
            raise
        if had_old and backup_old.exists():
            _rmtree_force(backup_old)
    except Exception:
        _rmtree_force(staging_dir)
        raise

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        # 每次重新导出强制重置 verifier_final_audit_passed = 0 与退修备注，彻底封死“审 A 放 B”！
        conn.execute(
            """
            UPDATE project_closure_state
            SET status = 'DELIVERY_EXPORTED',
                delivery_mode = ?,
                latest_delivery_id = ?,
                latest_delivery_sha256 = ?,
                verifier_final_audit_passed = 0,
                verifier_revision_notes = '',
                updated_at = ?
            WHERE id = 1
            """,
            (mode_u, delivery_id, delivery_sha256, now),
        )
        conn.execute(
            "UPDATE parse0_contract SET stage = 'STAGE3_CONSOLIDATE', updated_at = ? WHERE contract_id = 'active'",
            (now,),
        )

    return {
        "delivery_id": delivery_id,
        "delivery_sha256": delivery_sha256,
        "delivery_mode": mode_u,
        "delivery_dir": str(delivery_dir),
        "selected_l3_count": len(all_selected_l3),
        "closure_status": "DELIVERY_EXPORTED",
    }


def execute_heavy_async_job(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    job_id: str,
) -> dict[str, Any]:
    """按 `async_eval_jobs` 入队时冻结的候选快照、原仪器版本与规格执行/恢复 heavy 作业（幂等、仅扣费一次）。"""
    job = conn.execute("SELECT * FROM async_eval_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if job is None:
        raise FailClosedError(ERR_NOT_FOUND, f"重型作业 {job_id!r} 不存在")

    if str(job["status"]) == "COMPLETED" and job["obs_id"]:
        obs = conn.execute("SELECT * FROM observations WHERE obs_id = ?", (job["obs_id"],)).fetchone()
        obs_dict = dict(obs) if obs else None
        tracks = json.loads(obs_dict["tracks_json"] or "{}") if obs_dict else {}
        return {
            "job_id": job_id,
            "status": "COMPLETED",
            "obs_id": str(job["obs_id"]),
            "obs_status": str(obs_dict["obs_status"]) if obs_dict else None,
            "tracks": tracks,
            "budget_charged": int(job["budget_charged"]),
            "observation": obs_dict,
            "replayed_idempotent": True,
        }

    inst = conn.execute(
        "SELECT * FROM instruments WHERE instrument_id = ? AND version = ?",
        (job["instrument_id"], int(job["instrument_version"])),
    ).fetchone()
    if inst is None:
        raise FailClosedError(
            ERR_NOT_FOUND,
            f"冻结的仪器版本 ({job['instrument_id']} v{job['instrument_version']}) 不存在",
        )

    ws_root = Path(os.path.realpath(workspace_root))
    frozen_inst_raw = str(job["frozen_instrument_path"] or "").strip() if "frozen_instrument_path" in job.keys() else ""
    if frozen_inst_raw and Path(frozen_inst_raw).is_file():
        inst_path = Path(frozen_inst_raw)
    else:
        inst_path = ws_root / str(inst["instrument_rel_path"])
        if not inst_path.is_file():
            from .mcp_core_helpers import core_python_root
            inst_path = core_python_root() / str(inst["instrument_rel_path"])

    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute("UPDATE async_eval_jobs SET status = 'RUNNING', updated_at = ? WHERE job_id = ?", (now, job_id))

    paths = resolve_storage_paths(workspace_root)
    obs_id = next_prefixed_id(conn, "observations", "obs_id", "Obs-")
    stage_a_persist = str(paths["eval_artifacts_dir"] / obs_id / "stage_a_output.json")

    frozen_art = Path(str(job["artifact_snapshot_path"]))
    spec_snap = json.loads(job["spec_snapshot_json"] or "{}")
    # 冻结目录同时包含冻结时刻的 tools/
    frozen_root = str(frozen_art.parent)

    res = run_isolated_instrument(
        instrument_path=inst_path,
        instrument_role=str(inst["instrument_role"]),
        artifact_path=frozen_art,
        spec=spec_snap,
        tier="heavy",
        artifact_schema=str(inst["artifact_schema"]),
        worktree_root=frozen_root,
        persist_stage_a_path=stage_a_persist,
    )

    cand_sha = sha256_file(frozen_art) if frozen_art.is_file() else sha256_bytes(b"MISSING")
    from ..evaluators.isolated_runner import compute_recursive_dir_sha256, compute_spec_sha256
    tools_sha = compute_recursive_dir_sha256(Path(frozen_root) / "tools")
    spec_sha = compute_spec_sha256(spec_snap, "heavy")
    obs_status = str(res["obs_status"])
    cache_key = "" if obs_status in ("INSTRUMENT_ERROR", "INFRA_ERROR") else str(job["cache_key"])
    now2 = utc_now_iso()

    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO observations(
                obs_id, question_id, branch_id, node_id, instrument_id, instrument_version, tier,
                candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256, cache_key,
                stage_a_artifact_path, obs_status, tracks_json, details_text, linguistic_prediction,
                spec_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'heavy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs_id,
                str(job["question_id"]),
                str(job["branch_id"]),
                str(job["node_id"]),
                str(job["instrument_id"]),
                int(job["instrument_version"]),
                cand_sha,
                tools_sha,
                spec_sha,
                str(inst["instrument_sha256"]),
                cache_key,
                stage_a_persist if Path(stage_a_persist).is_file() else None,
                obs_status,
                json.dumps(res.get("tracks") or {}, ensure_ascii=False),
                str(res.get("details") or ""),
                str(job["linguistic_prediction"] or ""),
                json.dumps(spec_snap, ensure_ascii=False),
                now2,
                now2,
            ),
        )
        declared_refs = json.loads(job["declared_refs_json"] or "[]")
        record_declared_refs(conn, source_id=obs_id, declared_refs=declared_refs, default_edge_type="MOTIVATING_REF")
        conn.execute(
            "UPDATE async_eval_jobs SET obs_id = ?, status = 'COMPLETED', updated_at = ? WHERE job_id = ?",
            (obs_id, now2, job_id),
        )

    return {
        "job_id": job_id,
        "status": "COMPLETED",
        "obs_id": obs_id,
        "obs_status": obs_status,
        "instrument_id": str(job["instrument_id"]),
        "instrument_version": int(job["instrument_version"]),
        "budget_charged": int(job["budget_charged"]),
        "result": res,
        "replayed_idempotent": False,
    }


def recover_pending_heavy_jobs(conn: sqlite3.Connection, *, workspace_root: str) -> list[dict[str, Any]]:
    """宿主重启恢复：按原冻结现场续跑所有 `QUEUED` / `RUNNING` 的 heavy 作业（不重复扣费）。"""
    rows = conn.execute(
        "SELECT job_id FROM async_eval_jobs WHERE status IN ('QUEUED', 'RUNNING') ORDER BY created_at ASC"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(execute_heavy_async_job(conn, workspace_root=workspace_root, job_id=str(r["job_id"])))
    return out
