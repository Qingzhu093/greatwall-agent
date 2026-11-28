"""院内专题综述与微型论文目录的权威 DDL。"""

V032_SCHEMA_SQL = """
-- ============================================================================
-- 33. 院内零外网专题文献综述请求与报告表 (internal_survey_requests)
-- 与外网 survey_requests 物理分表，严防 external_surveyor 误触院内机密
-- ============================================================================
CREATE TABLE IF NOT EXISTS internal_survey_requests (
    survey_req_id TEXT PRIMARY KEY,
    epoch_id INTEGER NOT NULL DEFAULT 1,
    question_id TEXT NOT NULL REFERENCES subproblem_runtime_state(question_id),
    requester_role TEXT NOT NULL CHECK(requester_role IN ('explorer', 'lineage_companion', 'gw_chief')),
    requester_node_id TEXT REFERENCES lineage_nodes(node_id),
    requester_session_id TEXT NOT NULL DEFAULT '',
    query_md TEXT NOT NULL CHECK(length(query_md) BETWEEN 10 AND 1500),
    focus_scope TEXT NOT NULL DEFAULT 'QUESTION_ONLY'
        CHECK(focus_scope IN ('QUESTION_ONLY', 'CROSS_QUESTION_ALL')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK(status IN ('PENDING', 'RUNNING', 'FULFILLED', 'FAILED')),
    report_md TEXT NOT NULL DEFAULT '' CHECK(length(report_md) <= 4000),
    cited_entry_ids_json TEXT NOT NULL DEFAULT '[]',
    cited_obs_ids_json TEXT NOT NULL DEFAULT '[]',
    chronicler_session_id TEXT NOT NULL DEFAULT '',
    error_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    fulfilled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_int_survey_q_status
    ON internal_survey_requests(question_id, status, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_int_survey_node
    ON internal_survey_requests(requester_node_id, created_at DESC);
"""

MINI_PAPERS_VIEW_SQL = """
DROP VIEW IF EXISTS v_library_mini_papers_catalog;
CREATE VIEW v_library_mini_papers_catalog AS
SELECT
    l.entry_id,
    l.question_id,
    l.ledger_type,
    l.l3_entry_kind,
    l.goal_coverage,
    l.publish_tier,
    l.verified_spec_revision,
    l.author_node_id,
    l.author_branch_id,
    l.author_family_id,
    l.title,
    l.abstract_md,
    COALESCE(l.exact_verified_scope_md, l.exact_refuted_scope_md, '') AS scope_md,
    l.tags_json,
    l.cited_entries_json,
    l.bound_obs_ids_json,
    l.rigor_score,
    l.novelty_score,
    l.significance_score,
    l.overall_score,
    l.reviewer_comment_md,
    CASE WHEN l.publish_tier = 'MARGINAL_NOTE' THEN 1 ELSE 0 END AS is_marginal,
    l.created_at
FROM internal_research_ledger l
WHERE l.is_active = 1
ORDER BY
    is_marginal ASC,
    COALESCE(l.significance_score, 5) DESC,
    COALESCE(l.overall_score, 5.0) DESC,
    l.created_at DESC;
"""
