"""设施控制面子域：Stage 3 五件套外部不可变冻结导出与一步防篡改终签（裁决 3）。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ...evaluators.isolated_runner import RequestCancelledError, sha256_file
from ..db_runtime import _SINGLE_WRITER_LOCK
from ..db_schema import (
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)
from .blind_sandbox import _rmtree_force, _set_tree_readonly
from .scheduler_rules import check_stage2_closure_gate_data
from .subproblem_locks import get_subproblem_active_spec_revision
from .workspace_sync import sync_approved_public_inputs


def compute_delivery_dir_sha256(delivery_dir: Path) -> str:
    """对五件套目录计算确定性整包 SHA-256（只读安全，可在写锁外执行）。"""
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


def export_stage3_deliverables_v03(
    conn: sqlite3.Connection,
    *,
    workspace_root: str,
    delivery_mode: str,
    formal_paper_md: str,
    selected_l3_ids_by_question: dict[str, list[str]],
    remaining_gaps_by_question: dict[str, str],
    reproduction_candidate_nodes: list[str],
    cancel_event: Any = None,
) -> dict[str, Any]:
    """导出 Stage 3 五件套至工作区 `final_delivery/`，同时原子冻结至外部不可变目录 `frozen_deliveries/<delivery_id>/`。"""
    if cancel_event is not None and cancel_event.is_set():
        raise RequestCancelledError("Stage 3 导出在开始前已取消")

    closure_row = conn.execute("SELECT status FROM project_closure_state WHERE id = 1").fetchone()
    if closure_row is not None and str(closure_row["status"]) == "CLOSED_VERIFIED":
        raise FailClosedError(ERR_LOCKED, "项目已通过终核晋升 CLOSED_VERIFIED，严禁覆盖已签发交付包！")

    mode_u = str(delivery_mode or "FULL").strip().upper()
    gate = check_stage2_closure_gate_data(conn, mode=mode_u, human_aborted=(mode_u == "PARTIAL_ON_HUMAN_STOP"))
    if not gate["closure_allowed"]:
        raise FailClosedError(ERR_LOCKED, f"终局导出门禁拒止 ({gate['gate_code']}): mode={mode_u} 未满足结题条件！")
    if not formal_paper_md or len(formal_paper_md.strip()) < 50:
        raise FailClosedError(ERR_INVALID_INPUT, "formal_paper_md 内容过短，严禁空壳成文")

    required_qs = list(gate.get("required_questions") or [])
    required_q_set = set(required_qs)
    sel_map = selected_l3_ids_by_question if isinstance(selected_l3_ids_by_question, dict) else {}

    all_selected_l3: list[str] = []
    full_goal_covered_qs: set[str] = set()
    active_spec_by_q = {
        str(r["question_id"]): int(r["active_spec_revision"] or 0)
        for r in conn.execute("SELECT question_id, active_spec_revision FROM subproblem_runtime_state").fetchall()
    }

    for qid, l3_list in sel_map.items():
        qid_s = str(qid).strip()
        if required_q_set and qid_s not in required_q_set:
            raise FailClosedError(ERR_INVALID_INPUT, f"非法子题 {qid_s!r}（合法子题：{required_qs}）")
        if not isinstance(l3_list, list):
            raise FailClosedError(ERR_INVALID_INPUT, f"selected_l3_ids_by_question[{qid_s!r}] 必须为列表")
        q_req_rev = active_spec_by_q.get(qid_s, 0)
        for lid in l3_list:
            row = conn.execute(
                """
                SELECT entry_id, question_id, goal_coverage, verified_spec_revision
                FROM internal_research_ledger
                WHERE entry_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
                """,
                (str(lid),),
            ).fetchone()
            if row is None:
                raise FailClosedError(ERR_INVALID_INPUT, f"严禁混入未通过两阶段盲审的草稿或无效条目: {lid!r}")
            if str(row["question_id"]) != qid_s:
                raise FailClosedError(ERR_INVALID_INPUT, f"成果串题拦截：{lid!r} 归属 {row['question_id']!r} != {qid_s!r}")
            if str(row["goal_coverage"] or "") == "FULL_GOAL" and int(row["verified_spec_revision"] or 0) >= q_req_rev:
                full_goal_covered_qs.add(qid_s)
            all_selected_l3.append(str(lid))

    if mode_u == "FULL":
        missing = [q for q in required_qs if q not in full_goal_covered_qs]
        if missing:
            raise FailClosedError(ERR_INVALID_INPUT, f"FULL 交付包漏交当前生效口径 FULL_GOAL 核心成果：{missing}")

    repro_nodes_rows: list[sqlite3.Row] = []
    for nid in reproduction_candidate_nodes or []:
        node = conn.execute(
            "SELECT node_id, question_id, branch_id, branch_kind, human_modified, worktree_abs_path, retained_snapshot_abs_path, candidate_rel_path FROM lineage_nodes WHERE node_id = ?",
            (str(nid),),
        ).fetchone()
        if node is None:
            raise FailClosedError(ERR_NOT_FOUND, f"复现节点 {nid!r} 不存在")
        repro_nodes_rows.append(node)

    if mode_u == "FULL" and not repro_nodes_rows:
        raise FailClosedError(ERR_INVALID_INPUT, "FULL 交付包必须至少绑定 1 个有效复现节点 (reproduction_candidate_nodes)")

    p0_row = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
    shared_inputs_rels = json.loads(p0_row["shared_inputs_json"] or "[]") if p0_row else []

    ws_root = Path(os.path.realpath(workspace_root))
    paths = resolve_storage_paths(workspace_root)
    delivery_id = f"deliv_{uuid.uuid4().hex[:10]}"
    frozen_dir = paths["frozen_deliveries_dir"] / delivery_id
    staging_dir = ws_root / f".final_delivery_staging_{uuid.uuid4().hex[:8]}"
    delivery_dir = ws_root / "final_delivery"

    staging_dir.mkdir(parents=True, exist_ok=True)
    repro_dir = staging_dir / "reproduction_suite"
    repro_dir.mkdir(parents=True, exist_ok=True)

    try:
        (staging_dir / "01_formal_report.md").write_text(formal_paper_md.strip() + "\n", encoding="utf-8")

        repro_manifest: list[dict[str, Any]] = []
        for node in repro_nodes_rows:
            snap_raw = str(node["retained_snapshot_abs_path"] or "").strip()
            wt_raw = str(node["worktree_abs_path"] or "").strip()
            src_base = Path(snap_raw) if (snap_raw and Path(snap_raw).is_dir()) else (Path(wt_raw) if wt_raw else None)
            art_rel = str(node["candidate_rel_path"] or "").strip()
            node_bundle_dir = repro_dir / f"{node['question_id']}_{node['node_id']}"
            copied_rel = ""
            copied_tools: list[str] = []
            if src_base is not None and src_base.is_dir() and art_rel:
                src_f = src_base / art_rel
                if not src_f.is_file():
                    raise FailClosedError(ERR_NOT_FOUND, f"复现节点 {node['node_id']!r} 入口工件 {art_rel!r} 缺失")
                dst_f = node_bundle_dir / Path(art_rel)
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)
                copied_rel = dst_f.relative_to(staging_dir).as_posix()
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
                raise FailClosedError(ERR_NOT_FOUND, f"复现节点 {node['node_id']!r} 找不到快照或工作树目录")

            # 复用分支/盲审的已批准公开材料装配逻辑：自动发现默认 inputs/，绝不带入未批准的 rulings/ 草稿
            node_bundle_dir.mkdir(parents=True, exist_ok=True)
            node_qid = str(node["question_id"])
            sync_approved_public_inputs(
                workspace_root,
                str(node_bundle_dir),
                shared_inputs_rels,
                spec_revision=active_spec_by_q.get(node_qid, 0),
                question_id=node_qid,
            )

            repro_manifest.append(
                {
                    "node_id": str(node["node_id"]),
                    "question_id": str(node["question_id"]),
                    "branch_kind": str(node["branch_kind"] or "PURE"),
                    "human_assisted": bool(int(node["human_modified"] or 0) == 1 or str(node["branch_kind"]) == "HUMAN_SEEDED"),
                    "copied_artifact": copied_rel,
                    "copied_tools": copied_tools,
                }
            )
        (repro_dir / "manifest.json").write_text(json.dumps(repro_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        neg_rows = conn.execute(
            """
            SELECT entry_id, question_id, ledger_type, l3_entry_kind, l2_category, title, exact_verified_scope_md, exact_refuted_scope_md
            FROM internal_research_ledger
            WHERE ledger_type = 'L2_FAILURE_RECORD' OR l3_entry_kind IN ('NEG_COUNTEREXAMPLE', 'BARRIER_PROOF')
            ORDER BY question_id, entry_id
            """
        ).fetchall()
        (staging_dir / "03_barriers_and_refutations.json").write_text(
            json.dumps([dict(r) for r in neg_rows], ensure_ascii=False, indent=2), encoding="utf-8"
        )

        dag_rows = conn.execute(
            """
            SELECT node_id, question_id, branch_id, family_id, generation, branch_kind,
                   human_modified, node_status, evidence_grade, mechanism_summary
            FROM lineage_nodes
            ORDER BY question_id, branch_id, generation
            """
        ).fetchall()
        (staging_dir / "04_lineage_roadmap.json").write_text(
            json.dumps([dict(r) for r in dag_rows], ensure_ascii=False, indent=2), encoding="utf-8"
        )

        gaps_lines = [f"# 后续研究精确剩余断点（交付模式：{mode_u}）\n"]
        for qid, gap in (remaining_gaps_by_question or {}).items():
            gaps_lines.append(f"## {qid}\n{str(gap or '无剩余断点').strip()}\n")
        (staging_dir / "05_remaining_gaps_and_notes.md").write_text("\n".join(gaps_lines), encoding="utf-8")

        meta_manifest = {
            "delivery_id": delivery_id,
            "delivery_mode": mode_u,
            "subproblem_spec_revisions": active_spec_by_q,
            "selected_l3_ids_by_question": selected_l3_ids_by_question,
            "remaining_gaps_by_question": remaining_gaps_by_question,
            "reproduction_candidate_nodes": reproduction_candidate_nodes,
        }
        (staging_dir / "delivery_manifest.json").write_text(
            json.dumps(meta_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        delivery_sha256 = compute_delivery_dir_sha256(staging_dir)

        # 先复制到工作区外不可变冻结目录并加只读保护
        if frozen_dir.exists():
            _rmtree_force(frozen_dir)
        shutil.copytree(staging_dir, frozen_dir)
        _set_tree_readonly(frozen_dir, True)

        now = utc_now_iso()
        backup_old = ws_root / f".final_delivery_old_{uuid.uuid4().hex[:6]}"
        had_old = False
        swapped = False
        with _SINGLE_WRITER_LOCK:
            try:
                with rw_immediate_tx(conn):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RequestCancelledError("Stage 3 导出在原子切换前已取消")
                    cur_closure = conn.execute("SELECT status FROM project_closure_state WHERE id = 1").fetchone()
                    if cur_closure is not None and str(cur_closure["status"]) == "CLOSED_VERIFIED":
                        raise FailClosedError(ERR_LOCKED, "课题已进入 CLOSED_VERIFIED 终态，禁止覆盖已锁交付包")
                    # 写锁内再次复核结项门禁与子题最新生效口径（防导出期间并发改题）
                    recheck_gate = check_stage2_closure_gate_data(
                        conn, mode=mode_u, human_aborted=(mode_u == "PARTIAL_ON_HUMAN_STOP")
                    )
                    if not recheck_gate["closure_allowed"]:
                        raise FailClosedError(
                            ERR_LOCKED,
                            f"写锁内复核结项门禁已失效 ({recheck_gate['gate_code']})，中止导出切换！",
                        )
                    if mode_u == "FULL":
                        live_spec_by_q = {
                            str(r["question_id"]): int(r["active_spec_revision"] or 0)
                            for r in conn.execute("SELECT question_id, active_spec_revision FROM subproblem_runtime_state").fetchall()
                        }
                        for q_req in required_qs:
                            req_rev = live_spec_by_q.get(q_req, 0)
                            q_l3s = [str(x) for x in (sel_map.get(q_req) or [])]
                            if not q_l3s:
                                raise FailClosedError(ERR_CONFLICT, f"写锁内复核：子题 {q_req} 缺少入选 L3")
                            ph = ",".join("?" for _ in q_l3s)
                            ok_l3 = conn.execute(
                                f"""
                                SELECT 1 FROM internal_research_ledger
                                WHERE entry_id IN ({ph}) AND question_id = ?
                                  AND ledger_type = 'L3_VERIFIED' AND is_active = 1
                                  AND goal_coverage = 'FULL_GOAL' AND verified_spec_revision >= ?
                                LIMIT 1
                                """,
                                (*q_l3s, q_req, req_rev),
                            ).fetchone()
                            if ok_l3 is None:
                                raise FailClosedError(
                                    ERR_CONFLICT,
                                    f"导出期间子题 {q_req} 口径已升至 v{req_rev}，原选 L3 不再满足 FULL_GOAL 资格！",
                                )
                    had_old = delivery_dir.exists()
                    if had_old:
                        delivery_dir.rename(backup_old)
                    staging_dir.rename(delivery_dir)
                    swapped = True
                    conn.execute(
                        """
                        UPDATE project_closure_state
                        SET status = 'DELIVERY_EXPORTED',
                            delivery_mode = ?,
                            latest_delivery_id = ?,
                            latest_delivery_sha256 = ?,
                            frozen_delivery_dir_abs_path = ?,
                            verifier_final_audit_passed = 0,
                            verifier_revision_notes = '',
                            updated_at = ?
                        WHERE id = 1
                        """,
                        (mode_u, delivery_id, delivery_sha256, str(frozen_dir), now),
                    )
                    conn.execute(
                        "UPDATE parse0_contract SET stage = 'STAGE3_CONSOLIDATE', updated_at = ? WHERE contract_id = 'active'",
                        (now,),
                    )
            except Exception:
                if swapped and delivery_dir.exists():
                    _rmtree_force(delivery_dir)
                if had_old and backup_old.exists() and not delivery_dir.exists():
                    backup_old.rename(delivery_dir)
                _rmtree_force(frozen_dir)
                raise
            if had_old and backup_old.exists():
                _rmtree_force(backup_old)
    except Exception:
        _rmtree_force(staging_dir)
        raise

    return {
        "delivery_id": delivery_id,
        "delivery_sha256": delivery_sha256,
        "delivery_mode": mode_u,
        "delivery_dir": str(delivery_dir),
        "frozen_delivery_dir_abs_path": str(frozen_dir),
        "selected_l3_count": len(all_selected_l3),
        "closure_status": "DELIVERY_EXPORTED",
    }


def finalize_stage3_closure_on_verifier_accept(
    conn: sqlite3.Connection,
    *,
    target_delivery_id: str,
) -> dict[str, Any]:
    """裁决 3：盲审官核查外部不可变冻结目录通过后，写锁外算冻结目录 SHA-256，写锁内毫秒级比对一致一步原子结项。"""
    pre = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
    if pre is None or str(pre["status"]) != "DELIVERY_EXPORTED":
        raise FailClosedError(ERR_LOCKED, "当前项目不处于 DELIVERY_EXPORTED 待终核状态")
    latest_did = str(pre["latest_delivery_id"] or "")
    if not target_delivery_id or target_delivery_id != latest_did:
        raise FailClosedError(ERR_CONFLICT, f"终核版本不匹配：{target_delivery_id!r} != {latest_did!r}")

    frozen_path_raw = str(pre["frozen_delivery_dir_abs_path"] or "").strip()
    if not frozen_path_raw or not Path(frozen_path_raw).is_dir():
        raise FailClosedError(ERR_LOCKED, f"外部不可变冻结目录缺失: {frozen_path_raw!r}，拒绝放行结项")

    # 性能优化（裁决 3）：在进入单写者写锁前只读计算不可变冻结目录的实时 SHA-256 并读取交付清单
    frozen_dir_path = Path(frozen_path_raw)
    live_frozen_sha = compute_delivery_dir_sha256(frozen_dir_path)
    manifest_mode = str(pre["delivery_mode"] or "FULL").strip().upper()
    manifest_q_revs: dict[str, int] = {}
    manifest_fp = frozen_dir_path / "delivery_manifest.json"
    if manifest_fp.is_file():
        try:
            m_obj = json.loads(manifest_fp.read_text(encoding="utf-8"))
            if isinstance(m_obj, dict):
                if m_obj.get("delivery_mode"):
                    manifest_mode = str(m_obj["delivery_mode"]).strip().upper()
                if isinstance(m_obj.get("subproblem_spec_revisions"), dict):
                    manifest_q_revs = {str(k): int(v or 0) for k, v in m_obj["subproblem_spec_revisions"].items()}
        except Exception:
            pass
    now = utc_now_iso()

    invalidated_reason = ""
    with rw_immediate_tx(conn):
        closure = conn.execute("SELECT * FROM project_closure_state WHERE id = 1").fetchone()
        if closure is None or str(closure["status"]) != "DELIVERY_EXPORTED":
            raise FailClosedError(ERR_LOCKED, "当前项目不处于 DELIVERY_EXPORTED 状态")
        cur_did = str(closure["latest_delivery_id"] or "")
        cur_sha = str(closure["latest_delivery_sha256"] or "")
        cur_frozen = str(closure["frozen_delivery_dir_abs_path"] or "")
        if cur_did != target_delivery_id or cur_frozen != frozen_path_raw:
            raise FailClosedError(ERR_CONFLICT, f"终核落签版本冲突：{target_delivery_id!r} 已被新交付版本覆盖")
        if live_frozen_sha != cur_sha:
            raise FailClosedError(
                ERR_LOCKED,
                f"防审A放B完整性硬拦截：冻结目录实时 SHA-256 ({live_frozen_sha[:12]}) != 绑定哈希 ({cur_sha[:12]})！",
            )

        # 终签写锁内复核当前结项门禁与口径版本（防止导出后改题升版或撤回 L3 仍按旧冻结包直接结项）
        gate_now = check_stage2_closure_gate_data(conn, mode=manifest_mode)
        if not gate_now["closure_allowed"]:
            invalidated_reason = f"导出冻结包后结项资格已失效（{gate_now['gate_code']}），需在满足新条件后重新导出冻结包。"
        elif manifest_mode == "FULL":
            stale_qs: list[str] = []
            for qid in gate_now.get("required_questions") or []:
                cur_q_rev = get_subproblem_active_spec_revision(conn, str(qid))
                frozen_q_rev = manifest_q_revs.get(str(qid), -1)
                if frozen_q_rev >= 0 and cur_q_rev != frozen_q_rev:
                    stale_qs.append(f"{qid}(v{frozen_q_rev}->v{cur_q_rev})")
            if stale_qs:
                invalidated_reason = f"导出冻结包后子题口径已升版（{', '.join(stale_qs)}），旧冻结包已失效，请重新导出后再终签。"

        if invalidated_reason:
            # 口径升版或结项资格失效：原子退回 STAGE2_EVOLVE 并复位 closure 为 OPEN，避免卡死在 Stage 3 死锁
            conn.execute(
                """
                UPDATE project_closure_state
                SET status = 'OPEN',
                    verifier_final_audit_passed = 0,
                    verifier_revision_notes = ?,
                    updated_at = ?
                WHERE id = 1 AND status = 'DELIVERY_EXPORTED' AND latest_delivery_id = ?
                """,
                (invalidated_reason, now, cur_did),
            )
            conn.execute(
                "UPDATE parse0_contract SET stage = 'STAGE2_EVOLVE', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )
        else:
            cur = conn.execute(
                """
                UPDATE project_closure_state
                SET status = 'CLOSED_VERIFIED',
                    verifier_audited_delivery_id = ?,
                    verifier_audited_delivery_sha256 = ?,
                    verifier_final_audit_passed = 1,
                    supervisory_signed_at = ?,
                    updated_at = ?
                WHERE id = 1
                  AND status = 'DELIVERY_EXPORTED'
                  AND latest_delivery_id = ?
                  AND latest_delivery_sha256 = ?
                """,
                (cur_did, cur_sha, now, now, cur_did, cur_sha),
            )
            if cur.rowcount != 1:
                raise FailClosedError(ERR_CONFLICT, "终核落签并发状态冲突")
            conn.execute(
                "UPDATE parse0_contract SET stage = 'CLOSED_VERIFIED', updated_at = ? WHERE contract_id = 'active'",
                (now,),
            )
            conn.execute(
                "UPDATE subproblem_runtime_state SET desired_state = 'CLOSED', dispatch_state = 'CLOSED', updated_at = ?",
                (now,),
            )

    if invalidated_reason:
        raise FailClosedError(ERR_CONFLICT, invalidated_reason)

    return {
        "mode": "STAGE3_FINAL_AUDIT",
        "delivery_id": target_delivery_id,
        "delivery_sha256": live_frozen_sha,
        "frozen_delivery_dir_abs_path": frozen_path_raw,
        "verifier_final_audit_passed": True,
        "closure_status": "CLOSED_VERIFIED",
    }
