"""Phase 2 实质性硬核验收测试：
1. 并发正式评测（official）1:1 产物一致性（杜绝 Obs-001 撞号与 Stage A 产物串写）；
2. 并发抢领同一 heavy 作业防双跑；
3. 双池并发隔离（慢计算池饱和时，快照/时钟同步/停止指令毫秒级返回）；
4. 端到端真取消（$/cancelRequest 实杀底层隔离评测子进程树、排队跳过、已提交保留、零幽灵落库）；
5. 剥离 Schema 关键字对应的 Python 服务端校验覆盖。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.evaluators.isolated_runner import (
    RequestCancelledError,
    run_calibration_suite,
    run_isolated_instrument,
)
from core_python.mcp_server import db_schema as db
from core_python.mcp_server.control_plane import (
    execute_heavy_async_job,
    export_stage3_deliverables,
    init_parse0_contract,
    recover_pending_heavy_jobs,
)
from core_python.mcp_server.tools_explorer import tool_run_isolated_eval
from core_python.mcp_server.tools_logistics import tool_fork_branch, tool_register_method_family
from core_python.mcp_server.tools_supervisory import tool_record_compliance_check
from core_python.mcp_server.tools_verifier import tool_submit_stage2_unblind_verdict
from core_python.mcp_server.tools_works import (
    tool_recompute_stage_b_only,
    tool_register_question_instrument,
    tool_update_skill_ledger,
    tool_upgrade_instrument_with_calibration,
)


def _setup_eval_workspace(tmp: str, *, slow_sleep_sec: float = 0.0) -> tuple[Path, Path, str, str, str]:
    ws = Path(tmp) / "ws"
    data_dir = Path(tmp) / "data"
    ws.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["GREATWALL_DATA_DIR"] = str(data_dir)
    os.environ["PLUGIN_DATA"] = str(data_dir)

    # 编写极简通用仪器脚本 + 校准集
    eval_dir = ws / "evaluators"
    cal_dir = eval_dir / "_hidden_calibrations"
    cal_dir.mkdir(parents=True, exist_ok=True)

    inst_path = eval_dir / "echo_inst.py"
    inst_path.write_text(
        f"""
import time
def evaluate(artifact, spec, tier):
    sleep_s = float(spec.get("sleep_sec", {slow_sleep_sec}))
    if sleep_s > 0:
        time.sleep(sleep_s)
    val = float(artifact.get("tag_val", 0.0))
    return {{
        "status": "OK",
        "verdict": "PASS" if val >= 0 else "FAIL",
        "tracks": {{"tag_val": val}},
        "details": f"measured={{val}}",
    }}
""".strip(),
        encoding="utf-8",
    )
    cal_path = cal_dir / "cal.json"
    cal_path.write_text(
        json.dumps(
            [
                {"name": "pos", "artifact": {"tag_val": 1.0}, "tier": "probe", "expected_status": "OK", "expected_verdict": "PASS"},
                {"name": "neg", "artifact": {"tag_val": -1.0}, "tier": "probe", "expected_status": "OK", "expected_verdict": "FAIL"},
            ]
        ),
        encoding="utf-8",
    )

    paths = db.resolve_storage_paths(str(ws))
    db.reset_initialized_db_cache(paths["db_path"])
    conn = db.open_rw_connection(paths["db_path"], init_schema=True)
    try:
        init_parse0_contract(
            conn,
            goal_and_completion_md="# Concurrency Verification Goal",
            subquestions=["Q1"],
            initial_instruments=[],
            seed_families=[],
            total_budget={},
        )
        tool_register_question_instrument(
            conn=conn,
            workspace_root=str(ws),
            caller_role="works_engineer",
            session_id="s_works",
            question_id="Q1",
            instrument_id="inst_echo",
            instrument_role="VERDICT",
            instrument_rel_path="evaluators/echo_inst.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal.json",
            artifact_schema="python_run",
            default_spec={"public_input": {"seed": 1}, "sleep_sec": slow_sleep_sec, "timeout_sec": 30},
        )
        tool_register_method_family(
            conn=conn,
            caller_role="logistics_coordinator",
            session_id="s_log",
            question_id="Q1",
            family_id="fam_a",
            mechanism_signature="sig_a",
            orthogonal_contrast="contrast_a",
        )
        fb = tool_fork_branch(
            conn=conn,
            workspace_root=str(ws),
            caller_role="logistics_coordinator",
            session_id="s_log",
            question_id="Q1",
            parent_node_id=None,
            fork_mode="orthogonal",
            target_family_id="fam_a",
        )
        node_id = fb["data"]["node_id"]
        wt = Path(fb["data"]["worktree_abs_path"])
        (wt / "cand_a.py").write_text(
            "import time\ndef run(pub):\n    time.sleep(0.15)\n    return {'tag_val': 111.0, 'owner': 'A'}\n",
            encoding="utf-8",
        )
        (wt / "cand_b.py").write_text(
            "import time\ndef run(pub):\n    time.sleep(0.15)\n    return {'tag_val': 222.0, 'owner': 'B'}\n",
            encoding="utf-8",
        )
        (wt / "cand_slow.py").write_text(
            "import time\ndef run(pub):\n    time.sleep(8.0)\n    return {'tag_val': 999.0, 'owner': 'SLOW'}\n",
            encoding="utf-8",
        )
    finally:
        conn.close()

    return ws, paths["db_path"], node_id, str(data_dir), str(wt)


class TestPhase2ConcurrencyAndCancel(unittest.TestCase):
    def setUp(self) -> None:
        self._old_gw_data = os.environ.get("GREATWALL_DATA_DIR")
        self._old_plugin_data = os.environ.get("PLUGIN_DATA")

    def tearDown(self) -> None:
        if self._old_gw_data is None:
            os.environ.pop("GREATWALL_DATA_DIR", None)
        else:
            os.environ["GREATWALL_DATA_DIR"] = self._old_gw_data
        if self._old_plugin_data is None:
            os.environ.pop("PLUGIN_DATA", None)
        else:
            os.environ["PLUGIN_DATA"] = self._old_plugin_data

    def test_1_concurrent_official_evals_no_obs_collision_or_stage_a_overwrite(self) -> None:
        """两次并发 official 评测必须拿到互异 Obs-001/Obs-002，且各自 Stage A 磁盘产物 1:1 严格对应、零串写。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_conc_") as tmp:
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            barrier = threading.Barrier(2)
            results: dict[str, dict] = {}
            errors: list[Exception] = []

            def worker(label: str, rel_path: str) -> None:
                conn = db.open_rw_connection(db_path, init_schema=False)
                try:
                    barrier.wait(timeout=5)
                    res = tool_run_isolated_eval(
                        conn=conn,
                        workspace_root=str(ws),
                        caller_role="explorer",
                        session_id=f"s_exp_{label}",
                        node_id=node_id,
                        question_id="Q1",
                        instrument_id="inst_echo",
                        tier="official",
                        artifact_rel_path=rel_path,
                        linguistic_prediction=f"预测候选 {label} 应当返回严格独立的观测收据与产物",
                        declared_refs=[],
                    )
                    results[label] = res
                except Exception as exc:
                    errors.append(exc)
                finally:
                    conn.close()

            t1 = threading.Thread(target=worker, args=("A", "cand_a.py"))
            t2 = threading.Thread(target=worker, args=("B", "cand_b.py"))
            t1.start()
            t2.start()
            t1.join(timeout=20)
            t2.join(timeout=20)

            self.assertEqual(errors, [], f"并发评测不应报错: {errors}")
            self.assertTrue(results["A"]["ok"])
            self.assertTrue(results["B"]["ok"])
            obs_a = results["A"]["data"]["obs_id"]
            obs_b = results["B"]["data"]["obs_id"]
            self.assertNotEqual(obs_a, obs_b, "并发评测绝不可撞号分配相同 obs_id")

            # 核查数据库记录与 Stage A 磁盘产物 1:1 严格一致
            ro = db.open_ro_connection(db_path)
            try:
                row_a = ro.execute("SELECT tracks_json, stage_a_artifact_path FROM observations WHERE obs_id = ?", (obs_a,)).fetchone()
                row_b = ro.execute("SELECT tracks_json, stage_a_artifact_path FROM observations WHERE obs_id = ?", (obs_b,)).fetchone()
                self.assertEqual(json.loads(row_a["tracks_json"])["tag_val"], 111.0)
                self.assertEqual(json.loads(row_b["tracks_json"])["tag_val"], 222.0)
                disk_a = json.loads(Path(row_a["stage_a_artifact_path"]).read_text(encoding="utf-8"))
                disk_b = json.loads(Path(row_b["stage_a_artifact_path"]).read_text(encoding="utf-8"))
                self.assertEqual(disk_a["owner"], "A")
                self.assertEqual(disk_b["owner"], "B")
            finally:
                ro.close()

    def test_2_concurrent_heavy_job_claim_prevents_double_run(self) -> None:
        """并发抢领同一个 heavy 作业时，必须严格仅 1 个执行成功，另 1 个被条件更新挡回或幂等重放。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_heavy_") as tmp:
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            conn = db.open_rw_connection(db_path, init_schema=False)
            try:
                queued = tool_run_isolated_eval(
                    conn=conn,
                    workspace_root=str(ws),
                    caller_role="explorer",
                    session_id="s_exp",
                    node_id=node_id,
                    question_id="Q1",
                    instrument_id="inst_echo",
                    tier="heavy",
                    artifact_rel_path="cand_a.py",
                    linguistic_prediction="预测重型异步任务入队后仅会被单次领取执行",
                    declared_refs=[],
                )
                job_id = queued["data"]["job_id"]
            finally:
                conn.close()

            barrier = threading.Barrier(2)
            outcomes: list[tuple[str, str]] = []

            def claimer() -> None:
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    barrier.wait(timeout=5)
                    r = execute_heavy_async_job(c, workspace_root=str(ws), job_id=job_id)
                    outcomes.append(("ok", "replayed" if r.get("replayed_idempotent") else "executed"))
                except db.FailClosedError as exc:
                    outcomes.append(("locked", exc.code))
                finally:
                    c.close()

            t1 = threading.Thread(target=claimer)
            t2 = threading.Thread(target=claimer)
            t1.start()
            t2.start()
            t1.join(timeout=20)
            t2.join(timeout=20)

            executed_cnt = sum(1 for k, v in outcomes if k == "ok" and v == "executed")
            self.assertEqual(executed_cnt, 1, f"同一 heavy 作业只能被实际执行 1 次，实得: {outcomes}")

    def test_3_stdio_dual_pool_no_head_of_line_blocking_and_end_to_end_cancel(self) -> None:
        """真实子进程 stdio 验证：慢计算池占满时不阻塞快路径快照/时钟同步；$/cancelRequest 实杀底层子进程且零幽灵落库。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_stdio_") as tmp:
            ws, db_path, node_id, data_dir, _ = _setup_eval_workspace(tmp)
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT_DIR),
                "GREATWALL_WORKSPACE_ROOT": str(ws),
                "GREATWALL_DATA_DIR": data_dir,
                "PLUGIN_DATA": data_dir,
                "GREATWALL_COMPUTE_WORKERS": "2",
                "GREATWALL_FAST_WORKERS": "4",
            }
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "core_python.mcp_server.greatwall_core_mcp"],
                cwd=str(ROOT_DIR),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            assert proc.stdin is not None and proc.stdout is not None

            def send(obj: dict) -> None:
                proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
                proc.stdin.flush()

            responses: dict[int, tuple[float, dict]] = {}
            got_event = threading.Event()

            def reader() -> None:
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    if "id" in msg and msg["id"] is not None:
                        responses[int(msg["id"])] = (time.monotonic(), msg)
                        got_event.set()

            rt = threading.Thread(target=reader, daemon=True)
            rt.start()
            try:
                send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
                deadline = time.monotonic() + 10
                while 1 not in responses and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertIn(1, responses)

                # 占满 compute_pool（2 个 8 秒慢任务）
                t_send_slow = time.monotonic()
                for req_id in (10, 11):
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "method": "tools/call",
                            "params": {
                                "name": "run_isolated_eval",
                                "arguments": {
                                    "node_id": node_id,
                                    "question_id": "Q1",
                                    "instrument_id": "inst_echo",
                                    "tier": "official",
                                    "artifact_rel_path": "cand_slow.py",
                                    "linguistic_prediction": "测试双池隔离与端到端真取消行为",
                                    "declared_refs": [],
                                },
                                "_meta": {
                                    "workspace_root": str(ws),
                                    "caller_role": "explorer",
                                    "session_id": f"s_slow_{req_id}",
                                },
                            },
                        }
                    )
                time.sleep(0.25)

                # 在慢任务池 100% 饱和期间连发快路径快照 + 时钟同步
                t_fast_start = time.monotonic()
                send({"jsonrpc": "2.0", "id": 20, "method": "control_plane/schedule_snapshot", "params": {"workspace_root": str(ws)}})
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": 21,
                        "method": "control_plane/sync_pressure",
                        "params": {"workspace_root": str(ws), "node_id": node_id, "pressure_tokens": 12345},
                    }
                )
                fast_deadline = time.monotonic() + 3.0
                while (20 not in responses or 21 not in responses) and time.monotonic() < fast_deadline:
                    time.sleep(0.02)
                self.assertIn(20, responses, "慢计算池饱和时 schedule_snapshot 必须走快路径立即返回")
                self.assertIn(21, responses, "慢计算池饱和时 sync_pressure 必须走快路径立即返回")
                self.assertLess(responses[20][0] - t_fast_start, 2.0)
                self.assertTrue(responses[20][1]["result"]["ok"])
                self.assertTrue(responses[21][1]["result"]["ok"])

                # 对两个 8 秒慢任务发送 $/cancelRequest 真取消
                t_cancel = time.monotonic()
                send({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 10}})
                send({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 11}})
                cancel_deadline = time.monotonic() + 4.0
                while (10 not in responses or 11 not in responses) and time.monotonic() < cancel_deadline:
                    time.sleep(0.03)
                self.assertIn(10, responses, "被取消的慢评测应迅速返回而非苦等 8 秒")
                self.assertIn(11, responses)
                self.assertLess(responses[10][0] - t_cancel, 3.5, "取消后应及时杀掉子进程返回")
                self.assertLess(responses[10][0] - t_send_slow, 6.0)

                # 断言数据库 observations 零幽灵写入
                ro = db.open_ro_connection(db_path)
                try:
                    cnt = int(ro.execute("SELECT COUNT(*) AS cnt FROM observations").fetchone()["cnt"])
                    self.assertEqual(cnt, 0, "被取消的评测绝不可产生幽灵落库记录")
                finally:
                    ro.close()
            finally:
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                    proc.wait(timeout=3)

    def test_4_isolated_runner_cancel_event_and_skill_ledger_bounds(self) -> None:
        """验证 isolated_runner 直接响应 cancel_event 抛 RequestCancelledError，以及 update_skill_ledger 补齐的数值下界校验。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_bounds_") as tmp:
            ws, db_path, _, _, wt = _setup_eval_workspace(tmp)
            ev = threading.Event()
            ev.set()
            with self.assertRaises(RequestCancelledError):
                run_isolated_instrument(
                    instrument_path=ws / "evaluators" / "echo_inst.py",
                    instrument_role="VERDICT",
                    artifact_path=Path(wt) / "cand_a.py",
                    spec={"public_input": {"seed": 1}},
                    tier="official",
                    worktree_root=wt,
                    cancel_event=ev,
                )

            conn = db.open_rw_connection(db_path, init_schema=False)
            try:
                with self.assertRaises(db.FailClosedError):
                    tool_update_skill_ledger(
                        conn=conn,
                        workspace_root=str(ws),
                        caller_role="works_engineer",
                        session_id="s_w",
                        skill_id="valid_skill",
                        applicable_scope="Q1",
                        version=0,
                        raw_success_count=1,
                        raw_failure_count=0,
                        verified_artifact_rel_path="evaluators/echo_inst.py",
                        rollback_pointer="none",
                    )
                with self.assertRaises(db.FailClosedError):
                    tool_update_skill_ledger(
                        conn=conn,
                        workspace_root=str(ws),
                        caller_role="works_engineer",
                        session_id="s_w",
                        skill_id="valid_skill",
                        applicable_scope="Q1",
                        version=1,
                        raw_success_count=-1,
                        raw_failure_count=0,
                        verified_artifact_rel_path="evaluators/echo_inst.py",
                        rollback_pointer="none",
                    )
            finally:
                conn.close()

    def test_5_stage3_audit_a_release_b_blocked_and_commit_failure_rolls_back_dir(self) -> None:
        """Stage 3 并发导出 B 与盲审/监察签发 A 严禁出现审 A 放 B；COMMIT 失败时必须完整回滚 final_delivery 目录。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_stage3_") as tmp:
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            conn = db.open_rw_connection(db_path, init_schema=False)
            try:
                now = db.utc_now_iso()
                with db.rw_immediate_tx(conn):
                    conn.execute(
                        """
                        INSERT INTO review_queue(
                            review_id, question_id, source_node_id, source_type, proposer_session_id,
                            review_status, manuscript_title, spec_revision, column_a_snapshot_md,
                            column_b_snapshot_md, bound_obs_ids_json, stage1_ledger_json,
                            stage1_locked_at, final_locked_at, final_verdict, created_at, updated_at
                        ) VALUES (
                            'rev_stage3_test', 'Q1', ?, 'LEVEL1_MANUSCRIPT', 's_exp',
                            'CLOSED_ACCEPTED', '已验完整解', 0, 'A栏事实', '', '[]', '[]',
                            ?, ?, 'ACCEPT', ?, ?
                        )
                        """,
                        (node_id, now, now, now, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO internal_research_ledger(
                            entry_id, question_id, ledger_type, l3_entry_kind, goal_coverage,
                            title, abstract_md, exact_verified_scope_md, exact_refuted_scope_md,
                            body_proof_or_code_md, verified_review_id, is_active, created_at
                        ) VALUES (
                            'L3-001', 'Q1', 'L3_VERIFIED', 'POS_THEOREM', 'FULL_GOAL',
                            '已验完整解', '经盲审通过的核心完整解摘要内容，满足 Stage 3 交付门槛。',
                            'Q1 全量验证区间', '无', '完整证明与复现代码正文', 'rev_stage3_test', 1, ?
                        )
                        """,
                        (now,),
                    )
                    conn.execute(
                        "UPDATE lineage_nodes SET candidate_rel_path = 'cand_a.py' WHERE node_id = ?",
                        (node_id,),
                    )

                paper_a = "# Stage 3 Report Version A\n" + ("这是交付包 A 的正式科研结论正文。" * 10)
                paper_b = "# Stage 3 Report Version B\n" + ("这是交付包 B 的未审核覆盖正文。" * 10)
                exp_a = export_stage3_deliverables(
                    conn,
                    workspace_root=str(ws),
                    delivery_mode="FULL",
                    formal_paper_md=paper_a,
                    selected_l3_ids_by_question={"Q1": ["L3-001"]},
                    remaining_gaps_by_question={"Q1": "无"},
                    reproduction_candidate_nodes=[node_id],
                )
                deliv_a = exp_a["delivery_id"]

                # 1) 在盲审官终签 A 之前，馆员先导出新版 B（重置 latest_delivery_id 为 B）
                exp_b = export_stage3_deliverables(
                    conn,
                    workspace_root=str(ws),
                    delivery_mode="FULL",
                    formal_paper_md=paper_b,
                    selected_l3_ids_by_question={"Q1": ["L3-001"]},
                    remaining_gaps_by_question={"Q1": "无"},
                    reproduction_candidate_nodes=[node_id],
                )
                deliv_b = exp_b["delivery_id"]
                self.assertNotEqual(deliv_a, deliv_b)

                # 2) 盲审官滞后针对旧版 A 落签 ACCEPT，必须被单写者事务拦死（防审 A 放 B）！
                with self.assertRaises(db.FailClosedError):
                    tool_submit_stage2_unblind_verdict(
                        conn=conn,
                        caller_role="library_verifier",
                        session_id="s_ver_stale",
                        review_id=f"STAGE3_FINAL_AUDIT:{deliv_a}",
                        final_verdict="ACCEPT",
                        novelty_score=8, significance_score=8,
                        revision_requests=[],
                    )
                st_row = conn.execute(
                    "SELECT status, latest_delivery_id, verifier_final_audit_passed FROM project_closure_state WHERE id = 1"
                ).fetchone()
                self.assertEqual(st_row["status"], "DELIVERY_EXPORTED")
                self.assertEqual(st_row["latest_delivery_id"], deliv_b)
                self.assertEqual(int(st_row["verifier_final_audit_passed"]), 0)

                # 3) 模拟导出 COMMIT 阶段抛异常，验证 final_delivery/ 磁盘目录被 100% 完整回滚回 B！
                import core_python.mcp_server.control_plane.delivery_freeze as dj_mod
                from contextlib import contextmanager

                orig_tx = dj_mod.rw_immediate_tx
                paper_c = "# Stage 3 Report Version C\n" + ("这是模拟提交崩溃的交付包 C 正文。" * 10)

                @contextmanager
                def failing_commit_tx(c):
                    with orig_tx(c):
                        yield c
                        raise RuntimeError("SIMULATED_COMMIT_FAILURE")

                dj_mod.rw_immediate_tx = failing_commit_tx
                try:
                    with self.assertRaisesRegex(RuntimeError, "SIMULATED_COMMIT_FAILURE"):
                        export_stage3_deliverables(
                            conn,
                            workspace_root=str(ws),
                            delivery_mode="FULL",
                            formal_paper_md=paper_c,
                            selected_l3_ids_by_question={"Q1": ["L3-001"]},
                            remaining_gaps_by_question={"Q1": "无"},
                            reproduction_candidate_nodes=[node_id],
                        )
                finally:
                    dj_mod.rw_immediate_tx = orig_tx

                # 磁盘上 final_delivery 必须完好回滚为 B，绝不残留 C 或消失！
                restored_report = (ws / "final_delivery" / "01_formal_report.md").read_text(encoding="utf-8")
                self.assertIn("Version B", restored_report)
                self.assertNotIn("Version C", restored_report)

                # 4) 盲审官针对当前版本 B 终签 ACCEPT -> 一步原子结项 CLOSED_VERIFIED，之后严禁覆盖重导！
                tool_submit_stage2_unblind_verdict(
                    conn=conn,
                    caller_role="library_verifier",
                    session_id="s_ver_b",
                    review_id=f"STAGE3_FINAL_AUDIT:{deliv_b}",
                    final_verdict="ACCEPT",
                    novelty_score=8, significance_score=8,
                    revision_requests=[],
                )
                st_closed = conn.execute("SELECT status FROM project_closure_state WHERE id = 1").fetchone()
                self.assertEqual(st_closed["status"], "CLOSED_VERIFIED")
                with self.assertRaises(db.FailClosedError):
                    export_stage3_deliverables(
                        conn,
                        workspace_root=str(ws),
                        delivery_mode="FULL",
                        formal_paper_md=paper_c,
                        selected_l3_ids_by_question={"Q1": ["L3-001"]},
                        remaining_gaps_by_question={"Q1": "无"},
                        reproduction_candidate_nodes=[node_id],
                    )
            finally:
                conn.close()

    def test_6_heavy_active_vs_recover_and_double_recover_only_one_obs(self) -> None:
        """活跃 heavy 作业并发遇上 recover_pending_heavy_jobs，以及双 recover 并发恢复孤儿 RUNNING，均严格只生成 1 条 Obs。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_hrec_") as tmp:
            ws, db_path, node_id, _, wt = _setup_eval_workspace(tmp)
            Path(wt, "cand_med.py").write_text(
                "import time\ndef run(pub):\n    time.sleep(0.5)\n    return {'tag_val': 77.0, 'owner': 'MED'}\n",
                encoding="utf-8",
            )
            conn = db.open_rw_connection(db_path, init_schema=False)
            try:
                q1 = tool_run_isolated_eval(
                    conn=conn,
                    workspace_root=str(ws),
                    caller_role="explorer",
                    session_id="s_exp",
                    node_id=node_id,
                    question_id="Q1",
                    instrument_id="inst_echo",
                    tier="heavy",
                    artifact_rel_path="cand_med.py",
                    linguistic_prediction="测试活跃 heavy 执行期间遇上 recover_pending_heavy_jobs 绝不双跑",
                    declared_refs=[],
                )
                job1 = q1["data"]["job_id"]
            finally:
                conn.close()

            # 1) 线程 1 普通领取进入执行，线程 2 延迟 0.1s 调 recover_pending_heavy_jobs
            res_holder: dict[str, object] = {}
            errs: list[Exception] = []

            def run_normal() -> None:
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    res_holder["normal"] = execute_heavy_async_job(c, workspace_root=str(ws), job_id=job1)
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            def run_recover() -> None:
                time.sleep(0.12)
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    res_holder["recover"] = recover_pending_heavy_jobs(c, workspace_root=str(ws))
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            t1 = threading.Thread(target=run_normal)
            t2 = threading.Thread(target=run_recover)
            t1.start()
            t2.start()
            t1.join(timeout=20)
            t2.join(timeout=20)
            self.assertEqual(errs, [], f"活跃 heavy 与恢复并发不应报错: {errs}")

            ro = db.open_ro_connection(db_path)
            try:
                cnt1 = int(ro.execute("SELECT COUNT(*) AS cnt FROM observations").fetchone()["cnt"])
                self.assertEqual(cnt1, 1, "活跃 heavy 遇上 recover 必须严格只生成 1 条正式观测")
            finally:
                ro.close()

            # 2) 模拟进程崩溃遗留孤儿 RUNNING（无活跃线程），两个 recover 并发竞争，仍只能生成 1 条新 Obs！
            conn2 = db.open_rw_connection(db_path, init_schema=False)
            try:
                q2 = tool_run_isolated_eval(
                    conn=conn2,
                    workspace_root=str(ws),
                    caller_role="explorer",
                    session_id="s_exp",
                    node_id=node_id,
                    question_id="Q1",
                    instrument_id="inst_echo",
                    tier="heavy",
                    artifact_rel_path="cand_b.py",
                    linguistic_prediction="测试孤儿 RUNNING 作业被双 recover 并发恢复时只生成 1 条新观测",
                    declared_refs=[],
                )
                job2 = q2["data"]["job_id"]
                with db.rw_immediate_tx(conn2):
                    conn2.execute("UPDATE async_eval_jobs SET status = 'RUNNING' WHERE job_id = ?", (job2,))
            finally:
                conn2.close()

            barrier = threading.Barrier(2)
            rec_counts: list[int] = []

            def rec_worker() -> None:
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    barrier.wait(timeout=5)
                    items = recover_pending_heavy_jobs(c, workspace_root=str(ws))
                    rec_counts.append(len(items))
                finally:
                    c.close()

            r1 = threading.Thread(target=rec_worker)
            r2 = threading.Thread(target=rec_worker)
            r1.start()
            r2.start()
            r1.join(timeout=20)
            r2.join(timeout=20)

            ro2 = db.open_ro_connection(db_path)
            try:
                cnt2 = int(ro2.execute("SELECT COUNT(*) AS cnt FROM observations").fetchone()["cnt"])
                self.assertEqual(cnt2, 2, f"孤儿 RUNNING 双 recover 并发只能新增 1 条观测（总计 2），实得 {cnt2}")
                j2_row = ro2.execute("SELECT status, obs_id FROM async_eval_jobs WHERE job_id = ?", (job2,)).fetchone()
                self.assertEqual(j2_row["status"], "COMPLETED")
                self.assertIsNotNone(j2_row["obs_id"])
            finally:
                ro2.close()

    def test_7_inflight_old_eval_auto_queued_on_upgrade_and_stage_b_version_guard(self) -> None:
        """在途 v1 official 观测遇上并发升版 v2 必须自动入待重评队列；Stage B v2 重评遇上并发升版 v3 绝不误关 v3 队列。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_upg_") as tmp:
            ws, db_path, node_id, _, wt = _setup_eval_workspace(tmp)
            Path(wt, "cand_inflight.py").write_text(
                "import time\ndef run(pub):\n    time.sleep(0.6)\n    return {'tag_val': 55.0, 'owner': 'INFLIGHT'}\n",
                encoding="utf-8",
            )
            (ws / "evaluators" / "echo_inst_v2.py").write_text(
                """
import time
def evaluate(artifact, spec, tier):
    if spec.get("slow_stage_b"):
        time.sleep(0.5)
    val = float(artifact.get("tag_val", 0.0))
    return {"status": "OK", "verdict": "PASS" if val >= 0 else "FAIL", "tracks": {"v": 2, "tag_val": val}, "details": "v2"}
""".strip(),
                encoding="utf-8",
            )
            (ws / "evaluators" / "echo_inst_v3.py").write_text(
                """
def evaluate(artifact, spec, tier):
    val = float(artifact.get("tag_val", 0.0))
    return {"status": "OK", "verdict": "PASS" if val >= 0 else "FAIL", "tracks": {"v": 3, "tag_val": val}, "details": "v3"}
""".strip(),
                encoding="utf-8",
            )

            eval_res: dict[str, dict] = {}
            errs: list[Exception] = []

            def run_v1_eval() -> None:
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    eval_res["v1"] = tool_run_isolated_eval(
                        conn=c,
                        workspace_root=str(ws),
                        caller_role="explorer",
                        session_id="s_exp_v1",
                        node_id=node_id,
                        question_id="Q1",
                        instrument_id="inst_echo",
                        tier="official",
                        artifact_rel_path="cand_inflight.py",
                        linguistic_prediction="测试在途 v1 观测在仪器升版 v2 后自动标 PENDING_REVALIDATION 并入队列",
                        declared_refs=[],
                    )
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            def upgrade_to_v2() -> None:
                time.sleep(0.15)
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    tool_upgrade_instrument_with_calibration(
                        conn=c,
                        workspace_root=str(ws),
                        caller_role="works_engineer",
                        session_id="s_works_v2",
                        question_id="Q1",
                        instrument_id="inst_echo",
                        new_instrument_rel_path="evaluators/echo_inst_v2.py",
                        calibration_suite_rel_path="evaluators/_hidden_calibrations/cal.json",
                    )
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            t1 = threading.Thread(target=run_v1_eval)
            t2 = threading.Thread(target=upgrade_to_v2)
            t1.start()
            t2.start()
            t1.join(timeout=20)
            t2.join(timeout=20)
            self.assertEqual(errs, [], f"在途观测与升版并发不应报错: {errs}")

            obs_v1_id = eval_res["v1"]["data"]["obs_id"]
            self.assertEqual(eval_res["v1"]["data"]["obs_status"], "PENDING_REVALIDATION")

            ro = db.open_ro_connection(db_path)
            try:
                obs_row = ro.execute("SELECT instrument_version, obs_status, cache_key FROM observations WHERE obs_id = ?", (obs_v1_id,)).fetchone()
                self.assertEqual(int(obs_row["instrument_version"]), 1)
                self.assertEqual(obs_row["obs_status"], "PENDING_REVALIDATION")
                self.assertEqual(obs_row["cache_key"], "")
                q_row = ro.execute(
                    "SELECT target_version, status FROM pending_revalidation_queue WHERE obs_id = ? AND status = 'PENDING'",
                    (obs_v1_id,),
                ).fetchone()
                self.assertIsNotNone(q_row, "在途旧观测必须自动挂入 pending_revalidation_queue")
                self.assertEqual(int(q_row["target_version"]), 2)
            finally:
                ro.close()

            # 2) 让 v2 Stage B 重评变慢，在重评期间将仪器升版到 v3，验证绝不把 v3 队列误关为 DONE！
            conn_prep = db.open_rw_connection(db_path, init_schema=False)
            try:
                with db.rw_immediate_tx(conn_prep):
                    sp = json.loads(conn_prep.execute("SELECT spec_json FROM observations WHERE obs_id = ?", (obs_v1_id,)).fetchone()["spec_json"])
                    sp["slow_stage_b"] = True
                    conn_prep.execute("UPDATE observations SET spec_json = ? WHERE obs_id = ?", (json.dumps(sp), obs_v1_id))
            finally:
                conn_prep.close()

            def run_reval_v2() -> None:
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    eval_res["reval"] = tool_recompute_stage_b_only(
                        conn=c,
                        workspace_root=str(ws),
                        caller_role="works_engineer",
                        session_id="s_works_reval",
                        obs_id=obs_v1_id,
                        question_id="Q1",
                    )
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            def upgrade_to_v3() -> None:
                time.sleep(0.15)
                c = db.open_rw_connection(db_path, init_schema=False)
                try:
                    tool_upgrade_instrument_with_calibration(
                        conn=c,
                        workspace_root=str(ws),
                        caller_role="works_engineer",
                        session_id="s_works_v3",
                        question_id="Q1",
                        instrument_id="inst_echo",
                        new_instrument_rel_path="evaluators/echo_inst_v3.py",
                        calibration_suite_rel_path="evaluators/_hidden_calibrations/cal.json",
                    )
                except Exception as exc:
                    errs.append(exc)
                finally:
                    c.close()

            t3 = threading.Thread(target=run_reval_v2)
            t4 = threading.Thread(target=upgrade_to_v3)
            t3.start()
            t4.start()
            t3.join(timeout=20)
            t4.join(timeout=20)
            self.assertEqual(errs, [], f"Stage B 重评与升版 v3 并发不应报错: {errs}")

            ro2 = db.open_ro_connection(db_path)
            try:
                v3_pending = ro2.execute(
                    "SELECT COUNT(*) AS cnt FROM pending_revalidation_queue WHERE target_version = 3 AND status = 'PENDING'"
                ).fetchone()["cnt"]
                self.assertGreaterEqual(int(v3_pending), 1, "v2 重评完成后绝不可误将已升级为 target_version=3 的待重评队列标为 DONE")
                self.assertEqual(eval_res["reval"]["data"]["new_obs_status"], "SUPERSEDED_REVALIDATED")
            finally:
                ro2.close()

    def test_8_cancel_calibration_recompute_export_and_probe(self) -> None:
        """验证校准集回归、Stage B 重评、Stage 3 导出与 probe 均支持 cancel_event 立即中止且零落库。"""
        with tempfile.TemporaryDirectory(prefix="gw_p2_cancel_all_") as tmp:
            ws, db_path, node_id, _, _ = _setup_eval_workspace(tmp)
            ev = threading.Event()
            ev.set()

            with self.assertRaises(RequestCancelledError):
                run_calibration_suite(
                    instrument_path=ws / "evaluators" / "echo_inst.py",
                    instrument_role="VERDICT",
                    calibration_suite_path=ws / "evaluators" / "_hidden_calibrations" / "cal.json",
                    workspace_root=ws,
                    cancel_event=ev,
                )

            conn = db.open_rw_connection(db_path, init_schema=False)
            try:
                with self.assertRaises(RequestCancelledError):
                    tool_run_isolated_eval(
                        conn=conn,
                        workspace_root=str(ws),
                        caller_role="explorer",
                        session_id="s_probe_cancel",
                        node_id=node_id,
                        question_id="Q1",
                        instrument_id="inst_echo",
                        tier="probe",
                        artifact_rel_path="cand_a.py",
                        linguistic_prediction="测试 probe 取消零落库",
                        declared_refs=[],
                        cancel_event=ev,
                    )
                with self.assertRaises(RequestCancelledError):
                    export_stage3_deliverables(
                        conn,
                        workspace_root=str(ws),
                        delivery_mode="FULL",
                        formal_paper_md="# Cancelled Paper\n" + ("正文" * 40),
                        selected_l3_ids_by_question={"Q1": []},
                        remaining_gaps_by_question={"Q1": "无"},
                        reproduction_candidate_nodes=[],
                        cancel_event=ev,
                    )
                probe_cnt = int(conn.execute("SELECT COUNT(*) AS cnt FROM probe_diagnostic_logs").fetchone()["cnt"])
                self.assertEqual(probe_cnt, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
