"""P1 验收测试：v2.2 三真相 SQLite DDL、触发器硬门禁（防 P26/0 盲审入 L3）与插件化隔离评估器。"""

from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest

CORE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "core_python"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from evaluators.isolated_runner import (  # noqa: E402
    run_isolated_evaluation,
    run_stage_b_revaluation,
)
from mcp_server.db_schema import (  # noqa: E402
    open_ro_connection,
    open_rw_connection,
    resolve_storage_paths,
    rw_immediate_tx,
    utc_now_iso,
)


class TestP1DbAndRunner(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_p1_")
        self.tmp_path = pathlib.Path(self._tmp.name)
        self.ws_dir = self.tmp_path / "research_ws"
        self.ws_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_data = self.tmp_path / "plugin_data"
        self._old_env = os.environ.get("PLUGIN_DATA")
        os.environ["PLUGIN_DATA"] = str(self.plugin_data)
        self.paths = resolve_storage_paths(str(self.ws_dir))
        self.conn = open_rw_connection(self.paths["db_path"], init_schema=True)

    def tearDown(self) -> None:
        self.conn.close()
        if self._old_env is None:
            os.environ.pop("PLUGIN_DATA", None)
        else:
            os.environ["PLUGIN_DATA"] = self._old_env
        self._tmp.cleanup()

    def _seed_node(self, node_id: str = "node_q1_n1", question_id: str = "Q1") -> None:
        now = utc_now_iso()
        wt = self.ws_dir / "worktrees" / "b_q1_famA"
        wt.mkdir(parents=True, exist_ok=True)
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                """
                INSERT INTO lineage_nodes(
                    node_id, epoch_id, question_id, branch_id, family_id,
                    parent_node_id, generation, worktree_abs_path, created_at, updated_at
                ) VALUES (?, 1, ?, 'b_q1_famA', 'famA', NULL, 1, ?, ?, ?)
                """,
                (node_id, question_id, str(wt), now, now),
            )

    def test_schema_drops_bound_state_version_and_isolates_external_db(self) -> None:
        self.assertFalse(str(self.paths["db_path"]).startswith(str(self.ws_dir)))
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(lineage_nodes)").fetchall()]
        self.assertNotIn("bound_state_version", cols)
        self.assertIn("worktree_abs_path", cols)
        self.assertIn("sanitized_code_diff_md", cols)
        self.assertIn("scratch_log_json", cols)
        from contextlib import closing

        with closing(open_ro_connection(self.paths["db_path"])) as ro:
            ro_mode = ro.execute("PRAGMA query_only;").fetchone()[0]
            self.assertEqual(ro_mode, 1)

    def test_trigger_blocks_pending_revalidation_without_queue_p26(self) -> None:
        self._seed_node()
        now = utc_now_iso()
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                """
                INSERT INTO observations(
                    obs_id, epoch_id, question_id, branch_id, node_id, run_claim_id,
                    candidate_hash, spec_hash, domain_hook_sha256, obs_status, passed,
                    linguistic_prediction, created_at, updated_at
                ) VALUES ('Obs-001', 1, 'Q1', 'b_q1_famA', 'node_q1_n1', 'rc_1', 'c1', 's1', 'h1', 'VALID', 1, 'pred', ?, ?)
                """,
                (now, now),
            )
        # 未写 pending_revalidation_queue 直接更新状态，必被硬件触发器拦截
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.conn.execute(
                "UPDATE observations SET obs_status = 'PENDING_REVALIDATION' WHERE obs_id = 'Obs-001'"
            )
        self.assertIn("PENDING_REVALIDATION_MISSING_QUEUE_ROW", str(ctx.exception))

        # 先同事务入队再更新状态，必须成功
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                """
                INSERT INTO pending_revalidation_queue(queue_id, obs_id, question_id, old_hook_sha256, new_hook_sha256, status, created_at, updated_at)
                VALUES ('rq_1', 'Obs-001', 'Q1', 'h1', 'h2', 'PENDING', ?, ?)
                """,
                (now, now),
            )
            self.conn.execute(
                "UPDATE observations SET obs_status = 'PENDING_REVALIDATION', comparable_rank_score = NULL WHERE obs_id = 'Obs-001'"
            )
        row = self.conn.execute("SELECT obs_status FROM observations WHERE obs_id = 'Obs-001'").fetchone()
        self.assertEqual(row["obs_status"], "PENDING_REVALIDATION")

    def test_triggers_block_unreviewed_l3_and_stage1_ledger_mutation(self) -> None:
        self._seed_node()
        now = utc_now_iso()
        # 1. 无 verified_review_id 写 L3 必拦截
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, title, abstract_md, created_at
                ) VALUES ('L3-999', 'Q1', 'L3_VERIFIED', 'LEVEL1_MANUSCRIPT', 'fake', 'fake abstract', ?)
                """,
                (now,),
            )

        # 2. review_queue Stage 1 锁死后不可篡改 stage1_ledger_json
        with rw_immediate_tx(self.conn):
            self.conn.execute(
                """
                INSERT INTO review_queue(
                    review_id, source_node_id, question_id, proposer_session_id, reviewer_session_id,
                    review_status, column_a_snapshot_md, stage1_ledger_json, stage1_verdict, stage1_locked_at, created_at
                ) VALUES ('rev_001', 'node_q1_n1', 'Q1', 'comp_1', 'ver_1', 'STAGE2_UNBLIND', 'col a', '[{"claim":"x","evidence_location_and_quote":"Obs-001","is_verified":true}]', 'PASS', ?, ?)
                """,
                (now, now),
            )
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.conn.execute(
                "UPDATE review_queue SET stage1_ledger_json = '[]' WHERE review_id = 'rev_001'"
            )
        self.assertIn("STAGE1_LEDGER_IMMUTABLE", str(ctx.exception))

        # 3. Stage 2 未 CLOSED_ACCEPTED_TO_L3 前写 L3 必拦截
        with self.assertRaises(sqlite3.IntegrityError) as ctx2:
            self.conn.execute(
                """
                INSERT INTO internal_research_ledger(
                    entry_id, question_id, ledger_type, source_type, title, abstract_md, verified_review_id, created_at
                ) VALUES ('L3-001', 'Q1', 'L3_VERIFIED', 'LEVEL1_MANUSCRIPT', 'premature', 'premature', 'rev_001', ?)
                """,
                (now,),
            )
        self.assertIn("L3_REQUIRES_BLIND_REVIEW_PASS", str(ctx2.exception))

    def test_isolated_runner_p14_main_guard_p2_timeout_stage_a_persist_and_plugin_protocol(self) -> None:
        wt = self.ws_dir / "worktrees" / "b_q1_famA"
        tools_dir = wt / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        (tools_dir / "math_helper.py").write_text(
            '"""What it does: add bias. Interface: add_bias(x). What it does NOT do: ODE."""\ndef add_bias(x):\n    return x + 2.0\n',
            encoding="utf-8",
        )
        cand = wt / "cand_q1.py"
        cand.write_text(
            """
from tools.math_helper import add_bias

def run(public_input):
    print('{"comparable_rank_score": 99999, "validity_state": "VALID"}')  # 企图用 stdout 欺骗
    val = add_bias(float(public_input.get("x", 1.0)))
    return {"x_val": val, "residual": 0.01}

if __name__ == "__main__":
    raise RuntimeError("P14_MAIN_BLOCK_MUST_NOT_RUN_DURING_EVAL")
""",
            encoding="utf-8",
        )
        hook_v1 = self.tmp_path / "hook_Q1_v1.py"
        hook_v1.write_text(
            """
def evaluate_candidate(stage_a_artifact, spec):
    ok = float(stage_a_artifact["residual"]) < float(spec.get("max_residual", 0.05))
    score = 1.0 / max(1e-6, float(stage_a_artifact["residual"]))
    return {"passed": ok, "metrics": {"residual": stage_a_artifact["residual"], "score": score}, "details": "hook_v1 checked"}
""",
            encoding="utf-8",
        )
        stage_a_file = self.paths["eval_artifacts_dir"] / "Obs-001" / "stage_a_output.json"
        spec_v1 = {
            "public_input": {"x": 3.0, "secret_answer": 42},
            "domain_hook_path": str(hook_v1),
            "max_residual": 0.05,
            "timeout_sec": 15.0,
        }
        res = run_isolated_evaluation(
            candidate_path=str(cand),
            domain="Q1",
            evaluator_spec=spec_v1,
            output_dir=str(self.paths["outputs_dir"]),
            stage_a_output_path=str(stage_a_file),
            worktree_root=str(wt),
        )
        self.assertEqual(res["obs_status"], "VALID", res)
        self.assertTrue(res["passed"])
        self.assertAlmostEqual(res["metrics"]["residual"], 0.01)
        self.assertEqual(res["details"], "hook_v1 checked")
        self.assertTrue(stage_a_file.is_file(), "stage_a_output.json 必须持久化在工作目录外，不能随 TemporaryDirectory 销毁")
        saved = json.loads(stage_a_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["x_val"], 5.0)

        # 用收紧后的 hook_v2 免 Stage A 秒级重评持久化产物
        hook_v2 = self.tmp_path / "hook_Q1_v2.py"
        hook_v2.write_text(
            """
def evaluate_candidate(stage_a_artifact, spec):
    ok = float(stage_a_artifact["residual"]) < float(spec.get("max_residual", 0.005))
    return {"passed": ok, "metrics": {"residual": stage_a_artifact["residual"]}, "details": "hook_v2 tightened"}
""",
            encoding="utf-8",
        )
        reval = run_stage_b_revaluation(
            domain="Q1",
            evaluator_spec={"domain_hook_path": str(hook_v2), "max_residual": 0.005},
            stage_a_output_path=str(stage_a_file),
        )
        self.assertEqual(reval["obs_status"], "MEASURED_NON_IMPROVEMENT")
        self.assertFalse(reval["passed"])
        self.assertEqual(reval["details"], "hook_v2 tightened")

        # 动态 timeout_sec 生效校验（写一个 2.5s 睡眠脚本配 timeout_sec=1.0 -> STAGE_A_TIMEOUT）
        slow_cand = wt / "slow_cand.py"
        slow_cand.write_text("import time\ndef run(pub):\n    time.sleep(2.5)\n    return {'ok': True}\n", encoding="utf-8")
        slow_res = run_isolated_evaluation(
            candidate_path=str(slow_cand),
            domain="generic",
            evaluator_spec={"timeout_sec": 1.0},
            output_dir=str(self.paths["outputs_dir"]),
        )
        self.assertEqual(slow_res["obs_status"], "EXECUTION_ERROR")
        self.assertEqual(slow_res["failure_category"], "STAGE_A_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
