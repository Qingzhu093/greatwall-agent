"""长城 Agent V6-Up (v3.0) 核心 stdio JSON-RPC 2.0 MCP 服务端入口（零第三方依赖）。

完整挂载 7 大角色共 31 个单一职责窄工具（100% 对齐 agent_kb/05 §0.2）
+ Single-Writer 控制面内部原语（control_plane/*）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    __package__ = "core_python.mcp_server"

from .control_plane_service import (  # noqa: E402
    cleanup_blind_review_sandbox,
    init_parse0_contract,
    record_human_stop,
    record_pending_handoff,
    recover_pending_heavy_jobs,
    schedule_control_plane_snapshot,
    stage_blind_review_sandbox,
    sync_session_pressure,
    uninitialized_schedule_snapshot,
)
from .db_schema import (  # noqa: E402
    ERR_INVALID_INPUT,
    FailClosedError,
    open_rw_connection,
    resolve_storage_paths,
    rw_immediate_tx,
)
from .mcp_core_helpers import record_fact_edge  # noqa: E402
from .mcp_schema_docs import enrich_tool_definitions  # noqa: E402
from .tools_governance import (  # noqa: E402
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
    tool_register_question_instrument,
    tool_register_saved_graph_query,
    tool_submit_stage1_blind_ledger,
    tool_submit_stage2_unblind_verdict,
    tool_triage_node,
    tool_update_skill_ledger,
    tool_upgrade_instrument_with_calibration,
)
from .tools_research import (  # noqa: E402
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

SERVER_INFO = {"name": "greatwall-v6up-core", "version": "3.0.0"}
PROTOCOL_VERSION = "2024-11-05"


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


TOOL_DEFINITIONS: list[dict[str, Any]] = enrich_tool_definitions(
    [
        # 1. explorer (5)
        {
            "name": "run_isolated_eval",
            "description": "[explorer] 统一三档仪器隔离调用：probe（诊断不记 Obs）/ official（正式凭证）/ heavy（冻结快照异步幂等取回）。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "instrument_id": {"type": "string"},
                    "tier": {"type": "string"},
                    "artifact_rel_path": {"type": "string"},
                    "linguistic_prediction": {"type": "string"},
                    "declared_refs": {"type": "array", "items": {"type": "string"}, "default": []},
                    "job_id": {"type": ["string", "null"], "default": None},
                },
                ["node_id", "question_id", "instrument_id", "tier", "artifact_rel_path", "linguistic_prediction", "declared_refs"],
            ),
        },
        {
            "name": "query_library_catalog",
            "description": "[explorer] 一级目录 Pull（0-37% 仅返回外藏 [R###]，37% 解锁后全馆两翼开放）。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "scope": {"type": "string"},
                    "keyword": {"type": "string", "default": ""},
                },
                ["node_id", "question_id", "scope", "keyword"],
            ),
        },
        {
            "name": "get_library_entry",
            "description": "[explorer] 二级详卡 Pull 并静默写入参考性 FACT_LOG(READ) 边。",
            "inputSchema": _schema({"node_id": {"type": "string"}, "entry_id": {"type": "string"}}, ["node_id", "entry_id"]),
        },
        {
            "name": "request_literature_survey",
            "description": "[explorer] 委托图书馆外藏采编馆员补查外部文献/标准定理卡。",
            "inputSchema": _schema(
                {"node_id": {"type": "string"}, "question_id": {"type": "string"}, "topic_query": {"type": "string"}, "reason": {"type": "string"}},
                ["node_id", "question_id", "topic_query", "reason"],
            ),
        },
        {
            "name": "read_lineage_graph",
            "description": "[explorer] 37% 解锁后翻阅本门派私有谱系 DAG 或 lineage_dead_ends 全表（物理隔离他脉）。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "branch_id": {"type": "string"},
                    "target_node_id": {"type": ["string", "null"], "default": None},
                    "view": {"type": "string", "default": "nodes"},
                    "saved_query_name": {"type": ["string", "null"], "default": None},
                },
                ["node_id", "branch_id"],
            ),
        },
        # 2. lineage_companion (4)
        {
            "name": "get_companion_context",
            "description": "[lineage_companion] 获取 PRE_SPAWN / REFLECT_37 / HANDOFF_70 / CRASH_RECOVERY 阶段隔离上下文。",
            "inputSchema": _schema(
                {"branch_id": {"type": "string"}, "node_id": {"type": "string"}, "mode": {"type": "string"}},
                ["branch_id", "node_id", "mode"],
            ),
        },
        {
            "name": "save_lineage_briefing",
            "description": "[lineage_companion] 按 Rewrite_<=2200 定额滚动重压缩写入谱系状态看板（唯一硬限总长 <= 2200 字）。",
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
            "description": "[lineage_companion] 记录 <=2 轮(<=300字/轮) 37% 情报型元反思并当场解锁 first_reflection_unlocked=1（无 eval_count 门槛）。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "selected_categories": {"type": "array", "items": {"type": "string"}},
                    "holiday_prompt_id": {"type": "integer"},
                    "turns": {"type": "array", "items": {"type": "object"}},
                    "verdict_3state": {"type": "string"},
                },
                ["node_id", "selected_categories", "holiday_prompt_id", "turns", "verdict_3state"],
            ),
        },
        {
            "name": "submit_node_handoff",
            "description": "[lineage_companion] 独占单写谱系 DAG 页与只追加 lineage_dead_ends 表，并置节点 AWAITING_TRIAGE。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "branch_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "mechanism_summary": {"type": "string"},
                    "evidence_grade": {"type": "string"},
                    "column_a_facts_md": {"type": "string"},
                    "column_b_hypothesis_md": {"type": "string"},
                    "will_md": {"type": "string"},
                    "obs_ids": {"type": "array", "items": {"type": "string"}, "default": []},
                    "dead_ends": {"type": "array", "items": {"type": "object"}, "default": []},
                    "candidate_rel_path": {"type": ["string", "null"], "default": None},
                    "is_empty_crash": {"type": "boolean", "default": False},
                    "tool_pain_point": {"type": ["string", "null"], "default": None},
                },
                ["node_id", "branch_id", "question_id", "mechanism_summary", "evidence_grade", "column_a_facts_md", "column_b_hypothesis_md", "will_md", "obs_ids", "dead_ends", "is_empty_crash"],
            ),
        },
        # 3. logistics_coordinator (5)
        {
            "name": "get_logistics_dashboard",
            "description": "[logistics_coordinator] 纯只读 (<50ms) 拉取各题方法族谱占比、>50% 聚拢告警、待分诊页与 Ready Queue。",
            "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
        },
        {
            "name": "register_method_family",
            "description": "[logistics_coordinator] 按需登记底层数学/物理思想学派（不强卡固定条数）。",
            "inputSchema": _schema(
                {
                    "question_id": {"type": "string"},
                    "family_id": {"type": "string"},
                    "mechanism_signature": {"type": "string"},
                    "orthogonal_contrast": {"type": "string"},
                },
                ["question_id", "family_id", "mechanism_signature", "orthogonal_contrast"],
            ),
        },
        {
            "name": "triage_node",
            "description": "[logistics_coordinator] 对 AWAITING_TRIAGE 节点归类学派并执行四级认知分诊与快照托管。",
            "inputSchema": _schema(
                {
                    "node_id": {"type": "string"},
                    "assigned_family_id": {"type": "string"},
                    "triage_level": {"type": "string"},
                    "action": {"type": "string"},
                    "rationale": {"type": "string"},
                    "barrier_proof_md": {"type": ["string", "null"], "default": None},
                    "reopen_condition": {"type": ["string", "null"], "default": None},
                },
                ["node_id", "assigned_family_id", "triage_level", "action", "rationale"],
            ),
        },
        {
            "name": "fork_branch",
            "description": "[logistics_coordinator] 开启新探索分支（分支级确定性 requires、WHERE branch_id != :self 查重、双 L3 授粉门槛）。",
            "inputSchema": _schema(
                {
                    "question_id": {"type": "string"},
                    "parent_node_id": {"type": ["string", "null"], "default": None},
                    "fork_mode": {"type": "string"},
                    "target_family_id": {"type": "string"},
                    "requires": {"type": "array", "items": {"type": "string"}, "default": []},
                    "new_mechanism_note": {"type": ["string", "null"], "default": None},
                    "source_l3_id": {"type": ["string", "null"], "default": None},
                },
                ["question_id", "fork_mode", "target_family_id"],
            ),
        },
        {
            "name": "dispatch_stagnation_five_lanes",
            "description": "[logistics_coordinator] 停滞看门狗或 >50% 聚拢告警触发时执行五互斥车道算力重排。",
            "inputSchema": _schema(
                {"question_id": {"type": "string"}, "lane_assignments": {"type": "array", "items": {"type": "object"}}},
                ["question_id", "lane_assignments"],
            ),
        },
        # 4. library_surveyor (3)
        {
            "name": "get_survey_requests",
            "description": "[library_surveyor] 获取 Stage 1-2 查新委托队列及 Stage 3 全量已审 L3/L2/[R###] 综合数据包。",
            "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
        },
        {
            "name": "publish_external_literature_card",
            "description": "[library_surveyor] 将外部文献/定理卡入库左翼外藏 [R###]（严格 5 枚举 support_scope 与 60-1500 字独立摘要）。",
            "inputSchema": _schema(
                {
                    "ref_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "title": {"type": "string"},
                    "abstract_md": {"type": "string"},
                    "exact_preconditions_md": {"type": "string"},
                    "formulas_or_operators_md": {"type": "string"},
                    "read_depth": {"type": "string"},
                    "support_scope": {"type": "string"},
                    "source_citation": {"type": "string"},
                    "fulfilled_request_ids": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                },
                ["ref_id", "question_id", "title", "abstract_md", "exact_preconditions_md", "formulas_or_operators_md", "read_depth", "support_scope", "source_citation"],
            ),
        },
        {
            "name": "export_stage3_final_delivery",
            "description": "[library_surveyor] 导出 Stage 3 五件套（生成 delivery_id/sha256，置 DELIVERY_EXPORTED 等待两步联合终核）。",
            "inputSchema": _schema(
                {
                    "delivery_mode": {"type": "string"},
                    "formal_paper_md": {"type": "string"},
                    "selected_l3_ids_by_question": {"type": "object"},
                    "remaining_gaps_by_question": {"type": "object"},
                    "reproduction_candidate_nodes": {"type": "array", "items": {"type": "string"}},
                },
                ["delivery_mode", "formal_paper_md", "selected_l3_ids_by_question", "remaining_gaps_by_question", "reproduction_candidate_nodes"],
            ),
        },
        # 5. library_verifier (5)
        {
            "name": "get_blind_manuscript",
            "description": "[library_verifier] Stage 1 盲态拉取并挂载独立空白盲审沙箱（仅拷 A 栏、脱敏代码与 [Obs###]）。",
            "inputSchema": _schema({"review_id": {"type": "string"}}, ["review_id"]),
        },
        {
            "name": "submit_stage1_blind_ledger",
            "description": "[library_verifier] 永久锁定 Stage 1 不可逆 Evidence Ledger，按 PASS / REVISE / REFUTED 精准分流。",
            "inputSchema": _schema(
                {
                    "review_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "ledger_items": {"type": "array", "items": {"type": "object"}},
                    "stage1_verdict": {"type": "string"},
                    "revision_or_refutation_reason": {"type": ["string", "null"], "default": None},
                    "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
                },
                ["review_id", "question_id", "ledger_items", "stage1_verdict"],
            ),
        },
        {
            "name": "get_unblinded_manuscript_and_peers",
            "description": "[library_verifier] Stage 2 解盲横审拉取，或 Stage 3 终核模式 (STAGE3_FINAL_AUDIT:<delivery_id>) 五件套核查。",
            "inputSchema": _schema({"review_id": {"type": "string"}}, ["review_id"]),
        },
        {
            "name": "submit_stage2_unblind_verdict",
            "description": "[library_verifier] Stage 2 三态终判（ACCEPT* 入 L3 / REVISE 返工 / REFUTED 入 L2）及 Stage 3 终核版本落签。",
            "inputSchema": _schema(
                {
                    "review_id": {"type": "string"},
                    "final_verdict": {"type": "string"},
                    "l3_entry_kind": {"type": ["string", "null"], "default": None},
                    "goal_coverage": {"type": ["string", "null"], "default": None},
                    "is_equivalent_reduction": {"type": "boolean", "default": False},
                    "title": {"type": "string", "default": ""},
                    "abstract_md": {"type": "string", "default": ""},
                    "exact_verified_scope_md": {"type": ["string", "null"], "default": None},
                    "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
                    "revision_requests": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                    "cross_draft_comparison_notes": {"type": "string", "default": ""},
                    "cross_pollinate_nomination": {"type": ["object", "null"], "default": None},
                    "edge_type_overrides": {"type": ["object", "null"], "default": None},
                },
                ["review_id", "final_verdict"],
            ),
        },
        {
            "name": "propose_salvaged_lemma",
            "description": "[library_verifier] Auditor 对已闭/阻塞节点打捞自包含局部引理（严禁抢断 ACTIVE_REVISING 返工分支）。",
            "inputSchema": _schema(
                {
                    "source_node_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "title": {"type": "string"},
                    "abstract_md": {"type": "string"},
                    "column_a_self_contained_proof_md": {"type": "string"},
                    "column_b_scope_notes_md": {"type": "string"},
                    "bound_obs_ids": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                ["source_node_id", "question_id", "title", "abstract_md", "column_a_self_contained_proof_md", "column_b_scope_notes_md", "bound_obs_ids"],
            ),
        },
        # 6. works_engineer (5)
        {
            "name": "get_works_engineering_queue",
            "description": "[works_engineer] 纯只读 (<50ms) 返回仪器清单、熔断状态、故障/痛点工单与 pending_revalidation 待重评队列。",
            "inputSchema": _schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
        },
        {
            "name": "register_question_instrument",
            "description": "[works_engineer] 注册新科研仪器（VERDICT 强跑独立校准集 100% 匹配自声明预期；PROBE/ENV 可免校准集）。",
            "inputSchema": _schema(
                {
                    "question_id": {"type": "string"},
                    "instrument_id": {"type": "string"},
                    "instrument_role": {"type": "string"},
                    "instrument_rel_path": {"type": "string"},
                    "calibration_suite_rel_path": {"type": ["string", "null"], "default": None},
                    "artifact_schema": {"type": "string", "default": "python_run"},
                    "plugin_protocol_version": {"type": "string", "default": "v3"},
                    "default_spec": {"type": ["object", "null"], "default": None},
                },
                ["question_id", "instrument_id", "instrument_role", "instrument_rel_path", "artifact_schema", "plugin_protocol_version"],
            ),
        },
        {
            "name": "upgrade_instrument_with_calibration",
            "description": "[works_engineer] 校准集 100% 通过即升版仪器，仅选择性将本仪器旧观测入待重评队列（零误杀他题）。",
            "inputSchema": _schema(
                {
                    "question_id": {"type": "string"},
                    "instrument_id": {"type": "string"},
                    "new_instrument_rel_path": {"type": "string"},
                    "calibration_suite_rel_path": {"type": "string"},
                },
                ["question_id", "instrument_id", "new_instrument_rel_path", "calibration_suite_rel_path"],
            ),
        },
        {
            "name": "recompute_stage_b_only",
            "description": "[works_engineer] 读持久化 Stage A 产物按新版仪器诚实重评（保留旧收据，成功生新收据，缺字段标 INCOMPATIBLE）。",
            "inputSchema": _schema(
                {"obs_id": {"type": "string"}, "question_id": {"type": "string"}},
                ["obs_id", "question_id"],
            ),
        },
        {
            "name": "update_skill_ledger",
            "description": "[works_engineer] No-File 校验后向工作区隔离 SKILL_LEDGER.json 登记共享工具/探针。",
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
            "description": "[supervisory_committee] 纯只读 (<50ms) 获取 Parse 0、仪器熔断、口径红灯、聚拢告警与两步终局审计快照。",
            "inputSchema": _schema({}, []),
        },
        {
            "name": "check_stage2_closure_gate",
            "description": "[supervisory_committee] 校验 CDC 双段终局门禁（FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP）。",
            "inputSchema": _schema(
                {"mode": {"type": "string", "default": "FULL"}, "human_aborted": {"type": "boolean", "default": False}},
                ["mode", "human_aborted"],
            ),
        },
        {
            "name": "record_compliance_check",
            "description": "[supervisory_committee] 写入 SQLite 合规与红灯告警（零 .md 落盘；CLOSURE_GATE 强校验终核版本绑定）。",
            "inputSchema": _schema(
                {
                    "stage": {"type": "string"},
                    "status": {"type": "string"},
                    "blocking_questions": {"type": "array", "items": {"type": "string"}, "default": []},
                    "notes": {"type": "string", "default": ""},
                },
                ["stage", "status", "blocking_questions", "notes"],
            ),
        },
        {
            "name": "register_saved_graph_query",
            "description": "[supervisory_committee] 校验并注册单条只读 SELECT 共享图查询视图。",
            "inputSchema": _schema(
                {"query_name": {"type": "string"}, "description": {"type": "string"}, "sql_select": {"type": "string"}},
                ["query_name", "description", "sql_select"],
            ),
        },
    ]
)

_TOOL_REGISTRY: dict[str, tuple[Any, bool]] = {
    # (fn, needs_workspace_root)
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
    "get_blind_manuscript": (tool_get_blind_manuscript, True),
    "submit_stage1_blind_ledger": (tool_submit_stage1_blind_ledger, False),
    "get_unblinded_manuscript_and_peers": (tool_get_unblinded_manuscript_and_peers, True),
    "submit_stage2_unblind_verdict": (tool_submit_stage2_unblind_verdict, False),
    "propose_salvaged_lemma": (tool_propose_salvaged_lemma, False),
    "get_works_engineering_queue": (tool_get_works_engineering_queue, False),
    "register_question_instrument": (tool_register_question_instrument, True),
    "upgrade_instrument_with_calibration": (tool_upgrade_instrument_with_calibration, True),
    "recompute_stage_b_only": (tool_recompute_stage_b_only, True),
    "update_skill_ledger": (tool_update_skill_ledger, True),
    "get_supervisory_audit_snapshot": (tool_get_supervisory_audit_snapshot, False),
    "check_stage2_closure_gate": (tool_check_stage2_closure_gate, False),
    "record_compliance_check": (tool_record_compliance_check, True),
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
    """统一执行 31 个窄工具入口：剥离模型伪造身份，注入可信宿主 _meta 并处理 FailClosedError。"""
    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        return FailClosedError(ERR_INVALID_INPUT, f"未知工具: {name!r}").to_dict()
    if arguments is not None and not isinstance(arguments, dict):
        return FailClosedError(ERR_INVALID_INPUT, "tool arguments 必须为 JSON 对象").to_dict()

    raw_args = dict(arguments or {})
    meta = raw_args.pop("_meta", None)
    if not isinstance(meta, dict):
        meta = {}

    # 严格丢弃模型参数内私夹的身份伪造字段
    for spoof_k in ("workspace_root", "caller_role", "role", "session_id"):
        raw_args.pop(spoof_k, None)

    eff_ws = str(workspace_root or meta.get("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    eff_role = str(caller_role or meta.get("caller_role", "") or meta.get("role", "")).strip()
    eff_sid = str(session_id or meta.get("session_id", "")).strip()

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
    """Single-Writer 控制面内部桥接原语（仅供 Node Orchestrator 调用，非模型侧工具）。"""
    p = dict(params or {})
    eff_ws = str(p.pop("workspace_root", "") or os.environ.get("GREATWALL_WORKSPACE_ROOT", "")).strip()
    conn = None
    try:
        # 纯只读探测与启动恢复：若尚未初始化数据库，严禁无故创建目录与 300KB 空库
        if method in ("control_plane/schedule_snapshot", "control_plane/recover_heavy_jobs"):
            probe_paths = resolve_storage_paths(eff_ws, create_dirs=False)
            if not probe_paths["db_path"].is_file():
                if method == "control_plane/schedule_snapshot":
                    return {
                        "ok": True,
                        "data": uninitialized_schedule_snapshot(
                            max_concurrent_workers=p.get("max_concurrent_workers")
                        ),
                    }
                return {"ok": True, "data": {"recovered_jobs": []}}

        paths = resolve_storage_paths(eff_ws)
        conn = open_rw_connection(paths["db_path"], init_schema=True)
        if method in ("control_plane/init_parse0", "control_plane/init_epoch"):
            res = init_parse0_contract(
                conn,
                goal_and_completion_md=str(p.get("goal_and_completion_md") or p.get("goal_md") or ""),
                subquestions=p.get("subquestions") or p.get("required_questions"),
                question_order=p.get("question_order"),
                initial_instruments=p.get("initial_instruments"),
                seed_families=p.get("seed_families"),
                total_budget=p.get("total_budget"),
                min_commitment_window_sec=int(p.get("min_commitment_window_sec", 0) or 0),
                delivery_spec_md=str(p.get("delivery_spec_md") or ""),
                stage=str(p.get("stage", "STAGE1_PARSE0")),
                epoch_id=int(p.get("epoch_id", 1)),
                human_signed_at=p.get("human_signed_at"),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/schedule_snapshot":
            res = schedule_control_plane_snapshot(conn, max_concurrent_workers=p.get("max_concurrent_workers"))
            return {"ok": True, "data": res}
        if method == "control_plane/sync_pressure":
            res = sync_session_pressure(conn, node_id=str(p["node_id"]), pressure_tokens=int(p["pressure_tokens"]))
            return {"ok": True, "data": res}
        if method == "control_plane/record_human_stop":
            res = record_human_stop(conn, note=str(p.get("note", "HUMAN_UI_OR_CLI_STOP")))
            return {"ok": True, "data": res}
        if method == "control_plane/record_pending_handoff":
            res = record_pending_handoff(
                conn,
                node_id=str(p["node_id"]),
                mode=str(p.get("mode", "HANDOFF_70")),
                explorer_will_md=str(p.get("explorer_will_md", "")),
                reason=str(p.get("reason", "")),
            )
            return {"ok": True, "data": res}
        if method == "control_plane/stage_blind_sandbox":
            res = stage_blind_review_sandbox(conn, workspace_root=eff_ws, review_id=str(p["review_id"]))
            return {"ok": True, "data": res}
        if method == "control_plane/cleanup_blind_sandbox":
            res = cleanup_blind_review_sandbox(eff_ws, str(p["review_id"]))
            return {"ok": True, "data": res}
        if method == "control_plane/recover_heavy_jobs":
            res = recover_pending_heavy_jobs(conn, workspace_root=eff_ws)
            return {"ok": True, "data": {"recovered_jobs": res}}
        if method == "control_plane/fact_edge":
            with rw_immediate_tx(conn):
                record_fact_edge(
                    conn,
                    source_id=str(p.get("source_id") or p.get("src_id") or p.get("node_id") or p.get("session_id") or "host"),
                    target_id=str(p.get("target_id") or p.get("dst_id") or ""),
                    edge_type=str(p.get("edge_type") or "USED_TOOL"),
                    session_id=str(p.get("session_id") or ""),
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
        top_meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        res = dispatch_tool_call(
            t_name,
            t_args,
            workspace_root=str(top_meta.get("workspace_root", "") or ""),
            caller_role=str(top_meta.get("caller_role", "") or top_meta.get("role", "") or ""),
            session_id=str(top_meta.get("session_id", "") or ""),
        )
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


if __name__ == "__main__":
    raise SystemExit(serve_stdio())
