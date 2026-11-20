"""形式化证明领域适配器（Lean 4 / 结构化证明工件双轨核验）。

核心不变量（对齐《宿主机边界与文献源码对齐说明.md》§1.1 & §2.4）：
1. 锁定原命题规范化文本的 SHA-256 哈希，防止篡改命题偷换证明目标。
2. 显式区分 pure_kernel（仅允许标准三公理）与 external_certificate 模式，严禁 sorryAx。
3. 基于依赖图统计可达证明义务消除比例，不强制中间子目标数单调递减。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

STANDARD_KERNEL_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
_AXIOM_LINE_RE = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.IGNORECASE)
_DECL_NAME_RE = re.compile(r"^\s*(?:theorem|lemma|def)\s+([A-Za-z0-9_'.]+)", re.MULTILINE)


def normalize_theorem_text(text: str) -> str:
    """规范化命题空白后用于稳定计算 SHA-256。"""
    return " ".join((text or "").split())


def compute_theorem_sha256(text: str) -> str:
    """计算规范化命题文本的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(normalize_theorem_text(text).encode("utf-8")).hexdigest()


def _strip_lean_comments_and_strings(src: str) -> str:
    """剥离 Lean 单行注释 (-- ...)、嵌套块注释 (/- ... -/) 与字符串字面量，保留换行。"""
    out: list[str] = []
    i = 0
    n = len(src)
    block_depth = 0
    in_line_comment = False
    in_string = False

    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append("\n")
            i += 1
            continue

        if block_depth > 0:
            if ch == "/" and nxt == "-":
                block_depth += 1
                out.append("  ")
                i += 2
                continue
            if ch == "-" and nxt == "/":
                block_depth -= 1
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if in_string:
            if ch == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_string = False
                out.append(" ")
                i += 1
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            out.append("  ")
            i += 2
            continue
        if ch == "/" and nxt == "-":
            block_depth = 1
            out.append("  ")
            i += 2
            continue
        if ch == '"':
            in_string = True
            out.append(" ")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _resolve_target_decl_name(lean_content: str, target_name: str = "") -> str:
    name = target_name.strip()
    if name:
        return name
    stripped = _strip_lean_comments_and_strings(lean_content)
    matches = _DECL_NAME_RE.findall(stripped)
    return matches[-1] if matches else ""


def _ensure_print_axioms(lean_content: str, target_name: str = "") -> str:
    """剥离注释与字符串后，精确检查针对目标声明的 #print axioms；缺失时强制追加。"""
    stripped = _strip_lean_comments_and_strings(lean_content)
    name = _resolve_target_decl_name(lean_content, target_name=target_name)
    if not name:
        return lean_content
    pat = re.compile(rf"^\s*#print\s+axioms\s+{re.escape(name)}(?=\s|$)", re.MULTILINE)
    if pat.search(stripped):
        return lean_content
    return f"{lean_content.rstrip()}\n\n#print axioms {name}\n"


def _run_lean_axiom_probe(
    lean_content: str, target_name: str = "", timeout_sec: float = 15.0
) -> tuple[bool, list[str], str, bool]:
    """若本机存在 lean 二进制且启用 CLI 检查，则在独立临时文件执行公理审计。"""
    lean_bin = shutil.which("lean")
    if not lean_bin:
        return False, [], "LEAN_CLI_UNAVAILABLE", False

    resolved_name = _resolve_target_decl_name(lean_content, target_name=target_name)
    probe_src = _ensure_print_axioms(lean_content, target_name=resolved_name)
    with tempfile.TemporaryDirectory(prefix="gw_lean_") as tmp_dir:
        lean_file = Path(tmp_dir) / "probe.lean"
        lean_file.write_text(probe_src, encoding="utf-8")
        proc = subprocess.run(
            [lean_bin, str(lean_file)],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        axioms: list[str] = []
        for m in _AXIOM_LINE_RE.finditer(combined):
            for part in m.group(1).split(","):
                tok = part.strip()
                if tok:
                    axioms.append(tok)
        if resolved_name:
            dep_pat = re.compile(
                rf"'{re.escape(resolved_name)}'\s+depends on axioms:\s*\[([^\]]*)\]",
                re.IGNORECASE,
            )
            none_pat = re.compile(
                rf"'{re.escape(resolved_name)}'\s+does not depend on any axioms\b",
                re.IGNORECASE,
            )
            target_audited = bool(dep_pat.search(combined) or none_pat.search(combined))
        else:
            target_audited = bool(
                _AXIOM_LINE_RE.search(combined)
                or re.search(r"does not depend on any axioms\b", combined, re.IGNORECASE)
            )
        if proc.returncode != 0:
            return True, axioms, "LEAN_EXIT_NONZERO", target_audited
        return True, axioms, "OK", target_audited


def evaluate_formal_proof(
    candidate_output: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    """评估形式化证明候选产物。"""
    theorem_stmt = candidate_output.get("theorem_statement")
    if not isinstance(theorem_stmt, str) or not theorem_stmt.strip():
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "MISSING_THEOREM_STATEMENT",
        }

    actual_sha256 = compute_theorem_sha256(theorem_stmt)
    expected_sha256 = spec.get("expected_theorem_sha256")
    if not expected_sha256 and isinstance(spec.get("expected_theorem_statement"), str):
        expected_sha256 = compute_theorem_sha256(spec["expected_theorem_statement"])

    if expected_sha256 and actual_sha256 != str(expected_sha256).strip().lower():
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {
                "theorem_sha256_matched": False,
                "actual_theorem_sha256": actual_sha256,
            },
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "THEOREM_HASH_MISMATCH",
        }

    # 公理审计（双轨：若本机具备 lean 且显式开启 run_lean_cli，则联合 CLI 输出核验）
    raw_axioms = candidate_output.get("axioms_used")
    if not isinstance(raw_axioms, list) or not all(isinstance(a, str) for a in raw_axioms):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {"theorem_sha256_matched": True},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "INVALID_AXIOMS_LIST",
        }

    axioms_set = {a.strip() for a in raw_axioms if a.strip()}
    lean_cli_checked = False
    lean_cli_status = "SKIPPED"
    require_lean_cli = bool(spec.get("require_lean_cli", False))
    if spec.get("run_lean_cli", False) or require_lean_cli:
        lean_content = candidate_output.get("lean_file_content")
        if not isinstance(lean_content, str) or not lean_content.strip():
            if require_lean_cli:
                return {
                    "validity_state": "INVALIDATED",
                    "raw_metrics": {"theorem_sha256_matched": True},
                    "domain_invariants_passed": False,
                    "comparable_rank_score": None,
                    "failure_category": "MISSING_LEAN_FILE_CONTENT",
                }
        else:
            ran, cli_axioms, cli_status, target_audited = _run_lean_axiom_probe(
                lean_content,
                target_name=str(spec.get("lean_target_theorem", "")),
            )
            lean_cli_checked = ran
            lean_cli_status = cli_status
            if not ran and require_lean_cli:
                return {
                    "validity_state": "INVALIDATED",
                    "raw_metrics": {
                        "theorem_sha256_matched": True,
                        "lean_cli_checked": False,
                        "lean_cli_status": cli_status,
                    },
                    "domain_invariants_passed": False,
                    "comparable_rank_score": None,
                    "failure_category": "LEAN_CLI_REQUIRED_UNAVAILABLE",
                }
            if ran:
                if cli_status != "OK":
                    return {
                        "validity_state": "INVALIDATED",
                        "raw_metrics": {
                            "theorem_sha256_matched": True,
                            "lean_cli_checked": True,
                            "lean_cli_status": cli_status,
                        },
                        "domain_invariants_passed": False,
                        "comparable_rank_score": None,
                        "failure_category": "LEAN_CHECK_FAILED",
                    }
                if not target_audited:
                    return {
                        "validity_state": "INVALIDATED",
                        "raw_metrics": {
                            "theorem_sha256_matched": True,
                            "lean_cli_checked": True,
                            "lean_cli_status": cli_status,
                        },
                        "domain_invariants_passed": False,
                        "comparable_rank_score": None,
                        "failure_category": "MISSING_LEAN_AXIOM_AUDIT",
                    }
                axioms_set |= set(cli_axioms)

    # 拦截 sorryAx
    if any("sorry" in ax.lower() for ax in axioms_set):
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {
                "theorem_sha256_matched": True,
                "axioms_used": sorted(axioms_set),
                "lean_cli_checked": lean_cli_checked,
            },
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "SORRY_AXIOM_DETECTED",
        }

    axiom_mode = str(spec.get("axiom_mode", "pure_kernel")).strip()
    if axiom_mode == "pure_kernel":
        disallowed = axioms_set - STANDARD_KERNEL_AXIOMS
        if disallowed:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {
                    "theorem_sha256_matched": True,
                    "axiom_mode": axiom_mode,
                    "disallowed_axioms": sorted(disallowed),
                    "lean_cli_checked": lean_cli_checked,
                },
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "UNALLOWED_AXIOM_IN_PURE_KERNEL",
            }
    elif axiom_mode == "external_certificate":
        allowed_ext = {
            str(x).strip()
            for x in spec.get("allowed_external_axioms", [])
            if str(x).strip()
        }
        allowed_all = STANDARD_KERNEL_AXIOMS | allowed_ext
        disallowed = axioms_set - allowed_all
        if disallowed:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {
                    "theorem_sha256_matched": True,
                    "axiom_mode": axiom_mode,
                    "disallowed_axioms": sorted(disallowed),
                    "lean_cli_checked": lean_cli_checked,
                },
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "UNALLOWED_EXTERNAL_AXIOM",
            }
        if spec.get("require_certificate_manifest", False):
            certs = candidate_output.get("external_certificates")
            if not isinstance(certs, list) or not certs:
                return {
                    "validity_state": "INVALIDATED",
                    "raw_metrics": {
                        "theorem_sha256_matched": True,
                        "axiom_mode": axiom_mode,
                    },
                    "domain_invariants_passed": False,
                    "comparable_rank_score": None,
                    "failure_category": "MISSING_EXTERNAL_CERTIFICATE_MANIFEST",
                }
    else:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "UNKNOWN_AXIOM_MODE",
        }

    # 依赖图进度统计（支持非单调局部引理推进）
    obligations = candidate_output.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        return {
            "validity_state": "INVALIDATED",
            "raw_metrics": {"theorem_sha256_matched": True},
            "domain_invariants_passed": False,
            "comparable_rank_score": None,
            "failure_category": "MISSING_OBLIGATIONS_GRAPH",
        }

    ob_map: dict[str, dict[str, Any]] = {}
    for item in obligations:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "INVALID_OBLIGATION_ENTRY",
            }
        oid = item["id"].strip()
        if not oid or oid in ob_map:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"duplicate_id": oid},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "DUPLICATE_OBLIGATION_ID",
            }
        ob_map[oid] = item

    target_goal = spec.get("target_goal")
    if isinstance(target_goal, str) and target_goal.strip():
        goal_id = target_goal.strip()
        if goal_id not in ob_map:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"theorem_sha256_matched": True, "missing_target_goal": goal_id},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": "MISSING_TARGET_GOAL",
            }
        roots = [goal_id]
    else:
        roots = list(ob_map.keys())

    # 遍历可达子图并拦截悬空依赖与依赖环
    state: dict[str, int] = {}  # 0=未访问, 1=访问中, 2=已完成
    reachable: set[str] = set()

    def _dfs_check(nid: str) -> str | None:
        st = state.get(nid, 0)
        if st == 1:
            return "CYCLIC_OBLIGATION_DEP"
        if st == 2:
            return None
        state[nid] = 1
        reachable.add(nid)
        deps_raw = ob_map[nid].get("deps", [])
        if not isinstance(deps_raw, list):
            return "INVALID_OBLIGATION_ENTRY"
        for dep in deps_raw:
            if not isinstance(dep, str) or not dep.strip():
                return "DANGLING_OBLIGATION_DEP"
            dep_id = dep.strip()
            if dep_id not in ob_map:
                return "DANGLING_OBLIGATION_DEP"
            err = _dfs_check(dep_id)
            if err:
                return err
        state[nid] = 2
        return None

    for r_id in roots:
        graph_err = _dfs_check(r_id)
        if graph_err:
            return {
                "validity_state": "INVALIDATED",
                "raw_metrics": {"theorem_sha256_matched": True},
                "domain_invariants_passed": False,
                "comparable_rank_score": None,
                "failure_category": graph_err,
            }

    scoped_ids = sorted(reachable)

    # 递归确定有效已证节点：仅当自身 proved=True 且全部直接/传递依赖有效已证时才算真正已证
    eff_memo: dict[str, bool] = {}

    def _is_effectively_proved(nid: str) -> bool:
        if nid in eff_memo:
            return eff_memo[nid]
        if ob_map[nid].get("proved") is not True:
            eff_memo[nid] = False
            return False
        for dep in ob_map[nid].get("deps", []):
            if not _is_effectively_proved(str(dep).strip()):
                eff_memo[nid] = False
                return False
        eff_memo[nid] = True
        return True

    total_obligations = len(scoped_ids)
    proved_obligations = sum(1 for oid in scoped_ids if _is_effectively_proved(oid))
    verified_ratio = proved_obligations / total_obligations if total_obligations > 0 else 0.0
    all_proved = proved_obligations == total_obligations and total_obligations > 0

    return {
        "validity_state": "VALID",
        "raw_metrics": {
            "theorem_sha256_matched": True,
            "actual_theorem_sha256": actual_sha256,
            "axiom_mode": axiom_mode,
            "axioms_used": sorted(axioms_set),
            "lean_cli_checked": lean_cli_checked,
            "lean_cli_status": lean_cli_status,
            "total_obligations": total_obligations,
            "proved_obligations": proved_obligations,
            "verified_ratio": verified_ratio,
            "all_proved": all_proved,
        },
        "domain_invariants_passed": True,
        "comparable_rank_score": 1.0 if all_proved else verified_ratio,
        "failure_category": "",
    }


def evaluate(candidate_output: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """标准可插拔课题验证钩子入口。"""
    return evaluate_formal_proof(candidate_output, spec)
