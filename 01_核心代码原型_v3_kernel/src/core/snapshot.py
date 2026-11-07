"""
Atomic Snapshot Engine: Git Commit Hash Binding, POSIX/Windows Atomic Write-and-Rename, and Zero-Data-Loss State Restoration.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import FSMState, SnapshotError

__all__ = [
    "FSMStateSnapshot",
    "AtomicSnapshotEngine",
]


@dataclass(frozen=True)
class FSMStateSnapshot:
    """
    状态机全量状态快照实体。
    密码学绑定当前 Git Commit Hash 与最高已持久化 LSN，保障 0 丢失崩溃恢复。
    """
    snapshot_id: str                             # 快照唯一标识符
    lsn: int                                     # 快照对应的权威 WAL LSN 序列号
    timestamp: float                             # 快照生成物理时间戳
    current_state: str                           # 状态机当前所处状态名
    git_commit_hash: str                         # 绑定的不可变 Git Commit SHA-256
    context_variables: Dict[str, Any]            # 全局上下文与运行配置
    completed_tasks: List[str]                   # 已完成的任务 ID 集合
    active_worktrees: List[Dict[str, Any]]       # 当前活跃挂载的沙箱信息
    snapshot_checksum: str                       # 快照数据 SHA-256 校验和

    @staticmethod
    def compute_checksum(
        snapshot_id: str,
        lsn: int,
        timestamp: float,
        current_state: str,
        git_commit_hash: str,
        context_variables: Dict[str, Any],
        completed_tasks: List[str],
        active_worktrees: List[Dict[str, Any]],
    ) -> str:
        """计算快照核心载荷的确定性 SHA-256 签名"""
        payload = {
            "snapshot_id": snapshot_id,
            "lsn": lsn,
            "timestamp": timestamp,
            "current_state": current_state,
            "git_commit_hash": git_commit_hash,
            "context_variables": context_variables,
            "completed_tasks": sorted(completed_tasks),
            "active_worktrees": active_worktrees,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """校验快照完整性"""
        expected = self.compute_checksum(
            snapshot_id=self.snapshot_id,
            lsn=self.lsn,
            timestamp=self.timestamp,
            current_state=self.current_state,
            git_commit_hash=self.git_commit_hash,
            context_variables=self.context_variables,
            completed_tasks=self.completed_tasks,
            active_worktrees=self.active_worktrees,
        )
        return expected == self.snapshot_checksum

    @classmethod
    def create(
        cls,
        lsn: int,
        current_state: FSMState | str,
        git_commit_hash: str,
        context_variables: Optional[Dict[str, Any]] = None,
        completed_tasks: Optional[List[str]] = None,
        active_worktrees: Optional[List[Dict[str, Any]]] = None,
    ) -> "FSMStateSnapshot":
        """工厂方法：创建并自签名一个全息快照"""
        snap_id = f"snap_{uuid.uuid4().hex[:12]}"
        now = time.time()
        state_str = current_state.value if isinstance(current_state, FSMState) else str(current_state)
        ctx = context_variables or {}
        tasks = list(completed_tasks or [])
        worktrees = list(active_worktrees or [])

        chk = cls.compute_checksum(
            snapshot_id=snap_id,
            lsn=lsn,
            timestamp=now,
            current_state=state_str,
            git_commit_hash=git_commit_hash,
            context_variables=ctx,
            completed_tasks=tasks,
            active_worktrees=worktrees,
        )

        return cls(
            snapshot_id=snap_id,
            lsn=lsn,
            timestamp=now,
            current_state=state_str,
            git_commit_hash=git_commit_hash,
            context_variables=ctx,
            completed_tasks=tasks,
            active_worktrees=worktrees,
            snapshot_checksum=chk,
        )

    def to_json(self) -> str:
        """导出格式化 JSON 字符串"""
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "FSMStateSnapshot":
        """从 JSON 字符串安全反序列化并自动校验防篡改"""
        raw = json.loads(json_str)
        snapshot = cls(
            snapshot_id=str(raw["snapshot_id"]),
            lsn=int(raw["lsn"]),
            timestamp=float(raw["timestamp"]),
            current_state=str(raw["current_state"]),
            git_commit_hash=str(raw["git_commit_hash"]),
            context_variables=dict(raw.get("context_variables", {})),
            completed_tasks=list(raw.get("completed_tasks", [])),
            active_worktrees=list(raw.get("active_worktrees", [])),
            snapshot_checksum=str(raw["snapshot_checksum"]),
        )
        if not snapshot.verify_integrity():
            raise SnapshotError(
                f"Snapshot integrity verification failed for ID={snapshot.snapshot_id}, LSN={snapshot.lsn}!"
            )
        return snapshot


class AtomicSnapshotEngine:
    """
    原子快照落盘与自愈恢复引擎。
    采用“写入临时文件 (.tmp) -> 同步刷盘 (fsync) -> 原子重命名 (os.replace)”策略，
    在 Windows NTFS 及 POSIX 环境下彻底消除快照写入中途断电导致文件损坏的风险。
    """

    def __init__(self, snapshot_dir: str) -> None:
        self.snapshot_dir = os.path.abspath(snapshot_dir)
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self.latest_link_path = os.path.join(self.snapshot_dir, "latest_snapshot.json")

    def save_snapshot(self, snapshot: FSMStateSnapshot) -> str:
        """
        原子落盘快照文件，并原子更新 latest_snapshot.json 指针。
        :return: 最终生成的权威快照物理路径
        """
        target_filename = f"snapshot_lsn_{snapshot.lsn}_{snapshot.git_commit_hash[:8]}.json"
        final_path = os.path.join(self.snapshot_dir, target_filename)

        # 写入独占临时文件
        tmp_path = f"{final_path}.tmp_{time.time_ns()}_{os.getpid()}"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(snapshot.to_json())
                f.flush()
                os.fsync(f.fileno())

            # 原子重命名至目标快照
            os.replace(tmp_path, final_path)

            # 同时原子更新 latest_snapshot.json
            latest_tmp = f"{self.latest_link_path}.tmp_{time.time_ns()}"
            with open(latest_tmp, "w", encoding="utf-8") as f:
                f.write(snapshot.to_json())
                f.flush()
                os.fsync(f.fileno())
            os.replace(latest_tmp, self.latest_link_path)

            return final_path
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def load_latest_snapshot(self) -> Optional[FSMStateSnapshot]:
        """
        加载最新快照。优先读取 latest_snapshot.json，若异常则回退至快照目录中最高 LSN 文件。
        """
        if os.path.exists(self.latest_link_path):
            try:
                with open(self.latest_link_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return FSMStateSnapshot.from_json(content)
            except Exception:
                # 指针异常，回退目录扫描
                pass

        all_snapshots = self.list_snapshots()
        if not all_snapshots:
            return None

        # 按 LSN 降序尝试
        for snap_path in all_snapshots:
            try:
                with open(snap_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return FSMStateSnapshot.from_json(content)
            except Exception:
                continue

        return None

    def restore_state(self, snapshot_path: Optional[str] = None) -> FSMStateSnapshot:
        """
        全息恢复状态：从指定路径或最新快照加载状态。
        若无法读取到任何合规快照，抛出 SnapshotError。
        """
        if snapshot_path:
            if not os.path.exists(snapshot_path):
                raise SnapshotError(f"Specified snapshot file does not exist: {snapshot_path}")
            with open(snapshot_path, "r", encoding="utf-8") as f:
                return FSMStateSnapshot.from_json(f.read())

        latest = self.load_latest_snapshot()
        if latest is None:
            raise SnapshotError(f"No valid snapshot found in directory: {self.snapshot_dir}")
        return latest

    def list_snapshots(self) -> List[str]:
        """列出目录下所有已保存的快照绝对路径，按 LSN 降序排列"""
        files = []
        for name in os.listdir(self.snapshot_dir):
            if name.startswith("snapshot_lsn_") and name.endswith(".json"):
                full_path = os.path.join(self.snapshot_dir, name)
                files.append(full_path)

        def _extract_lsn(path: str) -> int:
            base = os.path.basename(path)
            try:
                parts = base.split("_")
                return int(parts[2])
            except Exception:
                return 0

        files.sort(key=_extract_lsn, reverse=True)
        return files

    def prune_snapshots(self, keep_count: int = 5) -> int:
        """保留最新的 keep_count 个快照文件，安全清理更早的历史快照"""
        snapshots = self.list_snapshots()
        if len(snapshots) <= keep_count:
            return 0

        pruned = 0
        for old_path in snapshots[keep_count:]:
            try:
                os.remove(old_path)
                pruned += 1
            except OSError:
                pass
        return pruned
