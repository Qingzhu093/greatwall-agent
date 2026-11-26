"""控制面子域 2：独立空白盲审沙箱的现建装填、脱敏拷入、只读锁定与审毕清理。"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ..db_schema import (
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
)
from .workspace_sync import (
    _SENSITIVE_COMMENT_RE,
    sync_public_inputs_to_worktree,
)


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
        # v0.3 防审A放B：盲审官终核强制只读外部不可变冻结目录 frozen_delivery_dir_abs_path（严禁读工作区可变 final_delivery/）
        closure = conn.execute("SELECT frozen_delivery_dir_abs_path FROM project_closure_state WHERE id = 1").fetchone()
        frozen_raw = str(closure["frozen_delivery_dir_abs_path"] or "").strip() if closure else ""
        src_delivery = Path(frozen_raw) if (frozen_raw and Path(frozen_raw).is_dir()) else None
        if src_delivery is None:
            raise FailClosedError(
                ERR_NOT_FOUND,
                f"Stage 3 不可变冻结目录不存在 ({frozen_raw!r})，拒绝回退读取可变工作区目录！",
            )
        dst = sandbox_dir / "final_delivery"
        shutil.copytree(src_delivery, dst, dirs_exist_ok=True)
        for fp in sorted(dst.rglob("*")):
            if fp.is_file():
                staged_files.append(fp.relative_to(sandbox_dir).as_posix())
        # 同时导出所有活跃 L3 的原始 exact_verified_scope_md 供核查是否夸大
        l3_rows = conn.execute(
            """
            SELECT entry_id, question_id, l3_entry_kind, goal_coverage, verified_spec_revision,
                   title, exact_verified_scope_md, exact_refuted_scope_md
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
        return {"sandbox_abs_path": str(sandbox_dir), "staged_files": staged_files, "frozen_source_dir": str(src_delivery)}

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
        snap_raw = str(node["retained_snapshot_abs_path"] or "").strip()
        wt_raw = str(node["worktree_abs_path"] or "").strip()
        src_base = Path(snap_raw) if (snap_raw and Path(snap_raw).is_dir()) else (Path(wt_raw) if wt_raw else None)
        if src_base is not None and src_base.is_dir():
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

