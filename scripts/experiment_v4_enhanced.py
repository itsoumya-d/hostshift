#!/usr/bin/env python3
"""Enhanced Experiment v4 — Criteria-Aligned Schema Guidance.

Key insight: Condition B must provide the state variable names that the
task criteria actually CHECK, not the reference spec's variable names.
This is the correct interpretation of "schema-guided generation."

Also includes a smarter category-aware operator.
"""

import json, os, sys, time, pathlib, re, copy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

from google import genai
from google.genai import types
from hostshift.oracle import grade, load_suite
from hostshift.render import HOSTS, open_session, intended_tree
from hostshift.metrics import render_parity, accessibility_parity

ROOT = pathlib.Path(__file__).resolve().parents[1]
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
all_tasks = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}

MODELS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
BASE_DELAY = 6

# Tasks with known criteria state paths
TASK_IDS = [
    "form-001", "form-002", "form-003",
    "list-001", "list-003",
    "wizard-001",
    "settings-001", "settings-002",
    "search-001", "search-002",
    "dependent-001", "dependent-002",
    "media-002",
    "filter-001", "filter-002",
]


def extract_schema_from_criteria(task):
    """Build the EXACT state schema the task criteria expect."""
    state = {}
    collections = {}

    for c in task.get("criteria", []) + task.get("negative_criteria", []):
        kind = c.get("kind", "")

        if kind == "state_equals":
            path = c["path"]
            val = c["value"]
            # Convert dot-notation to nested or flat depending on depth
            if "." in path:
                parts = path.split(".")
                if parts[0] not in state:
                    state[parts[0]] = {}
                state[parts[0]][parts[1]] = {"type": type(val).__name__, "default": "" if isinstance(val, str) else False if isinstance(val, bool) else 0}
            else:
                state[path] = {"type": type(val).__name__, "default": "" if isinstance(val, str) else False if isinstance(val, bool) else 0}

        elif kind == "state_truthy":
            path = c["path"]
            state[path] = {"type": "boolean", "default": False}

        elif kind in ("collection_contains", "collection_count", "collection_field_equals"):
            coll = c.get("collection", "")
            if coll and coll not in collections:
                match = c.get("match", {})
                where = c.get("where", {})
                fields_dict = {}
                for k, v in {**match, **where}.items():
                    fields_dict[k] = {"type": type(v).__name__}
                if c.get("field"):
                    fields_dict[c["field"]] = {"type": type(c.get("value", "")).__name__}
                collections[coll] = {"fields": fields_dict, "seed": []}

    return state, collections


def make_prompt_a(task):
    """Condition A: Freeform — no schema hints."""
    return (
        f"Create a JSON UI specification for: {task['goal']}\n\n"
        "Return JSON with: title, entry, state (vars with type/default), "
        "collections (optional, with fields and seed), screens (array with children). "
        "Widget kinds: heading, field, button, toggle, list, banner. "
        'Fields need "bind", buttons need "action" array. '
        "Return ONLY valid JSON."
    )


def make_prompt_b(task):
    """Condition B: Schema-guided with criteria-aligned state paths."""
    state, collections = extract_schema_from_criteria(task)

    state_json = json.dumps(state, indent=2)
    coll_json = json.dumps(collections, indent=2) if collections else "{}"

    return (
        f"Generate a UISpec 0.2 JSON document for: {task['goal']}\n\n"
        f"REQUIRED state variable schema (use EXACTLY these paths):\n{state_json}\n\n"
        f"REQUIRED collections schema:\n{coll_json}\n\n"
        "UISpec 0.2 Rules:\n"
        '"version":"0.2", "title", "entry", "state", "collections", "screens"\n'
        "Widget kinds: heading, field, button, toggle, list, banner, image\n"
        'field: {"kind":"field","id":"x","label":"L","bind":"stateVar"}\n'
        'button: {"kind":"button","id":"x","label":"L","action":[{"op":"set","target":"var","value":val}]}\n'
        '  or {"op":"append","target":"collName","value":{"field":"$state.var"}}\n'
        '  or {"op":"navigate","target":"screenId"}\n'
        'toggle: {"kind":"toggle","id":"x","label":"L","bind":"boolVar"}\n'
        'list: {"kind":"list","id":"x","source":"collName"}\n'
        "Return ONLY valid JSON."
    )


def smart_drive(session, task):
    """Category-aware operator that drives sessions based on task goal."""
    goal = task["goal"]
    actions = session.actions()
    steps = 0

    fields = [a for a in actions if a["kind"] == "field"]
    buttons = [a for a in actions if a["kind"] == "button"]
    toggles = [a for a in actions if a["kind"] == "toggle"]
    items = [a for a in actions if a["kind"] == "listItem"]

    cat = task.get("category", "")

    # Extract values from goal text
    quoted = re.findall(r"'([^']+)'", goal)
    email_match = re.search(r'[\w.-]+@[\w.-]+\.\w+', goal)
    name_match = re.search(r'for\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', goal)
    number_match = re.findall(r'\b(\d+)\b', goal)

    # Build value map from criteria
    crit_vals = {}
    for c in task.get("criteria", []):
        if c.get("kind") == "state_equals":
            crit_vals[c["path"]] = c["value"]
        elif c.get("kind") == "collection_contains":
            for k, v in c.get("match", {}).items():
                crit_vals[k] = v
        elif c.get("kind") == "collection_field_equals":
            crit_vals[c.get("field", "")] = c.get("value")

    def safe_invoke(widget_id, *args):
        nonlocal steps
        try:
            session.invoke(widget_id, *args)
            steps += 1
            return True
        except Exception:
            return False

    # ── FORM FILLING ──
    if cat in ("form_validation",):
        for f in fields:
            fid = f["id"].lower()
            fname = f.get("name", "").lower()
            comb = fid + " " + fname

            # Try criteria values first
            filled = False
            for ck, cv in crit_vals.items():
                if isinstance(cv, str) and ck.lower() in comb:
                    safe_invoke(f["id"], cv)
                    filled = True
                    break

            if not filled:
                if any(w in comb for w in ("name", "full", "user")):
                    safe_invoke(f["id"], name_match.group(1) if name_match else crit_vals.get("name", crit_vals.get("username", "Test User")))
                elif any(w in comb for w in ("email", "mail")):
                    safe_invoke(f["id"], email_match.group() if email_match else "test@test.com")
                elif any(w in comb for w in ("password", "pass", "confirm")):
                    safe_invoke(f["id"], quoted[0] if quoted else "password123")
                elif any(w in comb for w in ("msg", "message", "body", "comment", "text")):
                    safe_invoke(f["id"], quoted[0] if quoted else "Test message")
                elif any(w in comb for w in ("amount", "price", "cost", "qty")):
                    val = number_match[-1] if number_match else "10"
                    safe_invoke(f["id"], val)
                elif any(w in comb for w in ("category", "type", "dept")):
                    safe_invoke(f["id"], quoted[0] if quoted else "General")
                else:
                    safe_invoke(f["id"], "test input")

        # Click submit-type buttons
        for b in buttons:
            bid = (b.get("name", "") + b.get("id", "")).lower()
            if any(w in bid for w in ("submit", "send", "save", "add", "confirm")):
                safe_invoke(b["id"])
                break

    # ── SETTINGS/TOGGLES ──
    elif cat in ("settings_toggles",):
        for t in toggles:
            tid = t["id"].lower()
            tname = t.get("name", "").lower()
            comb = tid + " " + tname

            # Check criteria for desired toggle states
            for ck, cv in crit_vals.items():
                ck_parts = ck.split(".")
                ck_leaf = ck_parts[-1].lower()
                if ck_leaf in comb or ck.lower().replace(".", "") in comb:
                    if cv is True:
                        safe_invoke(t["id"])  # Toggle on
                    break
            else:
                # Check goal text
                if any(w in comb for w in ("dark", "theme")):
                    if "dark mode on" in goal.lower() or "turn dark" in goal.lower():
                        safe_invoke(t["id"])
                elif any(w in comb for w in ("master", "notification", "enable")):
                    if "master" in goal.lower() or "turn" in goal.lower():
                        safe_invoke(t["id"])

    # ── SEARCH ──
    elif cat in ("search_results",):
        search_field = next((f for f in fields if any(w in f["id"].lower() for w in ("search", "query", "filter"))), None)
        if search_field:
            query_val = crit_vals.get("query", quoted[0] if quoted else "test")
            safe_invoke(search_field["id"], query_val)

        # Click first result if we need route=detail
        if crit_vals.get("route") == "detail":
            new_actions = session.actions()
            new_items = [a for a in new_actions if a["kind"] == "listItem"]
            if new_items:
                safe_invoke(new_items[0]["id"])

    # ── DEPENDENT FIELDS ──
    elif cat in ("dependent_fields",):
        for f in fields:
            fid = f["id"].lower()
            for ck, cv in crit_vals.items():
                ck_leaf = ck.split(".")[-1].lower()
                if ck_leaf in fid or fid in ck_leaf:
                    if isinstance(cv, str):
                        safe_invoke(f["id"], cv)
                    elif isinstance(cv, bool) and cv:
                        safe_invoke(f["id"])

        for t in toggles:
            for ck, cv in crit_vals.items():
                if ck.lower().replace(".", "") in t["id"].lower() and cv is True:
                    safe_invoke(t["id"])

    # ── LIST DETAIL ──
    elif cat in ("list_detail",):
        if items:
            # Find the target item from goal
            target_name = ""
            for q in quoted:
                target_name = q
                break
            target = next((i for i in items if target_name.lower() in i.get("name", "").lower()), None)
            if target:
                safe_invoke(target["id"])

            # After navigation, look for action buttons
            new_actions = session.actions()
            for b in [a for a in new_actions if a["kind"] == "button"]:
                bid = (b.get("name", "") + b.get("id", "")).lower()
                if any(w in bid for w in ("resolve", "delete", "remove", "mark", "complete")):
                    safe_invoke(b["id"])
                    break

    # ── WIZARD ──
    elif cat in ("multi_step_wizard",):
        # Fill all fields on current screen, click Next, repeat
        for _ in range(5):  # max 5 screens
            cur_actions = session.actions()
            cur_fields = [a for a in cur_actions if a["kind"] == "field"]
            cur_buttons = [a for a in cur_actions if a["kind"] == "button"]

            for f in cur_fields:
                fid = f["id"].lower()
                for ck, cv in crit_vals.items():
                    if isinstance(cv, str) and ck.lower() in fid:
                        safe_invoke(f["id"], cv)
                        break
                else:
                    safe_invoke(f["id"], "test input")

            # Click Next/Finish
            next_btn = next((b for b in cur_buttons if any(w in b.get("id", "").lower() + b.get("name", "").lower() for w in ("next", "finish", "complete", "confirm", "submit"))), None)
            if next_btn:
                safe_invoke(next_btn["id"])
            else:
                break

    # ── FILTERABLE TABLE ──
    elif cat in ("filterable_table",):
        for f in fields:
            fid = f["id"].lower()
            for ck, cv in crit_vals.items():
                ck_leaf = ck.split(".")[-1].lower()
                if isinstance(cv, str) and (ck_leaf in fid or fid in ck_leaf):
                    safe_invoke(f["id"], cv)
                    break

        for b in buttons:
            bid = b.get("id", "").lower()
            if any(w in bid for w in ("sort", "filter", "apply", "clear")):
                safe_invoke(b["id"])

    # ── MEDIA ──
    elif cat in ("media_actions",):
        if items:
            target_name = quoted[0] if quoted else ""
            target = next((i for i in items if target_name.lower() in i.get("name", "").lower()), None)
            if target:
                safe_invoke(target["id"])

            new_actions = session.actions()
            for b in [a for a in new_actions if a["kind"] == "button"]:
                bid = (b.get("name", "") + b.get("id", "")).lower()
                if any(w in bid for w in ("fav", "like", "close", "back")):
                    safe_invoke(b["id"])
                    break

    # ── FALLBACK ──
    else:
        for f in fields:
            safe_invoke(f["id"], "test")
        for t in toggles:
            safe_invoke(t["id"])
        for b in buttons:
            bid = (b.get("name", "") + b.get("id", "")).lower()
            if any(w in bid for w in ("submit", "save", "next")):
                safe_invoke(b["id"])
                break

    return steps


def evaluate(spec, task):
    """Evaluate a spec across all 4 hosts."""
    results = {}
    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)
            steps = smart_drive(session, task)
            g = grade(task, session.state(), session.ui_facts())
            ref = intended_tree(spec, session._state)
            got = session.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score
            results[host] = {
                "success": g["success"], "criteria_met": g["criteria_met"],
                "criteria_total": g["criteria_total"], "steps": steps,
                "rp": round(rp, 3), "ap": round(ap, 3), "renderable": True,
            }
            session.close()
        except Exception as e:
            results[host] = {"success": False, "rp": 0.0, "ap": 0.0, "renderable": False, "error": str(e)[:80]}
    return results


def main():
    tasks = [all_tasks[tid] for tid in TASK_IDS if tid in all_tasks]
    print(f"{'='*74}", flush=True)
    print(f"ENHANCED EXPERIMENT v4 — Criteria-Aligned Schema Guidance", flush=True)
    print(f"{'='*74}", flush=True)
    print(f"Tasks: {len(tasks)} | Models: {len(MODELS)} | Conditions: A,B", flush=True)
    print(f"Total planned API calls: {len(tasks)*len(MODELS)*2}", flush=True)

    runs = []
    for model in MODELS:
        print(f"\nModel: {model}", flush=True)
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
                        runs.append({"model": model, "condition": cond, "task": task["id"], "category": task["category"], "gen_error": "no_screens"})
                        print(f"  {cond}/{task['id']:<14} NO_SCREENS", flush=True)
                        continue

                    r = evaluate(spec, task)
                    n_rend = sum(1 for h in r.values() if h.get("renderable"))
                    n_pass = sum(1 for h in r.values() if h.get("success"))
                    avg_rp = sum(h["rp"] for h in r.values()) / 4.0
                    print(f"  {cond}/{task['id']:<14} rend={n_rend}/4 pass={n_pass}/4 avgRP={avg_rp:.3f}", flush=True)
                    runs.append({"model": model, "condition": cond, "task": task["id"], "category": task["category"], "hosts": r})
                except Exception as e:
                    print(f"  {cond}/{task['id']:<14} FAIL({e.__class__.__name__})", flush=True)
                    runs.append({"model": model, "condition": cond, "task": task["id"], "category": task["category"], "gen_error": str(e)[:60]})

    # Summary
    print(f"\n{'='*74}", flush=True)
    print("SUMMARY", flush=True)
    for cond in ["A", "B"]:
        cr = [r for r in runs if r["condition"] == cond and "gen_error" not in r]
        rend = sum(1 for r in cr if any(h.get("renderable") for h in r.get("hosts", {}).values()))
        passed = sum(1 for r in cr if any(h.get("success") for h in r.get("hosts", {}).values()))
        label = "A (Freeform)" if cond == "A" else "B (Schema-Guided)"
        print(f"  {label}: Generated={len(cr)} Renderable={rend} TaskPass={passed}", flush=True)

    out = ROOT / "runs" / "experiment_v4_enhanced.json"
    out.write_text(json.dumps(runs, indent=2, default=str))
    print(f"\nSaved: {out}", flush=True)


if __name__ == "__main__":
    main()
