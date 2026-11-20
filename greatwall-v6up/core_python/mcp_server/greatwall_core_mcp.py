"""长城 Agent V6-Up (v2.2) 核心 stdio JSON-RPC 2.0 MCP 服务端入口（零第三方依赖）。

完整挂载全部 31 个单一职责窄工具 + Single-Writer 宿主控制面内部方法（control_plane/*）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_CORE_ROOT = str(Path(__file__).resolve().parent.parent)
if _CORE_ROOT not in sys.path:
    sys.path.insert(0, _CORE_ROOT)

from mcp_server.control_plane_service import (  # noqa: E402
    init_epoch_workspace,
    schedule_control_plane_snapshot,
    sync_session_pressure,
)
from mcp_server.db_schema import (  # noqa: E402
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
    ERR_INVALID_INPUT,
    FailClosedError,
    open_rw_connection,
    resolve_storage_paths,
    rw_immediate_tx,
)
from mcp_server.mcp_core_helpers import record_fact_edge  # noqa: E402
from mcp_server.mcp_schema_docs import enrich_tool_definitions  # noqa: E402
from mcp_server.tools_governance import (  # noqa: E402
    tool_check_stage2_closure_gate,
    tool_dispatch_stagnation_five_lanes,
    tool_export_stage3_final_delivery,
    tool_fork_branch,
    tool_get_blind_manuscript,
    tool_get_logistics_dashboard,
    tool_get_supervisory_audit_snapshot,
    tool_get_survey_requests,
    tool_get_unblinded_manuscript_and_peers,
    tool_get_works_engineering_queue,
    tool_propose_salvaged_lemma,
    tool_publish_external_literature_card,
    tool_recompute_stage_b_only,
    tool_record_compliance_check,
    tool_register_method_family,
    tool_register_question_domain_hook,
    tool_register_saved_graph_query,
    tool_submit_stage1_blind_ledger,
    tool_submit_stage2_unblind_verdict,
    tool_triage_node,
    tool_update_skill_ledger,
    tool_upgrade_hook_with_rqgm_gate,
)
from mcp_server.tools_research import (  # noqa: E402
    tool_get_companion_context,
    tool_get_library_entry,
    tool_query_library_catalog,
    tool_read_lineage_graph,
    tool_record_reflection_and_unlock_pull,
    tool_request_literature_survey,
    tool_run_isolated_eval,
    tool_save_lineage_briefing,
    tool_submit_node_handoff,
)

SERVER_INFO = {"name": "greatwall-v6up-core", "version": "2.2.0"}
PROTOCOL_VERSION = "2024-11-05"


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # 1. explorer (5)
    {
        "name": "run_isolated_eval",
        "description": "[explorer] 提交事前预测并对候选脚本执行跨进程隔离 Stage A+B 评估，同步写入 Observation。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "question_id": {"type": "string"},
                "candidate_rel_path": {"type": "string"},
                "linguistic_prediction": {"type": "string"},
                "declared_refs": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            ["node_id", "question_id", "candidate_rel_path", "linguistic_prediction", "declared_refs"],
        ),
    },
    {
        "name": "query_library_catalog",
        "description": "[explorer] 一级目录 Pull（0-37% 仅返回外藏 [R###]，37% 解锁后返回全馆 L3/L2/R）。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "question_id": {"type": "string"},
                "scope": {"type": "string", "enum": ["EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "ALL"]},
                "keyword": {"type": "string", "default": ""},
            },
            ["node_id", "question_id", "scope", "keyword"],
        ),
    },
    {
        "name": "get_library_entry",
        "description": "[explorer] 二级详情 Pull 并自动写入 FACT_LOG(READ) 暴露边。",
        "inputSchema": _schema({"node_id": {"type": "string"}, "entry_id": {"type": "string"}}, ["node_id", "entry_id"]),
    },
    {
        "name": "request_literature_survey",
        "description": "[explorer] 委托图书馆外藏采编馆员补查外部文献/标准定理卡片。",
        "inputSchema": _schema(
            {"node_id": {"type": "string"}, "question_id": {"type": "string"}, "topic_query": {"type": "string"}, "reason": {"type": "string"}},
            ["node_id", "question_id", "topic_query", "reason"],
        ),
    },
    {
        "name": "read_lineage_graph",
        "description": "[explorer] 37% 解锁后翻阅本门派私有谱系 DAG 或受租户隔离保护的只读视图。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "branch_id": {"type": "string"},
                "target_node_id": {"type": ["string", "null"], "default": None},
                "saved_query_name": {"type": ["string", "null"], "default": None},
            },
            ["node_id", "branch_id"],
        ),
    },
    # 2. lineage_companion (4)
    {
        "name": "get_companion_context",
        "description": "[lineage_companion] 获取 PRE_SPAWN / REFLECT_37 (含夜科学 1-28 随机 1-2 题) / HANDOFF_70 上下文包。",
        "inputSchema": _schema(
            {
                "branch_id": {"type": "string"},
                "node_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["PRE_SPAWN", "REFLECT_37", "HANDOFF_70"]},
            },
            ["branch_id", "node_id", "mode"],
        ),
    },
    {
        "name": "save_lineage_briefing",
        "description": "[lineage_companion] 按五段固定字数预算 (总长 <= 2200，禁切片) 保存增量状态看板。",
        "inputSchema": _schema(
            {
                "branch_id": {"type": "string"},
                "node_id": {"type": "string"},
                "sec1_mechanism": {"type": "string"},
                "sec2_verified_baseline": {"type": "string"},
                "sec3_bottleneck": {"type": "string"},
                "sec4_dead_ends": {"type": "string"},
                "sec5_immediate_will": {"type": "string"},
            },
            ["branch_id", "node_id", "sec1_mechanism", "sec2_verified_baseline", "sec3_bottleneck", "sec4_dead_ends", "sec5_immediate_will"],
        ),
    },
    {
        "name": "record_reflection_and_unlock_pull",
        "description": "[lineage_companion] 记录 <=2 轮(<=300字/轮) 37% 元反思并当场解锁 first_reflection_unlocked=1。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "selected_categories": {"type": "array", "items": {"type": "string"}},
                "holiday_prompt_id": {"type": "integer"},
                "turns": {"type": "array", "items": {"type": "object"}},
                "verdict_3state": {"type": "string", "enum": ["SUFFICIENT_EVIDENCE", "MINIMAL_EXPERIMENT_NEXT", "NEED_CONTROL_GROUP"]},
            },
            ["node_id", "selected_categories", "holiday_prompt_id", "turns", "verdict_3state"],
        ),
    },
    {
        "name": "submit_node_handoff",
        "description": "[lineage_companion] 谱系 DAG 唯一单写者交接（自动提取脱敏代码 Diff、痛点单及零实测崩溃隔离）。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "branch_id": {"type": "string"},
                "question_id": {"type": "string"},
                "column_a_facts_md": {"type": "string"},
                "column_b_hypothesis_md": {"type": "string"},
                "will_md": {"type": "string"},
                "obs_ids": {"type": "array", "items": {"type": "string"}},
                "candidate_rel_path": {"type": ["string", "null"], "default": None},
                "is_zero_eval_crash": {"type": "boolean", "default": False},
                "tool_pain_point": {"type": ["string", "null"], "default": None},
            },
            ["node_id", "branch_id", "question_id", "column_a_facts_md", "column_b_hypothesis_md", "will_md", "obs_ids", "is_zero_eval_crash"],
        ),
    },
    # 3. logistics_coordinator (5)
    {
        "name": "get_logistics_dashboard",
        "description": "[logistics_coordinator] 查看方法族谱、AWAITING_TRIAGE 待分诊节点、Ready Queue 与停滞计数器。",
        "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    },
    {
        "name": "register_method_family",
        "description": "[logistics_coordinator] 登记互斥方法学派（每子题开局 >= 2 个正交学派）。",
        "inputSchema": _schema(
            {
                "question_id": {"type": "string"},
                "family_id": {"type": "string"},
                "mechanism_signature": {"type": "string"},
                "orthogonal_contrast": {"type": "string"},
                "depends_on_questions": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
            },
            ["question_id", "family_id", "mechanism_signature", "orthogonal_contrast"],
        ),
    },
    {
        "name": "triage_node",
        "description": "[logistics_coordinator] 6 字段统一签名的四级分诊与物理快照/自动 L2 事务。",
        "inputSchema": _schema(
            {
                "node_id": {"type": "string"},
                "triage_level": {"type": "string", "enum": ["ROUTINE_CONTINUATION", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4A", "LEVEL_4B"]},
                "action": {"type": "string", "enum": ["CONTINUE", "SUBMIT_BLIND_REVIEW", "INPLACE_REPAIR", "SPAWN_PROTECTED", "SEAL_BARRIER", "PAUSE_TO_READY_QUEUE"]},
                "rationale": {"type": "string"},
                "barrier_proof_md": {"type": ["string", "null"], "default": None},
                "reopen_condition": {"type": ["string", "null"], "default": None},
            },
            ["node_id", "triage_level", "action", "rationale"],
        ),
    },
    {
        "name": "fork_branch",
        "description": "[logistics_coordinator] 派生正交/侧滑/授粉分支或唤醒 Ready Queue（orthogonal 自动排除自身分支）。",
        "inputSchema": _schema(
            {
                "question_id": {"type": "string"},
                "parent_node_id": {"type": ["string", "null"], "default": None},
                "fork_mode": {"type": "string", "enum": ["orthogonal", "lateral", "cross_pollinate"]},
                "target_family_id": {"type": "string"},
                "source_l3_id": {"type": ["string", "null"], "default": None},
            },
            ["question_id", "fork_mode", "target_family_id"],
        ),
    },
    {
        "name": "dispatch_stagnation_five_lanes",
        "description": "[logistics_coordinator] 停滞看门狗触发后打散编入 5 条互斥车道。",
        "inputSchema": _schema(
            {
                "question_id": {"type": "string"},
                "lane_assignments": {"type": "array", "items": {"type": "object"}},
            },
            ["question_id", "lane_assignments"],
        ),
    },
    # 4. library_surveyor (3)
    {
        "name": "get_survey_requests",
        "description": "[library_surveyor] 拉取待查新单或 Stage 3 全绿终稿汇编包。",
        "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    },
    {
        "name": "publish_external_literature_card",
        "description": "[library_surveyor] 将外部文献或标准定理/算子卡以独立摘要入库外藏 [R###]。",
        "inputSchema": _schema(
            {
                "ref_id": {"type": "string", "description": "外藏卡片编号（如 R001、R002）。"},
                "question_id": {"type": "string", "description": "所属子题编号（如 Q1、Q2 或 ALL）。"},
                "title": {"type": "string", "description": "文献或标准定理卡片标题。"},
                "abstract_md": {
                    "type": "string",
                    "minLength": 60,
                    "maxLength": 1500,
                    "description": "独立高密度摘要（60–1500 字符，推荐 120–500 字符）。",
                },
                "exact_preconditions_md": {"type": "string", "description": "严格适用前提与边界条件（必填）。"},
                "formulas_or_operators_md": {"type": "string", "description": "核心数学公式、定理表达式或算子定义（必填）。"},
                "read_depth": {
                    "type": "string",
                    "enum": sorted(ALLOWED_READ_DEPTHS),
                    "description": "阅读深度英文枚举：full_text | specified_sections | abstract_only。",
                },
                "support_scope": {
                    "type": "string",
                    "enum": sorted(ALLOWED_SUPPORT_SCOPES),
                    "description": "支持度分类英文枚举（严禁填中文）：常用 DIRECT_PROOF_OR_EXACT_MEASUREMENT | CONDITIONALLY_VERIFIED | NEGATIVE_REFUTATION | HEURISTIC_CORRELATION | BACKGROUND_REFERENCE。",
                },
                "source_citation": {"type": "string", "description": "文献出处或标准教材定理来源。"},
                "fulfilled_request_ids": {"type": ["array", "null"], "items": {"type": "string"}, "default": None, "description": "核销的 request_id 列表，主动建卡传 null 或 []。"},
            },
            ["ref_id", "question_id", "title", "abstract_md", "exact_preconditions_md", "formulas_or_operators_md", "read_depth", "support_scope", "source_citation"],
        ),
    },
    {
        "name": "export_stage3_final_delivery",
        "description": "[library_surveyor] Stage 3 终局导出 final_delivery/ 五件套（受 check_stage2_closure_gate 硬锁保护）。",
        "inputSchema": _schema(
            {
                "formal_paper_md": {"type": "string"},
                "selected_l3_ids_by_question": {"type": "object"},
                "reproduction_candidate_nodes": {"type": "array", "items": {"type": "string"}},
            },
            ["formal_paper_md", "selected_l3_ids_by_question", "reproduction_candidate_nodes"],
        ),
    },
    # 5. library_verifier (5)
    {
        "name": "get_blind_manuscript",
        "description": "[library_verifier] 纯 DB 零磁盘读取 Stage 1 盲态 A 栏 + sanitized_code_diff_md + [Obs###]。",
        "inputSchema": _schema({"review_id": {"type": "string"}}, ["review_id"]),
    },
    {
        "name": "submit_stage1_blind_ledger",
        "description": "[library_verifier] 提交并不可逆锁定 Stage 1 Evidence Ledger（REJECT 直接短路入 L2）。",
        "inputSchema": _schema(
            {
                "review_id": {"type": "string"},
                "question_id": {"type": "string"},
                "ledger_items": {"type": "array", "items": {"type": "object"}},
                "stage1_verdict": {"type": "string", "enum": ["PASS", "REJECT"]},
                "reject_failure_reason": {"type": ["string", "null"], "default": None},
                "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
            },
            ["review_id", "question_id", "ledger_items", "stage1_verdict"],
        ),
    },
    {
        "name": "get_unblinded_manuscript_and_peers",
        "description": "[library_verifier] Stage 1 锁定 PASS 后解盲读取 B 栏、FACT_LOG 对账与 Cross-Draft 横向快照。",
        "inputSchema": _schema({"review_id": {"type": "string"}}, ["review_id"]),
    },
    {
        "name": "submit_stage2_unblind_verdict",
        "description": "[library_verifier] 提交 Stage 2 终审裁决（单向降级锁，同事务自动写入 L3_VERIFIED 或 L2_FAILURE_RECORD）。",
        "inputSchema": _schema(
            {
                "review_id": {"type": "string"},
                "final_verdict": {"type": "string", "enum": ["PASS", "PASS_WITH_NARROWED_SCOPE", "REJECT"]},
                "title": {"type": "string"},
                "abstract_md": {"type": "string"},
                "exact_verified_scope_md": {"type": ["string", "null"], "default": None},
                "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
                "cross_draft_comparison_notes": {"type": "string", "default": ""},
                "cross_pollinate_nomination": {"type": ["object", "null"], "default": None},
                "edge_type_overrides": {"type": ["object", "null"], "default": None},
            },
            ["review_id", "final_verdict", "title", "abstract_md"],
        ),
    },
    {
        "name": "propose_salvaged_lemma",
        "description": "[library_verifier] Auditor 剥离打捞自包含引理并直入标准 STAGE1_BLIND 队列强制异会话盲审。",
        "inputSchema": _schema(
            {
                "source_node_id": {"type": "string"},
                "question_id": {"type": "string"},
                "title": {"type": "string"},
                "abstract_md": {"type": "string"},
                "column_a_self_contained_proof_md": {"type": "string"},
                "column_b_scope_notes_md": {"type": "string"},
                "bound_obs_ids": {"type": "array", "items": {"type": "string"}},
            },
            ["source_node_id", "question_id", "title", "abstract_md", "column_a_self_contained_proof_md", "column_b_scope_notes_md", "bound_obs_ids"],
        ),
    },
    # 6. works_engineer (5)
    {
        "name": "get_works_engineering_queue",
        "description": "[works_engineer] 查看子题钩子状态、前线痛点单与待重评队列。",
        "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    },
    {
        "name": "register_question_domain_hook",
        "description": "[works_engineer] 按子题注册独立验证钩子、隔离基线与公开样例包（校验 <5% 保真门禁与 AST 隔离）。",
        "inputSchema": _schema(
            {
                "question_id": {"type": "string"},
                "hook_rel_path": {"type": "string"},
                "baseline_rel_path": {"type": "string"},
                "fidelity_max_error_pct": {"type": "number"},
                "plugin_protocol_version": {"type": "string", "default": "v1"},
                "public_input_sample": {"type": ["object", "null"], "default": None},
            },
            ["question_id", "hook_rel_path", "baseline_rel_path", "fidelity_max_error_pct"],
        ),
    },
    {
        "name": "upgrade_hook_with_rqgm_gate",
        "description": "[works_engineer] 过 RQGM 锚点与对抗池 Q_P 门禁（配置脚本锚点时服务端强制实跑覆盖）升版并局部入队重评。",
        "inputSchema": _schema(
            {
                "question_id": {"type": "string"},
                "new_hook_rel_path": {"type": "string"},
                "gt_success_count": {"type": "integer"},
                "gt_failure_count": {"type": "integer"},
                "adv_pool_reject_rate": {"type": ["number", "null"], "default": None},
                "adv_pool_positive_rate": {"type": ["number", "null"], "default": None},
                "adv_pool_negative_rate": {"type": ["number", "null"], "default": None},
            },
            ["question_id", "new_hook_rel_path", "gt_success_count", "gt_failure_count"],
        ),
    },
    {
        "name": "recompute_stage_b_only",
        "description": "[works_engineer] 读取持久化 stage_a_output.json 免 Stage A 秒级重算并恢复 VALID。",
        "inputSchema": _schema({"obs_id": {"type": "string"}, "question_id": {"type": "string"}}, ["obs_id", "question_id"]),
    },
    {
        "name": "update_skill_ledger",
        "description": "[works_engineer] 过 No File 实测检验并登记 B 档共享探针入 SKILL_LEDGER.json。",
        "inputSchema": _schema(
            {
                "skill_id": {"type": "string"},
                "applicable_scope": {"type": "string"},
                "version": {"type": "integer"},
                "raw_success_count": {"type": "integer"},
                "raw_failure_count": {"type": "integer"},
                "verified_artifact_rel_path": {"type": "string"},
                "rollback_pointer": {"type": "string"},
            },
            ["skill_id", "applicable_scope", "version", "raw_success_count", "raw_failure_count", "verified_artifact_rel_path", "rollback_pointer"],
        ),
    },
    # 7. supervisory_committee (4)
    {
        "name": "get_supervisory_audit_snapshot",
        "description": "[supervisory_committee] 拉取钩子保真、FACT_LOG 对账、停滞计数、重评积压与 L3 计数快照。",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "check_stage2_closure_gate",
        "description": "[supervisory_committee] 核检每题 L3_VERIFIED >= 1 硬锁状态（零 .md 公文）。",
        "inputSchema": _schema({}, []),
    },
    {
        "name": "record_compliance_check",
        "description": "[supervisory_committee] 向 SQLite compliance_alerts 写入合规核验结果。",
        "inputSchema": _schema(
            {
                "stage": {"type": "string", "enum": ["STAGE1_GATE", "STAGE2_HEARTBEAT", "STAGE2_CLOSURE_GATE", "STAGE3_FINAL_AUDIT"]},
                "status": {"type": "string", "enum": ["PASSED", "ALERT", "BLOCKED"]},
                "blocking_questions_zero_l3": {"type": "array", "items": {"type": "string"}},
                "unread_citation_nodes": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            ["stage", "status", "blocking_questions_zero_l3", "unread_citation_nodes", "notes"],
        ),
    },
    {
        "name": "register_saved_graph_query",
        "description": "[supervisory_committee] 注册经 EXPLAIN QUERY PLAN 预检的 A 档只读 SQL 视图。",
        "inputSchema": _schema(
            {"query_name": {"type": "string"}, "description": {"type": "string"}, "sql_select": {"type": "string"}},
            ["query_name", "description", "sql_select"],
        ),
    },
]

_TOOL_REGISTRY: dict[str, tuple[Any, bool]] = {
    # (handler_fn, needs_workspace_root)
    "run_isolated_eval": (tool_run_isolated_eval, True),
    "query_library_catalog": (tool_query_library_catalog, False),
    "get_library_entry": (tool_get_library_entry, False),
    "request_literature_survey": (tool_request_literature_survey, False),
    "read_lineage_graph": (tool_read_lineage_graph, False),
    "get_companion_context": (tool_get_companion_context, False),
    "save_lineage_briefing": (tool_save_lineage_briefing, False),
    "record_reflection_and_unlock_pull": (tool_record_reflection_and_unlock_pull, False),
    "submit_node_handoff": (tool_submit_node_handoff, True),
    "get_logistics_dashboard": (tool_get_logistics_dashboard, False),
    "register_method_family": (tool_register_method_family, False),
    "triage_node": (tool_triage_node, True),
    "fork_branch": (tool_fork_branch, True),
    "dispatch_stagnation_five_lanes": (tool_dispatch_stagnation_five_lanes, False),
    "get_survey_requests": (tool_get_survey_requests, False),
    "publish_external_literature_card": (tool_publish_external_literature_card, False),
    "export_stage3_final_delivery": (tool_export_stage3_final_delivery, True),
    "get_blind_manuscript": (tool_get_blind_manuscript, False),
    "submit_stage1_blind_ledger": (tool_submit_stage1_blind_ledger, False),
    "get_unblinded_manuscript_and_peers": (tool_get_unblinded_manuscript_and_peers, False),
    "submit_stage2_unblind_verdict": (tool_submit_stage2_unblind_verdict, False),
    "propose_salvaged_lemma": (tool_propose_salvaged_lemma, False),
    "get_works_engineering_queue": (tool_get_works_engineering_queue, False),
    "register_question_domain_hook": (tool_register_question_domain_hook, True),
    "upgrade_hook_with_rqgm_gate": (tool_upgrade_hook_with_rqgm_gate, True),
    "recompute_stage_b_only": (tool_recompute_stage_b_only, True),
    "update_skill_ledger": (tool_update_skill_ledger, True),
    "get_supervisory_audit_snapshot": (tool_get_supervisory_audit_snapshot, False),
    "check_stage2_closure_gate": (tool_check_stage2_closure_gate, False),
    "record_compliance_check": (tool_record_compliance_check, False),
    "register_saved_graph_query": (tool_register_saved_graph_query, False),
}


def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    workspace_root: str = "",
    caller_role: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """统一执行 31 个窄工具的入口，负责连接管理、可信上下文注入与 FailClosedError 转换。"""
    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return FailClosedError(ERR_INVALID_INPUT, f"未知工具: {name!r}").to_dict()
    if arguments is not None and not isinstance(arguments, dict):
        return FailClosedError(ERR_INVALID_INPUT, "tool arguments 必须为 JSON 对象").to_dict()

    raw_args = dict(arguments or {})
    meta = raw_args.pop("_meta", None)
    if not isinstance(meta, dict):
        meta = {}

    # [P0 安全修复] 严格禁止模型参数伪造身份：丢弃 arguments 内私夹的 caller_role/role/session_id/workspace_root
    raw_args.pop("workspace_root", None)
    raw_args.pop("caller_role", None)
    raw_args.pop("role", None)
    raw_args.pop("session_id", None)

    eff_ws = str(
        workspace_root
        or meta.get("workspace_root", "")
        or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")
    ).strip()
    eff_role = str(
        caller_role
        or meta.get("caller_role", "")
        or meta.get("role", "")
    ).strip()
    eff_sid = str(
        session_id
        or meta.get("session_id", "")
    ).strip()

    fn, needs_ws = entry
    conn = None
    try:
        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        kwargs: dict[str, Any] = {
            "conn": conn,
            "caller_role": eff_role,
            "session_id": eff_sid,
            **raw_args,
        }
        if needs_ws:
            kwargs["workspace_root"] = eff_ws or str(paths["data_dir"])
        return fn(**kwargs)
    except FailClosedError as exc:
        return exc.to_dict()
    except TypeError as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"参数签名不匹配 ({name}): {exc}").to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"执行异常 ({name}): {type(exc).__name__}: {exc}").to_dict()
    finally:
        if conn is not None:
            conn.close()


def dispatch_control_call(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """Single-Writer 控制面内部桥接原语（供 Node Orchestrator 确定性同步，非模型侧工具）。"""
    p = dict(params or {})
    eff_ws = str(p.pop("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    conn = None
    try:
        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        if method == "control_plane/init_epoch":
            res = init_epoch_workspace(
                conn,
                goal_md=str(p.get("goal_md", "")),
                required_questions=p.get("required_questions"),
                contracts=p.get("contracts"),
                stage=str(p.get("stage", "STAGE1_PARSE0")),
                epoch_id=int(p.get("epoch_id", 1)),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/schedule_snapshot":
            res = schedule_control_plane_snapshot(
                conn,
                max_concurrent_workers=p.get("max_concurrent_workers"),
                workspace_root=eff_ws,
            )
            return {"ok": True, "data": res}
        if method == "control_plane/sync_pressure":
            res = sync_session_pressure(conn, node_id=str(p["node_id"]), pressure_tokens=int(p["pressure_tokens"]))
            return {"ok": True, "data": res}
        if method == "control_plane/fact_edge":
            with rw_immediate_tx(conn):
                record_fact_edge(
                    conn,
                    src_id=str(p.get("src_id") or p.get("node_id") or p.get("session_id") or "host"),
                    dst_id=str(p.get("dst_id") or ""),
                    edge_type=str(p.get("edge_type") or "USED_TOOL"),
                    metadata=p.get("metadata") if isinstance(p.get("metadata"), dict) else {},
                )
            return {"ok": True}
        return FailClosedError(ERR_INVALID_INPUT, f"未知控制面方法: {method!r}").to_dict()
    except FailClosedError as exc:
        return exc.to_dict()
    except Exception as exc:
        return FailClosedError(ERR_INVALID_INPUT, f"控制面异常 ({method}): {exc}").to_dict()
    finally:
        if conn is not None:
            conn.close()


def _read_next_message(stdin_buf: Any) -> tuple[dict[str, Any] | None, str]:
    while True:
        raw_line = stdin_buf.readline()
        if not raw_line:
            return None, ""
        stripped = raw_line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith(b"content-length:") or lower.startswith(b"content-type:"):
            content_length = 0
            header_line = stripped
            while True:
                if header_line.lower().startswith(b"content-length:"):
                    val_str = header_line.split(b":", 1)[1].strip().decode("ascii")
                    content_length = int(val_str)
                nxt = stdin_buf.readline()
                if not nxt or nxt in (b"\r\n", b"\n"):
                    break
                header_line = nxt.strip()
            body = stdin_buf.read(content_length)
            return json.loads(body.decode("utf-8")), "lsp"
        return json.loads(stripped.decode("utf-8")), "ndjson"


def _write_message(stdout_buf: Any, payload: dict[str, Any], framing_mode: str) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if framing_mode == "lsp":
        header = f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii")
        stdout_buf.write(header + encoded)
    else:
        stdout_buf.write(encoded + b"\n")
    stdout_buf.flush()


def handle_jsonrpc_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "notifications/initialized" or msg_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOL_DEFINITIONS}}

    if method == "tools/call":
        t_name = str(params.get("name", ""))
        t_args = params.get("arguments", {})
        res = dispatch_tool_call(t_name, t_args)
        is_err = not bool(res.get("ok", False))
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                "isError": is_err,
            },
        }

    if isinstance(method, str) and method.startswith("control_plane/"):
        res = dispatch_control_call(method, params)
        return {"jsonrpc": "2.0", "id": msg_id, "result": res}

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio() -> int:
    stdin_buf = sys.stdin.buffer
    stdout_buf = sys.stdout.buffer
    while True:
        try:
            msg, framing = _read_next_message(stdin_buf)
        except Exception as exc:
            _write_message(
                stdout_buf,
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}},
                "ndjson",
            )
            continue
        if msg is None:
            return 0
        resp = handle_jsonrpc_message(msg)
        if resp is not None:
            _write_message(stdout_buf, resp, framing or "ndjson")


TOOL_DEFINITIONS[:] = enrich_tool_definitions(TOOL_DEFINITIONS)


if __name__ == "__main__":
    raise SystemExit(serve_stdio())
