"""长城 V6-Up (v3.0) 通用跨进程隔离仪器容器与校准集回归引擎（零第三方依赖）。

核心工程规格（对齐 09 第四章 & agent_kb/04）：
1. 极薄零过拟合容器（plugin is everything）：不硬编码任何学科误差门禁、零解禁令或题名黑名单；
2. 统一三档四态协议：`evaluate(artifact, spec, tier) -> {status, verdict, tracks, details}`；
   四态物理隔离（OK / CANDIDATE_ERROR / INSTRUMENT_ERROR / INFRA_ERROR），判不了绝不判负；
3. 四元复合缓存键：`sha256(candidate_entry_sha256 + recursive_tools_dir_sha256 + spec_sha256(含 tier + data_slice) + instrument_sha256)`；
4. Stage A 外部持久化至 `$PLUGIN_DATA/workspaces/<ws_hash>/eval_artifacts/<obs_id>/stage_a_output.json`，支持 Stage B 诚实重评；
5. 独立校准集回归引擎：独立子进程逐条核对自声明 `(expected_status, expected_verdict)` 100% 匹配。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


class RequestCancelledError(RuntimeError):
    """请求已被上游显式取消，子进程树已终止且严禁继续落库。"""


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def _run_subprocess_cancellable(
    cmd: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_sec: float,
    cancel_event: Any = None,
) -> subprocess.CompletedProcess[str]:
    """跨平台可取消子进程执行器：支持超时与 `cancel_event` 实时终止整棵子进程树。"""
    if cancel_event is not None and cancel_event.is_set():
        raise RequestCancelledError("请求在启动子进程前已取消")

    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    deadline = time.monotonic() + max(0.5, float(timeout_sec))
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _terminate_process_tree(proc)
                raise RequestCancelledError("请求已取消，已强制终止隔离评测子进程树")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(proc)
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout_sec)
            slice_sec = min(0.05, remaining) if cancel_event is not None else remaining
            try:
                stdout_txt, stderr_txt = proc.communicate(timeout=slice_sec)
                return subprocess.CompletedProcess(cmd, proc.returncode, stdout_txt, stderr_txt)
            except subprocess.TimeoutExpired:
                if cancel_event is None:
                    _terminate_process_tree(proc)
                    raise
    except Exception:
        _terminate_process_tree(proc)
        raise

from .base_instrument import (
    ALLOWED_INSTRUMENT_TIERS,
    map_instrument_result_to_obs_status,
    validate_instrument_result,
)

_CLEAN_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
_CORE_PYTHON_DIR = str(Path(__file__).resolve().parent.parent)
_PROJECT_ROOT_DIR = str(Path(__file__).resolve().parent.parent.parent)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def compute_recursive_dir_sha256(dir_path: str | Path | None) -> str:
    """递归计算 `<worktree>/tools/` 下全部非缓存文件的复合 SHA-256。"""
    if not dir_path:
        return sha256_bytes(b"EMPTY_TOOLS_DIR")
    root = Path(dir_path)
    if not root.is_dir():
        return sha256_bytes(b"EMPTY_TOOLS_DIR")
    h = hashlib.sha256()
    files: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
            files.append(p)
    files.sort(key=lambda p: p.relative_to(root).as_posix())
    if not files:
        return sha256_bytes(b"EMPTY_TOOLS_DIR")
    for fp in files:
        rel = fp.relative_to(root).as_posix().encode("utf-8")
        h.update(rel + b"\x00")
        h.update(sha256_file(fp).encode("ascii") + b"\n")
    return h.hexdigest()


def compute_eval_cache_key(
    *,
    candidate_entry_sha256: str,
    tools_dir_sha256: str,
    spec_sha256: str,
    instrument_sha256: str,
) -> str:
    """四元复合幂等缓存指纹（任一维度变动均强制失效重算）。"""
    joined = "|".join([candidate_entry_sha256, tools_dir_sha256, spec_sha256, instrument_sha256])
    return sha256_bytes(joined.encode("utf-8"))


def compute_spec_sha256(spec: dict[str, Any], tier: str) -> str:
    """将 tier、public_input 与 data_slice_sha256 一并纳入 spec 指纹，严防跨档串用缓存。"""
    payload = {
        "tier": str(tier),
        "spec": spec,
    }
    return sha256_json(payload)


def _build_clean_env(extra_pythonpath: list[str] | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    for k in _CLEAN_ENV_ALLOWLIST:
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if extra_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(extra_pythonpath)
    return env


def _copy_branch_tools_into_sandbox(cand_src: Path, sandbox: Path, worktree_root: str = "") -> Path | None:
    """安全复制分支 `<worktree>/tools/` 供候选脚本在隔离 Stage A 中导入。"""
    candidates_tools: list[Path] = []
    if worktree_root:
        candidates_tools.append(Path(worktree_root) / "tools")
    elif cand_src.parent.name in ("src", "scripts", "solutions", "proofs"):
        candidates_tools.append(cand_src.parent.parent / "tools")
    else:
        candidates_tools.append(cand_src.parent / "tools")

    for src_tools in candidates_tools:
        if src_tools.is_dir():
            dst_tools = sandbox / "tools"
            shutil.copytree(
                src_tools,
                dst_tools,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"),
                dirs_exist_ok=True,
            )
            return src_tools
    return None


def _is_python_run_artifact(artifact_path: Path, artifact_schema: str) -> bool:
    schema_l = str(artifact_schema or "").strip().lower()
    if schema_l in ("raw_file", "raw_artifact", "lean", "lean4", "json", "text", "markdown", "counterexample_json"):
        return False
    return artifact_path.suffix.lower() == ".py"


def _candidate_py_exports_run(cand_file: Path) -> bool:
    """AST 静态检查 `.py` 候选是否定义了顶层 `run(...)` 函数（有语法错误时交由 Stage A 报 CANDIDATE_ERROR）。"""
    import ast as _ast

    try:
        src = cand_file.read_text(encoding="utf-8", errors="replace")
        tree = _ast.parse(src, filename=str(cand_file))
    except SyntaxError:
        return True
    except OSError:
        return False
    for node in tree.body:
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)) and node.name == "run":
            return True
    return False


def _instrument_calls_get_public_input(inst_file: Path) -> bool:
    """检查仪器脚本是否显式依赖 `get_public_input`（若不依赖且 spec 未配 public_input，支持直通 Stage B）。"""
    try:
        src = inst_file.read_text(encoding="utf-8", errors="replace")
        return "get_public_input" in src
    except OSError:
        return False


_STAGE_A_CHILD_SCRIPT = r"""
import json, pathlib, runpy, sys, traceback

cand_path = sys.argv[1]
public_input_path = sys.argv[2]
out_path = sys.argv[3]
err_path = sys.argv[4]

try:
    sys.path.insert(0, str(pathlib.Path(cand_path).parent))
    pub_in = json.loads(pathlib.Path(public_input_path).read_text(encoding="utf-8"))
    ns = runpy.run_path(cand_path, run_name="_gw_candidate")
    run_fn = ns.get("run")
    if not callable(run_fn):
        raise AttributeError("候选 Python 模块缺少可调用入口 run(public_input)")
    res = run_fn(pub_in)
    if not isinstance(res, dict):
        raise TypeError(f"候选 run(public_input) 必须返回 dict，实收 {type(res).__name__}")
    encoded = json.dumps(res, ensure_ascii=False, allow_nan=False)
    pathlib.Path(out_path).write_text(encoded, encoding="utf-8")
except Exception as exc:
    tb = traceback.format_exc(limit=6)
    pathlib.Path(err_path).write_text(
        json.dumps({"error_type": type(exc).__name__, "message": str(exc), "traceback": tb}, ensure_ascii=False),
        encoding="utf-8",
    )
    sys.exit(2)
"""


_STAGE_B_CHILD_SCRIPT = r"""
import importlib.util, inspect, json, pathlib, sys, traceback

inst_path = sys.argv[1]
artifact_json_path = sys.argv[2]
spec_json_path = sys.argv[3]
tier = sys.argv[4]
inst_role = sys.argv[5]
out_path = sys.argv[6]

sys.path.insert(0, sys.argv[7])
if len(sys.argv) > 8 and sys.argv[8]:
    sys.path.insert(0, sys.argv[8])
from evaluators import base_instrument as _gw_base_inst
sys.modules.setdefault("core_python.evaluators.base_instrument", _gw_base_inst)
InstrumentInputError = _gw_base_inst.InstrumentInputError
validate_instrument_result = _gw_base_inst.validate_instrument_result

def write_out(payload):
    pathlib.Path(out_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

try:
    artifact = json.loads(pathlib.Path(artifact_json_path).read_text(encoding="utf-8"))
    spec = json.loads(pathlib.Path(spec_json_path).read_text(encoding="utf-8"))

    mod_spec = importlib.util.spec_from_file_location("_gw_instrument_mod", inst_path)
    if mod_spec is None or mod_spec.loader is None:
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"无法加载仪器模块: {inst_path}",
        })
        sys.exit(0)
    mod = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(mod)

    eval_fn = getattr(mod, "evaluate", None)
    if not callable(eval_fn):
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": "仪器缺少必需的可调用入口 evaluate(artifact, spec, tier)",
        })
        sys.exit(0)

    try:
        inspect.signature(eval_fn).bind(artifact, spec, tier)
    except TypeError as sig_exc:
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"仪器 evaluate 签名不兼容 (artifact, spec, tier): {sig_exc}",
        })
        sys.exit(0)

    raw_res = eval_fn(artifact, spec, tier)
    ok, norm, err_msg = validate_instrument_result(raw_res, instrument_role=inst_role)
    if not ok:
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"仪器返回协议违约: {err_msg}",
        })
        sys.exit(0)
    write_out(norm)
except InstrumentInputError as ierr:
    write_out({
        "status": "INSTRUMENT_ERROR",
        "verdict": None,
        "tracks": {},
        "details": f"仪器取数错误 (InstrumentInputError): {ierr}",
    })
except KeyError as kerr:
    tb_frames = traceback.extract_tb(kerr.__traceback__)
    last_line = str(tb_frames[-1].line or "") if tb_frames else ""
    missing_k = kerr.args[0] if kerr.args else None
    is_artifact_missing = (
        isinstance(artifact, dict)
        and missing_k is not None
        and missing_k not in artifact
        and ("artifact" in last_line or "cand" in last_line or "data" in last_line)
    )
    write_out({
        "status": "INSTRUMENT_ERROR",
        "verdict": None,
        "tracks": {"missing_key": str(kerr), "incompatible_schema": bool(is_artifact_missing)},
        "details": f"仪器读取字段缺失 KeyError: {kerr}",
    })
except Exception as exc:
    if type(exc).__name__ == "InstrumentInputError":
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"仪器取数错误 (InstrumentInputError): {exc}",
        })
    else:
        tb = traceback.format_exc(limit=6)
        write_out({
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"仪器内部异常 ({type(exc).__name__}): {exc}\n{tb}",
        })
"""


def _run_stage_a_python(
    cand_file: Path,
    public_input: dict[str, Any],
    worktree_root: str,
    timeout_sec: float,
    persist_stage_a_path: str | None = None,
    cancel_event: Any = None,
) -> tuple[bool, dict[str, Any], str]:
    """在独立临时沙箱子进程运行 Python 候选 `run(public_input)` 并可选持久化产物。"""
    with tempfile.TemporaryDirectory(prefix="gw_stage_a_") as tmp:
        sandbox = Path(tmp)
        cand_dst = sandbox / cand_file.name
        shutil.copy2(cand_file, cand_dst)
        _copy_branch_tools_into_sandbox(cand_file, sandbox, worktree_root=worktree_root)

        pub_in_file = sandbox / "_public_input.json"
        out_file = sandbox / "_stage_a_output.json"
        err_file = sandbox / "_stage_a_error.json"
        pub_in_file.write_text(json.dumps(public_input, ensure_ascii=False), encoding="utf-8")

        env = _build_clean_env([str(sandbox)])
        try:
            proc = _run_subprocess_cancellable(
                [sys.executable, "-I", "-c", _STAGE_A_CHILD_SCRIPT, str(cand_dst), str(pub_in_file), str(out_file), str(err_file)],
                cwd=str(sandbox),
                env=env,
                timeout_sec=timeout_sec,
                cancel_event=cancel_event,
            )
        except RequestCancelledError:
            raise
        except subprocess.TimeoutExpired:
            return False, {}, f"候选执行超时（>{timeout_sec:.1f}s）"
        except Exception as exc:
            return False, {"_infra_error": True}, f"Stage A 容器启动异常: {exc}"

        if proc.returncode != 0 or not out_file.is_file():
            err_detail = f"候选进程退出码 {proc.returncode}"
            if err_file.is_file():
                try:
                    info = json.loads(err_file.read_text(encoding="utf-8"))
                    err_detail = f"{info.get('error_type')}: {info.get('message')}"
                except Exception:
                    pass
            elif proc.stderr.strip():
                err_detail = proc.stderr.strip()[-400:]
            return False, {}, err_detail

        try:
            stage_a_data = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, {}, f"Stage A 输出 JSON 解析失败: {exc}"

        if persist_stage_a_path:
            dst = Path(persist_stage_a_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(stage_a_data, ensure_ascii=False), encoding="utf-8")

        return True, stage_a_data, ""


def _run_stage_b_instrument(
    instrument_file: Path,
    instrument_role: str,
    artifact_payload: Any,
    spec: dict[str, Any],
    tier: str,
    timeout_sec: float,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """在独立子进程中执行仪器 `evaluate(artifact, spec, tier)` 并完成协议校验。"""
    with tempfile.TemporaryDirectory(prefix="gw_stage_b_") as tmp:
        sandbox = Path(tmp)
        art_file = sandbox / "_artifact.json"
        spec_file = sandbox / "_spec.json"
        out_file = sandbox / "_stage_b_result.json"
        art_file.write_text(json.dumps(artifact_payload, ensure_ascii=False), encoding="utf-8")
        spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

        env = _build_clean_env([_CORE_PYTHON_DIR, _PROJECT_ROOT_DIR, str(instrument_file.parent)])
        try:
            proc = _run_subprocess_cancellable(
                [
                    sys.executable,
                    "-c",
                    _STAGE_B_CHILD_SCRIPT,
                    str(instrument_file),
                    str(art_file),
                    str(spec_file),
                    str(tier),
                    str(instrument_role),
                    str(out_file),
                    _CORE_PYTHON_DIR,
                    _PROJECT_ROOT_DIR,
                ],
                cwd=str(sandbox),
                env=env,
                timeout_sec=timeout_sec,
                cancel_event=cancel_event,
            )
        except RequestCancelledError:
            raise
        except subprocess.TimeoutExpired:
            return {
                "status": "INFRA_ERROR",
                "verdict": None,
                "tracks": {},
                "details": f"Stage B 仪器子进程超时（>{timeout_sec:.1f}s）",
            }
        except Exception as exc:
            return {
                "status": "INFRA_ERROR",
                "verdict": None,
                "tracks": {},
                "details": f"Stage B 容器启动失败: {exc}",
            }

        if not out_file.is_file():
            stderr_tail = (proc.stderr or "").strip()[-400:]
            return {
                "status": "INSTRUMENT_ERROR" if proc.returncode != 0 else "INFRA_ERROR",
                "verdict": None,
                "tracks": {},
                "details": f"仪器未输出协议结果 (rc={proc.returncode}): {stderr_tail}",
            }

        try:
            raw_res = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "status": "INSTRUMENT_ERROR",
                "verdict": None,
                "tracks": {},
                "details": f"仪器结果 JSON 解析失败: {exc}",
            }

        ok, norm, err_msg = validate_instrument_result(raw_res, instrument_role=instrument_role)
        if not ok:
            return {
                "status": "INSTRUMENT_ERROR",
                "verdict": None,
                "tracks": {},
                "details": f"仪器返回协议违约: {err_msg}",
            }
        return norm


def run_isolated_instrument(
    *,
    instrument_path: str | Path,
    instrument_role: str,
    artifact_path: str | Path,
    spec: dict[str, Any],
    tier: str = "official",
    artifact_schema: str = "python_run",
    worktree_root: str = "",
    persist_stage_a_path: str | None = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """统一跨进程隔离仪器执行入口（支持三档同码、四态隔离与外部持久化）。"""
    tier_l = str(tier or "official").strip().lower()
    if tier_l not in ALLOWED_INSTRUMENT_TIERS:
        return {
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"非法调用档位 tier={tier!r}，仅允许 {sorted(ALLOWED_INSTRUMENT_TIERS)}",
            "obs_status": "INSTRUMENT_ERROR",
        }

    inst_file = Path(instrument_path)
    if not inst_file.is_file():
        return {
            "status": "INSTRUMENT_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"仪器脚本不存在: {inst_file}",
            "obs_status": "INSTRUMENT_ERROR",
        }

    art_file = Path(artifact_path)
    if not art_file.exists():
        return {
            "status": "CANDIDATE_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"候选产物不存在: {art_file}",
            "obs_status": "CANDIDATE_ERROR",
        }

    eff_spec = dict(spec) if isinstance(spec, dict) else {}
    timeout_sec = max(1.0, min(600.0, float(eff_spec.get("timeout_sec", 60.0))))

    # Stage A：对 Python `run(public_input)` 类型产物隔离执行并持久化；
    # 若候选脚本导出的是自定义函数（如 solve/q1_answer）或仪器本身不依赖 get_public_input 且未配置 public_input，则自动直通 Stage B！
    has_pub_dict = "public_input" in eff_spec and isinstance(eff_spec["public_input"], dict)
    is_py_cand = art_file.is_file() and _is_python_run_artifact(art_file, artifact_schema)
    cand_has_run = _candidate_py_exports_run(art_file) if is_py_cand else False
    inst_needs_pub = _instrument_calls_get_public_input(inst_file) if is_py_cand else False

    if is_py_cand and ((has_pub_dict and cand_has_run) or (not has_pub_dict and cand_has_run and inst_needs_pub)):
        if not has_pub_dict:
            # 平台缺失 public_input 归属仪器/规格配置错误，绝不判候选失败！
            return {
                "status": "INSTRUMENT_ERROR",
                "verdict": None,
                "tracks": {},
                "details": "evaluator_spec 缺少合法字典键 'public_input'（无法驱动 Python 候选 run(public_input)）",
                "obs_status": "INSTRUMENT_ERROR",
            }
        ok_a, stage_a_data, err_a = _run_stage_a_python(
            cand_file=art_file,
            public_input=eff_spec["public_input"],
            worktree_root=worktree_root,
            timeout_sec=timeout_sec,
            persist_stage_a_path=persist_stage_a_path,
            cancel_event=cancel_event,
        )
        if not ok_a:
            is_infra = bool(stage_a_data.get("_infra_error"))
            st = "INFRA_ERROR" if is_infra else "CANDIDATE_ERROR"
            return {
                "status": st,
                "verdict": None,
                "tracks": {},
                "details": err_a,
                "obs_status": st,
            }
        artifact_payload: Any = stage_a_data
    else:
        # 非 Stage-A `run(public_input)` 产物（JSON 反例 / 导出 solve() 的 .py 脚本 / .lean 文件 / 文本 / 目录）
        if art_file.is_file() and art_file.suffix.lower() == ".json":
            try:
                artifact_payload = json.loads(art_file.read_text(encoding="utf-8"))
            except Exception as exc:
                return {
                    "status": "CANDIDATE_ERROR",
                    "verdict": None,
                    "tracks": {},
                    "details": f"JSON 候选产物解析失败: {exc}",
                    "obs_status": "CANDIDATE_ERROR",
                }
        elif art_file.is_file():
            txt = art_file.read_text(encoding="utf-8", errors="replace")
            artifact_payload = {
                "artifact_path": str(art_file),
                "path": str(art_file),
                "module_path": str(art_file),
                "artifact_name": art_file.name,
                "artifact_text": txt,
            }
        else:
            artifact_payload = {
                "artifact_dir": str(art_file),
                "artifact_path": str(art_file),
                "path": str(art_file),
            }

        if persist_stage_a_path:
            dst = Path(persist_stage_a_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(artifact_payload, ensure_ascii=False), encoding="utf-8")

    # Stage B：独立子进程执行仪器 evaluate(artifact, spec, tier)
    res_b = _run_stage_b_instrument(
        instrument_file=inst_file,
        instrument_role=instrument_role,
        artifact_payload=artifact_payload,
        spec=eff_spec,
        tier=tier_l,
        timeout_sec=timeout_sec,
        cancel_event=cancel_event,
    )
    res_b["obs_status"] = map_instrument_result_to_obs_status(res_b["status"], res_b["verdict"])
    return res_b


def run_stage_b_revaluation(
    *,
    instrument_path: str | Path,
    instrument_role: str,
    stage_a_output_path: str | Path,
    spec: dict[str, Any],
    tier: str = "official",
    cancel_event: Any = None,
) -> dict[str, Any]:
    """读取持久化 `stage_a_output.json` 交新版仪器免重跑 Stage B 重算。"""
    if cancel_event is not None and cancel_event.is_set():
        raise RequestCancelledError("Stage B 重评在启动前已取消")
    p = Path(stage_a_output_path)
    if not p.is_file():
        return {
            "status": "INFRA_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"持久化 Stage A 产物不存在: {p}",
            "obs_status": "INFRA_ERROR",
            "incompatible": False,
        }
    try:
        artifact_payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "INFRA_ERROR",
            "verdict": None,
            "tracks": {},
            "details": f"持久化 Stage A 产物损坏: {exc}",
            "obs_status": "INFRA_ERROR",
            "incompatible": False,
        }

    eff_spec = dict(spec) if isinstance(spec, dict) else {}
    timeout_sec = max(1.0, min(600.0, float(eff_spec.get("timeout_sec", 60.0))))
    res_b = _run_stage_b_instrument(
        instrument_file=Path(instrument_path),
        instrument_role=instrument_role,
        artifact_payload=artifact_payload,
        spec=eff_spec,
        tier=str(tier or "official"),
        timeout_sec=timeout_sec,
        cancel_event=cancel_event,
    )
    res_b["obs_status"] = map_instrument_result_to_obs_status(res_b["status"], res_b["verdict"])
    tracks = res_b.get("tracks") or {}
    details_l = str(res_b.get("details") or "").lower()
    res_b["incompatible"] = bool(
        tracks.get("incompatible_schema")
        or tracks.get("incompatible")
        or "incompatible" in details_l
    )
    return res_b


def run_calibration_suite(
    *,
    instrument_path: str | Path,
    instrument_role: str,
    calibration_suite_path: str | Path,
    workspace_root: str | Path,
    artifact_schema: str = "python_run",
    cancel_event: Any = None,
) -> dict[str, Any]:
    """独立子进程实跑全量校准集用例，强校验每条用例自声明 `(expected_status, expected_verdict)` 100% 匹配。"""
    if cancel_event is not None and cancel_event.is_set():
        raise RequestCancelledError("校准集回归在启动前已取消")
    suite_file = Path(calibration_suite_path)
    if not suite_file.is_file():
        return {"passed": False, "error": f"校准集文件不存在: {suite_file}", "total": 0, "passed_count": 0, "failed_cases": []}

    try:
        cases = json.loads(suite_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"passed": False, "error": f"校准集 JSON 解析失败: {exc}", "total": 0, "passed_count": 0, "failed_cases": []}

    if not isinstance(cases, list) or len(cases) == 0:
        return {"passed": False, "error": "校准集必须为包含 >= 1 条用例的非空 JSON 数组", "total": 0, "passed_count": 0, "failed_cases": []}

    ws_root = Path(os.path.realpath(str(workspace_root)))
    suite_dir = suite_file.parent
    results: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []

    for idx, case in enumerate(cases):
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelledError(f"校准集回归在第 {idx + 1} 条用例前已取消")
        if not isinstance(case, dict):
            failed_cases.append({"case_id": f"case_{idx}", "error": "校准用例必须为 JSON 对象"})
            continue
        cid = str(case.get("case_id") or f"case_{idx}")
        exp_status = case.get("expected_status")
        exp_verdict = case.get("expected_verdict")
        tier = str(case.get("tier") or "official")
        art_rel = str(case.get("artifact_rel_path") or "").strip()

        # 支持相对工作区根或相对校准集目录解析样本文件，亦支持用例内联 JSON 对象 artifact / artifact_payload
        inline_has_artifact = ("artifact" in case) or ("artifact_payload" in case)
        inline_val = case["artifact_payload"] if "artifact_payload" in case else case.get("artifact")
        tmp_art_dir: tempfile.TemporaryDirectory[str] | None = None
        case_schema = str(case.get("artifact_schema") or artifact_schema)
        if art_rel:
            art_path = ws_root / art_rel
            if not art_path.exists():
                alt = suite_dir / art_rel
                if alt.exists():
                    art_path = alt
        elif inline_has_artifact:
            tmp_art_dir = tempfile.TemporaryDirectory(prefix="gw_cal_art_")
            art_path = Path(tmp_art_dir.name) / f"{cid}.json"
            art_path.write_text(json.dumps(inline_val, ensure_ascii=False), encoding="utf-8")
            case_schema = "json_file"
        else:
            art_path = Path("")

        spec = dict(case.get("spec") or {})
        if "public_input" in case:
            spec["public_input"] = case["public_input"]
        elif "public_input" not in spec:
            spec["public_input"] = {}

        try:
            actual = run_isolated_instrument(
                instrument_path=instrument_path,
                instrument_role=instrument_role,
                artifact_path=art_path,
                spec=spec,
                tier=tier,
                artifact_schema=case_schema,
                worktree_root=str(ws_root),
                cancel_event=cancel_event,
            )
        finally:
            if tmp_art_dir is not None:
                tmp_art_dir.cleanup()
        matched = (actual.get("status") == exp_status) and (actual.get("verdict") == exp_verdict)
        rec = {
            "case_id": cid,
            "expected_status": exp_status,
            "expected_verdict": exp_verdict,
            "actual_status": actual.get("status"),
            "actual_verdict": actual.get("verdict"),
            "matched": matched,
            "details": str(actual.get("details") or "")[:300],
        }
        results.append(rec)
        if not matched:
            failed_cases.append(rec)

    return {
        "passed": len(failed_cases) == 0 and len(results) > 0,
        "total": len(results),
        "passed_count": len(results) - len(failed_cases),
        "failed_cases": failed_cases,
        "results": results,
    }
