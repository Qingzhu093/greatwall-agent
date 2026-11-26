"""GreatWall v0.3 explorer 与 lineage_companion 共享三层渐进式馆藏 Pull、谱系图查阅与越界退回工具。"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .control_plane.effects_outbox import enqueue_runtime_effect
from .db_schema import (
    ERR_AUTH,
    ERR_INVALID_INPUT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    FailClosedError,
    rw_immediate_tx,
    sanitize_fts5_query,
    utc_now_iso,
)
from .mcp_core_helpers import (
    _SQL_WRITE_FORBIDDEN_RE,
    build_tool_receipt,
    enforce_role_tool_permission,
    next_prefixed_id,
    record_fact_edge,
)

_FORBIDDEN_TENANT_TABLES = (
    "review_queue",
    "compliance_alerts",
    "parse0_contract",
    "project_closure_state",
    "works_engineering_queue",
    "control_proposals",
    "runtime_effects",
)


def _is_internal_pull_unlocked(caller_role: str, node: sqlite3.Row) -> bool:
    """lineage_companion 0% 起直接免锁读取全馆与总览；explorer 严守 37% 净室独思门禁。"""
    if str(caller_role or "").strip() == "lineage_companion":
        return True
    return int(node["first_reflection_unlocked"] or 0) == 1


def tool_get_living_survey(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
) -> dict[str, Any]:
    """一级导览总览 Pull：拉取指定子题最新《子题全局总览（<=1500字）》与高优 OPEN 悬赏缺口。"""
    enforce_role_tool_permission(conn, caller_role, "get_living_survey", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if not _is_internal_pull_unlocked(caller_role, node):
        raise FailClosedError(
            ERR_LOCKED,
            "0-37% 净室独思期物理锁定《子题全局总览》（防过早锚定）；完成 37% 伴随元反思后立即解锁！",
        )

    qid = str(question_id or node["question_id"]).strip()
    survey_row = conn.execute(
        """
        SELECT survey_id, question_id, revision, trigger_reason,
               sec1_baseline_and_instruments_md, sec2_l3_lemma_tree_md,
               sec3_avoidance_radar_md, sec4_explicit_gaps_md, total_chars, created_at
        FROM subproblem_living_surveys
        WHERE question_id = ?
        ORDER BY revision DESC LIMIT 1
        """,
        (qid,),
    ).fetchone()
    open_gaps = [
        dict(r)
        for r in conn.execute(
            """
            SELECT gap_id, blocked_node_id, formal_statement_md, verification_spec_md, created_at
            FROM open_lemma_gaps
            WHERE question_id = ? AND status = 'OPEN'
            ORDER BY created_at ASC LIMIT 12
            """,
            (qid,),
        ).fetchall()
    ]
    return build_tool_receipt(
        conn=conn,
        tool_name="get_living_survey",
        question_id=qid,
        node_id=node_id,
        next_step_guidance=(
            f"已拉取 {qid} 最新《子题全局总览》r{survey_row['revision']}（含 {len(open_gaps)} 条 OPEN 悬赏缺口）；如需细查特定编号请用 query_library_catalog / get_library_entry。"
            if survey_row
            else f"子题 {qid} 尚未生成首版《子题全局总览》（现有 {len(open_gaps)} 条 OPEN 悬赏缺口），可直接用 query_library_catalog 检索目录卡。"
        ),
        data={
            "question_id": qid,
            "survey": dict(survey_row) if survey_row else None,
            "open_lemma_gaps": open_gaps,
        },
    )


def tool_query_library_catalog(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    scope: str = "ALL",
    keyword: str = "",
) -> dict[str, Any]:
    """二级目录卡按需检索（支持 EXTERNAL_R / INTERNAL_L3 / INTERNAL_L2 / AVOIDANCE_RADAR / ALL）。"""
    enforce_role_tool_permission(conn, caller_role, "query_library_catalog", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = _is_internal_pull_unlocked(caller_role, node)

    scope_u = str(scope or "ALL").strip().upper()
    if scope_u not in ("EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "AVOIDANCE_RADAR", "ALL"):
        raise FailClosedError(
            ERR_INVALID_INPUT,
            f"非法 scope={scope!r}，仅允许 ['ALL', 'AVOIDANCE_RADAR', 'EXTERNAL_R', 'INTERNAL_L2', 'INTERNAL_L3']",
        )

    fts_q = sanitize_fts5_query(keyword)
    cards: list[dict[str, Any]] = []
    warnings: list[str] = []

    if scope_u == "AVOIDANCE_RADAR":
        if not unlocked:
            raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期物理锁定内部排雷视图，完成 37% 伴随元反思后开放")
        kw_s = str(keyword or "").strip()
        rows = conn.execute(
            """
            SELECT entry_id, question_id, radar_kind, title, scope_md, created_at
            FROM v_library_avoidance_radar
            WHERE (? = 'ALL' OR question_id = ?)
              AND (? = '' OR title LIKE ? OR scope_md LIKE ?)
            ORDER BY created_at DESC LIMIT 30
            """,
            (question_id, question_id, kw_s, f"%{kw_s}%", f"%{kw_s}%"),
        ).fetchall()
        for r in rows:
            cards.append(
                {
                    "entry_id": str(r["entry_id"]),
                    "wing": "AVOIDANCE_RADAR",
                    "radar_kind": str(r["radar_kind"]),
                    "question_id": str(r["question_id"]),
                    "title": str(r["title"]),
                    "abstract_preview": str(r["scope_md"] or "")[:350],
                }
            )
        return build_tool_receipt(
            conn=conn,
            tool_name="query_library_catalog",
            question_id=question_id,
            node_id=node_id,
            next_step_guidance=f"已检索排雷视图 {len(cards)} 条（合并已证伪 L2 与负向 L3 反例/阻碍证明）。",
            data={"unlocked": True, "cards": cards},
        )

    # 左翼外藏 [R###] 从 0% 起全程开放
    if scope_u in ("EXTERNAL_R", "ALL"):
        if fts_q:
            rows = conn.execute(
                """
                SELECT c.ref_id, c.question_id, c.title, c.abstract_md, c.read_depth, c.support_scope, c.is_unverified_external
                FROM external_literature_cards c
                JOIN external_literature_fts f ON f.rowid = c.rowid
                WHERE external_literature_fts MATCH ?
                  AND (? = 'ALL' OR c.question_id = ? OR c.question_id = 'ALL')
                ORDER BY c.ref_id
                """,
                (fts_q, question_id, question_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ref_id, question_id, title, abstract_md, read_depth, support_scope, is_unverified_external
                FROM external_literature_cards
                WHERE ? = 'ALL' OR question_id = ? OR question_id = 'ALL'
                ORDER BY ref_id
                """,
                (question_id, question_id),
            ).fetchall()
        for r in rows:
            cards.append(
                {
                    "entry_id": str(r["ref_id"]),
                    "wing": "EXTERNAL_R",
                    "question_id": str(r["question_id"]),
                    "title": str(r["title"]),
                    "abstract_preview": str(r["abstract_md"])[:350],
                    "read_depth": str(r["read_depth"]),
                    "support_scope": str(r["support_scope"]),
                    "is_unverified_external": bool(r["is_unverified_external"]),
                }
            )

    # 右翼内藏 L3 / L2
    if scope_u in ("INTERNAL_L3", "INTERNAL_L2", "ALL"):
        if not unlocked:
            if scope_u in ("INTERNAL_L3", "INTERNAL_L2"):
                raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期物理锁定内藏 L3/L2，完成 37% 伴随元反思后立即可读")
            warnings.append("当前处于 0-37% 独思净室期，本次仅返回左翼外藏 [R###]；完成 37% 元反思后将解锁 L3/L2。")
        else:
            ltypes = ("L3_VERIFIED",) if scope_u == "INTERNAL_L3" else (("L2_FAILURE_RECORD",) if scope_u == "INTERNAL_L2" else ("L3_VERIFIED", "L2_FAILURE_RECORD"))
            ph = ",".join("?" for _ in ltypes)
            if fts_q:
                rows = conn.execute(
                    f"""
                    SELECT l.entry_id, l.question_id, l.ledger_type, l.l3_entry_kind, l.goal_coverage,
                           l.publish_tier, l.verified_spec_revision, l.l2_category, l.title, l.abstract_md
                    FROM internal_research_ledger l
                    JOIN internal_research_fts f ON f.rowid = l.rowid
                    WHERE internal_research_fts MATCH ?
                      AND l.is_active = 1
                      AND l.ledger_type IN ({ph})
                      AND (? = 'ALL' OR l.question_id = ?)
                    ORDER BY l.entry_id
                    """,
                    (fts_q, *ltypes, question_id, question_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage,
                           publish_tier, verified_spec_revision, l2_category, title, abstract_md
                    FROM internal_research_ledger
                    WHERE is_active = 1
                      AND ledger_type IN ({ph})
                      AND (? = 'ALL' OR question_id = ?)
                    ORDER BY entry_id
                    """,
                    (*ltypes, question_id, question_id),
                ).fetchall()
            for r in rows:
                cards.append(
                    {
                        "entry_id": str(r["entry_id"]),
                        "wing": str(r["ledger_type"]),
                        "question_id": str(r["question_id"]),
                        "l3_entry_kind": r["l3_entry_kind"],
                        "goal_coverage": r["goal_coverage"],
                        "publish_tier": r["publish_tier"],
                        "verified_spec_revision": int(r["verified_spec_revision"] or 0),
                        "l2_category": r["l2_category"],
                        "title": str(r["title"]),
                        "abstract_preview": str(r["abstract_md"])[:350],
                    }
                )

    return build_tool_receipt(
        conn=conn,
        tool_name="query_library_catalog",
        question_id=question_id,
        node_id=node_id,
        warnings=warnings,
        next_step_guidance=f"共检索到 {len(cards)} 张目录卡；选定 1-2 张高相关卡片调用 get_library_entry 拉取完整原文。",
        data={"unlocked": unlocked, "cards": cards},
    )


def tool_get_library_entry(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    entry_id: str,
) -> dict[str, Any]:
    """三级详卡按 ID 拉取全文，并静默写入参考性 FACT_LOG(READ) 边。"""
    enforce_role_tool_permission(conn, caller_role, "get_library_entry", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    unlocked = _is_internal_pull_unlocked(caller_role, node)

    ext = conn.execute("SELECT * FROM external_literature_cards WHERE ref_id = ?", (entry_id,)).fetchone()
    if ext is not None:
        with rw_immediate_tx(conn):
            record_fact_edge(conn, source_id=node_id, target_id=entry_id, edge_type="READ", session_id=session_id)
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取外藏参考卡 {entry_id}（未复验外部摘要，须在推导/计算中自行核验适用前提）。",
            data={"wing": "EXTERNAL_R", "entry": dict(ext)},
        )

    led = conn.execute("SELECT * FROM internal_research_ledger WHERE entry_id = ?", (entry_id,)).fetchone()
    if led is not None:
        if not unlocked:
            raise FailClosedError(ERR_LOCKED, f"0-37% 独思期物理锁定内藏条目 {entry_id!r}，完成 37% 反思后开放")
        with rw_immediate_tx(conn):
            record_fact_edge(conn, source_id=node_id, target_id=entry_id, edge_type="READ", session_id=session_id)
        return build_tool_receipt(
            conn=conn,
            tool_name="get_library_entry",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取内藏 {led['ledger_type']} 条目 {entry_id} 并静默记录参考 READ 轨迹。",
            data={"wing": str(led["ledger_type"]), "entry": dict(led)},
        )

    raise FailClosedError(ERR_NOT_FOUND, f"图书馆条目 {entry_id!r} 不存在")


def tool_request_literature_survey(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    topic_query: str,
    reason: str,
) -> dict[str, Any]:
    """委托对外采编员 external_surveyor 检索外部文献/标准定理卡。"""
    enforce_role_tool_permission(conn, caller_role, "request_literature_survey", session_id=session_id, node_id=node_id)
    if not str(topic_query or "").strip() or not str(reason or "").strip():
        raise FailClosedError(ERR_INVALID_INPUT, "topic_query 与 reason 均不能为空")
    req_id = next_prefixed_id(conn, "survey_requests", "req_id", "sreq_")
    now = utc_now_iso()
    with rw_immediate_tx(conn):
        conn.execute(
            """
            INSERT INTO survey_requests(req_id, question_id, node_id, topic_query, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)
            """,
            (req_id, question_id, node_id, topic_query.strip(), reason.strip(), now, now),
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="request_literature_survey",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance=f"脱敏查新请求 {req_id} 已入队，后台 external_surveyor 完成后将入库 [R###]。",
        data={"req_id": req_id, "status": "PENDING"},
    )


def tool_read_lineage_graph(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    branch_id: str,
    target_node_id: str | None = None,
    view: str = "nodes",
    saved_query_name: str | None = None,
) -> dict[str, Any]:
    """37% 解锁后翻阅本门派私有谱系 DAG 或 lineage_dead_ends 全表（物理隔离他脉）。"""
    enforce_role_tool_permission(conn, caller_role, "read_lineage_graph", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["branch_id"]) != str(branch_id):
        raise FailClosedError(ERR_AUTH, f"门派物理隔离拦截：节点 {node_id!r} 隶属分支 {node['branch_id']!r}，严禁跨分支偷读 {branch_id!r}！")
    if int(node["first_reflection_unlocked"] or 0) != 1:
        raise FailClosedError(ERR_LOCKED, "0-37% 净室独思期暂锁本脉深层谱系 DAG 与 dead_ends，完成 37% 反思后立即开放")

    if saved_query_name:
        sq = conn.execute("SELECT sql_select, description FROM saved_graph_queries WHERE query_name = ?", (saved_query_name,)).fetchone()
        if sq is None:
            raise FailClosedError(ERR_NOT_FOUND, f"已保存查询视图 {saved_query_name!r} 不存在")
        sql = str(sq["sql_select"]).strip()
        if _SQL_WRITE_FORBIDDEN_RE.search(sql) or ";" in sql.rstrip(";"):
            raise FailClosedError(ERR_AUTH, "非法非只读 SQL 视图")
        sql_l = sql.lower()
        for forbidden_tbl in _FORBIDDEN_TENANT_TABLES:
            if forbidden_tbl in sql_l:
                raise FailClosedError(ERR_AUTH, f"租户隔离阻断：探索者禁止执行涉及受保护表 {forbidden_tbl!r} 的 SQL 视图")
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已执行只读视图 {saved_query_name!r}，返回 {len(rows)} 行。",
            data={"saved_query_name": saved_query_name, "rows": rows},
        )

    view_l = str(view or "nodes").strip().lower()
    if view_l not in ("nodes", "dead_ends"):
        raise FailClosedError(ERR_INVALID_INPUT, f"非法 view={view!r}，仅允许 'nodes' 或 'dead_ends'")

    if view_l == "dead_ends":
        de_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lineage_dead_ends WHERE branch_id = ? ORDER BY created_at ASC",
                (branch_id,),
            ).fetchall()
        ]
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已拉取本脉 {branch_id} 全部 {len(de_rows)} 条历史死胡同排除记录。",
            data={"view": "dead_ends", "branch_id": branch_id, "dead_ends": de_rows},
        )

    if target_node_id:
        tgt = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (target_node_id,)).fetchone()
        if tgt is None:
            raise FailClosedError(ERR_NOT_FOUND, f"目标谱系节点 {target_node_id!r} 不存在")
        if str(tgt["branch_id"]) != str(branch_id):
            raise FailClosedError(ERR_AUTH, f"门派物理隔离拦截：目标节点 {target_node_id!r} 不属于本分支 {branch_id!r}")
        return build_tool_receipt(
            conn=conn,
            tool_name="read_lineage_graph",
            question_id=str(node["question_id"]),
            node_id=node_id,
            next_step_guidance=f"已读取本脉祖先节点 {target_node_id} 完整记录。",
            data={"view": "nodes", "node": dict(tgt)},
        )

    nodes = [
        dict(r)
        for r in conn.execute(
            """
            SELECT node_id, generation, node_status, evidence_grade, mechanism_summary,
                   column_a_facts_md, will_md, created_at
            FROM lineage_nodes
            WHERE branch_id = ?
            ORDER BY generation ASC, created_at ASC
            """,
            (branch_id,),
        ).fetchall()
    ]
    return build_tool_receipt(
        conn=conn,
        tool_name="read_lineage_graph",
        question_id=str(node["question_id"]),
        node_id=node_id,
        next_step_guidance=f"已读取本脉 {branch_id} 共 {len(nodes)} 代谱系节点摘要。",
        data={"view": "nodes", "branch_id": branch_id, "nodes": nodes},
    )


def tool_handback_to_chief(
    conn: sqlite3.Connection,
    caller_role: str,
    session_id: str,
    node_id: str,
    question_id: str,
    human_request_md: str,
    reason: str,
) -> dict[str, Any]:
    """越界退回权：将人类在本探索节点提出的全局/跨分支诉求原样退回 gw_chief 收件箱。"""
    enforce_role_tool_permission(conn, caller_role, "handback_to_chief", session_id=session_id, node_id=node_id)
    node = conn.execute("SELECT question_id, branch_id FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
    if str(node["question_id"]) != str(question_id):
        raise FailClosedError(ERR_INVALID_INPUT, f"节点 {node_id!r} 归属 {node['question_id']!r} != {question_id!r}")
    req_md = str(human_request_md or "").strip()
    rsn = str(reason or "").strip()
    if len(req_md) < 3 or len(rsn) < 3:
        raise FailClosedError(ERR_INVALID_INPUT, "human_request_md 与 reason 均不能为空")

    eff_res: dict[str, Any] = {}
    with rw_immediate_tx(conn):
        eff_res = enqueue_runtime_effect(
            conn,
            effect_key=f"handback:{node_id}:{uuid.uuid4().hex[:8]}",
            kind="NOTIFY_CHIEF",
            target_type="PROJECT",
            target_id="gw-chief",
            payload={
                "event_type": "EXPLORER_HANDBACK",
                "node_id": node_id,
                "branch_id": str(node["branch_id"]),
                "question_id": question_id,
                "human_request_md": req_md[:2000],
                "reason": rsn[:600],
            },
        )
    return build_tool_receipt(
        conn=conn,
        tool_name="handback_to_chief",
        question_id=question_id,
        node_id=node_id,
        next_step_guidance="已将该全局/跨分支诉求原样退回科研总控 gw-chief 收件箱，请告知用户前往主控窗确认，本节点切勿越权执行。",
        data={"effect_seq": eff_res.get("seq"), "node_id": node_id, "question_id": question_id, "handed_back": True},
    )
