#!/usr/bin/env python3
"""Multi-model A vs B experiment using all available models.

Each model has its own daily quota (20 RPD on free tier).
We cycle through models to maximize data collection.
"""

import json, os, sys, time, pathlib

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

# Models with fresh quotas (20 calls each)
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
]

DELAY = 5  # seconds between calls (within same model, 5 RPM limit)

PROMPT_A = (
    "Create a JSON UI spec for this task: {goal}\n"
    "Return a JSON object with: title, entry, state (variables with "
    "type/default), screens (array with children). "
    "Widget kinds: heading, field, button, toggle, list, banner. "
    'Fields need "bind" to state vars. Buttons need "action" array. '
    "Return ONLY valid JSON."
)

PROMPT_B = (
    "Generate a UISpec 0.2 JSON document for this task: {goal}\n\n"
    "UISpec 0.2 rules:\n"
    '1. Top level: "version":"0.2", "title", "entry", "state", "collections"(optional), "screens"\n'
    '2. "state" declares variables: "myVar":' + '{"type":"string","default":""}\n'
    '3. "collections" for lists: "items":' + '{"fields":{"name":{"type":"string"}},"seed":[{"name":"Ex"}]}\n'
    '4. Each screen: "id","title","children" array\n'
    '5. Widgets: heading, field, button, toggle, list, banner, image\n'
    '6. field: "kind":"field","id":"x","label":"L","bind":"stateVar"\n'
    '7. button: "kind":"button","id":"x","label":"L","action":[' + '{"op":"set","target":"var","value":true}]\n'
    '8. toggle: "kind":"toggle","id":"x","label":"L","bind":"boolVar"\n'
    '9. list: "kind":"list","id":"x","source":"collectionName"\n'
    '10. enabledWhen/visibleWhen: ' + '{"op":"nonempty","left":"stateVar"}\n'
    '11. Use "$state.varName" in action values\n'
    "Return ONLY the JSON."
)


def evaluate(spec, task):
    results = {}
    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)
            actions = session.actions()
            for f in [a for a in actions if a["kind"] == "field"]:
                fid = f["id"].lower()
                if "name" in fid:
                    session.invoke(f["id"], "Dana Reyes")
                elif "email" in fid or "mail" in fid:
                    session.invoke(f["id"], "dana@example.com")
                elif any(w in fid for w in ("msg", "message", "body", "text", "note")):
                    session.invoke(f["id"], "Please call me back")
                elif "title" in fid or "subject" in fid:
                    session.invoke(f["id"], "Printer offline")
                elif "status" in fid:
                    session.invoke(f["id"], "resolved")
                else:
                    session.invoke(f["id"], "test input")
            for b in [a for a in actions if a["kind"] == "button"]:
                bid = (b.get("name", "") + b.get("id", "")).lower()
                if any(w in bid for w in ("submit", "send", "save", "add", "resolve", "mark")):
                    try:
                        session.invoke(b["id"])
                    except Exception:
                        pass
                    break
            # Also try list items for list tasks
            items = [a for a in actions if a["kind"] == "listItem"]
            if items:
                target = next((i for i in items if "printer" in i.get("name", "").lower()), items[0] if items else None)
                if target:
                    try:
                        session.invoke(target["id"])
                        # Check for resolve button after navigation
                        new_actions = session.actions()
                        for b in [a for a in new_actions if a["kind"] == "button"]:
                            bid = (b.get("name", "") + b.get("id", "")).lower()
                            if any(w in bid for w in ("resolve", "done", "close", "mark")):
                                try:
                                    session.invoke(b["id"])
                                except Exception:
                                    pass
                                break
                    except Exception:
                        pass

            g = grade(task, session.state(), session.ui_facts())
            ref = intended_tree(spec, session._state)
            got = session.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score
            results[host] = {
                "success": g["success"],
                "crit": f"{g['criteria_met']}/{g['criteria_total']}",
                "rp": round(rp, 3), "ap": round(ap, 3),
                "renderable": True,
            }
            session.close()
        except Exception as e:
            results[host] = {"success": False, "rp": 0.0, "ap": 0.0, "renderable": False, "error": str(e)[:60]}
    return results


def generate(model, prompt):
    time.sleep(DELAY)
    try:
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
        )
        spec = json.loads(resp.text.strip())
        spec.setdefault("version", "0.2")
        spec.setdefault("entry", "home")
        spec.setdefault("state", {})
        spec.setdefault("collections", {})
        return spec if "screens" in spec else None
    except Exception as e:
        return None


def main():
    tasks = ["form-001", "list-001"]
    conditions = ["A", "B"]
    repeats = 2

    print("=" * 74)
    print("MULTI-MODEL EXPERIMENT")
    print("=" * 74)
    print(f"Models: {MODELS}")
    print(f"Tasks: {tasks} | Conditions: A, B | Repeats: {repeats}")
    print()

    all_results = []

    for model in MODELS:
        print(f"\n{'─' * 74}")
        print(f"MODEL: {model}")
        print("─" * 74)

        for tid in tasks:
            task = all_tasks[tid]
            for cond in conditions:
                for rep in range(repeats):
                    prompt_template = PROMPT_B if cond == "B" else PROMPT_A
                    prompt = prompt_template.replace("{goal}", task["goal"])

                    print(f"  {cond}/{tid} r{rep+1}: ", end="", flush=True)
                    spec = generate(model, prompt)

                    if spec is None:
                        print("FAIL(gen)")
                        all_results.append({
                            "model": model, "condition": cond, "task": tid,
                            "repeat": rep, "gen_error": True
                        })
                        continue

                    r = evaluate(spec, task)
                    n_rend = sum(1 for h in r.values() if h.get("renderable"))
                    n_pass = sum(1 for h in r.values() if h.get("success"))
                    print(f"rend={n_rend}/4 pass={n_pass}/4  ", end="")

                    rps = [h["rp"] for h in r.values() if isinstance(h.get("rp"), (int, float))]
                    avg_rp = sum(rps) / len(rps) if rps else 0
                    print(f"avgRP={avg_rp:.3f}")

                    all_results.append({
                        "model": model, "condition": cond, "task": tid,
                        "repeat": rep, "hosts": r
                    })

    # Summary
    print(f"\n{'=' * 74}")
    print("MULTI-MODEL SUMMARY")
    print("=" * 74)

    for cond in conditions:
        cond_runs = [r for r in all_results if r["condition"] == cond]
        gen_ok = [r for r in cond_runs if "gen_error" not in r]
        renderable = [r for r in gen_ok if any(h.get("renderable") for h in r.get("hosts", {}).values())]

        rp_all = []
        for r in gen_ok:
            for h in r.get("hosts", {}).values():
                rp_all.append(h.get("rp", 0))

        avg_rp = sum(rp_all) / len(rp_all) if rp_all else 0
        label = "A (freeform)" if cond == "A" else "B (schema)"
        print(f"\n  {label}:")
        print(f"    Generated: {len(gen_ok)}/{len(cond_runs)} ({len(gen_ok)/max(len(cond_runs),1):.0%})")
        print(f"    Renderable: {len(renderable)}/{len(gen_ok)} ({len(renderable)/max(len(gen_ok),1):.0%})")
        print(f"    Avg RP: {avg_rp:.3f}")

        # Per host
        for host in HOSTS:
            vals = [r["hosts"][host]["rp"] for r in gen_ok if host in r.get("hosts", {})]
            avg = sum(vals) / len(vals) if vals else 0
            print(f"      {host:<10} RP={avg:.3f} (n={len(vals)})")

    # Save
    out = ROOT / "runs" / "experiment_multimodel.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\n  Saved: {out}")
    print(f"  Total API calls: {len([r for r in all_results if 'gen_error' not in r])}")


if __name__ == "__main__":
    main()
