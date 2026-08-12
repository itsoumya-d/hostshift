"""Real experiment: Gemini-driven interaction parity on reference specs.

This runs the ComputerUseOperator (backed by gemini-3.5-flash) against
simulated sessions for each host, measuring whether Gemini can complete
the same task across all platforms.

Usage:
    GEMINI_API_KEY=... python3 scripts/real_experiment.py
"""

import json
import os
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from hostshift.harness import ComputerUseOperator, AccessibilityTreeOperator, RunRecord, Store
from hostshift.render import ReferenceSession, open_session
from hostshift.oracle import grade, load_suite
from hostshift.metrics import host_lock_index

SPECS_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "tasks" / "reference_specs"
SUITE_PATH = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "tasks" / "suite_v1.jsonl")


def run_one_spec(spec_name: str, operator, hosts=("web", "swiftui", "compose", "tui")):
    """Run one reference spec across all hosts and return per-host results."""
    spec_path = SPECS_DIR / f"{spec_name}.json"
    spec = json.loads(spec_path.read_text())

    # Find the task for this spec
    tasks = load_suite(SUITE_PATH)
    task = None
    for t in tasks:
        if t.get("reference_spec", "").endswith(f"{spec_name}.json"):
            task = t
            break
    if task is None:
        # Use the first task in the matching category
        cat = spec_name.split("-")[0]
        for t in tasks:
            if cat in t.get("category", ""):
                task = t
                break

    if task is None:
        print(f"  SKIP {spec_name}: no matching task found")
        return {}

    goal = task.get("goal", "Complete the task")
    criteria = task.get("criteria", [])
    max_steps = task.get("max_steps", 18)

    results = {}
    for host in hosts:
        print(f"  {host}: ", end="", flush=True)
        try:
            session = open_session(spec, host, simulated=True)
            steps = operator.run(session, goal, max_steps)
            state = session.state()
            facts = session.ui_facts()

            # Grade against criteria
            met = 0
            for c in criteria:
                try:
                    path = c.get("path", "")
                    expected = c.get("value")
                    parts = path.split(".")
                    val = state
                    for p in parts:
                        if isinstance(val, dict):
                            val = val.get(p)
                        elif isinstance(val, list) and p.isdigit():
                            val = val[int(p)]
                        else:
                            val = None
                            break
                    if val == expected:
                        met += 1
                except Exception:
                    pass

            success = met == len(criteria) if criteria else True
            results[host] = {
                "success": success,
                "steps": steps,
                "criteria_met": met,
                "criteria_total": len(criteria),
            }
            status = "PASS" if success else f"FAIL ({met}/{len(criteria)})"
            print(f"{status} in {steps} steps")

            session.close()
        except Exception as e:
            results[host] = {"success": False, "steps": 0, "error": str(e)}
            print(f"ERROR: {e}")

    return results


def main():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    print("=" * 70)
    print("REAL EXPERIMENT: Gemini-driven Interaction Parity")
    print("=" * 70)
    print(f"Model: gemini-3.5-flash")
    print(f"Operator: ComputerUseOperator (API-backed)")
    print()

    # Test with 2 reference specs first (form-001 and list-001)
    specs = ["form-001", "list-001"]
    operator = ComputerUseOperator()

    all_results = {}
    for spec_name in specs:
        print(f"\n--- {spec_name} ---")
        results = run_one_spec(spec_name, operator)
        all_results[spec_name] = results

    # Also run the deterministic operator for comparison
    print(f"\n{'=' * 70}")
    print("ABLATION: Deterministic (a11y-scripted) operator")
    print("=" * 70)

    a11y_operator = AccessibilityTreeOperator()
    ablation_results = {}
    for spec_name in specs:
        print(f"\n--- {spec_name} ---")
        results = run_one_spec(spec_name, a11y_operator)
        ablation_results[spec_name] = results

    # Summary
    print(f"\n{'=' * 70}")
    print("RESULTS SUMMARY")
    print("=" * 70)

    print("\nGemini Computer-Use Operator:")
    for spec, hosts in all_results.items():
        successes = sum(1 for h in hosts.values() if h.get("success"))
        total = len(hosts)
        print(f"  {spec}: {successes}/{total} hosts succeeded")
        for host, r in hosts.items():
            s = "✓" if r.get("success") else "✗"
            print(f"    {host}: {s} ({r.get('steps', '?')} steps, {r.get('criteria_met', '?')}/{r.get('criteria_total', '?')} criteria)")

    print("\nDeterministic A11y Operator:")
    for spec, hosts in ablation_results.items():
        successes = sum(1 for h in hosts.values() if h.get("success"))
        total = len(hosts)
        print(f"  {spec}: {successes}/{total} hosts succeeded")
        for host, r in hosts.items():
            s = "✓" if r.get("success") else "✗"
            print(f"    {host}: {s} ({r.get('steps', '?')} steps)")

    # Save results
    output = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": "gemini-3.5-flash",
        "gemini_results": all_results,
        "ablation_results": ablation_results,
    }
    out_path = __import__("pathlib").Path(__file__).resolve().parents[1] / "runs" / "real_experiment.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
