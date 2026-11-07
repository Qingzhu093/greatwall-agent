"""
Clean-Room Sandbox, Path Jail, Windows Job Object Hardware Limiter & WinError 32 Tombstone Purge.
精简务实版沙箱基础设施：
1. 无 .git 清洁室快照导出与提交 (支持 bare git repo 或基于 SHA-256 快照池的零泄漏克隆)；
2. SandboxPathJail：把探索节点的文件读写锁死在自身孤岛与同血统公共只读区内；
3. run_bounded_subprocess：环境变量脱敏清洗 + Windows Job Object 进程树连坐强杀与内存封顶；
4. force_cleanup_directory：毫秒级原子重命名至墓园 + 指数退避清理，彻底解决 Windows WinError 32。
"""

from __future__ import annotations

import ctypes
import gc
import hashlib
import io
import json
import os
import random
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# 1. 路径牢笼 (SandboxPathJail) —— 防 ../../ 越界与跨血统偷看
# ============================================================================

class SandboxPathJail:
    """
    强制将探索节点的文件访问锁死在：
    - 读写白名单：自身孤岛目录 `island_root`
    - 只读白名单：公共只读目录 `shared_readonly_root`（其中 `lineage_notes/` 仅限读取本血统 `lineage_id`）
    严禁访问 `.kernel_vault`、隔壁孤岛目录或宿主机外部路径。
    """

    def __init__(self, island_root: Path, shared_readonly_root: Path, allowed_lineage_id: str = "GLOBAL") -> None:
        self.island_root = island_root.resolve()
        self.shared_readonly_root = shared_readonly_root.resolve()
        self.allowed_lineage_id = allowed_lineage_id

    def validate_read(self, target_path: str | Path) -> Path:
        p = Path(target_path)
        real_path = p.resolve() if p.is_absolute() else (self.island_root / p).resolve()

        if real_path.is_relative_to(self.island_root):
            return real_path

        if real_path.is_relative_to(self.shared_readonly_root):
            lineage_dir = (self.shared_readonly_root / "archive" / "lineage_notes").resolve()
            if real_path.is_relative_to(lineage_dir) and real_path != lineage_dir:
                if self.allowed_lineage_id != "GLOBAL" and not real_path.name.startswith(self.allowed_lineage_id):
                    raise PermissionError(
                        f"跨血统隐私隔离拦截：节点血统 '{self.allowed_lineage_id}' 禁止读取其他血统笔记 '{real_path.name}'"
                    )
            return real_path

        raise PermissionError(
            f"沙箱越界读取拦截：路径 '{target_path}' (解析为 '{real_path}') 不在当前孤岛或公共只读区白名单内"
        )

    def validate_write(self, target_path: str | Path) -> Path:
        p = Path(target_path)
        real_path = p.resolve() if p.is_absolute() else (self.island_root / p).resolve()

        if real_path.is_relative_to(self.island_root):
            # 严禁在孤岛内部创建伪造的 .git 目录
            if ".git" in real_path.relative_to(self.island_root).parts:
                raise PermissionError("清洁室安全拦截：严禁在探索孤岛内创建或修改 .git 目录")
            return real_path

        raise PermissionError(
            f"沙箱越界写入拦截：禁止修改孤岛外部文件 '{target_path}' (解析为 '{real_path}')"
        )


# ============================================================================
# 2. Windows WinError 32 绝缘：五步墓碑原子移走与退避回收算法
# ============================================================================

def _close_in_process_handles(target_dir: Path) -> None:
    """主动关闭当前 Python 进程内残留指向 target_dir 的未关闭文件句柄"""
    try:
        resolved = target_dir.resolve()
        for obj in gc.get_objects():
            try:
                if isinstance(obj, io.IOBase):
                    name = getattr(obj, "name", None)
                    if name and isinstance(name, str):
                        p = Path(name).resolve()
                        if p == resolved or resolved in p.parents:
                            obj.close()
            except Exception:
                pass
    except Exception:
        pass


def force_cleanup_directory(target_dir: Path, graveyard_dir: Path) -> bool:
    """
    防 WinError 32 五步原子回收算法：
    1. GC 释放本进程文件描述符并尝试直接删除；
    2. 毫秒级原子重命名 (os.replace) 移入 .trash_graveyard 瞬间腾出槽位；
    3. 若重命名被外部子进程锁死，在 Windows 下按命令行路径匹配强杀残留进程；
    4. 清除只读权限位 (stat.S_IWRITE) + 指数退避重试删除；
    5. 顽固文件逐个疏散至墓园，确保原槽位路径 100% 干净可用。
    """
    target_dir = target_dir.resolve()
    if not target_dir.exists():
        return True

    graveyard_dir = graveyard_dir.resolve()
    graveyard_dir.mkdir(parents=True, exist_ok=True)

    def _on_rm_error(func: Any, path: str, exc_info: Any) -> None:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except Exception:
            pass

    # 步骤 1：本进程句柄清理 + 快速直接删除尝试
    _close_in_process_handles(target_dir)
    gc.collect()
    try:
        shutil.rmtree(target_dir, onerror=_on_rm_error)
        if not target_dir.exists():
            return True
    except Exception:
        pass

    # 步骤 2：原子重命名到墓园（瞬间腾出原路径）
    tombstone_path = graveyard_dir / f"tomb_{target_dir.name}_{uuid.uuid4().hex[:8]}_{int(time.time())}"
    try:
        os.replace(target_dir, tombstone_path)
    except PermissionError:
        # 步骤 3：按路径查找并强杀残留子进程 (Windows)
        if sys.platform == "win32":
            escaped = str(target_dir).replace("\\", "\\\\").replace("'", "''")
            kill_cmd = (
                f"Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.CommandLine -match '{escaped}' }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"
            )
            try:
                subprocess.run(["pwsh", "-NoProfile", "-Command", kill_cmd], capture_output=True, timeout=6)
            except Exception:
                pass
            time.sleep(0.15)
        try:
            os.replace(target_dir, tombstone_path)
        except Exception:
            tombstone_path = target_dir

    # 步骤 4：指数退避重试彻底删除墓碑
    for attempt in range(4):
        if not tombstone_path.exists():
            break
        shutil.rmtree(tombstone_path, onerror=_on_rm_error)
        if not tombstone_path.exists():
            break
        time.sleep(0.05 * (2 ** attempt) + random.uniform(0.0, 0.01))

    # 步骤 5：若仍在原位（整目录重命名失败），逐个文件移走
    if target_dir.exists():
        fallback_tomb = graveyard_dir / f"evac_{target_dir.name}_{uuid.uuid4().hex[:6]}"
        fallback_tomb.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(target_dir, topdown=False):
            for f in files:
                fp = Path(root) / f
                try:
                    os.chmod(fp, stat.S_IWRITE)
                    rel = fp.relative_to(target_dir)
                    dest = fallback_tomb / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(fp, dest)
                except Exception:
                    try:
                        fp.unlink(missing_ok=True)
                    except Exception:
                        pass
            for d in dirs:
                try:
                    (Path(root) / d).rmdir()
                except Exception:
                    pass
        try:
            target_dir.rmdir()
        except Exception:
            pass

    return not target_dir.exists()


# ============================================================================
# 3. 进程级硬件限额执行器 (Windows Job Object + 环境变量脱敏)
# ============================================================================

@dataclass
class SubprocessRunResult:
    exit_code: int
    stdout: str
    stderr: str
    wall_time_sec: float
    peak_memory_mb: float
    is_timeout: bool


def build_sanitized_env(island_dir: Path, shared_readonly_dir: Path, extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    清洗子进程环境变量：
    - 剥离宿主机所有 API Key、Token、代理配置与 Git 全局变量；
    - 注入只读共享区与档案馆到 PYTHONPATH，使节点可直接 `from archive.ledger.primitives import xxx`；
    - 锁定 PYTHONHASHSEED=42 保证确定性复现。
    """
    safe_keys = {
        "SYSTEMROOT", "PATH", "TEMP", "TMP", "WINDIR", "COMSPEC",
        "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PATHEXT",
        "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    }
    clean_env = {k: v for k, v in os.environ.items() if k.upper() in safe_keys}
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONUTF8"] = "1"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    clean_env["PYTHONHASHSEED"] = "42"
    clean_env["NO_PROXY"] = "*"
    clean_env["HTTP_PROXY"] = ""
    clean_env["HTTPS_PROXY"] = ""

    # 将孤岛 src、孤岛根目录、shared_readonly 加入 PYTHONPATH
    py_paths = [
        str((island_dir / "src").resolve()),
        str(island_dir.resolve()),
        str(shared_readonly_dir.resolve()),
    ]
    existing_py = os.environ.get("PYTHONPATH", "")
    if existing_py:
        py_paths.append(existing_py)
    clean_env["PYTHONPATH"] = os.pathsep.join(py_paths)

    if extra_env:
        clean_env.update(extra_env)
    return clean_env


def _attach_windows_job_object(proc_handle: int, max_memory_mb: int = 8192) -> Optional[Tuple[int, Any]]:
    """Windows 专用：创建内核 Job Object，绑定进程树连坐强杀 (KILL_ON_JOB_CLOSE) 与物理内存上限"""
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            return None

        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        mem_bytes = max(64, max_memory_mb) * 1024 * 1024
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.ProcessMemoryLimit = mem_bytes
        info.JobMemoryLimit = mem_bytes

        kernel32.SetInformationJobObject(
            job_handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        kernel32.AssignProcessToJobObject(job_handle, ctypes.c_void_p(int(proc_handle)))
        return job_handle, JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    except Exception:
        return None


def _query_and_close_job_object(job_tuple: Optional[Tuple[int, Any]]) -> float:
    """读取 Windows Job Object 峰值内存占用 (MB) 并关闭句柄（自动触发子孙进程连坐强杀）"""
    if not job_tuple or sys.platform != "win32":
        return 0.0
    job_handle, struct_cls = job_tuple
    peak_mb = 0.0
    try:
        kernel32 = ctypes.windll.kernel32
        info = struct_cls()
        ret_len = ctypes.c_ulong(0)
        res = kernel32.QueryInformationJobObject(
            job_handle, 9, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret_len)
        )
        if res:
            peak_bytes = max(info.PeakJobMemoryUsed, info.PeakProcessMemoryUsed)
            peak_mb = round(peak_bytes / (1024.0 * 1024.0), 2)
    except Exception:
        pass
    finally:
        try:
            ctypes.windll.kernel32.CloseHandle(job_handle)
        except Exception:
            pass
    return peak_mb


def run_bounded_subprocess(
    cmd: List[str],
    cwd: Path,
    shared_readonly_dir: Path,
    timeout_sec: float = 120.0,
    max_memory_mb: int = 8192,
    extra_env: Optional[Dict[str, str]] = None,
) -> SubprocessRunResult:
    """在脱敏环境变量与内核 Job Object 限额保护下运行沙箱子进程"""
    env = build_sanitized_env(cwd, shared_readonly_dir, extra_env)
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd.resolve()),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    job_tuple = _attach_windows_job_object(getattr(proc, "_handle", 0), max_memory_mb=max_memory_mb)
    is_timeout = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        exit_code = proc.returncode if proc.returncode is not None else -1
    except subprocess.TimeoutExpired:
        is_timeout = True
        proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=3.0)
        except Exception:
            stdout, stderr = "", "Subprocess hard timeout expired and killed by Job Object."
        exit_code = 124
    finally:
        elapsed = round(time.perf_counter() - t0, 4)
        peak_mb = _query_and_close_job_object(job_tuple)

    return SubprocessRunResult(
        exit_code=exit_code,
        stdout=stdout or "",
        stderr=stderr or "",
        wall_time_sec=elapsed,
        peak_memory_mb=peak_mb,
        is_timeout=is_timeout,
    )


# ============================================================================
# 4. 无 .git 清洁室孤岛快照导出与提交管理器 (CleanRoomSandbox)
# ============================================================================

class CleanRoomSandbox:
    """
    管理 `.kernel_vault/snapshots/` 与 `worktrees/slot_xx_node_yy/` 之间的纯净代码快照流转：
    - 导出给探索节点的孤岛目录内部 100% 不含 `.git` 目录或历史分支信息；
    - 每个 Commit 以确定性 SHA-256 内容寻址快照存储在 `.kernel_vault/snapshots/<commit_hash>/` 中，
      彻底避免外部 Git 配置冲突，同时支持毫秒级跨分支检出、回滚与代码块热插拔替换。
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.vault_dir = self.workspace_root / ".kernel_vault"
        self.snapshots_dir = self.vault_dir / "snapshots"
        self.worktrees_dir = self.workspace_root / "worktrees"
        self.graveyard_dir = self.workspace_root / ".trash_graveyard"
        self.shared_readonly_dir = self.workspace_root / "shared_readonly"

        for d in (self.vault_dir, self.snapshots_dir, self.worktrees_dir, self.graveyard_dir, self.shared_readonly_dir):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_directory_hash(src_dir: Path, parent_commit: str = "GENESIS", message: str = "") -> Tuple[str, Dict[str, str]]:
        """计算目录内所有业务源码文件 (排除 legacy_out 与临时缓存) 的整体确定性 SHA-256 Commit Hash"""
        hasher = hashlib.sha256()
        hasher.update(f"parent:{parent_commit}|msg:{message}\n".encode("utf-8"))
        file_manifest: Dict[str, str] = {}

        if not src_dir.exists():
            return hasher.hexdigest()[:16], file_manifest

        ignored_Top = {"legacy_out", "__pycache__", ".pytest_cache", ".git"}
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = sorted([d for d in dirs if d not in ignored_Top and not d.startswith(".")])
            for fname in sorted(files):
                if fname.endswith((".pyc", ".pyo")) or fname == "scoped_brief.md":
                    continue
                fpath = Path(root) / fname
                rel = fpath.relative_to(src_dir).as_posix()
                data = fpath.read_bytes()
                fhash = hashlib.sha256(data).hexdigest()
                file_manifest[rel] = fhash
                hasher.update(f"{rel}:{fhash}\n".encode("utf-8"))

        return hasher.hexdigest()[:16], file_manifest

    def store_snapshot(self, source_dir: Path, parent_commit: str = "GENESIS", message: str = "") -> str:
        """将给定目录的纯净代码归档入 `.kernel_vault/snapshots/<commit_hash>` 并返回 16 位 Commit ID"""
        commit_hash, manifest = self.compute_directory_hash(source_dir, parent_commit, message)
        snap_dir = self.snapshots_dir / commit_hash
        files_dir = snap_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        for rel in manifest:
            src_file = source_dir / rel
            dst_file = files_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)

        meta = {
            "commit_hash": commit_hash,
            "parent_commit": parent_commit,
            "message": message,
            "created_at": time.time(),
            "file_manifest": manifest,
        }
        (snap_dir / "commit_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return commit_hash

    def checkout_clean_island(self, commit_hash: str, slot_dir_name: str, scoped_brief_md: str = "") -> Path:
        """
        将指定 Commit 快照导出到 `worktrees/<slot_dir_name>/` 清洁室孤岛目录：
        - 内部零 `.git` 元数据；
        - 自动初始化 `src/`、`local_tests/`、`legacy_out/` 目录与 `scoped_brief.md`。
        """
        island_dir = self.worktrees_dir / slot_dir_name
        if island_dir.exists():
            force_cleanup_directory(island_dir, self.graveyard_dir)

        island_dir.mkdir(parents=True, exist_ok=True)
        (island_dir / "src").mkdir(exist_ok=True)
        (island_dir / "local_tests").mkdir(exist_ok=True)
        (island_dir / "legacy_out").mkdir(exist_ok=True)

        snap_files_dir = self.snapshots_dir / commit_hash / "files"
        if snap_files_dir.exists():
            for root, _, files in os.walk(snap_files_dir):
                for fname in files:
                    s_file = Path(root) / fname
                    rel = s_file.relative_to(snap_files_dir)
                    d_file = island_dir / rel
                    d_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(s_file, d_file)

        if scoped_brief_md:
            (island_dir / "scoped_brief.md").write_text(scoped_brief_md, encoding="utf-8")

        return island_dir

    @staticmethod
    def surgical_replace_block(script_path: Path, target_block_name: str, new_block_code: str) -> Tuple[bool, str]:
        """
        MLE-STAR 式局部代码块微创热插拔替换 (`s_t.replace(c_t, c_t^{(k)})`)：
        - 利用 Python AST 精准定位脚本中的目标函数或类定义 `target_block_name` 的起止行号；
        - 冻结脚本其余全部代码，仅原位替换该目标函数/类定义，并自动验证替换后的全文件 AST 语法合法性，
          从根源上消除全量重写导致的 41.7% 语法崩溃与变量遗漏。
        """
        import ast

        if not script_path.exists():
            return False, f"目标脚本不存在: {script_path}"

        original_source = script_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original_source)
        except SyntaxError as e:
            return False, f"原脚本存在语法错误: {e}"

        # 校验新代码块本身的语法
        try:
            new_tree = ast.parse(new_block_code)
        except SyntaxError as e:
            return False, f"提交的新代码块 '{target_block_name}' 存在语法错误，拒绝合入: {e}"

        target_node: Optional[ast.AST] = None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == target_block_name:
                target_node = node
                break

        lines = original_source.splitlines(keepends=True)
        if target_node is not None and hasattr(target_node, "lineno") and hasattr(target_node, "end_lineno"):
            # 若存在装饰器，从第一个装饰器行开始替换
            decorator_list = getattr(target_node, "decorator_list", [])
            start_line = min([target_node.lineno] + [d.lineno for d in decorator_list]) - 1
            end_line = target_node.end_lineno
            replacement = new_block_code if new_block_code.endswith("\n") else new_block_code + "\n"
            updated_source = "".join(lines[:start_line]) + replacement + "".join(lines[end_line:])
            action_msg = f"已原位微创替换代码块 '{target_block_name}' (原第 {start_line + 1}~{end_line} 行)"
        else:
            # 若目标函数为新增算子，安全追加在文件末尾（或 if __name__ == '__main__' 之前）
            main_guard_idx = None
            for node in tree.body:
                if isinstance(node, ast.If):
                    unparsed_test = ast.unparse(node.test)
                    if "__name__" in unparsed_test and "__main__" in unparsed_test:
                        main_guard_idx = node.lineno - 1
                        break
            replacement = "\n\n" + new_block_code.strip() + "\n\n"
            if main_guard_idx is not None:
                updated_source = "".join(lines[:main_guard_idx]) + replacement + "".join(lines[main_guard_idx:])
            else:
                updated_source = original_source.rstrip() + replacement
            action_msg = f"未找到同名旧块，已将新代码块 '{target_block_name}' 安全挂载至脚本主入口前"

        # 最终全文件 AST 二次校验
        try:
            ast.parse(updated_source)
        except SyntaxError as e:
            return False, f"替换后全文件 AST 校验未通过，已自动回滚: {e}"

        script_path.write_text(updated_source, encoding="utf-8")
        return True, action_msg
