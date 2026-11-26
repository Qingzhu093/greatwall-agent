"""GreatWall Agent v0.3 全系统 10 角色窄 MCP 工具单一契约注册表（Single Source of Truth）。

职责边界：
- 集中声明 10 大标准角色与全部窄工具的唯一权威元数据（支持多角色共享只读工具，如 explorer 与 lineage_companion）；
- 自动派生 RBAC 白名单、只读拦截表、长耗时表、回合收尾表与 `control_plane/describe_contracts` 握手快照；
- 严禁反向 import `tools_*.py` 或 `control_plane/*`。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db_schema import (
    CORE_ERROR_CODES,
)
from .mcp_schema_docs import enrich_tool_definitions

CONTRACTS_SCHEMA_VERSION = "0.3.0"

CANONICAL_ROLES: tuple[str, ...] = (
    "gw_chief",
    "supervisory_committee",
    "works_engineer",
    "explorer",
    "lineage_companion",
    "logistics_coordinator",
    "external_surveyor",
    "library_chronicler",
    "library_verifier",
    "conference_chair",
)

ERROR_CODES: tuple[str, ...] = tuple(sorted(CORE_ERROR_CODES))


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


def _spec(
    *,
    name: str,
    roles: str | tuple[str, ...],
    access: str,
    description: str,
    input_schema: dict[str, Any],
    needs_workspace_root: bool = False,
    long_running: bool = False,
    concludes_turn: bool = False,
) -> dict[str, Any]:
    role_tuple = (roles,) if isinstance(roles, str) else tuple(roles)
    if not role_tuple:
        raise ValueError(f"工具 {name!r} 缺少授权角色")
    for r in role_tuple:
        if r not in CANONICAL_ROLES:
            raise ValueError(f"非法角色: {r!r}")
    if access not in ("read", "write"):
        raise ValueError(f"非法读写属性: {access!r}")
    return {
        "name": name,
        "role": role_tuple[0],
        "roles": role_tuple,
        "access": access,
        "needs_workspace_root": needs_workspace_root,
        "long_running": long_running,
        "concludes_turn": concludes_turn,
        "description": description,
        "inputSchema": input_schema,
    }


_RAW_TOOL_SPECS: tuple[dict[str, Any], ...] = (
    # ========================================================================
    # 1. gw_chief (Superagent, 5 个物理零代码/零终端窄工具)
    # ========================================================================
    _spec(
        name="chief_get_overview_snapshot",
        roles="gw_chief",
        access="read",
        description="[gw_chief] Inline & Spill 全院轻量总览：返回自主档位、各子题状态/口径/最新总览 ID、待拍板提案与活跃圆桌（内联下一跳关联 ID）。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, []),
    ),
    _spec(
        name="chief_trace_entity",
        roles="gw_chief",
        access="read",
        description="[gw_chief] 强外键 Chain of Recall 回忆链只读展开：按 entity_type/entity_id 多跳查账，强制内联下一跳外键 ID 与原始 session_id 直达锚点。",
        input_schema=_schema(
            {
                "entity_type": {"type": "string"},
                "entity_id": {"type": "string"},
            },
            ["entity_type", "entity_id"],
        ),
    ),
    _spec(
        name="chief_get_wave_digest",
        roles="gw_chief",
        access="read",
        description="[gw_chief] 读取指定子题或会议的波次圆桌纪要、最新 1500 字子题全局总览与宏观调整建议摘要。",
        input_schema=_schema(
            {
                "question_id": {"type": "string"},
                "conference_id": {"type": ["string", "null"], "default": None},
            },
            ["question_id"],
        ),
    ),
    _spec(
        name="chief_preview_impact",
        roles="gw_chief",
        access="read",
        description="[gw_chief] 零副作用推测预演：只读测算改题影响面、排雷视图查重或波次调整受影响分支清单，绝不改库、绝不开重型分支。",
        input_schema=_schema(
            {
                "preview_kind": {"type": "string"},
                "question_id": {"type": "string", "default": "ALL"},
                "query_text": {"type": "string", "default": ""},
                "target_id": {"type": ["string", "null"], "default": None},
            },
            ["preview_kind"],
        ),
    ),
    _spec(
        name="chief_propose_control_action",
        roles="gw_chief",
        access="write",
        description="[gw_chief] 唯一结构化提案提交口：将人类自然语言意图整理为 8 类宪章正门确认单写入 control_proposals，等待人类经原生卡片或 UI 显式落签。",
        input_schema=_schema(
            {
                "action_type": {"type": "string"},
                "target_id": {"type": "string"},
                "payload": {"type": "object", "default": {}},
                "rationale_md": {"type": "string"},
                "human_action_question": {"type": "string", "default": ""},
            },
            ["action_type", "target_id", "rationale_md"],
        ),
    ),
    # ========================================================================
    # 2. explorer (7) & 共享只读 Pull 工具 (explorer + lineage_companion)
    # ========================================================================
    _spec(
        name="run_isolated_eval",
        roles="explorer",
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
        name="get_living_survey",
        roles=("explorer", "lineage_companion"),
        access="read",
        description="[explorer(37%+)/lineage_companion(0%+)] 拉取指定子题最新《子题全局总览（<=1500字导览索引）》与高优悬赏缺口摘要。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "question_id": {"type": "string"},
            },
            ["node_id", "question_id"],
        ),
    ),
    _spec(
        name="query_library_catalog",
        roles=("explorer", "lineage_companion"),
        access="read",
        description="[explorer(0-37%仅外藏)/lineage_companion(0%全馆)] 二级目录卡 Pull（每条<=350字简介卡与排雷视图）。",
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
        roles=("explorer", "lineage_companion"),
        access="read",
        description="[explorer/lineage_companion] 三级完整原文 Pull，并静默写入参考性 FACT_LOG(READ) 边。",
        input_schema=_schema({"node_id": {"type": "string"}, "entry_id": {"type": "string"}}, ["node_id", "entry_id"]),
    ),
    _spec(
        name="request_literature_survey",
        roles="explorer",
        access="write",
        description="[explorer] 委托对外采编员 external_surveyor 检索外部文献/标准定理卡（脱敏查新单）。",
        input_schema=_schema(
            {"node_id": {"type": "string"}, "question_id": {"type": "string"}, "topic_query": {"type": "string"}, "reason": {"type": "string"}},
            ["node_id", "question_id", "topic_query", "reason"],
        ),
    ),
    _spec(
        name="read_lineage_graph",
        roles="explorer",
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
    _spec(
        name="handback_to_chief",
        roles="explorer",
        access="write",
        description="[explorer] 越界退回权：人类直连本子节点对话时若提出改题/停他枝/结题等跨分支或全局诉求，原样退回 gw-chief 收件箱，本节点绝不越权执行。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "question_id": {"type": "string"},
                "human_request_md": {"type": "string"},
                "reason": {"type": "string"},
            },
            ["node_id", "question_id", "human_request_md", "reason"],
        ),
    ),
    # ========================================================================
    # 3. lineage_companion (专属阶段工具 + 封存后圆桌发言工具)
    # ========================================================================
    _spec(
        name="get_companion_context",
        roles="lineage_companion",
        access="read",
        description="[lineage_companion] 获取 PRE_SPAWN / REFLECT_37 / HANDOFF_70 / CRASH_RECOVERY / CONFERENCE_PARTICIPANT 上下文。",
        input_schema=_schema(
            {"branch_id": {"type": "string"}, "node_id": {"type": "string"}, "mode": {"type": "string"}},
            ["branch_id", "node_id", "mode"],
        ),
    ),
    _spec(
        name="save_lineage_briefing",
        roles="lineage_companion",
        access="write",
        concludes_turn=True,
        description="[lineage_companion] 定额滚动重压缩写入谱系前情提要（总长 <= 2200 字）。",
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
        roles="lineage_companion",
        access="write",
        concludes_turn=True,
        description="[lineage_companion] 记录 <=2 轮(<=300字/轮) 37% 外部专家问诊并当场解锁 first_reflection_unlocked=1（无 eval_count 门槛）。",
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
        roles="lineage_companion",
        access="write",
        needs_workspace_root=True,
        concludes_turn=True,
        description="[lineage_companion] 70% 两步清醒交班独占落库、封存加锁（briefing_sealed_at）、可选附带结构化去向建议直落与独立局部引理拆交送审。",
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
                "recommended_triage": {"type": ["object", "null"], "default": None},
                "local_lemma_submissions": {"type": ["array", "null"], "items": {"type": "object"}, "default": None},
            },
            ["node_id", "branch_id", "question_id", "mechanism_summary", "evidence_grade", "column_a_facts_md", "column_b_hypothesis_md", "will_md", "obs_ids", "dead_ends", "is_empty_crash"],
        ),
    ),
    _spec(
        name="submit_conference_statement",
        roles="lineage_companion",
        access="write",
        concludes_turn=True,
        description="[lineage_companion(封存参会态)] 在宏观大外环圆桌第 1/2 轮提交点对点红蓝交锋发言（已封存节点零档案写权）。",
        input_schema=_schema(
            {
                "conference_id": {"type": "string"},
                "node_id": {"type": "string"},
                "round_no": {"type": "integer"},
                "statement_md": {"type": "string"},
                "target_node_ids": {"type": "array", "items": {"type": "string"}, "default": []},
            },
            ["conference_id", "node_id", "round_no", "statement_md"],
        ),
    ),
    # ========================================================================
    # 4. logistics_coordinator (4 个轻量工具，已删除原五车道工具)
    # ========================================================================
    _spec(
        name="get_logistics_dashboard",
        roles="logistics_coordinator",
        access="read",
        description="[logistics_coordinator] 纯只读 (<50ms) 拉取各题方法族谱占比、>50% 聚拢告警、待分诊页、悬赏缺口与槽位状态。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="register_method_family",
        roles="logistics_coordinator",
        access="write",
        description="[logistics_coordinator] 登记底层数学/物理正交思想学派。",
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
        roles="logistics_coordinator",
        access="write",
        needs_workspace_root=True,
        description="[logistics_coordinator] 对疑难/未归类 AWAITING_TRIAGE 节点执行六去向中观分诊与快照托管。",
        input_schema=_schema(
            {
                "node_id": {"type": "string"},
                "assigned_family_id": {"type": "string"},
                "triage_level": {"type": "string"},
                "action": {"type": "string"},
                "rationale": {"type": "string"},
                "barrier_proof_md": {"type": ["string", "null"], "default": None},
                "reopen_condition": {"type": ["string", "null"], "default": None},
                "blocking_gap_formal_statement": {"type": ["string", "null"], "default": None},
            },
            ["node_id", "assigned_family_id", "triage_level", "action", "rationale"],
        ),
    ),
    _spec(
        name="fork_branch",
        roles="logistics_coordinator",
        access="write",
        needs_workspace_root=True,
        description="[logistics_coordinator] 开启新探索分支（默认 2 班岗成长保护期、确定性 requires、WHERE branch_id != :self 查重）。",
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
    # ========================================================================
    # 5. external_surveyor (2 个，唯一联网，物理禁读任何院内成果)
    # ========================================================================
    _spec(
        name="get_survey_requests",
        roles="external_surveyor",
        access="read",
        description="[external_surveyor] 仅返回脱敏外部文献查新请求与已有外藏 [R###] 目录（物理零院内 L3/L2 泄露）。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="publish_external_literature_card",
        roles="external_surveyor",
        access="write",
        description="[external_surveyor] 发布带诚实阅读深度标注的外藏参考卡 [R###]（CARD_PUBLISHED）或无解诚实结案（UNAVAILABLE_REPORT）。",
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
    # ========================================================================
    # 6. library_chronicler (3 个，零外网零代码，专司 1500 字总览与 Stage 3 终稿)
    # ========================================================================
    _spec(
        name="get_chronicler_snapshot",
        roles="library_chronicler",
        access="read",
        description="[library_chronicler] 零外网只读拉取指定子题或全卷的硬账本、圆桌交锋纪要、已审 L3/L2、可用仪器与活跃悬赏缺口。",
        input_schema=_schema(
            {
                "question_id": {"type": "string", "default": "ALL"},
                "conference_id": {"type": ["string", "null"], "default": None},
            },
            ["question_id"],
        ),
    ),
    _spec(
        name="publish_living_survey",
        roles="library_chronicler",
        access="write",
        concludes_turn=True,
        description="[library_chronicler] 发布每道子题唯一的《子题全局总览与明确缺口导览》（硬限 <= 1500 字），若绑定圆桌会议则同事务切至 ADJUDICATING。",
        input_schema=_schema(
            {
                "question_id": {"type": "string"},
                "sec1_baseline_and_instruments_md": {"type": "string"},
                "sec2_l3_lemma_tree_md": {"type": "string"},
                "sec3_avoidance_radar_md": {"type": "string"},
                "sec4_explicit_gaps_md": {"type": "string"},
                "conference_id": {"type": ["string", "null"], "default": None},
                "trigger_reason": {"type": "string", "default": "WAVE_CONFERENCE"},
            },
            [
                "question_id",
                "sec1_baseline_and_instruments_md",
                "sec2_l3_lemma_tree_md",
                "sec3_avoidance_radar_md",
                "sec4_explicit_gaps_md",
            ],
        ),
    ),
    _spec(
        name="export_stage3_final_delivery",
        roles="library_chronicler",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        concludes_turn=True,
        description="[library_chronicler] 仅基于已审 L3 导出 Stage 3 五件套并原子锁定外部不可变冻结目录，交盲审官一步终核放行。",
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
    # ========================================================================
    # 7. conference_chair (3 个，零外网零代码，主持圆桌并读最新总览拍板)
    # ========================================================================
    _spec(
        name="get_conference_dossier",
        roles="conference_chair",
        access="read",
        description="[conference_chair] 只读拉取本波代码硬账本、参会分支已封存 A 栏、圆桌交锋记录与最新《子题全局总览》。",
        input_schema=_schema({"conference_id": {"type": "string"}}, ["conference_id"]),
    ),
    _spec(
        name="record_conference_minutes",
        roles="conference_chair",
        access="write",
        concludes_turn=True,
        description="[conference_chair] 第 2 拍落盘《圆桌交锋纪要与争议焦点》，推进会议至 SURVEY_REFRESHING 等待综述官刷新总览。",
        input_schema=_schema(
            {
                "conference_id": {"type": "string"},
                "minutes_md": {"type": "string"},
            },
            ["conference_id", "minutes_md"],
        ),
    ),
    _spec(
        name="submit_conference_verdict",
        roles="conference_chair",
        access="write",
        needs_workspace_root=True,
        concludes_turn=True,
        description="[conference_chair] 第 4 拍读取刚刷新的《子题全局总览》后签发 6 类宏观调整单（WAVE_CONFIRM 挂人类审批，AUTOPILOT 低风险直落）。",
        input_schema=_schema(
            {
                "conference_id": {"type": "string"},
                "actions": {"type": "array", "items": {"type": "object"}},
                "rationale_md": {"type": "string"},
            },
            ["conference_id", "actions", "rationale_md"],
        ),
    ),
    # ========================================================================
    # 8. library_verifier (5 个，零外网空白沙箱实跑，支持 PARTIAL_PASS 与一步终签)
    # ========================================================================
    _spec(
        name="get_blind_manuscript",
        roles="library_verifier",
        access="read",
        needs_workspace_root=True,
        description="[library_verifier] Stage 1 盲态拉取并挂载独立空白盲审沙箱（仅拷 A 栏、脱敏代码与 [Obs###]）。",
        input_schema=_schema({"review_id": {"type": "string"}}, ["review_id"]),
    ),
    _spec(
        name="submit_stage1_blind_ledger",
        roles="library_verifier",
        access="write",
        concludes_turn=True,
        description="[library_verifier] 永久锁定 Stage 1 证据账本，支持 PASS / PARTIAL_PASS（主结论击穿但局部引理严密进 Stage 2 降级收编）/ REVISE / REFUTED，并可同事务签发反作弊 EXPLOIT 工单。",
        input_schema=_schema(
            {
                "review_id": {"type": "string"},
                "question_id": {"type": "string"},
                "ledger_items": {"type": "array", "items": {"type": "object"}},
                "stage1_verdict": {"type": "string"},
                "revision_or_refutation_reason": {"type": ["string", "null"], "default": None},
                "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
                "exploit_ticket_payload": {"type": ["object", "null"], "default": None},
            },
            ["review_id", "question_id", "ledger_items", "stage1_verdict"],
        ),
    ),
    _spec(
        name="get_unblinded_manuscript_and_peers",
        roles="library_verifier",
        access="read",
        needs_workspace_root=True,
        description="[library_verifier] Stage 2 解盲横审（附带本题全部 OPEN 悬赏缺口列表与子题生效口径），或 Stage 3 冻结包终核 (STAGE3_FINAL_AUDIT:<delivery_id>)。",
        input_schema=_schema({"review_id": {"type": "string"}}, ["review_id"]),
    ),
    _spec(
        name="submit_stage2_unblind_verdict",
        roles="library_verifier",
        access="write",
        concludes_turn=True,
        description="[library_verifier] Stage 2 终判（达标与基线两步分离、ACCEPT_NARROWED 同事务收编 L3+L2、fulfilled_gap_ids 核销唤醒）及 Stage 3 不可变冻结目录一步核签结项。",
        input_schema=_schema(
            {
                "review_id": {"type": "string"},
                "final_verdict": {"type": "string"},
                "l3_entry_kind": {"type": ["string", "null"], "default": None},
                "goal_coverage": {"type": ["string", "null"], "default": None},
                "publish_tier": {"type": ["string", "null"], "default": None},
                "is_equivalent_reduction": {"type": "boolean", "default": False},
                "title": {"type": "string", "default": ""},
                "abstract_md": {"type": "string", "default": ""},
                "exact_verified_scope_md": {"type": ["string", "null"], "default": None},
                "exact_refuted_scope_md": {"type": ["string", "null"], "default": None},
                "narrowed_l2_title": {"type": ["string", "null"], "default": None},
                "revision_requests": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                "cross_draft_comparison_notes": {"type": "string", "default": ""},
                "fulfilled_gap_ids": {"type": ["array", "null"], "items": {"type": "string"}, "default": None},
                "exploit_ticket_payload": {"type": ["object", "null"], "default": None},
                "edge_type_overrides": {"type": ["object", "null"], "default": None},
            },
            ["review_id", "final_verdict"],
        ),
    ),
    _spec(
        name="propose_salvaged_lemma",
        roles="library_verifier",
        access="write",
        description="[library_verifier] 沉船遗产打捞：对从未送审而被休眠/已闭节点提取自包含局部引理建独立盲审单。",
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
    # ========================================================================
    # 9. works_engineer (6 个仪器科窄工具)
    # ========================================================================
    _spec(
        name="get_works_engineering_queue",
        roles="works_engineer",
        access="read",
        description="[works_engineer] 纯只读 (<50ms) 返回仪器清单、熔断状态、故障/痛点/反作弊/鉴别工单与 pending_revalidation 队列。",
        input_schema=_schema({"question_id": {"type": "string", "default": "ALL"}}, ["question_id"]),
    ),
    _spec(
        name="register_question_instrument",
        roles="works_engineer",
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
        roles="works_engineer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[works_engineer] 校准集 100% 通过即升版仪器，仅将本仪器旧观测入待重评队列（零误杀他题）。",
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
        roles="works_engineer",
        access="write",
        needs_workspace_root=True,
        long_running=True,
        description="[works_engineer] 读持久化 Stage A 产物按新版仪器诚实重评（保留旧收据，缺字段标 INCOMPATIBLE）。",
        input_schema=_schema({"obs_id": {"type": "string"}, "question_id": {"type": "string"}}, ["obs_id", "question_id"]),
    ),
    _spec(
        name="update_skill_ledger",
        roles="works_engineer",
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
        roles="works_engineer",
        access="write",
        description="[works_engineer] 显式结案工造司工单（RESOLVED / WONTFIX / DUPLICATE）。",
        input_schema=_schema(
            {"ticket_id": {"type": "string"}, "resolution": {"type": "string"}, "resolution_note": {"type": "string"}},
            ["ticket_id", "resolution", "resolution_note"],
        ),
    ),
    # ========================================================================
    # 10. supervisory_committee (4 个，聚焦 Stage 1 立项与口径歧义裁决)
    # ========================================================================
    _spec(
        name="get_supervisory_audit_snapshot",
        roles="supervisory_committee",
        access="read",
        description="[supervisory_committee] 纯只读 (<50ms) 获取 Parse 0 契约、各子题口径状态与合规告警快照。",
        input_schema=_schema({}, []),
    ),
    _spec(
        name="check_stage2_closure_gate",
        roles="supervisory_committee",
        access="read",
        description="[supervisory_committee] 校验当前各子题生效口径下的结项门禁（FULL / PARTIAL_ON_BUDGET / PARTIAL_ON_HUMAN_STOP）。",
        input_schema=_schema(
            {"mode": {"type": "string", "default": "FULL"}, "human_aborted": {"type": "boolean", "default": False}},
            ["mode", "human_aborted"],
        ),
    ),
    _spec(
        name="record_compliance_check",
        roles="supervisory_committee",
        access="write",
        needs_workspace_root=True,
        concludes_turn=True,
        description="[supervisory_committee] 写入 Stage 1 PARSE0_GATE 放行或中途 AMBIGUOUS_SPEC_ALERT 口径歧义告警（Stage 3 终签已收编给盲审官冻结包事务）。",
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
        roles="supervisory_committee",
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
    role: frozenset(s["name"] for s in TOOL_SPECS if role in s["roles"])
    for role in CANONICAL_ROLES
}

ROLE_TOOL_ORDER: dict[str, tuple[str, ...]] = {
    role: tuple(s["name"] for s in TOOL_SPECS if role in s["roles"])
    for role in CANONICAL_ROLES
}

ALL_TOOL_NAMES: frozenset[str] = frozenset(s["name"] for s in TOOL_SPECS)
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
