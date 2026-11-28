"""GreatWall Agent v0.3 数据库初始化与 v0.2 -> v0.3 幂等无损迁移引擎。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ..db_runtime import rw_immediate_tx
from .enums import ERR_STORAGE, FailClosedError
from .schema_base import BASE_SCHEMA_SQL, STAGE1_TRIGGER_SQL
from .schema_v031 import V031_SCHEMA_SQL
from .schema_v032 import MINI_PAPERS_VIEW_SQL, V032_SCHEMA_SQL
from .schema_v03 import SEALED_HANDOFF_TRIGGER_SQL, V03_SCHEMA_SQL


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _detect_legacy_v2_database(conn: sqlite3.Connection) -> None:
    """检测旧版 v2.2 数据库：直接 Fail-Closed 阻止破坏性覆盖。"""
    tables = {
        str(r["name"])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if "observations" in tables:
        obs_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(observations)").fetchall()}
        if "cache_key" not in obs_cols or "obs_status" not in obs_cols:
            raise FailClosedError(
                ERR_STORAGE,
                "检测到旧版 v2.2 数据库（observations 表结构不兼容），请更换工作区目录或移走旧库后再启动！",
            )
    if "lineage_nodes" in tables:
        node_cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(lineage_nodes)").fetchall()}
        if "node_status" not in node_cols:
            raise FailClosedError(
                ERR_STORAGE,
                "检测到旧版 v2.2 数据库（lineage_nodes 表结构不兼容），请更换工作区目录或移走旧库后再启动！",
            )


def _rebuild_table_without_fk(conn: sqlite3.Connection, rebuild_fn) -> None:
    """在事务外短暂关闭外键并开启 legacy_alter_table（防止 RENAME 篡改其他表的外键引用），单事务内重建表并做完整性校验。"""
    if conn.in_transaction:
        conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("PRAGMA legacy_alter_table = ON;")
    try:
        with rw_immediate_tx(conn):
            rebuild_fn(conn)
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF;")
        conn.execute("PRAGMA foreign_keys = ON;")
    fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    if fk_violations:
        raise FailClosedError(ERR_STORAGE, f"旧库迁移后外键完整性校验失败: {len(fk_violations)} 条异常")


def _migrate_closure_state_check_constraint(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'project_closure_state'"
    ).fetchone()
    ddl = str(row["sql"] or "") if row else ""
    if not ddl or "REVISION_REQUESTED" in ddl:
        return
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(project_closure_state)").fetchall()}
    target_cols = [
        ("id", "1"),
        ("status", "'OPEN'"),
        ("delivery_mode", "NULL"),
        ("latest_delivery_id", "NULL"),
        ("latest_delivery_sha256", "NULL"),
        ("frozen_delivery_dir_abs_path", "''"),
        ("verifier_audited_delivery_id", "NULL"),
        ("verifier_audited_delivery_sha256", "NULL"),
        ("verifier_final_audit_passed", "0"),
        ("verifier_revision_notes", "''"),
        ("human_stop_requested_at", "NULL"),
        ("supervisory_signed_at", "NULL"),
        ("updated_at", "''"),
    ]
    insert_cols = ", ".join(name for name, _ in target_cols)
    select_exprs = ", ".join(name if name in cols else default_expr for name, default_expr in target_cols)

    def _do(c: sqlite3.Connection) -> None:
        c.execute("ALTER TABLE project_closure_state RENAME TO _project_closure_state_old")
        c.execute(
            """
            CREATE TABLE project_closure_state (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','DELIVERY_EXPORTED','REVISION_REQUESTED','CLOSED_VERIFIED')),
                delivery_mode TEXT,
                latest_delivery_id TEXT,
                latest_delivery_sha256 TEXT,
                frozen_delivery_dir_abs_path TEXT NOT NULL DEFAULT '',
                verifier_audited_delivery_id TEXT,
                verifier_audited_delivery_sha256 TEXT,
                verifier_final_audit_passed INTEGER NOT NULL DEFAULT 0,
                verifier_revision_notes TEXT NOT NULL DEFAULT '',
                human_stop_requested_at TEXT,
                supervisory_signed_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(f"INSERT INTO project_closure_state({insert_cols}) SELECT {select_exprs} FROM _project_closure_state_old")
        c.execute("DROP TABLE _project_closure_state_old")

    _rebuild_table_without_fk(conn, _do)


def _migrate_survey_requests_check_constraint(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'survey_requests'"
    ).fetchone()
    ddl = str(row["sql"] or "") if row else ""
    if not ddl or "CLOSED_UNAVAILABLE" in ddl:
        return
    cols = {str(r["name"]) for r in conn.execute("PRAGMA table_info(survey_requests)").fetchall()}
    target_cols = [
        ("req_id", "''"),
        ("question_id", "''"),
        ("node_id", "''"),
        ("topic_query", "''"),
        ("reason", "''"),
        ("status", "'PENDING'"),
        ("fulfilled_ref_id", "NULL"),
        ("resolution_note", "''"),
        ("created_at", "''"),
        ("updated_at", "''"),
    ]
    insert_cols = ", ".join(name for name, _ in target_cols)
    select_exprs = ", ".join(name if name in cols else default_expr for name, default_expr in target_cols)

    def _do(c: sqlite3.Connection) -> None:
        c.execute("ALTER TABLE survey_requests RENAME TO _survey_requests_old")
        c.execute(
            """
            CREATE TABLE survey_requests (
                req_id TEXT PRIMARY KEY,
                question_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                topic_query TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','FULFILLED','CLOSED_UNAVAILABLE')),
                fulfilled_ref_id TEXT,
                resolution_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        c.execute(f"INSERT INTO survey_requests({insert_cols}) SELECT {select_exprs} FROM _survey_requests_old")
        c.execute("DROP TABLE _survey_requests_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_survey_status ON survey_requests(status, question_id)")

    _rebuild_table_without_fk(conn, _do)


_INCREMENTAL_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # v0.2 既有安全增量列
    ("instruments", "frozen_snapshot_path", "TEXT"),
    ("async_eval_jobs", "frozen_instrument_path", "TEXT"),
    ("lineage_nodes", "explorer_will_md", "TEXT NOT NULL DEFAULT ''"),
    ("lineage_nodes", "pending_handoff_mode", "TEXT"),
    ("lineage_nodes", "pending_handoff_reason", "TEXT NOT NULL DEFAULT ''"),
    ("lineage_nodes", "effective_context_window", "INTEGER NOT NULL DEFAULT 360000"),
    ("lineage_nodes", "spec_revision", "INTEGER NOT NULL DEFAULT 0"),
    ("review_queue", "spec_revision", "INTEGER NOT NULL DEFAULT 0"),
    ("parse0_contract", "shared_inputs_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("parse0_contract", "stage1_works_checked", "INTEGER NOT NULL DEFAULT 0"),
    ("parse0_contract", "latest_spec_revision", "INTEGER NOT NULL DEFAULT 0"),
    ("parse0_contract", "latest_ruling_summary_md", "TEXT NOT NULL DEFAULT ''"),
    ("parse0_contract", "ruling_fingerprint_sha256", "TEXT NOT NULL DEFAULT ''"),
    ("survey_requests", "resolution_note", "TEXT NOT NULL DEFAULT ''"),
    ("project_closure_state", "verifier_revision_notes", "TEXT NOT NULL DEFAULT ''"),
    # v0.3 新增增量列（100% 对齐 agent_kb_v0_3_04 §二点一）
    ("parse0_contract", "autonomy_mode", "TEXT NOT NULL DEFAULT 'WAVE_CONFIRM'"),
    ("lineage_nodes", "branch_kind", "TEXT NOT NULL DEFAULT 'PURE'"),
    ("lineage_nodes", "protection_generations_left", "INTEGER NOT NULL DEFAULT 1"),
    ("lineage_nodes", "branch_budget_nodes_left", "INTEGER"),
    ("lineage_nodes", "companion_session_id", "TEXT NOT NULL DEFAULT ''"),
    ("lineage_nodes", "briefing_sealed_at", "TEXT"),
    ("lineage_nodes", "secondary_donor_node_id", "TEXT"),
    ("lineage_nodes", "control_state", "TEXT NOT NULL DEFAULT 'AUTO_RUNNING'"),
    ("lineage_nodes", "control_generation", "INTEGER NOT NULL DEFAULT 1"),
    ("lineage_nodes", "personal_turn_active", "INTEGER NOT NULL DEFAULT 0"),
    ("lineage_nodes", "human_modified", "INTEGER NOT NULL DEFAULT 0"),
    ("lineage_nodes", "artifact_dirty_since_last_obs", "INTEGER NOT NULL DEFAULT 0"),
    ("lineage_nodes", "last_reconciled_candidate_sha256", "TEXT NOT NULL DEFAULT ''"),
    ("lineage_nodes", "last_reconciled_tools_sha256", "TEXT NOT NULL DEFAULT ''"),
    ("lineage_nodes", "transient_retry_count", "INTEGER NOT NULL DEFAULT 0"),
    ("internal_research_ledger", "publish_tier", "TEXT NOT NULL DEFAULT 'BASELINE_UPDATE'"),
    ("internal_research_ledger", "verified_spec_revision", "INTEGER NOT NULL DEFAULT 0"),
    ("project_closure_state", "frozen_delivery_dir_abs_path", "TEXT NOT NULL DEFAULT ''"),
    ("review_queue", "artifact_snapshot_abs_path", "TEXT"),
)


def _backfill_v03_data(conn: sqlite3.Connection) -> None:
    """回填既有 L3 的真实核验口径与 subproblem_runtime_state 初始行。"""
    now = _utc_now_iso()
    with rw_immediate_tx(conn):
        # 1. 回填历史 L3 条目的真实 verified_spec_revision（避免 v3 成果误标 v0）
        conn.execute(
            """
            UPDATE internal_research_ledger
            SET verified_spec_revision = COALESCE(
                (SELECT r.spec_revision FROM review_queue r WHERE r.review_id = internal_research_ledger.verified_review_id),
                0
            )
            WHERE verified_spec_revision = 0 AND verified_review_id IS NOT NULL
            """
        )

        # 2. 为既有未填 companion_session_id 的节点补齐确定性会话 ID
        conn.execute(
            """
            UPDATE lineage_nodes
            SET companion_session_id = 'gw-comp-' || node_id
            WHERE companion_session_id = ''
            """
        )

        # 2.5 若旧库迁移时恰好停留在 DELIVERY_EXPORTED 且缺 v0.3 外部冻结目录，自动温和切至 REVISION_REQUESTED 以便重导终签
        conn.execute(
            """
            UPDATE project_closure_state
            SET status = 'REVISION_REQUESTED',
                verifier_final_audit_passed = 0,
                verifier_revision_notes = CASE
                    WHEN COALESCE(verifier_revision_notes, '') = '' THEN '由 v0.2 迁移：缺少 v0.3 外部不可变冻结目录，请由 library_chronicler 重新导出冻结包后再终签。'
                    ELSE verifier_revision_notes
                END,
                updated_at = ?
            WHERE id = 1 AND status = 'DELIVERY_EXPORTED' AND COALESCE(frozen_delivery_dir_abs_path, '') = ''
            """,
            (now,),
        )

        # 3. 从 active parse0_contract 自动回填 subproblem_runtime_state
        p0 = conn.execute(
            """
            SELECT subquestions_json, latest_spec_revision, min_commitment_window_sec,
                   total_budget_json, stage, human_signed_at, created_at
            FROM parse0_contract
            WHERE contract_id = 'active'
            """
        ).fetchone()
        if p0 is not None:
            try:
                subqs = json.loads(p0["subquestions_json"] or "[]")
            except Exception:
                subqs = []
            try:
                total_budget = json.loads(p0["total_budget_json"] or "{}")
                if not isinstance(total_budget, dict):
                    total_budget = {}
            except Exception:
                total_budget = {}

            latest_rev = int(p0["latest_spec_revision"] or 0)
            min_commit = max(0, int(p0["min_commitment_window_sec"] or 0))
            started_ts = str(p0["human_signed_at"] or p0["created_at"] or now)
            is_closed = str(p0["stage"] or "") == "CLOSED_VERIFIED"
            q_token_budget = max(0, int(total_budget.get("question_token_budget", 0) or 0))
            max_waves = max(0, int(total_budget.get("max_waves", 0) or 0))

            for raw_q in subqs:
                qid = str(raw_q).strip()
                if not qid:
                    continue
                existing = conn.execute(
                    "SELECT question_id FROM subproblem_runtime_state WHERE question_id = ?",
                    (qid,),
                ).fetchone()
                if existing is not None:
                    continue

                # 检查是否已有匹配当前最新口径的活跃 FULL_GOAL L3
                solved_row = conn.execute(
                    """
                    SELECT entry_id, verified_spec_revision
                    FROM internal_research_ledger
                    WHERE question_id = ?
                      AND ledger_type = 'L3_VERIFIED'
                      AND is_active = 1
                      AND goal_coverage = 'FULL_GOAL'
                      AND verified_spec_revision >= ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (qid, latest_rev),
                ).fetchone()

                if is_closed:
                    desired = "CLOSED"
                    dispatch = "CLOSED"
                elif solved_row is not None:
                    desired = "ACTIVE"
                    dispatch = "STOPPED_SOLVED"
                else:
                    desired = "ACTIVE"
                    dispatch = "DISPATCHING"

                conn.execute(
                    """
                    INSERT INTO subproblem_runtime_state(
                        question_id, contract_id, desired_state, dispatch_state,
                        active_spec_revision, solved_entry_id, solved_at_spec_revision,
                        started_at, min_commitment_sec, question_token_budget, max_waves, updated_at
                    ) VALUES (?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        qid,
                        desired,
                        dispatch,
                        latest_rev,
                        str(solved_row["entry_id"]) if solved_row is not None else None,
                        int(solved_row["verified_spec_revision"]) if solved_row is not None else None,
                        started_ts,
                        min_commit,
                        q_token_budget,
                        max_waves,
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


def _rebuild_from_schema(conn: sqlite3.Connection, table: str, schema: str) -> None:
    def rebuild(c: sqlite3.Connection) -> None:
        objects = c.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index','trigger') AND sql IS NOT NULL",
            (table,),
        ).fetchall()
        previous = f"_{table}_before_upgrade"
        c.execute(f"ALTER TABLE {table} RENAME TO {previous}")
        ddl = schema.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(";", 1)[0]
        c.execute(f"CREATE TABLE {table} ({ddl}")
        new_cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        common = ", ".join(f'"{r["name"]}"' for r in c.execute(f"PRAGMA table_info({previous})") if r["name"] in new_cols)
        c.execute(f"INSERT INTO {table} ({common}) SELECT {common} FROM {previous}")
        c.execute(f"DROP TABLE {previous}")
        for obj in objects:
            c.execute(obj["sql"])

    _rebuild_table_without_fk(conn, rebuild)


def _migrate_operator_plane_constraints(conn: sqlite3.Connection) -> None:
    for table, marker, schema in (
        ("method_families", "'ARCHIVED'", BASE_SCHEMA_SQL),
        ("node_interventions", "'ADVISOR_NOTE_SENT'", V03_SCHEMA_SQL),
        ("control_proposals", "'ADVANCE_EPOCH'", V03_SCHEMA_SQL),
    ):
        previous_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()["sql"]
        if marker not in previous_sql:
            _rebuild_from_schema(conn, table, schema)


def _migrate_v032_constraints_and_backfill(conn: sqlite3.Connection) -> None:
    for table, marker, schema in (
        ("lineage_nodes", "effective_context_window INTEGER NOT NULL DEFAULT 360000", BASE_SCHEMA_SQL),
        ("review_queue", "'COMPOSITE_FULL_GOAL'", BASE_SCHEMA_SQL),
        ("runtime_effects", "'RUN_INTERNAL_SURVEY'", V03_SCHEMA_SQL),
        ("works_engineering_queue", "'WONTFIX'", BASE_SCHEMA_SQL),
        ("subproblem_living_surveys", "length(marginal_notes_md) <= 1500", V03_SCHEMA_SQL),
        ("wave_conferences", "length(minutes_md) <= 6000", V03_SCHEMA_SQL),
    ):
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()["sql"]
        if marker in ddl and (table != "lineage_nodes" or "'RETIRED'" in ddl):
            continue
        _rebuild_from_schema(conn, table, schema)

    for table, columns in {
        "observations": ("frozen_code_snapshot_path TEXT NOT NULL DEFAULT ''",),
        "lineage_nodes": (
            "holiday_prompt_id INTEGER", "holiday_bet_json TEXT NOT NULL DEFAULT '{}'",
            "holiday_completed INTEGER NOT NULL DEFAULT 0", "pending_review_feedback_json TEXT NOT NULL DEFAULT '[]'",
            "peer_takeaways_json TEXT NOT NULL DEFAULT '[]'",
        ),
        "internal_research_ledger": (
            "author_node_id TEXT", "author_branch_id TEXT", "author_family_id TEXT",
            "tags_json TEXT NOT NULL DEFAULT '[]'", "cited_entries_json TEXT NOT NULL DEFAULT '[]'",
            "rigor_score INTEGER", "novelty_score INTEGER", "significance_score INTEGER",
            "overall_score REAL", "reviewer_comment_md TEXT NOT NULL DEFAULT ''",
        ),
        "open_lemma_gaps": (
            "gap_tier TEXT NOT NULL DEFAULT 'LOAD_BEARING' CHECK(gap_tier IN ('LOAD_BEARING', 'IMPROVEMENT'))",
            "source_entry_id TEXT",
        ),
    }.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for definition in columns:
            if definition.split()[0] not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    conn.executescript(STAGE1_TRIGGER_SQL)
    conn.executescript(MINI_PAPERS_VIEW_SQL)
    with rw_immediate_tx(conn):
        conn.execute(
            """
            UPDATE internal_research_ledger AS l
            SET (author_node_id, author_branch_id, author_family_id) = (
                SELECT r.source_node_id, n.branch_id, n.family_id
                FROM review_queue r LEFT JOIN lineage_nodes n ON n.node_id = r.source_node_id
                WHERE r.review_id = l.verified_review_id
            )
            WHERE author_node_id IS NULL AND verified_review_id IS NOT NULL
            """
        )
        conn.execute(
            """
            UPDATE works_engineering_queue
            SET resolution_note = json_extract(payload_json, '$.resolution_note'),
                status = CASE json_extract(payload_json, '$.resolution')
                    WHEN 'WONTFIX' THEN 'WONTFIX' WHEN 'DUPLICATE' THEN 'DUPLICATE' ELSE 'RESOLVED' END
            WHERE status = 'RESOLVED' AND resolution_note = '' AND json_valid(payload_json)
              AND json_type(payload_json, '$.resolution_note') = 'text'
              AND json_extract(payload_json, '$.resolution_note') != ''
            """
        )
        conn.execute(
            """
            UPDATE review_queue SET non_blocking = 0
            WHERE source_type IN ('LEVEL1_MANUSCRIPT','LEVEL4A_BARRIER') AND non_blocking != 0
            """
        )


def _migrate_relaxed_char_limit_constraints(conn: sqlite3.Connection) -> None:
    """幂等放宽旧库 lineage_briefings (2200/3600->5000) 与 subproblem_living_surveys (1500->4000) 字数 CHECK 约束。"""
    for tbl, old_tok, new_tok in (
        ("lineage_briefings", "total_chars <= 2200", "total_chars <= 5000"),
        ("lineage_briefings", "total_chars <= 3600", "total_chars <= 5000"),
        ("subproblem_living_surveys", "total_chars <= 1500", "total_chars <= 4000"),
    ):
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (tbl,),
        ).fetchone()
        ddl = str(row["sql"] or "") if row else ""
        if not ddl or old_tok not in ddl:
            continue
        new_ddl = ddl.replace(old_tok, new_tok)
        cols = [str(r["name"]) for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()]
        col_csv = ", ".join(cols)
        idx_sqls = [
            str(r["sql"])
            for r in conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
                (tbl,),
            ).fetchall()
        ]

        def _do(c: sqlite3.Connection, _tbl=tbl, _new_ddl=new_ddl, _col_csv=col_csv, _idx_sqls=idx_sqls) -> None:
            tmp_tbl = f"_{_tbl}_old_charlim"
            c.execute(f"DROP TABLE IF EXISTS {tmp_tbl}")
            c.execute(f"ALTER TABLE {_tbl} RENAME TO {tmp_tbl}")
            c.execute(_new_ddl)
            c.execute(f"INSERT INTO {_tbl}({_col_csv}) SELECT {_col_csv} FROM {tmp_tbl}")
            c.execute(f"DROP TABLE {tmp_tbl}")
            for sql in _idx_sqls:
                c.execute(sql)

        _rebuild_table_without_fk(conn, _do)


def init_database_schema(conn: sqlite3.Connection) -> None:
    """幂等初始化 v0.3 全量 Schema 并完成 v0.2 旧库无损迁移。"""
    _detect_legacy_v2_database(conn)
    conn.executescript(BASE_SCHEMA_SQL)
    conn.executescript(V03_SCHEMA_SQL)
    _migrate_closure_state_check_constraint(conn)
    _migrate_survey_requests_check_constraint(conn)
    _migrate_relaxed_char_limit_constraints(conn)

    for tbl, col, col_def in _INCREMENTAL_COLUMNS:
        existing = {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
        if col not in existing:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")

    for tbl, col, definition in (
        ("subproblem_runtime_state", "priority_weight", "INTEGER NOT NULL DEFAULT 100"),
        ("subproblem_runtime_state", "max_active_branches", "INTEGER NOT NULL DEFAULT 3"),
        ("subproblem_runtime_state", "dispatch_policy", "TEXT NOT NULL DEFAULT 'NORMAL'"),
        ("lineage_nodes", "session_epoch_id", "INTEGER NOT NULL DEFAULT 1"),
        ("lineage_nodes", "pending_advisor_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("lineage_nodes", "operator_arrangement_id", "TEXT"),
    ):
        if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({tbl})")}:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {definition}")
    _migrate_operator_plane_constraints(conn)
    conn.executescript(V031_SCHEMA_SQL)
    slot_columns = {row["name"] for row in conn.execute("PRAGMA table_info(operator_runtime_slots)")}
    if "slot_tier" not in slot_columns:
        conn.execute("ALTER TABLE operator_runtime_slots ADD COLUMN slot_tier TEXT NOT NULL DEFAULT 'normal'")
    if "worker_exited" not in slot_columns:
        conn.execute("ALTER TABLE operator_runtime_slots ADD COLUMN worker_exited INTEGER NOT NULL DEFAULT 0")
    conn.executescript(SEALED_HANDOFF_TRIGGER_SQL)
    # 若旧库已有内/外藏数据而新补建了 FTS5 表，先 rebuild 索引再执行 UPDATE 回填，避免 FTS5 AFTER UPDATE 触发器索引失步
    conn.execute("INSERT INTO internal_research_fts(internal_research_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO external_literature_fts(external_literature_fts) VALUES('rebuild')")
    _backfill_v03_data(conn)
    conn.commit()
    conn.executescript(V032_SCHEMA_SQL)
    _migrate_v032_constraints_and_backfill(conn)
