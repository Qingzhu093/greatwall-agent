"""全量 31 个 MCP 工具 JSON Schema 字段说明、枚举约束与结构补全模块。

将各工具的中文参数说明、共享通用字段规范及从 `db_schema.py` 派生的枚举列表统一注入
`TOOL_DEFINITIONS`，避免模型因 Schema 缺失 `enum`/`description`/`maxLength` 产生幻觉传参。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from mcp_server.db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_READ_DEPTHS,
    ALLOWED_SUPPORT_SCOPES,
)

# 跨工具复用的通用字段默认说明
_COMMON_PROP_DESCRIPTIONS: dict[str, str] = {
    "node_id": "探索节点唯一 ID（例如 node_q1_01）。",
    "branch_id": "探索分支唯一 ID（例如 br_q1_fam01_01）。",
    "question_id": "所属子题编号（例如 Q1、Q2，或全卷查询时的 ALL）。",
    "review_id": "盲审工单 ID（例如 rev_001，或 Stage 3 比较器模式 STAGE3_COMPARATOR）。",
    "obs_id": "观测实测记录 ID（例如 Obs001）。",
    "title": "条目标题（需概括核心物理/数学机制与适用结论）。",
}

# 各工具专属属性覆盖补丁（按工具名索引）
_TOOL_PROP_PATCHES: dict[str, dict[str, dict[str, Any]]] = {
    "run_isolated_eval": {
        "candidate_rel_path": {"description": "待测候选 Python 脚本相对工作区路径（例如 scripts/q1_solver.py）。"},
        "linguistic_prediction": {
            "minLength": 5,
            "description": "执行前必须写明的可证伪自然语言事前预测（至少 5 字，严禁空洞占位）。",
        },
        "declared_refs": {
            "description": "本实验显式依赖的外部/内部条目引用 ID 数组（如 [\"R001\", \"L3-001\"]，无引用传 []）。",
        },
    },
    "query_library_catalog": {
        "scope": {
            "enum": ["EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "ALL"],
            "description": "检索翼范围：0-37% 未解锁前仅能使用 EXTERNAL_R；37% 解锁后可使用 EXTERNAL_R | INTERNAL_L3 | INTERNAL_L2 | ALL。",
        },
        "keyword": {"description": "FTS5 关键词过滤词（支持中英文术语；留空 \"\" 返回该范围全部可用卡片）。"},
    },
    "get_library_entry": {
        "entry_id": {"description": "欲精读的文献或引理卡片 ID（如 R001、L3-001、L2-001），调用自动记录 READ 边。"},
    },
    "request_literature_survey": {
        "topic_query": {"description": "委托采编检索的具体数学物理机制、定理名称或关键词。"},
        "reason": {"description": "说明当前建模瓶颈及需要该文献/定理卡片解决的具体问题。"},
    },
    "read_lineage_graph": {
        "target_node_id": {"description": "可选：指定只查看某一历史谱系节点详情（不传或 null 返回当前门派全局视图）。"},
        "saved_query_name": {"description": "可选：监察委预注册的只读 SQL 视图名称（受租户盲审表隔离保护）。"},
    },
    "get_companion_context": {
        "mode": {
            "enum": ["PRE_SPAWN", "REFLECT_37", "HANDOFF_70"],
            "description": "伴随上下文模式：PRE_SPAWN（行前看板）| REFLECT_37（37% 触发元反思题包）| HANDOFF_70（70% 或崩溃打捞交接包）。",
        },
    },
    "save_lineage_briefing": {
        "sec1_mechanism": {"description": "第1段：当前假设的核心物理/数学机制（与其余4段合计总长 <= 2200 字）。"},
        "sec2_verified_baseline": {"description": "第2段：已实测确认的基线现象、[Obs###] 与边界范围。"},
        "sec3_bottleneck": {"description": "第3段：当前尚未突破的数学或数值瓶颈。"},
        "sec4_dead_ends": {"description": "第4段：已证伪路线与 L2 失败边界，防止后继重复踩坑。"},
        "sec5_immediate_will": {"description": "第5段：下一小步立即待验证的可执行改动遗愿。"},
    },
    "record_reflection_and_unlock_pull": {
        "selected_categories": {
            "description": "选题分类列表，必须包含第 7 类 \"Attractor Tasks\"。",
        },
        "holiday_prompt_id": {
            "minimum": 1,
            "maximum": 28,
            "description": "随机抽中的夜科学反思题编号（1–28 整数；29 号专供监察委）。",
        },
        "turns": {
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "提问内容。"},
                    "answer": {"type": "string", "description": "探索者基于实测的反思回答（<=300 字）。"},
                },
                "required": ["question", "answer"],
            },
            "description": "1 至 2 轮精简问答列表，每轮均须含 non-empty question 与 answer。",
        },
        "verdict_3state": {
            "enum": ["SUFFICIENT_EVIDENCE", "MINIMAL_EXPERIMENT_NEXT", "NEED_CONTROL_GROUP"],
            "description": "元反思三态结论枚举：SUFFICIENT_EVIDENCE | MINIMAL_EXPERIMENT_NEXT | NEED_CONTROL_GROUP。",
        },
    },
    "submit_node_handoff": {
        "column_a_facts_md": {"description": "A 栏（严格实证事实）：仅记录可回溯至 [Obs###] 与源码路径的实测数据与现象。"},
        "column_b_hypothesis_md": {"description": "B 栏（机制假说）：与 A 栏严格分离的理论推演与因果假说。"},
        "will_md": {"description": "接力遗愿：为下一代或后勤分诊留下的清晰后续实验建议。"},
        "obs_ids": {"description": "绑定的真实 [Obs###] ID 列表；正常交接至少 1 条（零实测崩溃传 [] 且设 is_zero_eval_crash=true）。"},
        "candidate_rel_path": {"description": "可选：交接关联的最新候选脚本相对路径（无则 null）。"},
        "is_zero_eval_crash": {"description": "仅当探索者未跑通任何一次 run_isolated_eval 即异常崩溃打捞时设为 true。"},
        "tool_pain_point": {"description": "可选：若发现验证钩子缺陷或基线痛点，简要说明以便派工造司修复。"},
    },
    "get_logistics_dashboard": {
        "question_id": {"description": "子题编号（如 Q1）或 ALL（查看全卷子题依赖、学派、待分诊节点及停滞计数）。"},
    },
    "register_method_family": {
        "family_id": {"description": "方法学派唯一英文标识（如 fam_q1_spectral）。"},
        "mechanism_signature": {"description": "该学派的核心机理与数学建模路线签名。"},
        "orthogonal_contrast": {"description": "说明本学派与已有学派在机制或近似假设上的正交差异。"},
        "depends_on_questions": {"description": "可选：前置依赖子题编号列表（如 [\"Q1\"]）；前置子题未获至少 1 条 L3 前不可派生探索。"},
    },
    "triage_node": {
        "triage_level": {
            "enum": ["ROUTINE_CONTINUATION", "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4A", "LEVEL_4B"],
            "description": "分诊级别枚举：ROUTINE_CONTINUATION | LEVEL_1(送盲审) | LEVEL_2(局部修补) | LEVEL_3(跨脉派生) | LEVEL_4A(死路封存L2) | LEVEL_4B(条件暂停)。",
        },
        "action": {
            "enum": ["CONTINUE", "SUBMIT_BLIND_REVIEW", "INPLACE_REPAIR", "SPAWN_PROTECTED", "SEAL_BARRIER", "PAUSE_TO_READY_QUEUE"],
            "description": "裁决动作枚举：CONTINUE | SUBMIT_BLIND_REVIEW | INPLACE_REPAIR | SPAWN_PROTECTED | SEAL_BARRIER | PAUSE_TO_READY_QUEUE。",
        },
        "rationale": {"description": "结合实测 rank_score、依赖与停滞计数给出的清晰裁决理由（必填）。"},
        "barrier_proof_md": {"description": "当 triage_level=LEVEL_4A / SEAL_BARRIER 时必填（>=15字），写明被证伪物理/数学边界。"},
        "reopen_condition": {"description": "当 triage_level=LEVEL_4B / PAUSE_TO_READY_QUEUE 时必填，说明重入就绪队列的解锁条件。"},
    },
    "fork_branch": {
        "parent_node_id": {"description": "父节点 ID（Stage 1 初始开启首枝探索分支时传 null）。"},
        "fork_mode": {
            "enum": ["orthogonal", "lateral", "cross_pollinate"],
            "description": "派生模式枚举：orthogonal（首脉或正交新学派）| lateral（同脉横向变体）| cross_pollinate（跨子题借用 L3 引理）。",
        },
        "target_family_id": {"description": "目标学派 family_id（须已通过 register_method_family 在该子题登记）。"},
        "source_l3_id": {"description": "仅 fork_mode=\"cross_pollinate\" 时必填：借用的已验证 L3 引理 ID（如 L3-001）。"},
    },
    "dispatch_stagnation_five_lanes": {
        "lane_assignments": {
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "branch_id": {"type": "string", "description": "待重排分支 ID。"},
                    "lane": {"type": "string", "description": "五车道类型（如 ORTHOGONAL_EXPLORE / ABLATION / LITERATURE_SURVEY / REPAIR / ARCHIVE）。"},
                    "directive": {"type": "string", "description": "该车道下一步指令。"},
                },
                "required": ["branch_id", "lane"],
            },
            "description": "停滞重排五车道分配数组，每项须指定不重复的 branch_id 与 lane。",
        },
    },
    "get_survey_requests": {
        "question_id": {"description": "过滤子题 ID（如 Q1）或 ALL（在 Stage 3 时同时返回全卷 L3/L2/R 综合包）。"},
    },
    "publish_external_literature_card": {
        "ref_id": {"description": "外藏卡片唯一编号（规范格式：R001、R002...；重复 ref_id 将拒绝或需递增编号）。"},
        "question_id": {"description": "主要关联的子题 ID（如 Q1、Q2 或 ALL）。"},
        "abstract_md": {
            "minLength": 60,
            "maxLength": 1500,
            "description": "独立高密度摘要（必须 60–1500 字符；推荐 120–500 字符，严禁 [:120] 伪摘要与冗余长篇推导）。",
        },
        "exact_preconditions_md": {"description": "严格适用前提、物理边界或数学假设条件列表（必填，不能为空）。"},
        "formulas_or_operators_md": {"description": "核心方程、定理表达式或算子定义（离线标准定理亦须公式完整）。"},
        "read_depth": {
            "enum": sorted(ALLOWED_READ_DEPTHS),
            "description": "诚实阅读深度英文枚举：full_text（全文/完备定理推导）| specified_sections（指定章节）| abstract_only（仅摘要）。",
        },
        "support_scope": {
            "enum": sorted(ALLOWED_SUPPORT_SCOPES),
            "description": (
                "支持度分类英文枚举（严禁填写中文解释或自定义词）：常用 "
                "DIRECT_PROOF_OR_EXACT_MEASUREMENT | CONDITIONALLY_VERIFIED | "
                "NEGATIVE_REFUTATION | HEURISTIC_CORRELATION | BACKGROUND_REFERENCE。"
            ),
        },
        "source_citation": {"description": "标准出处引用（文献作者/书名/章节/DOI 或公认标准教材定理名称）。"},
        "fulfilled_request_ids": {
            "description": "可选：本次精准核销的 request_id 数组（来自 get_survey_requests）；Stage 1 主动建卡或无指定工单时传 null 或 []。",
        },
    },
    "export_stage3_final_delivery": {
        "formal_paper_md": {
            "minLength": 50,
            "description": "正式学术论文全文 Markdown（需结构完整、数据对齐 [Obs###] 与 L3，严禁空壳成文）。",
        },
        "selected_l3_ids_by_question": {"description": "各子题最终入选的 L3_VERIFIED 映射字典，例如 {\"Q1\": [\"L3-001\"], \"Q2\": [\"L3-002\"]}。"},
        "reproduction_candidate_nodes": {"description": "各子题代表性可复现探索节点 ID 列表（如 [\"node_q1_01\"]）。"},
    },
    "submit_stage1_blind_ledger": {
        "ledger_items": {
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "待核验核心宣称。"},
                    "evidence_location_and_quote": {"type": "string", "description": "对应 [Obs###] / 代码 / 引用原文定位及精确摘录。"},
                    "verified": {"type": "boolean", "description": "是否被证据真实支撑。"},
                },
                "required": ["claim", "evidence_location_and_quote"],
            },
            "description": "Stage 1 不可逆独立证据核查账本（非空数组）。",
        },
        "stage1_verdict": {
            "enum": ["PASS", "REJECT"],
            "description": "Stage 1 盲态初判英文枚举：PASS | REJECT（落库后数据库触发器锁定不可改）。",
        },
        "reject_failure_reason": {"description": "当 stage1_verdict=\"REJECT\" 时必填：明确拒稿根本原因。"},
        "exact_refuted_scope_md": {"description": "当 stage1_verdict=\"REJECT\" 时必填：准确界定被证伪或未支撑的边界范围。"},
    },
    "submit_stage2_unblind_verdict": {
        "final_verdict": {
            "enum": ["PASS", "PASS_WITH_NARROWED_SCOPE", "REJECT"],
            "description": "Stage 2 终审英文枚举：PASS | PASS_WITH_NARROWED_SCOPE | REJECT。",
        },
        "abstract_md": {
            "minLength": 40,
            "description": "独立高密度终审摘要（必须 >= 40 字符，严禁空洞占位）。",
        },
        "exact_verified_scope_md": {"description": "PASS 或 PASS_WITH_NARROWED_SCOPE 时必填：明确已证实有效边界。"},
        "exact_refuted_scope_md": {"description": "REJECT（或窄化剔除场景）时必填：明确被否定/未达标边界。"},
        "cross_draft_comparison_notes": {"description": "跨稿件/同题其他候选对比评审说明。"},
        "cross_pollinate_nomination": {"description": "可选：推荐用于其他子题交叉授粉的结构化说明对象或 null。"},
        "edge_type_overrides": {
            "description": f"可选：按 ref_id 覆盖宣称引用边类型字典，合法值为 {sorted(ALLOWED_CLAIMED_EDGE_TYPES)}；无覆盖传 null。",
        },
    },
    "propose_salvaged_lemma": {
        "source_node_id": {"description": "被提议局部规律打捞的源探索节点 ID。"},
        "abstract_md": {"description": "打捞引理的独立摘要（阐述局部机制及有效范围）。"},
        "column_a_self_contained_proof_md": {"description": "A 栏自洽实证证明/数值规律（需独立可核查）。"},
        "column_b_scope_notes_md": {"description": "B 栏精确边界与失效区说明（不可越界推广）。"},
        "bound_obs_ids": {"minItems": 1, "description": "必须绑定至少 1 条真实存在的 [Obs###] ID 列表。"},
    },
    "get_works_engineering_queue": {
        "question_id": {"description": "过滤子题 ID 或 ALL（查看未处理的 tool_pain_point 与待局部重评队列）。"},
    },
    "register_question_domain_hook": {
        "hook_rel_path": {"description": "验证钩子相对工作区路径（如 evaluators/hook_q1.py），需提供 evaluate_candidate(art, spec)。"},
        "baseline_rel_path": {"description": "对应基准真值脚本相对路径（如 baselines/Q1/baseline.py）。"},
        "fidelity_max_error_pct": {"description": "与基准脚本对比允许的最大保真度相对误差百分比（非负浮点数，如 1.0）。"},
        "plugin_protocol_version": {"description": "钩子协议版本字符串，默认 v1。"},
        "public_input_sample": {"description": "可选：向探索者公开的标准输入样例 JSON 对象或 null。"},
    },
    "upgrade_hook_with_rqgm_gate": {
        "new_hook_rel_path": {"description": "升版后的新验证钩子相对路径。"},
        "gt_success_count": {"description": "RQGM 真值正样本通过数（整数）。"},
        "gt_failure_count": {"description": "RQGM 真值正样本失败数（整数）。"},
        "adv_pool_reject_rate": {"description": "对抗样本池总体拒识率 r_P（0..1，可为空）。"},
        "adv_pool_positive_rate": {"description": "对抗样本池真阳性率 p_+（0..1，可为空）。"},
        "adv_pool_negative_rate": {"description": "对抗样本池假阳性率 p_-（0..1，可为空）。"},
    },
    "recompute_stage_b_only": {
        "obs_id": {"description": "需要仅重算 Stage B 评分与通过状态的持久化观测记录 ID（不重复执行 Stage A）。"},
    },
    "update_skill_ledger": {
        "skill_id": {"pattern": "^[a-z0-9_]+$", "description": "技能唯一标识（严格匹配 ^[a-z0-9_]+$，禁止大写/空格/连字符）。"},
        "applicable_scope": {"description": "技能适用工程场景与约束条件说明。"},
        "version": {"minimum": 1, "description": "技能版本号（正整数，如 1、2）。"},
        "raw_success_count": {"minimum": 0, "description": "累计实测成功次数。"},
        "raw_failure_count": {"minimum": 0, "description": "累计实测失败次数。"},
        "verified_artifact_rel_path": {"description": "已通过 No-File 校验的非空技能产物相对路径。"},
        "rollback_pointer": {"description": "回滚指针或前序稳定版本标识（如 v0 / git sha）。"},
    },
    "record_compliance_check": {
        "stage": {
            "enum": ["STAGE1_GATE", "STAGE2_HEARTBEAT", "STAGE2_CLOSURE_GATE", "STAGE3_FINAL_AUDIT"],
            "description": "审计检查点枚举：STAGE1_GATE | STAGE2_HEARTBEAT | STAGE2_CLOSURE_GATE | STAGE3_FINAL_AUDIT。",
        },
        "status": {
            "enum": ["PASSED", "ALERT", "BLOCKED"],
            "description": "合规状态枚举：PASSED | ALERT | BLOCKED。",
        },
        "blocking_questions_zero_l3": {"description": "当前仍处于 0 L3 阻塞状态的子题编号列表（无则传 []）。"},
        "unread_citation_nodes": {"description": "声明引用但缺少 READ 暴露边的高风险节点 ID 列表（无则传 []）。"},
        "notes": {"description": "本次合规检查的简明对账备注。"},
    },
    "register_saved_graph_query": {
        "query_name": {"description": "只读图查询视图名称（供探索者 read_lineage_graph 复用）。"},
        "description": {"description": "说明该视图返回的图谱指标或查询用途。"},
        "sql_select": {"description": "单条合法只读 SELECT SQL 语句（严禁写操作或分号多语句）。"},
    },
}


def enrich_tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为 31 个 MCP 工具 JSON Schema 统一注入字段说明、枚举与内嵌数组结构。"""
    enriched: list[dict[str, Any]] = []
    for tool in tools:
        t = deepcopy(tool)
        name = str(t.get("name", ""))
        schema = t.get("inputSchema")
        if isinstance(schema, dict):
            props = schema.get("properties")
            if isinstance(props, dict):
                tool_patches = _TOOL_PROP_PATCHES.get(name, {})
                for prop_name, prop_def in props.items():
                    if not isinstance(prop_def, dict):
                        continue
                    if prop_name in _COMMON_PROP_DESCRIPTIONS and "description" not in prop_def:
                        prop_def["description"] = _COMMON_PROP_DESCRIPTIONS[prop_name]
                    patch = tool_patches.get(prop_name)
                    if patch:
                        prop_def.update(patch)
        enriched.append(t)
    return enriched
