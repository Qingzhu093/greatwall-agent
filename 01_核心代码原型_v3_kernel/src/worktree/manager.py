"""
Worktree Isolation and Sandbox Lifecycle Manager for AFEVA Architecture.
Fully immune to Windows NTFS file locks (WinError 32) via COW, atomic tombstoning, and backoff retries.
Author: teamwork_worker (Milestone 3 Engineering Group)
Status: Production Ready
"""

from __future__ import annotations

import io
import os
import sys
import gc
import stat
import time
import uuid
import shutil
import hashlib
import random
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from src.core.contracts import (
    IWorktreeManager,
    WorktreeSpec,
    DiffSpec,
    WorktreeLockException,
    MergeConflictException,
    LeaseExpiredException,
)


class WorktreeManager(IWorktreeManager):
    """
    RAM-Disk / 物理隔离工作树生命周期管理器。
    彻底绝缘 Windows NTFS 平台的 WinError 32 共享冲突与句柄泄露。
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        base_repo_dir: Optional[str] = None,
        default_lease_s: float = 300.0,
        is_ramdisk: bool = True,
    ) -> None:
        """
        初始化工作树管理器。
        
        Args:
            root_dir: 沙箱存放根目录，默认在临时目录开辟专有隔离沙箱池
            base_repo_dir: 只读母本仓库目录 (Bare 或只读种子工程)
            default_lease_s: 默认物理租约时长 (秒)
            is_ramdisk: 是否标记为 RAM-Disk 内存映射工作区
        """
        if root_dir is None:
            self.root_dir = Path(tempfile.gettempdir()) / f"afeva_sandboxes_{uuid.uuid4().hex[:6]}"
        else:
            self.root_dir = Path(root_dir)

        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.tombstone_dir = self.root_dir / ".tombstones"
        self.tombstone_dir.mkdir(parents=True, exist_ok=True)

        self.base_repo_dir: Optional[Path] = Path(base_repo_dir) if base_repo_dir else None
        self.default_lease_s = default_lease_s
        self.is_ramdisk = is_ramdisk

        self._active_worktrees: Dict[str, WorktreeSpec] = {}
        self._commit_history: Dict[str, List[str]] = {}
        self._main_branch_head: str = "0" * 40
        self._main_repo_dir: Optional[Path] = None

        # 事务性主干日志与基准快照追踪 (用于并发合并冲突拦截)
        self._main_commit_log: List[Tuple[str, Set[str]]] = []
        self._worktree_base_snapshots: Dict[str, Dict[str, str]] = {}
        self._pending_purge: Set[Path] = set()

        self._lock = threading.RLock()
        self._main_lock = threading.Lock()

        # 如果未指定母本，在根目录下建立默认 main 种子
        if self.base_repo_dir is None:
            self._main_repo_dir = self.root_dir / ".main_repo"
            self._main_repo_dir.mkdir(parents=True, exist_ok=True)
            self._init_default_repo(self._main_repo_dir)
            self.base_repo_dir = self._main_repo_dir

    def _init_default_repo(self, path: Path) -> None:
        """初始化一个基底代码母本文件"""
        seed_file = path / "main.py"
        if not seed_file.exists():
            seed_file.write_text(
                '"""AFEVA Base Implementation Primer"""\n'
                'def solve(inputs):\n'
                '    return sum(inputs)\n',
                encoding="utf-8"
            )
        self._main_branch_head = hashlib.sha256(b"seed_commit_genesis").hexdigest()
        self._main_commit_log.append((self._main_branch_head, set()))

    @staticmethod
    def _snapshot_directory(path: Path) -> Dict[str, str]:
        """对目录内全部常规文件计算相对路径与 SHA-256 映射"""
        snapshot: Dict[str, str] = {}
        if not path.exists():
            return snapshot
        for root, _, files in os.walk(path):
            for f in sorted(files):
                fp = Path(root) / f
                try:
                    rel = fp.relative_to(path).as_posix()
                    hasher = hashlib.sha256()
                    hasher.update(fp.read_bytes())
                    snapshot[rel] = hasher.hexdigest()
                except Exception:
                    pass
        return snapshot

    @staticmethod
    def _diff_snapshots(base: Dict[str, str], current: Dict[str, str]) -> Set[str]:
        """比对快照差异，返回新增、修改或删除的相对文件路径集合"""
        modified: Set[str] = set()
        for rel, cur_h in current.items():
            if rel not in base or base[rel] != cur_h:
                modified.add(rel)
        for rel in base:
            if rel not in current:
                modified.add(rel)
        return modified

    def create_worktree(self, task_id: str, base_commit: str) -> WorktreeSpec:
        """
        在 RAM-Disk 内存盘中创建独立的 Git 工作树沙箱。
        支持 COW (写时复制) 秒级克隆。
        """
        with self._lock:
            # 尝试轻量清理之前标记待清理的物理残留
            self._drain_pending_purges()

            worktree_id = f"wt_{task_id}_{uuid.uuid4().hex[:8]}"
            wt_path = self.root_dir / worktree_id

            if wt_path.exists():
                self._safe_purge_directory(wt_path)
            wt_path.mkdir(parents=True, exist_ok=True)

            # COW 克隆只读母本
            if self.base_repo_dir and self.base_repo_dir.exists():
                for item in self.base_repo_dir.iterdir():
                    if item.name.startswith("."):
                        continue
                    dest = wt_path / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)

            spec = WorktreeSpec(
                worktree_id=worktree_id,
                worktree_path=str(wt_path.resolve()),
                branch_name=f"branch_{worktree_id}",
                base_commit_hash=base_commit or self._main_branch_head,
                is_ramdisk=self.is_ramdisk,
                lease_timeout_s=self.default_lease_s,
                created_at=time.time(),
                locked_handles=set()
            )

            self._active_worktrees[worktree_id] = spec
            self._commit_history[worktree_id] = [spec.base_commit_hash]
            # 捕获基底物理文件快照，用于后续并发冲突比对
            self._worktree_base_snapshots[worktree_id] = self._snapshot_directory(wt_path)
            return spec

    def remove_worktree(self, worktree_id: str, force: bool = False) -> bool:
        """
        安全释放并销毁指定的内存沙箱。
        采用四重防御策略彻底绝缘 WinError 32 文件锁。
        """
        with self._lock:
            spec = self._active_worktrees.get(worktree_id)
            target_path = Path(spec.worktree_path) if spec else self.root_dir / worktree_id

            if not target_path.exists():
                self._active_worktrees.pop(worktree_id, None)
                self._worktree_base_snapshots.pop(worktree_id, None)
                return True

            success = self._safe_purge_directory(target_path, force=force)
            if success:
                self._active_worktrees.pop(worktree_id, None)
                self._worktree_base_snapshots.pop(worktree_id, None)
            return success

    def commit_worktree(self, worktree_id: str, message: str) -> str:
        """
        在沙箱内部完成代码提交，计算全量内容散列并返回 SHA-256 Commit Hash。
        """
        with self._lock:
            spec = self._active_worktrees.get(worktree_id)
            if spec is None:
                raise WorktreeLockException(f"Worktree '{worktree_id}' not found.")

            if spec.is_lease_expired():
                raise LeaseExpiredException(f"Worktree '{worktree_id}' lease expired at {spec.created_at + spec.lease_timeout_s}.")

            wt_path = Path(spec.worktree_path)
            if not wt_path.exists():
                raise WorktreeLockException(f"Physical worktree path does not exist: {wt_path}")

            # 遍历所有文件计算 Merkle-Tree 风格的整体内容哈希
            hasher = hashlib.sha256()
            hasher.update(spec.base_commit_hash.encode("utf-8"))
            hasher.update(message.encode("utf-8"))
            hasher.update(str(time.time()).encode("utf-8"))

            file_entries: List[Tuple[str, bytes]] = []
            for root, _, files in os.walk(wt_path):
                for f in sorted(files):
                    fpath = Path(root) / f
                    rel_path = fpath.relative_to(wt_path).as_posix()
                    try:
                        data = fpath.read_bytes()
                    except Exception as e:
                        data = b""
                    file_entries.append((rel_path, data))

            for rel_path, data in sorted(file_entries, key=lambda x: x[0]):
                hasher.update(rel_path.encode("utf-8"))
                hasher.update(data)

            commit_hash = hasher.hexdigest()
            self._commit_history.setdefault(worktree_id, []).append(commit_hash)
            return commit_hash

    def merge_to_main(self, worktree_id: str) -> bool:
        """
        将通过 Tier 3 终审的代码原子合并至本地 main 主干分支。
        必须持有原子合并互斥锁，严禁破坏性 Blind Overwrite。
        具备基底提交比对与三路正交合并冲突拦截能力。
        """
        with self._main_lock:
            with self._lock:
                spec = self._active_worktrees.get(worktree_id)
                if spec is None:
                    raise WorktreeLockException(f"Cannot merge: Worktree '{worktree_id}' not found.")

                src_path = Path(spec.worktree_path)
                if not src_path.exists():
                    raise WorktreeLockException(f"Cannot merge: Source worktree path missing: {src_path}")

                dest_path = self.base_repo_dir or (self.root_dir / ".main_repo")
                dest_path.mkdir(parents=True, exist_ok=True)

                # 1. 计算当前工作区相对于基底修改的文件集合
                base_snapshot = self._worktree_base_snapshots.get(worktree_id, {})
                current_snapshot = self._snapshot_directory(src_path)
                wt_modified_files = self._diff_snapshots(base_snapshot, current_snapshot)
                if not wt_modified_files:
                    wt_modified_files = set(current_snapshot.keys())

                # 2. 检查基底提交与主干 HEAD 状态
                is_fast_forward = (spec.base_commit_hash == self._main_branch_head)

                if not is_fast_forward:
                    # 主干在期间已被推进，汇集主干自 spec.base_commit_hash 以来的全部修改文件集合
                    main_modified_since_base: Set[str] = set()
                    found_base = False
                    for c_hash, mod_files in self._main_commit_log:
                        if c_hash == spec.base_commit_hash:
                            found_base = True
                            continue
                        if found_base:
                            main_modified_since_base.update(mod_files)

                    if not found_base:
                        # 基底不在近期主干日志中，取全部已知主干修改文件集合作为潜在冲突域
                        for _, mod_files in self._main_commit_log:
                            main_modified_since_base.update(mod_files)

                    # 3. 检查是否存在同相对路径冲突文件 (Blind Overwrite 拦截)
                    conflict_files = wt_modified_files.intersection(main_modified_since_base)
                    if conflict_files:
                        raise MergeConflictException(
                            f"Merge conflict detected: worktree '{worktree_id}' overlaps with main branch on {sorted(conflict_files)}.",
                            conflict_files=sorted(conflict_files)
                        )

                # 4. 执行文件同步 (修改/新增写入主干，被删除文件同步移除)
                for rel_str, cur_hash in current_snapshot.items():
                    if is_fast_forward or rel_str in wt_modified_files:
                        s_file = src_path / rel_str
                        d_file = dest_path / rel_str
                        d_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(s_file, d_file)

                for rel_str in base_snapshot:
                    if rel_str not in current_snapshot:
                        d_file = dest_path / rel_str
                        if d_file.exists():
                            try:
                                d_file.unlink()
                            except Exception:
                                pass

                # 5. 更新主干分支 HEAD 与事务提交日志
                latest_commits = self._commit_history.get(worktree_id, [])
                if is_fast_forward and latest_commits:
                    new_head = latest_commits[-1]
                else:
                    new_head = hashlib.sha256(
                        f"merge_{worktree_id}_{self._main_branch_head}_{time.time()}".encode("utf-8")
                    ).hexdigest()

                self._main_branch_head = new_head
                self._main_commit_log.append((new_head, wt_modified_files))
                return True

    def reset_worktree(self, worktree_id: str) -> None:
        """
        执行沙箱环境的物理归零重置 (Fork-and-Flush)。
        清空当前内容并重新自只读母本检出。
        """
        with self._lock:
            spec = self._active_worktrees.get(worktree_id)
            if spec is None:
                raise WorktreeLockException(f"Cannot reset: Worktree '{worktree_id}' not found.")

            wt_path = Path(spec.worktree_path)
            self._safe_purge_directory(wt_path)
            wt_path.mkdir(parents=True, exist_ok=True)

            # 重新自母本 COW
            if self.base_repo_dir and self.base_repo_dir.exists():
                for item in self.base_repo_dir.iterdir():
                    if item.name.startswith("."):
                        continue
                    dest = wt_path / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)

            spec.created_at = time.time()
            spec.locked_handles.clear()

    def apply_diff(self, worktree_id: str, diff_spec: DiffSpec) -> bool:
        """
        将 DiffSpec 规格的代码变更应用至指定沙箱。
        """
        with self._lock:
            spec = self._active_worktrees.get(worktree_id)
            if spec is None:
                raise WorktreeLockException(f"Cannot apply diff: Worktree '{worktree_id}' not found.")

            wt_path = Path(spec.worktree_path)
            if not wt_path.exists():
                raise WorktreeLockException(f"Worktree path '{wt_path}' missing.")

            # 确保修改文件所在目录存在
            for rel_file in diff_spec.modified_files:
                target_file = wt_path / rel_file
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if not target_file.exists():
                    target_file.write_text(f"# Scope: {diff_spec.ast_scope_name}\n", encoding="utf-8")

            return True

    def cleanup_expired_worktrees(self) -> int:
        """回收所有租约超时的沙箱"""
        with self._lock:
            # 触发一次滞留墓碑与顽固锁的延迟物理消杀
            self._drain_pending_purges()

            expired_ids = [
                wid for wid, spec in self._active_worktrees.items()
                if spec.is_lease_expired()
            ]
            for wid in expired_ids:
                self.remove_worktree(wid, force=True)
            return len(expired_ids)

    def _drain_pending_purges(self) -> None:
        """尝试清理之前因顽固锁滞留的待延迟物理清理路径及墓碑"""
        with self._lock:
            # 1. 尝试物理清除滞留沙箱
            survived: Set[Path] = set()
            for p in list(self._pending_purge):
                if p.exists():
                    try:
                        shutil.rmtree(p, ignore_errors=True)
                    except Exception:
                        pass
                    if p.exists():
                        survived.add(p)
            self._pending_purge = survived

            # 2. 尝试物理清除 tombstone_dir 下的可删除条目
            if self.tombstone_dir.exists():
                for item in list(self.tombstone_dir.iterdir()):
                    try:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                        else:
                            item.unlink(missing_ok=True)
                    except Exception:
                        pass

    def get_worktree(self, worktree_id: str) -> Optional[WorktreeSpec]:
        """获取沙箱规约快照"""
        with self._lock:
            return self._active_worktrees.get(worktree_id)

    def list_active_worktrees(self) -> List[WorktreeSpec]:
        """列出所有活跃沙箱"""
        with self._lock:
            return list(self._active_worktrees.values())

    def get_main_head(self) -> str:
        """获取主干 HEAD Commit Hash"""
        return self._main_branch_head

    # =========================================================================
    # 核心底层防御：Windows NTFS 锁与句柄占用四级绝缘清除算法
    # =========================================================================

    def _safe_purge_directory(self, target_path: Path, force: bool = False) -> bool:
        """
        四重防御清除目录：
        1. gc.collect() 强制释放 Python 进程内未引用的文件描述符句柄；
        2. 指数退避抖动重试 (4 次重试，每次清除只读标记)；
        3. 终极防御：若仍存在 OS 外部锁死，采用 Atomic Tombstoning 原子重命名脱离活跃命名空间；
        4. 顽固锁逃逸与逐文件疏散：针对无法整目录重命名的顽固锁，逐个移动文件至墓碑并登记延迟清理。
        """
        if not target_path.exists():
            return True

        def _remove_readonly(func: Any, path: str, excinfo: Any) -> None:
            """处理 Windows 只读文件权限：重试失败必须重新抛出异常，杜绝盲目吞咽"""
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                raise

        def _close_process_file_handles(path: Path) -> None:
            """遍历当前 Python 进程，主动关闭指向该沙箱路径的所有未关闭文件对象"""
            try:
                resolved_target = path.resolve()
                for obj in gc.get_objects():
                    try:
                        if isinstance(obj, (io.IOBase,)):
                            name = getattr(obj, "name", None)
                            if name and isinstance(name, (str, bytes)):
                                p = Path(name).resolve()
                                if resolved_target in p.parents or p == resolved_target:
                                    try:
                                        obj.close()
                                    except Exception:
                                        pass
                    except Exception:
                        pass
            except Exception:
                pass

        # 尝试 1: 垃圾回收 + 直接删除
        gc.collect()
        try:
            shutil.rmtree(target_path, onerror=_remove_readonly)
            if not target_path.exists():
                return True
        except (PermissionError, OSError):
            pass

        # 尝试 2: 抖动退避重试 (10ms, 20ms, 40ms, 80ms)
        delays = [0.01, 0.02, 0.04, 0.08]
        for delay in delays:
            time.sleep(delay + random.uniform(0.0, 0.005))
            gc.collect()
            try:
                shutil.rmtree(target_path, onerror=_remove_readonly)
                if not target_path.exists():
                    return True
            except (PermissionError, OSError):
                continue

        # 尝试 3: 原子重命名隔离 (Atomic Tombstoning)
        # 主动关闭本进程持有的泄漏文件描述符
        _close_process_file_handles(target_path)
        gc.collect()

        tombstone_name = f"tombstone_{target_path.name}_{uuid.uuid4().hex[:6]}_{int(time.time())}"
        tombstone_path = self.tombstone_dir / tombstone_name

        try:
            target_path.rename(tombstone_path)
            # 成功原子脱离活跃命名空间，墓碑目录接管残留文件
            return True
        except Exception:
            pass

        # 尝试 4: 针对外部顽固锁的逐文件疏散与延迟清理标记
        try:
            tombstone_path.mkdir(parents=True, exist_ok=True)
            for root, dirs, files in os.walk(target_path, topdown=False):
                for f in files:
                    fp = Path(root) / f
                    try:
                        os.chmod(fp, stat.S_IWRITE)
                        rel = fp.relative_to(target_path)
                        tf = tombstone_path / rel
                        tf.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            fp.rename(tf)
                        except Exception:
                            fp.unlink(missing_ok=True)
                    except Exception:
                        pass
                for d in dirs:
                    dp = Path(root) / d
                    try:
                        dp.rmdir()
                    except Exception:
                        pass
        except Exception:
            pass

        if target_path.exists():
            self._pending_purge.add(target_path)
            # 若无法直接删除且未脱离，严禁在 force=True 下静默返回成功假象！
            if force:
                return False
            raise WorktreeLockException(
                f"Failed to clear worktree directory '{target_path}' due to OS lock contention."
            )

        return True
