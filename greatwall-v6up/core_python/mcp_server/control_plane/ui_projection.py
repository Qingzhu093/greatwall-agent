"""控制面子域 6：面向前端指挥舱与 inspect 工具的纯只读视图投影（与写事务物理隔离）。"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .scheduler_rules import (
    compute_topology_and_revision_health,
    schedule_control_plane_snapshot,
)
from .workspace_sync import safe_resolve_in_worktree


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
                   branch_kind, protection_generations_left, branch_budget_nodes_left,
                   companion_session_id, briefing_sealed_at, secondary_donor_node_id,
                   spec_revision, node_status, control_state, control_generation,
                   personal_turn_active, human_modified, artifact_dirty_since_last_obs,
                   worktree_abs_path, retained_snapshot_abs_path,
                   mechanism_summary, evidence_grade, candidate_rel_path, bound_obs_ids_json,
                   revise_count, inplace_repair_count, pressure_tokens, effective_context_window,
                   first_reflection_unlocked, pending_handoff_mode,
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
    interventions = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM node_interventions ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    ]
    conferences = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM wave_conferences ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    ]
    proposals = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM control_proposals ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    ]
    avoidance_radar = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM v_library_avoidance_radar ORDER BY created_at DESC LIMIT 30"
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

    sub_dict = snap.get("subproblem_states") or {}
    sub_list = snap.get("subproblem_runtime_state")
    if not isinstance(sub_list, list):
        sub_list = [sub_dict[q] for q in sorted(sub_dict.keys())]
    surveys_dict = snap.get("living_surveys") or {}
    surveys_list = snap.get("living_surveys_list")
    if not isinstance(surveys_list, list):
        surveys_list = [surveys_dict[q] for q in sorted(surveys_dict.keys())]

    return {
        "snapshot": snap,
        "topology_health": topo,
        "subproblem_states": sub_dict,
        "subproblem_runtime_state": sub_list,
        "autonomy_mode": snap.get("autonomy_mode") or "WAVE_CONFIRM",
        "living_surveys": surveys_dict,
        "living_surveys_list": surveys_list,
        "pending_proposals": snap.get("pending_proposals") or [],
        "proposals": proposals,
        "wave_conferences": conferences,
        "active_wave_conferences": snap.get("active_wave_conferences") or snap.get("active_conferences") or [],
        "open_lemma_gaps": snap.get("open_lemma_gaps") or [],
        "avoidance_radar": avoidance_radar,
        "node_interventions": interventions,
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

