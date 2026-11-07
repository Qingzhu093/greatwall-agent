"""
AFEVA End-to-End (E2E) Test Runner Engine.
Executes 4-Tier integration test scenarios, collects execution metrics,
renders ANSI matrix summaries, and ensures deterministic exit codes.

Usage:
  python e2e_tests/runner.py
  python e2e_tests/runner.py --tier 1
  python e2e_tests/runner.py --tier 2
  python e2e_tests/runner.py --tier 3
  python e2e_tests/runner.py --tier 4
  python e2e_tests/runner.py --all

Author: worker_m5_e2e (End-to-End Testing Architect)
Status: Production Ready
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from e2e_tests.test_e2e_scenarios import ALL_TIERS


@dataclass
class TestResult:
    tier: int
    name: str
    passed: bool
    duration_s: float
    error_info: Optional[str] = None


class E2ERunner:
    """4-Tier E2E 主执行引擎"""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.results: List[TestResult] = []

    def run_tier(self, tier_id: int) -> List[TestResult]:
        if tier_id not in ALL_TIERS:
            raise ValueError(f"Unknown tier: {tier_id}")

        tier_tests = ALL_TIERS[tier_id]
        tier_results: List[TestResult] = []

        print(f"\n>>> Executing Tier {tier_id} Scenarios ({len(tier_tests)} tests)...")
        for name, test_func in tier_tests:
            t_start = time.perf_counter()
            passed = False
            err_msg = None
            try:
                test_func()
                passed = True
            except AssertionError as ae:
                err_msg = f"AssertionError: {ae}"
                if self.verbose:
                    err_msg += "\n" + traceback.format_exc()
            except Exception as e:
                err_msg = f"Unexpected Error: {type(e).__name__}: {e}"
                if self.verbose:
                    err_msg += "\n" + traceback.format_exc()
            finally:
                t_end = time.perf_counter()
                duration = t_end - t_start

            result = TestResult(
                tier=tier_id,
                name=name,
                passed=passed,
                duration_s=duration,
                error_info=err_msg,
            )
            tier_results.append(result)
            self.results.append(result)

            status_str = "\033[92mPASS\033[0m" if passed else "\033[91mFAIL\033[0m"
            print(f"  [{status_str}] Tier {tier_id} :: {name:<65} ({duration * 1000:6.1f}ms)")
            if not passed and err_msg:
                print(f"         \033[91mError: {err_msg.splitlines()[0]}\033[0m")

        return tier_results

    def print_summary_matrix(self, total_elapsed: float) -> int:
        print("\n" + "=" * 90)
        print(" " * 26 + "AFEVA E2E TEST EXECUTION MATRIX")
        print("=" * 90)
        print(f" {'Tier':<8} | {'Description':<38} | {'Passed':<8} | {'Total':<8} | {'Rate':<8} | {'Time':<8}")
        print("-" * 90)

        tier_descriptions = {
            1: "Feature Coverage (F01~F10 Core)",
            2: "Boundary & Corner Cases",
            3: "Cross-Feature Combinations",
            4: "Real-World Application Scenarios",
        }

        all_passed = True
        total_tests = len(self.results)
        total_passed = 0

        for tier_id in sorted(ALL_TIERS.keys()):
            tier_res = [r for r in self.results if r.tier == tier_id]
            if not tier_res:
                continue
            passed_cnt = sum(1 for r in tier_res if r.passed)
            total_cnt = len(tier_res)
            total_passed += passed_cnt
            rate = (passed_cnt / total_cnt) * 100.0 if total_cnt > 0 else 0.0
            tier_time = sum(r.duration_s for r in tier_res)
            desc = tier_descriptions.get(tier_id, f"Tier {tier_id}")

            status_color = "\033[92m" if passed_cnt == total_cnt else "\033[91m"
            reset_color = "\033[0m"
            print(f" Tier {tier_id:<3} | {desc:<38} | {passed_cnt:<8} | {total_cnt:<8} | {status_color}{rate:6.1f}%{reset_color} | {tier_time:6.2f}s")
            if passed_cnt < total_cnt:
                all_passed = False

        print("-" * 90)
        overall_rate = (total_passed / total_tests) * 100.0 if total_tests > 0 else 0.0
        final_color = "\033[92m" if all_passed and total_tests > 0 else "\033[91m"
        final_verdict = "PASSED (100%)" if all_passed else "FAILED"

        print(f" TOTAL   | {'All Executed Tiers':<38} | {total_passed:<8} | {total_tests:<8} | {final_color}{overall_rate:6.1f}%{reset_color} | {total_elapsed:6.2f}s")
        print("=" * 90)
        print(f" Final Verdict: {final_color}{final_verdict}{reset_color} | Exit Code: {0 if all_passed else 1}")
        print("=" * 90 + "\n")

        return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="AFEVA E2E Test Suite Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run specific tier only")
    parser.add_argument("--all", action="store_true", default=False, help="Run all tiers (default)")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Verbose traceback output")

    args = parser.parse_args()
    runner = E2ERunner(verbose=args.verbose)

    t_global_start = time.perf_counter()

    if args.tier:
        runner.run_tier(args.tier)
    else:
        # Default or --all: run Tier 1 to Tier 4
        for t in [1, 2, 3, 4]:
            runner.run_tier(t)

    t_global_end = time.perf_counter()
    exit_code = runner.print_summary_matrix(t_global_end - t_global_start)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
