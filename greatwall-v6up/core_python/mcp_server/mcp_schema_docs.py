"""GreatWall Agent v0.3 全量窄 MCP 工具 JSON Schema 中文说明与权威枚举绑定（100% 同源 db_schema.py）。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .db.enums import ALLOWED_CONFERENCE_SPEECH_ACTS, ALLOWED_CONVERGENCE_MODES, ALLOWED_HOLIDAY_OUTCOMES, ALLOWED_INTERNAL_SURVEY_SCOPES
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
    ALLOWED_PROPOSAL_ACTIONS,
    ALLOWED_PUBLISH_TIERS,
    ALLOWED_READ_DEPTHS,
    ALLOWED_STAGE1_VERDICTS,
    ALLOWED_SUPPORT_SCOPES,
    ALLOWED_SURVEY_OUTCOMES,
    ALLOWED_TICKET_RESOLUTIONS,
    ALLOWED_TRIAGE_ACTIONS,
    ALLOWED_TRIAGE_LEVELS,
    ALLOWED_VERDICT_3STATE,
    ALLOWED_WAVE_VERDICT_ACTIONS,
)

_COMMON_DESCRIPTIONS: dict[str, str] = {
    "node_id": "探索节点唯一 ID（例如 node_q1_xxxx）。",
    "branch_id": "探索分支唯一 ID（例如 b_q1_famA）。",
    "question_id": "所属子题编号（例如 Q1、Q2，或全卷查询时的 ALL）。",
    "review_id": "盲审工单 ID（例如 rev_001，或 Stage 3 冻结终核模式 STAGE3_FINAL_AUDIT:<delivery_id>）。",
    "obs_id": "正式观测收据 ID（例如 Obs-001）。",
    "instrument_id": "科研仪器唯一 ID（例如 inst_q1_geom）。",
    "conference_id": "宏观大外环波次圆桌会议唯一 ID（例如 wc_q1_w1_xxxx）。",
    "title": "条目标题（概括核心数学/物理机制与结论）。",
    "query_text": "检索或预演所用的自然语言/关键词查询文本。",
    "payload": "结构化 JSON 负载参数对象。",
    "affected_question_ids": "本次操作或修订受影响的子题编号列表。",
    "summary_md": "简明 Markdown 摘要说明。",
    "rationale": "决策依据与客观理由说明。",
    "notes": "附加备注与核验说明。",
    "abstract_md": "高密度客观摘要正文（Markdown）。",
    "exact_verified_scope_md": "精确已证实适用范围与边界条件说明。",
    "exact_refuted_scope_md": "精确已证伪或排除的边界范围说明。",
    "exact_preconditions_md": "成立前提与数学/物理前置条件说明。",
    "formulas_or_operators_md": "核心公式、算子或算法结构摘录。",
    "source_citation": "外部来源引用（作者、年份、URL 或 DOI）。",
    "unavailable_reason_md": "客观不可得/无解查新结案说明。",
    "fulfilled_request_ids": "本次结案核销的查新请求 ID 列表。",
    "fulfilled_gap_ids": "本次 L3 成果核销的悬赏缺口 gap_id 列表。",
    "narrowed_l2_title": "ACCEPT_NARROWED 降级收编时同步归档的 L2 失败记录标题。",
    "revision_requests": "盲审退修具体可操作修改要求列表。",
    "cross_draft_comparison_notes": "与同题既有 L3/L2 馆藏的横向对照。申请低新颖分精简豁免时，写明原规模、新规模及降幅百分数（如证明从 50 步减为 40 步，精简 20%）。",
    "exploit_ticket_payload": "发现仪器漏洞/反作弊漏洞时同事务签发给工造司的 EXPLOIT 工单负载。",
    "minutes_md": "圆桌会议结构化纪要正文（Markdown）。",
    "next_round_focus_md": "下一轮圆桌聚焦议题或交锋靶点。",
    "actions": "宏观圆桌裁决动作列表（6 类允许动作）。",
    "verdict_summary_md": "宏观圆桌主席最终裁决综述。",
    "target_node_id": "圆桌点对点交锋中指向的对手或目标节点 ID。",
    "evidence_refs": "发言引用的馆藏/观测编号清单（如 Obs-###、L3-###）。",
    "selected_l3_ids_by_question": "按子题映射的终稿入选 L3 条目 ID 列表。",
    "remaining_gaps_by_question": "按子题映射的未闭合缺口与边界诚实说明。",
    "formal_paper_md": "Stage 3 正式研究总报告正文（Markdown）。",
    "reproduction_candidate_nodes": "纳入最小可复现套件的候选节点 ID 列表。",
}

_TOOL_PROP_PATCHES: dict[str, dict[str, dict[str, Any]]] = {
    "chief_trace_entity": {
        "entity_type": {
            "enum": ["question", "node", "review", "entry", "conference", "proposal", "gap", "obs"],
            "description": "要沿强外键回忆链展开的目标实体类型。",
        },
        "entity_id": {"description": "目标实体唯一编号（如 Q1 / node_xxx / rev_001 / L3-001 / wc_xxx / prop_xxx）。"},
    },
    "chief_read": {
        "resource": {
            "description": "统一资源 URI：contract（Parse 0 完整契约与完成判据）| survey/<Q> | node/<id>/manuscript | node/<id>/briefing | node/<id>/transcript | review/<id>/ledger | conference/<id>/minutes | entry/<id>（支持内藏 L3/L2 与外藏 R###）| receipt/<op_id> | archive/<epoch_id>/<上述任一路径>。",
        },
        "offset": {"minimum": 0, "description": "UTF-16 字符起始偏移（沿上一次返回的 next_offset 续读）。"},
        "limit": {"minimum": 1, "maximum": 16000, "description": "单页最大读取字符数（默认 4000）。"},
    },
    "chief_operate": {
        "operation": {
            "enum": [
                "apply_arrangement",
                "revoke_arrangement",
                "node_intervene",
                "family_manage",
                "approve_wave_verdict",
                "open_wave_conference",
                "submit_ticket",
                "cancel_ticket",
                "request_survey",
                "recover_queue",
                "pin_note",
            ],
            "description": "11 类日常运维直执原语枚举（含人工随时召集圆桌 open_wave_conference、直派外藏查新 request_survey 与撤回未结工单 cancel_ticket）。",
        },
        "arrangement": {"description": "单条运行安排补丁（含 scope_type、target_id、dispatch_policy、priority_weight、max_active_branches、max_concurrent_workers、inflight_drain_mode、ends_on_kind/expires_at 等）。"},
        "arrangements": {"description": "多条运行安排列表（同一人类意图涉及多个子题时一次原子提交）。"},
        "node_action": {"description": "点名分支动作（node_ids + mode: retire|hibernate|pause_takeover|resume|early_handoff|reactivate + 可选 archive_family/reason）。"},
        "handback_id": {"description": "可选：人类在探索者窗口发起并转办至总控的一次性授权凭证 ID。"},
        "details": {"description": "扩展操作参数（revoke_arrangement 传 arrangement_id；family_manage 传 family_id/mode；submit_ticket 传 question_id/ticket_type/description/instrument_id；cancel_ticket 传 ticket_id/reason；request_survey 传 question_id/topic_query/reason；pin_note 传 question_id/note_id/content_md）。"},
    },
    "submit_works_ticket": {
        "question_id": {"description": "关联子题号（如 Q1 / ALL）。"},
        "ticket_type": {
            "enum": ["INSTRUMENT_ERROR", "PAIN_POINT", "DUPLICATE_TOOL", "EXPLOIT", "DISCRIMINATOR"],
            "description": "工单类型枚举：仪器报错 / 痛点 / 重复造轮子 / 漏洞 / 鉴别器。",
        },
        "description": {"minLength": 5, "description": "简明扼要的问题或共享工具需求描述（>=5 字）。"},
        "instrument_id": {"description": "可选：关联的仪器或目标共享工具 ID（如 sim_env / geo_kernel）。"},
    },
    "chief_send_branch_note": {
        "node_id": {"description": "接收导师点拨的目标探索节点 ID。"},
        "note_md": {"minLength": 2, "description": "导师指导便签正文（Markdown），在线温和注入、离线下一回合自动送达。"},
    },
    "chief_seed_branch": {
        "question_id": {"description": "目标子题编号（如 Q1）。"},
        "family_signature": {"description": "新学派核心机制签名（简明唯一标识该研究路线）。"},
        "blueprint_md": {"minLength": 10, "maxLength": 8000, "description": "完整研究蓝图正文（10–8000 字，完整保留推导与验证要点，不作摘要压缩）。"},
        "orthogonal_contrast": {"description": "与现有学派的正交差异说明。"},
    },
    "chief_preview_impact": {
        "preview_kind": {
            "enum": ["run_arrangement", "ruling_amendment", "avoidance_check", "wave_verdict", "subproblem_budget"],
            "description": "零副作用推测预演类型：运行安排影响 / 改题影响面 / 排雷雷达查重 / 波次调整受影响分支 / 子题预算测算。",
        },
        "arrangement": {"description": "preview_kind='run_arrangement' 时待预演的运行安排草案。"},
    },
    "chief_propose_control_action": {
        "action_type": {
            "enum": ["AMEND_RULING_DRAFT", "AUTHORIZE_PARTIAL_DELIVERY", "ADVANCE_EPOCH", "APPROVE_WAVE_VERDICT"],
            "description": "4 类宪章正门确认单动作枚举（改题升版 / 部分结题 / 推进纪元 / 后台圆桌拍板）。",
        },
        "target_id": {"description": "受影响目标 ID（子题号 / 节点 ID / 会议 ID / 自主档位等）。"},
        "rationale_md": {"minLength": 5, "description": "给人类审阅的简明依据与影响范围说明（>=5 字）。"},
        "human_action_question": {"description": "一次只问一个具体问题的单句确认提问（展示在原生 Action Card 上）。"},
    },
    "run_isolated_eval": {
        "tier": {"enum": sorted(ALLOWED_INSTRUMENT_TIERS), "description": "三档同码：probe | official | heavy。"},
        "artifact_rel_path": {"description": "相对当前 worktree 根目录的候选文件路径。"},
        "linguistic_prediction": {"description": "official/heavy 必填（>=5 字）可证伪事前自然语言预期。"},
        "declared_refs": {"description": "引用条目列表（默认 MOTIVATING_REF）。"},
        "job_id": {"description": "仅 heavy 幂等取回时传入先前 job_id，首次传 null。"},
    },
    "query_library_catalog": {
        "scope": {
            "enum": ["EXTERNAL_R", "INTERNAL_L3", "INTERNAL_L2", "AVOIDANCE_RADAR", "ALL"],
            "description": "检索范围：explorer 0-37% 仅限 EXTERNAL_R；37%+ 及伴随助手 0%+ 全馆开放。",
        },
        "keyword": {"description": "FTS5 中英文关键词（空串返回全部）。"},
    },
    "get_library_entry": {
        "entry_id": {"description": "条目编号（R### / L3-### / L2-###），静默记录 FACT_LOG(READ)。"},
    },
    "read_lineage_graph": {
        "view": {"enum": ["nodes", "dead_ends"], "description": "本脉谱系视图：nodes | dead_ends。"},
    },
    "handback_to_chief": {
        "human_request_md": {"minLength": 5, "description": "人类在子节点聊天窗提出的超出本分支范围的原始诉求。"},
        "reason": {"description": "说明为何超出本分支权限范围并需交 gw-chief 统筹。"},
    },
    "get_companion_context": {
        "mode": {"enum": sorted(ALLOWED_COMPANION_MODES), "description": "伴随阶段模式。"},
    },
    "record_reflection_and_unlock_pull": {
        "holiday_prompt_id": {"minimum": 1, "maximum": 28, "description": "旧调用的兼容参数，默认 null。夜科学由宿主在 52% 另行选题。"},
        "turns": {
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "maxLength": 300},
                    "answer": {"type": "string", "maxLength": 300},
                },
                "required": ["question", "answer"],
            },
        },
        "verdict_3state": {"enum": sorted(ALLOWED_VERDICT_3STATE)},
    },
    "submit_node_handoff": {
        "mechanism_summary": {"maxLength": 99, "description": "必填 <100 字纯底层机理摘要。"},
        "evidence_grade": {"enum": sorted(ALLOWED_EVIDENCE_GRADES)},
        "dead_ends": {
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": sorted(ALLOWED_DEAD_END_CATEGORIES)},
                    "scope_condition_md": {"type": "string"},
                    "failure_mechanism_md": {"type": "string"},
                    "bound_obs_id": {"type": ["string", "null"]},
                },
                "required": ["category", "scope_condition_md", "failure_mechanism_md"],
            },
        },
        "recommended_triage": {
            "description": "可选：伴随助手结构化去向建议（合法常规情形由确定性控制面直接落单，无需额外拉起后勤分诊员）。",
        },
        "holiday_bet_outcome": {
            "description": '核销本班收到的赌注。示例：{"outcome":"FALSIFIED","note_md":"在 Obs-007 条件下观测到反例"}。',
            "properties": {"outcome": {"type": "string", "enum": sorted(ALLOWED_HOLIDAY_OUTCOMES)},
                           "note_md": {"type": "string", "description": "实验依据或未测试原因。"}},
        },
        "manuscript_submissions": {
            "description": (
                '阶段投稿默认为非阻塞。示例：[{"title":"有限域引理","abstract_md":"适用有限凸域",'
                '"claim_and_proof_md":"逐步证明正文","exact_scope_md":"有限凸域",'
                '"bound_obs_ids":["Obs-001"],"declared_citations":["L3-001"],"tags":["凸性"],"non_blocking":true}]'
            ),
        },
        "local_lemma_submissions": {
            "description": (
                "可选：活节点 70% 交班顺手独立拆交的局部引理列表（挂冻结快照建一次性盲审单，绝不锁死也不打断继续推进的原分支）。"
                "每项必填字段：title（引理标题）与 column_a_self_contained_proof_md（>=20字自包含证明正文）；"
                "可选：column_b_scope_notes_md、bound_obs_ids、artifact_rel_path。"
                "示例：[{\"title\":\"Lemma 1: 能量单调性\",\"column_a_self_contained_proof_md\":\"完整自包含证明（>=20字）...\",\"column_b_scope_notes_md\":\"适用边界\",\"bound_obs_ids\":[\"Obs001\"]}]。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "必填：局部引理标题。"},
                    "column_a_self_contained_proof_md": {
                        "type": "string",
                        "minLength": 20,
                        "description": "必填（>=20字）：自包含证明正文（严禁改名为 proof_md）。",
                    },
                    "column_b_scope_notes_md": {"type": "string", "description": "可选：适用范围与边界备注。"},
                    "bound_obs_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：绑定的实测 [Obs###] 编号列表。",
                    },
                    "artifact_rel_path": {"type": ["string", "null"], "description": "可选：对应代码/产物相对路径。"},
                },
                "required": ["title", "column_a_self_contained_proof_md"],
            },
        },
    },
    "submit_conference_statement": {
        "round_no": {"minimum": 1, "maximum": 4, "description": "第 1 轮自审与提案，第 2 轮及后续追问轮点对点回复（按本场 discussion_rounds 上限）。"},
        "statement_md": {"minLength": 20, "maxLength": 1200, "description": "提交本轮证据、接口与协作动作。"},
        "speech_act": {"enum": sorted(ALLOWED_CONFERENCE_SPEECH_ACTS), "description": "第 1 轮固定 PROPOSE_AND_SELF_AUDIT，第 2 轮及后续轮选择一种同行协作动作。"},
        "unverified_ideas": {"description": "未验证的设想或可供嫁接模块，内核加 [UNVERIFIED] 标记。"},
        "target_node_ids": {"description": "第 2 轮及后续轮参会人至少两名时，点名至少一位其他参会者。"},
    },
    "triage_node": {
        "triage_level": {"enum": sorted(ALLOWED_TRIAGE_LEVELS)},
        "action": {"enum": sorted(ALLOWED_TRIAGE_ACTIONS)},
    },
    "fork_branch": {
        "fork_mode": {"enum": sorted(ALLOWED_FORK_MODES)},
    },
    "publish_external_literature_card": {
        "outcome": {"enum": sorted(ALLOWED_SURVEY_OUTCOMES)},
        "read_depth": {"enum": [*sorted(ALLOWED_READ_DEPTHS), None]},
        "support_scope": {"enum": [*sorted(ALLOWED_SUPPORT_SCOPES), None]},
        "abstract_md": {"minLength": 60, "maxLength": 1200, "description": "文献高密度核心摘要（60–1200 字）。"},
    },
    "publish_living_survey": {
        "sec1_baseline_and_instruments_md": {"description": "栏1：当前最优已证实解与实验室可用仪器（四栏合计硬限 <= 4000 字）。"},
        "sec2_l3_lemma_tree_md": {"description": "栏2：已证实可复用的模块化引理索引。"},
        "sec3_avoidance_radar_md": {"description": "栏3：实锤死路禁区与反例摘要。"},
        "sec4_explicit_gaps_md": {"description": "栏4：Top 客观明确缺口导览与高优悬赏编号（严禁泄露他派未验真私有思路）。"},
        "marginal_notes_md": {"maxLength": 1500, "description": "边缘注记专栏，独立于核心四栏；含固定系统印章的合计上限 1500 字。"},
    },
    "export_stage3_final_delivery": {
        "delivery_mode": {"enum": sorted(ALLOWED_DELIVERY_MODES)},
    },
    "record_conference_minutes": {
        "minutes_md": {"maxLength": 6000, "description": "完整会议纪要，包含证据共识、接口缝隙与承重缺口。"},
    },
    "submit_conference_verdict": {
        "actions": {
            "description": (
                '示例：[{"action_type":"HIBERNATE","target_node_id":"node_q1_a","reason_md":"边际投入已枯竭","salvage_audit":true},'
                '{"action_type":"SPAWN_SYNTHESIS","primary_node_id":"node_q1_b","secondary_node_id":"node_q1_c",'
                '"target_family_id":"fam_q1_b","synthesis_goal_md":"拼接有限域与无界域的前提接口"},'
                '{"action_type":"DISCRIMINATOR","instrument_id":"inst_q1","probe_requirement_md":"区分两个构造的边界输入"},'
                '{"action_type":"CONVERGE_SUBPROBLEM","convergence_mode":"CONVERGE_FULL_COMPOSITE",'
                '"composite_entry_ids":["L3-001","L3-002"],"rationale_md":"核验两篇覆盖合并后的完成判据"}]'
            ),
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "enum": sorted(ALLOWED_WAVE_VERDICT_ACTIONS)},
                    "family_id": {"type": "string", "description": "开枝学派 ID。"},
                    "mechanism_signature": {"type": "string", "description": "开枝的方法机制。"},
                    "orthogonal_contrast": {"type": "string", "description": "开枝与现有方法的正交差异。"},
                    "gap_directive_md": {"type": "string", "description": "开枝对应的承重缺口与验证目标。"},
                    "requires": {"type": "array", "items": {"type": "string"}, "description": "可选：分支级精确前置依赖（L3-### 或 OBS:<instrument_id>:PASS）。"},
                    "source_node_id": {"type": "string", "description": "PROTECT 的来源节点。"},
                    "primary_node_id": {"type": "string", "description": "融合主供体。"},
                    "secondary_node_id": {"type": "string", "description": "融合副供体。"},
                    "target_family_id": {"type": "string", "description": "融合分支的已登记学派。"},
                    "synthesis_goal_md": {"type": "string", "description": "融合的具体目标与接口。"},
                    "budget_nodes": {"type": "integer", "minimum": 1, "description": "本波额度内的合体班岗预算。"},
                    "target_node_id": {"type": "string", "description": "休眠目标分支的代表节点。"},
                    "reason_md": {"type": "string", "description": "休眠的实证理由。"},
                    "salvage_audit": {"type": "boolean", "default": False, "description": "将可用局部成果送盲审打捞。"},
                    "instrument_id": {"type": "string", "description": "鉴别探针对应仪器。"},
                    "probe_requirement_md": {"type": "string", "description": "鉴别探针的证据需求。"},
                    "convergence_mode": {"type": "string", "enum": sorted(ALLOWED_CONVERGENCE_MODES)},
                    "composite_entry_ids": {"type": "array", "items": {"type": "string"}, "default": []},
                    "rationale_md": {"type": "string", "description": "收敛、保护或请示的依据。"},
                },
                "required": ["action_type"],
            },
        },
    },
    "submit_holiday_bet": {
        "anomaly_or_analogy_md": {"minLength": 30, "maxLength": 600, "description": "说明反常或跨领域类比。"},
        "testable_hypothesis_md": {"minLength": 30, "maxLength": 500, "description": "写出实测可证伪的假设。"},
        "falsification_experiment_md": {
            "minLength": 30, "maxLength": 500,
            "description": (
                '描述能推翻假设的判据。示例：{"node_id":"node_q1_a",'
                '"anomaly_or_analogy_md":"边界扰动导致状态突然转换，类似跨越相变阈值时的两类稳态结构。",'
                '"testable_hypothesis_md":"保持输入规模和求解费率固定时，转换只由指定边界距离触发。",'
                '"falsification_experiment_md":"用配对输入逐步扫描阈值两侧，如果远离阈值仍反复出现转换即推翻假设。"}'
            ),
        },
    },
    "request_internal_survey": {
        "query_md": {"minLength": 10, "maxLength": 1500, "description": "院内专题检索问题。"},
        "focus_scope": {"enum": sorted(ALLOWED_INTERNAL_SURVEY_SCOPES), "description": "限当前子题或跨子题。"},
    },
    "publish_internal_survey_report": {
        "report_md": {"minLength": 800, "maxLength": 4000, "description": "逐段引用实存编号的客观院内综述。"},
        "cited_entry_ids": {"description": "正文引用的 L3、L2 或 R 编号。"},
        "cited_obs_ids": {"description": "正文引用的有效正式观测编号。"},
    },
    "upgrade_instrument_with_calibration": {
        "resolved_ticket_ids": {"description": "本次升版明确修复的 OPEN 工单编号。"},
        "upgrade_summary_md": {"description": "点名自动结案时必填的修复与校准说明。"},
    },
    "submit_stage1_blind_ledger": {
        "rigor_score": {"minimum": 1, "maximum": 10, "description": "阶段一锁定的严密性分；PASS 或 PARTIAL_PASS 须 >=7。"},
        "ledger_items": {
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence_location_and_quote": {"type": "string"},
                    "sandbox_check_cmd_or_note": {"type": ["string", "null"]},
                    "is_verified": {"type": "boolean"},
                },
                "required": ["claim", "evidence_location_and_quote"],
            },
        },
        "stage1_verdict": {
            "enum": sorted(ALLOWED_STAGE1_VERDICTS),
            "description": "Stage 1 裁决：PASS | PARTIAL_PASS（主结论击穿但局部引理严密，进 Stage 2 判 ACCEPT_NARROWED）| REVISE | REFUTED。",
        },
    },
    "submit_stage2_unblind_verdict": {
        "novelty_score": {"description": "新颖性 1–10；低于 4 且无实质精简，查重退稿。"},
        "significance_score": {"description": "重要性 1–10；低于 5 强制收为 MARGINAL_NOTE。"},
        "reviewer_comment_md": {"description": "公开审稿附页，按承重缺口与改良项说明。"},
        "confirmed_citations": {"description": "确认实存的馆藏或外藏引用编号。"},
        "is_equivalent_reduction": {
            "description": "等价归约时勾选。低新颖分稿须在 cross_draft_comparison_notes 说明具体至少 20% 的实质精简。",
        },
        "final_verdict": {"enum": sorted(ALLOWED_FINAL_VERDICTS)},
        "l3_entry_kind": {"enum": [*sorted(ALLOWED_L3_ENTRY_KINDS), None]},
        "goal_coverage": {"enum": [*sorted(ALLOWED_GOAL_COVERAGES), None]},
        "publish_tier": {"enum": [*sorted(ALLOWED_PUBLISH_TIERS), None]},
        "edge_type_overrides": {
            "description": f"按引用 ID 升级承重前提边类型，合法值 {sorted(ALLOWED_CLAIMED_EDGE_TYPES)}。",
        },
    },
    "register_question_instrument": {
        "instrument_role": {"enum": sorted(ALLOWED_INSTRUMENT_ROLES)},
    },
    "resolve_works_ticket": {
        "resolution": {"enum": sorted(ALLOWED_TICKET_RESOLUTIONS)},
    },
    "check_stage2_closure_gate": {
        "mode": {"enum": sorted(ALLOWED_DELIVERY_MODES)},
    },
    "record_compliance_check": {
        "stage": {"enum": sorted(ALLOWED_COMPLIANCE_STAGES)},
        "status": {"enum": sorted(ALLOWED_COMPLIANCE_STATUSES)},
    },
}


def enrich_tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为全量窄工具 JSON Schema 统一注入中文说明、权威枚举与内嵌对象结构。"""
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
                    if not pdef.get("description"):
                        pdef["description"] = f"参数 {pname}。"
        enriched.append(t)
    return enriched
