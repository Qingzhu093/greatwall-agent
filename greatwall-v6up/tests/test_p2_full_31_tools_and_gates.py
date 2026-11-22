"""P2 全量 31 窄工具、门禁不变量、盲审触发器、版本绑定终核、返工状态机与 JSON-RPC 测试。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core_python.mcp_server import control_plane_service as cp
from core_python.mcp_server import db_schema as db
from core_python.mcp_server import fact_bridge
from core_python.mcp_server import greatwall_core_mcp as mcp


def _write_file(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _write_json(path: Path, obj: object) -> str:
    return _write_file(path, json.dumps(obj, ensure_ascii=False, indent=2))


class TestP2Full31ToolsAndGates(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gw_v3_p2_")
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
            goal_and_completion_md="# Goal\nQ1 纯数学证明；Q2 数值验证。",
            subquestions=[
                {"question_id": "Q1", "title": "纯推导猜想证明"},
                {"question_id": "Q2", "title": "多轨道数值验证"},
            ],
            question_order=["Q1", "Q2"],
            min_commitment_window_sec=3600,
            stage="STAGE2_EVOLVE",
        )

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

    def _create_family_and_branch(
        self,
        qid: str,
        fam_id: str,
        requires: list[str] | None = None,
    ) -> tuple[str, str, str, Path]:
        f = self._call(
            "register_method_family",
            "logistics_coordinator",
            "s_log",
            question_id=qid,
            family_id=fam_id,
            mechanism_signature=f"机制：{fam_id}",
            orthogonal_contrast="与其他学派原理正交",
        )
        self.assertTrue(f["ok"], f)
        b = self._call(
            "fork_branch",
            "logistics_coordinator",
            "s_log",
            question_id=qid,
            fork_mode="orthogonal",
            target_family_id=fam_id,
            requires=requires or [],
        )
        self.assertTrue(b["ok"], b)
        return fam_id, b["data"]["branch_id"], b["data"]["node_id"], Path(b["data"]["worktree_abs_path"])

    def _submit_artifact_handoff(self, node_id: str, branch_id: str, qid: str, sid: str, rel_file: str = "proof.md") -> dict:
        return self._call(
            "submit_node_handoff",
            "lineage_companion",
            sid,
            node_id=node_id,
            branch_id=branch_id,
            question_id=qid,
            mechanism_summary="纯解析推导与结构化构造",
            evidence_grade="ARTIFACT_ONLY",
            column_a_facts_md=f"已完成独立推导文档 {rel_file}，无外部仪器依赖。",
            column_b_hypothesis_md="若放松紧致假设可能仍成立。",
            will_md="下代可补充边界极值讨论。",
            obs_ids=[],
            dead_ends=[],
            candidate_rel_path=rel_file,
            is_empty_crash=False,
        )

    def test_1_pure_derivation_no_obs_37_unlock_and_pre_spawn_isolation(self) -> None:
        lit = self._call(
            "publish_external_literature_card",
            "library_surveyor",
            "s_surv",
            ref_id="R001",
            question_id="Q1",
            title="Algebraic Invariants in Extremal Graphs",
            abstract_md="本文建立了一组新的代数不变量，用于排除特定极大图的反例构造，提供了直接的理论界证明与反证策略，并系统讨论了连通图特征值上界与极值结构之间的等价转化关系，可供纯理论推导借鉴。",
            exact_preconditions_md="有限简单连通图",
            formulas_or_operators_md="lambda_1(G) <= sqrt(2m)",
            read_depth="full_text",
            support_scope="DIRECT_PROOF_OR_EXACT_MEASUREMENT",
            source_citation="Doe (2024) https://example.org/alg-2024",
        )
        self.assertTrue(lit["ok"], lit)

        _, bid, nid, wt = self._create_family_and_branch("Q1", "fam_alg")
        _write_file(wt / "proof_draft.md", "# 引理 1\n纯解析推导完成，无需外部数值仪器。\n")

        # 0-37% 外藏 [R###] 允许开放读取，但内藏 L2/L3 严禁偷读！
        r_ext_ok = self._call("query_library_catalog", "explorer", "s_exp1", node_id=nid, question_id="Q1", scope="EXTERNAL_R", keyword="代数")
        self.assertTrue(r_ext_ok["ok"], r_ext_ok)

        denied = self._call("query_library_catalog", "explorer", "s_exp1", node_id=nid, question_id="Q1", scope="INTERNAL_L3", keyword="代数")
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error_code"], db.ERR_LOCKED)

        # PRE_SPAWN 上下文绝不包含 37% 图书馆目录预览
        pre = self._call("get_companion_context", "lineage_companion", "s_comp1", branch_id=bid, node_id=nid, mode="PRE_SPAWN")
        self.assertTrue(pre["ok"], pre)
        self.assertNotIn("internal_catalog_preview", pre["data"])

        # 保存开题五栏看板
        brief = self._call(
            "save_lineage_briefing",
            "lineage_companion",
            "s_comp1",
            branch_id=bid,
            node_id=nid,
            sec1_mechanism="代数不变量路线",
            sec2_verified_baseline="暂无外部观测，首代纯推导",
            sec3_bottleneck="尚未处理非正则图界",
            sec4_dead_ends="当前为首代探索节点，尚无历史死胡同记录。",
            sec5_immediate_will="完成主引理解析证明",
        )
        self.assertTrue(brief["ok"], brief)

        # 模拟上下文达到 38% 水位（>=37%），但 eval_count == 0：纯推导节点仍必须能合法解锁 L2/L3 拉取！
        cp.sync_session_pressure(self.conn, node_id=nid, pressure_tokens=190000)
        ref = self._call(
            "record_reflection_and_unlock_pull",
            "lineage_companion",
            "s_comp1",
            node_id=nid,
            selected_categories=["Attractor Tasks", "Boundary Assumptions"],
            holiday_prompt_id=3,
            turns=[{"question": "是否可放宽正则性前提？", "answer": "可改用 Cauchy-Schwarz 不等式消除正则假设。"}],
            verdict_3state="SUFFICIENT_EVIDENCE",
        )
        self.assertTrue(ref["ok"], ref)
        self.assertEqual(ref["data"]["first_reflection_unlocked"], 1)

        # 解锁后合法查询内藏
        allowed = self._call("query_library_catalog", "explorer", "s_exp1", node_id=nid, question_id="Q1", scope="ALL", keyword="代数")
        self.assertTrue(allowed["ok"], allowed)

        # 70% 提交纯理论交接（ARTIFACT_ONLY，空 obs_ids）
        ho = self._submit_artifact_handoff(nid, bid, "Q1", "s_comp1", "proof_draft.md")
        self.assertTrue(ho["ok"], ho)
        self.assertEqual(ho["data"]["node_status"], "AWAITING_TRIAGE")

    def test_2_blind_review_triggers_anti_spoof_cross_branch_and_rbac(self) -> None:
        _, b1, n1, wt1 = self._create_family_and_branch("Q1", "fam_a")
        _, b2, n2, _ = self._create_family_and_branch("Q2", "fam_b")
        _write_file(wt1 / "thm.md", "# Theorem 1\nComplete proof.\n")

        # 跨分支读取 DAG 必须被拒
        cross_read = self._call("read_lineage_graph", "explorer", "s_e1", node_id=n1, branch_id=b2)
        self.assertFalse(cross_read["ok"])
        self.assertEqual(cross_read["error_code"], db.ERR_AUTH)

        # RBAC 越权与参数伪造身份拦截
        rbac_err = self._call("fork_branch", "explorer", "s_e1", question_id="Q1", fork_mode="NEW_ORTHOGONAL_FAMILY", target_family_id="x")
        self.assertFalse(rbac_err["ok"])
        self.assertEqual(rbac_err["error_code"], db.ERR_AUTH)

        spoof = mcp.dispatch_tool_call(
            "fork_branch",
            {
                "question_id": "Q1",
                "fork_mode": "NEW_ORTHOGONAL_FAMILY",
                "target_family_id": "x",
                "caller_role": "logistics_coordinator",
                "_meta": {"caller_role": "logistics_coordinator"},
            },
            workspace_root=str(self.ws),
            caller_role="explorer",
            session_id="s_e1",
        )
        self.assertFalse(spoof["ok"])
        self.assertEqual(spoof["error_code"], db.ERR_AUTH)

        # 直接绕过审稿单往 internal_research_ledger 插 L3：必须被 SQLite 触发器拦截！
        with self.assertRaises(sqlite3.IntegrityError):
            with db.rw_immediate_tx(self.conn):
                self.conn.execute(
                    """
                    INSERT INTO internal_research_ledger(
                        entry_id, ledger_type, question_id, l3_entry_kind, goal_coverage,
                        title, abstract_md, exact_verified_scope_md, verified_review_id,
                        created_at
                    ) VALUES ('L3_FAKE', 'L3_VERIFIED', 'Q1', 'POS_THEOREM', 'FULL_GOAL', 'fake', 'fake', 'fake', NULL, ?);
                    """,
                    (db.utc_now_iso(),),
                )

        # 正常交接 -> 后勤分诊送审 LEVEL_1
        self.assertTrue(self._submit_artifact_handoff(n1, b1, "Q1", "s_same_session", "thm.md")["ok"])
        tri = self._call(
            "triage_node",
            "logistics_coordinator",
            "s_log",
            node_id=n1,
            assigned_family_id="fam_a",
            triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW",
            rationale="达到正式送审标准",
        )
        self.assertTrue(tri["ok"], tri)
        review_id = tri["data"]["created_review_id"]

        # 同会话自审必须被拒
        self_rev = self._call("get_blind_manuscript", "library_verifier", "s_same_session", review_id=review_id)
        self.assertFalse(self_rev["ok"])
        self.assertEqual(self_rev["error_code"], db.ERR_CONFLICT)

        # 独立审稿会话完成 Stage 1 -> Stage 2 ACCEPT 入库 L3
        bm = self._call("get_blind_manuscript", "library_verifier", "s_ver1", review_id=review_id)
        self.assertTrue(bm["ok"], bm)
        self.assertNotIn("branch_id", bm["data"])

        # 未完成 Stage 1 就调用 Stage 2 解盲必须被拒
        premature = self._call("get_unblinded_manuscript_and_peers", "library_verifier", "s_ver1", review_id=review_id)
        self.assertFalse(premature["ok"])
        self.assertEqual(premature["error_code"], db.ERR_LOCKED)

        s1 = self._call(
            "submit_stage1_blind_ledger",
            "library_verifier",
            "s_ver1",
            review_id=review_id,
            question_id="Q1",
            ledger_items=[{"claim": "主定理成立", "evidence_location_and_quote": "thm.md L1-L3: Complete proof", "status": "VERIFIED"}],
            stage1_verdict="PASS",
        )
        self.assertTrue(s1["ok"], s1)

        # Stage 1 锁死不可二次覆写（SQLite 触发器）
        s1_again = self._call(
            "submit_stage1_blind_ledger",
            "library_verifier",
            "s_ver1",
            review_id=review_id,
            question_id="Q1",
            ledger_items=[{"claim": "主定理成立", "evidence_location_and_quote": "thm.md L1", "status": "REFUTED"}],
            stage1_verdict="REFUTED",
        )
        self.assertFalse(s1_again["ok"])

        unb = self._call("get_unblinded_manuscript_and_peers", "library_verifier", "s_ver1", review_id=review_id)
        self.assertTrue(unb["ok"], unb)
        s2 = self._call(
            "submit_stage2_unblind_verdict",
            "library_verifier",
            "s_ver1",
            review_id=review_id,
            final_verdict="ACCEPT",
            l3_entry_kind="POS_THEOREM",
            goal_coverage="FULL_GOAL",
            title="Q1 主定理完整证明",
            abstract_md="在标准连通图假设下定理 1 严格成立，且经过独立沙箱核验无逻辑漏洞，可作为本子题完整证明成果收录入馆。",
            exact_verified_scope_md="全部有限简单连通图",
        )
        self.assertTrue(s2["ok"], s2)
        self.assertTrue(str(s2["data"]["created_l3_id"]).startswith("L3-"))

        # 触发器防跨题冒用审稿单（用 Q1 的 review_id 插 Q2 的 L3）
        with self.assertRaises(sqlite3.IntegrityError):
            with db.rw_immediate_tx(self.conn):
                self.conn.execute(
                    """
                    INSERT INTO internal_research_ledger(
                        entry_id, ledger_type, question_id, l3_entry_kind, goal_coverage,
                        title, abstract_md, exact_verified_scope_md, verified_review_id,
                        created_at
                    ) VALUES ('L3_CROSS', 'L3_VERIFIED', 'Q2', 'POS_THEOREM', 'FULL_GOAL', 'cross', 'cross', 'cross', ?, ?);
                    """,
                    (review_id, db.utc_now_iso()),
                )

    def test_3_stage3_version_binding_prevents_audit_a_release_b(self) -> None:
        l3_by_q: dict[str, list[str]] = {}
        nodes_by_q: list[str] = []
        for qid in ("Q1", "Q2"):
            fid, bid, nid, wt = self._create_family_and_branch(qid, f"fam_{qid}")
            _write_file(wt / "res.md", f"# {qid} Result\nVerified.\n")
            self.assertTrue(self._submit_artifact_handoff(nid, bid, qid, f"sc_{qid}", "res.md")["ok"])
            rid = self._call(
                "triage_node", "logistics_coordinator", "sl",
                node_id=nid, assigned_family_id=fid, triage_level="LEVEL_1",
                action="SUBMIT_BLIND_REVIEW", rationale="送审",
            )["data"]["created_review_id"]
            self._call("get_blind_manuscript", "library_verifier", f"sv_{qid}", review_id=rid)
            self._call(
                "submit_stage1_blind_ledger", "library_verifier", f"sv_{qid}",
                review_id=rid, question_id=qid,
                ledger_items=[{"claim": "结论成立", "evidence_location_and_quote": "res.md L1-L2: Verified", "status": "VERIFIED"}],
                stage1_verdict="PASS",
            )
            self._call("get_unblinded_manuscript_and_peers", "library_verifier", f"sv_{qid}", review_id=rid)
            s2 = self._call(
                "submit_stage2_unblind_verdict", "library_verifier", f"sv_{qid}",
                review_id=rid, final_verdict="ACCEPT", l3_entry_kind="POS_THEOREM", goal_coverage="FULL_GOAL",
                title=f"{qid} 结论", abstract_md=f"{qid} 严格成立并通过全部独立复核，结论边界清晰且已与馆藏条目逐项对齐无冲突，可供终稿直接引用。",
                exact_verified_scope_md=f"{qid} 全域",
            )
            self.assertTrue(s2["ok"], s2)
            l3_by_q[qid] = [s2["data"]["created_l3_id"]]
            nodes_by_q.append(nid)

        # FULL 模式终稿验证测试将 min_commitment_window_sec 置 0（窗口阻断在 test_5 单独测）
        with db.rw_immediate_tx(self.conn):
            self.conn.execute("UPDATE parse0_contract SET min_commitment_window_sec = 0 WHERE contract_id = 'active';")
        # 导出版本 A
        exp_a = self._call(
            "export_stage3_final_delivery",
            "library_surveyor",
            "s_surv",
            delivery_mode="FULL",
            formal_paper_md="# 终稿版本 A\n完整论文正文 A：本报告系统汇总 Q1 与 Q2 两条正交主线的严格定理证明、独立盲审验证结论与可复现工件路径清单，所有核心结论均已通过两阶段盲审并入库 L3。\n",
            selected_l3_ids_by_question=l3_by_q,
            remaining_gaps_by_question={"Q1": "", "Q2": ""},
            reproduction_candidate_nodes=nodes_by_q,
        )
        self.assertTrue(exp_a["ok"], exp_a)
        deliv_a = exp_a["data"]["delivery_id"]

        # 核查员对版本 A 做 Stage 3 终核通过
        audit_a = self._call(
            "submit_stage2_unblind_verdict",
            "library_verifier",
            "s_ver_final",
            review_id=f"STAGE3_FINAL_AUDIT:{deliv_a}",
            final_verdict="ACCEPT",
            title="版本 A 终稿审定",
            abstract_md="版本 A 全部溯源与引用一致。",
        )
        self.assertTrue(audit_a["ok"], audit_a)

        # 在监察委签发前，采编重导出修改后的版本 B！
        exp_b = self._call(
            "export_stage3_final_delivery",
            "library_surveyor",
            "s_surv",
            delivery_mode="FULL",
            formal_paper_md="# 终稿版本 B\n修改后的论文正文 B（内容已变更）：本修订版更新了 Q2 结论的表述并补充了实验参数边界说明，用于验证终稿版本 SHA-256 绑定门禁是否能阻断旧审稿签字放行新版。\n",
            selected_l3_ids_by_question=l3_by_q,
            remaining_gaps_by_question={"Q1": "", "Q2": ""},
            reproduction_candidate_nodes=nodes_by_q,
        )
        self.assertTrue(exp_b["ok"], exp_b)
        deliv_b = exp_b["data"]["delivery_id"]
        self.assertNotEqual(exp_a["data"]["delivery_sha256"], exp_b["data"]["delivery_sha256"])

        # 监察委试图直接签发 CLOSURE_GATE(PASSED)（偷梁换柱审 A 放 B）：必须被拒！
        blocked = self._call(
            "record_compliance_check",
            "supervisory_committee",
            "s_sup",
            stage="CLOSURE_GATE",
            status="PASSED",
            blocking_questions=[],
            notes="尝试直接放行",
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error_code"], db.ERR_LOCKED)
        self.assertIn("防审 A 放 B", blocked["error"])

        # 核查员重审版本 B 通过后，监察委再签发 CLOSURE_GATE(PASSED) 才晋升 CLOSED_VERIFIED
        audit_b = self._call(
            "submit_stage2_unblind_verdict",
            "library_verifier",
            "s_ver_final2",
            review_id=f"STAGE3_FINAL_AUDIT:{deliv_b}",
            final_verdict="ACCEPT",
            title="版本 B 终稿审定",
            abstract_md="版本 B 全部引用与哈希匹配。",
        )
        self.assertTrue(audit_b["ok"], audit_b)

        passed = self._call(
            "record_compliance_check",
            "supervisory_committee",
            "s_sup",
            stage="CLOSURE_GATE",
            status="PASSED",
            blocking_questions=[],
            notes="三项版本校验全部通过，准予结项。",
        )
        self.assertTrue(passed["ok"], passed)
        st = self.conn.execute("SELECT status FROM project_closure_state WHERE id = 1;").fetchone()["status"]
        self.assertEqual(st, "CLOSED_VERIFIED")

    def test_4_revise_loop_active_revising_forbids_salvage_and_level2_dead_end(self) -> None:
        fid, b1, n1, wt = self._create_family_and_branch("Q1", "fam_rev")
        _write_file(wt / "draft.md", "# Draft\n")

        # 第 1 次送审 -> Stage 1 判 REVISE -> 节点回退 ACTIVE_REVISING
        self.assertTrue(self._submit_artifact_handoff(n1, b1, "Q1", "sc1", "draft.md")["ok"])
        r1 = self._call(
            "triage_node", "logistics_coordinator", "sl",
            node_id=n1, assigned_family_id=fid, triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW", rationale="首审",
        )["data"]["created_review_id"]
        self._call("get_blind_manuscript", "library_verifier", "sv1", review_id=r1)
        rev1 = self._call(
            "submit_stage1_blind_ledger", "library_verifier", "sv1",
            review_id=r1, question_id="Q1",
            ledger_items=[{"claim": "边界完备", "evidence_location_and_quote": "draft.md L1: 缺边界证明", "status": "UNVERIFIED"}],
            stage1_verdict="REVISE",
            revision_or_refutation_reason="请补全边界情形推导",
        )
        self.assertTrue(rev1["ok"], rev1)
        self.assertEqual(rev1["data"]["node_status"], "ACTIVE_REVISING")

        # ACTIVE_REVISING 期间严禁 Auditor 打捞引理
        salv_blocked = self._call(
            "propose_salvaged_lemma",
            "library_verifier",
            "sv_aud",
            source_node_id=n1,
            question_id="Q1",
            title="抢先打捞",
            abstract_md="试图在返工期打捞该节点的中间引理，本段摘要用于测试返工期对打捞接口的严格锁死机制是否生效。",
            column_a_self_contained_proof_md="自洽证明",
            column_b_scope_notes_md="范围",
            bound_obs_ids=[],
        )
        self.assertFalse(salv_blocked["ok"])
        self.assertEqual(salv_blocked["error_code"], db.ERR_LOCKED)

        # 第 2 次送审 -> Stage 2 判 REVISE（共用 revise_count 记为 2）
        self.assertTrue(self._submit_artifact_handoff(n1, b1, "Q1", "sc2", "draft.md")["ok"])
        r2 = self._call(
            "triage_node", "logistics_coordinator", "sl",
            node_id=n1, assigned_family_id=fid, triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW", rationale="二审",
        )["data"]["created_review_id"]
        self._call("get_blind_manuscript", "library_verifier", "sv2", review_id=r2)
        self._call(
            "submit_stage1_blind_ledger", "library_verifier", "sv2",
            review_id=r2, question_id="Q1",
            ledger_items=[{"claim": "阶段一复核", "evidence_location_and_quote": "draft.md L1: s1 ok", "status": "VERIFIED"}],
            stage1_verdict="PASS",
        )
        self._call("get_unblinded_manuscript_and_peers", "library_verifier", "sv2", review_id=r2)
        rev2 = self._call(
            "submit_stage2_unblind_verdict", "library_verifier", "sv2",
            review_id=r2, final_verdict="REVISE",
            title="仍需修订", abstract_md="Stage 2 要求补全对照分析。",
            revision_requests=["补全与馆藏引理的等价性比较"],
        )
        self.assertTrue(rev2["ok"], rev2)
        self.assertEqual(rev2["data"]["revise_count"], 2)

        # 第 3 次送审 -> Stage 1 判 REVISE -> 满 3 次自动沉淀入 L2(UNRESOLVED_OBJECTION) 并封存
        self.assertTrue(self._submit_artifact_handoff(n1, b1, "Q1", "sc3", "draft.md")["ok"])
        r3 = self._call(
            "triage_node", "logistics_coordinator", "sl",
            node_id=n1, assigned_family_id=fid, triage_level="LEVEL_1",
            action="SUBMIT_BLIND_REVIEW", rationale="三审",
        )["data"]["created_review_id"]
        self._call("get_blind_manuscript", "library_verifier", "sv3", review_id=r3)
        rev3 = self._call(
            "submit_stage1_blind_ledger", "library_verifier", "sv3",
            review_id=r3, question_id="Q1",
            ledger_items=[{"claim": "边界闭环", "evidence_location_and_quote": "draft.md L1: 三次仍未闭合", "status": "REFUTED"}],
            stage1_verdict="REVISE",
            revision_or_refutation_reason="三次返工后仍未闭合核心质疑",
            exact_refuted_scope_md="边界情形未闭合",
        )
        self.assertTrue(rev3["ok"], rev3)
        self.assertEqual(rev3["data"]["revise_count"], 3)
        l2_row = self.conn.execute(
            "SELECT ledger_type, l2_category FROM internal_research_ledger WHERE verified_review_id = ?;", (r3,)
        ).fetchone()
        self.assertIsNotNone(l2_row)
        self.assertEqual(l2_row["ledger_type"], "L2_FAILURE_RECORD")
        self.assertEqual(l2_row["l2_category"], "UNRESOLVED_OBJECTION")

        # 另起节点测试 LEVEL_2（工程未通）满 3 次只记入 lineage_dead_ends(IMPL_FAILURE)，绝不污染图书馆 L2
        fid2, b2, cur_nid, wt2 = self._create_family_and_branch("Q1", "fam_eng")
        _write_file(wt2 / "impl.py", "# impl\n")
        for i in range(1, 5):
            self.assertTrue(self._submit_artifact_handoff(cur_nid, b2, "Q1", f"sc_l2_{i}", "impl.py")["ok"])
            t_l2 = self._call(
                "triage_node", "logistics_coordinator", "sl",
                node_id=cur_nid, assigned_family_id=fid2, triage_level="LEVEL_2",
                action="INPLACE_REPAIR", rationale=f"工程未通第 {i} 次",
            )
            self.assertTrue(t_l2["ok"], t_l2)
            if t_l2["data"].get("exhausted"):
                break
            cur_nid = t_l2["data"]["next_node_id"]
        dead_row = self.conn.execute("SELECT category FROM lineage_dead_ends WHERE branch_id = ?;", (b2,)).fetchone()
        self.assertIsNotNone(dead_row)
        self.assertEqual(dead_row["category"], "IMPL_FAILURE")
        l2_cnt = self.conn.execute("SELECT COUNT(*) AS c FROM internal_research_ledger WHERE question_id = 'Q1' AND title LIKE '%fam_eng%';").fetchone()["c"]
        self.assertEqual(l2_cnt, 0)

    def test_5_human_stop_truth_source_pair(self) -> None:
        # min_commitment_window_sec=3600 且未在控制面登记人工叫停：传 human_aborted=True 必报 HUMAN_STOP_NOT_RECORDED 且不放行
        denied = self._call(
            "check_stage2_closure_gate",
            "supervisory_committee",
            "s_sup",
            mode="PARTIAL_ON_HUMAN_STOP",
            human_aborted=True,
        )
        self.assertTrue(denied["ok"], denied)
        self.assertFalse(denied["data"]["closure_allowed"])
        self.assertEqual(denied["data"]["gate_code"], "HUMAN_STOP_NOT_RECORDED")

        # 控制面正式写入 human_stop_requested_at 后，无视 min_commitment_window 立即放行
        cp.record_human_stop(self.conn, note="用户点击停止按钮")
        allowed = self._call(
            "check_stage2_closure_gate",
            "supervisory_committee",
            "s_sup",
            mode="PARTIAL_ON_HUMAN_STOP",
            human_aborted=True,
        )
        self.assertTrue(allowed["ok"], allowed)
        self.assertTrue(allowed["data"]["closure_allowed"])

    def test_6_branch_requires_concentration_circuit_breaker_and_dependency_propagation(self) -> None:
        # 1. 分支级 requires：Q1 某分支依赖 Q2，但 Q1 另一独立分支无依赖（绝不跨分支并集连坐）
        _, b_indep, n_indep, wt_indep = self._create_family_and_branch("Q1", "fam_indep", requires=[])
        _, b_dep, n_dep, _ = self._create_family_and_branch("Q1", "fam_dep", requires=["L3-999"])
        req_indep = json.loads(self.conn.execute("SELECT requires_json FROM lineage_nodes WHERE node_id = ?;", (n_indep,)).fetchone()["requires_json"])
        req_dep = json.loads(self.conn.execute("SELECT requires_json FROM lineage_nodes WHERE node_id = ?;", (n_dep,)).fetchone()["requires_json"])
        self.assertTrue(cp.check_branch_requires_satisfied(self.conn, req_indep)[0])
        self.assertFalse(cp.check_branch_requires_satisfied(self.conn, req_dep)[0])

        # 2. >=2 && >50% 无豁免聚拢检测（2 条同家族分支占 2/2 = 100% > 50%）
        f_same, _, _, _ = self._create_family_and_branch("Q2", "fam_hot")
        b_dup = self._call(
            "fork_branch", "logistics_coordinator", "s_log",
            question_id="Q2", fork_mode="lateral", target_family_id=f_same,
        )
        self.assertTrue(b_dup["ok"], b_dup)
        alerts = cp.compute_family_concentration_alerts(self.conn)
        self.assertTrue(any(a["question_id"] == "Q2" and a["family_id"] == f_same for a in alerts), alerts)

        # 3. 3 次连续 INSTRUMENT_ERROR 熔断 UNHEALTHY
        _write_file(
            self.ws / "evaluators" / "broken_runtime.py",
            """
def evaluate(artifact, spec, tier="official"):
    if artifact.get("trigger_bug"):
        raise RuntimeError("instrument runtime bug")
    return {"status": "OK", "verdict": "PASS", "tracks": {"ok": True}, "details": "ok"}
""",
        )
        _write_json(
            self.ws / "evaluators" / "_hidden_calibrations" / "cal_brk.json",
            [
                {
                    "case_id": "c1",
                    "tier": "official",
                    "spec": {"public_input": {"k": 1}},
                    "artifact": {"trigger_bug": False},
                    "expected_status": "OK",
                    "expected_verdict": "PASS",
                }
            ],
        )
        reg = self._call(
            "register_question_instrument",
            "works_engineer",
            "sw",
            question_id="Q1",
            instrument_id="inst_brk",
            instrument_role="VERDICT",
            instrument_rel_path="evaluators/broken_runtime.py",
            calibration_suite_rel_path="evaluators/_hidden_calibrations/cal_brk.json",
            artifact_schema="python_run",
            plugin_protocol_version="v3",
            default_spec={"public_input": {"k": 1}},
        )
        self.assertTrue(reg["ok"], reg)

        _write_file(wt_indep / "bug.py", "def run(spec):\n    return {'trigger_bug': True}\n")
        for i in range(3):
            ev = self._call(
                "run_isolated_eval", "explorer", "se",
                node_id=n_indep, question_id="Q1", instrument_id="inst_brk", tier="official",
                artifact_rel_path="bug.py", linguistic_prediction=f"触发仪器故障 #{i+1}", declared_refs=[],
            )
            self.assertTrue(ev["ok"], ev)
            self.assertEqual(ev["data"]["status"], "INSTRUMENT_ERROR")

        health = self.conn.execute(
            "SELECT health_status, consecutive_error_count FROM instruments WHERE instrument_id = 'inst_brk' AND is_active = 1;"
        ).fetchone()
        self.assertEqual(health["health_status"], "UNHEALTHY")
        self.assertGreaterEqual(health["consecutive_error_count"], 3)

        # 4. 非连坐依赖传播：仅 REQUIRED_PREMISE 触发重检，MOTIVATING_REF 零连坐
        with db.rw_immediate_tx(self.conn):
            self.conn.execute(
                """
                INSERT INTO epistemic_edges(edge_id, source_id, target_id, edge_track, edge_type, session_id, metadata_json, created_at)
                VALUES
                  ('e_mot', 'entry_mot', 'entry_root', 'CLAIM_DECLARED', 'MOTIVATING_REF', 's', '{}', ?),
                  ('e_req', 'entry_req', 'entry_root', 'CLAIM_DECLARED', 'REQUIRED_PREMISE', 's', '{}', ?);
                """,
                (db.utc_now_iso(), db.utc_now_iso()),
            )
        prop = db.propagate_dependency_recheck(self.conn, "entry_root")
        self.assertIn("entry_req", prop["recheck_triggered_entries"])
        self.assertNotIn("entry_mot", prop["recheck_triggered_entries"])

    def test_7_jsonrpc_and_fact_bridge_cli(self) -> None:
        init_resp = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init_resp["result"]["serverInfo"]["version"], "3.0.0")

        list_resp = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(len(list_resp["result"]["tools"]), 32)

        snap_resp = mcp.handle_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "control_plane/schedule_snapshot",
            "params": {"workspace_root": str(self.ws)},
        })
        self.assertTrue(snap_resp["result"]["ok"])

        rc = fact_bridge.record_fact_cli([str(self.ws), "s_cli_1", "worktrees/b1/a.py", "READ", "n_1", '{"tool":"read"}'])
        self.assertEqual(rc, 0)
        row = self.conn.execute(
            "SELECT source_id, target_id, edge_type, session_id FROM epistemic_edges WHERE session_id = 's_cli_1';"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["source_id"], "n_1")
        self.assertEqual(row["target_id"], "worktrees/b1/a.py")
        self.assertEqual(row["edge_type"], "READ")


if __name__ == "__main__":
    unittest.main()
