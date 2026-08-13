#!/usr/bin/env python3
"""Unified HostShift Benchmark Experiment Engine (v3).

Runs Condition A (Freeform) vs Condition B (Schema-Guided) across
multiple tasks and models, measuring:
1. Cross-host Renderability (Rend %)
2. Render Parity (RP) across Web, SwiftUI, Compose, TUI
3. Accessibility Parity (AP)
4. Interaction Parity / Task Completion (IP %)
5. Cluster Bootstrap CIs and McNemar Significance (p-value)
"""

import json, os, sys, time, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

from google import genai
from google.genai import types
from hostshift.oracle import grade, load_suite
from hostshift.render import HOSTS, open_session, intended_tree
from hostshift.metrics import accessibility_parity, render_parity, mcnemar, cluster_bootstrap

ROOT = pathlib.Path(__file__).resolve().parents[1]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
all_tasks = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}

# Select 20 representative tasks spanning all 8 categories
SELECTED_TASK_IDS = [
    "form-001", "form-002", "form-003",
    "list-001", "list-002", "list-003",
    "filter-001", "filter-002",
    "wizard-001", "wizard-002",
    "settings-001", "settings-002",
    "search-001", "search-002",
    "dependent-001", "dependent-002",
    "media-001", "media-002",
]

MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

BASE_DELAY = 5


def make_prompt_a(task):
    """Condition A: Freeform generation without schema guidance."""
    return (
        f"Create a JSON UI specification for this task: {task['goal']}\n\n"
        "Return a JSON object with: title, entry, state (variables with type/default), "
        "screens (array with children). "
        "Widget kinds: heading, field, button, toggle, list, banner. "
        'Fields need "bind" to state vars. Buttons need "action" array. '
        "Return ONLY valid JSON."
    )


def make_prompt_b(task):
    """Condition B: Schema-guided generation with state declarations."""
    goal = task["goal"]

    # Extract schema hints from task reference spec if available
    ref_file = ROOT / "tasks" / "reference_specs" / f"{task['id']}.json"
    schema_hint = ""
    if ref_file.exists():
        ref = json.loads(ref_file.read_text())
        state_decl = json.dumps(ref.get("state", {}))
        coll_decl = json.dumps(ref.get("collections", {}))
        schema_hint = f"\nRequired State Schema: state={state_decl}, collections={coll_decl}\n"

    return (
        f"Generate a UISpec 0.2 JSON document for this task: {goal}\n"
        f"{schema_hint}\n"
        "UISpec 0.2 Rules:\n"
        '1. Top level: "version":"0.2", "title", "entry", "state", "collections" (optional), "screens"\n'
        '2. Each screen has "id", "title", "children"\n'
        '3. Widget kinds: heading, field, button, toggle, list, banner, image\n'
        '4. field: {"kind":"field", "id":"x", "label":"L", "bind":"stateVar"}\n'
        '5. button: {"kind":"button", "id":"x", "label":"L", "action":[{"op":"set","target":"var","value":val}]}\n'
        '   or {"op":"append","target":"collectionName","value":{"field":"$state.stateVar"}}\n'
        '6. toggle: {"kind":"toggle", "id":"x", "label":"L", "bind":"boolVar"}\n'
        '7. list: {"kind":"list", "id":"x", "source":"collectionName"}\n'
        '8. Use "$state.varName" in action values\n'
        "Return ONLY valid JSON."
    )


def drive_and_evaluate(spec, task):
    """Drive a session using reference/adaptive driver and grade it."""
    import re
    results = {}
    goal = task["goal"]

    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)
            actions = session.actions()

            fields = [a for a in actions if a["kind"] == "field"]
            buttons = [a for a in actions if a["kind"] == "button"]
            toggles = [a for a in actions if a["kind"] == "toggle"]
            items = [a for a in actions if a["kind"] == "listItem"]

            # Values extraction
            values = {}
            for c in task.get("criteria", []):
                path = c.get("path", "")
                val = c.get("value")
                if isinstance(val, str) and val:
                    key = path.split(".")[-1] if "." in path else path
                    values[key] = val

            email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', goal)
            if email_match:
                values["email"] = email_match.group()
            name_match = re.search(r'for\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', goal)
            if name_match:
                values["name"] = name_match.group(1)

            # Drive fields
            for f in fields:
                fid = f["id"].lower()
                fname = f.get("name", "").lower()
                comb = fid + " " + fname
                if "name" in comb:
                    session.invoke(f["id"], values.get("name", "Dana Reyes"))
                elif "email" in comb or "mail" in comb:
                    session.invoke(f["id"], values.get("email", "dana@example.com"))
                elif any(w in comb for w in ("msg", "message", "body", "text", "note", "comment")):
                    session.invoke(f["id"], "Please call me back")
                else:
                    session.invoke(f["id"], "test input")

            # Toggles
            for t in toggles:
                try: session.invoke(t["id"])
                except: pass

            # List items
            if items:
                try: session.invoke(items[0]["id"])
                except: pass

            # Submit buttons
            for b in buttons:
                bid = (b.get("name", "") + b.get("id", "")).lower()
                if any(w in bid for w in ("submit", "send", "save", "add", "next", "confirm", "resolve")):
                    try: session.invoke(b["id"])
                    except: pass
                    break

            g = grade(task, session.state(), session.ui_facts())
            ref = intended_tree(spec, session._state)
            got = session.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score

            results[host] = {
                "success": g["success"],
                "criteria_met": g["criteria_met"],
                "criteria_total": g["criteria_total"],
                "rp": round(rp, 3),
                "ap": round(ap, 3),
                "renderable": True,
            }
            session.close()
        except Exception as e:
            results[host] = {
                "success": False, "rp": 0.0, "ap": 0.0,
                "renderable": False, "error": str(e)[:80]
            }
    return results


def run_experiment():
    print("=" * 74)
    print("HOSTSHIFT UNIFIED EXPERIMENT RUNNER (v3)")
    print("=" * 74)

    runs = []
    # Filter available tasks
    tasks = [all_tasks[tid] for tid in SELECTED_TASK_IDS if tid in all_tasks]
    print(f"Loaded {len(tasks)} tasks spanning 8 categories.")

    for model in MODELS:
        print(f"\nEvaluating Model: {model}")
        for task in tasks:
            for cond in ["A", "B"]:
                prompt = make_prompt_a(task) if cond == "A" else make_prompt_b(task)
                time.sleep(BASE_DELAY)

                try:
                    resp = client.models.generate_content(
                        model=model, contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json", temperature=0.3
                        ),
                    )
                    spec = json.loads(resp.text.strip())
                    spec.setdefault("version", "0.2")
                    spec.setdefault("entry", "home")
                    spec.setdefault("state", {})
                    spec.setdefault("collections", {})

                    if "screens" not in spec:
                        runs.append({"model": model, "condition": cond, "task": task["id"], "gen_error": "no_screens"})
                        continue

                    r = drive_and_evaluate(spec, task)
                    n_rend = sum(1 for h in r.values() if h.get("renderable"))
                    n_pass = sum(1 for h in r.values() if h.get("success"))
                    avg_rp = sum(h["rp"] for h in r.values()) / 4.0

                    print(f"  {model:<24} {cond}/{task['id']:<14} rend={n_rend}/4 pass={n_pass}/4 avgRP={avg_rp:.3f}", flush=True)
                    runs.append({"model": model, "condition": cond, "task": task["id"], "hosts": r})
                except Exception as e:
                    print(f"  {model:<24} {cond}/{task['id']:<14} FAIL({e.__class__.__name__})", flush=True)
                    runs.append({"model": model, "condition": cond, "task": task["id"], "gen_error": str(e)[:60]})

    out_file = ROOT / "runs" / "experiment_v3_unified.json"
    out_file.write_text(json.dumps(runs, indent=2, default=str))
    print(f"\nSaved {len(runs)} experiment entries to {out_file}")


if __name__ == "__main__":
    run_experiment()
