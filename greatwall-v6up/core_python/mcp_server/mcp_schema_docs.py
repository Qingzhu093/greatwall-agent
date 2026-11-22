"""长城 V6-Up (v3.0) 全量 31 个 MCP 工具 JSON Schema 字段说明、枚举与内嵌结构表（100% 同源 db_schema.py）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ALLOWED_COMPANION_MODES,
    ALLOWED_COMPLIANCE_STAGES,
    ALLOWED_COMPLIANCE_STATUSES,
    ALLOWED_DEAD_END_CATEGORIES,
    ALLOWED_DELIVERY_MODES,
    ALLOWED_EVIDENCE_GRADES,
    ALLOWED_FINAL_VERDICTS,
    ALLOWED_FORK_MODES,
    ALLOWED_GOAL_COVERAGES,
    ALLOWED_INSTRUMENT_ROLES,
    ALLOWED_INSTRUMENT_TIERS,
    ALLOWED_L3_ENTRY_KINDS,
    ALLOWED_READ_DEPTHS,
    ALLOWED_STAGE1_VERDICTS,
    ALLOWED_STAGNATION_LANES,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ALLOWED_TICKET_RESOLUTIONS,
    ALLOWED_TRIAGE_ACTIONS,
    ALLOWED_TRIAGE_LEVELS,
    ALLOWED_VERDICT_3STATE,
)

_COMMON_DESCRIPTIONS: dict[str, str] = {
    "node_id": "探索节点唯一 ID（例如 node_p1_n2）。",
    "branch_id": "探索分支唯一 ID（例如 b_q1_famA）。",
    "question_id": "所属子题编号（例如 Q1、Q2，或全卷查询时的 ALL）。",
    "review_id": "盲审工单 ID（例如 rev_001，或终核模式 STAGE3_FINAL_AUDIT:<delivery_id>）。",
    "obs_id": "正式观测收据 ID（例如 Obs-001）。",
    "instrument_id": "科研仪器唯一 ID（例如 inst_q1_geom）。",
    "title": "条目标题（需概括核心数学/物理机制与适用结论）。",
}

_TOOL_PROP_PATCHES: dict[str, dict[str, dict[str, Any]]] = {
    "run_isolated_eval": {
        "tier": {
            "enum": sorted(ALLOWED_INSTRUMENT_TIERS),
            "description": "三档同码调用档位：probe（公开快速诊断，不记 Obs）| official（受控正式收据 [Obs###]）| heavy（重型排队，冻结快照幂等取回）。",
        },
        "artifact_rel_path": {"description": "待测候选产物路径，严格相对于当前分支 worktree_abs_path 根目录（例如 proofs/jung_counterexample.py）。"},
        "linguistic_prediction": {"description": "调用 official/heavy 前必填（>=5 字）的可证伪事前自然语言预测。"},
        "declared_refs": {"description": "本实验显式引用的外藏/内藏条目 ID 列表（默认记为 MOTIVATING_REF，不触发连坐撤回）。"},
        "job_id": {"description": "可选：仅 tier='heavy' 幂等取回已排队重型作业时传入先前返回的 job_id，首次提交传 null。"},
    },
    "query_library_catalog": {
        "scope": {
            "enum": ["EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "ALL"],
            "description": "检索范围：0-37% 未解锁前仅能使用 EXTERNAL_R；37% 元反思解锁后开放 EXTERNAL_R | INTERNAL_L3 | INTERNAL_L2 | ALL。",
        },
        "keyword": {"description": "FTS5 中英文关键词过滤词（留空 '' 返回该范围全部目录卡）。"},
    },
    "get_library_entry": {
        "entry_id": {"description": "目标文献或引理条目 ID（如 R006、L3-001、L2-001），调用静默记录参考 READ 边。"},
    },
    "request_literature_survey": {
        "topic_query": {"description": "委托外藏采编检索的数学定理、物理机制或关键词。"},
        "reason": {"description": "当前研究瓶颈及需要该外部参考卡片解决的具体问题。"},
    },
    "read_lineage_graph": {
        "target_node_id": {"description": "可选：仅查看本分支指定祖先节点详情（不传或 null 返回本分支谱系摘要）。"},
        "view": {
            "enum": ["nodes", "dead_ends"],
            "description": "查询视图：nodes（本脉历代 DAG 页）| dead_ends（本脉只增不改的全量历史死胡同表）。",
        },
        "saved_query_name": {"description": "可选：监察委预注册的只读 SQL 视图名（受租户与盲审表隔离保护）。"},
    },
    "get_companion_context": {
        "mode": {
            "enum": sorted(ALLOWED_COMPANION_MODES),
            "description": "伴随阶段模式：PRE_SPAWN（仅旧看板与上代手记）| REFLECT_37（含本脉 dead_ends、L3/L2 目录与夜科学题）| HANDOFF_70 | CRASH_RECOVERY。",
        },
    },
    "save_lineage_briefing": {
        "sec1_mechanism": {"description": "段1（稳定精炼）：核心底层机理与不变量（五段合计硬限 <= 2200 字，分段配比仅为软参考）。"},
        "sec2_verified_baseline": {"description": "段2（合并覆写）：已证实前提、最新快照及活跃 REVISE 审稿异议。"},
        "sec3_bottleneck": {"description": "段3（覆盖刷新）：当前尚未突破的核心矛盾。"},
        "sec4_dead_ends": {"description": "段4（Top-K 下沉）：当前直接相关死胡同精选 + lineage_dead_ends 全表条数索引。"},
        "sec5_immediate_will": {"description": "段5（整体替换）：刚退场这一代的新《科研遗嘱》（最小鉴别实验与翻转条件）。"},
    },
    "record_reflection_and_unlock_pull": {
        "selected_categories": {"description": "元反思分类列表，必须包含第 7 类 Attractor Tasks。"},
        "holiday_prompt_id": {"minimum": 1, "maximum": 28, "description": "抽中的夜科学启发题编号（1–28 整数）。"},
        "turns": {
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "maxLength": 300, "description": "伴随外部专家诊断追问（<=300字）。"},
                    "answer": {"type": "string", "maxLength": 300, "description": "探索者反思回答（<=300字）。"},
                },
                "required": ["question", "answer"],
            },
            "description": "1 至 2 轮精简问答，每轮 <= 300 字。",
        },
        "verdict_3state": {
            "enum": sorted(ALLOWED_VERDICT_3STATE),
            "description": "三态元反思决断枚举。",
        },
    },
    "submit_node_handoff": {
        "mechanism_summary": {"maxLength": 99, "description": "必填 <100 字纯底层核心数学/物理机制摘要（严禁写指标分数或结果）。"},
        "evidence_grade": {
            "enum": sorted(ALLOWED_EVIDENCE_GRADES),
            "description": "证据形态分级：NONE | ARTIFACT_ONLY（纯推导/反例脚本）| MEASURED（绑定真实 official/heavy [Obs###]）。",
        },
        "column_a_facts_md": {"description": "A 栏（客观实证事实与推导资产，供 Stage 1 盲审；A+B+will 总长 <= 2000 字）。"},
        "column_b_hypothesis_md": {"description": "B 栏（机理猜想与反常线索，Stage 1 物理屏蔽）。"},
        "will_md": {"description": "核对后的下代《科研遗嘱》。"},
        "obs_ids": {"description": "绑定的正式 official/heavy [Obs###] ID 列表（严禁把 probe 日志混入；纯推导可传 []）。"},
        "dead_ends": {
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": sorted(ALLOWED_DEAD_END_CATEGORIES), "description": "失败归因分类。"},
                    "scope_condition_md": {"type": "string", "description": "失效条件与边界范围。"},
                    "failure_mechanism_md": {"type": "string", "description": "精确失灵机理。"},
                    "bound_obs_id": {"type": ["string", "null"], "description": "关联 [Obs###] 或 null。"},
                },
                "required": ["category", "scope_condition_md", "failure_mechanism_md"],
            },
            "description": "本代新排除边界数组，只追加写入 lineage_dead_ends 表（严禁把 INSTRUMENT_ERROR 记为候选失败）。",
        },
        "candidate_rel_path": {"description": "可选：本代主产物/脚本相对分支 worktree 路径。"},
        "is_empty_crash": {"description": "仅当探索者一字未产即意外崩溃时设为 true（记入 scratch_log）；非空产物一律 false 写正式 DAG。"},
        "tool_pain_point": {"description": "可选：工具/仪器痛点说明（自动入队工造司）。"},
    },
    "get_logistics_dashboard": {
        "question_id": {"description": "子题编号或 ALL。"},
    },
    "register_method_family": {
        "family_id": {"description": "底层方法学派唯一英文标识（如 fam_q1_jung_extremal）。"},
        "mechanism_signature": {"description": "底层思想与数理机理签名。"},
        "orthogonal_contrast": {"description": "说明与已有学派在原理层面的正交区别。"},
    },
    "triage_node": {
        "assigned_family_id": {"description": "后勤依据 mechanism_summary 归类确定的学派 family_id。"},
        "triage_level": {"enum": sorted(ALLOWED_TRIAGE_LEVELS), "description": "分诊级别枚举。"},
        "action": {"enum": sorted(ALLOWED_TRIAGE_ACTIONS), "description": "分诊动作枚举。"},
        "rationale": {"description": "清晰的分诊裁决理由。"},
        "barrier_proof_md": {"description": "LEVEL_4A / SEAL_BARRIER 时必填（>=15 字）：严密反例或结构阻碍证明。"},
        "reopen_condition": {"description": "LEVEL_4B / PAUSE_TO_READY_QUEUE 时必填：重入队列解锁条件。"},
    },
    "fork_branch": {
        "parent_node_id": {"description": "父节点 ID（开局首枝可传 null）。"},
        "fork_mode": {"enum": sorted(ALLOWED_FORK_MODES), "description": "派生模式：orthogonal | lateral | cross_pollinate。"},
        "target_family_id": {"description": "目标学派 family_id。"},
        "requires": {"description": "分支级确定性前置列表（仅限 L3-### 或 OBS:<instrument_id>:PASS，只锁本分支）。"},
        "new_mechanism_note": {"description": "可选：学派处于 BLOCKED 时重开必填的实质绕开方案说明。"},
        "source_l3_id": {"description": "仅 cross_pollinate 必填：借用的活跃 L3 ID（需双方学派各有 >=1 L3）。"},
    },
    "dispatch_stagnation_five_lanes": {
        "lane_assignments": {
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "branch_id": {"type": "string", "description": "分支 ID。"},
                    "lane": {"type": "string", "enum": sorted(ALLOWED_STAGNATION_LANES), "description": "五互斥车道枚举。"},
                    "directive": {"type": "string", "description": "车道行动指令。"},
                },
                "required": ["branch_id", "lane", "directive"],
            },
            "description": "停滞或 >50% 聚拢告警时的五车道重排清单。",
        },
    },
    "get_survey_requests": {
        "question_id": {"description": "过滤子题 ID 或 ALL（Stage 3 附带全量已审 L3 综合包）。"},
    },
    "publish_external_literature_card": {
        "outcome": {
            "enum": sorted(ALLOWED_SURVEY_OUTCOMES),
            "description": "查新结果类型：CARD_PUBLISHED（默认，确有真实来源入库 [R###]）| UNAVAILABLE_REPORT（客观不存在或违背合规边界，不造伪卡，将对应 survey_requests 结案为 CLOSED_UNAVAILABLE）。",
        },
        "ref_id": {"description": "外藏参考卡唯一编号（如 R001、R006；outcome='UNAVAILABLE_REPORT' 时可传 null）。"},
        "abstract_md": {
            "minLength": 60,
            "maxLength": 1500,
            "description": "独立高密度外部参考摘要（CARD_PUBLISHED 必填，服务端硬限 60–1500 字符，推荐 120–300 字符；UNAVAILABLE_REPORT 可传 null）。",
        },
        "exact_preconditions_md": {"description": "严格适用前提与边界假设（CARD_PUBLISHED 必填）。"},
        "formulas_or_operators_md": {"description": "核心数学公式、定理表达式或算子定义（CARD_PUBLISHED 必填）。"},
        "read_depth": {"enum": sorted(ALLOWED_READ_DEPTHS), "description": "诚实阅读深度英文枚举（CARD_PUBLISHED 必填；UNAVAILABLE_REPORT 不传或传 null）。"},
        "support_scope": {"enum": sorted(ALLOWED_SUPPORT_SCOPES), "description": "严格 5 选 1 支持度分类英文枚举（严禁填中文；UNAVAILABLE_REPORT 不传或传 null）。"},
        "source_citation": {"description": "标准文献或教材出处（CARD_PUBLISHED 必填）。"},
        "fulfilled_request_ids": {"description": "精准核销或结案的 survey_requests.req_id 列表（UNAVAILABLE_REPORT 必填）。"},
        "unavailable_reason_md": {"description": "outcome='UNAVAILABLE_REPORT' 必填（>=10 字）：写明已查范围与不可得原因，写入 survey_requests.resolution_note。"},
    },
    "export_stage3_final_delivery": {
        "delivery_mode": {"enum": sorted(ALLOWED_DELIVERY_MODES), "description": "终局交付模式：FULL | PARTIAL_ON_BUDGET | PARTIAL_ON_HUMAN_STOP。"},
        "formal_paper_md": {"minLength": 50, "description": "正式研究报告全文 Markdown（严禁混入未审稿或夸大 L3 边界）。"},
        "selected_l3_ids_by_question": {"description": "各子题入选的活跃 L3 ID 映射字典。"},
        "remaining_gaps_by_question": {"description": "各子题精确剩余断点（Remaining Gaps）映射字典。"},
        "reproduction_candidate_nodes": {"description": "可复现节点 ID 列表。"},
    },
    "submit_stage1_blind_ledger": {
        "ledger_items": {
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "核心宣称。"},
                    "evidence_location_and_quote": {"type": "string", "description": "精确原文定位、代码行或沙箱实跑输出摘录（缺证填 No direct evidence found）。"},
                    "sandbox_check_cmd_or_note": {"type": ["string", "null"], "description": "可选：盲审沙箱执行的验证命令与输出摘要。"},
                    "is_verified": {"type": "boolean", "description": "是否通过核验。"},
                },
                "required": ["claim", "evidence_location_and_quote"],
            },
            "description": "Stage 1 不可逆独立 Evidence Ledger 列表。",
        },
        "stage1_verdict": {"enum": sorted(ALLOWED_STAGE1_VERDICTS), "description": "Stage 1 裁决枚举：PASS | REVISE | REFUTED。"},
        "revision_or_refutation_reason": {"description": "判 REVISE 或 REFUTED 时必填的明确原因或返工要求。"},
        "exact_refuted_scope_md": {"description": "判 REFUTED 时必填的精确被证伪范围。"},
    },
    "submit_stage2_unblind_verdict": {
        "final_verdict": {"enum": sorted(ALLOWED_FINAL_VERDICTS), "description": "Stage 2 终审三态枚举：ACCEPT | ACCEPT_NARROWED | REVISE | REFUTED。"},
        "l3_entry_kind": {"enum": [*sorted(ALLOWED_L3_ENTRY_KINDS), None], "description": "ACCEPT* 必填：POS_THEOREM | NEG_COUNTEREXAMPLE | BARRIER_PROOF。"},
        "goal_coverage": {"enum": [*sorted(ALLOWED_GOAL_COVERAGES), None], "description": "ACCEPT* 必填：FULL_GOAL | PARTIAL_OR_LEMMA | EQUIVALENT_REDUCTION（缩窄/等价归约严禁标 FULL_GOAL）。"},
        "is_equivalent_reduction": {"description": "是否为问题等价归约（若为 true 严禁标 FULL_GOAL）。"},
        "abstract_md": {"description": "独立高密度终审摘要（ACCEPT* 必填 >= 40 字）。"},
        "exact_verified_scope_md": {"description": "ACCEPT* 必填：严格已证实成立范围。"},
        "exact_refuted_scope_md": {"description": "REFUTED 必填（ACCEPT_NARROWED 可选）：精确失灵/证伪范围。"},
        "revision_requests": {"description": "REVISE 必填：退回原分支的具体返工项列表。"},
        "cross_draft_comparison_notes": {"description": "跨稿件横向对比说明。"},
        "cross_pollinate_nomination": {"description": "可选：交叉授粉提名对象或 null。"},
        "edge_type_overrides": {
            "description": f"可选：按引用 ID 升级承重前提边类型，合法值 {sorted(ALLOWED_CLAIMED_EDGE_TYPES)}。",
        },
    },
    "propose_salvaged_lemma": {
        "source_node_id": {"description": "已闭或阻塞源节点 ID（严禁对 ACTIVE_REVISING 返工分支打捞）。"},
        "abstract_md": {"description": "打捞引理独立摘要。"},
        "column_a_self_contained_proof_md": {"description": "剥离原上下文后的自包含证明/实证正文。"},
        "column_b_scope_notes_md": {"description": "精确适用边界与限制条件。"},
        "bound_obs_ids": {"description": "关联正式 [Obs###] 列表（纯解析引理可传 []）。"},
    },
    "get_works_engineering_queue": {
        "question_id": {"description": "子题编号或 ALL（返回仪器健康、故障工单与 pending_revalidation 队列）。"},
    },
    "register_question_instrument": {
        "instrument_role": {"enum": sorted(ALLOWED_INSTRUMENT_ROLES), "description": "仪器角色枚举：VERDICT | PROBE | ENV。"},
        "instrument_rel_path": {
            "description": "仪器 Python 脚本相对工作区路径，须导出 evaluate(artifact, spec, tier) -> {'status': 'OK|CANDIDATE_ERROR|INSTRUMENT_ERROR|INFRA_ERROR', 'verdict': 'PASS|FAIL|UNDECIDED'|None（非 OK 态必须为 None）, 'tracks': {str: 有限数值}, 'details': str}。",
        },
        "calibration_suite_rel_path": {
            "description": "校准集 JSON 相对路径（VERDICT 必填且 100% 通过；PROBE/ENV 可传 null）。格式为非空 JSON 数组，每项含 {'name', 'artifact_rel_path' 或 'artifact', 'tier': 'probe|official|heavy', 'expected_status', 'expected_verdict'（非 OK 态填 null）}。",
        },
        "artifact_schema": {"description": "自声明待测 artifact 形态（如 python_run / raw_file / counterexample_json / lean4）。"},
        "plugin_protocol_version": {"description": "仪器协议版本，默认 v3。"},
        "default_spec": {
            "description": "可选：仪器默认配置规格字典（可含 public_input，并推荐写入 'interface_hint' 简述待测产物入口/输出约定，服务端会自动推送给探索者）。",
        },
    },
    "upgrade_instrument_with_calibration": {
        "new_instrument_rel_path": {
            "description": "新版仪器脚本相对路径，须导出 evaluate(artifact, spec, tier) -> {'status', 'verdict', 'tracks': {数值}, 'details': str}（非 OK 态 verdict 必须为 None）。",
        },
        "calibration_suite_rel_path": {
            "description": "独立校准集 JSON 相对路径（非空 JSON 数组，tier 仅限 probe/official/heavy，非 OK 态 expected_verdict 为 null，100% 匹配即直接升版）。",
        },
        "artifact_schema": {
            "description": "可选：升版时同步更新仪器的 artifact_schema（如 python_run / raw_file）；不传或 null 则保持原 schema。",
        },
        "default_spec": {
            "description": "可选：升版时同步更新仪器的 default_spec 配置字典（含 public_input 或 interface_hint）；不传或 null 则保持原配置。",
        },
    },
    "recompute_stage_b_only": {
        "obs_id": {"description": "需按新版仪器免重跑 Stage A 重评的旧观测 ID（保留旧收据，成功生成新版新收据，缺字段标 INCOMPATIBLE）。"},
    },
    "update_skill_ledger": {
        "skill_id": {"pattern": "^[a-z0-9_]+$", "description": "技能唯一 ID（严格匹配 ^[a-z0-9_]+$）。"},
        "applicable_scope": {"description": "适用范围说明。"},
        "version": {"minimum": 1, "description": "版本号（正整数）。"},
        "raw_success_count": {"minimum": 0, "description": "原始成功次数。"},
        "raw_failure_count": {"minimum": 0, "description": "原始失败次数。"},
        "verified_artifact_rel_path": {"description": "经 No-File 校验的非空产物相对路径。"},
        "rollback_pointer": {"description": "回滚指针或前序版本标识。"},
    },
    "resolve_works_ticket": {
        "ticket_id": {"description": "待结案的工造司工单 ID（如 tkt_xxxx）。"},
        "resolution": {
            "enum": sorted(ALLOWED_TICKET_RESOLUTIONS),
            "description": "结案结论枚举：RESOLVED（已修复/处理）| WONTFIX（权限设计使然或无需修改）| DUPLICATE（重复工单）。",
        },
        "resolution_note": {"minLength": 5, "description": "结案依据与处理说明（>=5 字）。"},
    },
    "check_stage2_closure_gate": {
        "mode": {"enum": sorted(ALLOWED_DELIVERY_MODES), "description": "结题模式：FULL | PARTIAL_ON_BUDGET | PARTIAL_ON_HUMAN_STOP。"},
        "human_aborted": {"description": "是否按人类紧急叫停路径核验（服务端强校验控制面真实写入的 human_stop_requested_at，严禁伪造）。"},
    },
    "record_compliance_check": {
        "stage": {"enum": sorted(ALLOWED_COMPLIANCE_STAGES), "description": "合规审计阶段枚举。"},
        "status": {"enum": sorted(ALLOWED_COMPLIANCE_STATUSES), "description": "合规状态枚举（口径歧义用 ALERT_AMBIGUOUS_SPEC 后台亮红灯不停机）。"},
        "blocking_questions": {"description": "阻塞子题编号列表（无则 []）。"},
        "notes": {"description": "简明审计备注（零 .md 落盘）。"},
    },
    "register_saved_graph_query": {
        "query_name": {"description": "只读图查询视图名称。"},
        "description": {"description": "视图用途说明。"},
        "sql_select": {"description": "单条合法只读 SELECT SQL 语句。"},
    },
}


def enrich_tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为全量 31 个 MCP 工具 JSON Schema 统一注入中文说明、枚举与内嵌数组结构。"""
    enriched: list[dict[str, Any]] = []
    for tool in tools:
        t = deepcopy(tool)
        name = str(t.get("name", ""))
        schema = t.get("inputSchema")
        if isinstance(schema, dict):
            props = schema.get("properties")
            if isinstance(props, dict):
                patches = _TOOL_PROP_PATCHES.get(name, {})
                for pname, pdef in props.items():
                    if not isinstance(pdef, dict):
                        continue
                    if pname in _COMMON_DESCRIPTIONS and "description" not in pdef:
                        pdef["description"] = _COMMON_DESCRIPTIONS[pname]
                    patch = patches.get(pname)
                    if patch:
                        pdef.update(patch)
        enriched.append(t)
    return enriched
