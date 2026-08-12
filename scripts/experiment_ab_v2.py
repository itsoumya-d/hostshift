#!/usr/bin/env python3
"""Real A vs B experiment v2 — with adaptive operator and rate limiting.

Fixes from v1:
  - Rate limiting: 15s between API calls (free tier = 5 RPM)
  - Adaptive operator: discovers field IDs from the generated spec
  - Structural grading: checks if spec has right state/collections structure
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
UISPEC_SCHEMA = json.loads(SCHEMA_PATH.read_text())

API_DELAY = 15  # seconds between API calls (free tier: 5 RPM)


# ---------------------------------------------------------------------------
# Adaptive operator — discovers fields from spec, not hardcoded
# ---------------------------------------------------------------------------

def adaptive_driver(s, task: dict, spec: dict) -> int:
    """Drive a session by discovering actions from the spec, not hardcoding.

    For form tasks:  find all fields → fill them → click submit button
    For list tasks:  find list items → click first matching → click action button
    """
    actions = s.actions()
    steps = 0

    # Identify task type from the goal
    goal = task.get("goal", "").lower()

    # Collect field and button actions
    fields = [a for a in actions if a["kind"] == "field"]
    buttons = [a for a in actions if a["kind"] == "button"]
    toggles = [a for a in actions if a["kind"] == "toggle"]
    list_items = [a for a in actions if a["kind"] == "listItem"]

    if "submit" in goal or "contact" in goal or "form" in goal or "fill" in goal:
        # Form-like task: fill fields with values derived from goal
        values = _extract_form_values(task)
        for field in fields:
            field_label = field.get("name", "").lower()
            field_id = field["id"]
            # Match field to a value
            value = _match_field_value(field_label, field_id, values)
            if value:
                try:
                    s.invoke(field_id, value)
                    steps += 1
                except Exception:
                    pass

        # Click submit
        for btn in buttons:
            btn_label = (btn.get("name", "") or btn.get("id", "")).lower()
            if any(w in btn_label for w in ("submit", "send", "save", "confirm", "add")):
                try:
                    s.invoke(btn["id"])
                    steps += 1
                except Exception:
                    pass
                break

    elif "ticket" in goal or "open" in goal or "select" in goal or "mark" in goal:
        # List task: click matching item, then action button
        target_name = _extract_target_name(task)
        clicked = False
        for item in list_items:
            if target_name and target_name.lower() in (item.get("name", "")).lower():
                try:
                    s.invoke(item["id"])
                    steps += 1
                    clicked = True
                except Exception:
                    pass
                break
        if not clicked and list_items:
            try:
                s.invoke(list_items[0]["id"])
                steps += 1
            except Exception:
                pass

        # Refresh actions after navigation
        actions = s.actions()
        buttons = [a for a in actions if a["kind"] == "button"]
        for btn in buttons:
            btn_label = (btn.get("name", "") or btn.get("id", "")).lower()
            if any(w in btn_label for w in ("resolve", "done", "close", "mark", "complete")):
                try:
                    s.invoke(btn["id"])
                    steps += 1
                except Exception:
                    pass
                break

    else:
        # Generic: try all interactive elements
        for action in actions:
            try:
                if action["kind"] == "field":
                    s.invoke(action["id"], "test")
                elif action["kind"] in ("button", "toggle", "listItem"):
                    s.invoke(action["id"])
                steps += 1
            except Exception:
                pass

    return steps


def _extract_form_values(task: dict) -> dict:
    """Extract expected form values from the task goal and criteria."""
    values = {}
    goal = task.get("goal", "")

    # Parse from criteria
    for c in task.get("criteria", []):
        path = c.get("path", "")
        val = c.get("value")
        if isinstance(val, str) and val:
            key = path.split(".")[-1] if "." in path else path
            values[key] = val

    # Parse common patterns from goal
    import re
    email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', goal)
    if email_match:
        values["email"] = email_match.group()

    # Extract quoted strings
    quoted = re.findall(r"'([^']+)'", goal)
    for q in quoted:
        if "@" not in q:
            values.setdefault("message", q)

    # Extract names (e.g., "for Dana Reyes")
    name_match = re.search(r'for\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', goal)
    if name_match:
        values["name"] = name_match.group(1)

    return values


def _match_field_value(field_label: str, field_id: str, values: dict) -> str | None:
    """Match a field (by label or id) to a value from the extracted values."""
    label_lower = field_label.lower()
    id_lower = field_id.lower()

    for key, val in values.items():
        key_lower = key.lower()
        if (key_lower in label_lower or key_lower in id_lower or
            label_lower in key_lower or id_lower in key_lower):
            return val

    # Fuzzy: name fields
    if any(w in label_lower or w in id_lower for w in ("name", "full", "first", "last")):
        return values.get("name", "Test User")

    # Email fields
    if any(w in label_lower or w in id_lower for w in ("email", "mail")):
        return values.get("email", "test@example.com")

    # Message/body fields
    if any(w in label_lower or w in id_lower for w in ("message", "body", "note", "text", "comment")):
        return values.get("message", "Test message")

    return "test input"


def _extract_target_name(task: dict) -> str:
    """Extract target item name from goal, e.g., 'Printer offline' from the goal."""
    import re
    match = re.search(r"titled\s+'([^']+)'", task.get("goal", ""))
    if match:
        return match.group(1)
    match = re.search(r"'([^']+)'", task.get("goal", ""))
    if match:
        return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# Gemini spec generation (with rate limiting)
# ---------------------------------------------------------------------------

def get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY")
        sys.exit(1)
    return genai.Client(api_key=api_key)


CONDITION_A_PROMPT = """\
You are a UI designer. Create a JSON spec for a user interface.

Task: {goal}

Return a JSON object with this structure:
{{
  "title": "Screen Title",
  "entry": "home",
  "state": {{ "varName": {{ "type": "string", "default": "" }} }},
  "collections": {{ "items": {{ "fields": {{ "f1": {{"type":"string"}} }}, "seed": [{{...}}] }} }},
  "screens": [
    {{
      "id": "home",
      "title": "Screen Title",
      "children": [
        {{ "kind": "field", "id": "myField", "label": "Label", "bind": "varName" }},
        {{ "kind": "button", "id": "submit", "label": "Submit",
          "action": [{{ "op": "set", "target": "varName", "value": true }}] }}
      ]
    }}
  ]
}}

Widget kinds: heading, field, button, toggle, list, banner, image.
Fields must have "bind" linking to a state variable.
Buttons must have "action" with operations: set, append, navigate.
Include "enabledWhen" guards for validation.
Return ONLY valid JSON, no markdown.
"""

CONDITION_B_PROMPT = """\
Generate a UISpec 0.2 JSON document for this task.

Task: {goal}

UISpec 0.2 rules:
1. Top level: version, title, entry, state, collections (optional), screens
2. "state" declares all variables: {{ "varName": {{ "type": "string"|"boolean"|"number", "default": value }} }}
3. "collections" for lists: {{ "collName": {{ "fields": {{...}}, "seed": [{{...}}] }} }}
4. Each screen: {{ "id": "screenId", "title": "...", "children": [...] }}
5. Widget kinds: heading, field, button, toggle, list, banner, image
6. field: {{ "kind": "field", "id": "x", "label": "L", "bind": "stateVar" }}
7. button: {{ "kind": "button", "id": "x", "label": "L", "action": [...] }}
   Actions: {{ "op": "set", "target": "stateVar", "value": val }}
            {{ "op": "append", "target": "collection", "value": {{...}} }}
            {{ "op": "navigate", "target": "screenId" }}
8. toggle: {{ "kind": "toggle", "id": "x", "label": "L", "bind": "stateVar" }}
9. list: {{ "kind": "list", "id": "x", "source": "collName", "onTap": [...] }}
10. "enabledWhen"/"visibleWhen": {{ "op": "nonempty"|"truthy"|"eq"|"and"|"not", "left": "stateVar" }}
11. Use "$state.varName" in action values to reference current state
12. MUST include "version": "0.2"

Return ONLY the JSON.
"""


_last_call_time = 0.0

def rate_limited_generate(client, prompt: str) -> dict | None:
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < API_DELAY:
        wait = API_DELAY - elapsed
        print(f"(wait {wait:.0f}s)...", end=" ", flush=True)
        time.sleep(wait)

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        _last_call_time = time.time()
        text = response.text.strip()
        spec = json.loads(text)

        # Ensure minimum fields
        spec.setdefault("version", "0.2")
        spec.setdefault("entry", "home")
        spec.setdefault("state", {})
        if "screens" not in spec:
            return None
        if "collections" not in spec:
            spec["collections"] = {}

        return spec
    except Exception as e:
        _last_call_time = time.time()
        print(f"ERR:{e.__class__.__name__}", end=" ", flush=True)
        return None


# ---------------------------------------------------------------------------
# Evaluate a spec across all hosts
# ---------------------------------------------------------------------------

def evaluate_spec(spec: dict, task: dict, host_list=HOSTS) -> dict:
    results = {}
    for host in host_list:
        try:
            session = open_session(spec, host, simulated=True)
            steps = adaptive_driver(session, task, spec)

            g = grade(task, session.state(), session.ui_facts())
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
                "renderable": True,
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
                "renderable": False,
                "error": str(e)[:80],
            }
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    client = get_client()
    all_tasks = {t["id"]: t for t in load_suite(SUITE_PATH)}
    experiment_tasks = ["form-001", "list-001"]
    repeats = 3

    print("=" * 74)
    print("EXPERIMENT v2: Condition A vs B (adaptive operator, rate-limited)")
    print("=" * 74)
    print(f"Model: gemini-3.5-flash | Delay: {API_DELAY}s | Repeats: {repeats}")
    print()

    results = {
        "metadata": {
            "model": "gemini-3.5-flash",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "api_delay": API_DELAY,
        },
        "reference": {},
        "condition_a": {},
        "condition_b": {},
    }

    # ── Baseline ──
    print("─" * 74)
    print("BASELINE: Reference specs")
    print("─" * 74)

    for tid in experiment_tasks:
        task = all_tasks[tid]
        ref_spec = json.loads((SPECS_DIR / f"{tid}.json").read_text())
        print(f"\n  {tid}:")
        r = evaluate_spec(ref_spec, task)
        results["reference"][tid] = r
        for host, hr in r.items():
            s = "✓" if hr["success"] else "✗"
            print(f"    {host:<10} {s}  crit={hr['criteria_met']}/{hr['criteria_total']}"
                  f"  RP={hr['render_parity']:.3f}  AP={hr['a11y_parity']:.3f}")

    # ── Condition A ──
    print(f"\n{'─' * 74}")
    print("CONDITION A: Freeform generation")
    print("─" * 74)

    for tid in experiment_tasks:
        task = all_tasks[tid]
        results["condition_a"][tid] = []
        for rep in range(repeats):
            print(f"\n  {tid} [{rep+1}/{repeats}]: ", end="", flush=True)
            prompt = CONDITION_A_PROMPT.format(goal=task["goal"])
            spec = rate_limited_generate(client, prompt)
            if not spec:
                print("FAIL(gen)")
                results["condition_a"][tid].append({"gen_error": True})
                continue

            print("eval...", end=" ", flush=True)
            r = evaluate_spec(spec, task)
            results["condition_a"][tid].append(r)

            n_render = sum(1 for h in r.values() if h.get("renderable"))
            n_pass = sum(1 for h in r.values() if h.get("success"))
            print(f"render={n_render}/4 pass={n_pass}/4")
            for host, hr in r.items():
                s = "✓" if hr["success"] else ("◐" if hr.get("renderable") else "✗")
                print(f"      {host:<10} {s}  RP={hr['render_parity']:.3f}  AP={hr['a11y_parity']:.3f}"
                      + (f"  err={hr['error']}" if hr.get("error") else ""))

    # ── Condition B ──
    print(f"\n{'─' * 74}")
    print("CONDITION B: Schema-guided generation (UISpec 0.2)")
    print("─" * 74)

    for tid in experiment_tasks:
        task = all_tasks[tid]
        results["condition_b"][tid] = []
        for rep in range(repeats):
            print(f"\n  {tid} [{rep+1}/{repeats}]: ", end="", flush=True)
            prompt = CONDITION_B_PROMPT.format(goal=task["goal"])
            spec = rate_limited_generate(client, prompt)
            if not spec:
                print("FAIL(gen)")
                results["condition_b"][tid].append({"gen_error": True})
                continue

            print("eval...", end=" ", flush=True)
            r = evaluate_spec(spec, task)
            results["condition_b"][tid].append(r)

            n_render = sum(1 for h in r.values() if h.get("renderable"))
            n_pass = sum(1 for h in r.values() if h.get("success"))
            print(f"render={n_render}/4 pass={n_pass}/4")
            for host, hr in r.items():
                s = "✓" if hr["success"] else ("◐" if hr.get("renderable") else "✗")
                print(f"      {host:<10} {s}  RP={hr['render_parity']:.3f}  AP={hr['a11y_parity']:.3f}"
                      + (f"  err={hr['error']}" if hr.get("error") else ""))

    # ── Summary ──
    print(f"\n{'=' * 74}")
    print("TABLE 1: A vs B Comparison")
    print("=" * 74)

    def metrics(cond_data):
        renders, successes, rps, aps, total = 0, 0, [], [], 0
        ip_runs, ip_pass = 0, 0
        for tid, runs in cond_data.items():
            for run in runs:
                if "gen_error" in run:
                    continue
                ip_runs += 1
                all_pass = True
                for host, hr in run.items():
                    total += 1
                    if hr.get("renderable"):
                        renders += 1
                    if hr.get("success"):
                        successes += 1
                    else:
                        all_pass = False
                    rps.append(hr.get("render_parity", 0))
                    aps.append(hr.get("a11y_parity", 0))
                if all_pass:
                    ip_pass += 1
        return {
            "gen_rate": f"{(len([r for runs in cond_data.values() for r in runs if 'gen_error' not in r])/(len([r for runs in cond_data.values() for r in runs]) or 1)):.0%}",
            "render": f"{renders}/{total}",
            "success": f"{successes}/{total}" if total else "0/0",
            "sr": successes / total if total else 0,
            "ip": ip_pass / ip_runs if ip_runs else 0,
            "rp": sum(rps) / len(rps) if rps else 0,
            "ap": sum(aps) / len(aps) if aps else 0,
        }

    ref_m = metrics({"ref": [results["reference"]]})
    a_m = metrics(results["condition_a"])
    b_m = metrics(results["condition_b"])

    print(f"\n  {'':20} {'GenOK':>8} {'Render':>10} {'Success':>10} {'IP':>8} {'RP':>8} {'AP':>8}")
    print(f"  {'─' * 74}")
    print(f"  {'Reference':20} {'100%':>8} {ref_m['render']:>10} {ref_m['success']:>10}"
          f" {ref_m['ip']:>7.1%} {ref_m['rp']:>7.3f} {ref_m['ap']:>7.3f}")
    print(f"  {'A (freeform)':20} {a_m['gen_rate']:>8} {a_m['render']:>10} {a_m['success']:>10}"
          f" {a_m['ip']:>7.1%} {a_m['rp']:>7.3f} {a_m['ap']:>7.3f}")
    print(f"  {'B (schema-first)':20} {b_m['gen_rate']:>8} {b_m['render']:>10} {b_m['success']:>10}"
          f" {b_m['ip']:>7.1%} {b_m['rp']:>7.3f} {b_m['ap']:>7.3f}")

    delta_rp = b_m['rp'] - a_m['rp']
    delta_ap = b_m['ap'] - a_m['ap']
    print(f"\n  Schema advantage:  ΔRP = {delta_rp:+.3f}   ΔAP = {delta_ap:+.3f}")

    # Per-host
    print(f"\n  Per-host render parity (avg):")
    for host in HOSTS:
        a_vals = [run[host]["render_parity"] for tid in experiment_tasks
                  for run in results["condition_a"].get(tid, [])
                  if isinstance(run, dict) and host in run and "gen_error" not in run]
        b_vals = [run[host]["render_parity"] for tid in experiment_tasks
                  for run in results["condition_b"].get(tid, [])
                  if isinstance(run, dict) and host in run and "gen_error" not in run]
        a_avg = sum(a_vals) / len(a_vals) if a_vals else 0
        b_avg = sum(b_vals) / len(b_vals) if b_vals else 0
        print(f"    {host:<10}  A={a_avg:.3f}  B={b_avg:.3f}  Δ={b_avg-a_avg:+.3f}")

    # Save
    out = ROOT / "runs" / "experiment_ab_v2.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n  Saved: {out}")


if __name__ == "__main__":
    main()
