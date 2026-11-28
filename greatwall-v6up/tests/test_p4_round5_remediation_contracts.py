"""P4 / 第五轮整改权威契约 Python 单测：
1. resolve_works_ticket 闭环写入 status='RESOLVED' 与 payload_json 审计字段；
2. publish_external_literature_card(outcome='UNAVAILABLE_REPORT') 无卡结案为 CLOSED_UNAVAILABLE 且零伪 [R###]；
3. submit_node_handoff 防静默吞稿（同内容幂等跳过，已闭环写不同内容硬报 ERR_LOCKED）；
4. spec_revision 版本化公开裁决共享 + 旧口径盲审隔离 + Stage 2 旧口径禁标最新 FULL_GOAL；
5. Stage 1 mark_stage1_works_checked 多台仪器断点核验与空清单确认；
6. effective_context_window 自适应窗口 W = min(500k, model_window) 单真源同步与 37%/70% 触发；
7. abort_lineage_node 原子闭环与 fork_branch 公开 inputs/ 自动挂载隔离。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.mcp_server import control_plane_service as cps
from core_python.mcp_server import db_schema as db
from core_python.mcp_server import greatwall_core_mcp as mcp


class TestP4Round5RemediationContracts(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_p4_remed_")
        self.ws = Path(self._tmp.name) / "ws"
        self.data = Path(self._tmp.name) / "plugin_data"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.data.mkdir(parents=True, exist_ok=True)
        self._prev_data = os.environ.get("GREATWALL_PLUGIN_DATA_DIR")
        os.environ["GREATWALL_PLUGIN_DATA_DIR"] = str(self.data)

    def tearDown(self) -> None:
        if self._prev_data is None:
            os.environ.pop("GREATWALL_PLUGIN_DATA_DIR", None)
        else:
            os.environ["GREATWALL_PLUGIN_DATA_DIR"] = self._prev_data
        self._tmp.cleanup()

    def _call(self, tool: str, args: dict, *, role: str, sid: str) -> dict:
        return mcp.dispatch_tool_call(
            tool,
            args,
            workspace_root=str(self.ws),
            caller_role=role,
            session_id=sid,
        )

    def _ctrl(self, method: str, params: dict) -> dict:
        return mcp.dispatch_control_call(method, {"workspace_root": str(self.ws), **params})

    def test_1_resolve_works_ticket_and_unavailable_survey_without_fake_card(self) -> None:
        self.assertTrue(
            self._ctrl("control_plane/init_parse0", {"goal_and_completion_md": "测试工单与无解查新闭环", "subquestions": ["Q1"]})["ok"]
        )
        # 1. 创建分支与节点，触发 PAIN_POINT 工单与查新请求
        self.assertTrue(
            self._call(
                "register_method_family",
                {"question_id": "Q1", "family_id": "fam_a", "mechanism_signature": "sig", "orthogonal_contrast": "ctrl"},
                role="logistics_coordinator",
                sid="log_1",
            )["ok"]
        )
        fb = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_a"},
            role="logistics_coordinator",
            sid="log_1",
        )
        self.assertTrue(fb["ok"])
        nid = fb["data"]["node_id"]
        bid = fb["data"]["branch_id"]

        # 探索者发起不可得资料查新请求
        sreq = self._call(
            "request_literature_survey",
            {"node_id": nid, "question_id": "Q1", "topic_query": "2026国赛赛后内部答案压缩包", "reason": "尝试检索不存在的赛后答案"},
            role="explorer",
            sid="exp_1",
        )
        self.assertTrue(sreq["ok"])
        req_id = sreq["data"]["req_id"]

        # 馆员以 UNAVAILABLE_REPORT 结案：不插入伪 [R###] 卡！
        unavail = self._call(
            "publish_external_literature_card",
            {
                "outcome": "UNAVAILABLE_REPORT",
                "question_id": "Q1",
                "fulfilled_request_ids": [req_id],
                "unavailable_reason_md": "已核查公开来源与竞赛规约，赛后内部答案包客观不存在且违背合规边界，按规约无卡结案。",
            },
            role="external_surveyor",
            sid="surv_1",
        )
        self.assertTrue(unavail["ok"], unavail)
        self.assertIsNone(unavail["data"]["ref_id"])
        self.assertEqual(unavail["data"]["closed_unavailable_request_ids"], [req_id])

        paths = db.resolve_storage_paths(str(self.ws))
        conn = db.open_rw_connection(paths["db_path"])
        try:
            ext_cnt = conn.execute("SELECT COUNT(*) AS c FROM external_literature_cards").fetchone()["c"]
            self.assertEqual(ext_cnt, 0)
            req_row = conn.execute("SELECT status, fulfilled_ref_id, resolution_note FROM survey_requests WHERE req_id = ?", (req_id,)).fetchone()
            self.assertEqual(req_row["status"], "CLOSED_UNAVAILABLE")
            self.assertIsNone(req_row["fulfilled_ref_id"])
            self.assertIn("客观不存在", req_row["resolution_note"])
        finally:
            conn.close()

        # 2. 伴随交接带 tool_pain_point 入队工造司工单，随后工造司调 resolve_works_ticket 显式结案
        ho = self._call(
            "submit_node_handoff",
            {
                "node_id": nid,
                "branch_id": bid,
                "question_id": "Q1",
                "mechanism_summary": "纯解析边界推导初探",
                "evidence_grade": "ARTIFACT_ONLY",
                "column_a_facts_md": "A栏：完成核心不等式推导并验证三个极端特例。",
                "column_b_hypothesis_md": "B栏：预计下一步可收紧常数因子。",
                "will_md": "下代检查对称极值点。",
                "obs_ids": [],
                "dead_ends": [],
                "is_empty_crash": False,
                "tool_pain_point": "希望只读开放某内部隐藏文件",
            },
            role="lineage_companion",
            sid="comp_1",
        )
        self.assertTrue(ho["ok"], ho)

        wq = self._call("get_works_engineering_queue", {"question_id": "ALL"}, role="works_engineer", sid="works_1")
        open_tkts = [t for t in wq["data"]["engineering_tickets"] if t["status"] == "OPEN"]
        self.assertEqual(len(open_tkts), 1)
        tid = open_tkts[0]["ticket_id"]

        res_tkt = self._call(
            "resolve_works_ticket",
            {"ticket_id": tid, "resolution": "WONTFIX", "resolution_note": "隐藏校验集属隔离红线设计，不得向探索者开放。"},
            role="works_engineer",
            sid="works_1",
        )
        self.assertTrue(res_tkt["ok"], res_tkt)
        self.assertEqual(res_tkt["data"]["status"], "WONTFIX")
        self.assertEqual(res_tkt["data"]["resolution"], "WONTFIX")

        wq2 = self._call("get_works_engineering_queue", {"question_id": "ALL"}, role="works_engineer", sid="works_1")
        open_tkts2 = [t for t in wq2["data"]["engineering_tickets"] if t["status"] == "OPEN"]
        self.assertEqual(len(open_tkts2), 0)
        saved = next(t for t in wq2["data"]["engineering_tickets"] if t["ticket_id"] == tid)
        self.assertEqual(saved["resolution_note"], "隐藏校验集属隔离红线设计，不得向探索者开放。")

    def test_2_handoff_anti_silent_swallow_and_abort_node(self) -> None:
        self.assertTrue(
            self._ctrl("control_plane/init_parse0", {"goal_and_completion_md": "防静默吞稿与精准中止测试", "subquestions": ["Q1"]})["ok"]
        )
        self._call(
            "register_method_family",
            {"question_id": "Q1", "family_id": "fam_a", "mechanism_signature": "sig", "orthogonal_contrast": "ctrl"},
            role="logistics_coordinator",
            sid="log_1",
        )
        fb = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_a"},
            role="logistics_coordinator",
            sid="log_1",
        )
        nid = fb["data"]["node_id"]
        bid = fb["data"]["branch_id"]

        payload = {
            "node_id": nid,
            "branch_id": bid,
            "question_id": "Q1",
            "mechanism_summary": "原始机制摘要",
            "evidence_grade": "ARTIFACT_ONLY",
            "column_a_facts_md": "原始客观A栏推导结果与边界核验。",
            "column_b_hypothesis_md": "原始B栏猜想。",
            "will_md": "原始科研遗嘱。",
            "obs_ids": [],
            "dead_ends": [],
            "is_empty_crash": False,
        }
        first = self._call("submit_node_handoff", payload, role="lineage_companion", sid="comp_1")
        self.assertTrue(first["ok"])
        # 同内容重试 -> 合法幂等跳过
        same = self._call("submit_node_handoff", payload, role="lineage_companion", sid="comp_1")
        self.assertTrue(same["ok"])
        self.assertTrue(same["data"].get("idempotent_skip"))

        # 写入截然不同的新内容 -> 必硬报错 ERR_LOCKED，绝不静默吞稿！
        diff = self._call(
            "submit_node_handoff",
            {**payload, "column_a_facts_md": "这是一份全新的不同研究成果，绝不可被静默吞掉！"},
            role="lineage_companion",
            sid="comp_2",
        )
        self.assertFalse(diff["ok"])
        self.assertEqual(diff["error_code"], db.ERR_LOCKED)

        # 新建节点测试 abort_node 原子置 CLOSED 并清空 pending_handoff_mode
        fb2 = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "lateral", "target_family_id": "fam_a"},
            role="logistics_coordinator",
            sid="log_1",
        )
        nid2 = fb2["data"]["node_id"]
        self._ctrl(
            "control_plane/record_pending_handoff",
            {"node_id": nid2, "mode": "HANDOFF_70", "explorer_will_md": "亲笔遗嘱原文"},
        )
        ab = self._ctrl("control_plane/abort_node", {"node_id": nid2, "reason": "切换到新口径"})
        self.assertTrue(ab["ok"])
        self.assertEqual(ab["data"]["node_status"], "CLOSED")
        snap = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        self.assertEqual(snap["pending_handoff_nodes"], [])

    def test_3_versioned_spec_revision_public_inputs_and_old_spec_blind_review(self) -> None:
        # 准备公开题面 + 隐藏目录（验证隔离）
        (self.ws / "problem_pack").mkdir(parents=True, exist_ok=True)
        (self.ws / "problem_pack" / "problem.md").write_text("# 原题 v0 规范\n", encoding="utf-8")
        (self.ws / "_hidden_secret").mkdir(parents=True, exist_ok=True)
        (self.ws / "_hidden_secret" / "answer.txt").write_text("SECRET", encoding="utf-8")

        self.assertTrue(
            self._ctrl("control_plane/init_parse0", {"goal_and_completion_md": "版本化公开裁决与盲审口径测试", "subquestions": ["Q1"]})["ok"]
        )
        self._call(
            "register_method_family",
            {"question_id": "Q1", "family_id": "fam_a", "mechanism_signature": "sig", "orthogonal_contrast": "ctrl"},
            role="logistics_coordinator",
            sid="log_1",
        )
        fb = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_a"},
            role="logistics_coordinator",
            sid="log_1",
        )
        nid = fb["data"]["node_id"]
        bid = fb["data"]["branch_id"]
        wt = Path(fb["data"]["worktree_abs_path"])
        # fork_branch 自动挂载公开 inputs/ 且绝不拷贝 _hidden_secret
        self.assertTrue((wt / "inputs" / "problem_pack" / "problem.md").is_file())
        self.assertFalse((wt / "inputs" / "_hidden_secret").exists())

        # v0 节点交接并送盲审
        self._call(
            "submit_node_handoff",
            {
                "node_id": nid,
                "branch_id": bid,
                "question_id": "Q1",
                "mechanism_summary": "v0 口径下的完整解析推导",
                "evidence_grade": "ARTIFACT_ONLY",
                "column_a_facts_md": "在 v0 原题口径下，我们构造了严格证明：对任意输入均满足上界估计并给出可复核代数恒等式展开，所有边界条件均已逐条检验成立。",
                "column_b_hypothesis_md": "在原口径下完整成立。",
                "will_md": "提交盲审。",
                "obs_ids": [],
                "dead_ends": [],
                "is_empty_crash": False,
            },
            role="lineage_companion",
            sid="comp_1",
        )
        tr = self._call(
            "triage_node",
            {"node_id": nid, "assigned_family_id": "fam_a", "triage_level": "LEVEL_1", "action": "SUBMIT_BLIND_REVIEW", "rationale": "送盲审"},
            role="logistics_coordinator",
            sid="log_1",
        )
        self.assertTrue(tr["ok"])
        rev_id = tr["data"]["created_review_id"]
        self.assertEqual(tr["data"]["spec_revision"], 0)

        # 裁决 4：废除扫盘自动静默升版暗门（磁盘未审批文件仅只读提示），必须走 AMEND_RULING_DRAFT 人类审批单入口升版至 v1
        (self.ws / "rulings").mkdir(parents=True, exist_ok=True)
        (self.ws / "rulings" / "ruling_01.md").write_text("# 补充裁决 v1\n新增非对称约束条件。\n", encoding="utf-8")
        sync_res = self._ctrl("control_plane/sync_public_rulings", {"refresh_active_worktrees": True})
        self.assertTrue(sync_res["ok"])
        self.assertFalse(sync_res["data"]["changed"])
        self.assertEqual(sync_res["data"]["latest_spec_revision"], 0)

        prop = self._call(
            "chief_propose_control_action",
            {
                "action_type": "AMEND_RULING_DRAFT",
                "target_id": "Q1",
                "rationale_md": "补充裁决 v1：新增非对称约束条件。",
                "payload": {
                    "affected_question_ids": ["Q1"],
                    "ruling_title": "补充裁决 v1",
                    "ruling_markdown": "# 补充裁决 v1\n新增非对称约束条件。\n",
                    "summary_md": "补充裁决 v1：新增非对称约束条件。",
                },
            },
            role="gw_chief",
            sid="chief_r5",
        )
        self.assertTrue(prop["ok"], prop)
        appr = self._ctrl(
            "control_plane/approve_control_proposal",
            {"proposal_id": prop["data"]["proposal_id"], "decision": "APPROVE", "approved_by_source": "human_ui"},
        )
        self.assertTrue(appr["ok"], appr)
        exec_res = appr["data"].get("execution") or appr["data"]
        self.assertEqual(exec_res["latest_spec_revision"], 1)

        # 零工具后勤与监察委均可从 DB 视图直接看到 latest_spec_revision=1 与裁决摘要
        dash = self._call("get_logistics_dashboard", {"question_id": "ALL"}, role="logistics_coordinator", sid="log_2")
        self.assertEqual(dash["data"]["latest_spec_revision"], 1)
        self.assertIn("补充裁决 v1", dash["data"]["latest_ruling_summary_md"])
        sup = self._call("get_supervisory_audit_snapshot", {}, role="supervisory_committee", sid="sup_1")
        self.assertEqual(sup["data"]["latest_spec_revision"], 1)

        # 盲审 v0 手稿：沙箱应挂载原题 inputs/problem_pack/problem.md，且绝不混入事后新增的 v1 ruling_01.md！
        bm = self._call("get_blind_manuscript", {"review_id": rev_id}, role="library_verifier", sid="ver_1")
        self.assertTrue(bm["ok"])
        self.assertEqual(bm["data"]["spec_revision"], 0)
        sb = Path(bm["data"]["blind_sandbox_abs_path"])
        self.assertTrue((sb / "inputs" / "problem_pack" / "problem.md").is_file())
        self.assertFalse((sb / "inputs" / "rulings" / "ruling_01.md").exists())

        # Stage 1 按 v0 口径 PASS -> Stage 2 解盲看到 spec_revision_outdated=True
        s1 = self._call(
            "submit_stage1_blind_ledger",
            {
                "review_id": rev_id,
                "question_id": "Q1",
                "ledger_items": [{"claim": "v0下成立", "evidence_location_and_quote": "manuscript_column_a.md", "is_verified": True}],
                "stage1_verdict": "PASS",
                "rigor_score": 8,
            },
            role="library_verifier",
            sid="ver_1",
        )
        self.assertTrue(s1["ok"])
        ub = self._call("get_unblinded_manuscript_and_peers", {"review_id": rev_id}, role="library_verifier", sid="ver_1")
        self.assertTrue(ub["ok"])
        self.assertEqual(ub["data"]["spec_revision"], 0)
        self.assertEqual(ub["data"]["active_spec_revision"], 1)
        self.assertTrue(ub["data"]["spec_revision_outdated"])

        # Stage 2 禁止对旧口径手稿标最新 FULL_GOAL！
        bad_full = self._call(
            "submit_stage2_unblind_verdict",
            {
                "review_id": rev_id,
                "final_verdict": "ACCEPT",
                "novelty_score": 8, "significance_score": 8,
                "l3_entry_kind": "POS_THEOREM",
                "goal_coverage": "FULL_GOAL",
                "is_equivalent_reduction": False,
                "title": "旧口径定理",
                "abstract_md": "这是一段超过四十个字符的独立高密度终审摘要，用于验证旧口径不可标记为最新 FULL_GOAL。",
                "exact_verified_scope_md": "仅在 spec_revision=v0 口径下成立",
            },
            role="library_verifier",
            sid="ver_1",
        )
        self.assertFalse(bad_full["ok"])
        self.assertIn("旧口径 v0", bad_full["error"])

        # 改为 PARTIAL_OR_LEMMA 并在 exact_verified_scope_md 标明 v0 口径 -> 顺利入库 L3
        ok_partial = self._call(
            "submit_stage2_unblind_verdict",
            {
                "review_id": rev_id,
                "final_verdict": "ACCEPT",
                "novelty_score": 8, "significance_score": 8,
                "l3_entry_kind": "POS_THEOREM",
                "goal_coverage": "PARTIAL_OR_LEMMA",
                "is_equivalent_reduction": False,
                "title": "v0 口径已证实定理",
                "abstract_md": "这是一段超过四十个字符的独立高密度终审摘要，完整标明该定理在 v0 原口径下成立且可作为 v1 局部引理复用。",
                "exact_verified_scope_md": "仅在 spec_revision=v0 口径下成立（尚未覆盖 v1 新增非对称约束）",
            },
            role="library_verifier",
            sid="ver_1",
        )
        self.assertTrue(ok_partial["ok"], ok_partial)

    def test_4_adaptive_window_272k_and_stage1_works_checked(self) -> None:
        # 1. 空初始仪器清单：调 mark_stage1_works_checked 直接通过置 1
        self._ctrl(
            "control_plane/init_parse0",
            {"goal_and_completion_md": "自适应窗口与Stage1工造司核查", "subquestions": ["Q1"], "initial_instruments": []},
        )
        snap0 = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        self.assertFalse(snap0["stage1_works_checked"])
        chk0 = self._ctrl("control_plane/mark_stage1_works_checked", {})
        self.assertTrue(chk0["data"]["stage1_works_checked"])
        snap1 = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        self.assertTrue(snap1["stage1_works_checked"])

        # 2. 非空初始仪器清单（要求 2 台）：缺仪器时拒置 1，全部注册后通过
        self._ctrl(
            "control_plane/init_parse0",
            {
                "goal_and_completion_md": "多台初始仪器断点续检",
                "subquestions": ["Q1"],
                "initial_instruments": [{"instrument_id": "inst_a", "question_id": "Q1"}, {"instrument_id": "inst_b", "question_id": "Q1"}],
            },
        )
        # 重置 stage1_works_checked=0 模拟新建项目
        paths = db.resolve_storage_paths(str(self.ws))
        conn = db.open_rw_connection(paths["db_path"])
        try:
            conn.execute("UPDATE parse0_contract SET stage1_works_checked = 0 WHERE contract_id = 'active'")
            conn.commit()
        finally:
            conn.close()
        chk_missing = self._ctrl("control_plane/mark_stage1_works_checked", {})
        self.assertFalse(chk_missing["data"]["stage1_works_checked"])
        self.assertEqual(len(chk_missing["data"]["missing_initial_instruments"]), 2)

        # 2.5 Parse 0 声明无前缀 ID（如 surrogate_simulator），工造司注册 inst_surrogate_simulator 后应正确匹配落标
        self._ctrl(
            "control_plane/init_parse0",
            {
                "goal_and_completion_md": "inst_ 前缀归一化匹配核验",
                "subquestions": ["Q1"],
                "initial_instruments": [{"instrument_id": "surrogate_simulator", "question_id": "Q1"}],
            },
        )
        conn = db.open_rw_connection(paths["db_path"])
        try:
            conn.execute("UPDATE parse0_contract SET stage1_works_checked = 0 WHERE contract_id = 'active'")
            conn.execute(
                """
                INSERT INTO instruments(
                    instrument_id, version, question_id, instrument_role, instrument_rel_path,
                    instrument_sha256, calibration_suite_rel_path, artifact_schema, default_spec_json,
                    is_active, health_status, consecutive_error_count, created_at, updated_at
                ) VALUES ('inst_surrogate_simulator', 1, 'Q1', 'ENV', 'evaluators/sim.py',
                          'sha_dummy', 'evaluators/cal.py', 'python_run', '{}', 1, 'HEALTHY', 0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
                """
            )
            conn.commit()
        finally:
            conn.close()
        chk_norm = self._ctrl("control_plane/mark_stage1_works_checked", {})
        self.assertTrue(chk_norm["data"]["stage1_works_checked"], chk_norm)
        self.assertEqual(chk_norm["data"]["missing_initial_instruments"], [])

        # 3. 272k 小窗口模型自适应时钟（W = min(500k, 272k) = 272k）
        self._call(
            "register_method_family",
            {"question_id": "Q1", "family_id": "fam_a", "mechanism_signature": "sig", "orthogonal_contrast": "ctrl"},
            role="logistics_coordinator",
            sid="log_1",
        )
        fb = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_a"},
            role="logistics_coordinator",
            sid="log_1",
        )
        nid = fb["data"]["node_id"]
        bid = fb["data"]["branch_id"]

        # 同步 102,000 / 272,000 = 37.5% -> 应立即触发 REFLECT_37（不再傻等 185,000！）
        sp1 = self._ctrl("control_plane/sync_pressure", {"node_id": nid, "pressure_tokens": 102000, "effective_context_window": 272000})
        self.assertTrue(sp1["ok"])
        self.assertEqual(sp1["data"]["effective_context_window"], 272000)
        self.assertEqual(sp1["data"]["trigger"], "REFLECT_37")

        # 伴随立即调 get_companion_context(REFLECT_37) 与 record_reflection_and_unlock_pull 应直接放行！
        ctx37 = self._call("get_companion_context", {"branch_id": bid, "node_id": nid, "mode": "REFLECT_37"}, role="lineage_companion", sid="comp_1")
        self.assertTrue(ctx37["ok"], ctx37)
        self.assertEqual(ctx37["state_snapshot"]["effective_context_window"], 272000)

        # 同步 191,000 / 272,000 = 70.2% -> 应触发 HANDOFF_70
        sp2 = self._ctrl("control_plane/sync_pressure", {"node_id": nid, "pressure_tokens": 191000, "effective_context_window": 272000})
        self.assertEqual(sp2["data"]["trigger"], "HANDOFF_70")

        # 若模型声称 1,000,000 窗口，应钳位至上限 360,000
        sp3 = self._ctrl("control_plane/sync_pressure", {"node_id": nid, "pressure_tokens": 190000, "effective_context_window": 1000000})
        self.assertEqual(sp3["data"]["effective_context_window"], 360000)

    def test_5_active_instruments_pushed_in_snapshot_and_pre_spawn(self) -> None:
        self._ctrl(
            "control_plane/init_parse0",
            {"goal_and_completion_md": "仪器清单直推测试", "subquestions": ["Q1", "Q2"], "initial_instruments": []},
        )
        # 在 evaluators/ 下写一个极简 PROBE 仪器并注册
        eval_dir = self.ws / "evaluators"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "q1_probe.py").write_text(
            "def evaluate(artifact, spec, tier='probe'):\n"
            "    return {'obs_status': 'VALID_PASS', 'tracks': {'score': 1.0}, 'details_text': 'ok'}\n",
            encoding="utf-8",
        )
        reg = self._call(
            "register_question_instrument",
            {
                "instrument_id": "inst_q1_probe_push",
                "question_id": "Q1",
                "instrument_role": "PROBE",
                "instrument_rel_path": "evaluators/q1_probe.py",
                "artifact_schema": "python_run",
            },
            role="works_engineer",
            sid="wks_push",
        )
        self.assertTrue(reg["ok"], reg)

        # 1. schedule_snapshot 必须返回结构化 active_instruments
        snap = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        ids = [x["instrument_id"] for x in snap.get("active_instruments", [])]
        self.assertIn("inst_q1_probe_push", ids)

        # 2. PRE_SPAWN 伴随上下文必须收到对应子题的活跃仪器清单
        self._call(
            "register_method_family",
            {"question_id": "Q1", "family_id": "fam_push", "mechanism_signature": "sig", "orthogonal_contrast": "ctrl"},
            role="logistics_coordinator",
            sid="log_push",
        )
        fb = self._call(
            "fork_branch",
            {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_push"},
            role="logistics_coordinator",
            sid="log_push",
        )
        ctx_pre = self._call(
            "get_companion_context",
            {"branch_id": fb["data"]["branch_id"], "node_id": fb["data"]["node_id"], "mode": "PRE_SPAWN"},
            role="lineage_companion",
            sid="comp_push",
        )
        self.assertTrue(ctx_pre["ok"], ctx_pre)
        pre_ids = [x["instrument_id"] for x in ctx_pre["data"].get("active_instruments", [])]
        self.assertIn("inst_q1_probe_push", pre_ids)

        # 3. 探索者调用未知 instrument_id 时，ERR_NOT_FOUND 必须附带当前可用仪器 ID 列表以便一秒自纠
        bad_eval = self._call(
            "run_isolated_eval",
            {
                "node_id": fb["data"]["node_id"],
                "question_id": "Q1",
                "instrument_id": "inst_nonexistent_guess",
                "tier": "probe",
                "artifact_rel_path": "cand.py",
                "linguistic_prediction": "猜错仪器名应返回可用列表",
            },
            role="explorer",
            sid="exp_push",
        )
        self.assertFalse(bad_eval["ok"])
        self.assertEqual(bad_eval["error_code"], "ERR_NOT_FOUND")
        self.assertIn("inst_q1_probe_push", bad_eval["error"])

    def test_6_round6_supervisory_watchdog_orphaned_revision_and_worktree_probe_mirror(self) -> None:
        """第六轮法医复现回归：
        1. PROBE/ENV 公开仪器自动同步至探索者 <worktree>/inputs/instruments/ 与 <worktree>/tools/shared_probes/，且严禁泄漏 _hidden_calibrations；
        2. 导出 solve() 的 .py 候选或无参 probe (artifact_rel_path='') 在无 public_input 时自动直通 Stage B；
        3. upgrade_instrument_with_calibration 支持同步更新 artifact_schema 与 default_spec；
        4. abort_node 中止 ACTIVE_REVISING 节点后，监察委快照与后勤看板均能检出 orphaned_blind_review_revisions 与 understaffed_questions，且 fork_branch 无损继承返工单；
        5. triage_node(INPLACE_REPAIR) 禁止跨学派吞并消灭原正交学派的唯一分支。
        """
        self._ctrl(
            "control_plane/init_parse0",
            {"goal_and_completion_md": "第六轮法医闭环测试", "subquestions": ["Q1"], "initial_instruments": []},
        )
        eval_dir = self.ws / "evaluators"
        hidden_dir = eval_dir / "_hidden_calibrations"
        hidden_dir.mkdir(parents=True, exist_ok=True)
        (hidden_dir / "secret_cal.json").write_text(
            json.dumps(
                [
                    {
                        "case_id": "c1",
                        "tier": "official",
                        "spec": {},
                        "artifact": {"ok": True},
                        "expected_status": "OK",
                        "expected_verdict": "PASS",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (eval_dir / "probe_tool.py").write_text(
            "def evaluate(artifact, spec, tier='probe'):\n"
            "    return {'status': 'OK', 'verdict': None, 'tracks': {'checked': 1}, 'details': 'probe_ok'}\n",
            encoding="utf-8",
        )
        (eval_dir / "geom_verdict.py").write_text(
            "def evaluate(artifact, spec, tier='official'):\n"
            "    return {'status': 'OK', 'verdict': 'PASS', 'tracks': {'err': 0.0}, 'details': 'geom_ok'}\n",
            encoding="utf-8",
        )

        # 注册 3 个正交学派：wedge, rotat, jung
        for fid in ("fam_wedge", "fam_rotat", "fam_jung"):
            self.assertTrue(
                self._call(
                    "register_method_family",
                    {"question_id": "Q1", "family_id": fid, "mechanism_signature": f"sig_{fid}", "orthogonal_contrast": "orth"},
                    role="logistics_coordinator",
                    sid="log_r6",
                )["ok"]
            )

        fb_w = self._call("fork_branch", {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_wedge"}, role="logistics_coordinator", sid="log_r6")
        fb_r = self._call("fork_branch", {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_rotat"}, role="logistics_coordinator", sid="log_r6")
        fb_j = self._call("fork_branch", {"question_id": "Q1", "fork_mode": "orthogonal", "target_family_id": "fam_jung"}, role="logistics_coordinator", sid="log_r6")
        nid_w, bid_w, wt_w = fb_w["data"]["node_id"], fb_w["data"]["branch_id"], Path(fb_w["data"]["worktree_abs_path"])
        nid_r, bid_r, wt_r = fb_r["data"]["node_id"], fb_r["data"]["branch_id"], Path(fb_r["data"]["worktree_abs_path"])
        nid_j, bid_j = fb_j["data"]["node_id"], fb_j["data"]["branch_id"]

        # 工造司注册 PROBE 与 VERDICT 仪器 -> 活跃 Worktree 立即获得 PROBE 镜像与 INSTRUMENT_CATALOG.json，且无隐藏校准集
        reg_p = self._call(
            "register_question_instrument",
            {
                "question_id": "Q1",
                "instrument_id": "inst_probe_r6",
                "instrument_role": "PROBE",
                "instrument_rel_path": "evaluators/probe_tool.py",
                "artifact_schema": "python_run",
                "default_spec": {"interface_hint": "无参自检探针"},
            },
            role="works_engineer",
            sid="wks_r6",
        )
        self.assertTrue(reg_p["ok"], reg_p)
        reg_v = self._call(
            "register_question_instrument",
            {
                "question_id": "Q1",
                "instrument_id": "inst_geom_r6",
                "instrument_role": "VERDICT",
                "instrument_rel_path": "evaluators/geom_verdict.py",
                "calibration_suite_rel_path": "evaluators/_hidden_calibrations/secret_cal.json",
                "artifact_schema": "python_run",
                "default_spec": {"hw_deg": 1},
            },
            role="works_engineer",
            sid="wks_r6",
        )
        self.assertTrue(reg_v["ok"], reg_v)

        self.assertTrue((wt_w / "inputs" / "instruments" / "probe_tool.py").is_file())
        self.assertTrue((wt_w / "tools" / "shared_probes" / "probe_tool.py").is_file())
        self.assertTrue((wt_w / "inputs" / "instruments" / "INSTRUMENT_CATALOG.json").is_file())
        self.assertFalse((wt_w / "inputs" / "instruments" / "secret_cal.json").exists())

        # 探索者调用 tier='probe' 且 artifact_rel_path=''（无参目录自检）直接成功！
        pr_res = self._call(
            "run_isolated_eval",
            {
                "node_id": nid_w,
                "question_id": "Q1",
                "instrument_id": "inst_probe_r6",
                "tier": "probe",
                "artifact_rel_path": "",
                "linguistic_prediction": "无参目录探针自检",
            },
            role="explorer",
            sid="exp_w",
        )
        self.assertTrue(pr_res["ok"], pr_res)
        self.assertEqual(pr_res["data"]["status"], "OK")

        # 探索者提交导出 solve()（而非 run()）的 .py 脚本给无 public_input 的 inst_geom_r6 -> 直通 Stage B PASS！
        (wt_w / "solver.py").write_text("def solve(pts, brs):\n    return {'area': 1.0}\n", encoding="utf-8")
        off_res = self._call(
            "run_isolated_eval",
            {
                "node_id": nid_w,
                "question_id": "Q1",
                "instrument_id": "inst_geom_r6",
                "tier": "official",
                "artifact_rel_path": "solver.py",
                "linguistic_prediction": "导出 solve 的脚本应直通 Stage B 评测通过",
            },
            role="explorer",
            sid="exp_w",
        )
        self.assertTrue(off_res["ok"], off_res)
        self.assertEqual(off_res["data"]["obs_status"], "VALID_PASS")

        # 工造司升版 inst_geom_r6 时同步更新 artifact_schema 与 default_spec
        upg_res = self._call(
            "upgrade_instrument_with_calibration",
            {
                "question_id": "Q1",
                "instrument_id": "inst_geom_r6",
                "new_instrument_rel_path": "evaluators/geom_verdict.py",
                "calibration_suite_rel_path": "evaluators/_hidden_calibrations/secret_cal.json",
                "artifact_schema": "raw_file",
                "default_spec": {"hw_deg": 1, "interface_hint": "已升级为 raw_file 直通"},
            },
            role="works_engineer",
            sid="wks_r6",
        )
        self.assertTrue(upg_res["ok"], upg_res)
        cat_data = json.loads((wt_w / "inputs" / "instruments" / "INSTRUMENT_CATALOG.json").read_text(encoding="utf-8"))
        geom_entry = next(x for x in cat_data["instruments"] if x["instrument_id"] == "inst_geom_r6")
        self.assertEqual(geom_entry["artifact_schema"], "raw_file")
        self.assertIn("raw_file 直通", geom_entry["interface_hint"])

        # 模拟第六轮：wedge 分支交接送盲审 -> 盲审判 REVISE -> 主控 abort_node 杀掉 wedge 与 jung
        self._call(
            "submit_node_handoff",
            {
                "node_id": nid_w,
                "branch_id": bid_w,
                "question_id": "Q1",
                "mechanism_summary": "半平面楔形偶极反例",
                "evidence_grade": "ARTIFACT_ONLY",
                "column_a_facts_md": "A栏：构造双站大距离偶极极限反例并验证 ρ=1/sin(2δ)，满六十字符核验载体要求，送盲审检验。",
                "column_b_hypothesis_md": "B栏猜想",
                "will_md": "送审",
                "obs_ids": [],
                "dead_ends": [],
                "candidate_rel_path": "solver.py",
                "is_empty_crash": False,
            },
            role="lineage_companion",
            sid="comp_w",
        )
        tr_w = self._call(
            "triage_node",
            {"node_id": nid_w, "assigned_family_id": "fam_wedge", "triage_level": "LEVEL_1", "action": "SUBMIT_BLIND_REVIEW", "rationale": "送审"},
            role="logistics_coordinator",
            sid="log_r6",
        )
        rev_id = tr_w["data"]["created_review_id"]
        self._call(
            "submit_stage1_blind_ledger",
            {
                "review_id": rev_id,
                "question_id": "Q1",
                "ledger_items": [{"claim": "反例需补全对称与物理界", "evidence_location_and_quote": "manuscript_column_a.md", "is_verified": False}],
                "stage1_verdict": "REVISE",
                "rigor_score": 5,
                "revision_or_refutation_reason": "请补全 R1..R3 三项边界",
            },
            role="library_verifier",
            sid="ver_r6",
        )

        # 主控 abort_node 中止 nid_w（手握 rev_001 的 ACTIVE_REVISING 节点）与 nid_j
        self._ctrl("control_plane/abort_node", {"node_id": nid_w, "reason": "R1 裁决切换"})
        self._ctrl("control_plane/abort_node", {"node_id": nid_j, "reason": "R1 裁决切换"})

        # rotat 分支交接后，后勤判 LEVEL_2 (INPLACE_REPAIR) 时若试图把 assigned_family_id 偷改成 fam_jung，服务端自动保护原学派 fam_rotat！
        self._call(
            "submit_node_handoff",
            {
                "node_id": nid_r,
                "branch_id": bid_r,
                "question_id": "Q1",
                "mechanism_summary": "旋转卡壳直径圆",
                "evidence_grade": "ARTIFACT_ONLY",
                "column_a_facts_md": "A栏：partA 脚本出现 TypeError 待原地修补。",
                "column_b_hypothesis_md": "B栏",
                "will_md": "修补 TypeError",
                "obs_ids": [],
                "dead_ends": [],
                "is_empty_crash": False,
            },
            role="lineage_companion",
            sid="comp_r",
        )
        tr_r = self._call(
            "triage_node",
            {"node_id": nid_r, "assigned_family_id": "fam_jung", "triage_level": "LEVEL_2", "action": "INPLACE_REPAIR", "rationale": "修补 TypeError"},
            role="logistics_coordinator",
            sid="log_r6",
        )
        self.assertTrue(tr_r["ok"], tr_r)
        self.assertEqual(tr_r["data"]["assigned_family_id"], "fam_rotat")

        # 此时监察委调用 get_supervisory_audit_snapshot：必须一眼检出 ORPHANED_BLIND_REVIEW_REVISION 与 SINGLE_BRANCH_DEGENERATION！
        sup_snap = self._call("get_supervisory_audit_snapshot", {}, role="supervisory_committee", sid="sup_r6")
        self.assertTrue(sup_snap["ok"], sup_snap)
        anom_types = {a["anomaly_type"] for a in sup_snap["data"]["watchdog_anomalies"]}
        self.assertIn("ORPHANED_BLIND_REVIEW_REVISION", anom_types)
        self.assertIn("SINGLE_BRANCH_DEGENERATION_OR_UNDERSTAFFED_FAMILIES", anom_types)
        self.assertIn("status='ALERT'", sup_snap["next_step_guidance"])

        # 后勤调用 get_logistics_dashboard：同样清晰看到孤儿返工单与断代分支，并调用 fork_branch 无损续接 nid_w！
        dash = self._call("get_logistics_dashboard", {"question_id": "Q1"}, role="logistics_coordinator", sid="log_r6")
        self.assertEqual(len(dash["data"]["orphaned_blind_review_revisions"]), 1)
        self.assertEqual(dash["data"]["orphaned_blind_review_revisions"][0]["source_node_id"], nid_w)

        respawn = self._call(
            "fork_branch",
            {"question_id": "Q1", "parent_node_id": nid_w, "fork_mode": "lateral", "target_family_id": "fam_wedge"},
            role="logistics_coordinator",
            sid="log_r6",
        )
        self.assertTrue(respawn["ok"], respawn)
        self.assertEqual(respawn["data"]["node_status"], "ACTIVE_REVISING")
        self.assertTrue(len(respawn["data"]["inherited_revision_requests"]) >= 1)
        respawn_wt = Path(respawn["data"]["worktree_abs_path"])
        self.assertTrue((respawn_wt / "solver.py").is_file())

        # 续接后孤儿盲审返工单立即清零！
        dash_after = self._call("get_logistics_dashboard", {"question_id": "Q1"}, role="logistics_coordinator", sid="log_r6")
        self.assertEqual(len(dash_after["data"]["orphaned_blind_review_revisions"]), 0)

        # 验证 UI 全景透视原语 control_plane/ui_inspector
        ui_insp = self._ctrl("control_plane/ui_inspector", {"selected_node_id": respawn["data"]["node_id"], "selected_worktree_rel_file": "solver.py"})
        self.assertTrue(ui_insp["ok"], ui_insp)
        self.assertEqual(ui_insp["data"]["selected_node_detail"]["node_id"], respawn["data"]["node_id"])
        self.assertIn("def solve", ui_insp["data"]["selected_node_detail"]["preview_file_content"])

    def test_7_main_controller_submit_works_ticket(self) -> None:
        self._ctrl("control_plane/init_parse0", {"goal_and_completion_md": "主控直发工单至科研仪器科测试", "subquestions": ["Q1", "Q3"]})
        # 空描述应 fail-closed 拒收
        bad = self._ctrl("control_plane/submit_works_ticket", {"question_id": "Q3", "ticket_type": "INSTRUMENT_ERROR", "description": "  "})
        self.assertFalse(bad["ok"])

        # 主控签发正式工单
        res = self._ctrl(
            "control_plane/submit_works_ticket",
            {
                "question_id": "Q3",
                "ticket_type": "INSTRUMENT_ERROR",
                "instrument_id": "inst_surrogate_simulator",
                "description": "模拟器物理边界条件符号写反，请核验并升版校准。",
                "source": "main_controller",
            },
        )
        self.assertTrue(res["ok"], res)
        tid = res["data"]["ticket_id"]
        self.assertEqual(res["data"]["status"], "OPEN")

        # 调度快照立即可见 open_works_tickets，确保 orchestrator 立刻唤醒 works_engineer
        snap = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        open_ids = [t["ticket_id"] for t in snap["open_works_tickets"]]
        self.assertIn(tid, open_ids)

        # 工造司通过 get_works_engineering_queue 看到并显式结案
        q = self._call("get_works_engineering_queue", {"question_id": "ALL"}, role="works_engineer", sid="wk_mc")
        self.assertTrue(q["ok"], q)
        matched = [t for t in q["data"]["engineering_tickets"] if t["ticket_id"] == tid]
        self.assertEqual(len(matched), 1)
        self.assertIn("符号写反", matched[0]["payload_json"])

        closed = self._call(
            "resolve_works_ticket",
            {"ticket_id": tid, "resolution": "RESOLVED", "resolution_note": "已修复边界符号并重新通过校准集。"},
            role="works_engineer",
            sid="wk_mc",
        )
        self.assertTrue(closed["ok"], closed)
        snap2 = self._ctrl("control_plane/schedule_snapshot", {})["data"]
        self.assertNotIn(tid, [t["ticket_id"] for t in snap2["open_works_tickets"]])


if __name__ == "__main__":
    unittest.main()
