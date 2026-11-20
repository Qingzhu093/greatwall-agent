"""P2 全量 31 窄工具、JSON-RPC 2.0 协议与端到端闭环测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
GREATWALL_ROOT = TESTS_DIR.parent
CORE_PYTHON = GREATWALL_ROOT / "core_python"
if str(CORE_PYTHON) not in sys.path:
    sys.path.insert(0, str(CORE_PYTHON))

from mcp_server.db_schema import (  # noqa: E402
    ERR_AUTH,
    ERR_CONFLICT,
    ERR_INVALID_INPUT,
    ERR_INVARIANT,
    ERR_LOCKED,
    open_ro_connection,
    open_rw_connection,
    resolve_storage_paths,
)
from mcp_server.fact_bridge import record_fact_cli  # noqa: E402
from mcp_server.greatwall_core_mcp import (  # noqa: E402
    _TOOL_REGISTRY,
    dispatch_control_call,
    dispatch_tool_call,
    handle_jsonrpc_message,
)


def _ok(res: dict) -> dict:
    if not res.get("ok"):
        raise AssertionError(f"期望 ok=True，实际失败: {json.dumps(res, ensure_ascii=False)}")
    return res


def _err(res: dict, expected_code: str) -> dict:
    if res.get("ok"):
        raise AssertionError(f"期望报错 {expected_code}，实际成功: {json.dumps(res, ensure_ascii=False)}")
    if res.get("error_code") != expected_code:
        raise AssertionError(
            f"期望 error_code={expected_code}，实际 {res.get('error_code')}: {res.get('error')}"
        )
    return res


class TestP2Full31ToolsAndE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name) / "proj_ws"
        self.ws.mkdir(parents=True, exist_ok=True)
        # 备份原 SKILL_LEDGER.json，测试结束恢复，避免污染仓库文件
        self._ledger_path = CORE_PYTHON / "skills" / "SKILL_LEDGER.json"
        self._orig_ledger_bytes = self._ledger_path.read_bytes()

        # 准备可运行钩子与隔离基线（Q1 弱，Q2 含 anchors 真值检验）
        (self.ws / "evaluators").mkdir(parents=True, exist_ok=True)
        (self.ws / "baselines" / "Q1").mkdir(parents=True, exist_ok=True)
        (self.ws / "baselines" / "Q2").mkdir(parents=True, exist_ok=True)
        (self.ws / "branches" / "br_q1" / "src").mkdir(parents=True, exist_ok=True)
        (self.ws / "branches" / "br_q2" / "src").mkdir(parents=True, exist_ok=True)
        (self.ws / "branches" / "br_q1_zero" / "src").mkdir(parents=True, exist_ok=True)

        # Q1 钩子：返回统一协议 {passed, metrics, details: str}
        (self.ws / "evaluators" / "hook_q1.py").write_text(
            "def evaluate(stage_a_out, ctx):\n"
            "    val = float(stage_a_out.get('energy', 999.0))\n"
            "    passed = val <= 1.05\n"
            "    return {\n"
            "        'passed': passed,\n"
            "        'metrics': {'comparable_rank_score': -abs(val - 1.0), 'energy': val},\n"
            "        'details': f'Q1 check energy={val}',\n"
            "    }\n",
            encoding="utf-8",
        )
        # Q2 v1 钩子（故意对 candidate_score>=0.4 宽松放行，用于后面 RQGM 锚点覆盖比对）
        (self.ws / "evaluators" / "hook_q2_v1.py").write_text(
            "def evaluate(stage_a_out, ctx):\n"
            "    s = float(stage_a_out.get('score', 0.0))\n"
            "    passed = s >= 0.4\n"
            "    return {\n"
            "        'passed': passed,\n"
            "        'metrics': {'comparable_rank_score': s},\n"
            "        'details': f'hook_ver=1 score={s}',\n"
            "    }\n",
            encoding="utf-8",
        )
        # Q2 v2 更严格准确钩子（仅 0.75..0.95 真正物理自洽，假阳性 s=0.45 与夸张作弊 s=2.0 都拒止）
        (self.ws / "evaluators" / "hook_q2_v2.py").write_text(
            "def evaluate(stage_a_out, ctx):\n"
            "    s = float(stage_a_out.get('score', 0.0))\n"
            "    passed = 0.75 <= s <= 0.95\n"
            "    return {\n"
            "        'passed': passed,\n"
            "        'metrics': {'comparable_rank_score': s if passed else -1.0},\n"
            "        'details': f'hook_ver=2 score={s}',\n"
            "    }\n",
            encoding="utf-8",
        )
        # Q2 自动化真值锚点集：前 4 条为真实正例(0.8..0.9)，后 3 条为反例(0.45, 0.5, 2.0)
        # hook_q2_v1 对 7 条全通过 (4 TP, 3 FP -> adv reject=0) -> s_gt=4, f_gt=3
        # 注意 _eval_hook_on_anchors 会按 ground_truth_pass 与 candidate output 算准确匹配数！
        (self.ws / "evaluators" / "anchors" / "Q2").mkdir(parents=True, exist_ok=True)
        (self.ws / "evaluators" / "anchors" / "Q2" / "cases.json").write_text(
            json.dumps(
                [
                    {"stage_a_artifact": {"score": 0.80}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"score": 0.85}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"score": 0.90}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"score": 0.82}, "expected_passed": True, "is_adversarial": False},
                    {"stage_a_artifact": {"score": 0.45}, "expected_passed": False, "is_adversarial": True},
                    {"stage_a_artifact": {"score": 0.50}, "expected_passed": False, "is_adversarial": True},
                    {"stage_a_artifact": {"score": 2.00}, "expected_passed": False, "is_adversarial": True},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # 合法隔离基线 + 恶意跨题引用基线
        (self.ws / "baselines" / "Q1" / "baseline.py").write_text("SCALE = 1.0\n", encoding="utf-8")
        (self.ws / "baselines" / "Q2" / "baseline.py").write_text("SCALE = 2.0\n", encoding="utf-8")
        (self.ws / "baselines" / "Q1" / "dirty_cross_q.py").write_text(
            "from baselines.Q2 import baseline\nSCALE = baseline.SCALE\n",
            encoding="utf-8",
        )

        # 候选脚本
        (self.ws / "branches" / "br_q1" / "src" / "cand_pass.py").write_text(
            "def run(public_input):\n    return {'energy': 1.02}\n", encoding="utf-8"
        )
        (self.ws / "branches" / "br_q1" / "src" / "cand_crash.py").write_text(
            "def run(public_input):\n    raise RuntimeError('numerical blowup')\n", encoding="utf-8"
        )
        (self.ws / "branches" / "br_q2" / "src" / "cand_q2.py").write_text(
            "def run(public_input):\n    return {'score': 0.88}\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._ledger_path.write_bytes(self._orig_ledger_bytes)
        self._tmp.cleanup()

    def _call(self, tool: str, role: str, sid: str, **args) -> dict:
        return dispatch_tool_call(
            tool,
            args,
            workspace_root=str(self.ws),
            caller_role=role,
            session_id=sid,
        )

    def test_01_registry_has_exact_31_tools_and_rbac_enforced(self) -> None:
        self.assertEqual(len(_TOOL_REGISTRY), 31)
        resp = handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 31)

        _ok(
            dispatch_control_call(
                "control_plane/init_epoch",
                {"workspace_root": str(self.ws), "goal_md": "G", "required_questions": ["Q1", "Q2"]},
            )
        )
        # explorer 调用治理/审稿工具必须被硬拦截并写入 FACT_LOG UNAUTHORIZED_TOOL_ATTEMPT
        _err(
            self._call(
                "register_question_domain_hook",
                "explorer",
                "sess_exp_bad",
                question_id="Q1",
                hook_rel_path="evaluators/hook_q1.py",
                baseline_rel_path="baselines/Q1/baseline.py",
                fidelity_max_error_pct=1.2,
            ),
            ERR_AUTH,
        )
        _err(
            self._call(
                "triage_node",
                "explorer",
                "sess_exp_bad",
                node_id="n_q1",
                triage_level="LEVEL_1",
                action="SUBMIT_BLIND_REVIEW",
                rationale="hijack",
            ),
            ERR_AUTH,
        )
        db_path = resolve_storage_paths(str(self.ws))["db_path"]
        conn = open_ro_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT edge_type, dst_id FROM epistemic_edges WHERE edge_track='FACT_LOG' AND edge_type='UNAUTHORIZED_TOOL_ATTEMPT'"
            ).fetchall()
            self.assertGreaterEqual(len(rows), 2)
        finally:
            conn.close()

    def test_02_full_lifecycle_31_tools_rqgm_clock_blind_review_and_stage3(self) -> None:
        ws_str = str(self.ws)
        # 0. 初始化纪元与物理目录映射
        _ok(
            dispatch_control_call(
                "control_plane/init_epoch",
                {
                    "workspace_root": ws_str,
                    "goal_md": "完成 Q1 与 Q2 物理基准验证",
                    "required_questions": ["Q1", "Q2"],
                    "stage": "STAGE1_PARSE0",
                },
            )
        )

        # 1. Works Engineer：P25 保真门禁 >=5% 拒止 & P24 AST 跨题引用拒止
        _err(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q1",
                hook_rel_path="evaluators/hook_q1.py",
                baseline_rel_path="baselines/Q1/baseline.py",
                fidelity_max_error_pct=5.0,
            ),
            ERR_INVARIANT,
        )
        _err(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q1",
                hook_rel_path="evaluators/hook_q1.py",
                baseline_rel_path="baselines/Q1/dirty_cross_q.py",
                fidelity_max_error_pct=1.0,
            ),
            ERR_INVARIANT,
        )
        _ok(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q1",
                hook_rel_path="evaluators/hook_q1.py",
                baseline_rel_path="baselines/Q1/baseline.py",
                fidelity_max_error_pct=0.8,
            )
        )
        _ok(
            self._call(
                "register_question_domain_hook",
                "works_engineer",
                "sess_we_1",
                question_id="Q2",
                hook_rel_path="evaluators/hook_q2_v1.py",
                baseline_rel_path="baselines/Q2/baseline.py",
                fidelity_max_error_pct=1.5,
            )
        )

        # 2. Logistics：注册方法族 + 创建两题根节点 + Stage 1 Gate 检查并进入 STAGE2_EVOLVE
        _ok(
            self._call(
                "register_method_family",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                family_id="fam_symp",
                mechanism_signature="采用哈密顿保结构离散步进保持相空间体积与能量长期有界。",
                orthogonal_contrast="区别于显式 Runge-Kutta 的耗散步进，强调辛几何守恒。",
            )
        )
        _ok(
            self._call(
                "register_method_family",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                family_id="fam_rk_orth",
                mechanism_signature="高阶自适应显式龙格库塔与误差估计子正交控制方案。",
                orthogonal_contrast="无辛保结构约束，以局部截断误差实时控制步长。",
            )
        )
        _ok(
            self._call(
                "register_method_family",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q2",
                family_id="fam_q2_a",
                mechanism_signature="Q2 变分与真值锚点对齐采样族。",
                orthogonal_contrast="独立于 Q1，面向 Q2 离散分布。",
            )
        )
        # 用真实 fork_branch 创建 Q1 两个正交分支及 Q2 一个分支，并在其工作树写入候选代码
        fq1 = _ok(
            self._call(
                "fork_branch",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                fork_mode="orthogonal",
                target_family_id="fam_symp",
            )
        )
        n_q1 = fq1["data"]["node_id"]
        b_q1 = fq1["data"]["branch_id"]
        wt_q1 = Path(fq1["data"]["worktree_abs_path"])
        (wt_q1 / "src" / "cand_pass.py").write_text(
            "def run(public_input):\n    return {'energy': 1.02}\n", encoding="utf-8"
        )
        (wt_q1 / "src" / "cand_crash.py").write_text(
            "def run(public_input):\n    raise RuntimeError('numerical blowup 1')\n", encoding="utf-8"
        )
        (wt_q1 / "src" / "cand_crash2.py").write_text(
            "def run(public_input):\n    raise RuntimeError('numerical blowup 2')\n", encoding="utf-8"
        )

        fq2 = _ok(
            self._call(
                "fork_branch",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q2",
                fork_mode="orthogonal",
                target_family_id="fam_q2_a",
            )
        )
        n_q2 = fq2["data"]["node_id"]
        b_q2 = fq2["data"]["branch_id"]
        wt_q2 = Path(fq2["data"]["worktree_abs_path"])
        (wt_q2 / "src" / "cand_q2.py").write_text(
            "def run(public_input):\n    return {'score': 0.88}\n", encoding="utf-8"
        )

        fzero = _ok(
            self._call(
                "fork_branch",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                fork_mode="orthogonal",
                target_family_id="fam_rk_orth",
            )
        )
        n_zero = fzero["data"]["node_id"]
        b_zero = fzero["data"]["branch_id"]
        db_path = resolve_storage_paths(ws_str)["db_path"]

        _ok(
            self._call(
                "record_compliance_check",
                "supervisory_committee",
                "sess_sup_1",
                stage="STAGE1_GATE",
                status="PASSED",
                blocking_questions_zero_l3=[],
                unread_citation_nodes=[],
                notes="Q1 Q2 钩子与基线门禁均已通过",
            )
        )

        # 3. Library Surveyor：查请求并发布 [R001] 外部文献卡
        _ok(
            self._call(
                "request_literature_survey",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                question_id="Q1",
                topic_query="Symplectic Verlet error bound",
                reason="需要收敛阶与能量漂移上界的外部文献依据",
            )
        )
        req_res = _ok(self._call("get_survey_requests", "library_surveyor", "sess_surv_1", question_id="ALL"))
        self.assertEqual(len(req_res["data"]["pending_requests"]), 1)
        pub_res = _ok(
            self._call(
                "publish_external_literature_card",
                "library_surveyor",
                "sess_surv_1",
                ref_id="R001",
                question_id="Q1",
                title="Symplectic Euler & Verlet Long-Time Energy Conservation",
                abstract_md="本文证明了四阶辛积分方法在哈密顿系统长时演进中可将修正哈密顿量能量振幅控制在极小多项式有界误差内，并给出了显式时间步长上限定理。",
                exact_preconditions_md="光滑可分哈密顿量 H(p,q)=T(p)+V(q)，时间步长 dt < h_crit。",
                formulas_or_operators_md="Phi_dt = exp(dt/2 D_T) exp(dt D_V) exp(dt/2 D_T)，局部能量误差 O(dt^2)。",
                read_depth="full_text",
                support_scope="DIRECT_PROOF_OR_EXACT_MEASUREMENT",
                source_citation="Hairer et al., Geometric Numerical Integration, 2006",
            )
        )
        r_id = pub_res["data"]["ref_id"]
        self.assertEqual(r_id, "R001")

        # 4. Lineage Companion：保存 5 段式 <=2200 简报（超 2200 拒止）
        _err(
            self._call(
                "save_lineage_briefing",
                "lineage_companion",
                "sess_comp_q1",
                branch_id=b_q1,
                node_id=n_q1,
                sec1_mechanism="x" * 600,
                sec2_verified_baseline="x" * 600,
                sec3_bottleneck="x" * 600,
                sec4_dead_ends="x" * 600,
                sec5_immediate_will="x" * 200,
            ),
            ERR_INVALID_INPUT,
        )
        _ok(
            self._call(
                "save_lineage_briefing",
                "lineage_companion",
                "sess_comp_q1",
                branch_id=b_q1,
                node_id=n_q1,
                sec1_mechanism="采用对称辛分解推进 Q1 数值求解。",
                sec2_verified_baseline="目前基线 SCALE=1.0 尚未实测。",
                sec3_bottleneck="需验证能量偏差低于 1.05。",
                sec4_dead_ends="尚无已知死胡同。",
                sec5_immediate_will="先运行 cand_pass.py 实测一次建立锚点。",
            )
        )
        _ok(
            self._call(
                "save_lineage_briefing",
                "lineage_companion",
                "sess_comp_q2",
                branch_id=b_q2,
                node_id=n_q2,
                sec1_mechanism="Q2 独立测试探索与 RQGM 重算。",
                sec2_verified_baseline="Q2 独立基线 SCALE=2.0。",
                sec3_bottleneck="需验证 score 在目标区间。",
                sec4_dead_ends="尚无。",
                sec5_immediate_will="执行 cand_q2.py。",
            )
        )

        # 5. Explorer 运行隔离实测（含幂等命中 + 两次不同 EXECUTION_ERROR 触发自动痛点单 + 成功观测）
        crash1 = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                question_id="Q1",
                candidate_rel_path="src/cand_crash.py",
                linguistic_prediction="预期第一次异常触发监控计数。",
            )
        )
        self.assertFalse(crash1["data"]["idempotent_hit"])
        crash1_dup = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                question_id="Q1",
                candidate_rel_path="src/cand_crash.py",
                linguistic_prediction="同一代码同一预测命中幂等。",
            )
        )
        self.assertTrue(crash1_dup["data"]["idempotent_hit"])
        crash2 = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                question_id="Q1",
                candidate_rel_path="src/cand_crash2.py",
                linguistic_prediction="预期第二次不同崩溃自动派发 Works 痛点单。",
            )
        )
        self.assertEqual(crash2["data"]["obs_status"], "EXECUTION_ERROR")
        self.assertTrue(bool(crash2["data"]["auto_pain_ticket"]))
        wq_res = _ok(self._call("get_works_engineering_queue", "works_engineer", "sess_we_1", question_id="Q1"))
        self.assertTrue(any(t["source_type"] == "AUTO_CONSECUTIVE_ERRORS" for t in wq_res["data"]["pain_point_tickets"]))

        # 阅读 [R001] 建立真实 READ 事实边，再跑正确候选生成 [Obs001]
        cat_r = _ok(self._call("query_library_catalog", "explorer", "sess_exp_q1", node_id=n_q1, question_id="Q1", scope="EXTERNAL_R"))
        self.assertGreaterEqual(len(cat_r["data"]["cards"]), 1)
        _ok(self._call("get_library_entry", "explorer", "sess_exp_q1", node_id=n_q1, entry_id=r_id))
        # 0-37% 区间调 scope='INTERNAL_L3' 必须保持锁闭（unlocked_internal=False, 不泄内藏卡）！
        cat_locked = _ok(
            self._call("query_library_catalog", "explorer", "sess_exp_q1", node_id=n_q1, question_id="Q1", scope="INTERNAL_L3")
        )
        self.assertFalse(cat_locked["data"]["unlocked_internal"])
        self.assertEqual(cat_locked["data"]["cards"], [])

        ev_q1 = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                question_id="Q1",
                candidate_rel_path="src/cand_pass.py",
                linguistic_prediction="依据 R001 能量振幅应低于 1.05。",
                declared_refs=[r_id],
            )
        )
        obs_q1_id = ev_q1["data"]["obs_id"]
        self.assertTrue(ev_q1["data"]["passed"])
        self.assertTrue(Path(ev_q1["data"]["stage_a_artifact_path"]).is_file())

        # Q2 运行一次产出 [Obs002]（用于稍后验证 RQGM 只重算 Q2 不误杀 Q1！）
        ev_q2 = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_q2",
                node_id=n_q2,
                question_id="Q2",
                candidate_rel_path="src/cand_q2.py",
                linguistic_prediction="Q2 目标分数预计落在 0.85 附近。",
            )
        )
        obs_q2_id = ev_q2["data"]["obs_id"]

        # 6. 控制面同步 185,000 tokens (37%) -> 触发 REFLECT_37 -> Companion 检视与解锁
        _ok(dispatch_control_call("control_plane/sync_pressure", {"workspace_root": ws_str, "node_id": n_q1, "pressure_tokens": 185000}))
        comp_ctx = _ok(
            self._call(
                "get_companion_context",
                "lineage_companion",
                "sess_comp_q1",
                branch_id=b_q1,
                node_id=n_q1,
                mode="REFLECT_37",
            )
        )
        self.assertEqual(len(comp_ctx["data"]["holiday_candidates"]), 2)
        self.assertTrue(all(1 <= c["id"] <= 28 for c in comp_ctx["data"]["holiday_candidates"]))
        chosen_pid = comp_ctx["data"]["holiday_candidates"][0]["id"]

        # 非法反思：第29条、缺第7类、超300字、3轮 均被拒
        _err(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_q1",
                node_id=n_q1,
                selected_categories=["7. Attractor Tasks"],
                holiday_prompt_id=29,
                turns=[{"question": "q", "answer": "a"}],
                verdict_3state="SUFFICIENT_EVIDENCE",
            ),
            ERR_INVALID_INPUT,
        )
        _err(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_q1",
                node_id=n_q1,
                selected_categories=["1. Domain framing"],
                holiday_prompt_id=chosen_pid,
                turns=[{"question": "q", "answer": "a"}],
                verdict_3state="SUFFICIENT_EVIDENCE",
            ),
            ERR_INVALID_INPUT,
        )
        _err(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_q1",
                node_id=n_q1,
                selected_categories=["7. Attractor Tasks"],
                holiday_prompt_id=chosen_pid,
                turns=[{"question": "q" * 301, "answer": "a"}],
                verdict_3state="SUFFICIENT_EVIDENCE",
            ),
            ERR_INVALID_INPUT,
        )
        _ok(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_q1",
                node_id=n_q1,
                selected_categories=["7. Attractor Tasks", "2. Assumptions"],
                holiday_prompt_id=chosen_pid,
                turns=[
                    {"question": "步长是否进入人工吸引子？", "answer": "已对照 R001 确认真实物理周期稳定。"},
                    {"question": "本轮微调方向？", "answer": "直接整理两栏实测交接。"},
                ],
                verdict_3state="SUFFICIENT_EVIDENCE",
            )
        )
        # 37% 解锁后全馆查询 + 血脉图只读 SQL 查询放开（含租户隔离拦截与合格视图）！
        _ok(self._call("query_library_catalog", "explorer", "sess_exp_q1", node_id=n_q1, question_id="Q1", scope="ALL"))
        _ok(
            self._call(
                "register_saved_graph_query",
                "supervisory_committee",
                "sess_sup_1",
                query_name="q_cross_leak",
                description="缺少 branch_id 的跨分支视图测试",
                sql_select="SELECT node_id, node_status FROM lineage_nodes WHERE question_id = :question_id",
            )
        )
        _err(
            self._call(
                "read_lineage_graph",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                branch_id=b_q1,
                saved_query_name="q_cross_leak",
            ),
            ERR_AUTH,
        )
        _ok(
            self._call(
                "register_saved_graph_query",
                "supervisory_committee",
                "sess_sup_1",
                query_name="q_node_status",
                description="含 branch_id 租户隔离的安全视图",
                sql_select="SELECT node_id, node_status FROM lineage_nodes WHERE branch_id = :branch_id",
            )
        )
        g_res = _ok(
            self._call(
                "read_lineage_graph",
                "explorer",
                "sess_exp_q1",
                node_id=n_q1,
                branch_id=b_q1,
                saved_query_name="q_node_status",
            )
        )
        self.assertEqual(len(g_res["data"]["saved_query_rows"]), 1)

        # 7. 提交零实测节点（落 scratch_log）及正规双栏 L1 节点交接（含主动痛点上报）
        _ok(
            self._call(
                "submit_node_handoff",
                "lineage_companion",
                "sess_comp_zero",
                node_id=n_zero,
                branch_id=b_zero,
                question_id="Q1",
                column_a_facts_md="未运行任何实测，仅作思路草稿。",
                column_b_hypothesis_md="计划下次接续。",
                will_md="等待探索者接手实测。",
                obs_ids=[],
                is_zero_eval_crash=True,
                tool_pain_point="需要更快速的向量化评估包装",
            )
        )
        conn = open_ro_connection(db_path)
        try:
            zrow = conn.execute("SELECT scratch_log_json FROM lineage_nodes WHERE node_id=?", (n_zero,)).fetchone()
            self.assertIn("思路草稿", str(zrow["scratch_log_json"]))
        finally:
            conn.close()

        _ok(
            self._call(
                "submit_node_handoff",
                "lineage_companion",
                "sess_comp_q1",
                node_id=n_q1,
                branch_id=b_q1,
                question_id="Q1",
                column_a_facts_md=f"依据 [{r_id}] 与 [{obs_q1_id}] 实测 energy=1.02 <= 1.05。",
                column_b_hypothesis_md="对称辛求解器在当前网格下已稳定收敛，建议提交盲审入库。",
                will_md="交由后勤提交 Level 1 盲审。",
                obs_ids=[obs_q1_id],
                candidate_rel_path="src/cand_pass.py",
            )
        )
        # 为 Q2 也解锁并提交交接，以便稍后验证双题闭环
        _ok(dispatch_control_call("control_plane/sync_pressure", {"workspace_root": ws_str, "node_id": n_q2, "pressure_tokens": 190000}))
        _ok(
            self._call(
                "record_reflection_and_unlock_pull",
                "lineage_companion",
                "sess_comp_q2",
                node_id=n_q2,
                selected_categories=["7. Attractor Tasks"],
                holiday_prompt_id=2,
                turns=[{"question": "是否假阳性？", "answer": "待 RQGM 更严锚点核验。"}],
                verdict_3state="SUFFICIENT_EVIDENCE",
            )
        )
        _ok(
            self._call(
                "submit_node_handoff",
                "lineage_companion",
                "sess_comp_q2",
                node_id=n_q2,
                branch_id=b_q2,
                question_id="Q2",
                column_a_facts_md=f"依 [{obs_q2_id}] 实测 score=0.88。",
                column_b_hypothesis_md="Q2 结果可靠，待送盲审。",
                will_md="提交 Level 1 盲审。",
                obs_ids=[obs_q2_id],
                candidate_rel_path="src/cand_q2.py",
            )
        )

        # 8. 验证 RQGM 锚点覆盖与 P26 选择性重评：仅使 Q2 [Obs002] 进入 PENDING_REVALIDATION，Q1 [Obs001] 丝毫无损！
        rqgm_res = _ok(
            self._call(
                "upgrade_hook_with_rqgm_gate",
                "works_engineer",
                "sess_we_1",
                question_id="Q2",
                new_hook_rel_path="evaluators/hook_q2_v2.py",
                gt_success_count=100,  # 故意传入假大数检验是否被服务端 anchors/Q2 覆盖
                gt_failure_count=0,
            )
        )
        self.assertTrue(rqgm_res["data"]["server_ran_anchors"])
        self.assertEqual(rqgm_res["data"]["pending_revalidation_obs_ids"], [obs_q2_id])
        conn = open_ro_connection(db_path)
        try:
            q1_stat = conn.execute("SELECT obs_status FROM observations WHERE obs_id=?", (obs_q1_id,)).fetchone()["obs_status"]
            q2_stat = conn.execute("SELECT obs_status FROM observations WHERE obs_id=?", (obs_q2_id,)).fetchone()["obs_status"]
            self.assertEqual(q1_stat, "VALID")
            self.assertEqual(q2_stat, "PENDING_REVALIDATION")
        finally:
            conn.close()

        # 调用 recompute_stage_b_only 读取 stage_a_output.json 秒级恢复 Q2 观测
        recomp = _ok(
            self._call(
                "recompute_stage_b_only",
                "works_engineer",
                "sess_we_1",
                obs_id=obs_q2_id,
                question_id="Q2",
            )
        )
        self.assertTrue(recomp["data"]["passed"])

        # 9. 后勤调度看板 + Triage LEVEL_1 + fork_branch P19 自排除
        dash = _ok(self._call("get_logistics_dashboard", "logistics_coordinator", "sess_log_1"))
        self.assertGreaterEqual(len(dash["data"]["awaiting_triage_nodes"]), 2)

        t1 = _ok(
            self._call(
                "triage_node",
                "logistics_coordinator",
                "sess_log_1",
                node_id=n_q1,
                triage_level="LEVEL_1",
                action="SUBMIT_BLIND_REVIEW",
                rationale="Q1 证据完整且未超限，送盲审。",
            )
        )
        rev_q1 = t1["data"]["created_review_id"]
        t2 = _ok(
            self._call(
                "triage_node",
                "logistics_coordinator",
                "sess_log_1",
                node_id=n_q2,
                triage_level="LEVEL_1",
                action="SUBMIT_BLIND_REVIEW",
                rationale="Q2 经新版 RQGM 钩子重评依然通过，送盲审。",
            )
        )
        rev_q2 = t2["data"]["created_review_id"]

        # 用 fzero 派生一个实测失败的 fam_rk_orth 分支，顺便测通 P19 同族互斥分叉拦截 & LEVEL_4A 自动入 L2 & dispatch_stagnation_five_lanes
        f_fork = _ok(
            self._call(
                "fork_branch",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                parent_node_id=n_zero,
                fork_mode="orthogonal",
                target_family_id="fam_rk_orth",
            )
        )
        rk_node = f_fork["data"]["node_id"]
        rk_branch = f_fork["data"]["branch_id"]
        rk_wt = Path(f_fork["data"]["worktree_abs_path"])
        (rk_wt / "src" / "cand_fail.py").write_text(
            "def run(public_input):\n    return {'energy': 9.99}\n", encoding="utf-8"
        )
        ev_rk = _ok(
            self._call(
                "run_isolated_eval",
                "explorer",
                "sess_exp_rk",
                node_id=rk_node,
                question_id="Q1",
                candidate_rel_path="src/cand_fail.py",
                linguistic_prediction="测试显式 RK 大步长发散边界。",
            )
        )
        obs_rk_id = ev_rk["data"]["obs_id"]
        self.assertFalse(ev_rk["data"]["passed"])

        # P19：rk_branch 正在 EXPLORING fam_rk_orth，另一分支试图同族 orthogonal 必被 ERR_CONFLICT 拦，而自身 lateral 继承允许
        _err(
            self._call(
                "fork_branch",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                parent_node_id=n_q1,
                fork_mode="orthogonal",
                target_family_id="fam_rk_orth",
            ),
            ERR_CONFLICT,
        )
        # dispatch_stagnation_five_lanes 测试
        stag_res = _ok(
            self._call(
                "dispatch_stagnation_five_lanes",
                "logistics_coordinator",
                "sess_log_1",
                question_id="Q1",
                lane_assignments=[
                    {"branch_id": rk_branch, "lane": "EXPLORATION", "directive": "按第29条跳出旧辛离散假设，开启高阶显式探索"}
                ],
            )
        )
        self.assertEqual(len(stag_res["data"]["assigned"]), 1)

        # 对 rk_node 提交手记进入 AWAITING_TRIAGE -> 分诊 LEVEL_4A SEAL_BARRIER 自动写入 L2_FAILURE_RECORD
        _ok(
            self._call(
                "submit_node_handoff",
                "lineage_companion",
                "sess_comp_rk",
                node_id=rk_node,
                branch_id=rk_branch,
                question_id="Q1",
                column_a_facts_md=f"依 [{obs_rk_id}] 实测 energy=9.99 > 1.05。",
                column_b_hypothesis_md="显式方法在此步长下发散，应封存禁入区。",
                will_md="建议 LEVEL_4A 封存。",
                obs_ids=[obs_rk_id],
                candidate_rel_path="src/cand_fail.py",
            )
        )
        t4a = _ok(
            self._call(
                "triage_node",
                "logistics_coordinator",
                "sess_log_1",
                node_id=rk_node,
                triage_level="LEVEL_4A",
                action="SEAL_BARRIER",
                rationale="证实该大步长显式方案发散，封存禁入区。",
                barrier_proof_md="energy=9.99 >> 1.05，存在数值发散禁入区。",
            )
        )
        self.assertTrue(str(t4a["data"]["created_l2_id"]).startswith("L2-"))

        # 10. Stage 1 盲审（零信息泄漏：不暴露 source_node_id / branch_id）+ 不可逆单向锁 + Stage 2 解盲 + edge_type_overrides
        blind1 = _ok(self._call("get_blind_manuscript", "library_verifier", "sess_ver_1", review_id=rev_q1))
        self.assertNotIn("source_node_id", blind1["data"])
        self.assertNotIn("branch_id", blind1["data"])
        # 自审拦截（若用同一 sess_comp_q1 提交审稿应报错）
        _err(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_comp_q1",
                review_id=rev_q1,
                question_id="Q1",
                ledger_items=[{"claim": "e<=1.05", "evidence_location_and_quote": f"{obs_q1_id}: energy=1.02", "is_verified": True}],
                stage1_verdict="PASS",
            ),
            ERR_CONFLICT,
        )
        # 合法异会话 Stage 1 PASS
        _ok(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_1",
                review_id=rev_q1,
                question_id="Q1",
                ledger_items=[
                    {"claim": "energy=1.02 <= 1.05", "evidence_location_and_quote": f"[{obs_q1_id}] stage_a energy=1.02", "is_verified": True}
                ],
                stage1_verdict="PASS",
            )
        )
        # 二次改写 Stage 1 Ledger 被硬件锁拦截
        _err(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_1",
                review_id=rev_q1,
                question_id="Q1",
                ledger_items=[{"claim": "篡改", "evidence_location_and_quote": "fake", "is_verified": False}],
                stage1_verdict="REJECT",
                reject_failure_reason="x",
                exact_refuted_scope_md="y",
            ),
            ERR_LOCKED,
        )

        # 还没过 Q2 时，监察委结题硬锁必报 BLOCKED（Q2 尚无 L3）！
        gate_blk = _ok(self._call("check_stage2_closure_gate", "supervisory_committee", "sess_sup_1"))
        self.assertFalse(gate_blk["data"]["closure_allowed"])
        self.assertIn("Q2", gate_blk["data"]["blocking_questions_zero_l3"])
        _err(
            self._call(
                "record_compliance_check",
                "supervisory_committee",
                "sess_sup_1",
                stage="STAGE2_CLOSURE_GATE",
                status="PASSED",
                blocking_questions_zero_l3=[],
                unread_citation_nodes=[],
                notes="试图抢跑结题",
            ),
            ERR_LOCKED,
        )

        # Stage 2 解盲终审 Q1 并把 R001 引用边降级为 INDEPENDENT_SUPPORT，入 L3_VERIFIED
        _ok(self._call("get_unblinded_manuscript_and_peers", "library_verifier", "sess_ver_1", review_id=rev_q1))
        s2_q1 = _ok(
            self._call(
                "submit_stage2_unblind_verdict",
                "library_verifier",
                "sess_ver_1",
                review_id=rev_q1,
                final_verdict="PASS",
                title="[Q1] 对称辛求解器基准收敛定理",
                abstract_md="在 Q1 标准对称哈密顿基线下，四阶对称辛解法将实测能量稳定控制在 1.02，且通过 Stage 1/2 独立核验。",
                exact_verified_scope_md="仅适用于 Q1 SCALE=1.0 对称正则条件。",
                cross_draft_comparison_notes="与已知失败屏障无耦合，独立成立。",
                edge_type_overrides={r_id: "INDEPENDENT_SUPPORT"},
            )
        )
        l3_q1 = s2_q1["data"]["created_ledger_entry_id"]
        self.assertTrue(l3_q1.startswith("L3-"))

        # 完成 Q2 盲审流，入库 Q2 的 L3_VERIFIED
        _ok(self._call("get_blind_manuscript", "library_verifier", "sess_ver_2", review_id=rev_q2))
        _ok(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_2",
                review_id=rev_q2,
                question_id="Q2",
                ledger_items=[
                    {"claim": "score=0.88 在 [0.75,0.95]", "evidence_location_and_quote": f"[{obs_q2_id}] score=0.88", "is_verified": True}
                ],
                stage1_verdict="PASS",
            )
        )
        _ok(self._call("get_unblinded_manuscript_and_peers", "library_verifier", "sess_ver_2", review_id=rev_q2))
        s2_q2 = _ok(
            self._call(
                "submit_stage2_unblind_verdict",
                "library_verifier",
                "sess_ver_2",
                review_id=rev_q2,
                final_verdict="PASS",
                title="[Q2] 高精度真值锚点验证定式",
                abstract_md="经 RQGM v2 真值锚点重算验证，Q2 候选方案得分 0.88 严格处于有效物理自洽区间并完成双阶段终审。",
                exact_verified_scope_md="适用于 Q2 v2 真值锚点分布范围。",
            )
        )
        l3_q2 = s2_q2["data"]["created_ledger_entry_id"]

        # 顺带测通 propose_salvaged_lemma + Stage 1 盲审 REJECT 短路入 L2
        salv = _ok(
            self._call(
                "propose_salvaged_lemma",
                "library_verifier",
                "sess_ver_1",
                source_node_id=n_q1,
                question_id="Q1",
                title="附带打捞引理（测试拒绝短路）",
                abstract_md="测试短引理提议并走一次独立拒稿短路生成 L2 记录。",
                column_a_self_contained_proof_md="证明见附表。",
                column_b_scope_notes_md="范围界定。",
                bound_obs_ids=[obs_q1_id],
            )
        )
        rev_salv = salv["data"]["review_id"]
        _err(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_1",  # 同一 verifier 会话严禁自审自己打捞的引理！
                review_id=rev_salv,
                question_id="Q1",
                ledger_items=[{"claim": "self", "evidence_location_and_quote": "no direct evidence found", "is_verified": False}],
                stage1_verdict="REJECT",
                reject_failure_reason="x",
                exact_refuted_scope_md="y",
            ),
            ERR_CONFLICT,
        )
        s1_rej = _ok(
            self._call(
                "submit_stage1_blind_ledger",
                "library_verifier",
                "sess_ver_2",
                review_id=rev_salv,
                question_id="Q1",
                ledger_items=[{"claim": "附表缺乏实测支撑", "evidence_location_and_quote": "no direct evidence found", "is_verified": False}],
                stage1_verdict="REJECT",
                reject_failure_reason="引理声称外推超出观测边界",
                exact_refuted_scope_md="外推区间未获实证支持",
            )
        )
        self.assertTrue(str(s1_rej["data"]["short_circuited_l2_id"]).startswith("L2-"))

        # 更新 SKILL_LEDGER 验证 No File 物理校验 + Supervisory 审计快照 + 放行 Stage 2 & 导出 Stage 3
        _ok(
            self._call(
                "update_skill_ledger",
                "works_engineer",
                "sess_we_1",
                skill_id="symplectic_test_skill",
                applicable_scope="Q1/Q2 单元测试验证",
                version=1,
                raw_success_count=3,
                raw_failure_count=0,
                verified_artifact_rel_path="evaluators/hook_q1.py",
                rollback_pointer="git:none",
            )
        )
        snap = _ok(self._call("get_supervisory_audit_snapshot", "supervisory_committee", "sess_sup_1"))
        self.assertTrue(snap["data"]["closure_gate_summary"]["closure_allowed"])
        _ok(
            self._call(
                "record_compliance_check",
                "supervisory_committee",
                "sess_sup_1",
                stage="STAGE2_CLOSURE_GATE",
                status="PASSED",
                blocking_questions_zero_l3=[],
                unread_citation_nodes=[],
                notes="Q1 Q2 均具备 L3_VERIFIED，准予进入 Stage 3。",
            )
        )
        exp = _ok(
            self._call(
                "export_stage3_final_delivery",
                "library_surveyor",
                "sess_surv_1",
                formal_paper_md=(
                    f"# 终稿科研报告\n\n## Q1\n依据 {l3_q1} 收敛（详细方法、误差边界与实测结论）。\n\n"
                    f"## Q2\n依据 {l3_q2} 在 RQGM 真值锚点验证下稳定成立。\n"
                ),
                selected_l3_ids_by_question={"Q1": [l3_q1], "Q2": [l3_q2]},
                reproduction_candidate_nodes=[n_q1, n_q2],
            )
        )
        deliv_dir = Path(exp["data"]["delivery_dir"])
        for rel in exp["data"]["five_piece_files"]:
            self.assertTrue((deliv_dir / rel).is_file(), f"缺少交付件 {rel}")

        _ok(
            self._call(
                "record_compliance_check",
                "supervisory_committee",
                "sess_sup_1",
                stage="STAGE3_FINAL_AUDIT",
                status="PASSED",
                blocking_questions_zero_l3=[],
                unread_citation_nodes=[],
                notes="Stage 3 五件套核验通过，正式结题。",
            )
        )

    def test_03_stdio_jsonrpc_and_fact_bridge_cli(self) -> None:
        ws_str = str(self.ws)
        _ok(dispatch_control_call("control_plane/init_epoch", {"workspace_root": ws_str, "required_questions": ["Q1"]}))
        # 测试 fact_bridge.py CLI 写入 FACT_LOG
        rc = record_fact_cli([ws_str, "sess_cli_1", "src/cand_pass.py", "READ", "node_cli_1", '{"tool":"read"}'])
        self.assertEqual(rc, 0)
        db_path = resolve_storage_paths(ws_str)["db_path"]
        conn = open_ro_connection(db_path)
        try:
            cnt = conn.execute("SELECT COUNT(*) FROM epistemic_edges WHERE edge_track='FACT_LOG' AND src_id='node_cli_1'").fetchone()[0]
            self.assertEqual(cnt, 1)
        finally:
            conn.close()

        # 通过真实子进程以 Content-Length 与 NDJSON 双帧通信测试 greatwall_core_mcp.py
        req1 = json.dumps({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}})
        req2 = json.dumps({"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}})
        req3 = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "control_plane/schedule_snapshot",
                "params": {"workspace_root": ws_str},
            }
        )
        frame1 = f"Content-Length: {len(req1.encode('utf-8'))}\r\n\r\n{req1}".encode("utf-8")
        frame2 = (req2 + "\n" + req3 + "\n").encode("utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(CORE_PYTHON)
        proc = subprocess.run(
            [sys.executable, "-m", "mcp_server.greatwall_core_mcp"],
            input=frame1 + frame2,
            capture_output=True,
            cwd=str(CORE_PYTHON),
            env=env,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr.decode('utf-8', errors='replace')}")
        out = proc.stdout.decode("utf-8")
        self.assertIn("greatwall-v6up-core", out)
        self.assertIn("get_logistics_dashboard", out)
        self.assertIn('"slot_cap": 6', out)


if __name__ == "__main__":
    unittest.main()
