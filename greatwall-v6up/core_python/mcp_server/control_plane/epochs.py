"""Human-confirmed epoch rotation with a verified SQLite archive."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from ..db_schema import ERR_INVALID_INPUT, ERR_LOCKED, ERR_NOT_FOUND, ERR_STORAGE, FailClosedError
from ..db_schema import open_ro_connection, rw_immediate_tx, utc_now_iso
from .lifecycle_ops import init_parse0_contract


_CLEAR_TABLES = (
    "handback_records", "chief_pinned_notes", "operation_receipts", "run_arrangements",
    "runtime_effects", "node_interventions", "open_lemma_gaps", "pending_revalidation_queue",
    "subproblem_living_surveys", "wave_conferences", "async_eval_jobs", "observations",
    "probe_diagnostic_logs", "epistemic_edges", "internal_research_ledger", "review_queue",
    "lineage_dead_ends", "lineage_briefings", "lineage_nodes", "method_families",
    "works_engineering_queue", "survey_requests", "saved_graph_queries", "compliance_alerts",
    "subproblem_runtime_state", "project_closure_state", "parse0_contract",
)


def _backup(conn: sqlite3.Connection, old_epoch: int) -> Path:
    db_file = conn.execute("PRAGMA database_list").fetchone()["file"]
    if not db_file:
        raise FailClosedError(ERR_STORAGE, "无法归档没有文件路径的科研数据库")
    source_path = Path(db_file)
    archive_dir = source_path.parent / "epoch_archives"
    archive_dir.mkdir(exist_ok=True)
    target = archive_dir / f"epoch-{old_epoch}-{uuid4().hex[:8]}.sqlite3"
    temporary = target.with_suffix(".tmp")
    try:
        with closing(open_ro_connection(source_path)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise FailClosedError(ERR_STORAGE, "旧纪元数据库备份完整性校验失败")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def advance_epoch(conn: sqlite3.Connection, *, proposal_id: str, payload: dict) -> dict:
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        old = conn.execute("SELECT * FROM parse0_contract WHERE contract_id='active'").fetchone()
        if old is None:
            raise FailClosedError(ERR_NOT_FOUND, "没有可归档的旧纪元")
        prior = int(old["epoch_id"])
        if "expected_epoch_id" in payload and payload["expected_epoch_id"] != prior:
            raise FailClosedError(ERR_LOCKED, "该确认单指向旧纪元，请重新生成")
        if conn.execute("SELECT 1 FROM operator_runtime_slots LIMIT 1").fetchone():
            raise FailClosedError(ERR_LOCKED, "有分支尚未退出，不可推进纪元")
        if conn.execute("SELECT 1 FROM async_eval_jobs WHERE status='RUNNING' LIMIT 1").fetchone():
            raise FailClosedError(ERR_LOCKED, "有在途重型实验，请等其完成或退出后重试")
        contract = payload.get("new_contract") or {}
        if not isinstance(contract, dict):
            raise FailClosedError(ERR_INVALID_INPUT, "new_contract 必须是课题设置对象")
        qids = contract.get("subquestions", json.loads(old["subquestions_json"]))
        inheritable_qids = [q.get("question_id") or q.get("id") if isinstance(q, dict) else q for q in qids]
        inheritance = {
            "external_literature": payload.get("inherit_external_literature") is True,
            "instruments": payload.get("inherit_instruments") is True,
        }
        backup = _backup(conn, prior)
        conn.execute("PRAGMA defer_foreign_keys=ON")
        for table in _CLEAR_TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM control_proposals WHERE proposal_id<>?", (proposal_id,))
        if not inheritance["external_literature"]:
            conn.execute("DELETE FROM external_literature_cards")
        if inheritance["instruments"]:
            markers = ",".join("?" for _ in inheritable_qids)
            conn.execute(
            f"""DELETE FROM instruments WHERE is_active=0 OR health_status<>'HEALTHY'
                     OR COALESCE(calibration_suite_rel_path,'')=''
                    OR question_id NOT IN ('ALL'{',' + markers if markers else ''})""",
                inheritable_qids,
            )
        else:
            conn.execute("DELETE FROM instruments")
        init_parse0_contract(
            conn, epoch_id=prior + 1, human_signed_at=now, stage="STAGE1_PARSE0",
            goal_and_completion_md=contract.get("goal_and_completion_md", old["goal_and_completion_md"]),
            subquestions=qids,
            question_order=contract.get("question_order", json.loads(old["question_order_json"]) if "subquestions" not in contract else []),
            initial_instruments=contract.get("initial_instruments", json.loads(old["initial_instruments_json"]) if "subquestions" not in contract else []),
            seed_families=contract.get("seed_families"),
            total_budget=contract.get("total_budget", json.loads(old["total_budget_json"])),
            min_commitment_window_sec=contract.get("min_commitment_window_sec", old["min_commitment_window_sec"]),
            delivery_spec_md=contract.get("delivery_spec_md", old["delivery_spec_md"]),
            shared_inputs_rel_paths=contract.get("shared_inputs_rel_paths", []),
            autonomy_mode=contract.get("autonomy_mode", "WAVE_CONFIRM"),
        )
        conn.execute(
            """INSERT INTO epoch_archives(epoch_id,archive_abs_path,last_spec_revision,proposal_id,created_at,
               inherited_external_literature,inherited_instruments) VALUES(?,?,?,?,?,?,?)""",
            (prior, str(backup), old["latest_spec_revision"], proposal_id, now, int(inheritance["external_literature"]), int(inheritance["instruments"])),
        )
    return {"previous_epoch_id": prior, "epoch_id": prior + 1, "archive_path": str(backup),
            "stage": "STAGE1_PARSE0", "inheritance": inheritance}

