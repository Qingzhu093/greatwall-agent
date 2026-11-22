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
            role="library_surveyor",
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
        self.assertEqual(res_tkt["data"]["status"], "RESOLVED")
        self.assertEqual(res_tkt["data"]["resolution"], "WONTFIX")

        wq2 = self._call("get_works_engineering_queue", {"question_id": "ALL"}, role="works_engineer", sid="works_1")
        open_tkts2 = [t for t in wq2["data"]["engineering_tickets"] if t["status"] == "OPEN"]
        self.assertEqual(len(open_tkts2), 0)

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

        # 人类事后往 rulings/ 新增补充裁决文档，触发 spec_revision 升至 v1
        (self.ws / "rulings").mkdir(parents=True, exist_ok=True)
        (self.ws / "rulings" / "ruling_01.md").write_text("# 补充裁决 v1\n新增非对称约束条件。\n", encoding="utf-8")
        sync_res = self._ctrl("control_plane/sync_public_rulings", {"refresh_active_worktrees": True})
        self.assertTrue(sync_res["ok"])
        self.assertTrue(sync_res["data"]["changed"])
        self.assertEqual(sync_res["data"]["latest_spec_revision"], 1)

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
            },
            role="library_verifier",
            sid="ver_1",
        )
        self.assertTrue(s1["ok"])
        ub = self._call("get_unblinded_manuscript_and_peers", {"review_id": rev_id}, role="library_verifier", sid="ver_1")
        self.assertTrue(ub["ok"])
        self.assertEqual(ub["data"]["spec_revision"], 0)
        self.assertEqual(ub["data"]["latest_spec_revision"], 1)
        self.assertTrue(ub["data"]["spec_revision_outdated"])

        # Stage 2 禁止对旧口径手稿标最新 FULL_GOAL！
        bad_full = self._call(
            "submit_stage2_unblind_verdict",
            {
                "review_id": rev_id,
                "final_verdict": "ACCEPT",
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
        self.assertIn("spec_revision=v0", bad_full["error"])

        # 改为 PARTIAL_OR_LEMMA 并在 exact_verified_scope_md 标明 v0 口径 -> 顺利入库 L3
        ok_partial = self._call(
            "submit_stage2_unblind_verdict",
            {
                "review_id": rev_id,
                "final_verdict": "ACCEPT",
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

        # 若模型声称 1,000,000 窗口，应钳位至上限 500,000
        sp3 = self._ctrl("control_plane/sync_pressure", {"node_id": nid, "pressure_tokens": 190000, "effective_context_window": 1000000})
        self.assertEqual(sp3["data"]["effective_context_window"], 500000)

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


if __name__ == "__main__":
    unittest.main()
