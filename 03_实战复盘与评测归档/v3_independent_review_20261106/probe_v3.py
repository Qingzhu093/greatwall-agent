"""Read-only diagnostic runs against V3; writes evidence only in this review folder.

The masked-stop condition removes the simulator's omniscient completion signal.
It does not repair the policy, change the two-dog environment, or reproduce the
official single-dog simulator. Results are a sensitivity analysis, not competition scores.
"""
from pathlib import Path
import importlib
import json
import sys
import time

V3 = Path(r"D:\Documents\deepseek harness\实战v3")
sys.path.insert(0, str(V3))
from tools.radio_sandbox import RadioSandbox, BenchmarkSuite


class MaskedStopSandbox(RadioSandbox):
    @property
    def is_all_cleared(self):
        return False


def main():
    results = []
    started = time.perf_counter()
    for node in (4, 6):
        module = importlib.import_module(f"solution_tree.node_{node:02d}.solver")
        solver_type = getattr(module, f"Node{node:02d}Solver")
        for seed in [42, *range(10)]:
            for level in (1, 2, 3):
                for masked in (False, True):
                    scenario = getattr(BenchmarkSuite, f"create_level{level}")(seed)
                    sandbox = (MaskedStopSandbox if masked else RadioSandbox)(scenario, seed=seed)
                    solver = solver_type()
                    error = None
                    try:
                        getattr(solver, "solve_q4" if level == 3 else "solve_q3")(sandbox)
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                    cleared = sandbox.cleared_sources_count
                    results.append(dict(node=f"node_{node:02d}", seed=seed, level=level,
                        masked_stop=masked, error=error, cleared=cleared, total=sandbox.total_sources_count,
                        time=sandbox.global_time, avg_time=sandbox.global_time/cleared if cleared else None,
                        last_clear=sandbox.last_cleared_time,
                        actions=sum(len(d.trajectory) for d in sandbox.dogs.values())))
    out = Path(__file__).with_name("probe_results.json")
    out.write_text(json.dumps({"scope":"V3 two-dog simulator; not official results",
        "wall_seconds":time.perf_counter()-started,"runs":results}, ensure_ascii=False, indent=2), encoding="utf-8")
    for node in ("node_04", "node_06"):
        for level in (1, 2, 3):
            for masked in (False, True):
                rr=[r for r in results if r["node"]==node and r["level"]==level and r["masked_stop"]==masked]
                seed42=next(r for r in rr if r["seed"]==42)
                held=[r for r in rr if r["seed"]!=42]
                print(json.dumps({"node":node,"level":level,"masked_stop":masked,
                    "seed42_avg_time":round(seed42["avg_time"],2),"seed42_cleared":seed42["cleared"],
                    "other_10_mean_avg_time":round(sum(r["avg_time"] for r in held)/10,2),
                    "seed42_error":seed42["error"],
                    "other_10_errors":sum(r["error"] is not None for r in held),
                    "other_10_full_clear_runs":sum(r["cleared"]==r["total"] and r["error"] is None for r in held),
                    "other_10_min_clear_fraction":min(r["cleared"]/r["total"] for r in held)},ensure_ascii=False))
    print("Saved",out,"wall seconds",round(time.perf_counter()-started,2))


if __name__ == "__main__":
    main()
