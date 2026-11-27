"""GreatWall Agent v0.3 全量窄 MCP 工具 JSON Schema 中文说明与权威枚举绑定（100% 同源 db_schema.py）。"""

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
    "cross_draft_comparison_notes": "与同题既有 L3/L2 馆藏的横向对照与去重说明。",
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
            "description": "统一资源 URI：survey/<Q> | node/<id>/manuscript | node/<id>/briefing | node/<id>/transcript | review/<id>/ledger | conference/<id>/minutes | entry/<id> | receipt/<op_id> | archive/<epoch_id>/<上述任一路径>。",
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
                "submit_ticket",
                "recover_queue",
                "pin_note",
            ],
            "description": "8 类日常运维直执原语枚举。",
        },
        "arrangement": {"description": "单条运行安排补丁（含 scope_type、target_id、dispatch_policy、priority_weight、max_active_branches、max_concurrent_workers、inflight_drain_mode、ends_on_kind/expires_at 等）。"},
        "arrangements": {"description": "多条运行安排列表（同一人类意图涉及多个子题时一次原子提交）。"},
        "node_action": {"description": "点名分支动作（node_ids + mode: retire|hibernate|pause_takeover|resume|early_handoff|reactivate + 可选 archive_family/reason）。"},
        "handback_id": {"description": "可选：人类在探索者窗口发起并转办至总控的一次性授权凭证 ID。"},
        "details": {"description": "扩展操作参数（如 revoke_arrangement 的 arrangement_id、family_manage 的 family_id/mode、submit_ticket 的 ticket_type/description、pin_note 的 content_md 等）。"},
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
        "holiday_prompt_id": {"minimum": 1, "maximum": 28, "description": "夜科学启发题编号（1–28）。"},
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
        "local_lemma_submissions": {
            "description": "可选：活节点 70% 交班顺手独立拆交的局部引理列表（挂冻结快照建一次性盲审单，绝不锁死也不打断继续推进的原分支）。",
        },
    },
    "submit_conference_statement": {
        "round_no": {"minimum": 1, "maximum": 2, "description": "圆桌轮次：1（互挑刺）或 2（回应辩护）。"},
        "statement_md": {"minLength": 20, "description": "点对点红蓝交锋发言正文（>=20 字）。"},
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
        "sec1_baseline_and_instruments_md": {"description": "栏1：当前最优已证实解与实验室可用仪器（四栏合计硬限 <= 1500 字）。"},
        "sec2_l3_lemma_tree_md": {"description": "栏2：已证实可复用的模块化引理索引。"},
        "sec3_avoidance_radar_md": {"description": "栏3：实锤死路禁区与反例摘要。"},
        "sec4_explicit_gaps_md": {"description": "栏4：Top 客观明确缺口导览与高优悬赏编号（严禁泄露他派未验真私有思路）。"},
    },
    "export_stage3_final_delivery": {
        "delivery_mode": {"enum": sorted(ALLOWED_DELIVERY_MODES)},
    },
    "submit_conference_verdict": {
        "actions": {
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": sorted(ALLOWED_WAVE_VERDICT_ACTIONS)},
                },
                "required": ["action"],
            },
            "description": "6 类宏观树结构调整动作列表。",
        },
    },
    "submit_stage1_blind_ledger": {
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
