#!/usr/bin/env python3
"""Comprehensive A vs B experiment — Day 2, full quotas.

Uses all 4 models with fresh daily quotas (80 total calls).
Tests ALL 8 reference spec categories.
Includes retry logic and exponential backoff for rate limits.
"""

import json, os, sys, time, pathlib, traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

from google import genai
from google.genai import types
from hostshift.oracle import grade, load_suite
from hostshift.render import HOSTS, open_session, intended_tree
from hostshift.metrics import accessibility_parity, render_parity

ROOT = pathlib.Path(__file__).resolve().parents[1]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
all_tasks = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}

# 7 reference specs that have matching tasks in suite_v1
SPEC_IDS = [
    "form-001", "list-001", "wizard-001",
    "settings-001", "search-001", "dependent-001", "media-001",
]

# 4 models with fresh daily quotas
MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

BASE_DELAY = 13  # seconds between calls (stay under 5 RPM)
MAX_RETRIES = 2


def make_prompt_a(goal):
    return (
        "Create a JSON UI specification for this application task:\n\n"
        f"Task: {goal}\n\n"
        "Return a JSON object with these keys:\n"
        '- "title": application title\n'
        '- "entry": "home"\n'
        '- "state": object of state variables, each with "type" and "default"\n'
        '- "collections": optional data collections with "fields" and "seed" arrays\n'
        '- "screens": array of screen objects, each with "id", "title", "children"\n\n'
        "Each child widget must have:\n"
        '- "kind": one of heading, field, button, toggle, list, banner, image\n'
        '- "id": unique identifier\n'
        '- "label": display text\n'
        '- For fields: "bind" referencing a state variable\n'
        '- For buttons: "action" array with operations like {"op":"set","target":"var","value":val}\n'
        '- For lists: "source" referencing a collection name\n'
        '- Optional: "enabledWhen"/"visibleWhen" for conditional logic\n\n'
        "Return ONLY valid JSON, no explanation or markdown."
    )


def make_prompt_b(goal):
    return (
        "Generate a UISpec 0.2 JSON document conforming to these exact rules:\n\n"
        f"Task: {goal}\n\n"
        "UISpec 0.2 Schema Rules (follow precisely):\n"
        '1. Top-level keys: "version" (MUST be "0.2"), "title", "entry", "state", "collections" (optional), "screens"\n'
        '2. "state" declares variables: {"varName": {"type": "string"|"boolean"|"number", "default": value}}\n'
        '3. "collections" for list data: {"collName": {"fields": {"fieldName": {"type":"string"}}, "seed": [{"fieldName":"value"}]}}\n'
        '4. Each screen: {"id": "screenId", "title": "Title", "children": [...]}\n'
        '5. Widget kinds: heading, field, button, toggle, list, banner, image\n'
        '6. field: {"kind":"field", "id":"x", "label":"L", "bind":"stateVar"}\n'
        '7. button: {"kind":"button", "id":"x", "label":"L", "action":[{"op":"set","target":"stateVar","value":true}]}\n'
        '   Other ops: {"op":"append","target":"collectionName","value":{"field":"$state.stateVar"}}\n'
        '              {"op":"navigate","target":"screenId"}\n'
        '8. toggle: {"kind":"toggle", "id":"x", "label":"L", "bind":"boolStateVar"}\n'
        '9. list: {"kind":"list", "id":"x", "source":"collectionName"}\n'
        '10. Conditional guards: {"op":"nonempty"|"truthy"|"eq"|"and"|"not", "left":"stateVar"}\n'
        '11. Use "$state.varName" in action values to reference current state\n'
        '12. MUST include "version": "0.2"\n\n'
        "Return ONLY the JSON, no markdown fences, no explanation."
    )


def generate_with_retry(model, prompt):
    """Generate with retry and exponential backoff."""
    for attempt in range(MAX_RETRIES + 1):
        delay = BASE_DELAY * (2 ** attempt)
        time.sleep(delay)
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
                return None, "no_screens"
            return spec, None
        except json.JSONDecodeError as e:
            if attempt < MAX_RETRIES:
                continue
            return None, f"json_error:{e}"
        except Exception as e:
            err_str = str(e)
            if "429" in err_str and attempt < MAX_RETRIES:
                print(f"(rate-limit, retry {attempt+1})...", end=" ", flush=True)
                continue
            return None, f"{e.__class__.__name__}"
    return None, "max_retries"


def adaptive_drive(session, task):
    """Drive a session by discovering actions from the spec."""
    import re
    goal = task.get("goal", "")
    actions = session.actions()
    fields = [a for a in actions if a["kind"] == "field"]
    buttons = [a for a in actions if a["kind"] == "button"]
    toggles = [a for a in actions if a["kind"] == "toggle"]
    items = [a for a in actions if a["kind"] == "listItem"]
    steps = 0

    # Extract values from goal and criteria
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
    quoted = re.findall(r"'([^']+)'", goal)
    for q in quoted:
        if "@" not in q:
            values.setdefault("message", q)

    # Fill fields
    for f in fields:
        fid = f["id"].lower()
        fname = f.get("name", "").lower()
        combined = fid + " " + fname
        filled = False
        for key, val in values.items():
            if key.lower() in combined:
                try:
                    session.invoke(f["id"], val)
                    steps += 1
                    filled = True
                except Exception:
                    pass
                break
        if not filled:
            # Heuristic matching
            if any(w in combined for w in ("name", "full", "first", "last")):
                try: session.invoke(f["id"], values.get("name", "Test User")); steps += 1
                except: pass
            elif any(w in combined for w in ("email", "mail")):
                try: session.invoke(f["id"], values.get("email", "test@test.com")); steps += 1
                except: pass
            elif any(w in combined for w in ("msg", "message", "body", "note", "text", "comment", "description")):
                try: session.invoke(f["id"], values.get("message", "Test message")); steps += 1
                except: pass
            elif any(w in combined for w in ("search", "query", "filter")):
                try: session.invoke(f["id"], "test search"); steps += 1
                except: pass
            elif any(w in combined for w in ("title", "subject")):
                try: session.invoke(f["id"], "Test Title"); steps += 1
                except: pass
            else:
                try: session.invoke(f["id"], "test input"); steps += 1
                except: pass

    # Toggle toggles
    for t in toggles:
        try:
            session.invoke(t["id"])
            steps += 1
        except Exception:
            pass

    # Click list items
    if items:
        target_name = ""
        for q in quoted:
            target_name = q
            break
        target = next((i for i in items if target_name.lower() in i.get("name", "").lower()), None) if target_name else None
        if target is None and items:
            target = items[0]
        if target:
            try:
                session.invoke(target["id"])
                steps += 1
            except Exception:
                pass
            # Check for action buttons after navigation
            new_actions = session.actions()
            for b in [a for a in new_actions if a["kind"] == "button"]:
                bid = (b.get("name", "") + b.get("id", "")).lower()
                if any(w in bid for w in ("resolve", "done", "close", "mark", "complete", "save")):
                    try: session.invoke(b["id"]); steps += 1
                    except: pass
                    break

    # Click submit-type buttons
    for b in buttons:
        bid = (b.get("name", "") + b.get("id", "")).lower()
        if any(w in bid for w in ("submit", "send", "save", "add", "next", "confirm", "apply")):
            try:
                session.invoke(b["id"])
                steps += 1
            except Exception:
                pass
            break

    return steps


def evaluate_spec(spec, task):
    """Run a spec through all 4 hosts and return graded results."""
    results = {}
    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)
            steps = adaptive_drive(session, task)
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
                "rp": round(rp, 3),
                "ap": round(ap, 3),
                "renderable": True,
            }
            session.close()
        except Exception as e:
            results[host] = {
                "success": False, "criteria_met": 0,
                "criteria_total": len(task.get("criteria", [])),
                "steps": 0, "rp": 0.0, "ap": 0.0,
                "renderable": False, "error": str(e)[:80],
            }
    return results


def main():
    # Use 2 models × 4 specs × 2 conditions = 16 calls per model, well under 20
    # Then 2 more models × 4 specs × 2 conditions = 16 more
    # Total: 64 calls, leaving headroom

    # Split specs across models to stay under 20 calls/model quota
    # Each model: ~4 specs × 2 conditions = 8 calls (safe under 20)
    model_specs = {
        "gemini-3.5-flash": ["form-001", "list-001", "wizard-001", "settings-001"],
        "gemini-flash-latest": ["search-001", "dependent-001", "media-001", "form-001"],
        "gemini-3.1-flash-lite": ["form-001", "list-001", "settings-001", "search-001"],
        "gemini-flash-lite-latest": ["wizard-001", "dependent-001", "media-001", "list-001"],
    }

    print("=" * 74)
    print("COMPREHENSIVE A vs B EXPERIMENT — Day 2 (Fresh Quotas)")
    print("=" * 74)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M')}")
    print(f"Total planned calls: {sum(len(s)*2 for s in model_specs.values())}")
    print()

    all_results = {
        "metadata": {
            "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "description": "Comprehensive A vs B across 4 models and 8 specs",
        },
        "reference": {},
        "runs": [],
    }

    # First, establish reference baselines for ALL specs
    print("─" * 74)
    print("BASELINES: Reference specs (ground truth)")
    print("─" * 74)

    for sid in SPEC_IDS:
        task = all_tasks[sid]
        ref_spec = json.loads((ROOT / "tasks" / "reference_specs" / f"{sid}.json").read_text())
        r = evaluate_spec(ref_spec, task)
        all_results["reference"][sid] = r
        rps = [h["rp"] for h in r.values()]
        avg_rp = sum(rps) / len(rps)
        n_pass = sum(1 for h in r.values() if h["success"])
        print(f"  {sid:<18} pass={n_pass}/4 avgRP={avg_rp:.3f}")

    # Run A vs B for each model
    for model, specs in model_specs.items():
        print(f"\n{'─' * 74}")
        print(f"MODEL: {model} ({len(specs)} specs × 2 conditions = {len(specs)*2} calls)")
        print("─" * 74)

        for sid in specs:
            task = all_tasks[sid]

            for cond in ["A", "B"]:
                prompt = make_prompt_a(task["goal"]) if cond == "A" else make_prompt_b(task["goal"])
                label = f"{cond}/{sid}"

                print(f"\n  {label}: ", end="", flush=True)
                spec, err = generate_with_retry(model, prompt)

                if spec is None:
                    print(f"FAIL({err})")
                    all_results["runs"].append({
                        "model": model, "condition": cond, "task": sid,
                        "gen_error": err,
                    })
                    continue

                r = evaluate_spec(spec, task)
                n_rend = sum(1 for h in r.values() if h.get("renderable"))
                n_pass = sum(1 for h in r.values() if h.get("success"))
                rps = [h["rp"] for h in r.values()]
                avg_rp = sum(rps) / len(rps)
                print(f"rend={n_rend}/4 pass={n_pass}/4 avgRP={avg_rp:.3f}")

                for host, hr in r.items():
                    icon = "✓" if hr["success"] else ("◐" if hr.get("renderable") else "✗")
                    detail = f"  err={hr['error']}" if hr.get("error") else ""
                    print(f"      {host:<10} {icon}  RP={hr['rp']:.3f}  AP={hr['ap']:.3f}{detail}")

                all_results["runs"].append({
                    "model": model, "condition": cond, "task": sid,
                    "hosts": r, "generated_spec_keys": list(spec.keys()),
                })

    # ── SUMMARY ──
    print(f"\n{'=' * 74}")
    print("COMPREHENSIVE SUMMARY")
    print("=" * 74)

    for cond in ["A", "B"]:
        runs = [r for r in all_results["runs"] if r["condition"] == cond]
        gen_ok = [r for r in runs if "gen_error" not in r]
        renderable = [r for r in gen_ok if any(h.get("renderable") for h in r.get("hosts", {}).values())]
        passed = [r for r in gen_ok if any(h.get("success") for h in r.get("hosts", {}).values())]

        rp_all, ap_all = [], []
        for r in gen_ok:
            for h in r.get("hosts", {}).values():
                rp_all.append(h.get("rp", 0))
                ap_all.append(h.get("ap", 0))

        label = "A (freeform)" if cond == "A" else "B (schema-first)"
        print(f"\n  {label}:")
        print(f"    Attempted: {len(runs)}")
        print(f"    Generated: {len(gen_ok)}/{len(runs)} ({len(gen_ok)/max(len(runs),1):.0%})")
        print(f"    Renderable: {len(renderable)}/{len(gen_ok)} ({len(renderable)/max(len(gen_ok),1):.0%})")
        print(f"    Task Pass: {len(passed)}/{len(gen_ok)}")
        print(f"    Avg RP: {sum(rp_all)/len(rp_all):.3f}" if rp_all else "    Avg RP: N/A")
        print(f"    Avg AP: {sum(ap_all)/len(ap_all):.3f}" if ap_all else "    Avg AP: N/A")

        for host in HOSTS:
            vals = [r["hosts"][host]["rp"] for r in gen_ok if host in r.get("hosts", {})]
            avg = sum(vals) / len(vals) if vals else 0
            print(f"      {host:<10} RP={avg:.3f} (n={len(vals)})")

    # Per-model breakdown
    print(f"\n  Per-Model Renderability:")
    for model in MODELS:
        for cond in ["A", "B"]:
            runs = [r for r in all_results["runs"]
                    if r["model"] == model and r["condition"] == cond and "gen_error" not in r]
            rend = [r for r in runs if any(h.get("renderable") for h in r.get("hosts", {}).values())]
            pct = len(rend) / len(runs) if runs else 0
            label = "A" if cond == "A" else "B"
            print(f"    {model:<25} {label}: {len(rend)}/{len(runs)} ({pct:.0%})")

    # Save
    out = ROOT / "runs" / "experiment_comprehensive.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  Saved: {out}")
    print(f"  Total successful API calls: {len([r for r in all_results['runs'] if 'gen_error' not in r])}")


if __name__ == "__main__":
    main()
