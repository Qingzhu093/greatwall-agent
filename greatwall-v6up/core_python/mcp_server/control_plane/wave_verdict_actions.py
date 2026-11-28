"""圆桌决议的三阶段动作、锁外工件准备与双模收敛。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import uuid
from typing import Any, Iterator

from ..db.enums import ALLOWED_CONVERGENCE_MODES
from ..db_schema import ERR_INVALID_INPUT, ERR_LOCKED, ERR_NOT_FOUND, FailClosedError
from ..mcp_core_helpers import load_runtime_config, next_prefixed_id
from .blind_sandbox import _rmtree_force, _set_tree_readonly
from .effects_outbox import cancel_stale_effects_for_target
from .lifecycle_ops import submit_works_ticket
from .operator_policy import check_question_branch_quota, epoch_id
from .subproblem_locks import evaluate_subproblem_locks, get_subproblem_active_spec_revision, set_subproblem_state
from .workspace_sync import (
    restore_retained_candidate_snapshot, sync_approved_public_inputs, sync_public_instruments_and_skills_to_worktree,
)


_PHASES = (
    ("HIBERNATE",),
    ("SPAWN_SYNTHESIS", "OPEN_NEW_BRANCH", "PROTECT"),
    ("DISCRIMINATOR", "PAUSE_FOR_HUMAN", "CONVERGE_SUBPROBLEM"),
)
_PHASE_BY_ACTION = {action: phase for phase, actions in enumerate(_PHASES) for action in actions}
_REQUIRED_TEXT = {
    "HIBERNATE": ("target_node_id", "reason_md"),
    "SPAWN_SYNTHESIS": ("primary_node_id", "secondary_node_id", "target_family_id", "synthesis_goal_md"),
    "OPEN_NEW_BRANCH": ("mechanism_signature",),
    "PROTECT": ("source_node_id",),
    "DISCRIMINATOR": ("instrument_id", "probe_requirement_md"),
    "PAUSE_FOR_HUMAN": (),
    "CONVERGE_SUBPROBLEM": ("convergence_mode", "rationale_md"),
}


def _validate_wave_requires(requires: Any) -> list[str]:
    if requires is None:
        return []
    if not isinstance(requires, list):
        raise FailClosedError(ERR_INVALID_INPUT, "requires 必须为前置 ID 字符串数组")
    out: list[str] = []
    for raw in requires:
        req = str(raw or "").strip()
        if not req:
            continue
        if req.startswith("L3-") or (req.startswith("OBS:") and req.endswith(":PASS") and len(req) > len("OBS::PASS")):
            if req not in out:
                out.append(req)
        else:
            raise FailClosedError(
                ERR_INVALID_INPUT,
                f"非法 requires 条目 {req!r}：仅支持 'L3-###' 或 'OBS:<instrument_id>:PASS'",
            )
    return out


def validate_wave_actions(actions: list[dict[str, Any]]) -> None:
    if not isinstance(actions, list):
        raise FailClosedError(ERR_INVALID_INPUT, "圆桌裁决 actions 必须为动作数组")
    for action in actions:
        if not isinstance(action, dict) or action.get("action_type") not in _PHASE_BY_ACTION:
            raise FailClosedError(ERR_INVALID_INPUT, "圆桌动作必须提供合法 action_type")
        kind = action["action_type"]
        for key in _REQUIRED_TEXT[kind]:
            value = action.get(key)
            if not isinstance(value, str) or not value.strip():
                raise FailClosedError(ERR_INVALID_INPUT, f"{kind} 必须填写非空 {key}")
        if kind in _PHASES[1] and "requires" in action:
            _validate_wave_requires(action.get("requires"))
        if kind == "CONVERGE_SUBPROBLEM":
            if action["convergence_mode"] not in ALLOWED_CONVERGENCE_MODES:
                raise FailClosedError(ERR_INVALID_INPUT, f"非法 convergence_mode {action['convergence_mode']!r}")
            ids = action.get("composite_entry_ids", [])
            if not isinstance(ids, list) or any(not isinstance(e, str) for e in ids):
                raise FailClosedError(ERR_INVALID_INPUT, "composite_entry_ids 必须为馆藏编号数组")
            if action["convergence_mode"] == "CONVERGE_FULL_COMPOSITE" and (len(ids) < 2 or len(set(ids)) != len(ids)):
                raise FailClosedError(ERR_INVALID_INPUT, "组合完备核验须点名至少两篇不同的 L3")
    if sum(item["action_type"] == "CONVERGE_SUBPROBLEM" for item in actions) > 1:
        raise FailClosedError(ERR_INVALID_INPUT, "每场圆桌只能选择一种子题收敛模式")


def _node(conn: sqlite3.Connection, question_id: str, node_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ? AND question_id = ?", (node_id, question_id)).fetchone()
    if row is None:
        raise FailClosedError(ERR_NOT_FOUND, f"子题 {question_id} 无节点 {node_id!r}")
    return row


def _donor_manifest(
    conf: sqlite3.Row, primary: sqlite3.Row, secondary: sqlite3.Row,
    worktree: Path, synthesis_goal_md: str,
) -> str:
    secondary_id = secondary["node_id"]
    destination = worktree / ".greatwall_donors" / secondary_id
    frozen = secondary["retained_snapshot_abs_path"]
    source = Path(frozen if frozen else secondary["worktree_abs_path"])
    shutil.copytree(
        source, destination,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "inputs", ".greatwall_donors"),
    )
    paths = [p.relative_to(destination).as_posix() for p in sorted(destination.rglob("*")) if p.is_file()]
    participants = {primary["node_id"], secondary_id}
    replies = [
        f"- [R{item['round']}] {item['node_id']} → {', '.join(item['target_node_ids'])}\n  {item['statement_md']}"
        for item in json.loads(conf["critiques_ledger_json"])
        if item["round"] >= 2 and item["node_id"] in participants and participants.intersection(item["target_node_ids"])
    ]
    lines = ["# 双供体嫁接清单", "", "## 圆桌融合目标", synthesis_goal_md]
    for role, donor in (("主供体", primary), ("副供体", secondary)):
        observations = ", ".join(json.loads(donor["bound_obs_ids_json"]))
        lines.extend(["", f"## {role} {donor['node_id']}", donor["mechanism_summary"], f"绑定观测 {observations}"])
    lines.extend(["", "## 点对点排雷记录", *replies, "", "## 副供体文件", *(f"- `{p}`" for p in paths)])
    (destination / "DONOR_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _set_tree_readonly(destination, True)
    return destination.relative_to(worktree).as_posix()


@dataclass(frozen=True)
class PreparedBranch:
    node_id: str
    branch_id: str
    worktree: Path
    spec_revision: int
    family_id: str
    primary: sqlite3.Row | None
    donor_mount: str | None


@contextmanager
def prepare_wave_growth(
    conn: sqlite3.Connection, workspace_root: str, conference_id: str | None,
) -> Iterator[dict[int, PreparedBranch]]:
    prepared: dict[int, PreparedBranch] = {}
    worktrees: list[Path] = []
    try:
        if conference_id is not None:
            conf = conn.execute("SELECT * FROM wave_conferences WHERE conference_id = ?", (conference_id,)).fetchone()
            if conf is None:
                raise FailClosedError(ERR_NOT_FOUND, f"圆桌会议 {conference_id!r} 不存在")
            actions = json.loads(conf["verdict_json"])["actions"]
            validate_wave_actions(actions)
            qid = conf["question_id"]
            spec_revision = get_subproblem_active_spec_revision(conn, qid)
            contract = conn.execute("SELECT shared_inputs_json FROM parse0_contract WHERE contract_id = 'active'").fetchone()
            for idx, action in enumerate(actions):
                kind = action["action_type"]
                if kind not in _PHASES[1]:
                    continue
                primary = None
                if kind == "SPAWN_SYNTHESIS":
                    primary = _node(conn, qid, action["primary_node_id"])
                    secondary = _node(conn, qid, action["secondary_node_id"])
                    if primary["branch_id"] == secondary["branch_id"] or primary["family_id"] == secondary["family_id"]:
                        raise FailClosedError(ERR_INVALID_INPUT, "SPAWN_SYNTHESIS 的双供体须来自不同分支与学派")
                    family_id = action["target_family_id"]
                elif kind == "PROTECT":
                    primary = _node(conn, qid, action["source_node_id"])
                    family_id = primary["family_id"]
                else:
                    family_id = action.get("family_id", f"fam_{qid.lower()}_{uuid.uuid4().hex[:6]}")
                branch_id = f"b_{qid.lower()}_{uuid.uuid4().hex[:10]}"
                node_id = f"node_{qid.lower()}_{uuid.uuid4().hex[:10]}"
                worktree = Path(workspace_root).resolve() / "worktrees" / branch_id
                worktree.mkdir(parents=True)
                worktrees.append(worktree)
                if primary is not None and primary["retained_snapshot_abs_path"]:
                    restore_retained_candidate_snapshot(primary["retained_snapshot_abs_path"], str(worktree))
                mount = _donor_manifest(conf, primary, secondary, worktree, action["synthesis_goal_md"]) if kind == "SPAWN_SYNTHESIS" else None
                sync_approved_public_inputs(
                    workspace_root, worktree, json.loads(contract["shared_inputs_json"]),
                    spec_revision=spec_revision, question_id=qid,
                )
                sync_public_instruments_and_skills_to_worktree(conn, workspace_root, worktree)
                prepared[idx] = PreparedBranch(node_id, branch_id, worktree, spec_revision, family_id, primary, mount)
        yield prepared
    finally:
        for path in worktrees:
            if conn.execute("SELECT 1 FROM lineage_nodes WHERE worktree_abs_path = ?", (str(path),)).fetchone() is None:
                _rmtree_force(path)


def enqueue_salvage_review(conn: sqlite3.Connection, node: sqlite3.Row, now: str) -> str | None:
    if not node["column_a_facts_md"] or conn.execute(
        "SELECT 1 FROM review_queue WHERE source_node_id = ?", (node["node_id"],),
    ).fetchone() is not None:
        return None
    review_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
    conn.execute(
        """
        INSERT INTO review_queue(review_id, question_id, source_node_id, source_type, proposer_session_id,
            non_blocking, manuscript_title, spec_revision, column_a_snapshot_md, bound_obs_ids_json,
            artifact_rel_path, artifact_snapshot_abs_path, created_at, updated_at)
        VALUES (?, ?, ?, 'AUDITOR_SALVAGED_LEMMA', ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (review_id, node["question_id"], node["node_id"], node["companion_session_id"], node["mechanism_summary"],
         node["spec_revision"], node["column_a_facts_md"], node["bound_obs_ids_json"], node["candidate_rel_path"],
         node["retained_snapshot_abs_path"], now, now),
    )
    return review_id


def _hibernate(conn: sqlite3.Connection, conf: sqlite3.Row, action: dict, now: str) -> dict:
    target = _node(conn, conf["question_id"], action["target_node_id"])
    node = conn.execute(
        """
        SELECT * FROM lineage_nodes WHERE question_id = ? AND branch_id = ?
          AND node_status IN ('EXPLORING','ACTIVE_REVISING','AWAITING_TRIAGE')
        ORDER BY generation DESC LIMIT 1
        """,
        (conf["question_id"], target["branch_id"]),
    ).fetchone()
    if node is None:
        raise FailClosedError(ERR_LOCKED, "该分支没有可休眠的活跃节点")
    if node["protection_generations_left"] > 0:
        raise FailClosedError(ERR_LOCKED, "目标分支仍在成长保护期")
    if conn.execute(
        """
        SELECT 1 FROM internal_research_ledger
        WHERE author_branch_id = ? AND ledger_type = 'L3_VERIFIED' AND is_active = 1
          AND publish_tier != 'MARGINAL_NOTE' AND created_at >= ?
        """,
        (node["branch_id"], conf["created_at"]),
    ).fetchone() is not None:
        raise FailClosedError(ERR_LOCKED, "目标分支在开会后已有新的核心成果")
    salvage = action.get("salvage_audit", False)
    live = conn.execute("SELECT 1 FROM operator_runtime_slots WHERE node_id = ?", (node["node_id"],)).fetchone()
    state = "DRAIN_AFTER_TURN" if live else "HIBERNATED"
    reason = "HIBERNATED_BY_WAVE_CONFERENCE:SALVAGE" if salvage else "HIBERNATED_BY_WAVE_CONFERENCE"
    generation = node["control_generation"] + 1
    conn.execute(
        """
        UPDATE lineage_nodes SET control_state = ?, control_generation = ?, pending_handoff_reason = ?, updated_at = ?
        WHERE node_id = ?
        """,
        (state, generation, reason, now, node["node_id"]),
    )
    cancel_stale_effects_for_target(
        conn, target_type="NODE", target_id=node["node_id"], below_generation=generation,
        kinds=("SPAWN_PAIR", "DRAIN_AND_STOP_NODE", "CANCEL_NODE_SESSION"),
    )
    review_id = enqueue_salvage_review(conn, target, now) if salvage else None
    return {"branch_id": node["branch_id"], "node_id": node["node_id"], "salvage_review_id": review_id}


def _grow(
    conn: sqlite3.Connection, conf: sqlite3.Row, action: dict, branch: PreparedBranch,
    released: set[str], remaining_synthesis_budget: int, now: str,
) -> dict:
    kind, qid = action["action_type"], conf["question_id"]
    if branch.spec_revision != get_subproblem_active_spec_revision(conn, qid):
        raise FailClosedError(ERR_LOCKED, "工件准备期间子题口径已变化")
    check_question_branch_quota(conn, qid, family_id=branch.family_id, released_branch_ids=released)
    budget = None
    if kind == "SPAWN_SYNTHESIS":
        # 双供体跨学派嫁接，只占总槽位与本波合体预算。
        budget = action.get("budget_nodes", remaining_synthesis_budget)
        if type(budget) is not int or not 1 <= budget <= remaining_synthesis_budget:
            raise FailClosedError(ERR_LOCKED, "本波合体节点预算不足")
    else:
        from .scheduler_rules import compute_family_concentration_alerts

        if any(a["question_id"] == qid and a["family_id"] == branch.family_id for a in compute_family_concentration_alerts(conn)):
            raise FailClosedError(ERR_LOCKED, "目标学派触发单学派占比护栏")
    primary = branch.primary
    if kind == "OPEN_NEW_BRANCH":
        signature = action["mechanism_signature"]
        goal = action.get("gap_directive_md", signature)
    elif kind == "PROTECT":
        signature = primary["mechanism_summary"]
        goal = action.get("rationale_md", signature)
    else:
        goal = action["synthesis_goal_md"]
        signature = str(action.get("mechanism_summary") or goal).strip()[:95]
    if len(signature) >= 100:
        raise FailClosedError(ERR_INVALID_INPUT, f"mechanism_summary 当前 {len(signature)} 字，上限 99 字，请精简后重交")
    if kind == "OPEN_NEW_BRANCH":
        conn.execute(
            """
            INSERT OR IGNORE INTO method_families(family_id, question_id, mechanism_signature,
                orthogonal_contrast, family_status, created_at) VALUES (?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (branch.family_id, qid, signature, action.get("orthogonal_contrast", ""), now),
        )
    elif conn.execute("SELECT 1 FROM method_families WHERE question_id = ? AND family_id = ?", (qid, branch.family_id)).fetchone() is None:
        raise FailClosedError(ERR_INVALID_INPUT, f"学派 {branch.family_id!r} 尚未登记")
    secondary = action.get("secondary_node_id")
    clean_reqs = _validate_wave_requires(action.get("requires"))
    cfg = load_runtime_config()
    default_prot = int(cfg.get("branch_growth_protection_generations", cfg.get("default_protection_generations", 1)))
    conn.execute(
        """
        INSERT INTO lineage_nodes(node_id, question_id, branch_id, family_id, parent_node_id, generation,
            branch_kind, protection_generations_left, branch_budget_nodes_left, companion_session_id,
            secondary_donor_node_id, node_status, worktree_abs_path, retained_snapshot_abs_path,
            mechanism_summary, requires_json, will_md, spec_revision, session_epoch_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'EXPLORING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (branch.node_id, qid, branch.branch_id, branch.family_id, primary["node_id"] if primary else None,
         {"OPEN_NEW_BRANCH": "PURE", "PROTECT": "PROTECTED", "SPAWN_SYNTHESIS": "SYNTHESIS"}[kind],
         default_prot, budget, f"gw-comp-{branch.node_id}", secondary, str(branch.worktree),
         primary["retained_snapshot_abs_path"] if primary else None, signature,
         json.dumps(clean_reqs, ensure_ascii=False), goal, branch.spec_revision,
         epoch_id(conn), now, now),
    )
    data = {
        "branch_id": branch.branch_id, "node_id": branch.node_id, "family_id": branch.family_id,
        "worktree_abs_path": str(branch.worktree), "protection_generations_left": default_prot,
        "requires": clean_reqs,
    }
    if kind == "SPAWN_SYNTHESIS":
        data.update(synthesis_goal_md=goal, donor_mount_rel=branch.donor_mount, budget_nodes=budget)
    return data


def _converge(conn: sqlite3.Connection, conf: sqlite3.Row, action: dict, now: str) -> dict:
    qid = conf["question_id"]
    mode = action["convergence_mode"]
    if mode == "CONVERGE_SATURATED":
        open_gap = conn.execute(
            "SELECT 1 FROM open_lemma_gaps WHERE question_id = ? AND status = 'OPEN' AND gap_tier = 'LOAD_BEARING'",
            (qid,),
        ).fetchone()
        if open_gap is not None:
            raise FailClosedError(ERR_LOCKED, "仍存在未解决的承重缺口")
        res = evaluate_subproblem_locks(
            conn, question_id=qid, semantic_saturation_requested=True, saturation_reason_md=action["rationale_md"],
        )["evaluated"][0]
        if res["dispatch_state"] != "PAUSED_SATURATED":
            raise FailClosedError(ERR_LOCKED, "尚未满足最低投入窗或子题当前不可饱和收敛")
        data = {"dispatch_state": "PAUSED_SATURATED"}
    else:
        entry_ids = action["composite_entry_ids"]
        ids_json = json.dumps(entry_ids)
        active_rev = get_subproblem_active_spec_revision(conn, qid)
        rows = conn.execute(
            """
            SELECT entry_id, bound_obs_ids_json FROM internal_research_ledger WHERE question_id = ?
              AND entry_id IN (SELECT value FROM json_each(?)) AND ledger_type = 'L3_VERIFIED'
              AND is_active = 1 AND verified_spec_revision >= ? AND rigor_score >= 7 AND publish_tier != 'MARGINAL_NOTE'
            """,
            (qid, ids_json, active_rev),
        ).fetchall()
        if len(rows) != len(entry_ids):
            raise FailClosedError(ERR_LOCKED, "组合子篇须为当前口径、有效且严密性至少为 7 的核心 L3")
        obs_ids = sorted({obs for row in rows for obs in json.loads(row["bound_obs_ids_json"])})
        review_id = next_prefixed_id(conn, "review_queue", "review_id", "rev_")
        conn.execute(
            """
            INSERT INTO review_queue(review_id, question_id, source_node_id, source_type, proposer_session_id,
                manuscript_title, spec_revision, column_a_snapshot_md, composite_entry_ids_json,
                declared_citations_json, bound_obs_ids_json, non_blocking, created_at, updated_at)
            VALUES (?, ?, '', 'COMPOSITE_FULL_GOAL', ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (review_id, qid, conf["chair_session_id"], f"{qid} 组合完备核验", active_rev, action["rationale_md"],
             ids_json, ids_json, json.dumps(obs_ids), now, now),
        )
        data = {"review_id": review_id, "composite_entry_ids": entry_ids}
    conn.execute("UPDATE wave_conferences SET convergence_mode = ? WHERE conference_id = ?", (mode, conf["conference_id"]))
    return {"convergence_mode": mode, **data}


def execute_wave_phases(
    conn: sqlite3.Connection, conf: sqlite3.Row, actions: list[dict], prepared: dict[int, PreparedBranch], now: str,
) -> tuple[list[dict], list[dict]]:
    executed: list[dict] = []
    skipped: list[dict] = []
    released: set[str] = set()
    remaining = conf["synthesis_budget_nodes"]
    ordered = sorted(enumerate(actions), key=lambda pair: _PHASE_BY_ACTION[pair[1]["action_type"]])
    for index, action in ordered:
        kind = action["action_type"]
        try:
            if kind == "HIBERNATE":
                result = _hibernate(conn, conf, action, now)
                released.add(result["branch_id"])
            elif kind in _PHASES[1]:
                result = _grow(conn, conf, action, prepared[index], released, remaining, now)
                if kind == "SPAWN_SYNTHESIS":
                    remaining -= result["budget_nodes"]
            elif kind == "DISCRIMINATOR":
                ticket = submit_works_ticket(
                    conn, question_id=conf["question_id"], ticket_type="DISCRIMINATOR",
                    instrument_id=action["instrument_id"], description=action["probe_requirement_md"],
                    source=f"wave_conference:{conf['conference_id']}",
                )
                result = {"ticket_id": ticket["ticket_id"], "description": action["probe_requirement_md"]}
            elif kind == "PAUSE_FOR_HUMAN":
                result = set_subproblem_state(
                    conn, question_id=conf["question_id"], desired_state="PAUSED", actor_source="chief_approved",
                    reason=action.get("rationale_md", json.loads(conf["verdict_json"])["rationale_md"]),
                )
            else:
                result = _converge(conn, conf, action, now)
        except FailClosedError as exc:
            if exc.code != ERR_LOCKED:
                raise
            skipped.append({"action": kind, "reason": exc.message})
        else:
            executed.append({"action": kind, **result})
    return executed, skipped
