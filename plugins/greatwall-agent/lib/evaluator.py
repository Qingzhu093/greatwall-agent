"""
AST Forensic Inspector, De-Jargonized Novelty Stripper & Cross-Process HMAC Isolated Evaluator.
务实严谨的代码审查与沙箱评测器：
1. ASTCodeInspector：
   - 扫描逃逸黑客调用 (ctypes/socket/urllib/inspect.stack) 与超大硬编码查表作弊；
   - 检测 MLE-STAR 式数据穿越泄漏 (切分前 fit_transform)；
   - 计算剥离常数与变量名后的 AST 结构改动率 (拦截只改数字 0% 结构改动的伪创新)；
   - 核对“方案说明与实际代码一致性” (防止像 Sakana AI Scientist 实测那样把搜索变量死写成 e=2)；
   - 四元数学算子剥皮查新与《教科书常识黑名单》比对。
2. IsolatedEvaluator：
   - 跨进程物理隔离运行 + 同构扰动测试 (Isomorphic Perturbation) + 一次性随机盐值 (run_nonce) HMAC-SHA256 签名成绩单。
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .sandbox import run_bounded_subprocess


DEFAULT_TEXTBOOK_COMMONSENSE: List[str] = [
    "mini-batch", "micro-batch", "microbatch", "gradient accumulation",
    "l1 regularization", "l2 regularization", "weight decay", "dropout",
    "cosine annealing", "reducelronplateau", "step decay", "adaptive learning rate",
    "hybrid matrix factorization", "svd", "standard pruning", "int8 quantization",
    "k-fold cross validation", "grid search", "random search", "standard scaler",
]


@dataclass
class ASTInspectionReport:
    passed: bool
    security_violations: List[str] = field(default_factory=list)
    leakage_warnings: List[str] = field(default_factory=list)
    structural_diff_ratio: float = 1.0
    is_superficial_tweak: bool = False
    claim_code_mismatch: List[str] = field(default_factory=list)
    novelty_classification: str = "SOLID_ENGINEERING"
    novelty_notes: str = ""


class ASTCodeInspector:
    """轻量零开销的 Python AST 静态审计器（毫秒级完成全套反作弊与真伪创新对账）"""

    FORBIDDEN_IMPORTS = {
        "ctypes", "winreg", "socket", "urllib", "requests", "http", "ftplib", "telnetlib", "webbrowser"
    }
    FORBIDDEN_CALLS = {
        "eval", "exec", "__subclasses__", "_getframe"
    }

    @classmethod
    def inspect_code(
        cls,
        candidate_code: str,
        parent_code: str = "",
        claimed_swept_variables: Optional[List[str]] = None,
        operator_description: str = "",
        commonsense_blacklist: Optional[List[str]] = None,
        max_lookup_table_size: int = 40,
    ) -> ASTInspectionReport:
        report = ASTInspectionReport(passed=True)
        try:
            tree = ast.parse(candidate_code)
        except SyntaxError as e:
            report.passed = False
            report.security_violations.append(f"SyntaxError: {e}")
            return report

        # 1. 安全逃逸与硬编码查表扫描
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_pkg = alias.name.split(".")[0]
                    if top_pkg in cls.FORBIDDEN_IMPORTS:
                        report.security_violations.append(f"禁止导入外部网络/底层逃逸库: '{alias.name}' (第 {node.lineno} 行)")
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_pkg = node.module.split(".")[0]
                if top_pkg in cls.FORBIDDEN_IMPORTS:
                    report.security_violations.append(f"禁止从受限模块导入: '{node.module}' (第 {node.lineno} 行)")
            elif isinstance(node, ast.Call):
                fn_name = ""
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fn_name = node.func.attr
                if fn_name in cls.FORBIDDEN_CALLS:
                    report.security_violations.append(f"禁止调用动态反射/执行函数: '{fn_name}()' (第 {node.lineno} 行)")
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if node.func.value.id == "inspect" and node.func.attr in ("stack", "currentframe"):
                        report.security_violations.append(f"禁止调用栈反射探测: 'inspect.{node.func.attr}()' (第 {node.lineno} 行)")
            elif isinstance(node, ast.Dict):
                if len(node.keys) > max_lookup_table_size and all(
                    isinstance(v, ast.Constant) for v in node.values if v is not None
                ):
                    report.security_violations.append(
                        f"检测到疑似硬编码查表作弊字典 (含 {len(node.keys)} 个常量键值对，第 {node.lineno} 行)"
                    )

        # 2. MLE-STAR 式数据防泄漏静态扫描 (检测是否在没有任何 Split/KFold 的情况下对全量特征做 fit_transform)
        has_cv_or_split = any(
            kw in candidate_code for kw in ("KFold", "Split", "train_test_split", "cross_val", "train_idx")
        )
        if "fit_transform(" in candidate_code and not has_cv_or_split:
            report.leakage_warnings.append(
                "检测到调用 `.fit_transform()` 但脚本中未出现训练/验证集切分 (KFold/Split)，存在全量统计量数据穿越泄漏风险！"
            )
        if re.search(r"concat\s*\(\s*\[\s*train.*test", candidate_code, re.IGNORECASE):
            report.leakage_warnings.append(
                "检测到疑似将训练集与测试集 `concat([train, test])` 合并预处理，严禁测试集特征统计量穿透！"
            )

        # 3. 计算剥离常数后的 AST 计算图结构改动率 (防止只改 lr=0.001 -> 0.0005 假装算法结构创新)
        if parent_code.strip():
            report.structural_diff_ratio = cls.compute_structural_diff_ratio(parent_code, candidate_code)
            if report.structural_diff_ratio < 0.015 and candidate_code.strip() != parent_code.strip():
                report.is_superficial_tweak = True

        # 4. 方案说明与代码 AST 一致性对账 (专治 Sakana 实测中宣称动态探索 e in {2,3,4,5} 实际写死 e = 2)
        if claimed_swept_variables:
            for var_name in claimed_swept_variables:
                if not cls._verify_variable_is_dynamic(tree, var_name):
                    report.claim_code_mismatch.append(
                        f"声明-代码对账失败：声称对控制变量 '{var_name}' 进行了动态探索/消融，但 AST 中该变量仅被赋值为单一静态常量或根本未参与循环控制流！"
                    )

        # 5. 四元组剥皮查新与《教科书常识黑名单》比对
        if operator_description.strip():
            classification, note = cls.evaluate_stripped_novelty(
                operator_description, commonsense_blacklist or DEFAULT_TEXTBOOK_COMMONSENSE
            )
            report.novelty_classification = classification
            report.novelty_notes = note
            if report.is_superficial_tweak and classification == "NOVEL_METHODOLOGY":
                report.novelty_classification = "HYPERPARAMETER_TWEAK"
                report.novelty_notes = "AST 结构改动率 < 1.5%（仅修改常数字面量），已自动从方法创新降级为超参微调。"

        if report.security_violations or report.claim_code_mismatch:
            report.passed = False

        return report

    @staticmethod
    def _skeletonize_ast(source_code: str) -> List[str]:
        """剥离所有注释、变量名与数值/字符串常量，仅保留 AST 语法结构与控制流/函数调用骨架"""
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []
        tokens: List[str] = []
        for node in ast.walk(tree):
            tname = type(node).__name__
            if isinstance(node, (ast.Constant, ast.Name)):
                tokens.append(tname)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    tokens.append(f"Call:{node.func.attr}")
                elif isinstance(node.func, ast.Name):
                    tokens.append(f"Call:{node.func.id}")
                else:
                    tokens.append("Call")
            else:
                tokens.append(tname)
        return tokens

    @classmethod
    def compute_structural_diff_ratio(cls, code_a: str, code_b: str) -> float:
        """计算两段代码的 AST 拓扑骨架差异率 [0.0, 1.0]（纯改数字或变量名时差异率为 0.0）"""
        skel_a = cls._skeletonize_ast(code_a)
        skel_b = cls._skeletonize_ast(code_b)
        if not skel_a and not skel_b:
            return 0.0
        if skel_a == skel_b:
            return 0.0

        # 统计骨架 token 频次曼哈顿相对距离 + 序列长度变化
        counts_a: Dict[str, int] = {}
        counts_b: Dict[str, int] = {}
        for t in skel_a:
            counts_a[t] = counts_a.get(t, 0) + 1
        for t in skel_b:
            counts_b[t] = counts_b.get(t, 0) + 1

        all_keys = set(counts_a) | set(counts_b)
        diff_sum = sum(abs(counts_a.get(k, 0) - counts_b.get(k, 0)) for k in all_keys)
        total_sum = max(1, len(skel_a) + len(skel_b))
        return round(min(1.0, diff_sum / total_sum), 4)

    @staticmethod
    def _verify_variable_is_dynamic(tree: ast.AST, var_name: str) -> bool:
        """检查变量 `var_name` 是否真实作为函数参数、循环迭代变量或列表/集合遍历被动态使用，而非死写成单一常数"""
        used_in_loop_or_param = False
        constant_assignments = 0
        non_constant_assignments = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.arg) and node.arg == var_name:
                used_in_loop_or_param = True
            elif isinstance(node, ast.For):
                if var_name in ast.unparse(node.target) or var_name in ast.unparse(node.iter):
                    used_in_loop_or_param = True
            elif isinstance(node, ast.comprehension):
                if var_name in ast.unparse(node.target) or var_name in ast.unparse(node.iter):
                    used_in_loop_or_param = True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        if isinstance(node.value, ast.Constant):
                            constant_assignments += 1
                        else:
                            non_constant_assignments += 1

        if used_in_loop_or_param or non_constant_assignments > 0:
            return True
        if constant_assignments > 1:
            return True
        return False

    @staticmethod
    def evaluate_stripped_novelty(operator_description: str, commonsense_blacklist: List[str]) -> Tuple[str, str]:
        """
        剥离花哨包装形容词，检查底层算子描述是否落入《教科书常识黑名单》：
        若命中微批处理、L1/L2 正则、标准剪枝等常识项，仅准标记为 `BASELINE_ENGINEERING`，严禁自封 `NOVEL_METHODOLOGY`。
        """
        buzzwords = [
            r"green-aware", r"eco-friendly", r"quantum-inspired", r"hyper-adaptive",
            r"multi-granular", r"synergistic", r"holistic", r"paradigm-shifting",
            r"全息", r"量子启发", r"超维自适应", r"生态感知", r"颠覆性",
        ]
        stripped = operator_description.lower()
        for bw in buzzwords:
            stripped = re.sub(bw, "", stripped, flags=re.IGNORECASE)

        matched_commonsense = [item for item in commonsense_blacklist if item.lower() in stripped]
        if matched_commonsense:
            return (
                "BASELINE_ENGINEERING",
                f"算子剥皮比对命中《教科书常识黑名单》({', '.join(matched_commonsense)})，归类为常规工程调优，禁止在报告中吹嘘为方法创新。",
            )
        return ("NOVEL_METHODOLOGY", "底层算子结构未命中教科书常识黑名单，准许作为方法学创新候选。")


# ============================================================================
# 2. 跨进程 HMAC 防伪隔离评测器 (IsolatedEvaluator)
# ============================================================================

class IsolatedEvaluator:
    """
    跨进程黑盒评测与四级分诊裁决器：
    1. 每次评测生成一次性随机盐值 `run_nonce`；
    2. 在受限子进程中执行候选脚本与评测基准（含常规 Frozen 集、Live 挑战集与同构旋转/重排扰动测试）；
    3. 使用内核专属密钥 `.kernel_vault/hmac_secret.key` 对 `(node_id, commit_hash, run_nonce, frozen_score, live_score)`
       计算 HMAC-SHA256 防伪签名，杜绝节点伪造静态 `metrics_receipt.json`；
    4. 执行四级分诊：`PARETO_PROMOTE` / `NICHE_CHAMPION` / `IN_PLACE_REPAIR` / `DEAD_END_ARCHIVE`。
    """

    def __init__(self, vault_dir: Path, shared_readonly_dir: Path) -> None:
        self.vault_dir = vault_dir.resolve()
        self.shared_readonly_dir = shared_readonly_dir.resolve()
        self.secret_file = self.vault_dir / "hmac_secret.key"
        self.eval_suite_dir = self.vault_dir / "evaluator_suite"
        self.eval_suite_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_secret()

    def _ensure_secret(self) -> bytes:
        if not self.secret_file.exists():
            self.secret_file.write_text(uuid.uuid4().hex + uuid.uuid4().hex, encoding="utf-8")
        return self.secret_file.read_text(encoding="utf-8").strip().encode("utf-8")

    def sign_receipt(self, node_id: str, commit_hash: str, run_nonce: str, frozen_score: float, live_score: float) -> str:
        secret = self._ensure_secret()
        payload = f"{node_id}|{commit_hash}|{run_nonce}|{frozen_score:.8f}|{live_score:.8f}".encode("utf-8")
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    def verify_receipt_signature(self, receipt: Dict[str, Any]) -> bool:
        try:
            expected = self.sign_receipt(
                node_id=str(receipt["node_id"]),
                commit_hash=str(receipt["commit_hash"]),
                run_nonce=str(receipt["run_nonce"]),
                frozen_score=float(receipt["scores"]["frozen_benchmark"]),
                live_score=float(receipt["scores"]["live_challenge"]),
            )
            return hmac.compare_digest(expected, str(receipt.get("hmac_sha256_signature", "")))
        except Exception:
            return False

    def evaluate_island(
        self,
        island_dir: Path,
        node_id: str,
        commit_hash: str,
        entry_script: str = "src/main.py",
        parent_code: str = "",
        anchor_s0_score: float = 0.0,
        higher_is_better: bool = True,
        timeout_sec: float = 120.0,
        claimed_swept_variables: Optional[List[str]] = None,
        operator_description: str = "",
    ) -> Dict[str, Any]:
        """
        执行端到端防作弊沙箱评测并生成签名收据 `legacy_out/metrics_receipt.json`
        """
        script_path = island_dir / entry_script
        if not script_path.exists():
            return {
                "status": "ERROR",
                "triage_tier": "IN_PLACE_REPAIR",
                "message": f"找不到入口脚本: {script_path}",
            }

        candidate_code = script_path.read_text(encoding="utf-8")

        # 1. AST 静态安全、防泄漏与结构改动对账
        ast_report = ASTCodeInspector.inspect_code(
            candidate_code=candidate_code,
            parent_code=parent_code,
            claimed_swept_variables=claimed_swept_variables,
            operator_description=operator_description,
        )
        if not ast_report.passed:
            return {
                "status": "REJECTED_BY_AST_AUDITOR",
                "triage_tier": "DEAD_END_ARCHIVE",
                "security_violations": ast_report.security_violations,
                "claim_code_mismatch": ast_report.claim_code_mismatch,
                "leakage_warnings": ast_report.leakage_warnings,
            }

        # 2. 跨进程隔离运行评测器
        run_nonce = str(uuid.uuid4())
        custom_eval_runner = self.eval_suite_dir / "evaluate_runner.py"

        if custom_eval_runner.exists():
            # 若任务配置了专属特权评测脚本，调用特权评测脚本并传入孤岛脚本路径与 nonce
            cmd = [
                sys.executable,
                str(custom_eval_runner),
                "--candidate-script",
                str(script_path.resolve()),
                "--island-dir",
                str(island_dir.resolve()),
                "--run-nonce",
                run_nonce,
            ]
        else:
            # 通用内置跨进程评测器：支持调用候选脚本的 evaluate() / solve() 或直接运行脚本提取 JSON 指标，并自动做同构打乱扰动测试
            harness_code = self._build_builtin_eval_harness(str(script_path.resolve()), run_nonce)
            cmd = [sys.executable, "-c", harness_code]

        sub_res = run_bounded_subprocess(
            cmd=cmd,
            cwd=island_dir,
            shared_readonly_dir=self.shared_readonly_dir,
            timeout_sec=timeout_sec,
            max_memory_mb=8192,
        )

        if sub_res.exit_code != 0:
            err_snippet = (sub_res.stderr or sub_res.stdout).strip()[-600:]
            return {
                "status": "RUNTIME_CRASH",
                "triage_tier": "IN_PLACE_REPAIR",
                "exit_code": sub_res.exit_code,
                "is_timeout": sub_res.is_timeout,
                "wall_time_sec": sub_res.wall_time_sec,
                "peak_memory_mb": sub_res.peak_memory_mb,
                "error_traceback": err_snippet,
                "recommended_action": "保留当前孤岛目录，根据 error_traceback 原地微创修复报错代码段（最多允许 3 步快速修补）。",
            }

        # 解析跨进程管道回传的客观指标行
        parsed_metrics = self._extract_metrics_from_stdout(sub_res.stdout)
        frozen_score = float(parsed_metrics.get("frozen_score", 0.0))
        live_score = float(parsed_metrics.get("live_score", frozen_score))
        iso_gap = float(parsed_metrics.get("isomorphic_perturbation_gap", 0.0))
        niche_score = float(parsed_metrics.get("niche_hard_cases_score", live_score))

        # 3. 同构变换扰动防背题检验
        if iso_gap > 0.05:
            return {
                "status": "REJECTED_INDEX_MEMORIZATION",
                "triage_tier": "DEAD_END_ARCHIVE",
                "isomorphic_perturbation_gap": iso_gap,
                "message": f"同构打乱/旋转算例前后得分差高达 {iso_gap:.4f} (> 0.05)，判定为针对固定算例顺序硬编码背答案！",
            }

        # 4. 四级分诊裁决 (4-Tier Triage)
        triage_tier = self._determine_triage_tier(
            frozen_score=frozen_score,
            niche_score=niche_score,
            anchor_s0_score=anchor_s0_score,
            higher_is_better=higher_is_better,
        )

        # 5. 签发带 HMAC-SHA256 签名的防伪成绩单收据
        sig = self.sign_receipt(node_id, commit_hash, run_nonce, frozen_score, live_score)
        receipt = {
            "receipt_id": f"RCPT-{int(time.time())}-{node_id}",
            "node_id": node_id,
            "commit_hash": commit_hash,
            "run_nonce": run_nonce,
            "hmac_sha256_signature": sig,
            "triage_tier": triage_tier,
            "scores": {
                "frozen_benchmark": round(frozen_score, 6),
                "live_challenge": round(live_score, 6),
                "isomorphic_perturbation_gap": round(iso_gap, 6),
                "niche_hard_cases_score": round(niche_score, 6),
            },
            "resource_profile": {
                "wall_time_sec": sub_res.wall_time_sec,
                "peak_memory_mb": sub_res.peak_memory_mb,
            },
            "ast_audit": {
                "structural_diff_ratio": ast_report.structural_diff_ratio,
                "is_superficial_tweak": ast_report.is_superficial_tweak,
                "data_leakage_clean": len(ast_report.leakage_warnings) == 0,
                "leakage_warnings": ast_report.leakage_warnings,
                "novelty_classification": ast_report.novelty_classification,
                "novelty_notes": ast_report.novelty_notes,
            },
            "timestamp": time.time(),
        }

        legacy_out = island_dir / "legacy_out"
        legacy_out.mkdir(parents=True, exist_ok=True)
        (legacy_out / "metrics_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        return receipt

    @staticmethod
    def _determine_triage_tier(
        frozen_score: float,
        niche_score: float,
        anchor_s0_score: float,
        higher_is_better: bool = True,
    ) -> str:
        if higher_is_better:
            if frozen_score > anchor_s0_score + 1e-6:
                return "PARETO_PROMOTE"
            if niche_score > anchor_s0_score * 1.05:
                return "NICHE_CHAMPION"
            return "DEAD_END_ARCHIVE"
        else:
            if anchor_s0_score > 0 and frozen_score < anchor_s0_score - 1e-6:
                return "PARETO_PROMOTE"
            if anchor_s0_score > 0 and niche_score < anchor_s0_score * 0.95:
                return "NICHE_CHAMPION"
            return "DEAD_END_ARCHIVE"

    @staticmethod
    def _build_builtin_eval_harness(script_abs_path: str, run_nonce: str) -> str:
        """
        构建跨进程内置评测驱动脚本：
        -若被测模块定义了 `evaluate()`，直接调用；
        -若被测模块定义了 `solve(inputs)`，自动用标准算例与打乱顺序后的同构算例分别测试，检验是否背题号；
        -输出带 `__GW_METRICS_JSON__:` 前缀的纯数据行。
        """
        return f"""
import importlib.util, json, sys, random

spec = importlib.util.spec_from_file_location("cand_mod", r"{script_abs_path}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

metrics = {{"frozen_score": 0.0, "live_score": 0.0, "isomorphic_perturbation_gap": 0.0, "niche_hard_cases_score": 0.0}}

if hasattr(mod, "evaluate") and callable(mod.evaluate):
    res = mod.evaluate()
    if isinstance(res, dict):
        metrics.update({{k: float(v) for k, v in res.items() if isinstance(v, (int, float))}})
    elif isinstance(res, (int, float)):
        metrics["frozen_score"] = float(res)
        metrics["live_score"] = float(res)
        metrics["niche_hard_cases_score"] = float(res)
elif hasattr(mod, "solve") and callable(mod.solve):
    base_inputs = [10, 25, -5, 42, 88, 13, 7, 99]
    out_normal = mod.solve(list(base_inputs))
    # 同构置换扰动测试：打乱输入顺序检验结果是否具备置换不变性/一致性
    shuffled = list(base_inputs)
    random.Random(42).shuffle(shuffled)
    out_iso = mod.solve(shuffled)
    if isinstance(out_normal, (int, float)) and isinstance(out_iso, (int, float)):
        denom = max(1.0, abs(float(out_normal)))
        gap = abs(float(out_normal) - float(out_iso)) / denom
        score = float(out_normal)
        metrics["frozen_score"] = score
        metrics["live_score"] = score
        metrics["niche_hard_cases_score"] = score
        metrics["isomorphic_perturbation_gap"] = gap

print("__GW_METRICS_JSON__:" + json.dumps(metrics))
"""

    @staticmethod
    def _extract_metrics_from_stdout(stdout: str) -> Dict[str, Any]:
        for line in reversed(stdout.splitlines()):
            if "__GW_METRICS_JSON__:" in line:
                raw = line.split("__GW_METRICS_JSON__:", 1)[1].strip()
                try:
                    return json.loads(raw)
                except Exception:
                    pass
        # 兜底尝试解析最后一行 JSON
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        return {"frozen_score": 0.0, "live_score": 0.0, "isomorphic_perturbation_gap": 0.0, "niche_hard_cases_score": 0.0}
