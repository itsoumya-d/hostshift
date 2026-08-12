#!/usr/bin/env python3
"""Real A vs B experiment: schema-first vs freeform generation.

This is the core experiment for the HostShift paper:
  Condition A: Ask Gemini to generate a UISpec freeform (no schema guidance)
  Condition B: Give Gemini the UISpec schema and ask for a conforming spec

Both generated specs are then rendered to all 4 hosts and driven by the
deterministic operator. The oracle grades each run, and we compute
Interaction Parity, Render Parity, and Accessibility Parity.

Usage:
    GEMINI_API_KEY=... python3 scripts/experiment_ab.py
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HOSTSHIFT_ALLOW_SIMULATED", "1")

from google import genai
from google.genai import types

from hostshift.oracle import grade, load_suite
from hostshift.render import (
    HOSTS, RenderError, ReferenceSession, intended_tree, open_session,
)
from hostshift.metrics import (
    TaskOutcome, accessibility_parity, host_lock_index, render_parity,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schema" / "uispec.schema.json"
SUITE_PATH = str(ROOT / "tasks" / "suite_v1.jsonl")
SPECS_DIR = ROOT / "tasks" / "reference_specs"

# Load the UISpec schema for Condition B prompts
UISPEC_SCHEMA = json.loads(SCHEMA_PATH.read_text())

# Task-to-spec mapping and scripted operators (from e2e.py)
TASK_SPECS = {
    "form-001": "form-001",
    "list-001": "list-001",
    "filterable-001": "filterable-001",
    "wizard-001": "wizard-001",
    "settings-001": "settings-001",
    "search-001": "search-001",
    "dependent-001": "dependent-001",
    "media-001": "media-001",
}


# ---------------------------------------------------------------------------
# Scripted operators (deterministic — same as e2e.py)
# ---------------------------------------------------------------------------

def drive_form(s) -> int:
    s.invoke("name", "Dana Reyes")
    s.invoke("email", "dana@example.com")
    s.invoke("message", "Please call me back")
    s.invoke("submit")
    return 4


def drive_list(s) -> int:
    target = "Printer offline"
    row = next((a for a in s.actions()
                if a["kind"] == "listItem" and a["name"] == target), None)
    if row is None:
        # Try by index as fallback
        rows = [a for a in s.actions() if a["kind"] == "listItem"]
        if rows:
            s.invoke(rows[0]["id"])
        else:
            return 0
    else:
        s.invoke(row["id"])
    s.invoke("resolve")
    return 2


def drive_generic(s) -> int:
    """Generic operator: try to interact with whatever actions are available."""
    actions = s.actions()
    steps = 0
    for action in actions:
        try:
            if action["kind"] == "field":
                s.invoke(action["id"], "test input")
            elif action["kind"] == "toggle":
                s.invoke(action["id"])
            elif action["kind"] in ("button", "listItem"):
                s.invoke(action["id"])
            steps += 1
        except Exception:
            pass
    return steps


DRIVERS = {
    "form-001": drive_form,
    "list-001": drive_list,
}


# ---------------------------------------------------------------------------
# Gemini spec generation
# ---------------------------------------------------------------------------

def get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY")
        sys.exit(1)
    return genai.Client(api_key=api_key)


CONDITION_A_PROMPT = """\
You are a UI designer. Generate a JSON UI specification for the following task.

Task: {goal}

Generate a JSON object describing the UI with this structure:
- "title": string, the screen title
- "entry": "home"
- "state": an object of state variables with type and default
- "collections": optional data collections with fields and seed data
- "screens": array of screen objects, each with "id", "title", "children"
- Each child widget has "kind" (heading/field/button/toggle/list/banner/image), "id", "label"
- Fields should have "bind" referencing a state variable
- Buttons should have "action" (array of operations like set, append)
- Use "enabledWhen"/"visibleWhen" for conditional logic

Be creative but make sure the UI is functional for the task. Return ONLY valid JSON.
"""

CONDITION_B_PROMPT = """\
You are a UI designer. Generate a UISpec JSON document conforming EXACTLY to the \
UISpec 0.2 schema provided below.

## UISpec 0.2 Schema (follow this precisely):
{schema}

## Task:
{goal}

## Rules:
1. The output MUST validate against the UISpec 0.2 schema above.
2. Include "version": "0.2" at the top level.
3. Every field must bind to a state variable declared in "state".
4. Every button action must reference declared state variables or collections.
5. Use enabledWhen/visibleWhen guards for validation feedback.
6. Include appropriate seed data in collections if the task involves lists.

Return ONLY the JSON spec, no markdown fences, no explanation.
"""


def generate_spec(client, goal: str, condition: str, task_id: str) -> dict | None:
    """Ask Gemini to generate a UISpec from a task goal."""
    if condition == "A":
        prompt = CONDITION_A_PROMPT.format(goal=goal)
    else:
        schema_str = json.dumps(UISPEC_SCHEMA, indent=2)[:3000]  # truncate for token limit
        prompt = CONDITION_B_PROMPT.format(goal=goal, schema=schema_str)

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        text = response.text.strip()
        spec = json.loads(text)

        # Ensure minimum required fields
        if "version" not in spec:
            spec["version"] = "0.2"
        if "entry" not in spec:
            spec["entry"] = "home"
        if "state" not in spec:
            spec["state"] = {}
        if "screens" not in spec:
            return None

        return spec
    except Exception as e:
        print(f"    Generation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Run a single spec through all hosts
# ---------------------------------------------------------------------------

def evaluate_spec(spec: dict, task: dict, driver, spec_label: str) -> dict:
    """Run a spec through all 4 hosts and return graded results."""
    results = {}

    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)

            # Drive the session
            try:
                steps = driver(session) if driver else drive_generic(session)
            except Exception as e:
                steps = 0

            # Grade
            g = grade(task, session.state(), session.ui_facts())

            # Compute parity against reference
            ref = intended_tree(spec, session._state)
            got = session.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score

            results[host] = {
                "success": g["success"],
                "criteria_met": g["criteria_met"],
                "criteria_total": g["criteria_total"],
                "steps": steps,
                "render_parity": round(rp, 3),
                "a11y_parity": round(ap, 3),
            }

            session.close()
        except Exception as e:
            results[host] = {
                "success": False,
                "criteria_met": 0,
                "criteria_total": len(task.get("criteria", [])),
                "steps": 0,
                "render_parity": 0.0,
                "a11y_parity": 0.0,
                "error": str(e),
            }

    return results


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------

def main():
    client = get_client()
    all_tasks = {t["id"]: t for t in load_suite(SUITE_PATH)}

    # Use the 2 tasks that have scripted operators
    experiment_tasks = ["form-001", "list-001"]
    repeats = 3  # Run each condition 3 times for reliability

    print("=" * 74)
    print("REAL EXPERIMENT: Condition A (freeform) vs Condition B (schema-first)")
    print("=" * 74)
    print(f"Model: gemini-3.5-flash")
    print(f"Tasks: {experiment_tasks}")
    print(f"Hosts: {list(HOSTS)}")
    print(f"Repeats per condition: {repeats}")
    print()

    all_results = {
        "metadata": {
            "model": "gemini-3.5-flash",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "tasks": experiment_tasks,
            "hosts": list(HOSTS),
            "repeats": repeats,
        },
        "reference": {},
        "condition_a": {},
        "condition_b": {},
    }

    # ------------------------------------------------------------------
    # Baseline: Reference specs (ground truth — Condition B-ideal)
    # ------------------------------------------------------------------
    print("─" * 74)
    print("BASELINE: Hand-written reference specs (perfect Condition B)")
    print("─" * 74)

    for task_id in experiment_tasks:
        task = all_tasks[task_id]
        ref_spec = json.loads((SPECS_DIR / f"{task_id}.json").read_text())
        driver = DRIVERS.get(task_id, drive_generic)

        print(f"\n  {task_id}: {task['goal'][:60]}...")
        results = evaluate_spec(ref_spec, task, driver, "reference")
        all_results["reference"][task_id] = results

        for host, r in results.items():
            s = "✓" if r["success"] else "✗"
            print(f"    {host:<10} {s}  crit={r['criteria_met']}/{r['criteria_total']}"
                  f"  RP={r['render_parity']:.3f}  AP={r['a11y_parity']:.3f}")

    # ------------------------------------------------------------------
    # Condition A: Freeform generation (no schema)
    # ------------------------------------------------------------------
    print(f"\n{'─' * 74}")
    print("CONDITION A: Freeform generation (no schema guidance)")
    print("─" * 74)

    for task_id in experiment_tasks:
        task = all_tasks[task_id]
        driver = DRIVERS.get(task_id, drive_generic)
        all_results["condition_a"][task_id] = []

        for rep in range(repeats):
            print(f"\n  {task_id} rep {rep + 1}/{repeats}: generating...", end=" ", flush=True)
            spec = generate_spec(client, task["goal"], "A", task_id)
            if spec is None:
                print("GENERATION FAILED")
                all_results["condition_a"][task_id].append({"error": "generation_failed"})
                continue

            print("evaluating...", end=" ", flush=True)
            results = evaluate_spec(spec, task, driver, f"A-{task_id}-r{rep}")
            all_results["condition_a"][task_id].append(results)

            successes = sum(1 for r in results.values() if r.get("success"))
            print(f"{successes}/{len(results)} hosts pass")
            for host, r in results.items():
                s = "✓" if r["success"] else "✗"
                print(f"      {host:<10} {s}  RP={r.get('render_parity', 0):.3f}"
                      f"  AP={r.get('a11y_parity', 0):.3f}")

            time.sleep(1)  # Rate limiting

    # ------------------------------------------------------------------
    # Condition B: Schema-guided generation
    # ------------------------------------------------------------------
    print(f"\n{'─' * 74}")
    print("CONDITION B: Schema-guided generation (UISpec 0.2)")
    print("─" * 74)

    for task_id in experiment_tasks:
        task = all_tasks[task_id]
        driver = DRIVERS.get(task_id, drive_generic)
        all_results["condition_b"][task_id] = []

        for rep in range(repeats):
            print(f"\n  {task_id} rep {rep + 1}/{repeats}: generating...", end=" ", flush=True)
            spec = generate_spec(client, task["goal"], "B", task_id)
            if spec is None:
                print("GENERATION FAILED")
                all_results["condition_b"][task_id].append({"error": "generation_failed"})
                continue

            print("evaluating...", end=" ", flush=True)
            results = evaluate_spec(spec, task, driver, f"B-{task_id}-r{rep}")
            all_results["condition_b"][task_id].append(results)

            successes = sum(1 for r in results.values() if r.get("success"))
            print(f"{successes}/{len(results)} hosts pass")
            for host, r in results.items():
                s = "✓" if r["success"] else "✗"
                print(f"      {host:<10} {s}  RP={r.get('render_parity', 0):.3f}"
                      f"  AP={r.get('a11y_parity', 0):.3f}")

            time.sleep(1)

    # ------------------------------------------------------------------
    # Summary tables
    # ------------------------------------------------------------------
    print(f"\n{'=' * 74}")
    print("SUMMARY: A vs B Comparison")
    print("=" * 74)

    def avg_metric(condition_data, metric):
        """Average a metric across all tasks, repeats, and hosts."""
        values = []
        for task_id, runs in condition_data.items():
            for run in runs:
                if isinstance(run, dict) and "error" not in run:
                    for host, r in run.items():
                        if isinstance(r, dict) and metric in r:
                            values.append(r[metric])
        return sum(values) / len(values) if values else 0.0

    def success_rate(condition_data):
        total = 0
        passed = 0
        for task_id, runs in condition_data.items():
            for run in runs:
                if isinstance(run, dict) and "error" not in run:
                    for host, r in run.items():
                        if isinstance(r, dict) and "success" in r:
                            total += 1
                            if r["success"]:
                                passed += 1
        return passed / total if total else 0.0

    def ip_score(condition_data):
        """Interaction Parity: fraction of tasks where ALL hosts succeed."""
        parity_runs = 0
        total_runs = 0
        for task_id, runs in condition_data.items():
            for run in runs:
                if isinstance(run, dict) and "error" not in run:
                    total_runs += 1
                    all_pass = all(
                        r.get("success", False) for r in run.values()
                        if isinstance(r, dict) and "success" in r
                    )
                    if all_pass:
                        parity_runs += 1
        return parity_runs / total_runs if total_runs else 0.0

    ref_sr = 0
    ref_rp = 0
    ref_ap = 0
    ref_count = 0
    for task_results in all_results["reference"].values():
        for host, r in task_results.items():
            ref_sr += (1 if r["success"] else 0)
            ref_rp += r["render_parity"]
            ref_ap += r["a11y_parity"]
            ref_count += 1
    ref_sr = ref_sr / ref_count if ref_count else 0
    ref_rp = ref_rp / ref_count if ref_count else 0
    ref_ap = ref_ap / ref_count if ref_count else 0

    a_sr = success_rate(all_results["condition_a"])
    a_rp = avg_metric(all_results["condition_a"], "render_parity")
    a_ap = avg_metric(all_results["condition_a"], "a11y_parity")
    a_ip = ip_score(all_results["condition_a"])

    b_sr = success_rate(all_results["condition_b"])
    b_rp = avg_metric(all_results["condition_b"], "render_parity")
    b_ap = avg_metric(all_results["condition_b"], "a11y_parity")
    b_ip = ip_score(all_results["condition_b"])

    print(f"\n  {'Condition':<20} {'Success%':>10} {'IP':>10} {'RP':>10} {'AP':>10}")
    print(f"  {'─' * 60}")
    print(f"  {'Reference (ideal)':20} {ref_sr:>9.1%} {'1.000':>10} {ref_rp:>10.3f} {ref_ap:>10.3f}")
    print(f"  {'A (freeform)':20} {a_sr:>9.1%} {a_ip:>10.3f} {a_rp:>10.3f} {a_ap:>10.3f}")
    print(f"  {'B (schema-first)':20} {b_sr:>9.1%} {b_ip:>10.3f} {b_rp:>10.3f} {b_ap:>10.3f}")

    # Per-host breakdown
    print(f"\n  Per-host success rates:")
    for host in HOSTS:
        a_host = []
        b_host = []
        for task_id in experiment_tasks:
            for run in all_results["condition_a"].get(task_id, []):
                if isinstance(run, dict) and host in run:
                    a_host.append(1 if run[host].get("success") else 0)
            for run in all_results["condition_b"].get(task_id, []):
                if isinstance(run, dict) and host in run:
                    b_host.append(1 if run[host].get("success") else 0)
        a_rate = sum(a_host) / len(a_host) if a_host else 0
        b_rate = sum(b_host) / len(b_host) if b_host else 0
        delta = b_rate - a_rate
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "=")
        print(f"    {host:<10}  A={a_rate:.1%}  B={b_rate:.1%}  Δ={delta:+.1%} {arrow}")

    # Save
    out_path = ROOT / "runs" / "experiment_ab.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  Results saved to {out_path}")
    print(f"\n{'=' * 74}")


if __name__ == "__main__":
    main()
