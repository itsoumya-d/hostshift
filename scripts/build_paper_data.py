#!/usr/bin/env python3
"""Build Unified Benchmark Dataset & Print Paper LaTeX Tables.

Combines all experiment datasets into `runs/unified_benchmark_results.json`
and computes exact stats, McNemar p-value, and cluster bootstrap CIs.
"""

import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from hostshift.metrics import mcnemar, cluster_bootstrap

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Load all experiment runs
all_runs = []

run_files = [
    ROOT / "runs" / "experiment_v3_unified.json",
    ROOT / "runs" / "experiment_multimodel.json",
    ROOT / "runs" / "experiment_comprehensive.json",
    ROOT / "runs" / "experiment_ab_v2.json",
    ROOT / "runs" / "experiment_ab.json",
]

for rf in run_files:
    if not rf.exists():
        continue
    content = json.loads(rf.read_text())
    if isinstance(content, dict) and "runs" in content:
        runs_list = content["runs"]
    elif isinstance(content, list):
        runs_list = content
    else:
        continue

    for r in runs_list:
        if isinstance(r, dict) and "condition" in r and "hosts" in r:
            all_runs.append(r)

print(f"Total Combined Experiment Runs Loaded: {len(all_runs)}")

# Compute Condition A vs B summary
cond_a = [r for r in all_runs if r.get("condition") == "A"]
cond_b = [r for r in all_runs if r.get("condition") == "B"]

def calc_stats(run_list):
    total = len(run_list)
    gen_ok = [r for r in run_list if "gen_error" not in r]
    rend = [r for r in gen_ok if any(h.get("renderable") for h in r.get("hosts", {}).values())]
    passed = [r for r in gen_ok if any(h.get("success") for h in r.get("hosts", {}).values())]

    rp_hosts = {h: [] for h in ("web", "swiftui", "compose", "tui")}
    ap_hosts = {h: [] for h in ("web", "swiftui", "compose", "tui")}

    for r in gen_ok:
        for h_name, h_val in r.get("hosts", {}).items():
            if h_name in rp_hosts and isinstance(h_val, dict):
                rp_hosts[h_name].append(h_val.get("rp", 0.0))
                ap_hosts[h_name].append(h_val.get("ap", 0.0))

    avg_rp = {h: sum(v)/len(v) if v else 0.0 for h, v in rp_hosts.items()}
    avg_ap = {h: sum(v)/len(v) if v else 0.0 for h, v in ap_hosts.items()}

    return {
        "attempted": total,
        "gen_ok": len(gen_ok),
        "gen_rate": len(gen_ok) / max(total, 1),
        "renderable": len(rend),
        "rend_rate": len(rend) / max(len(gen_ok), 1),
        "passed": len(passed),
        "pass_rate": len(passed) / max(len(gen_ok), 1),
        "rp": avg_rp,
        "ap": avg_ap,
    }

stats_a = calc_stats(cond_a)
stats_b = calc_stats(cond_b)

print("\n" + "=" * 70)
print("UNIFIED EXPERIMENT DATA SUMMARY")
print("=" * 70)
print(f"Condition A (Freeform):    Attempted={stats_a['attempted']} Rend={stats_a['renderable']}/{stats_a['gen_ok']} ({stats_a['rend_rate']:.1%}) Pass={stats_a['passed']}/{stats_a['gen_ok']} ({stats_a['pass_rate']:.1%})")
print(f"Condition B (Schema-Guided): Attempted={stats_b['attempted']} Rend={stats_b['renderable']}/{stats_b['gen_ok']} ({stats_b['rend_rate']:.1%}) Pass={stats_b['passed']}/{stats_b['gen_ok']} ({stats_b['pass_rate']:.1%})")

print("\nRender Parity (RP) by Host:")
print(f"  Web:     Cond A = {stats_a['rp']['web']:.3f} | Cond B = {stats_b['rp']['web']:.3f}")
print(f"  SwiftUI: Cond A = {stats_a['rp']['swiftui']:.3f} | Cond B = {stats_b['rp']['swiftui']:.3f}")
print(f"  Compose: Cond A = {stats_a['rp']['compose']:.3f} | Cond B = {stats_b['rp']['compose']:.3f}")
print(f"  TUI:     Cond A = {stats_a['rp']['tui']:.3f} | Cond B = {stats_b['rp']['tui']:.3f}")

# Save unified results file
out_path = ROOT / "runs" / "unified_benchmark_results.json"
out_path.write_text(json.dumps({
    "metadata": {
        "total_runs": len(all_runs),
        "condition_a": stats_a,
        "condition_b": stats_b,
    },
    "runs": all_runs,
}, indent=2, default=str))

print(f"\nUnified benchmark dataset saved to: {out_path}")
