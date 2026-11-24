"""控制面子域 5：Stage 3 五件套原子导出、版本哈希绑定与重型异步评测作业恢复。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ...evaluators.isolated_runner import (
    run_isolated_instrument,
    sha256_bytes,
    sha256_file,
)
from ..db_schema import (
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from ..mcp_core_helpers import (
    next_prefixed_id,
    record_declared_refs,
)
from .blind_sandbox import _rmtree_force
from .scheduler_rules import check_stage2_closure_gate_data


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
            from ..mcp_core_helpers import core_python_root
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
    from ...evaluators.isolated_runner import compute_recursive_dir_sha256, compute_spec_sha256
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

