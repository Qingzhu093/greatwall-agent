"""长城 V6-Up (v3.0) 全系统 32 个窄 MCP 工具单一契约注册表（Single Source of Truth）。

职责边界：
- 集中声明 7 大标准角色与 32 个窄工具的唯一权威元数据（角色归属、读写属性、长超时、Turn 收尾、
  workspace_root 注入需求与完整 JSON Schema）；
- 自动派生 RBAC 白名单、只读拦截表、长超时表与 `control_plane/describe_contracts` 握手快照；
- 严禁反向 import `tools_*.py` 或 `control_plane/*`（仅依赖 `db_schema` 与 `mcp_schema_docs`）。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db_schema import (
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_EXECUTION,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    ERR_STORAGE,
)
from .mcp_schema_docs import enrich_tool_definitions

CONTRACTS_SCHEMA_VERSION = "3.0.0"

CANONICAL_ROLES: tuple[str, ...] = (
    "explorer",
    "lineage_companion",
    "logistics_coordinator",
    "library_surveyor",
    "library_verifier",
    "works_engineer",
    "supervisory_committee",
)

ERROR_CODES: tuple[str, ...] = (
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_EXECUTION,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    ERR_STORAGE,
)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


def _spec(
    *,
    name: str,
    role: str,
    access: str,
    description: str,
    input_schema: dict[str, Any],
    needs_workspace_root: bool = False,
    long_running: bool = False,
    concludes_turn: bool = False,
) -> dict[str, Any]:
    if role not in CANONICAL_ROLES:
        raise ValueError(f"非法角色: {role!r}")
    if access not in ("read", "write"):
        raise ValueError(f"非法读写属性: {access!r}")
    return {
        "name": name,
        "role": role,
        "access": access,
        "needs_workspace_root": needs_workspace_root,
        "long_running": long_running,
        "concludes_turn": concludes_turn,
        "description": description,
        "inputSchema": input_schema,
    }


_RAW_TOOL_SPECS: tuple[dict[str, Any], ...] = (
    # 1. explorer (5)
    _spec(
        name="run_isolated_eval",
        role="explorer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[explorer] 统一三档仪器隔离调用：probe（诊断不记 Obs）/ official（正式凭证）/ heavy（冻结快照异步幂等取回）。",
        input_schema=_schema(
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
    ),
    _spec(
        name="query_library_catalog",
        role="explorer",
        access="read",
        description="[explorer] 一级目录 Pull（0-37% 仅返回外藏 [R###]，37% 解锁后全馆两翼开放）。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "question_id": {"type": "string"},
                "scope": {"type": "string"},
                "keyword": {"type": "string", "default": ""},
            },
            ["node_id", "question_id", "scope", "keyword"],
        ),
    ),
    _spec(
        name="get_library_entry",
        role="explorer",
        access="read",
        description="[explorer] 二级详卡 Pull 并静默写入参考性 FACT_LOG(READ) 边。",
        input_schema=_schema({"node_id": {"type": "string"}, "entry_id": {"type": "string"}}, ["node_id", "entry_id"]),
    ),
    _spec(
        name="request_literature_survey",
        role="explorer",
        access="write",
        description="[explorer] 委托图书馆外藏采编馆员补查外部文献/标准定理卡。",
        input_schema=_schema(
            {"node_id": {"type": "string"}, "question_id": {"type": "string"}, "topic_query": {"type": "string"}, "reason": {"type": "string"}},
            ["node_id", "question_id", "topic_query", "reason"],
        ),
    ),
    _spec(
        name="read_lineage_graph",
        role="explorer",
        access="read",
        description="[explorer] 37% 解锁后翻阅本门派私有谱系 DAG 或 lineage_dead_ends 全表（物理隔离他脉）。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "branch_id": {"type": "string"},
                "target_node_id": {"type": ["string", "null"], "default": None},
                "view": {"type": "string", "default": "nodes"},
                "saved_query_name": {"type": ["string", "null"], "default": None},
            },
            ["node_id", "branch_id"],
        ),
    ),
    # 2. lineage_companion (4)
    _spec(
        name="get_companion_context",
        role="lineage_companion",
        access="read",
        description="[lineage_companion] 获取 PRE_SPAWN / REFLECT_37 / HANDOFF_70 / CRASH_RECOVERY 阶段隔离上下文。",
        input_schema=_schema(
            {"branch_id": {"type": "string"}, "node_id": {"type": "string"}, "mode": {"type": "string"}},
            ["branch_id", "node_id", "mode"],
        ),
    ),
    _spec(
        name="save_lineage_briefing",
        role="lineage_companion",
        access="write",
        concludes_turn=True,
        description="[lineage_companion] 按 Rewrite_<=2200 定额滚动重压缩写入谱系状态看板（唯一硬限总长 <= 2200 字）。",
        input_schema=_schema(
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
    ),
    _spec(
        name="record_reflection_and_unlock_pull",
        role="lineage_companion",
        access="write",
        concludes_turn=True,
        description="[lineage_companion] 记录 <=2 轮(<=300字/轮) 37% 情报型元反思并当场解锁 first_reflection_unlocked=1（无 eval_count 门槛）。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "selected_categories": {"type": "array", "items": {"type": "string"}},
                "holiday_prompt_id": {"type": "integer"},
                "turns": {"type": "array", "items": {"type": "object"}},
                "verdict_3state": {"type": "string"},
            },
            ["node_id", "selected_categories", "holiday_prompt_id", "turns", "verdict_3state"],
        ),
    ),
    _spec(
        name="submit_node_handoff",
        role="lineage_companion",
        access="write",
        needs_workspace_root=True,
        concludes_turn=True,
        description="[lineage_companion] 独占单写谱系 DAG 页与只追加 lineage_dead_ends 表，并置节点 AWAITING_TRIAGE。",
        input_schema=_schema(
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
    ),
    # 3. logistics_coordinator (5)
    _spec(
        name="get_logistics_dashboard",
        role="logistics_coordinator",
        access="read",
        description="[logistics_coordinator] 纯只读 (<50ms) 拉取各题方法族谱占比、>50% 聚拢告警、待分诊页与 Ready Queue。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="register_method_family",
        role="logistics_coordinator",
        access="write",
        description="[logistics_coordinator] 按需登记底层数学/物理思想学派（不强卡固定条数）。",
        input_schema=_schema(
            {
                "question_id": {"type": "string"},
                "family_id": {"type": "string"},
                "mechanism_signature": {"type": "string"},
                "orthogonal_contrast": {"type": "string"},
            },
            ["question_id", "family_id", "mechanism_signature", "orthogonal_contrast"],
        ),
    ),
    _spec(
        name="triage_node",
        role="logistics_coordinator",
        access="write",
        needs_workspace_root=True,
        description="[logistics_coordinator] 对 AWAITING_TRIAGE 节点归类学派并执行四级认知分诊与快照托管。",
        input_schema=_schema(
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
    ),
    _spec(
        name="fork_branch",
        role="logistics_coordinator",
        access="write",
        needs_workspace_root=True,
        description="[logistics_coordinator] 开启新探索分支（分支级确定性 requires、WHERE branch_id != :self 查重、双 L3 授粉门槛）。",
        input_schema=_schema(
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
    ),
    _spec(
        name="dispatch_stagnation_five_lanes",
        role="logistics_coordinator",
        access="write",
        description="[logistics_coordinator] 停滞看门狗或 >50% 聚拢告警触发时执行五互斥车道算力重排。",
        input_schema=_schema(
            {"question_id": {"type": "string"}, "lane_assignments": {"type": "array", "items": {"type": "object"}}},
            ["question_id", "lane_assignments"],
        ),
    ),
    # 4. library_surveyor (3)
    _spec(
        name="get_survey_requests",
        role="library_surveyor",
        access="read",
        description="[library_surveyor] 获取 Stage 1-2 查新委托队列及 Stage 3 全量已审 L3/L2/[R###] 综合数据包。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="publish_external_literature_card",
        role="library_surveyor",
        access="write",
        description="[library_surveyor] 将外部文献/定理卡入库左翼外藏 [R###]（outcome='CARD_PUBLISHED'），或对无解/不合规查新请求做无卡结案（outcome='UNAVAILABLE_REPORT'，不插伪卡）。",
        input_schema=_schema(
            {
                "outcome": {"type": "string", "default": "CARD_PUBLISHED"},
                "ref_id": {"type": ["string", "null"], "default": None},
                "question_id": {"type": "string"},
                "title": {"type": ["string", "null"], "default": None},
                "abstract_md": {"type": ["string", "null"], "default": None},
                "exact_preconditions_md": {"type": ["string", "null"], "default": None},
                "formulas_or_operators_md": {"type": ["string", "null"], "default": None},
                "read_depth": {"type": ["string", "null"], "default": None},
                "support_scope": {"type": ["string", "null"], "default": None},
                "source_citation": {"type": ["string", "null"], "default": None},
                "fulfilled_request_ids": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                "unavailable_reason_md": {"type": ["string", "null"], "default": None},
            },
            ["question_id"],
        ),
    ),
    _spec(
        name="export_stage3_final_delivery",
        role="library_surveyor",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        concludes_turn=True,
        description="[library_surveyor] 导出 Stage 3 五件套（生成 delivery_id/sha256，置 DELIVERY_EXPORTED 等待两步联合终核）。",
        input_schema=_schema(
            {
                "delivery_mode": {"type": "string"},
                "formal_paper_md": {"type": "string"},
                "selected_l3_ids_by_question": {"type": "object"},
                "remaining_gaps_by_question": {"type": "object"},
                "reproduction_candidate_nodes": {"type": "array", "items": {"type": "string"}},
            },
            ["delivery_mode", "formal_paper_md", "selected_l3_ids_by_question", "remaining_gaps_by_question", "reproduction_candidate_nodes"],
        ),
    ),
    # 5. library_verifier (5)
    _spec(
        name="get_blind_manuscript",
        role="library_verifier",
        access="read",
        needs_workspace_root=True,
        description="[library_verifier] Stage 1 盲态拉取并挂载独立空白盲审沙箱（仅拷 A 栏、脱敏代码与 [Obs###]）。",
        input_schema=_schema({"review_id": {"type": "string"}}, ["review_id"]),
    ),
    _spec(
        name="submit_stage1_blind_ledger",
        role="library_verifier",
        access="write",
        concludes_turn=True,
        description="[library_verifier] 永久锁定 Stage 1 不可逆 Evidence Ledger，按 PASS / REVISE / REFUTED 精准分流。",
        input_schema=_schema(
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
    ),
    _spec(
        name="get_unblinded_manuscript_and_peers",
        role="library_verifier",
        access="read",
        needs_workspace_root=True,
        description="[library_verifier] Stage 2 解盲横审拉取，或 Stage 3 终核模式 (STAGE3_FINAL_AUDIT:<delivery_id>) 五件套核查。",
        input_schema=_schema({"review_id": {"type": "string"}}, ["review_id"]),
    ),
    _spec(
        name="submit_stage2_unblind_verdict",
        role="library_verifier",
        access="write",
        concludes_turn=True,
        description="[library_verifier] Stage 2 三态终判（ACCEPT* 入 L3 / REVISE 返工 / REFUTED 入 L2）及 Stage 3 终核版本落签。",
        input_schema=_schema(
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
    ),
    _spec(
        name="propose_salvaged_lemma",
        role="library_verifier",
        access="write",
        description="[library_verifier] Auditor 对已闭/阻塞节点打捞自包含局部引理（严禁抢断 ACTIVE_REVISING 返工分支）。",
        input_schema=_schema(
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
    ),
    # 6. works_engineer (6)
    _spec(
        name="get_works_engineering_queue",
        role="works_engineer",
        access="read",
        description="[works_engineer] 纯只读 (<50ms) 返回仪器清单、熔断状态、故障/痛点工单与 pending_revalidation 待重评队列。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="register_question_instrument",
        role="works_engineer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[works_engineer] 注册新科研仪器（VERDICT 强跑独立校准集 100% 匹配自声明预期；PROBE/ENV 可免校准集）。",
        input_schema=_schema(
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
    ),
    _spec(
        name="upgrade_instrument_with_calibration",
        role="works_engineer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[works_engineer] 校准集 100% 通过即升版仪器（支持可选更新 artifact_schema 与 default_spec），仅选择性将本仪器旧观测入待重评队列（零误杀他题）。",
        input_schema=_schema(
            {
                "question_id": {"type": "string"},
                "instrument_id": {"type": "string"},
                "new_instrument_rel_path": {"type": "string"},
                "calibration_suite_rel_path": {"type": "string"},
                "artifact_schema": {"type": ["string", "null"], "default": None},
                "default_spec": {"type": ["object", "null"], "default": None},
            },
            ["question_id", "instrument_id", "new_instrument_rel_path", "calibration_suite_rel_path"],
        ),
    ),
    _spec(
        name="recompute_stage_b_only",
        role="works_engineer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[works_engineer] 读持久化 Stage A 产物按新版仪器诚实重评（保留旧收据，成功生新收据，缺字段标 INCOMPATIBLE）。",
        input_schema=_schema({"obs_id": {"type": "string"}, "question_id": {"type": "string"}}, ["obs_id", "question_id"]),
    ),
    _spec(
        name="update_skill_ledger",
        role="works_engineer",
        access="write",
        needs_workspace_root=True,
        description="[works_engineer] No-File 校验后向工作区隔离 SKILL_LEDGER.json 登记共享工具/探针。",
        input_schema=_schema(
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
    ),
    _spec(
        name="resolve_works_ticket",
        role="works_engineer",
        access="write",
        description="[works_engineer] 显式结案工造司工单（RESOLVED / WONTFIX / DUPLICATE），防止 OPEN 工单无限自旋唤醒。",
        input_schema=_schema(
            {"ticket_id": {"type": "string"}, "resolution": {"type": "string"}, "resolution_note": {"type": "string"}},
            ["ticket_id", "resolution", "resolution_note"],
        ),
    ),
    # 7. supervisory_committee (4)
    _spec(
        name="get_supervisory_audit_snapshot",
        role="supervisory_committee",
        access="read",
        description="[supervisory_committee] 纯只读 (<50ms) 获取 Parse 0、仪器熔断、口径红灯、聚拢告警与两步终局审计快照。",
        input_schema=_schema({}, []),
    ),
    _spec(
        name="check_stage2_closure_gate",
        role="supervisory_committee",
        access="read",
        description="[supervisory_committee] 校验 CDC 双段终局门禁（FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP）。",
        input_schema=_schema(
            {"mode": {"type": "string", "default": "FULL"}, "human_aborted": {"type": "boolean", "default": False}},
            ["mode", "human_aborted"],
        ),
    ),
    _spec(
        name="record_compliance_check",
        role="supervisory_committee",
        access="write",
        needs_workspace_root=True,
        concludes_turn=True,
        description="[supervisory_committee] 写入 SQLite 合规与红灯告警（零 .md 落盘；CLOSURE_GATE 强校验终核版本绑定）。",
        input_schema=_schema(
            {
                "stage": {"type": "string"},
                "status": {"type": "string"},
                "blocking_questions": {"type": "array", "items": {"type": "string"}, "default": []},
                "notes": {"type": "string", "default": ""},
            },
            ["stage", "status", "blocking_questions", "notes"],
        ),
    ),
    _spec(
        name="register_saved_graph_query",
        role="supervisory_committee",
        access="write",
        description="[supervisory_committee] 校验并注册单条只读 SELECT 共享图查询视图。",
        input_schema=_schema(
            {"query_name": {"type": "string"}, "description": {"type": "string"}, "sql_select": {"type": "string"}},
            ["query_name", "description", "sql_select"],
        ),
    ),
)

TOOL_SPECS: tuple[dict[str, Any], ...] = tuple(
    {
        **raw,
        "inputSchema": enriched["inputSchema"],
    }
    for raw, enriched in zip(
        _RAW_TOOL_SPECS,
        enrich_tool_definitions(
            [{"name": s["name"], "description": s["description"], "inputSchema": s["inputSchema"]} for s in _RAW_TOOL_SPECS]
        ),
        strict=True,
    )
)

TOOL_SPEC_BY_NAME: dict[str, dict[str, Any]] = {s["name"]: s for s in TOOL_SPECS}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {"name": s["name"], "description": s["description"], "inputSchema": deepcopy(s["inputSchema"])}
    for s in TOOL_SPECS
]

ALLOWED_TOOLS_BY_ROLE: dict[str, frozenset[str]] = {
    role: frozenset(s["name"] for s in TOOL_SPECS if s["role"] == role)
    for role in CANONICAL_ROLES
}

ROLE_TOOL_ORDER: dict[str, tuple[str, ...]] = {
    role: tuple(s["name"] for s in TOOL_SPECS if s["role"] == role)
    for role in CANONICAL_ROLES
}

ALL_TOOL_NAMES: frozenset[str] = frozenset(s["name"] for s in TOOL_SPECS)
# 向后兼容别名（含 resolve_works_ticket 共 32 个窄工具）
ALL_31_TOOL_NAMES: frozenset[str] = ALL_TOOL_NAMES

READONLY_BLOCKED_MCP_TOOLS: frozenset[str] = frozenset(
    s["name"] for s in TOOL_SPECS if s["access"] == "write"
)
LONG_RUNNING_MCP_TOOLS: frozenset[str] = frozenset(
    s["name"] for s in TOOL_SPECS if s["long_running"]
)
TURN_CONCLUDING_TOOLS: frozenset[str] = frozenset(
    s["name"] for s in TOOL_SPECS if s["concludes_turn"]
)


def export_contracts_snapshot() -> dict[str, Any]:
    """导出机器可读的单源契约快照，供 Node 插件握手校验与静态架构门禁使用。"""
    return {
        "schema_version": CONTRACTS_SCHEMA_VERSION,
        "tool_count": len(TOOL_SPECS),
        "canonical_roles": list(CANONICAL_ROLES),
        "role_mcp_tools": {role: list(ROLE_TOOL_ORDER[role]) for role in CANONICAL_ROLES},
        "readonly_blocked_mcp_tools": sorted(READONLY_BLOCKED_MCP_TOOLS),
        "long_running_mcp_tools": sorted(LONG_RUNNING_MCP_TOOLS),
        "turn_concluding_tools": sorted(TURN_CONCLUDING_TOOLS),
        "error_codes": list(ERROR_CODES),
    }
