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


def sync_public_instruments_and_skills_to_worktree(
    conn: sqlite3.Connection,
    workspace_root: str,
    target_root: str | Path,
) -> list[str]:
    """将已激活的公开 PROBE/ENV 仪器源码、SKILL_LEDGER 共享探针及全量活跃仪器说明书清单只读镜像至探索者 Worktree。

    严守安全边界：
    1. 绝不拷贝任何校准集（`calibration_suite_rel_path` / `_hidden_calibrations`）或 `VERDICT` 裁判内部隐藏真值；
    2. `PROBE` 与 `ENV` 仪器（以及 `SKILL_LEDGER.json` 登记的共享探针）同步至 `<worktree>/inputs/instruments/`
       与 `<worktree>/tools/shared_probes/`，使探索者在自身 Worktree 内即可用 `pwsh` / `import` 直接运行探针与模拟器；
    3. 生成 `<worktree>/inputs/instruments/INSTRUMENT_CATALOG.json`，清晰列出全部活跃仪器（含 `VERDICT`）的
       `instrument_id`、`version`、`artifact_schema` 与 `default_spec_json`（含 `interface_hint`）。
    """
    ws = Path(os.path.realpath(workspace_root or ""))
    tgt_base = Path(os.path.realpath(str(target_root)))
    if not tgt_base.is_dir():
        return []

    core_root = Path(__file__).resolve().parent.parent
    inst_out_dir = tgt_base / "inputs" / "instruments"
    shared_tools_dir = tgt_base / "tools" / "shared_probes"
    synced: list[str] = []

    try:
        active_rows = conn.execute(
            """
            SELECT instrument_id, version, question_id, instrument_role, instrument_rel_path,
                   frozen_snapshot_path, artifact_schema, health_status, default_spec_json, updated_at
            FROM instruments
            WHERE is_active = 1
            ORDER BY question_id, instrument_id, version DESC
            """
        ).fetchall()
    except Exception:
        active_rows = []

    catalog_entries: list[dict[str, Any]] = []
    for r in active_rows:
        iid = str(r["instrument_id"])
        role_u = str(r["instrument_role"]).upper()
        rel_p = str(r["instrument_rel_path"] or "").strip()
        frozen_p = str(r["frozen_snapshot_path"] or "").strip() if "frozen_snapshot_path" in r.keys() else ""
        try:
            spec_obj = json.loads(r["default_spec_json"] or "{}")
            if not isinstance(spec_obj, dict):
                spec_obj = {}
        except Exception:
            spec_obj = {}

        local_mirror_rel: str | None = None
        if role_u in ("PROBE", "ENV"):
            src_fp: Path | None = None
            if ws.is_dir() and rel_p:
                cand_ws = Path(os.path.realpath(ws / rel_p))
                if cand_ws.is_file() and "_hidden" not in cand_ws.as_posix().lower():
                    src_fp = cand_ws
            if src_fp is None and rel_p:
                cand_core = Path(os.path.realpath(core_root / rel_p))
                if cand_core.is_file() and "_hidden" not in cand_core.as_posix().lower():
                    src_fp = cand_core
            if src_fp is None and frozen_p:
                cand_frz = Path(frozen_p)
                if cand_frz.is_file():
                    src_fp = cand_frz

            if src_fp is not None and src_fp.is_file():
                safe_name = Path(rel_p).name if rel_p else f"{iid}.py"
                inst_out_dir.mkdir(parents=True, exist_ok=True)
                shared_tools_dir.mkdir(parents=True, exist_ok=True)
                dst1 = inst_out_dir / safe_name
                dst2 = shared_tools_dir / safe_name
                try:
                    shutil.copy2(src_fp, dst1)
                    shutil.copy2(src_fp, dst2)
                    local_mirror_rel = dst1.relative_to(tgt_base).as_posix()
                    synced.append(local_mirror_rel)
                    synced.append(dst2.relative_to(tgt_base).as_posix())
                except OSError:
                    pass

        catalog_entries.append(
            {
                "instrument_id": iid,
                "version": int(r["version"]),
                "question_id": str(r["question_id"]),
                "instrument_role": role_u,
                "artifact_schema": str(r["artifact_schema"] or "python_run"),
                "health_status": str(r["health_status"] or "HEALTHY"),
                "interface_hint": str(spec_obj.get("interface_hint") or ""),
                "default_spec": spec_obj,
                "worktree_local_path": local_mirror_rel,
            }
        )

    # 同步 SKILL_LEDGER.json 中的共享探针
    try:
        paths = resolve_storage_paths(workspace_root, create_dirs=False)
        ledger_path = paths["skills_ledger_path"]
        if not ledger_path.is_file():
            ledger_path = core_root / "skills" / "SKILL_LEDGER.json"
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            skills_map = ledger.get("skills") if isinstance(ledger, dict) else {}
            if isinstance(skills_map, dict):
                for sid, sinfo in sorted(skills_map.items()):
                    if not isinstance(sinfo, dict):
                        continue
                    v_rel = str(sinfo.get("verified_artifact_rel_path") or "").strip()
                    if not v_rel:
                        continue
                    src_sk: Path | None = None
                    if ws.is_dir() and (ws / v_rel).is_file():
                        src_sk = ws / v_rel
                    elif (core_root / v_rel).is_file():
                        src_sk = core_root / v_rel
                    if src_sk is not None and src_sk.is_file() and "_hidden" not in src_sk.as_posix().lower():
                        shared_tools_dir.mkdir(parents=True, exist_ok=True)
                        dst_sk = shared_tools_dir / Path(v_rel).name
                        try:
                            shutil.copy2(src_sk, dst_sk)
                            synced.append(dst_sk.relative_to(tgt_base).as_posix())
                        except OSError:
                            pass
    except Exception:
        pass

    if catalog_entries:
        inst_out_dir.mkdir(parents=True, exist_ok=True)
        cat_fp = inst_out_dir / "INSTRUMENT_CATALOG.json"
        try:
            cat_fp.write_text(
                json.dumps(
                    {
                        "schema_version": "3.0.0",
                        "note": "活跃科研仪器与本地镜像清单：PROBE/ENV 已同步至 inputs/instruments/ 与 tools/shared_probes/ 可直接在本地 pwsh/python 调用；正式 [Obs###] 凭证请调 run_isolated_eval(tier='official')。",
                        "instruments": catalog_entries,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            synced.append(cat_fp.relative_to(tgt_base).as_posix())
        except OSError:
            pass

    return synced


def sync_public_instruments_to_all_active_worktrees(
    conn: sqlite3.Connection,
    workspace_root: str,
) -> int:
    """当工造司注册/升版仪器或更新共享探针时，增量同步至所有当前活跃探索分支的 Worktree。"""
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT worktree_abs_path
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE')
            """
        ).fetchall()
    except Exception:
        return 0
    count = 0
    for r in rows:
        wt = str(r["worktree_abs_path"] or "").strip()
        if wt and Path(wt).is_dir():
            sync_public_instruments_and_skills_to_worktree(conn, workspace_root, wt)
            count += 1
    return count


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


_ALLOWED_WORKS_TICKET_TYPES = {"INSTRUMENT_ERROR", "PAIN_POINT", "DUPLICATE_TOOL", "EXPLOIT"}


def submit_works_ticket(
    conn: sqlite3.Connection,
    *,
    question_id: str = "ALL",
    ticket_type: str = "INSTRUMENT_ERROR",
    instrument_id: str | None = None,
    description: str = "",
    source: str = "main_controller",
) -> dict[str, Any]:
    """控制面/主控向科研仪器科（works_engineering_queue）直接签发正式 OPEN 工单。

    适用场景：主控或人类在运行期间发现明显的仪器逻辑缺陷、接口错误、校准集漏洞或缺失探针，
    通过控制面正规通道入队并立即唤醒工造司（works_engineer）定向修复与升版，严禁越权直改 DB。
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
    tid = f"tkt_{uuid.uuid4().hex[:10]}"
    now = utc_now_iso()
    payload = {
        "source": src,
        "description": desc,
        "instrument_id": iid,
        "submitted_at": now,
    }
    with rw_immediate_tx(conn):
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
        "created_at": now,
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


def compute_topology_and_revision_health(
    conn: sqlite3.Connection,
    *,
    question_filter: str = "ALL",
    slot_cap: int | None = None,
) -> dict[str, Any]:
    """纯查 SQLite (<15ms) 计算全卷或指定子题的 Worktree 拓扑健康度、断代分支、孤儿盲审返工单与缺编正交学派。

    消除第六轮暴露的四大治理盲区：
    1. 断代分支（`stalled_or_aborted_branches`）：最新节点为 `CLOSED`（含被 `abort_node` 中止）且所在子题尚未取得 `FULL_GOAL L3`；
    2. 孤儿盲审返工单（`orphaned_blind_review_revisions`）：盲审判了 `REVISE`（`CLOSED_REVISE`）要求定向返工，但原分支被中止或断代、当前无活跃节点承接；
    3. 缺编正交学派与单线独苗退化（`understaffed_questions`）：子题已注册 >=2 个 `ACTIVE` 学派且有空闲槽位，但在跑活跃学派数 < min(2, 已登记活跃学派数)；
    4. 并发槽位利用率（`slot_utilization`）：`active_branches_count` / `slot_cap` / `free_slots`。
    """
    cfg = load_runtime_config()
    eff_slot_cap = int(slot_cap or cfg.get("max_concurrent_workers", 6))
    qf = str(question_filter or "ALL").strip()
    order_status = get_question_order_status(conn)

    # 1. 已注册方法学派
    if qf.upper() == "ALL":
        fam_rows = conn.execute("SELECT * FROM method_families ORDER BY question_id, family_id").fetchall()
    else:
        fam_rows = conn.execute(
            "SELECT * FROM method_families WHERE question_id = ? ORDER BY family_id",
            (qf,),
        ).fetchall()

    active_families_by_q: dict[str, list[str]] = {}
    for fr in fam_rows:
        if str(fr["family_status"] or "ACTIVE") == "ACTIVE":
            active_families_by_q.setdefault(str(fr["question_id"]), []).append(str(fr["family_id"]))

    # 2. 按 branch_id 聚合每条分支的最新一代节点状态
    if qf.upper() == "ALL":
        all_nodes = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                   spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                   inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                   pressure_tokens, effective_context_window, first_reflection_unlocked,
                   created_at, updated_at
            FROM lineage_nodes
            ORDER BY generation ASC, created_at ASC
            """
        ).fetchall()
    else:
        all_nodes = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                   spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, revise_count,
                   inplace_repair_count, last_revision_requests_json, pending_handoff_reason,
                   pressure_tokens, effective_context_window, first_reflection_unlocked,
                   created_at, updated_at
            FROM lineage_nodes
            WHERE question_id = ?
            ORDER BY generation ASC, created_at ASC
            """,
            (qf,),
        ).fetchall()

    latest_by_branch: dict[str, dict[str, Any]] = {}
    branch_has_live_node: set[str] = set()
    live_statuses = ("EXPLORING", "ACTIVE_REVISING", "AWAITING_TRIAGE", "PENDING_REVIEW")
    for r in all_nodes:
        d = dict(r)
        bid = str(d["branch_id"])
        latest_by_branch[bid] = d
        if str(d["node_status"]) in live_statuses:
            branch_has_live_node.add(bid)

    # 统计总活跃探索分支槽位（全卷口径）
    total_live_branches = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT branch_id) AS cnt
            FROM lineage_nodes
            WHERE node_status IN ('EXPLORING', 'ACTIVE_REVISING', 'AWAITING_TRIAGE', 'PENDING_REVIEW')
            """
        ).fetchone()["cnt"]
        or 0
    )
    free_slots = max(0, eff_slot_cap - total_live_branches)

    # 3. 检索所有 CLOSED_REVISE 盲审单，判断是否已被后续活跃分支承接
    if qf.upper() == "ALL":
        rev_rows = conn.execute(
            """
            SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                   r.final_verdict, r.revision_requests_json, r.updated_at,
                   n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
            FROM review_queue r
            LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
            WHERE r.review_status = 'CLOSED_REVISE'
            ORDER BY r.updated_at DESC
            """
        ).fetchall()
    else:
        rev_rows = conn.execute(
            """
            SELECT r.review_id, r.question_id, r.source_node_id, r.manuscript_title,
                   r.final_verdict, r.revision_requests_json, r.updated_at,
                   n.branch_id, n.family_id, n.retained_snapshot_abs_path, n.worktree_abs_path
            FROM review_queue r
            LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
            WHERE r.review_status = 'CLOSED_REVISE' AND r.question_id = ?
            ORDER BY r.updated_at DESC
            """,
            (qf,),
        ).fetchall()

    # 判断某个 source_node_id 是否已有后代节点送过新盲审或正处于活跃态
    active_parent_ids = {
        str(r["parent_node_id"])
        for r in all_nodes
        if r["parent_node_id"] and str(r["node_status"]) in live_statuses
    }
    reviewed_source_nodes = {
        str(r["source_node_id"])
        for r in conn.execute("SELECT source_node_id FROM review_queue").fetchall()
    }

    orphaned_revisions: list[dict[str, Any]] = []
    orphaned_by_branch: dict[str, dict[str, Any]] = {}
    for rr in rev_rows:
        rqid = str(rr["question_id"])
        if order_status.get(rqid, {}).get("full_goal_l3_count", 0) > 0:
            continue
        rbid = str(rr["branch_id"] or "")
        src_nid = str(rr["source_node_id"])
        if rbid in branch_has_live_node or src_nid in active_parent_ids:
            continue
        # 检查是否有后代节点已经重新送审
        descendant_resubmitted = any(
            str(n["parent_node_id"] or "") == src_nid and str(n["node_id"]) in reviewed_source_nodes
            for n in all_nodes
        )
        if descendant_resubmitted:
            continue
        try:
            reqs_list = json.loads(rr["revision_requests_json"] or "[]")
        except Exception:
            reqs_list = []
        item = {
            "review_id": str(rr["review_id"]),
            "question_id": rqid,
            "source_node_id": src_nid,
            "branch_id": rbid,
            "family_id": str(rr["family_id"] or ""),
            "manuscript_title": str(rr["manuscript_title"] or ""),
            "revision_requests": reqs_list,
            "retained_snapshot_abs_path": rr["retained_snapshot_abs_path"],
            "worktree_abs_path": rr["worktree_abs_path"],
            "respawn_guidance": (
                f"调用 fork_branch(question_id={rqid!r}, parent_node_id={src_nid!r}, "
                f"fork_mode='lateral', target_family_id={str(rr['family_id'] or '')!r}) "
                f"即可继承其快照与 {rr['review_id']} 返工单继续冲刺二审"
            ),
        }
        orphaned_revisions.append(item)
        if rbid:
            orphaned_by_branch[rbid] = item

    # 4. 整理断代/被中止分支列表
    stalled_branches: list[dict[str, Any]] = []
    live_families_by_q: dict[str, set[str]] = {}
    live_branches_by_q: dict[str, list[str]] = {}

    for bid, latest in sorted(latest_by_branch.items()):
        qid = str(latest["question_id"])
        fid = str(latest["family_id"] or "")
        st = str(latest["node_status"])
        if st in live_statuses:
            if fid:
                live_families_by_q.setdefault(qid, set()).add(fid)
            live_branches_by_q.setdefault(qid, []).append(bid)
            continue
        if st == "CLOSED" and order_status.get(qid, {}).get("full_goal_l3_count", 0) == 0:
            try:
                rev_reqs = json.loads(latest.get("last_revision_requests_json") or "[]")
            except Exception:
                rev_reqs = []
            orphan_rev = orphaned_by_branch.get(bid)
            if orphan_rev and not rev_reqs:
                rev_reqs = orphan_rev.get("revision_requests") or []
            stalled_branches.append(
                {
                    "branch_id": bid,
                    "question_id": qid,
                    "family_id": fid,
                    "last_node_id": str(latest["node_id"]),
                    "last_generation": int(latest["generation"] or 1),
                    "last_node_status": st,
                    "close_reason": str(latest.get("pending_handoff_reason") or "CLOSED_OR_ABORTED"),
                    "retained_snapshot_abs_path": latest.get("retained_snapshot_abs_path"),
                    "worktree_abs_path": latest.get("worktree_abs_path"),
                    "pending_blind_review_id": orphan_rev["review_id"] if orphan_rev else None,
                    "pending_revision_requests": rev_reqs,
                }
            )

    # 5. 检查各解锁子题是否存在“正交学派缺编 / 单线独苗退化”
    understaffed_questions: list[dict[str, Any]] = []
    check_qs = sorted(active_families_by_q.keys()) if qf.upper() == "ALL" else [qf]
    for q in check_qs:
        q_info = order_status.get(q, {})
        if not q_info.get("unlocked", True) or q_info.get("full_goal_l3_count", 0) > 0:
            continue
        reg_fams = active_families_by_q.get(q, [])
        live_fams = sorted(live_families_by_q.get(q, set()))
        missing_fams = [f for f in reg_fams if f not in live_fams]
        live_b_list = live_branches_by_q.get(q, [])
        # 当注册了 >=2 个活跃学派，但当前在跑分支数退化为 <=1（独苗或全空），且有空闲槽位时告警
        is_degenerated = len(reg_fams) >= 2 and len(live_b_list) < min(2, len(reg_fams)) and free_slots > 0
        if missing_fams and (is_degenerated or len(live_b_list) == 0):
            understaffed_questions.append(
                {
                    "question_id": q,
                    "registered_active_families": reg_fams,
                    "active_families_in_flight": live_fams,
                    "missing_active_family_ids": missing_fams,
                    "active_branch_count": len(live_b_list),
                    "free_explorer_slots": free_slots,
                    "single_branch_monopoly": len(live_b_list) == 1 and len(reg_fams) >= 2,
                }
            )

    return {
        "slot_utilization": {
            "active_branches_count": total_live_branches,
            "slot_cap": eff_slot_cap,
            "free_slots": free_slots,
        },
        "stalled_or_aborted_branches": stalled_branches,
        "orphaned_blind_review_revisions": orphaned_revisions,
        "understaffed_questions": understaffed_questions,
    }


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
    topology_health = compute_topology_and_revision_health(conn, question_filter="ALL", slot_cap=slot_cap)
    orphaned_revisions = topology_health.get("orphaned_blind_review_revisions") or []
    understaffed_questions = topology_health.get("understaffed_questions") or []
    stalled_branches = topology_health.get("stalled_or_aborted_branches") or []

    # 读取最近一条监察委 STAGE2_HEARTBEAT 合规告警（若状态为 ALERT，用于闭环唤醒后勤/工造司）
    latest_hb_row = conn.execute(
        """
        SELECT alert_id, stage, status, blocking_questions_json, notes, created_at
        FROM compliance_alerts
        WHERE stage = 'STAGE2_HEARTBEAT'
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    active_supervisory_alert: dict[str, Any] | None = None
    if latest_hb_row is not None and str(latest_hb_row["status"]).upper() == "ALERT":
        active_supervisory_alert = dict(latest_hb_row)

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
        "understaffed_questions": [] if stop_new_dispatch else understaffed_questions,
        "orphaned_blind_review_revisions": [] if stop_new_dispatch else orphaned_revisions,
        "stalled_or_aborted_branches": stalled_branches,
        "slot_utilization": topology_health.get("slot_utilization") or {"active_branches_count": 0, "slot_cap": slot_cap, "free_slots": slot_cap},
        "active_supervisory_alert": active_supervisory_alert,
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
        "understaffed_questions": [],
        "orphaned_blind_review_revisions": [],
        "stalled_or_aborted_branches": [],
        "slot_utilization": {"active_branches_count": 0, "slot_cap": slot_cap, "free_slots": slot_cap},
        "active_supervisory_alert": None,
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


def get_ui_full_inspector_payload(
    conn: sqlite3.Connection,
    *,
    workspace_root: str = "",
    selected_node_id: str | None = None,
    selected_worktree_rel_file: str | None = None,
) -> dict[str, Any]:
    """为右侧挂板 UI「长城科研指挥舱」提供全景只读透视数据（<30ms）：
    1. 全部探索节点谱系 DAG 树（含 0%—37%—70% 水位、绑定 [Obs-###]、学派、状态与父子关系）；
    2. 方法学派与断代分支、孤儿盲审返工单、监察委 watchdog_anomalies；
    3. 观测账 summary + 探针日志 summary + 盲审单列表 + 工造司工单；
    4. 选中节点的深潜文书详情（五段看板全文、37% 元反思问答原文、70% 探索者亲笔遗嘱 + A/B 栏交接单、死胡同列表、Worktree 文件树与源码预览）。
    """
    snap = schedule_control_plane_snapshot(conn, workspace_root=workspace_root)
    topo = compute_topology_and_revision_health(conn, question_filter="ALL")

    families = [
        dict(r)
        for r in conn.execute("SELECT * FROM method_families ORDER BY question_id, family_id").fetchall()
    ]
    all_nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, parent_node_id, generation,
                   spec_revision, node_status, worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, bound_obs_ids_json,
                   revise_count, inplace_repair_count, pressure_tokens, effective_context_window,
                   first_reflection_unlocked, lane_assignment, pending_handoff_mode,
                   pending_handoff_reason, created_at, updated_at
            FROM lineage_nodes
            ORDER BY created_at ASC
            """
        ).fetchall()
    ]
    for nd in all_nodes:
        try:
            nd["bound_obs_ids"] = json.loads(nd.get("bound_obs_ids_json") or "[]")
        except Exception:
            nd["bound_obs_ids"] = []
        win = max(1, int(nd.get("effective_context_window") or 500000))
        tok = int(nd.get("pressure_tokens") or 0)
        nd["pressure_pct"] = round((tok / float(win)) * 100.0, 1)

    obs_list = [
        dict(r)
        for r in conn.execute(
            """
            SELECT obs_id, question_id, branch_id, node_id, instrument_id, instrument_version,
                   tier, obs_status, tracks_json, substr(details_text, 1, 500) AS details_preview, created_at
            FROM observations
            ORDER BY created_at DESC LIMIT 60
            """
        ).fetchall()
    ]
    probes_list = [
        dict(r)
        for r in conn.execute(
            """
            SELECT probe_id, node_id, question_id, instrument_id, instrument_version,
                   status, tracks_json, substr(details_text, 1, 400) AS details_preview, created_at
            FROM probe_diagnostic_logs
            ORDER BY created_at DESC LIMIT 30
            """
        ).fetchall()
    ]
    reviews_list = [
        dict(r)
        for r in conn.execute(
            """
            SELECT review_id, question_id, source_node_id, source_type, review_status,
                   manuscript_title, spec_revision, final_verdict, stage1_ledger_json,
                   revision_requests_json, created_at, updated_at
            FROM review_queue
            ORDER BY created_at DESC LIMIT 30
            """
        ).fetchall()
    ]
    l3_l2_entries = [
        dict(r)
        for r in conn.execute(
            """
            SELECT entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage,
                   l2_category, title, substr(abstract_md, 1, 400) AS abstract_preview,
                   exact_verified_scope_md, exact_refuted_scope_md, verified_review_id, created_at
            FROM internal_research_ledger
            WHERE is_active = 1
            ORDER BY created_at DESC LIMIT 40
            """
        ).fetchall()
    ]
    works_tickets = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM works_engineering_queue ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    ]
    compliance_logs = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM compliance_alerts ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    ]

    # 若未指定 selected_node_id，默认选最新更新的探索节点
    target_nid = str(selected_node_id or "").strip()
    if not target_nid and all_nodes:
        target_nid = str(all_nodes[-1]["node_id"])

    node_detail: dict[str, Any] | None = None
    if target_nid:
        nrow = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (target_nid,)).fetchone()
        if nrow is not None:
            nd_full = dict(nrow)
            briefings = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM lineage_briefings WHERE node_id = ? OR branch_id = ? ORDER BY created_at DESC LIMIT 5",
                    (target_nid, nd_full["branch_id"]),
                ).fetchall()
            ]
            dead_ends = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM lineage_dead_ends WHERE branch_id = ? ORDER BY created_at DESC LIMIT 20",
                    (nd_full["branch_id"],),
                ).fetchall()
            ]
            node_obs = [
                dict(r)
                for r in conn.execute(
                    "SELECT obs_id, instrument_id, instrument_version, tier, obs_status, tracks_json, details_text, created_at FROM observations WHERE node_id = ? ORDER BY created_at ASC",
                    (target_nid,),
                ).fetchall()
            ]
            node_reviews = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM review_queue WHERE source_node_id = ? ORDER BY created_at DESC",
                    (target_nid,),
                ).fetchall()
            ]
            try:
                reflections_parsed = json.loads(nd_full.get("reflections_json") or "[]")
            except Exception:
                reflections_parsed = []
            try:
                rev_reqs_parsed = json.loads(nd_full.get("last_revision_requests_json") or "[]")
            except Exception:
                rev_reqs_parsed = []

            # 扫描该节点 Worktree（及快照目录）文件树
            wt_abs = str(nd_full.get("worktree_abs_path") or "").strip()
            wt_files: list[dict[str, Any]] = []
            preview_file_rel = str(selected_worktree_rel_file or nd_full.get("candidate_rel_path") or "").strip()
            preview_content = ""

            if wt_abs and Path(wt_abs).is_dir():
                wt_root = Path(os.path.realpath(wt_abs))
                for fp in sorted(wt_root.rglob("*")):
                    if not fp.is_file():
                        continue
                    rel_parts = fp.relative_to(wt_root).parts
                    if any(p in (".git", "__pycache__", ".venv", "node_modules") for p in rel_parts):
                        continue
                    rel_p = fp.relative_to(wt_root).as_posix()
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        sz = 0
                    wt_files.append({"rel_path": rel_p, "size": sz})
                    if not preview_file_rel and fp.suffix.lower() in (".py", ".md", ".json", ".txt") and not rel_p.startswith("inputs/"):
                        preview_file_rel = rel_p

                if preview_file_rel:
                    try:
                        target_fp = safe_resolve_in_worktree(str(wt_root), preview_file_rel)
                        if target_fp.is_file():
                            preview_content = target_fp.read_text(encoding="utf-8", errors="replace")[:16000]
                    except Exception:
                        preview_content = ""

            node_detail = {
                "node_id": target_nid,
                "question_id": str(nd_full["question_id"]),
                "branch_id": str(nd_full["branch_id"]),
                "family_id": str(nd_full.get("family_id") or ""),
                "parent_node_id": nd_full.get("parent_node_id"),
                "generation": int(nd_full.get("generation") or 1),
                "spec_revision": int(nd_full.get("spec_revision") or 0),
                "node_status": str(nd_full["node_status"]),
                "pressure_tokens": int(nd_full.get("pressure_tokens") or 0),
                "effective_context_window": int(nd_full.get("effective_context_window") or 500000),
                "first_reflection_unlocked": int(nd_full.get("first_reflection_unlocked") or 0),
                "mechanism_summary": str(nd_full.get("mechanism_summary") or ""),
                "evidence_grade": str(nd_full.get("evidence_grade") or "NONE"),
                "candidate_rel_path": nd_full.get("candidate_rel_path"),
                "worktree_abs_path": wt_abs,
                "retained_snapshot_abs_path": nd_full.get("retained_snapshot_abs_path"),
                "explorer_will_md": str(nd_full.get("explorer_will_md") or nd_full.get("will_md") or ""),
                "will_md": str(nd_full.get("will_md") or ""),
                "column_a_facts_md": str(nd_full.get("column_a_facts_md") or ""),
                "column_b_hypothesis_md": str(nd_full.get("column_b_hypothesis_md") or ""),
                "sanitized_code_diff_md": str(nd_full.get("sanitized_code_diff_md") or "")[:12000],
                "reflections": reflections_parsed,
                "active_revision_requests": rev_reqs_parsed,
                "briefings": briefings,
                "dead_ends": dead_ends,
                "observations": node_obs,
                "reviews": node_reviews,
                "worktree_files": wt_files[:120],
                "preview_file_rel": preview_file_rel,
                "preview_file_content": preview_content,
            }

    return {
        "snapshot": snap,
        "topology_health": topo,
        "method_families": families,
        "lineage_nodes": all_nodes,
        "observations": obs_list,
        "probes": probes_list,
        "reviews": reviews_list,
        "internal_ledger": l3_l2_entries,
        "works_tickets": works_tickets,
        "compliance_logs": compliance_logs,
        "selected_node_detail": node_detail,
    }
