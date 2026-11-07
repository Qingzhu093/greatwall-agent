"""
Great Wall Agent V4.2 — Unattended Campaign Orchestration Engine.
负责将沙箱 (`CleanRoomSandbox`)、轻量级档案馆 (`LightweightArchive`) 与跨进程评测器 (`IsolatedEvaluator`)
串联成完整的无人值守攻关状态机，并内置预写式事务日志 (WAL) 以确保断网/崩溃后毫秒级幂等恢复。
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .archive import LightweightArchive
from .evaluator import DEFAULT_TEXTBOOK_COMMONSENSE, ASTCodeInspector, IsolatedEvaluator
from .sandbox import CleanRoomSandbox, SandboxPathJail, force_cleanup_directory


class GreatWallEngine:
    """
    长城 Agent V4.2 顶层编排引擎：
    - 管理 `.kernel_vault/state_graph.json` 与 `wal.jsonl`；
    - 驱动 Phase 0 开局消歧与知识蒸馏四件套固化；
    - 管理并发槽位 (Slots)、60 步导师深挖计数与原位 3 轮内省室触发；
    - 执行终局防吹牛数字硬绑定与五件套交付信封打包。
    """

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.sandbox = CleanRoomSandbox(self.workspace_root)
        self.archive = LightweightArchive(self.sandbox.shared_readonly_dir)
        self.evaluator = IsolatedEvaluator(self.sandbox.vault_dir, self.sandbox.shared_readonly_dir)

        self.state_file = self.sandbox.vault_dir / "state_graph.json"
        self.wal_file = self.sandbox.vault_dir / "wal.jsonl"
        self.distilled_dir = self.sandbox.shared_readonly_dir / "distilled"
        self.distilled_dir.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # 1. 状态持久化与 WAL 预写日志
    # ========================================================================

    def _append_wal(self, event_type: str, payload: Dict[str, Any]) -> int:
        entry = {
            "ts": time.time(),
            "event": event_type,
            "payload": payload,
        }
        with self.wal_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return int(entry["ts"] * 1000)

    def load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {
                "initialized": False,
                "task_id": "",
                "domain_type": "ALGO_COMPETITION",
                "primary_metric": "score",
                "higher_is_better": True,
                "anchor_s0_commit": "",
                "anchor_s0_score": 0.0,
                "total_steps_executed": 0,
                "max_concurrent_slots": 4,
                "active_slots": {},
                "lineages": {},
                "pending_proposals": [],
                "reflections_completed": 0,
            }
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save_state(self, state: Dict[str, Any]) -> None:
        tmp_path = self.state_file.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_file)

    # ========================================================================
    # 2. Phase 0：工作区初始化与开局先蒸馏固化 (Opening Distillation)
    # ========================================================================

    def init_campaign(
        self,
        task_id: str,
        task_description: str,
        domain_type: str = "ALGO_COMPETITION",
        primary_metric: str = "score",
        higher_is_better: bool = True,
        max_concurrent_slots: int = 4,
        resolved_ambiguities: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        初始化长程无人值守工作区，执行开局数据静态探针 (EDA Grounding)，
        并锁死 `shared_readonly/task_config.yaml` (杜绝盘中分裂 A/~A 歧义分支)。
        """
        self._append_wal("INIT_CAMPAIGN", {"task_id": task_id, "domain_type": domain_type})

        # 扫描 shared_readonly/datasets_public/ 自动生成多模态数据资产清点表 (MLE-STAR A_data 哨兵)
        datasets_dir = self.sandbox.shared_readonly_dir / "datasets_public"
        datasets_dir.mkdir(parents=True, exist_ok=True)
        discovered_files = [
            p.relative_to(datasets_dir).as_posix()
            for p in sorted(datasets_dir.rglob("*"))
            if p.is_file()
        ]

        task_contract = {
            "task_id": task_id,
            "domain_type": domain_type,
            "task_description": task_description,
            "evaluation_protocol": {
                "primary_metric": primary_metric,
                "higher_is_better": higher_is_better,
                "anchor_baseline_s0_score": 0.0,
            },
            "data_completeness_inventory": discovered_files,
            "resolved_ambiguities": resolved_ambiguities or [],
            "locked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        task_cfg_path = self.sandbox.shared_readonly_dir / "task_config.yaml"
        task_cfg_path.write_text(json.dumps(task_contract, ensure_ascii=False, indent=2), encoding="utf-8")

        state = self.load_state()
        state.update(
            {
                "initialized": True,
                "task_id": task_id,
                "domain_type": domain_type,
                "primary_metric": primary_metric,
                "higher_is_better": higher_is_better,
                "max_concurrent_slots": max_concurrent_slots,
                "data_inventory": discovered_files,
                "created_at": time.time(),
            }
        )
        self.save_state(state)
        self.archive.rebuild_l0_index()

        return {
            "status": "OK",
            "workspace_root": str(self.workspace_root),
            "task_config_path": str(task_cfg_path),
            "discovered_data_modalities": discovered_files,
            "next_step": "请运行 Phase 0 开局知识蒸馏，然后调用 gw_lock_distillation 固化 SOTA 锚点卡与零号强基线 s_0。",
        }

    def lock_opening_distillation(
        self,
        orthogonal_families: List[Dict[str, Any]],
        obsolete_blacklist: Optional[List[str]] = None,
        must_reuse_libraries: Optional[List[str]] = None,
        pitfall_guardrails: Optional[List[str]] = None,
        anchor_baseline_code: str = "",
        commonsense_blacklist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        固化 Phase 0 开局蒸馏四件套，并在沙箱中实跑验分铸造【零号强基线 s_0】：
        1. `sota_anchors.json`：正交方法族与反预训练偏见黑名单 (Familiarity Bias Blacklist)
        2. `build_vs_buy_contract.json`：强制调库 vs 鼓励手搓边界清单
        3. `pitfall_guardrails.md`：防数据泄漏与多源数据完整性红线卡
        4. `anchor_baseline.py`：实机跑分入库的零号强基线 $s_0$
        """
        state = self.load_state()
        if not state.get("initialized"):
            raise RuntimeError("工作区尚未初始化，请先调用 gw_init_campaign！")

        sota_pack = {
            "obsolete_familiarity_blacklist": obsolete_blacklist or [
                "LogisticRegression / Ridge as final model",
                "ResNet18 / ResNet50 (2015) without modern ViT/ConvNeXt comparison",
                "Unvectorized triple Python for-loops on N > 2000",
            ],
            "trivial_commonsense_blacklist": commonsense_blacklist or DEFAULT_TEXTBOOK_COMMONSENSE,
            "orthogonal_families": orthogonal_families,
        }
        (self.distilled_dir / "sota_anchors.json").write_text(
            json.dumps(sota_pack, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        build_vs_buy = {
            "must_reuse_infrastructure": must_reuse_libraries or [
                "sklearn.model_selection.(StratifiedKFold | GroupKFold | TimeSeriesSplit)",
                "scipy.spatial.cKDTree / scipy.spatial.distance.cdist",
                "archive.ledger.primitives.*",
            ],
            "encouraged_custom_operator_zones": [f.get("custom_zone", "核心瓶颈算子与领域特征块") for f in orthogonal_families],
        }
        (self.distilled_dir / "build_vs_buy_contract.json").write_text(
            json.dumps(build_vs_buy, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        guardrails_lines = ["# 🛡️ 多模态数据源清点与防踩坑红线卡 (Pitfall Guardrails)\n"]
        for idx, g in enumerate(pitfall_guardrails or [
            "一切特征归一化与缺失值统计量填充必须在每个 CV 折的 train_idx 内部独立 fit，严禁全局 fit_transform！",
            "严禁在代码中硬编码测试集算例编号或静态预测数组！",
        ], 1):
            guardrails_lines.append(f"{idx}. {g}")
        (self.distilled_dir / "pitfall_guardrails.md").write_text("\n".join(guardrails_lines) + "\n", encoding="utf-8")

        # 若提供了零号强基线源码，在临时孤岛实跑评测并归档为 s_0 快照
        s0_commit = "GENESIS_S0"
        s0_score = 0.0
        s0_eval_receipt = {}

        if anchor_baseline_code.strip():
            s0_island = self.sandbox.worktrees_dir / "_anchor_s0_builder"
            if s0_island.exists():
                force_cleanup_directory(s0_island, self.sandbox.graveyard_dir)
            (s0_island / "src").mkdir(parents=True, exist_ok=True)
            (s0_island / "legacy_out").mkdir(parents=True, exist_ok=True)
            (s0_island / "src" / "main.py").write_text(anchor_baseline_code, encoding="utf-8")
            (self.distilled_dir / "anchor_baseline.py").write_text(anchor_baseline_code, encoding="utf-8")

            s0_commit = self.sandbox.store_snapshot(s0_island, parent_commit="GENESIS", message="Phase 0 Anchor Baseline s_0")
            s0_eval_receipt = self.evaluator.evaluate_island(
                island_dir=s0_island,
                node_id="ANCHOR_S0",
                commit_hash=s0_commit,
                entry_script="src/main.py",
                higher_is_better=state.get("higher_is_better", True),
            )
            if "scores" in s0_eval_receipt:
                s0_score = float(s0_eval_receipt["scores"]["frozen_benchmark"])
                self.archive.update_leaderboard(
                    node_id="ANCHOR_S0",
                    family_id="ANCHOR_S0",
                    commit_hash=s0_commit,
                    frozen_score=s0_score,
                    live_score=float(s0_eval_receipt["scores"]["live_challenge"]),
                    wall_time_sec=float(s0_eval_receipt["resource_profile"]["wall_time_sec"]),
                    summary="Phase 0 开局蒸馏实跑固化的零号强基线 s_0",
                    higher_is_better=state.get("higher_is_better", True),
                )
            force_cleanup_directory(s0_island, self.sandbox.graveyard_dir)

        # 初始化各正交方法族的谱系追踪 (Lineage BeliefState)
        lineages = state.setdefault("lineages", {})
        for fam in orthogonal_families:
            fid = fam.get("family_id", "FAM-01")
            lin_id = f"LIN-{fid}"
            lineages[lin_id] = {
                "family_id": fid,
                "family_name": fam.get("family_name", fid),
                "lineage_id": lin_id,
                "steps_invested": 0,
                "head_commit": s0_commit,
                "best_score": s0_score,
                "status": "ACTIVE_DEEPENING",
            }

        state["anchor_s0_commit"] = s0_commit
        state["anchor_s0_score"] = s0_score
        self.save_state(state)
        self.archive.rebuild_l0_index()
        self._append_wal("LOCK_DISTILLATION", {"s0_commit": s0_commit, "s0_score": s0_score})

        return {
            "status": "OK",
            "anchor_s0_commit": s0_commit,
            "anchor_s0_score": s0_score,
            "registered_families": [f.get("family_id") for f in orthogonal_families],
            "s0_evaluation": s0_eval_receipt,
        }

    # ========================================================================
    # 3. 并发槽位分配、代码块微创手术、沙箱评测与五件套遗产交卷
    # ========================================================================

    def allocate_exploration_slot(
        self,
        family_id: str,
        targeted_code_block: str,
        hypothesis: str,
        parent_commit: Optional[str] = None,
        step_budget: int = 25,
        is_unbound_junior: bool = False,
    ) -> Dict[str, Any]:
        """
        分配一个无 `.git` 的清洁室孤岛槽位 (`worktrees/slot_xx_node_yy/`)，
        自动检出基底代码快照并注入 `scoped_brief.md` (L1 启动简报)。
        """
        state = self.load_state()
        active_slots: Dict[str, Any] = state.setdefault("active_slots", {})
        max_slots = int(state.get("max_concurrent_slots", 4))
        if len(active_slots) >= max_slots:
            return {
                "status": "SLOTS_FULL",
                "message": f"当前活跃槽位已满 ({len(active_slots)}/{max_slots})，请先完成现有节点的评测与遗产归档！",
                "active_slots": list(active_slots.keys()),
            }

        node_seq = int(state.get("node_counter", 0)) + 1
        state["node_counter"] = node_seq
        node_id = f"NODE-{node_seq:03d}"
        slot_id = f"slot_{len(active_slots) + 1:02d}_{node_id.lower()}"
        lineage_id = "UNBOUND_JUNIOR" if is_unbound_junior else f"LIN-{family_id}"

        lineages = state.setdefault("lineages", {})
        lin_info = lineages.get(lineage_id, {})
        base_commit = parent_commit or lin_info.get("head_commit") or state.get("anchor_s0_commit") or "GENESIS_S0"

        # 生成 L1 启动专属简报
        brief_md = self.archive.build_scoped_l1_brief(
            node_id=node_id,
            slot_id=slot_id,
            family_id="GLOBAL" if is_unbound_junior else family_id,
            lineage_id=lineage_id,
            parent_commit=base_commit,
            targeted_code_block=targeted_code_block,
            hypothesis=hypothesis,
            step_budget=step_budget,
        )

        island_dir = self.sandbox.checkout_clean_island(
            commit_hash=base_commit,
            slot_dir_name=slot_id,
            scoped_brief_md=brief_md,
        )

        slot_record = {
            "slot_id": slot_id,
            "node_id": node_id,
            "family_id": family_id,
            "lineage_id": lineage_id,
            "base_commit": base_commit,
            "targeted_code_block": targeted_code_block,
            "hypothesis": hypothesis,
            "island_path": str(island_dir),
            "step_budget": step_budget,
            "allocated_at": time.time(),
        }
        active_slots[slot_id] = slot_record
        self.save_state(state)
        self._append_wal("ALLOCATE_SLOT", slot_record)

        return {
            "status": "OK",
            "slot_id": slot_id,
            "node_id": node_id,
            "lineage_id": lineage_id,
            "base_commit": base_commit,
            "island_path": str(island_dir),
            "scoped_brief_path": str(island_dir / "scoped_brief.md"),
        }

    def surgical_replace_in_slot(
        self,
        slot_id: str,
        target_block_name: str,
        new_block_code: str,
        rel_script_path: str = "src/main.py",
    ) -> Dict[str, Any]:
        """在指定槽位的清洁室孤岛内执行 MLE-STAR 式局部代码块微创热插拔替换"""
        state = self.load_state()
        slot_info = state.get("active_slots", {}).get(slot_id)
        if not slot_info:
            return {"status": "ERROR", "message": f"找不到活跃槽位: {slot_id}"}

        island_dir = Path(slot_info["island_path"])
        jail = SandboxPathJail(island_dir, self.sandbox.shared_readonly_dir, slot_info.get("lineage_id", "GLOBAL"))
        safe_script_path = jail.validate_write(rel_script_path)

        ok, msg = self.sandbox.surgical_replace_block(safe_script_path, target_block_name, new_block_code)
        return {
            "status": "OK" if ok else "ERROR",
            "slot_id": slot_id,
            "target_block_name": target_block_name,
            "script_path": str(safe_script_path),
            "message": msg,
        }

    def evaluate_slot(
        self,
        slot_id: str,
        entry_script: str = "src/main.py",
        claimed_swept_variables: Optional[List[str]] = None,
        operator_description: str = "",
        timeout_sec: float = 120.0,
    ) -> Dict[str, Any]:
        """
        对指定槽位的代码生成快照并执行跨进程防作弊评测，签发带 HMAC 签名的 `legacy_out/metrics_receipt.json`
        """
        state = self.load_state()
        slot_info = state.get("active_slots", {}).get(slot_id)
        if not slot_info:
            return {"status": "ERROR", "message": f"找不到活跃槽位: {slot_id}"}

        island_dir = Path(slot_info["island_path"])
        base_commit = slot_info.get("base_commit", "GENESIS")
        parent_snap_file = self.sandbox.snapshots_dir / base_commit / "files" / entry_script
        parent_code = parent_snap_file.read_text(encoding="utf-8") if parent_snap_file.exists() else ""

        commit_hash = self.sandbox.store_snapshot(
            island_dir, parent_commit=base_commit, message=f"Eval {slot_info['node_id']}: {slot_info.get('hypothesis', '')}"
        )
        slot_info["latest_commit"] = commit_hash
        self.save_state(state)

        receipt = self.evaluator.evaluate_island(
            island_dir=island_dir,
            node_id=slot_info["node_id"],
            commit_hash=commit_hash,
            entry_script=entry_script,
            parent_code=parent_code,
            anchor_s0_score=float(state.get("anchor_s0_score", 0.0)),
            higher_is_better=bool(state.get("higher_is_better", True)),
            timeout_sec=timeout_sec,
            claimed_swept_variables=claimed_swept_variables,
            operator_description=operator_description,
        )
        self._append_wal("EVALUATE_SLOT", {"slot_id": slot_id, "commit_hash": commit_hash, "triage": receipt.get("triage_tier")})
        return receipt

    def submit_legacy_and_release_slot(
        self,
        slot_id: str,
        steps_consumed: int = 15,
    ) -> Dict[str, Any]:
        """
        验收探索节点留下的【五件套遗产包】，校验 HMAC 成绩单签名，
        更新档案馆与谱系步数计数（若满 60 步自动触发原位 3 轮内省室信号），并调用五步墓碑算法回收孤岛目录。
        """
        state = self.load_state()
        active_slots = state.get("active_slots", {})
        slot_info = active_slots.get(slot_id)
        if not slot_info:
            return {"status": "ERROR", "message": f"找不到活跃槽位: {slot_id}"}

        island_dir = Path(slot_info["island_path"])
        node_id = slot_info["node_id"]
        family_id = slot_info["family_id"]
        lineage_id = slot_info["lineage_id"]
        commit_hash = slot_info.get("latest_commit") or self.sandbox.store_snapshot(island_dir, slot_info["base_commit"], f"Final {node_id}")

        # 1. 校验五件套遗产包并入库
        val_res = self.archive.validate_and_admit_legacy(
            island_dir=island_dir,
            node_id=node_id,
            family_id=family_id,
            lineage_id=lineage_id,
            commit_hash=commit_hash,
        )
        if not val_res.ok:
            return {
                "status": "LEGACY_REJECTED",
                "slot_id": slot_id,
                "errors": val_res.errors,
                "warnings": val_res.warnings,
                "message": "五件套遗产包校验未通过，槽位拒绝释放！请按 errors 列表补齐文件后重新提交。",
            }

        # 2. 校验成绩单 HMAC 签名并更新排行榜
        receipt_path = island_dir / "legacy_out" / "metrics_receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not self.evaluator.verify_receipt_signature(receipt):
            return {
                "status": "FORGED_RECEIPT_DETECTED",
                "slot_id": slot_id,
                "message": "安全警报：metrics_receipt.json 的 HMAC-SHA256 签名验证失败，严禁手工伪造成绩单！",
            }

        frozen_score = float(receipt["scores"]["frozen_benchmark"])
        live_score = float(receipt["scores"]["live_challenge"])
        triage_tier = receipt.get("triage_tier", "DEAD_END_ARCHIVE")

        rank = self.archive.update_leaderboard(
            node_id=node_id,
            family_id=family_id,
            commit_hash=commit_hash,
            frozen_score=frozen_score,
            live_score=live_score,
            wall_time_sec=float(receipt["resource_profile"]["wall_time_sec"]),
            summary=slot_info.get("hypothesis", ""),
            higher_is_better=bool(state.get("higher_is_better", True)),
        )

        # 3. 读取遗嘱提案排入调度器队列
        will_path = island_dir / "legacy_out" / "last_will_proposals.json"
        will_data = json.loads(will_path.read_text(encoding="utf-8"))
        proposals = will_data if isinstance(will_data, list) else will_data.get("proposals", [])
        pending_queue: List[Dict[str, Any]] = state.setdefault("pending_proposals", [])
        for p in proposals:
            p["from_node_id"] = node_id
            p["family_id"] = family_id
            p["parent_commit"] = commit_hash
            pending_queue.append(p)
        pending_queue.sort(key=lambda x: float(x.get("priority_score", 0.5)), reverse=True)

        # 4. 更新谱系步数与最优解指针，检查是否触发 60 步原位内省室 (Station Reflection Chamber)
        state["total_steps_executed"] = int(state.get("total_steps_executed", 0)) + steps_consumed
        lineages = state.setdefault("lineages", {})
        lin_state = lineages.setdefault(
            lineage_id,
            {"family_id": family_id, "lineage_id": lineage_id, "steps_invested": 0, "head_commit": commit_hash, "best_score": frozen_score},
        )
        lin_state["steps_invested"] = int(lin_state.get("steps_invested", 0)) + steps_consumed
        if triage_tier == "PARETO_PROMOTE":
            lin_state["head_commit"] = commit_hash
            lin_state["best_score"] = frozen_score
            # 突破自动续期激励 (+25 步)
            lin_state["bonus_lease_steps"] = int(lin_state.get("bonus_lease_steps", 0)) + 25

        needs_reflection_chamber = (lin_state["steps_invested"] >= 60 and lin_state.get("last_reflected_step", 0) + 60 <= lin_state["steps_invested"])

        # 5. 五步墓碑算法安全回收孤岛目录
        force_cleanup_directory(island_dir, self.sandbox.graveyard_dir)
        active_slots.pop(slot_id, None)
        self.save_state(state)
        self.archive.rebuild_l0_index()
        self._append_wal("RELEASE_SLOT", {"slot_id": slot_id, "node_id": node_id, "triage": triage_tier, "rank": rank})

        return {
            "status": "OK",
            "node_id": node_id,
            "commit_hash": commit_hash,
            "triage_tier": triage_tier,
            "leaderboard_rank": rank,
            "admitted_primitives": val_res.admitted_primitives,
            "admitted_record_id": val_res.admitted_record_id,
            "lineage_steps_invested": lin_state["steps_invested"],
            "trigger_60_step_reflection_chamber": needs_reflection_chamber,
            "reflection_prompt_hint": (
                "该谱系已累积满 60 步！请立即开启 Station 原位 3 轮内省室（调用高阶大脑模型按九大拷问题库审视路线）！"
                if needs_reflection_chamber
                else ""
            ),
        }

    # ========================================================================
    # 4. 终局统稿、防吹牛核对与标准五件套交付信封编译 (Final Delivery Envelope)
    # ========================================================================

    def compile_final_delivery(self, executive_summary_md: str = "") -> Dict[str, Any]:
        """
        编译 `final_delivery/` 标准五件套终局交付目录，并执行三大防吹牛门禁检查：
        1. 实验对比表格全部从带 HMAC 签名的 `leaderboard.json` 与 `claims.jsonl` 硬绑定渲染（严禁手敲捏造数字）；
        2. 扫描并拦截 `TODO` / `TBD` / `Conclusions Here` / `Insert Figure` 等模板占位符残留；
        3. 完整打包：
           - `01_executive_report.md`
           - `02_verified_source_code/` (最优 Commit 源码 + 全套已验证原语 `primitives/`)
           - `03_claim_evidence_ledger.json`
           - `04_reproduce_all.ps1`
           - `05_boundary_and_dead_ends_report.md`
        """
        # 1. 占位符残留拦截
        forbidden_placeholders = [
            r"\bTODO\b", r"\bTBD\b", r"Conclusions Here", r"Insert Figure", r"\[PLACEHOLDER\]"
        ]
        found_placeholders = [
            pat for pat in forbidden_placeholders if re.search(pat, executive_summary_md, re.IGNORECASE)
        ]
        if found_placeholders:
            return {
                "status": "DELIVERY_BLOCKED_PLACEHOLDERS",
                "found_placeholders": found_placeholders,
                "message": "终局审计拦截：报告正文中存在未完成的模板占位符，请清理后重新生成！",
            }

        delivery_dir = self.workspace_root / "final_delivery"
        if delivery_dir.exists():
            force_cleanup_directory(delivery_dir, self.sandbox.graveyard_dir)
        delivery_dir.mkdir(parents=True, exist_ok=True)

        state = self.load_state()
        lb_data = json.loads(self.archive.leaderboard_file.read_text(encoding="utf-8"))
        entries = lb_data.get("entries", [])
        records = self.archive._read_jsonl(self.archive.records_file)
        claims = self.archive._read_jsonl(self.archive.claims_file)

        # 2. 硬绑定生成实验得分对比表 (100% 源自签名收据)
        table_lines = [
            "## 📊 独立沙箱实测性能演进总表（由内核从 HMAC 签名收据硬绑定生成）\n",
            "| 排名 | 节点编号 | 方法族 (Family) | 快照 Commit | Frozen 基准得分 | Live 挑战得分 | 运行耗时 (s) | 核心改进摘要 |",
            "| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :--- |",
        ]
        for idx, item in enumerate(entries[:10], 1):
            table_lines.append(
                f"| {idx} | `{item['node_id']}` | `{item['family_id']}` | `{item['commit_hash'][:8]}` | "
                f"**{item['frozen_score']:.6f}** | {item['live_score']:.6f} | {item['wall_time_sec']:.2f} | {item['summary']} |"
            )

        report_content = (
            f"# 长城 Agent V4.2 终局技术报告 (`{state.get('task_id', 'CAMPAIGN')}`)\n\n"
            f"{executive_summary_md.strip()}\n\n---\n\n"
            + "\n".join(table_lines)
            + "\n"
        )
        (delivery_dir / "01_executive_report.md").write_text(report_content, encoding="utf-8")

        # 3. 导出冠军源码与已验证原语库到 02_verified_source_code/
        code_out_dir = delivery_dir / "02_verified_source_code"
        code_out_dir.mkdir(parents=True, exist_ok=True)
        best_commit = entries[0]["commit_hash"] if entries else state.get("anchor_s0_commit", "")
        best_snap_files = self.sandbox.snapshots_dir / best_commit / "files"
        if best_snap_files.exists():
            shutil.copytree(best_snap_files, code_out_dir, dirs_exist_ok=True)
        if self.archive.primitives_dir.exists():
            shutil.copytree(self.archive.primitives_dir, code_out_dir / "primitives", dirs_exist_ok=True)

        # 4. 生成 03_claim_evidence_ledger.json
        ledger_bundle = {
            "task_id": state.get("task_id"),
            "anchor_s0_score": state.get("anchor_s0_score"),
            "best_champion": entries[0] if entries else None,
            "verified_claims": claims,
            "verified_primitives": [p.name for p in self.archive.primitives_dir.glob("*.py") if p.name != "__init__.py"],
            "leaderboard_top10": entries[:10],
        }
        (delivery_dir / "03_claim_evidence_ledger.json").write_text(
            json.dumps(ledger_bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 5. 生成 04_reproduce_all.ps1 (PowerShell 7 一键复现脚本)
        repro_ps1 = (
            "#!/usr/bin/env pwsh\n"
            "# Great Wall Agent V4.2 One-Click Clean-Room Reproduction Script\n"
            "$ErrorActionPreference = 'Stop'\n"
            "$env:PYTHONUTF8 = '1'\n"
            "$env:PYTHONHASHSEED = '42'\n"
            "$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
            "$env:PYTHONPATH = \"$ScriptDir/02_verified_source_code;$ScriptDir/../shared_readonly\"\n"
            "Write-Host '🚀 正在清洁室环境中复现最优冠军解...' -ForegroundColor Cyan\n"
            "python \"$ScriptDir/02_verified_source_code/src/main.py\"\n"
            "Write-Host '✅ 复现执行完成！' -ForegroundColor Green\n"
        )
        (delivery_dir / "04_reproduce_all.ps1").write_text(repro_ps1, encoding="utf-8")

        # 6. 生成 05_boundary_and_dead_ends_report.md
        dead_lines = [
            "# 🚧 算法适用边界与死胡同避坑档案 (Boundary & Dead-Ends Report)\n",
            "## 一、已证伪的死胡同与负面实验记录 (`record_blacklist`)\n",
        ]
        if not records:
            dead_lines.append("*(无死胡同记录)*")
        else:
            for r in records:
                dead_lines.append(
                    f"- **`[{r.get('record_id')}]`** (节点 `{r.get('node_id')}`, 方法族 `{r.get('family_id')}`) — "
                    f"尝试机制: `{r.get('tried_mechanism')}` -> **失败原因**: {r.get('failure_summary')}"
                )
        (delivery_dir / "05_boundary_and_dead_ends_report.md").write_text("\n".join(dead_lines) + "\n", encoding="utf-8")

        self._append_wal("COMPILE_FINAL_DELIVERY", {"delivery_dir": str(delivery_dir), "best_commit": best_commit})
        return {
            "status": "OK",
            "delivery_dir": str(delivery_dir),
            "files_generated": [
                "01_executive_report.md",
                "02_verified_source_code/",
                "03_claim_evidence_ledger.json",
                "04_reproduce_all.ps1",
                "05_boundary_and_dead_ends_report.md",
            ],
            "best_champion": entries[0] if entries else None,
        }
