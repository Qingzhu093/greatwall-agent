#!/usr/bin/env python3
"""
Great Wall Agent V4.2 — Pure Python Stdio MCP Server for Google Antigravity
===========================================================================
零第三方依赖（100% Python 标准库），通过 JSON-RPC 2.0 over Stdio 向 Antigravity 暴露 8 个核心工具：
1. gw_init_campaign      : 初始化无人值守攻关工作区与多模态数据探针清点 (Phase 0 消歧锁定)
2. gw_lock_distillation  : 固化开局知识蒸馏四件套并实跑铸造【零号强基线 s_0】
3. gw_allocate_slot      : 分配无 .git 的清洁室探索孤岛槽位并自动注入 L1 专属启动简报
4. gw_surgical_replace   : MLE-STAR 式局部代码块 AST 微创热插拔替换 (防全量重写崩溃)
5. gw_evaluate_slot      : 跨进程隔离评测 + AST 反作弊/防泄漏对账 + HMAC 签名成绩单
6. gw_submit_legacy      : 校验节点五件套遗产包入库 (含原语单测验证)、更新榜单并五步墓碑回收孤岛
7. gw_archive_query      : 按需读取 L0 索引、L2 单点详情或触发错误结论依赖树撤回 (Retraction Tree)
8. gw_compile_delivery   : 终局防吹牛数字硬绑定审计并打包标准五件套交付目录 (final_delivery/)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List

# 将插件根目录加入 sys.path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from lib.engine import GreatWallEngine
from lib.evaluator import ASTCodeInspector


TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "gw_init_campaign",
        "description": "【Phase 0 第一步】初始化长城 Agent V4.2 无人值守攻关工作区：自动扫描多模态数据资产，锁死题面消歧结论 (task_config.yaml)，建立 .kernel_vault、shared_readonly/archive 与 worktrees 清洁室目录树。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {
                    "type": "string",
                    "description": "攻关任务工作区根目录路径（默认使用当前工作区）",
                },
                "taskId": {
                    "type": "string",
                    "description": "任务唯一标识（如 CUMCM_2026_B 或 KAGGLE_MOL_01）",
                },
                "taskDescription": {
                    "type": "string",
                    "description": "赛题或科学攻关任务的核心目标与硬性边界说明",
                },
                "domainType": {
                    "type": "string",
                    "enum": ["ALGO_COMPETITION", "FORMAL_MATH", "PHYSICS_SIM", "BIO_CHEM"],
                    "description": "任务所属学科领域类型（决定验证经济学策略）",
                },
                "primaryMetric": {
                    "type": "string",
                    "description": "主评测指标名称（如 RMSLE, Accuracy, TotalCost, Score）",
                },
                "higherIsBetter": {
                    "type": "boolean",
                    "description": "主评测指标是否越大越好（默认 true；若为误差/耗时则传 false）",
                },
                "maxConcurrentSlots": {
                    "type": "integer",
                    "description": "最大并发工作槽位数（默认 4）",
                },
                "resolvedAmbiguities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "resolution": {"type": "string"},
                            "resolved_by": {"type": "string"},
                        },
                    },
                    "description": "开局前置消歧锁定的规则问答列表（严禁在盘中分裂 A/~A 歧义分支）",
                },
            },
            "required": ["workspaceRoot", "taskId", "taskDescription"],
        },
    },
    {
        "name": "gw_lock_distillation",
        "description": "【Phase 0 第二步】固化开局先蒸馏（Opening Distillation）四件套成果：写入现代正交 SOTA 方法族、过时模型禁用黑名单、调库 vs 造轮子边界清单、防踩坑红线卡，并在清洁室沙箱中实跑验分铸造【零号强基线 s_0】。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {
                    "type": "string",
                    "description": "攻关任务工作区根目录路径",
                },
                "orthogonalFamilies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "family_id": {"type": "string"},
                            "family_name": {"type": "string"},
                            "core_libraries": {"type": "array", "items": {"type": "string"}},
                            "key_mechanism": {"type": "string"},
                            "custom_zone": {"type": "string"},
                        },
                        "required": ["family_id", "family_name"],
                    },
                    "description": "开局拆分的 2~4 个正交现代 SOTA 方法族列表",
                },
                "anchorBaselineCode": {
                    "type": "string",
                    "description": "零号强基线 s_0 的完整可运行 Python 源码（将自动写入 src/main.py 并在沙箱实跑测定基准分）",
                },
                "obsoleteBlacklist": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "反预训练熟悉度偏见黑名单（严禁作为主模型刷分的陈旧方案）",
                },
                "mustReuseLibraries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "强制直接调库复用、严禁手搓重复造轮子的基础设施列表",
                },
                "pitfallGuardrails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本任务防数据泄漏与多源数据完整性红线列表",
                },
            },
            "required": ["workspaceRoot", "orthogonalFamilies", "anchorBaselineCode"],
        },
    },
    {
        "name": "gw_allocate_slot",
        "description": "【内层循环 Step 1】分配一个无 .git 的清洁室孤岛槽位（worktrees/slot_xx_node_yy/）：从内核快照库检出基底代码，并自动装配 L1 专属启动简报（scoped_brief.md，含锁定代码块 c_t、上代墓志铭与可直接 import 的原语签名表）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "familyId": {"type": "string", "description": "绑定的正交方法族 ID（如 FAM-01）"},
                "targetedCodeBlock": {
                    "type": "string",
                    "description": "本轮外层消融锁定的单一微创手术目标函数或类名 c_t",
                },
                "hypothesis": {
                    "type": "string",
                    "description": "本节点要验证的具体可证伪算法改进假说",
                },
                "parentCommit": {
                    "type": "string",
                    "description": "可选：指定派生的父快照 Commit ID（默认继承本方法族最新最优 Commit 或 s_0）",
                },
                "stepBudget": {
                    "type": "integer",
                    "description": "分配给本节点的沙箱微循环步数配额（默认 25）",
                },
                "isUnboundJunior": {
                    "type": "boolean",
                    "description": "是否作为不挂载历史旧包袱的‘初级独立探索席位 (Unbound Junior)’启动（默认 false）",
                },
            },
            "required": ["workspaceRoot", "familyId", "targetedCodeBlock", "hypothesis"],
        },
    },
    {
        "name": "gw_surgical_replace",
        "description": "【内层循环 Step 2】MLE-STAR 式局部代码块 AST 微创热插拔替换：冻结脚本其余全部外围代码，仅精准定位并替换目标函数或类定义 `targetBlockName`，并自动验证全文件 AST 语法，彻底消除全量重写引发的崩溃。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "slotId": {"type": "string", "description": "目标活跃槽位 ID（如 slot_01_node-001）"},
                "targetBlockName": {
                    "type": "string",
                    "description": "要原位替换或新增的目标函数名/类名（如 extract_features 或 solve）",
                },
                "newBlockCode": {
                    "type": "string",
                    "description": "该目标函数或类的完整新 Python 代码块定义",
                },
                "relScriptPath": {
                    "type": "string",
                    "description": "相对于孤岛根目录的脚本路径（默认 src/main.py）",
                },
            },
            "required": ["workspaceRoot", "slotId", "targetBlockName", "newBlockCode"],
        },
    },
    {
        "name": "gw_evaluate_slot",
        "description": "【内层循环 Step 3 & 独立审计环】对指定槽位执行 AST 静态反作弊/防泄漏/结构改动率对账、四元组剥皮查新与跨进程物理隔离评测（含同构扰动防背题检验），并在 legacy_out/metrics_receipt.json 生成带 HMAC-SHA256 签名的防伪成绩单与四级分诊结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "slotId": {"type": "string", "description": "待评测的活跃槽位 ID"},
                "entryScript": {"type": "string", "description": "入口脚本相对路径（默认 src/main.py）"},
                "claimedSweptVariables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：节点声称进行了动态探索/消融的控制变量名列表（AST 将校验其是否被写死为静态常数）",
                },
                "operatorDescription": {
                    "type": "string",
                    "description": "可选：节点自述的核心数学算子机制说明（用于剥皮查新并与《教科书常识黑名单》比对）",
                },
                "timeoutSec": {
                    "type": "number",
                    "description": "单次评测超时秒数（默认 120 秒）",
                },
            },
            "required": ["workspaceRoot", "slotId"],
        },
    },
    {
        "name": "gw_submit_legacy",
        "description": "【节点退场交卷】严格验收探索节点在 legacy_out/ 下留下的【五件套遗产包】（150字墓志铭、HMAC签名成绩单、带单测的可复用原语 primitives/*.py、悬赏卡、1~3条临终接力遗嘱单），通过后入库轻量档案馆、更新排行榜与 60 步内省计数，并调用五步墓碑算法安全回收孤岛目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "slotId": {"type": "string", "description": "申请交卷释放的槽位 ID"},
                "stepsConsumed": {
                    "type": "integer",
                    "description": "本节点实际消耗的探索步数（默认 15，用于累计 60 步导师深挖承诺与触发原位内省室）",
                },
            },
            "required": ["workspaceRoot", "slotId"],
        },
    },
    {
        "name": "gw_archive_query",
        "description": "【轻量级档案馆按需检索】支持读取 L0 全局目录索引（ARCHIVE_INDEX.md + PRIMITIVES_API.md）、按 ID 点读 L2 原语/引理/死胡同详情、查看全局状态与待排期遗嘱队列，或触发错误结论依赖树局部撤回（Retraction Tree）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "action": {
                    "type": "string",
                    "enum": ["get_l0_index", "get_l2_item", "get_campaign_status", "retract_claim"],
                    "description": "查询动作类型",
                },
                "familyId": {
                    "type": "string",
                    "description": "可选：在 get_l0_index 时按指定方法族过滤死胡同记录",
                },
                "itemId": {
                    "type": "string",
                    "description": "在 get_l2_item 或 retract_claim 时指定的条目编号（如 REC-001, CLM-002, 或原语模块名）",
                },
                "retractReason": {
                    "type": "string",
                    "description": "在 retract_claim 时说明证伪或撤回的具体原因",
                },
            },
            "required": ["workspaceRoot", "action"],
        },
    },
    {
        "name": "gw_compile_delivery",
        "description": "【Phase 4 终局交付】执行终局防吹牛审计（拦截 TODO/TBD/Conclusions Here 占位符残留，强制从 HMAC 签名收据硬绑定生成全套得分对比表），并编译标准五件套终局交付目录 final_delivery/。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspaceRoot": {"type": "string", "description": "工作区根目录路径"},
                "executiveSummaryMd": {
                    "type": "string",
                    "description": "终局研究报告的核心方法论、理论分析与消融结论正文（Markdown 格式，严禁含未填占位符）",
                },
            },
            "required": ["workspaceRoot", "executiveSummaryMd"],
        },
    },
]


def handle_tool_call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    workspace_root = args.get("workspaceRoot") or os.getcwd()
    engine = GreatWallEngine(workspace_root)

    if name == "gw_init_campaign":
        return engine.init_campaign(
            task_id=str(args["taskId"]),
            task_description=str(args["taskDescription"]),
            domain_type=str(args.get("domainType", "ALGO_COMPETITION")),
            primary_metric=str(args.get("primaryMetric", "score")),
            higher_is_better=bool(args.get("higherIsBetter", True)),
            max_concurrent_slots=int(args.get("maxConcurrentSlots", 4)),
            resolved_ambiguities=args.get("resolvedAmbiguities"),
        )

    if name == "gw_lock_distillation":
        return engine.lock_opening_distillation(
            orthogonal_families=list(args["orthogonalFamilies"]),
            anchor_baseline_code=str(args["anchorBaselineCode"]),
            obsolete_blacklist=args.get("obsoleteBlacklist"),
            must_reuse_libraries=args.get("mustReuseLibraries"),
            pitfall_guardrails=args.get("pitfallGuardrails"),
        )

    if name == "gw_allocate_slot":
        return engine.allocate_exploration_slot(
            family_id=str(args["familyId"]),
            targeted_code_block=str(args["targetedCodeBlock"]),
            hypothesis=str(args["hypothesis"]),
            parent_commit=args.get("parentCommit"),
            step_budget=int(args.get("stepBudget", 25)),
            is_unbound_junior=bool(args.get("isUnboundJunior", False)),
        )

    if name == "gw_surgical_replace":
        return engine.surgical_replace_in_slot(
            slot_id=str(args["slotId"]),
            target_block_name=str(args["targetBlockName"]),
            new_block_code=str(args["newBlockCode"]),
            rel_script_path=str(args.get("relScriptPath", "src/main.py")),
        )

    if name == "gw_evaluate_slot":
        return engine.evaluate_slot(
            slot_id=str(args["slotId"]),
            entry_script=str(args.get("entryScript", "src/main.py")),
            claimed_swept_variables=args.get("claimedSweptVariables"),
            operator_description=str(args.get("operatorDescription", "")),
            timeout_sec=float(args.get("timeoutSec", 120.0)),
        )

    if name == "gw_submit_legacy":
        return engine.submit_legacy_and_release_slot(
            slot_id=str(args["slotId"]),
            steps_consumed=int(args.get("stepsConsumed", 15)),
        )

    if name == "gw_archive_query":
        action = str(args["action"])
        if action == "get_l0_index":
            l0_md = engine.archive.rebuild_l0_index(target_family_id=args.get("familyId"))
            return {"status": "OK", "l0_index_markdown": l0_md}
        if action == "get_l2_item":
            return engine.archive.query_l2_item(str(args.get("itemId", "")))
        if action == "get_campaign_status":
            return {"status": "OK", "campaign_state": engine.load_state()}
        if action == "retract_claim":
            affected = engine.archive.retract_claim(
                target_claim_id=str(args.get("itemId", "")),
                reason=str(args.get("retractReason", "Counterexample found")),
            )
            return {"status": "OK", "retracted_and_invalidated_ids": affected}
        raise ValueError(f"未知的 gw_archive_query action: {action}")

    if name == "gw_compile_delivery":
        return engine.compile_final_delivery(
            executive_summary_md=str(args["executiveSummaryMd"]),
        )

    raise ValueError(f"未知的 MCP 工具名称: {name}")


def send_jsonrpc(req_id: Any, result: Any = None, error: Any = None) -> None:
    resp: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    # 强制 UTF-8 标准输入输出，防止 Windows 终端中文乱码
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            send_jsonrpc(None, error={"code": -32700, "message": "JSON Parse error"})
            continue

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        if method == "initialize":
            send_jsonrpc(
                req_id,
                result={
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "greatwall-agent",
                        "version": "4.2.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                },
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send_jsonrpc(req_id, result={"tools": TOOLS_SCHEMA})
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments") or {}
            try:
                out = handle_tool_call(tool_name, tool_args)
                send_jsonrpc(
                    req_id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(out, ensure_ascii=False, indent=2),
                            }
                        ],
                        "isError": False,
                    },
                )
            except Exception as e:
                send_jsonrpc(
                    req_id,
                    result={
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "status": "ERROR",
                                        "message": str(e),
                                        "traceback": traceback.format_exc(),
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                            }
                        ],
                        "isError": True,
                    },
                )
        elif req_id is not None:
            send_jsonrpc(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
