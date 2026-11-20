"""跨进程隔离评估器（v2.2 插件化底座：Stage A 干净执行沙箱 + 持久化产物 + Stage B 插件计分）。

严格遵循《09》§4.4 与《agent_kb/04》§二：
1. 严格保留 `run(public_input)` 入口与禁解析 `stdout` 反作弊铁律；
2. 修复 P14：`runpy.run_path(..., run_name="_gw_candidate")` 避开 `"__main__"` 误触发本地自测；
3. 修复 P2：动态读取 `evaluator_spec["timeout_sec"]`（限 `[1.0, 600.0]` 秒）；
4. 修复 P1/P28/P29：持久化 `eval_artifacts/<obs_id>/stage_a_output.json`，支持 `STAGE_B_ONLY` 秒级重评；
5. 插件化评估协议（`plugin is everything`）：按题动态加载 `hook_<question_id>.py`：
   - 首选标准入口 `evaluate_candidate(stage_a_artifact, spec) -> {"passed": bool, "metrics": dict, "details": str}`；
   - 同步兼容既有示例钩子入口 `evaluate(cand_data, spec)`。
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_CLEAN_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")

_HIDDEN_SPEC_KEYS = frozenset(
    {
        "ground_truth",
        "reference_u_final",
        "reference_frontier",
        "nadir_secret",
        "expected_theorem_sha256",
        "expected_theorem_statement",
        "allowed_external_axioms",
        "r_nadir",
        "domain_hook_path",
    }
)

_STAGE_A_SHIM = r'''
import json
import runpy
import sys
from pathlib import Path

def main():
    cand_file = Path(sys.argv[1])
    pub_file = Path(sys.argv[2])
    out_file = Path(sys.argv[3])
    cand_dir = str(cand_file.parent)
    if cand_dir not in sys.path:
        sys.path.insert(0, cand_dir)
    public_input = json.loads(pub_file.read_text(encoding="utf-8"))
    ns = runpy.run_path(str(cand_file), run_name="_gw_candidate")
    run_fn = ns.get("run")
    if callable(run_fn):
        result = run_fn(public_input)
        if not out_file.exists():
            out_file.write_text(
                json.dumps(result, ensure_ascii=False, allow_nan=True),
                encoding="utf-8",
            )

if __name__ == "__main__":
    main()
'''


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(file_path: Path) -> str:
    if not file_path.is_file():
        return ""
    return sha256_bytes(file_path.read_bytes())


def sha256_canonical_json(obj: Any) -> str:
    encoded = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def _resolve_timeout_sec(spec: dict[str, Any], default_timeout: float) -> float:
    raw = spec.get("timeout_sec", default_timeout)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return max(1.0, min(600.0, float(default_timeout)))
    val = float(raw)
    if not math.isfinite(val):
        return max(1.0, min(600.0, float(default_timeout)))
    return max(1.0, min(600.0, val))


def _build_clean_env(sandbox_dir: Path) -> dict[str, str]:
    """构造剔除 PLUGIN_DATA / GREATWALL_DB_PATH / 密钥环境变量的最小白名单环境。"""
    clean_env: dict[str, str] = {}
    for key in _CLEAN_ENV_ALLOWLIST:
        val = os.environ.get(key)
        if val is not None:
            clean_env[key] = val
    sandbox_str = str(sandbox_dir)
    clean_env["TEMP"] = sandbox_str
    clean_env["TMP"] = sandbox_str
    clean_env["TMPDIR"] = sandbox_str
    clean_env["PYTHONUTF8"] = "1"
    clean_env["PYTHONIOENCODING"] = "utf-8"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    return clean_env


def _strip_hidden_recursive(obj: Any) -> Any:
    """递归剥离任何层级的隐藏配置键。"""
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k)
            if ks in _HIDDEN_SPEC_KEYS or ks.startswith(("hidden_", "secret_")):
                continue
            cleaned[k] = _strip_hidden_recursive(v)
        return cleaned
    if isinstance(obj, list):
        return [_strip_hidden_recursive(item) for item in obj]
    return obj


def _sanitize_public_spec(evaluator_spec: dict[str, Any]) -> dict[str, Any]:
    """构造下发给 Stage A 候选进程的公开输入，物理剔除隐藏键。"""
    pub = evaluator_spec.get("public_input")
    if isinstance(pub, dict):
        return _strip_hidden_recursive(pub)
    return _strip_hidden_recursive(evaluator_spec)


def _check_all_finite(obj: Any) -> bool:
    """递归拦截任意 NaN / Inf / -Inf 数值。"""
    if isinstance(obj, bool):
        return True
    if isinstance(obj, (int, float)):
        return math.isfinite(float(obj))
    if isinstance(obj, list):
        return all(_check_all_finite(item) for item in obj)
    if isinstance(obj, dict):
        return all(_check_all_finite(v) for v in obj.values())
    return True


def _normalize_plugin_verdict(raw: Any) -> dict[str, Any]:
    """将标准 `{passed, metrics, details}` 或传统 `{validity_state, raw_metrics, ...}` 映射为统一 Stage B 结果。"""
    if not isinstance(raw, dict):
        return {
            "obs_status": "EXECUTION_ERROR",
            "validity_state": "EXECUTION_ERROR",
            "passed": False,
            "metrics": {},
            "raw_metrics": {},
            "details": "验证钩子未返回 dict",
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_HOOK_PROTOCOL_OUTPUT",
        }

    # 标准 v2.2 协议: {"passed": bool, "metrics": dict, "details": str}
    if "passed" in raw and "metrics" in raw and "details" in raw:
        if (
            not isinstance(raw["passed"], bool)
            or not isinstance(raw["metrics"], dict)
            or not isinstance(raw["details"], str)
        ):
            return {
                "obs_status": "EXECUTION_ERROR",
                "validity_state": "EXECUTION_ERROR",
                "passed": False,
                "metrics": {},
                "raw_metrics": {},
                "details": "验证钩子返回值不符合 {passed: bool, metrics: dict, details: str} 类型契约",
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INVALID_HOOK_PROTOCOL_OUTPUT",
            }
        passed = bool(raw["passed"])
        metrics = raw["metrics"]
        details = raw["details"]
        rank_score = raw.get("comparable_rank_score")
        if rank_score is None:
            for cand_k in ("score", "comparable_rank_score", "rank_score", "primary_score"):
                v = metrics.get(cand_k)
                if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)):
                    rank_score = float(v)
                    break
        elif isinstance(rank_score, bool) or not isinstance(rank_score, (int, float)):
            rank_score = None
        else:
            rank_score = float(rank_score)

        obs_status = str(raw.get("obs_status") or ("VALID" if passed else "MEASURED_NON_IMPROVEMENT"))
        if obs_status not in (
            "VALID",
            "EXECUTION_ERROR",
            "MEASURED_NON_IMPROVEMENT",
            "INCONCLUSIVE",
            "INVALIDATED",
        ):
            obs_status = "VALID" if passed else "MEASURED_NON_IMPROVEMENT"
        return {
            "obs_status": obs_status,
            "validity_state": "VALID" if obs_status == "VALID" else obs_status,
            "passed": passed,
            "metrics": metrics,
            "raw_metrics": metrics,
            "details": details,
            "domain_invariants_passed": passed,
            "comparable_rank_score": rank_score,
            "failure_category": "" if passed else str(raw.get("failure_category") or "HOOK_CRITERIA_NOT_MET"),
        }

    # 兼容既有 examples 协议
    vstate = str(raw.get("validity_state") or "INVALIDATED")
    passed = bool(raw.get("domain_invariants_passed", vstate == "VALID"))
    metrics = raw.get("raw_metrics") if isinstance(raw.get("raw_metrics"), dict) else {}
    details = str(raw.get("details") or raw.get("failure_category") or vstate)
    obs_status = "VALID" if (vstate == "VALID" and passed) else (
        "EXECUTION_ERROR" if vstate == "EXECUTION_ERROR" else "MEASURED_NON_IMPROVEMENT" if vstate == "VALID" else vstate
    )
    rank_score = raw.get("comparable_rank_score")
    if rank_score is None:
        for cand_k in ("score", "comparable_rank_score", "rank_score", "primary_score"):
            v = metrics.get(cand_k)
            if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)):
                rank_score = float(v)
                break
    elif isinstance(rank_score, bool) or not isinstance(rank_score, (int, float)):
        rank_score = None
    else:
        rank_score = float(rank_score)
    return {
        "obs_status": obs_status,
        "validity_state": vstate,
        "passed": passed,
        "metrics": metrics,
        "raw_metrics": metrics,
        "details": details,
        "domain_invariants_passed": passed,
        "comparable_rank_score": rank_score,
        "failure_category": str(raw.get("failure_category") or ""),
    }


def _fail_verdict(
    obs_status: str, failure_category: str, details: str = "", raw_metrics: dict[str, Any] | None = None
) -> dict[str, Any]:
    metrics = raw_metrics or {}
    return {
        "obs_status": obs_status,
        "validity_state": obs_status,
        "passed": False,
        "metrics": metrics,
        "raw_metrics": metrics,
        "details": details or failure_category,
        "domain_invariants_passed": False,
        "comparable_rank_score": None,
        "failure_category": failure_category,
    }


def _validate_eval_fn_ast_returns(hook_file: Path, entry_name: str) -> str | None:
    """静态检查钩子函数体直接返回的字典字面量，防止含 valid/缺 passed|metrics|details 的旧/假协议通过。"""
    try:
        tree = ast.parse(hook_file.read_text(encoding="utf-8", errors="replace"), filename=str(hook_file))
    except SyntaxError as exc:
        return f"钩子语法错误: {exc}"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                    missing = [k for k in ("passed", "metrics", "details") if k not in keys]
                    if missing:
                        return f"{entry_name} 返回字典字面量缺少必需字段 {missing}（当前键={sorted(keys)}）"
            return None
    return None


def _run_baseline_probe_output(baseline_file: Path | None, sample_payload: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """若同题 baseline 导出了 run(public_input) 且 sample_payload 非空，实跑获取真实 Stage A 载荷用于冒烟测试。"""
    if baseline_file is None or not baseline_file.is_file() or not sample_payload:
        return None, False
    try:
        bspec = importlib.util.spec_from_file_location("_gw_baseline_probe", str(baseline_file))
        if bspec is None or bspec.loader is None:
            return None, False
        bmod = importlib.util.module_from_spec(bspec)
        bspec.loader.exec_module(bmod)
        run_fn = getattr(bmod, "run", None)
        if not callable(run_fn):
            return None, False
        out = run_fn(copy.deepcopy(sample_payload))
        if isinstance(out, dict):
            return out, True
    except Exception:
        return None, False
    return None, False


def _validate_hook_return_contract(raw_res: Any, entry_name: str) -> tuple[bool, str]:
    """严格校验钩子返回是否符合 {passed: bool, metrics: dict, details: str} 协议。"""
    if not isinstance(raw_res, dict):
        return False, f"{entry_name} 返回值必须为 dict，实收 {type(raw_res).__name__}"
    if "passed" not in raw_res or not isinstance(raw_res["passed"], bool):
        return False, f"{entry_name} 返回缺少布尔型 'passed' 字段（严禁用 'valid' 替代；实收键={sorted(raw_res.keys())}）"
    if "metrics" not in raw_res or not isinstance(raw_res["metrics"], dict):
        return False, f"{entry_name} 返回缺少字典型 'metrics' 字段（实收键={sorted(raw_res.keys())}）"
    if "details" not in raw_res or not isinstance(raw_res["details"], str):
        return False, f"{entry_name} 返回缺少字符串型 'details' 字段（实收键={sorted(raw_res.keys())}）"
    return True, "OK"


def probe_domain_hook_protocol(
    hook_path: str | Path,
    sample_payload: dict[str, Any] | None = None,
    baseline_path: str | Path | None = None,
    spec: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """对验证钩子执行导出签名 + Smoke Call 协议检验，阻止求解器或非标返回值误锁入 Stage 2。"""
    hook_file = Path(hook_path)
    if not hook_file.is_file():
        return False, f"钩子文件不存在: {hook_file}"
    try:
        mod_spec = importlib.util.spec_from_file_location("_gw_domain_hook_probe", str(hook_file))
        if mod_spec is None or mod_spec.loader is None:
            return False, f"无法加载钩子模块: {hook_file}"
        hook_mod = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(hook_mod)
    except Exception as exc:
        return False, f"加载钩子模块失败: {type(exc).__name__}: {exc}"

    entry_name = ""
    eval_fn = getattr(hook_mod, "evaluate_candidate", None)
    if callable(eval_fn):
        entry_name = "evaluate_candidate"
    else:
        eval_legacy = getattr(hook_mod, "evaluate", None)
        if callable(eval_legacy):
            eval_fn = eval_legacy
            entry_name = "evaluate"

    if not callable(eval_fn):
        return (
            False,
            "钩子缺少必需的可调用入口 evaluate_candidate(cand_data, spec)（严禁仅提供 compute_metrics / solve）",
        )

    try:
        sig = inspect.signature(eval_fn)
        sig.bind({}, {})
    except TypeError as exc:
        return False, f"{entry_name} 参数签名不兼容 (cand_data, spec): {exc}"

    ast_err = _validate_eval_fn_ast_returns(hook_file, entry_name)
    if ast_err:
        return False, ast_err

    base_file = Path(baseline_path) if baseline_path else None
    sample_dict = dict(sample_payload) if isinstance(sample_payload, dict) else {}
    baseline_out, from_baseline = _run_baseline_probe_output(base_file, sample_dict)
    probe_art = baseline_out if baseline_out is not None else dict(sample_dict)
    probe_spec = dict(spec or {})

    # 执行 Smoke Call：遇 KeyError（缺特定输出字段且无 baseline.run）时填充探测浮点重试最多 4 次
    for _ in range(5):
        try:
            raw_res = eval_fn(copy.deepcopy(probe_art), copy.deepcopy(probe_spec))
            return _validate_hook_return_contract(raw_res, entry_name)
        except KeyError as ke:
            missing_k = ke.args[0] if ke.args else None
            if isinstance(missing_k, str) and missing_k not in probe_art and not from_baseline:
                probe_art[missing_k] = 1.0
                continue
            return False, f"Smoke Test 运行 {entry_name} 缺少字段 KeyError: {ke}"
        except TypeError as te:
            return False, f"Smoke Test 调用 {entry_name} 类型错误: {te}"
        except ValueError as ve:
            if not from_baseline and not sample_dict:
                # 无基准输出也无样例时，严谨钩子按契约对空输入 raise ValueError 属于预期；已过签名与 AST 字面量检查
                return True, "OK"
            return False, f"Smoke Test 调用 {entry_name} 在样例输出上抛出 ValueError: {ve}"
        except Exception as exc:
            if not from_baseline and not sample_dict:
                return False, f"Smoke Test 调用 {entry_name} 异常: {type(exc).__name__}: {exc}"
            return False, f"Smoke Test 在 baseline/样例输出上调用 {entry_name} 崩溃: {type(exc).__name__}: {exc}"
    return False, f"Smoke Test 重试填充后仍无法完成 {entry_name} 调用"


def _stage_b_evaluate(domain: str, spec: dict[str, Any], cand_out_path: Path) -> dict[str, Any]:
    """Stage B 独立计分子进程核心逻辑（屏蔽堆栈，仅返回脱敏摘要）。"""
    if not cand_out_path.exists() or not cand_out_path.is_file():
        return _fail_verdict("EXECUTION_ERROR", "MISSING_CANDIDATE_OUTPUT_FILE", "候选未写出 JSON 结果文件")

    try:
        raw_text = cand_out_path.read_text(encoding="utf-8")
        cand_data = json.loads(raw_text)
    except Exception:
        return _fail_verdict("INVALIDATED", "MALFORMED_CANDIDATE_JSON", "候选输出不是合法 JSON")

    if not isinstance(cand_data, dict):
        return _fail_verdict("INVALIDATED", "CANDIDATE_OUTPUT_NOT_DICT", "候选输出顶层必须为 JSON object")

    if not _check_all_finite(cand_data):
        return _fail_verdict("INVALIDATED", "NON_FINITE_VALUE", "检测到 NaN 或 Inf 非有限数值")

    required_keys = spec.get("required_keys", [])
    if isinstance(required_keys, list):
        missing = [k for k in required_keys if k not in cand_data]
        if missing:
            return _fail_verdict(
                "INVALIDATED",
                "MISSING_REQUIRED_KEYS",
                f"缺少必需输出字段 (count={len(missing)})",
                {"missing_keys_count": len(missing)},
            )

    expected_length = spec.get("expected_length")
    length_key = str(spec.get("length_key", "u_final"))
    if expected_length is not None:
        if isinstance(expected_length, bool) or not isinstance(expected_length, int) or expected_length < 0:
            return _fail_verdict("INVALIDATED", "INVALID_EXPECTED_LENGTH_SPEC")
        if length_key not in cand_data:
            return _fail_verdict("INVALIDATED", "MISSING_REQUIRED_KEYS", f"缺少长度字段 {length_key}", {"missing_length_key": length_key})
        arr = cand_data.get(length_key)
        if not isinstance(arr, list) or len(arr) != expected_length:
            return _fail_verdict("INVALIDATED", "OUTPUT_LENGTH_MISMATCH")

    non_const_key = spec.get("check_non_constant_key")
    if isinstance(non_const_key, str) and non_const_key.strip():
        if non_const_key not in cand_data:
            return _fail_verdict("INVALIDATED", "MISSING_REQUIRED_KEYS", raw_metrics={"missing_non_constant_key": non_const_key})
        arr = cand_data.get(non_const_key)
        if not isinstance(arr, list) or len(arr) <= 1:
            return _fail_verdict("INVALIDATED", "CONSTANT_DEGENERATE_OUTPUT", raw_metrics={"non_constant_key": non_const_key})
        distinct_vals = {
            round(float(x), 12)
            for x in arr
            if isinstance(x, (int, float)) and not isinstance(x, bool)
        }
        if len(distinct_vals) <= 1:
            return _fail_verdict("INVALIDATED", "CONSTANT_DEGENERATE_OUTPUT")

    if spec.get("hidden_force_scorer_error"):
        raise RuntimeError("SECRET_INTERNAL_STACK_DO_NOT_LEAK_42")

    hook_raw = str(spec.get("domain_hook_path") or "").strip()
    if hook_raw:
        if "\x00" in hook_raw or not os.path.isabs(hook_raw):
            return _fail_verdict("INVALIDATED", "INVALID_DOMAIN_HOOK_PATH")
        hook_file = Path(hook_raw)
        if not hook_file.is_file():
            return _fail_verdict("EXECUTION_ERROR", "MISSING_DOMAIN_HOOK_FILE")

        mod_spec = importlib.util.spec_from_file_location("_gw_domain_hook", str(hook_file))
        if mod_spec is None or mod_spec.loader is None:
            return _fail_verdict("EXECUTION_ERROR", "DOMAIN_HOOK_LOAD_FAILED")
        hook_mod = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(hook_mod)

        eval_cand_fn = getattr(hook_mod, "evaluate_candidate", None)
        eval_legacy_fn = getattr(hook_mod, "evaluate", None)
        if callable(eval_cand_fn):
            raw_res = eval_cand_fn(cand_data, spec)
            return _normalize_plugin_verdict(raw_res)
        if callable(eval_legacy_fn):
            raw_res = eval_legacy_fn(cand_data, spec)
            return _normalize_plugin_verdict(raw_res)
        return _fail_verdict("EXECUTION_ERROR", "DOMAIN_HOOK_MISSING_EVALUATE")

    domain_clean = (domain or "").strip().lower()
    if domain_clean in ("generic", ""):
        score = cand_data.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            score = None
        return _normalize_plugin_verdict(
            {
                "passed": True,
                "metrics": {"generic_keys_count": len(cand_data), **({"score": float(score)} if score is not None else {})},
                "details": "通用协议校验通过",
                "comparable_rank_score": float(score) if score is not None else None,
            }
        )

    return _fail_verdict("INVALIDATED", "MISSING_DOMAIN_HOOK", raw_metrics={"domain": domain_clean})


def _copy_branch_tools_into_sandbox(cand_src: Path, sandbox: Path, worktree_root: str = "") -> None:
    """若工作树下存在 tools/ 目录，安全复制其纯 .py 模块供候选在 Stage A 合法导入。"""
    candidates_tools: list[Path] = []
    if worktree_root:
        candidates_tools.append(Path(worktree_root) / "tools")
    elif cand_src.parent.name in ("src", "scripts", "solutions"):
        candidates_tools.append(cand_src.parent.parent / "tools")
    else:
        candidates_tools.append(cand_src.parent / "tools")

    for tools_dir in candidates_tools:
        if tools_dir.is_dir():
            dst_tools = sandbox / "tools"
            dst_tools.mkdir(parents=True, exist_ok=True)
            for item in tools_dir.rglob("*.py"):
                if item.name.startswith("_hidden") or "__pycache__" in item.parts:
                    continue
                rel = item.relative_to(tools_dir)
                target = dst_tools / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            break


def run_isolated_evaluation(
    candidate_path: str,
    domain: str,
    evaluator_spec: dict[str, Any],
    output_dir: str,
    timeout_sec: float = 30.0,
    stage_a_output_path: str = "",
    worktree_root: str = "",
) -> dict[str, Any]:
    """跨进程隔离执行候选并持久化 `stage_a_output.json`，随后启动独立 Stage B 子进程计分。"""
    cand_src = Path(candidate_path)
    if not cand_src.is_absolute() or not cand_src.is_file():
        res = _fail_verdict("EXECUTION_ERROR", "INVALID_CANDIDATE_PATH", "候选代码路径无效或不存在")
        res["stage_a_artifact_path"] = ""
        res["raw_output_path"] = ""
        return res

    effective_timeout = _resolve_timeout_sec(evaluator_spec, timeout_sec)
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    plugin_root = str(Path(__file__).resolve().parent.parent)

    with tempfile.TemporaryDirectory(prefix="gw_eval_") as tmp_str:
        sandbox = Path(tmp_str)
        sandbox_cand = sandbox / cand_src.name
        shutil.copy2(cand_src, sandbox_cand)
        _copy_branch_tools_into_sandbox(cand_src, sandbox, worktree_root=worktree_root)

        pub_input_path = sandbox / "public_input.json"
        pub_input_path.write_text(
            json.dumps(_sanitize_public_spec(evaluator_spec), ensure_ascii=False),
            encoding="utf-8",
        )
        cand_out_path = sandbox / "candidate_output.json"
        shim_path = sandbox / "_stage_a_runner.py"
        shim_path.write_text(_STAGE_A_SHIM, encoding="utf-8")

        clean_env = _build_clean_env(sandbox)

        try:
            proc_a = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(shim_path),
                    str(sandbox_cand),
                    str(pub_input_path),
                    str(cand_out_path),
                ],
                cwd=str(sandbox),
                env=clean_env,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            res = _fail_verdict("EXECUTION_ERROR", "STAGE_A_TIMEOUT", f"Stage A 执行超时 ({effective_timeout}s)")
            res["stage_a_artifact_path"] = ""
            res["raw_output_path"] = ""
            return res
        except Exception:
            res = _fail_verdict("EXECUTION_ERROR", "STAGE_A_LAUNCH_FAILED")
            res["stage_a_artifact_path"] = ""
            res["raw_output_path"] = ""
            return res

        if proc_a.returncode != 0:
            err_tail = (proc_a.stderr or "").strip()
            if len(err_tail) > 1500:
                err_tail = err_tail[-1500:]
            detail_msg = f"Stage A 进程异常退出 (exit_code={proc_a.returncode})"
            if err_tail:
                detail_msg += f"\n--- stderr_tail ---\n{err_tail}"
            res = _fail_verdict(
                "EXECUTION_ERROR",
                "STAGE_A_NONZERO_EXIT",
                detail_msg,
                {"exit_code": proc_a.returncode},
            )
            res["stage_a_artifact_path"] = ""
            res["raw_output_path"] = ""
            return res

        persisted_out = ""
        if cand_out_path.exists():
            if stage_a_output_path:
                dest_out = Path(stage_a_output_path)
            else:
                digest = sha256_bytes(cand_out_path.read_bytes())[:16]
                dest_out = out_root / f"stage_a_{digest}.json"
            dest_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cand_out_path, dest_out)
            persisted_out = str(dest_out)

        stage_b_dir = sandbox / "_stage_b"
        stage_b_dir.mkdir(parents=True, exist_ok=True)
        spec_path = stage_b_dir / "evaluator_spec.json"
        spec_path.write_text(json.dumps(evaluator_spec, ensure_ascii=False), encoding="utf-8")
        verdict_path = stage_b_dir / "stage_b_verdict.json"
        env_b = _build_clean_env(stage_b_dir)
        env_b["PYTHONPATH"] = plugin_root

        target_for_stage_b = Path(persisted_out) if persisted_out else cand_out_path
        try:
            proc_b = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--stage-b",
                    domain,
                    str(spec_path),
                    str(target_for_stage_b),
                    str(verdict_path),
                    plugin_root,
                ],
                cwd=str(stage_b_dir),
                env=env_b,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            res = _fail_verdict("EXECUTION_ERROR", "STAGE_B_TIMEOUT")
            res["stage_a_artifact_path"] = persisted_out
            res["raw_output_path"] = persisted_out
            return res
        except Exception:
            res = _fail_verdict("EXECUTION_ERROR", "STAGE_B_LAUNCH_FAILED")
            res["stage_a_artifact_path"] = persisted_out
            res["raw_output_path"] = persisted_out
            return res

        if proc_b.returncode != 0 or not verdict_path.exists():
            res = _fail_verdict("EXECUTION_ERROR", "SCORING_INTERNAL_ERROR")
            res["stage_a_artifact_path"] = persisted_out
            res["raw_output_path"] = persisted_out
            return res

        try:
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        except Exception:
            res = _fail_verdict("EXECUTION_ERROR", "SCORING_MALFORMED_VERDICT")
            res["stage_a_artifact_path"] = persisted_out
            res["raw_output_path"] = persisted_out
            return res

        verdict["stage_a_artifact_path"] = persisted_out
        verdict["raw_output_path"] = persisted_out
        return verdict


def run_stage_b_revaluation(
    domain: str,
    evaluator_spec: dict[str, Any],
    stage_a_output_path: str,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """在独立 Stage B 子进程对持久化 `stage_a_output.json` 执行免 Stage A 秒级重算。"""
    out_file = Path(stage_a_output_path) if stage_a_output_path else None
    if out_file is None or not out_file.is_file():
        return _fail_verdict("EXECUTION_ERROR", "MISSING_STAGE_A_ARTIFACT_FILE", "持久化 Stage A 产物文件不存在")

    effective_timeout = _resolve_timeout_sec(evaluator_spec, timeout_sec)
    plugin_root = str(Path(__file__).resolve().parent.parent)
    with tempfile.TemporaryDirectory(prefix="gw_reval_") as tmp_str:
        stage_b_dir = Path(tmp_str)
        spec_path = stage_b_dir / "evaluator_spec.json"
        spec_path.write_text(json.dumps(evaluator_spec, ensure_ascii=False), encoding="utf-8")
        verdict_path = stage_b_dir / "stage_b_verdict.json"
        env_b = _build_clean_env(stage_b_dir)
        env_b["PYTHONPATH"] = plugin_root

        try:
            proc_b = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--stage-b",
                    domain,
                    str(spec_path),
                    str(out_file),
                    str(verdict_path),
                    plugin_root,
                ],
                cwd=str(stage_b_dir),
                env=env_b,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            return _fail_verdict("EXECUTION_ERROR", "STAGE_B_TIMEOUT")
        except Exception:
            return _fail_verdict("EXECUTION_ERROR", "STAGE_B_LAUNCH_FAILED")

        if proc_b.returncode != 0 or not verdict_path.exists():
            return _fail_verdict("EXECUTION_ERROR", "SCORING_INTERNAL_ERROR")

        try:
            return json.loads(verdict_path.read_text(encoding="utf-8"))
        except Exception:
            return _fail_verdict("EXECUTION_ERROR", "SCORING_MALFORMED_VERDICT")


def _cli_stage_b() -> int:
    """独立子进程 Stage B CLI 入口（只写脱敏 verdict JSON，屏蔽异常回流）。"""
    if len(sys.argv) < 7 or sys.argv[1] != "--stage-b":
        return 2
    domain = sys.argv[2]
    spec_path = Path(sys.argv[3])
    cand_out_path = Path(sys.argv[4])
    verdict_path = Path(sys.argv[5])
    plugin_root = sys.argv[6]
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        result = _stage_b_evaluate(domain, spec, cand_out_path)
    except Exception:
        result = _fail_verdict("EXECUTION_ERROR", "SCORING_INTERNAL_ERROR")
    verdict_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_stage_b())
