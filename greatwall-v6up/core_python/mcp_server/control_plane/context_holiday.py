"""宿主 52% 夜科学绿洲的持久时钟与逐轮核销。"""

from __future__ import annotations

import json
import random
import sqlite3

from ..db_schema import ERR_INVALID_INPUT, ERR_LOCKED, ERR_NOT_FOUND, FailClosedError, rw_immediate_tx, utc_now_iso
from ..mcp_core_helpers import load_holiday_prompts


def begin_context_holiday(conn: sqlite3.Connection, node_id: str, threshold: float) -> dict:
    if type(threshold) not in (float, int) or not 0.42 <= threshold <= 0.62:
        raise FailClosedError(ERR_INVALID_INPUT, "夜科学阈值须在 0.42–0.62")
    prompts = {p["id"]: p["text"] for p in load_holiday_prompts() if p["scope"] == "holiday_52"}
    with rw_immediate_tx(conn):
        node = conn.execute("SELECT * FROM lineage_nodes WHERE node_id = ?", (node_id,)).fetchone()
        if node is None:
            raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
        if node["holiday_completed"]:
            return {"holiday_completed": True}
        if (
            not node["first_reflection_unlocked"]
            or node["pressure_tokens"] / node["effective_context_window"] < threshold
            or node["node_status"] not in ("EXPLORING", "ACTIVE_REVISING")
        ):
            raise FailClosedError(
                ERR_LOCKED,
                f"节点尚未达到夜科学入口条件：水位 {node['pressure_tokens']}/{node['effective_context_window']}，"
                f"要求 {threshold:.0%}，元反思解锁={node['first_reflection_unlocked']}，状态={node['node_status']}",
            )
        prompt_id = node["holiday_prompt_id"]
        if prompt_id is None:
            # 优先避开本脉历史已用卡片后再完全随机抽卡；若本脉已抽遍则重置全池随机
            used_ids = {
                row["holiday_prompt_id"]
                for row in conn.execute(
                    "SELECT DISTINCT holiday_prompt_id FROM lineage_nodes WHERE branch_id = ? AND holiday_prompt_id IS NOT NULL",
                    (node["branch_id"],),
                ).fetchall()
            }
            candidates = [pid for pid in prompts if pid not in used_ids] or list(prompts)
            prompt_id = random.choice(candidates)
            conn.execute(
                "UPDATE lineage_nodes SET holiday_prompt_id = ?, updated_at = ? WHERE node_id = ?",
                (prompt_id, utc_now_iso(), node_id),
            )
        turns = json.loads(node["holiday_bet_json"]).get("turns_completed", 0)
    return {"holiday_completed": False, "holiday_prompt_id": prompt_id, "prompt": prompts[prompt_id], "turns_completed": turns}


def advance_context_holiday(conn: sqlite3.Connection, node_id: str, completed_turn: int) -> dict:
    if type(completed_turn) is not int or completed_turn not in (1, 2):
        raise FailClosedError(ERR_INVALID_INPUT, "夜科学只记录第 1 或第 2 回合")
    with rw_immediate_tx(conn):
        node = conn.execute(
            "SELECT holiday_prompt_id, holiday_completed, holiday_bet_json FROM lineage_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if node is None:
            raise FailClosedError(ERR_NOT_FOUND, f"节点 {node_id!r} 不存在")
        if node["holiday_prompt_id"] is None:
            raise FailClosedError(ERR_LOCKED, "夜科学尚未开启")
        if node["holiday_completed"]:
            return {"holiday_completed": True}
        prior = json.loads(node["holiday_bet_json"]).get("turns_completed", 0)
        if completed_turn > prior + 1:
            raise FailClosedError(ERR_INVALID_INPUT, "夜科学回合必须按顺序核销")
        complete = completed_turn == 2
        data = {"turns_completed": max(prior, completed_turn)}
        if complete:
            data["outcome"] = "SKIPPED_TIMEOUT"
        conn.execute(
            "UPDATE lineage_nodes SET holiday_completed = ?, holiday_bet_json = ?, updated_at = ? WHERE node_id = ?",
            (int(complete), json.dumps(data), utc_now_iso(), node_id),
        )
    return {"holiday_completed": complete, **data}
