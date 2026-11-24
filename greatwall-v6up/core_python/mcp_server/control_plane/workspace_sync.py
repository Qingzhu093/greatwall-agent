"""控制面子域 1：工作区与 Worktree 同步、公开输入/裁决同步、物理快照与工具扫描。"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ...evaluators.isolated_runner import sha256_file
from ..db_schema import (
    ERR_INVALID_INPUT,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from ..mcp_core_helpers import core_python_root

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

