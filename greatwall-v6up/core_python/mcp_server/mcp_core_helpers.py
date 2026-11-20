"""V6-Up (v2.2) MCP 核心辅助引擎：

- 7 大标准角色契约与 31 个单一职责窄工具白名单校验；
- 500,000 Token 物理真时钟（pressure_tokens / 500000）、_noise_phrase 噪声预警与 _cache_advice Cost Note；
- 统一 JSON 回执 Schema（§0.1）与 [JIT-Guidance] 路标封装；
- 五段定额预算看板校验（200/400/350/650/400 <= 2200 字，禁切片截断）；
- AST 基线物理隔离检查（防跨子题机制串味）；
- RQGM Beta 逆 CDF (BB_epsilon) 与对抗池 Q_P 数学内核。
"""

from __future__ import annotations

import ast
import json
import math
import random
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .db_schema import (
    ALLOWED_CLAIMED_EDGE_TYPES,
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_EXECUTION,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    ERR_NOT_FOUND,
    ERR_STORAGE,
    FailClosedError,
    resolve_ref_target,
    utc_now_iso,
)

CANONICAL_ROLES: frozenset[str] = frozenset(
    {
        "explorer",
        "lineage_companion",
        "logistics_coordinator",
        "library_surveyor",
        "library_verifier",
        "works_engineer",
        "supervisory_committee",
    }
)

ALLOWED_TOOLS_BY_ROLE: dict[str, frozenset[str]] = {
    "explorer": frozenset(
        {
            "run_isolated_eval",
            "query_library_catalog",
            "get_library_entry",
            "request_literature_survey",
            "read_lineage_graph",
        }
    ),
    "lineage_companion": frozenset(
        {
            "get_companion_context",
            "save_lineage_briefing",
            "record_reflection_and_unlock_pull",
            "submit_node_handoff",
        }
    ),
    "logistics_coordinator": frozenset(
        {
            "get_logistics_dashboard",
            "register_method_family",
            "triage_node",
            "fork_branch",
            "dispatch_stagnation_five_lanes",
        }
    ),
    "library_surveyor": frozenset(
        {
            "get_survey_requests",
            "publish_external_literature_card",
            "export_stage3_final_delivery",
        }
    ),
    "library_verifier": frozenset(
        {
            "get_blind_manuscript",
            "submit_stage1_blind_ledger",
            "get_unblinded_manuscript_and_peers",
            "submit_stage2_unblind_verdict",
            "propose_salvaged_lemma",
        }
    ),
    "works_engineer": frozenset(
        {
            "get_works_engineering_queue",
            "register_question_domain_hook",
            "upgrade_hook_with_rqgm_gate",
            "recompute_stage_b_only",
            "update_skill_ledger",
        }
    ),
    "supervisory_committee": frozenset(
        {
            "get_supervisory_audit_snapshot",
            "check_stage2_closure_gate",
            "record_compliance_check",
            "register_saved_graph_query",
        }
    ),
}

ALL_31_TOOL_NAMES: frozenset[str] = frozenset().union(*ALLOWED_TOOLS_BY_ROLE.values())

VALID_FORK_MODES = frozenset({"orthogonal", "lateral", "cross_pollinate"})
VALID_STAGNATION_LANES = frozenset(
    {"EXPLORATION", "EXPLOITATION", "REVIVAL", "UNDERSTANDING", "STRATEGY"}
)
VALID_VERDICT_3STATE = frozenset(
    {"SUFFICIENT_EVIDENCE", "MINIMAL_EXPERIMENT_NEXT", "NEED_CONTROL_GROUP"}
)

_HIDDEN_KEY_EXACT = frozenset(
    {
        "ground_truth",
        "reference_u_final",
        "reference_frontier",
        "nadir_secret",
        "expected_theorem_sha256",
        "expected_theorem_statement",
        "allowed_external_axioms",
        "r_nadir",
        "domain_hook_path",
    }
)


def core_python_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_runtime_config() -> dict[str, Any]:
    """读取 core_python/config.json 并与 v2.2 基准默认值合并。"""
    defaults: dict[str, Any] = {
        "context_window_tokens": 500000,
        "clock_formula": "pressureTokens / 500000",
        "min_evals_before_reflection": 1,
        "context_reflect_hint_pct": 0.37,
        "context_handoff_pct": 0.70,
        "reflection_sequential_turn_boundary": True,
        "reflection_max_turns": 2,
        "reflection_max_chars_per_turn": 300,
        "cost_note_enable": True,
        "max_handoff_chars": 2000,
        "max_briefing_chars": 2200,
        "briefing_section_char_budgets": {
            "sec1_mechanism": 200,
            "sec2_verified_baseline": 400,
            "sec3_bottleneck": 350,
            "sec4_dead_ends": 650,
            "sec5_immediate_will": 400,
        },
        "max_concurrent_workers": 6,
        "max_concurrent_workers_hard_cap": 10,
        "min_initial_method_families_per_question": 2,
        "stagnation_consecutive_non_l1_handoffs": 8,
        "level2_max_inplace_repairs": 3,
        "simulator_fidelity_max_error_pct": 5.0,
        "hard_lock_closure_min_l3_verified_per_question": 1,
        "eval_anchor_epsilon": 0.05,
        "eval_anchor_min_samples": 5,
    }
    cfg_path = core_python_root() / "config.json"
    if cfg_path.is_file():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            for sec in ("session_context_clock", "orchestration_and_eval"):
                sub = raw.get(sec)
                if isinstance(sub, dict):
                    defaults.update(sub)
        except Exception:
            pass
    return defaults


def normalize_role(role: str) -> str:
    key = (role or "").strip().lower()
    if key not in CANONICAL_ROLES:
        raise FailClosedError(
            ERR_AUTH,
            f"未知或已废除角色 {role!r}，v2.2 唯一合法角色为 {sorted(CANONICAL_ROLES)}",
        )
    return key


def enforce_role_tool_permission(
    conn: sqlite3.Connection | None,
    caller_role: str,
    tool_name: str,
    session_id: str = "",
    node_id: str = "",
) -> str:
    role = normalize_role(caller_role)
    allowed = ALLOWED_TOOLS_BY_ROLE.get(role, frozenset())
    if tool_name not in allowed:
        if conn is not None:
            try:
                record_fact_edge(
                    conn,
                    src_id=session_id or role,
                    dst_id=f"tool:{tool_name}",
                    edge_type="UNAUTHORIZED_TOOL_ATTEMPT",
                    metadata={"role": role, "node_id": node_id},
                )
            except Exception:
                pass
        raise FailClosedError(
            ERR_AUTH,
            f"权责门禁阻断：角色 {role!r} 无权调用窄工具 {tool_name!r}，仅允许 {sorted(allowed)}",
        )
    return role


def record_fact_edge(
    conn: sqlite3.Connection,
    src_id: str,
    dst_id: str,
    edge_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO epistemic_edges(edge_id, src_id, dst_id, edge_track, edge_type, metadata_json, created_at)
        VALUES (?, ?, ?, 'FACT_LOG', ?, ?, ?)
        """,
        (
            f"fe_{uuid.uuid4().hex[:14]}",
            src_id,
            dst_id,
            edge_type,
            json.dumps(metadata or {}, ensure_ascii=False),
            utc_now_iso(),
        ),
    )


def record_claim_edge(
    conn: sqlite3.Connection,
    src_id: str,
    dst_id: str,
    edge_type: str = "REQUIRED_PREMISE",
    metadata: dict[str, Any] | None = None,
) -> None:
    etype = edge_type if edge_type in ALLOWED_CLAIMED_EDGE_TYPES else "REQUIRED_PREMISE"
    conn.execute(
        """
        INSERT INTO epistemic_edges(edge_id, src_id, dst_id, edge_track, edge_type, metadata_json, created_at)
        VALUES (?, ?, ?, 'CLAIM_DECLARED', ?, ?, ?)
        """,
        (
            f"ce_{uuid.uuid4().hex[:14]}",
            src_id,
            dst_id,
            etype,
            json.dumps(metadata or {}, ensure_ascii=False),
            utc_now_iso(),
        ),
    )


def strip_hidden_recursive(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            if ks in _HIDDEN_KEY_EXACT or ks.startswith(("hidden_", "secret_")):
                continue
            cleaned[k] = strip_hidden_recursive(v)
        return cleaned
    if isinstance(obj, list):
        return [strip_hidden_recursive(item) for item in obj]
    return obj


def build_state_snapshot(conn: sqlite3.Connection, node_id: str = "", question_id: str = "") -> dict[str, Any]:
    cfg = load_runtime_config()
    window = int(cfg["context_window_tokens"])
    if node_id:
        row = conn.execute(
            """
            SELECT question_id, branch_id, node_id, node_status, pressure_tokens, eval_count, first_reflection_unlocked
            FROM lineage_nodes WHERE node_id = ?
            """,
            (node_id,),
        ).fetchone()
        if row is not None:
            pt = int(row["pressure_tokens"] or 0)
            return {
                "question_id": str(row["question_id"]),
                "branch_id": str(row["branch_id"]),
                "node_id": str(row["node_id"]),
                "node_status": str(row["node_status"]),
                "pressure_tokens": pt,
                "context_window_tokens": window,
                "pressure_pct": round(pt / float(window), 4),
                "eval_count": int(row["eval_count"] or 0),
                "first_reflection_unlocked": int(row["first_reflection_unlocked"] or 0),
            }
    return {
        "question_id": question_id or "GLOBAL",
        "branch_id": "",
        "node_id": node_id or "",
        "node_status": "",
        "pressure_tokens": 0,
        "context_window_tokens": window,
        "pressure_pct": 0.0,
        "eval_count": 0,
        "first_reflection_unlocked": 0,
    }


def build_tool_receipt(
    *,
    conn: sqlite3.Connection,
    tool_name: str,
    data: Any,
    next_step_guidance: str,
    warnings: list[str] | None = None,
    node_id: str = "",
    question_id: str = "",
    ok: bool = True,
) -> dict[str, Any]:
    """构造完全符合 agent_kb/05 §0.1 的统一工具回执载荷。"""
    return {
        "ok": ok,
        "tool": tool_name,
        "state_snapshot": build_state_snapshot(conn, node_id=node_id, question_id=question_id),
        "data": data,
        "warnings": list(warnings or []),
        "next_step_guidance": (
            next_step_guidance
            if next_step_guidance.startswith("[JIT-Guidance]")
            else f"[JIT-Guidance] {next_step_guidance}"
        ),
    }


def compute_clock_warnings_and_guidance(
    conn: sqlite3.Connection, node_id: str, new_score: float | None = None
) -> tuple[list[str], str, dict[str, Any]]:
    """依据 pressure_tokens / 500,000 + eval_count 计算 _noise_phrase、_cache_advice 与准确路标。"""
    cfg = load_runtime_config()
    window = int(cfg["context_window_tokens"])
    min_evals = int(cfg["min_evals_before_reflection"])
    reflect_pct = float(cfg["context_reflect_hint_pct"])
    handoff_pct = float(cfg["context_handoff_pct"])

    node = conn.execute(
        "SELECT question_id, pressure_tokens, eval_count, first_reflection_unlocked FROM lineage_nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if node is None:
        return [], "继续依据观测残差决定微创修正或换机制。", {"trigger": "NONE"}

    qid = str(node["question_id"])
    pt = int(node["pressure_tokens"] or 0)
    ec = int(node["eval_count"] or 0)
    unlocked = int(node["first_reflection_unlocked"] or 0)
    pct = pt / float(window)

    warnings: list[str] = []

    # 1. _noise_phrase：计算中位数突变步长，预警微小数值波动
    if new_score is not None:
        hist = conn.execute(
            """
            SELECT comparable_rank_score FROM observations
            WHERE question_id = ? AND obs_status = 'VALID' AND comparable_rank_score IS NOT NULL
            ORDER BY created_at DESC LIMIT 20
            """,
            (qid,),
        ).fetchall()
        vals = [float(r["comparable_rank_score"]) for r in hist]
        if len(vals) >= 4:
            diffs = sorted(abs(vals[i] - vals[i + 1]) for i in range(len(vals) - 1) if abs(vals[i] - vals[i + 1]) > 0)
            if diffs:
                median_step = diffs[len(diffs) // 2]
                cur_delta = abs(float(new_score) - vals[1]) if len(vals) >= 2 else abs(float(new_score) - vals[0])
                if cur_delta < 0.25 * median_step and median_step > 1e-12:
                    warnings.append(
                        f"[_noise_phrase] 当前指标变化 ({cur_delta:.5g}) 显著小于图谱中位数突变步长 ({median_step:.5g})，高度疑似数值噪声而非机理突破"
                    )

    # 2. _cache_advice：连续 >= 4 次无明显进展时建议 Cost Note 交接
    recent_obs = conn.execute(
        """
        SELECT obs_status, passed, comparable_rank_score FROM observations
        WHERE node_id = ? ORDER BY created_at DESC LIMIT 5
        """,
        (node_id,),
    ).fetchall()
    cost_note_hit = False
    if len(recent_obs) >= 4:
        no_pass_streak = all(int(r["passed"] or 0) == 0 for r in recent_obs[:4])
        if no_pass_streak and pct >= 0.45:
            cost_note_hit = True
            warnings.append(
                "[_cache_advice] 连续 4 次评估无新通过实证且 KV-Cache 重读历史成本已高，建议启动 Cost Note 交接"
            )

    # 3. 三段状态迁移路标
    if pct >= handoff_pct or cost_note_hit:
        guidance = (
            "已达 70% / Cost Note 停笔线！请立即停止改码，整理本轮核心结论与 [Local-Sweep] 边界并在回复末尾宣告 READY_FOR_HANDOFF，由伴随助手接手写入谱系 DAG。"
        )
        signal = {"trigger": "HANDOFF_70", "pressure_pct": pct, "cost_note": cost_note_hit}
    elif pct >= reflect_pct and ec >= min_evals and unlocked == 0:
        guidance = (
            "评测已完成（成绩单见 data）。当前上下文占比已达 37%，回合结束后控制面将顺序切入伴随助手进行 2 轮 <=300 字元反思问答，完成后当场为你解锁内藏 L3/L2 与本脉谱系 DAG！"
        )
        signal = {"trigger": "REFLECT_37", "pressure_pct": pct, "eval_count": ec}
    elif unlocked == 0:
        guidance = (
            f"当前位于 0-37% 净室独思期（占比 {pct:.1%}）。请对比事前预测与实测分项残差，决定微创修正或换机制；需要基础文献可随时调 query_library_catalog(scope='EXTERNAL_R')。"
        )
        signal = {"trigger": "PHASE_A", "pressure_pct": pct}
    else:
        guidance = (
            f"当前位于 37-70% 开放攻坚期（占比 {pct:.1%}，内藏 L3/L2 与本脉 DAG 已解锁）。可结合 query_library_catalog(scope='ALL') 与 read_lineage_graph 深化验证，或沉淀通用模块至 tools/。"
        )
        signal = {"trigger": "PHASE_C", "pressure_pct": pct}

    return warnings, guidance, signal


def load_holiday_prompts(scope_filter: str = "reflect_37") -> list[dict[str, Any]]:
    """读取 core_python/prompts/holiday_prompts.yaml（29 条夜科学完整题库）。"""
    yaml_path = core_python_root() / "prompts" / "holiday_prompts.yaml"
    if not yaml_path.is_file():
        return []
    items: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for raw in yaml_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- id:"):
            if cur:
                items.append(cur)
            cur = {"id": int(line.split(":", 1)[1].strip())}
        elif line.startswith("scope:") and cur:
            cur["scope"] = line.split(":", 1)[1].strip()
        elif line.startswith("text:") and cur:
            val = line.split(":", 1)[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            cur["text"] = val
    if cur:
        items.append(cur)
    if scope_filter:
        return [it for it in items if it.get("scope") == scope_filter]
    return items


def sample_holiday_candidates_for_reflect37(count: int = 2, seed: int | None = None) -> list[dict[str, Any]]:
    """控制面从夜科学 1–28 条中随机抽取 1–2 条推给 REFLECT_37 伴随助手（严禁 29 条全量灌注）。"""
    pool = load_holiday_prompts(scope_filter="reflect_37")
    if not pool:
        return []
    rng = random.Random(seed) if seed is not None else random.Random()
    k = max(1, min(2, count, len(pool)))
    return rng.sample(pool, k=k)


def validate_baseline_isolation_ast(baseline_file: Path, question_id: str) -> None:
    """P24 根治：AST 扫描子题基线，拦截跨子题机理或代码串味（如 baseline_Q3 混入 Q4 / second_pass）。"""
    if not baseline_file.is_file():
        raise FailClosedError(ERR_NOT_FOUND, f"基线文件不存在: {baseline_file}")
    src = baseline_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(baseline_file))
    except SyntaxError as exc:
        raise FailClosedError(ERR_INVALID_INPUT, f"基线脚本存在语法错误: {exc}")

    q_upper = question_id.strip().upper()
    other_qs = {f"Q{i}" for i in range(1, 10)} - {q_upper}

    # 扫描 import 模块名、函数/标识符定义中是否显式引用其他子题（或针对 Q3 混入 second_pass 等跨题开关）
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for mod_name in names:
                mod_u = mod_name.upper()
                for oq in other_qs:
                    if re.search(rf"(?<![A-Z0-9]){oq}(?![A-Z0-9])", mod_u):
                        raise FailClosedError(
                            ERR_INVARIANT,
                            f"物理隔离拦截 (P24)：{baseline_file.name} 属 {q_upper}，禁止导入 {oq} 模块 ({mod_name})",
                        )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Name)):
            ident = node.name if hasattr(node, "name") else node.id
            ident_l = ident.lower()
            if q_upper == "Q3" and "second_pass" in ident_l:
                raise FailClosedError(
                    ERR_INVARIANT,
                    f"物理隔离拦截 (P24)：{baseline_file.name} (Q3) 禁止混入 Q4 机制标识符 {ident!r}",
                )
            for oq in other_qs:
                if re.search(rf"(?:baseline|hook|model|solver)_{oq.lower()}", ident_l):
                    raise FailClosedError(
                        ERR_INVARIANT,
                        f"物理隔离拦截 (P24)：{baseline_file.name} 严禁引用他题符号 {ident!r}",
                    )


def check_mechanism_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, (a or "").strip().lower(), (b or "").strip().lower()).ratio()


def resolve_claimed_refs_list(
    conn: sqlite3.Connection, declared_refs: list[Any], allow_empty: bool = True
) -> list[dict[str, str]]:
    if not isinstance(declared_refs, list):
        raise FailClosedError(ERR_INVALID_INPUT, "declared_refs 必须为字符串数组 list[str]")
    out: list[dict[str, str]] = []
    for item in declared_refs:
        if isinstance(item, str):
            raw_id = item.strip()
            edge_type = "REQUIRED_PREMISE"  # 拍板 4：探索阶段扁平数组默认按 REQUIRED_PREMISE
        elif isinstance(item, dict):
            raw_id = str(item.get("id") or item.get("entry_id") or "").strip()
            edge_type = str(item.get("edge_type") or "REQUIRED_PREMISE").strip()
        else:
            raise FailClosedError(ERR_INVALID_INPUT, f"declared_refs 包含非法元素类型: {type(item).__name__}")
        if not raw_id:
            if allow_empty:
                continue
            raise FailClosedError(ERR_INVALID_INPUT, "declared_refs 不得包含空字符串")
        ref_kind, pk = resolve_ref_target(conn, raw_id)
        out.append({"dst_id": pk, "ref_kind": ref_kind, "edge_type": edge_type})
    return out


# ==============================================================================
# RQGM 数学内核（纯标准库 Beta 逆 CDF & 对抗池校准）
# ==============================================================================


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 200
    eps = 3.0e-14
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def reg_betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def beta_ppf(a: float, b: float, q: float) -> float:
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if reg_betainc(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def compute_bb_epsilon(s_gt: int, f_gt: int, epsilon: float = 0.05) -> float:
    """RQGM BB_epsilon = I^{-1}_epsilon(1 + S_gt, 1 + F_gt)。"""
    return beta_ppf(1.0 + max(0, int(s_gt)), 1.0 + max(0, int(f_gt)), float(epsilon))


def compute_adversarial_qp(p_plus: float, p_minus: float, r_p: float) -> float:
    """RQGM 对抗池校准公式 Q_P(e) = p_+(e)/2 + p_-(e)/4 + r_P(e)/4。"""
    return 0.5 * float(p_plus) + 0.25 * float(p_minus) + 0.25 * float(r_p)
