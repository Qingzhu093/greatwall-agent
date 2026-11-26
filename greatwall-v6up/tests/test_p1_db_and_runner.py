"""P1 隔离仪器容器、四元复合缓存、Stage A/B 分离重评、heavy 异步冻结、FTS5 与轮询性能验收。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.evaluators.isolated_runner import run_calibration_suite, run_isolated_instrument
from core_python.mcp_server import control_plane_service as cp
from core_python.mcp_server import db_schema as db
from core_python.mcp_server import greatwall_core_mcp as mcp


def _write_file(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _write_json(path: Path, obj: object) -> str:
    return _write_file(path, json.dumps(obj, ensure_ascii=False, indent=2))


class TestP1DbAndRunner(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_v3_p1_")
        self.ws = Path(self._tmp.name) / "ws"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.plugin_data = Path(self._tmp.name) / "plugin_data"
        self._old_env = os.environ.get("GREATWALL_PLUGIN_DATA_DIR")
        os.environ["GREATWALL_PLUGIN_DATA_DIR"] = str(self.plugin_data)

        paths = db.resolve_storage_paths(str(self.ws))
        self.db_path = paths["db_path"]
        self.conn = db.open_rw_connection(self.db_path, init_schema=True)
        cp.init_parse0_contract(
            self.conn,
            goal_and_completion_md="# Goal\n通用多题科学发现验证。",
            subquestions=[
                {"question_id": "Q1", "title": "反例与仿真"},
                {"question_id": "Q2", "title": "对照独立子题"},
            ],
            stage="STAGE2_EVOLVE",
        )
        # 通过正规工具创建分支与节点
        self.b1, self.n1, self.wt1 = self._seed_branch_and_node("Q1", "fam_q1")
        self.b2, self.n2, self.wt2 = self._seed_branch_and_node("Q2", "fam_q2")

    def tearDown(self) -> None:
        self.conn.close()
        if self._old_env is None:
            os.environ.pop("GREATWALL_PLUGIN_DATA_DIR", None)
        else:
            os.environ["GREATWALL_PLUGIN_DATA_DIR"] = self._old_env
        self._tmp.cleanup()

    def _call(self, tool: str, role: str, sid: str, **kwargs) -> dict:
        return mcp.dispatch_tool_call(
            tool,
            kwargs,
            workspace_root=str(self.ws),
            caller_role=role,
            session_id=sid,
        )

    def _seed_branch_and_node(self, qid: str, fid: str) -> tuple[str, str, Path]:
        r_fam = self._call(
            "register_method_family",
            "logistics_coordinator",
            "s_log",
            question_id=qid,
            family_id=fid,
            mechanism_signature=f"核心机制 {fid}",
            orthogonal_contrast="首条基线学派",
        )
        self.assertTrue(r_fam["ok"], r_fam)
        r_fork = self._call(
            "fork_branch",
            "logistics_coordinator",
            "s_log",
            question_id=qid,
            fork_mode="orthogonal",
            target_family_id=fid,
        )
        self.assertTrue(r_fork["ok"], r_fork)
        bid = r_fork["data"]["branch_id"]
        nid = r_fork["data"]["node_id"]
        wt = Path(r_fork["data"]["worktree_abs_path"])
        (wt / "tools").mkdir(parents=True, exist_ok=True)
        return bid, nid, wt

    def test_1_missing_public_input_yields_instrument_error_zero_penalty(self) -> None:
        inst_path = _write_file(
            self.ws / "evaluators" / "inst_pub.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    pub = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"x": pub["v"]}, "details": "ok"}
""",
        )
        cand_path = _write_file(
            self.wt1 / "cand.py",
            "def run(spec):\n    return {'x': 1}\n",
        )
        res = run_isolated_instrument(
            artifact_path=cand_path,
            instrument_path=inst_path,
            spec={"tier": "official"},  # 故意缺少 public_input
            tier="official",
            instrument_role="VERDICT",
            artifact_schema="python_run",
        )
        self.assertEqual(res["status"], "INSTRUMENT_ERROR")
        self.assertEqual(res["obs_status"], "INSTRUMENT_ERROR")
        self.assertIn("public_input", res["details"])

    def test_2_four_tuple_cache_invalidation_on_tools_and_tier_and_error_bypass(self) -> None:
        _write_file(
            self.ws / "evaluators" / "inst_q1_v1.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    pub = get_public_input(spec)
    val = float(artifact.get("val", -1))
    passed = val >= float(pub.get("min_val", 0.0))
    return {
        "status": "OK",
        "verdict": "PASS" if passed else "FAIL",
        "tracks": {"val": val, "tier": tier, "bonus": 2 if tier == "heavy" else 1},
        "details": f"tier={tier} val={val}",
    }
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_q1.json",
            [
                {
                    "case_id": "gold_zero",
                    "tier": "official",
                    "spec": {"public_input": {"min_val": 0.0}},
                    "artifact": {"val": 0.0},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                },
                {
                    "case_id": "bad_neg",
                    "tier": "official",
                    "spec": {"public_input": {"min_val": 0.0}},
                    "artifact": {"val": -1.0},
                    "expected_status": "OK",
                    "expected_verdict": "FAIL",
                },
            ],
        )
        reg = self._call(
            "register_question_instrument",
            "works_engineer",
            "s_works_1",
            question_id="Q1",
            instrument_id="inst_q1",
            instrument_role="VERDICT",
            instrument_rel_path="evaluators/inst_q1_v1.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_q1.json",
            artifact_schema="python_run",
            plugin_protocol_version="v3",
            default_spec={"public_input": {"min_val": 0.0}},
        )
        self.assertTrue(reg["ok"], reg)

        _write_file(self.wt1 / "tools" / "helper.py", "FACTOR = 1.0\n")
        _write_file(
            self.wt1 / "cand.py",
            "import tools.helper as h\ndef run(spec):\n    return {'val': h.FACTOR}\n",
        )

        # 第一次 official 计算
        r1 = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="official",
            artifact_rel_path="cand.py",
            linguistic_prediction="预期输出 val=1.0 并通过底线 0.0",
            declared_refs=[],
        )
        self.assertTrue(r1["ok"], r1)
        self.assertFalse(r1["data"]["cache_hit"])
        self.assertEqual(r1["data"]["tracks"]["val"], 1.0)
        obs1 = r1["data"]["obs_id"]

        # 相同四元组命中缓存且复用原 obs_id
        r1_hit = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="official",
            artifact_rel_path="cand.py",
            linguistic_prediction="重跑相同四元组应命中缓存",
            declared_refs=[],
        )
        self.assertTrue(r1_hit["ok"], r1_hit)
        self.assertTrue(r1_hit["data"]["cache_hit"])
        self.assertEqual(r1_hit["data"]["obs_id"], obs1)

        # 修改 tools/helper.py 后，四元复合缓存必须失效重算
        _write_file(self.wt1 / "tools" / "helper.py", "FACTOR = 3.5\n")
        r2 = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="official",
            artifact_rel_path="cand.py",
            linguistic_prediction="改 tools/helper.py 后预期输出 val=3.5",
            declared_refs=[],
        )
        self.assertTrue(r2["ok"], r2)
        self.assertFalse(r2["data"]["cache_hit"])
        self.assertEqual(r2["data"]["tracks"]["val"], 3.5)

        # 切换到 probe 档位走轻量诊断日志，不污染官方缓存槽
        r_probe = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="probe",
            artifact_rel_path="cand.py",
            linguistic_prediction="probe 档位独立诊断槽位",
            declared_refs=[],
        )
        self.assertTrue(r_probe["ok"], r_probe)
        self.assertEqual(r_probe["data"]["tier"], "probe")
        self.assertEqual(r_probe["data"]["tracks"]["val"], 3.5)

        # 制造一次 CANDIDATE_ERROR：验证错误态绝不写入缓存（下次重跑仍穿透）
        _write_file(self.wt1 / "bad.py", "def run(spec):\n    raise RuntimeError('boom')\n")
        e1 = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="official",
            artifact_rel_path="bad.py",
            linguistic_prediction="测试候选异常",
            declared_refs=[],
        )
        self.assertTrue(e1["ok"], e1)
        self.assertEqual(e1["data"]["status"], "CANDIDATE_ERROR")
        e2 = self._call(
            "run_isolated_eval",
            "explorer",
            "s_exp_1",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_q1",
            tier="official",
            artifact_rel_path="bad.py",
            linguistic_prediction="第二次错误穿透缓存",
            declared_refs=[],
        )
        self.assertTrue(e2["ok"], e2)
        self.assertFalse(e2["data"]["cache_hit"])

    def test_3_calibration_rejects_leaky_instrument_and_allows_legit_zero(self) -> None:
        leaky_inst = _write_file(
            self.ws / "evaluators" / "leaky.py",
            """
def evaluate(artifact, spec, tier="official"):
    return {"status": "OK", "verdict": "PASS", "tracks": {"val": 0.0}, "details": "always pass"}
""",
        )
        cal_path = _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_zero.json",
            [
                {
                    "case_id": "empty_must_fail",
                    "tier": "official",
                    "spec": {"public_input": {"target": 0}},
                    "artifact": {},
                    "expected_status": "OK",
                    "expected_verdict": "FAIL",
                },
                {
                    "case_id": "legit_zero_must_pass",
                    "tier": "official",
                    "spec": {"public_input": {"target": 0}},
                    "artifact": {"x": 0.0},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                },
            ],
        )
        bad_suite = run_calibration_suite(
            instrument_path=leaky_inst,
            instrument_role="VERDICT",
            calibration_suite_path=cal_path,
            workspace_root=self.ws,
        )
        self.assertFalse(bad_suite["passed"])

        good_inst = _write_file(
            self.ws / "evaluators" / "good_zero.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    pub = get_public_input(spec)
    if not isinstance(artifact, dict) or "x" not in artifact:
        return {"status": "OK", "verdict": "FAIL", "tracks": {}, "details": "missing x"}
    ok = float(artifact["x"]) == float(pub["target"])
    return {"status": "OK", "verdict": "PASS" if ok else "FAIL", "tracks": {"x": float(artifact["x"])}, "details": "checked"}
""",
        )
        good_suite = run_calibration_suite(
            instrument_path=good_inst,
            instrument_role="VERDICT",
            calibration_suite_path=cal_path,
            workspace_root=self.ws,
        )
        self.assertTrue(good_suite["passed"], good_suite)

    def test_4_stage_a_b_upgrade_recompute_append_only_incompatible_and_isolation(self) -> None:
        _write_file(
            self.ws / "evaluators" / "q1_v1.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"score": float(artifact["a"])}, "details": "v1"}
""",
        )
        _write_file(
            self.ws / "evaluators" / "q2_v1.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"q2": float(artifact["q2"])}, "details": "q2_v1"}
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_q1.json",
            [
                {
                    "case_id": "c1",
                    "tier": "official",
                    "spec": {"public_input": {"k": 1}},
                    "artifact": {"a": 2.0, "b": 3.0},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                }
            ],
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_q2.json",
            [
                {
                    "case_id": "c2",
                    "tier": "official",
                    "spec": {"public_input": {"k": 1}},
                    "artifact": {"q2": 1.0},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                }
            ],
        )
        self.assertTrue(
            self._call(
                "register_question_instrument",
                "works_engineer",
                "s_w1",
                question_id="Q1",
                instrument_id="inst_q1",
                instrument_role="VERDICT",
                instrument_rel_path="evaluators/q1_v1.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_q1.json",
                artifact_schema="python_run",
                plugin_protocol_version="v3",
                default_spec={"public_input": {"k": 1}},
            )["ok"]
        )
        self.assertTrue(
            self._call(
                "register_question_instrument",
                "works_engineer",
                "s_w1",
                question_id="Q2",
                instrument_id="inst_q2",
                instrument_role="VERDICT",
                instrument_rel_path="evaluators/q2_v1.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_q2.json",
                artifact_schema="python_run",
                plugin_protocol_version="v3",
                default_spec={"public_input": {"k": 1}},
            )["ok"]
        )

        _write_file(self.wt1 / "c_full.py", "def run(spec):\n    return {'a': 2.0, 'b': 5.0}\n")
        _write_file(self.wt1 / "c_part.py", "def run(spec):\n    return {'a': 2.0}\n")
        _write_file(self.wt2 / "c_q2.py", "def run(spec):\n    return {'q2': 9.0}\n")

        o_full = self._call(
            "run_isolated_eval", "explorer", "se1",
            node_id=self.n1, question_id="Q1", instrument_id="inst_q1", tier="official",
            artifact_rel_path="c_full.py", linguistic_prediction="含 a 与 b", declared_refs=[],
        )["data"]["obs_id"]
        o_part = self._call(
            "run_isolated_eval", "explorer", "se1",
            node_id=self.n1, question_id="Q1", instrument_id="inst_q1", tier="official",
            artifact_rel_path="c_part.py", linguistic_prediction="预测产物仅含字段 a 且通过 v1 仪器", declared_refs=[],
        )["data"]["obs_id"]
        o_q2 = self._call(
            "run_isolated_eval", "explorer", "se2",
            node_id=self.n2, question_id="Q2", instrument_id="inst_q2", tier="official",
            artifact_rel_path="c_q2.py", linguistic_prediction="Q2 独立评估", declared_refs=[],
        )["data"]["obs_id"]

        # 删除原始 worktree 源文件，验证 Stage A 产物已安全外置在 $PLUGIN_DATA
        shutil.rmtree(self.wt1)

        # 升版 Q1 仪器为 v2（要求字段 b）
        _write_file(
            self.ws / "evaluators" / "q1_v2.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"sum": float(artifact["a"]) + float(artifact["b"])}, "details": "v2"}
""",
        )
        up = self._call(
            "upgrade_instrument_with_calibration",
            "works_engineer",
            "s_w2",
            question_id="Q1",
            instrument_id="inst_q1",
            new_instrument_rel_path="evaluators/q1_v2.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_q1.json",
        )
        self.assertTrue(up["ok"], up)

        # 检查工造司待办列队可见 2 条 Q1 重评单，且 Q2 零波及
        q_resp = self._call("get_works_engineering_queue", "works_engineer", "s_w2", question_id="ALL")
        self.assertTrue(q_resp["ok"])
        pending_obs = {row["obs_id"] for row in q_resp["data"]["pending_revalidation"]}
        self.assertEqual(pending_obs, {o_full, o_part})

        q2_status = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = ?;", (o_q2,)).fetchone()["obs_status"]
        self.assertEqual(q2_status, "VALID_PASS")

        # 逐条触发 Stage B 离线重评（不覆写旧记录，append-only 新收据）
        rec_full = self._call("recompute_stage_b_only", "works_engineer", "s_w2", obs_id=o_full, question_id="Q1")
        self.assertTrue(rec_full["ok"], rec_full)
        self.assertEqual(rec_full["data"]["old_obs_status"], "SUPERSEDED_REVALIDATED")
        new_obs_id = rec_full["data"]["new_obs_id"]

        rec_part = self._call("recompute_stage_b_only", "works_engineer", "s_w2", obs_id=o_part, question_id="Q1")
        self.assertTrue(rec_part["ok"], rec_part)
        self.assertEqual(rec_part["data"]["status"], "INCOMPATIBLE")

        # 验证旧收据永久留存并标记为 SUPERSEDED_REVALIDATED / INCOMPATIBLE
        old_full_row = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = ?;", (o_full,)).fetchone()
        self.assertEqual(old_full_row["obs_status"], "SUPERSEDED_REVALIDATED")
        new_full_row = self.conn.execute(
            "SELECT obs_status, revalidated_from_obs_id, tracks_json FROM observations WHERE obs_id = ?;",
            (new_obs_id,),
        ).fetchone()
        self.assertEqual(new_full_row["obs_status"], "VALID_PASS")
        self.assertEqual(new_full_row["revalidated_from_obs_id"], o_full)
        self.assertEqual(json.loads(new_full_row["tracks_json"])["sum"], 7.0)

        old_part_row = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = ?;", (o_part,)).fetchone()
        self.assertEqual(old_part_row["obs_status"], "INCOMPATIBLE")

    def test_5_heavy_async_freeze_survives_worktree_edit_upgrade_and_restart(self) -> None:
        _write_file(
            self.ws / "evaluators" / "heavy_v1.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"v": artifact["v"], "inst": "v1", "tier": tier}, "details": "ok"}
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_h.json",
            [
                {
                    "case_id": "c1",
                    "tier": "heavy",
                    "spec": {"public_input": {"k": 1}},
                    "artifact": {"v": 42},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                }
            ],
        )
        self.assertTrue(
            self._call(
                "register_question_instrument",
                "works_engineer",
                "sw",
                question_id="Q1",
                instrument_id="inst_h",
                instrument_role="VERDICT",
                instrument_rel_path="evaluators/heavy_v1.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_h.json",
                artifact_schema="python_run",
                plugin_protocol_version="v3",
                default_spec={"public_input": {"k": 1}},
            )["ok"]
        )
        _write_file(self.wt1 / "tools" / "cfg.py", "VAL = 100\n")
        _write_file(self.wt1 / "cand.py", "import tools.cfg as c\ndef run(spec):\n    return {'v': c.VAL}\n")

        # 1. 入队 heavy 任务（同步立即返回 QUEUED 与 job_id）
        enq = self._call(
            "run_isolated_eval",
            "explorer",
            "se",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_h",
            tier="heavy",
            artifact_rel_path="cand.py",
            linguistic_prediction="重型异步冻结快照测试",
            declared_refs=[],
        )
        self.assertTrue(enq["ok"], enq)
        self.assertEqual(enq["data"]["status"], "QUEUED")
        job_id = enq["data"]["job_id"]

        # 2. 在作业尚未执行前：篡改工作树 + 升版仪器 v1->v2
        _write_file(self.wt1 / "tools" / "cfg.py", "VAL = 999\n")
        _write_file(
            self.ws / "evaluators" / "heavy_v2.py",
            """
from core_python.evaluators.base_instrument import get_public_input

def evaluate(artifact, spec, tier="official"):
    _ = get_public_input(spec)
    return {"status": "OK", "verdict": "PASS", "tracks": {"v": artifact["v"], "inst": "v2", "tier": tier}, "details": "v2"}
""",
        )
        self.assertTrue(
            self._call(
                "upgrade_instrument_with_calibration",
                "works_engineer",
                "sw2",
                question_id="Q1",
                instrument_id="inst_h",
                new_instrument_rel_path="evaluators/heavy_v2.py",
                calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_h.json",
            )["ok"]
        )

        # 3. 模拟进程重启后控制面恢复重跑 QUEUED 作业
        rec = cp.recover_pending_heavy_jobs(self.conn, workspace_root=str(self.ws))
        self.assertEqual(len(rec), 1)

        # 4. 凭 job_id 幂等查询结果：必须保持冻结时的 VAL=100 与 inst=v1，且预算仅扣 1 次
        polled = self._call(
            "run_isolated_eval",
            "explorer",
            "se",
            node_id=self.n1,
            question_id="Q1",
            instrument_id="inst_h",
            tier="heavy",
            artifact_rel_path="cand.py",
            linguistic_prediction="凭 job_id 轮询结果",
            declared_refs=[],
            job_id=job_id,
        )
        self.assertTrue(polled["ok"], polled)
        self.assertEqual(polled["data"]["status"], "COMPLETED")
        tracks = polled["data"].get("tracks") or polled["data"].get("result", {}).get("tracks") or {}
        self.assertEqual(tracks["v"], 100)
        self.assertEqual(tracks["inst"], "v1")
        job_row = self.conn.execute("SELECT budget_charged FROM async_eval_jobs WHERE job_id = ?;", (job_id,)).fetchone()
        self.assertEqual(job_row["budget_charged"], 1)

    def test_6_fts5_sanitization_multilingual_and_special_chars(self) -> None:
        res = self._call(
            "publish_external_literature_card",
            "external_surveyor",
            "s_surv",
            ref_id="R001",
            question_id="Q1",
            title="Hamilton-Jacobi & Convexity: 非线性控制 (v3)",
            abstract_md="本文构造了 Hamilton-Jacobi 方程下的非线性控制界并给出离散收敛性分析，适用于高维约束几何与多目标松弛构造的直接支撑。",
            exact_preconditions_md="紧致凸域且 Lipschitz 连续",
            formulas_or_operators_md="H(x, Du) <= C",
            read_depth="full_text",
            support_scope="HEURISTIC_CORRELATION",
            source_citation="Smith et al. (2025) https://example.org/hj-2025",
        )
        self.assertTrue(res["ok"], res)
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE lineage_nodes SET first_reflection_unlocked = 1 WHERE node_id = ?;", (self.n1,))
        for tricky_query in [
            'Hamilton-Jacobi "quoted" OR (a:b) * ^ NEAR/3 -negation',
            "非线性控制 AND +++ ??? /// [brackets]",
            '"""   :::   ***',
        ]:
            q = self._call(
                "query_library_catalog",
                "explorer",
                "se",
                node_id=self.n1,
                question_id="Q1",
                scope="ALL",
                keyword=tricky_query,
            )
            self.assertTrue(q["ok"], f"查询崩溃: {tricky_query} -> {q}")

    def test_7_readonly_schedule_snapshot_under_50ms(self) -> None:
        cp.schedule_control_plane_snapshot(self.conn)
        t0 = time.perf_counter()
        snap = cp.schedule_control_plane_snapshot(self.conn)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertIn("stage", snap)
        self.assertLess(elapsed_ms, 50.0, f"只读轮询耗时过高: {elapsed_ms:.2f}ms")


if __name__ == "__main__":
    unittest.main()
