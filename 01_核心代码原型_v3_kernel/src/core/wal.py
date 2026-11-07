"""
Write-Ahead Logging (WAL) Engine: Append-Only Event Sourcing, Cryptographic Checksums, and Deterministic Replay.
Author: worker_m2 (Implementation Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from .contracts import FSMState, IFSMDriver, WALCorruptionError

__all__ = [
    "WALEntry",
    "WriteAheadLog",
]


@dataclass(frozen=True)
class WALEntry:
    """
    单条不可变预写日志记录实体。
    严格满足：
    WAL_Entry = <LSN, Timestamp, NodeID, FromState, ToState, CommitHash, Payload, PayloadChecksum>
    """
    lsn: int                                     # 单调递增日志序列号 (Log Sequence Number)
    timestamp: float                             # 物理发生时间戳
    node_id: str                                 # 写入节点或沙箱标识符
    from_state: str                              # 状态跃迁源状态
    to_state: str                                # 状态跃迁目标状态
    commit_hash: str                             # 关联 Git Commit Hash
    payload: Dict[str, Any]                      # 状态迁移参数与附加数据
    payload_checksum: str                        # 负载 SHA-256 密码学防篡改校验和

    @staticmethod
    def compute_checksum(payload: Dict[str, Any]) -> str:
        """计算字典对象的确定性 SHA-256 校验和"""
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def verify_integrity(self) -> bool:
        """校验当前日志记录在内存与落盘状态下的完整性"""
        expected = self.compute_checksum(self.payload)
        return expected == self.payload_checksum

    def to_json_line(self) -> str:
        """序列化为单行 JSON 字符串 (包含换行符)"""
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False) + "\n"

    @classmethod
    def from_json_line(cls, line: str) -> "WALEntry":
        """从 JSON 行反序列化并自动执行校验"""
        raw = json.loads(line)
        entry = cls(
            lsn=int(raw["lsn"]),
            timestamp=float(raw["timestamp"]),
            node_id=str(raw["node_id"]),
            from_state=str(raw["from_state"]),
            to_state=str(raw["to_state"]),
            commit_hash=str(raw["commit_hash"]),
            payload=raw.get("payload", {}),
            payload_checksum=str(raw["payload_checksum"]),
        )
        if not entry.verify_integrity():
            raise WALCorruptionError(
                f"WAL entry at LSN={entry.lsn} failed checksum verification! "
                f"Recorded={entry.payload_checksum}, Computed={cls.compute_checksum(entry.payload)}"
            )
        return entry


class WriteAheadLog:
    """
    仅追加预写日志驱动器 (Append-Only Write Ahead Log).
    功能保障：
    1. 线程安全的单调自增 LSN 分配；
    2. 物理刷盘（fsync）保证崩溃不丢数据；
    3. 全息重放（Deterministic Replay）能力，从 0 还原状态机；
    4. 密码学 SHA-256 防静默数据损坏。
    """

    def __init__(self, log_path: str, auto_sync: bool = True) -> None:
        """
        初始化 WAL 预写日志。
        :param log_path: WAL 日志物理落盘文件路径 (.jsonl)
        :param auto_sync: 每次写入后是否强制执行操作系统级 os.fsync
        """
        self.log_path = os.path.abspath(log_path)
        self.auto_sync = auto_sync
        self._lock = threading.Lock()
        self._current_lsn = 0

        # 确保父目录存在
        log_dir = os.path.dirname(self.log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        # 启动时恢复当前最大 LSN
        self._init_or_recover()

    def _init_or_recover(self) -> None:
        """检查并恢复最新 LSN"""
        if not os.path.exists(self.log_path):
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.flush()
            self._current_lsn = 0
            return

        max_lsn = 0
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                clean_line = line.strip()
                if not clean_line:
                    continue
                try:
                    entry = WALEntry.from_json_line(clean_line)
                    if entry.lsn > max_lsn:
                        max_lsn = entry.lsn
                except Exception as e:
                    raise WALCorruptionError(
                        f"Failed to parse existing WAL file {self.log_path} at line {line_no}: {e}"
                    ) from e
        self._current_lsn = max_lsn

    @property
    def current_lsn(self) -> int:
        """获取当前最新分配的 LSN"""
        with self._lock:
            return self._current_lsn

    def append(
        self,
        node_id: str,
        from_state: FSMState | str,
        to_state: FSMState | str,
        commit_hash: str = "HEAD",
        payload: Optional[Dict[str, Any]] = None,
    ) -> WALEntry:
        """
        向仅追加日志持久化一条状态跃迁记录。
        该方法在返回前确保日志已可靠落盘。
        """
        payload_dict = payload or {}
        from_val = from_state.value if isinstance(from_state, FSMState) else str(from_state)
        to_val = to_state.value if isinstance(to_state, FSMState) else str(to_state)
        checksum = WALEntry.compute_checksum(payload_dict)

        with self._lock:
            self._current_lsn += 1
            entry = WALEntry(
                lsn=self._current_lsn,
                timestamp=time.time(),
                node_id=node_id,
                from_state=from_val,
                to_state=to_val,
                commit_hash=commit_hash,
                payload=payload_dict,
                payload_checksum=checksum,
            )
            line = entry.to_json_line()

            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                if self.auto_sync:
                    os.fsync(f.fileno())

        return entry

    def read_entries(self, from_lsn: int = 0) -> List[WALEntry]:
        """按序读取从指定 from_lsn 开始的所有日志记录，并验证校验和"""
        entries: List[WALEntry] = []
        if not os.path.exists(self.log_path):
            return entries

        with self._lock:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    clean_line = line.strip()
                    if not clean_line:
                        continue
                    try:
                        entry = WALEntry.from_json_line(clean_line)
                        if entry.lsn >= from_lsn:
                            entries.append(entry)
                    except Exception as e:
                        raise WALCorruptionError(
                            f"WAL read corruption in {self.log_path} at line {line_no}: {e}"
                        ) from e
        return entries

    def deterministic_replay(self, driver: IFSMDriver, from_lsn: int = 0) -> int:
        """
        确定性状态重放：将 WAL 日志依序回放至目标状态机驱动引擎中。
        重放期间驱动引擎不应重复向 WAL 写入新日志。
        :param driver: 实现了 IFSMDriver 接口的目标状态机
        :param from_lsn: 起始 LSN (通常为快照绑定的最新 LSN + 1)
        :return: 成功回放的步骤数
        """
        entries = self.read_entries(from_lsn=from_lsn)
        replayed_count = 0

        for entry in entries:
            target_state = FSMState(entry.to_state)
            # 执行直接状态跃迁恢复
            if hasattr(driver, "force_set_state"):
                driver.force_set_state(target_state, context=entry.payload)
            elif hasattr(driver, "_current_state"):
                setattr(driver, "_current_state", target_state)
            replayed_count += 1

        return replayed_count

    def truncate_before(self, up_to_lsn: int) -> int:
        """
        日志压缩修剪：安全移除 LSN 小于 up_to_lsn 的历史旧日志（用于快照生成后释放磁盘）。
        采用原子写重命名机制保障文件安全。
        :return: 修剪掉的历史日志条目数
        """
        with self._lock:
            if not os.path.exists(self.log_path):
                return 0

            entries_to_keep: List[WALEntry] = []
            removed_count = 0

            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip()
                    if not clean:
                        continue
                    entry = WALEntry.from_json_line(clean)
                    if entry.lsn >= up_to_lsn:
                        entries_to_keep.append(entry)
                    else:
                        removed_count += 1

            tmp_path = f"{self.log_path}.tmp_{time.time_ns()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                for entry in entries_to_keep:
                    f.write(entry.to_json_line())
                f.flush()
                if self.auto_sync:
                    os.fsync(f.fileno())

            # 原子替换
            os.replace(tmp_path, self.log_path)
            return removed_count

    def close(self) -> None:
        """关闭日志资源"""
        pass

    def __enter__(self) -> "WriteAheadLog":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
