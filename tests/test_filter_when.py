"""filterWhen and predicate template regression tests.

UISpec 0.2 gained two capabilities while making the filterable_table tasks
expressible:

  - list.filterWhen -- a per-row predicate narrowing what a list shows;
  - ``$state.path`` references in predicate operands (either side), so a
    control bound to state can drive a filter without action plumbing.

These tests pin the semantics in the Python reference AND assert the emitted
JavaScript agrees with it, because a filter that behaves differently on web
than in the reference would poison every visible_row_count criterion.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render import ReferenceSession, get_renderer
from hostshift.render.semantics import evaluate, project, resolve

ROOT = pathlib.Path(__file__).resolve().parents[1]

SPEC = {
    "version": "0.2",
    "title": "t",
    "entry": "main",
    "state": {
        "dept": {"type": "string", "default": "All"},
        "q": {"type": "string", "default": ""},
    },
    "collections": {
        "rows": {
            "fields": {"name": {"type": "string"}, "dept": {"type": "string"}},
            "seed": [
                {"name": "Ann", "dept": "Eng"},
                {"name": "Bob", "dept": "Sales"},
                {"name": "Cid", "dept": "Eng"},
            ],
        }
    },
    "screens": [{
        "id": "main",
        "title": "T",
        "children": [
            {"kind": "select", "id": "d", "label": "Dept", "bind": "dept"},
            {"kind": "field", "id": "q", "label": "Search", "bind": "q"},
            {"kind": "list", "id": "lst", "of": "rows", "rowLabel": "name",
             "filterWhen": {"op": "and", "clauses": [
                 {"op": "or", "clauses": [
                     {"op": "eq", "left": "$row.dept", "right": "$state.dept"},
                     {"op": "eq", "left": "$state.dept", "right": "All"},
                 ]},
                 {"op": "matches", "left": "$row.name", "right": "$state.q"},
             ]}},
        ],
    }],
}


def test_resolve_strips_state_prefix():
    st = {"a": {"b": 7}}
    assert resolve(st, "$state.a.b") == 7
    assert resolve(st, "a.b") == 7


def test_filter_when_narrows_rows():
    s = ReferenceSession(SPEC)
    f = s.ui_facts()
    assert f["visible_rows"]["lst"] == 3
    s.invoke("d", "Eng")
    f = s.ui_facts()
    assert f["visible_rows"]["lst"] == 2
    names = [r["name"] for r in project(SPEC, s.state()).children[-1].rows]
    assert names == ["Ann", "Cid"]
    # underlying collection untouched by filtering
    assert len(s.state()["collections"]["rows"]) == 3


def test_right_operand_state_template():
    s = ReferenceSession(SPEC)
    s.invoke("d", "Eng")
    s.invoke("q", "^A")
    rows = project(SPEC, s.state()).children[-1].rows
    assert [r["name"] for r in rows] == ["Ann"]
    assert s.ui_facts()["visible_rows"]["lst"] == 1


def test_predicate_row_context_direct():
    st = {"x": 1}
    pred = {"op": "eq", "left": "$row.k", "right": "$state.x"}
    assert evaluate(pred, st, row={"k": 1})
    assert not evaluate(pred, st, row={"k": 2})


def test_validate_spec_rejects_misplaced_filter_when():
    bad = json.loads(json.dumps(SPEC))
    bad["screens"][0]["children"][0]["filterWhen"] = {"op": "truthy", "left": "q"}
    problems = __import__(
        "hostshift.render.semantics", fromlist=["validate_spec"]).validate_spec(bad)
    assert any("filterWhen" in p for p in problems)


def test_js_runtime_agrees_with_reference_on_filters():
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("  SKIP  node not available")
        return

    html = get_renderer("web").emit(SPEC)["index.html"]
    js = html.split("<script>")[2].split("</script>")[0]
    steps = [("d", None), ("d", "Eng"), ("q", "^C"), ("q", ""), ("d", "All")]

    def snap(session):
        f = session.ui_facts()
        return {"visible": f["visible_rows"]["lst"],
                "names": sorted(r["name"] for r in
                                project(SPEC, session.state()).children[-1].rows)}

    py = ReferenceSession(SPEC)
    trace_py = [snap(py)]
    for k, v in steps:
        py.invoke(k, v)
        trace_py.append(snap(py))

    shim = """
const fs = require('fs');
function mkEl(tag) { return { tagName: tag.toUpperCase(), children: [], attrs: {},
  setAttribute(k,v){this.attrs[k]=v}, getAttribute(k){return this.attrs[k]??null},
  appendChild(c){this.children.push(c);return c}, addEventListener(){},
  set innerHTML(v){this.children=[]}, get id(){return this.attrs.id||''} }; }
const root = mkEl('div');
global.CSS = { escape: (s) => s };
global.document = { createElement: mkEl, getElementById: () => root,
  querySelector: () => root.children[0] || null, addEventListener() {}, readyState: 'complete' };
global.window = {};
window.__HOSTSHIFT_SPEC__ = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
eval(fs.readFileSync(process.argv[3], 'utf8'));
const api = window.__hostshift;
const steps = JSON.parse(process.argv[4]);
const out = [];
function snap() { const f = api.facts();
  out.push({ visible: f.visible_rows.lst }); }
snap();
for (const [k, v] of steps) { api.invoke(k, v); snap(); }
console.log(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        (p / "runtime.js").write_text(js)
        (p / "shim.js").write_text(shim)
        (p / "spec.json").write_text(json.dumps(SPEC))
        out = subprocess.run(
            [node, str(p / "shim.js"), str(p / "spec.json"),
             str(p / "runtime.js"), json.dumps(steps)],
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, f"web runtime crashed:\n{out.stderr[:1200]}"
        trace_js = json.loads(out.stdout)

    assert len(trace_js) == len(trace_py)
    for i, (a, b) in enumerate(zip(trace_js, trace_py)):
        assert a["visible"] == b["visible"], f"step {i}: {a} != {b}"


def test_emitted_native_sources_handle_filter_when():
    from hostshift.render.compose import ComposeRenderer
    from hostshift.render.swiftui import SwiftUIRenderer
    from hostshift.render.tui import TuiRenderer

    for renderer, filename, marker in (
        (ComposeRenderer(), "MainActivity.kt", "filterWhen"),
        (SwiftUIRenderer(), "GeneratedApp.swift", "filterWhen"),
        (TuiRenderer(), "app.py", "filterWhen"),
    ):
        src = renderer.emit(SPEC)[filename]
        assert marker in src, f"{renderer.host} runtime lost filterWhen support"


if __name__ == "__main__":
    import traceback
    import unittest

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  SKIP  {fn.__name__}  ({exc})")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    ran = len(fns) - failed - skipped
    print(f"\n{ran}/{len(fns)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)
