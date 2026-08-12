#!/usr/bin/env python3
"""Final batch: fill remaining A and B data points."""

import json, os, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

from google import genai
from google.genai import types
from hostshift.oracle import grade, load_suite
from hostshift.render import HOSTS, open_session, intended_tree
from hostshift.metrics import accessibility_parity, render_parity

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
all_tasks = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}

DELAY = 25

def make_prompt_a(goal):
    return (
        "Create a JSON UI spec for this task: " + goal + "\n"
        "Return a JSON object with: title, entry, state (variables with type/default), "
        "screens (array of screen objects with children). "
        "Widget kinds: heading, field, button, toggle, list, banner. "
        'Fields need "bind" to state vars. Buttons need "action" array. '
        "Return ONLY valid JSON, no explanation."
    )

def make_prompt_b(goal):
    return (
        "Generate a UISpec 0.2 JSON document for this task: " + goal + "\n\n"
        "UISpec 0.2 rules:\n"
        '1. Top level keys: "version" (must be "0.2"), "title", "entry", "state", "collections" (optional), "screens"\n'
        '2. "state" declares variables like: "myVar": {"type": "string", "default": ""}\n'
        '3. "collections" for lists like: "items": {"fields": {"name": {"type":"string"}}, "seed": [{"name":"Example"}]}\n'
        '4. Each screen has "id", "title", "children" array\n'
        '5. Widget kinds: heading, field, button, toggle, list, banner, image\n'
        '6. field needs "kind", "id", "label", "bind" (referencing a state var)\n'
        '7. button needs "kind", "id", "label", "action" array with ops like {"op":"set","target":"stateVar","value":true}\n'
        '   or {"op":"append","target":"collectionName","value":{"field":"$state.stateVar"}}\n'
        '8. toggle needs "kind", "id", "label", "bind" (boolean state var)\n'
        '9. list needs "kind", "id", "source" (collection name)\n'
        '10. enabledWhen/visibleWhen: {"op":"nonempty","left":"stateVar"} or {"op":"truthy","left":"stateVar"}\n'
        '11. Use "$state.varName" in action values to reference current state\n'
        "Return ONLY the JSON, no markdown."
    )

def evaluate(spec, task):
    results = {}
    for host in HOSTS:
        try:
            session = open_session(spec, host, simulated=True)
            actions = session.actions()
            fields = [a for a in actions if a["kind"] == "field"]
            buttons = [a for a in actions if a["kind"] == "button"]
            for f in fields:
                fid = f["id"].lower()
                if "name" in fid:
                    session.invoke(f["id"], "Dana Reyes")
                elif "email" in fid or "mail" in fid:
                    session.invoke(f["id"], "dana@example.com")
                elif any(w in fid for w in ("msg","message","body","text","note")):
                    session.invoke(f["id"], "Please call me back")
                else:
                    session.invoke(f["id"], "test input")
            for b in buttons:
                bid = (b.get("name","") + b.get("id","")).lower()
                if any(w in bid for w in ("submit","send","save","add","resolve")):
                    try:
                        session.invoke(b["id"])
                    except Exception:
                        pass
                    break

            g = grade(task, session.state(), session.ui_facts())
            ref = intended_tree(spec, session._state)
            got = session.widget_tree()
            rp = render_parity(ref, got)
            ap = accessibility_parity(ref, got).score
            results[host] = {
                "success": g["success"], "criteria_met": g["criteria_met"],
                "criteria_total": g["criteria_total"],
                "rp": round(rp, 3), "ap": round(ap, 3), "renderable": True
            }
            session.close()
        except Exception as e:
            results[host] = {
                "success": False, "rp": 0.0, "ap": 0.0,
                "renderable": False, "error": str(e)[:80]
            }
    return results

runs_to_do = [
    ("B", "form-001"), ("A", "list-001"),
    ("B", "list-001"), ("A", "form-001"),
]

print("Final batch — 4 calls with 25s delay")
print("Waiting 60s for rate limit reset...")
time.sleep(60)

results = []
for cond, tid in runs_to_do:
    task = all_tasks[tid]
    prompt = make_prompt_b(task["goal"]) if cond == "B" else make_prompt_a(task["goal"])

    print(f"\n{cond}/{tid}: generating...", end=" ", flush=True)
    time.sleep(DELAY)

    try:
        resp = client.models.generate_content(
            model="gemini-3.5-flash", contents=prompt,
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
            print("FAIL(no screens)")
            results.append({"condition": cond, "task": tid, "gen_error": "no_screens"})
            continue

        print("evaluating...")
        r = evaluate(spec, task)
        results.append({"condition": cond, "task": tid, "hosts": r})
        for host, hr in r.items():
            icon = "✓" if hr["success"] else ("◐" if hr.get("renderable") else "✗")
            print(f"  {host:<10} {icon}  RP={hr['rp']:.3f}  AP={hr['ap']:.3f}"
                  + (f"  err={hr['error']}" if hr.get("error") else ""))
    except Exception as e:
        print(f"FAIL({e.__class__.__name__}: {e})")
        results.append({"condition": cond, "task": tid, "gen_error": str(e)[:100]})

out = ROOT / "runs" / "experiment_final_batch.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(results, indent=2, default=str))
print(f"\nSaved {len(results)} runs to {out}")
