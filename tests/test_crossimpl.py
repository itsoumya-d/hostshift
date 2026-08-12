"""Cross-implementation agreement: JavaScript runtime vs. Python reference.

Each host runs its own native reimplementation of the UISpec semantics, which
is deliberate -- divergence between per-platform runtimes is the phenomenon
under study. But that design creates a confound the paper has to rule out: if
the web runtime simply implements the semantics *wrong*, its interaction-parity
score measures my bug rather than the host.

This test drives the emitted JavaScript through a minimal DOM shim and asserts
it agrees with the Python reference on every observable the oracle reads. Any
divergence it finds is a renderer defect to fix before the run, not a finding.

Equivalent harnesses are owed for the Swift and Kotlin runtimes; until those
exist, their interaction-parity numbers carry an unquantified implementation
risk that the paper must disclose rather than assume away.

Skips cleanly when Node is unavailable.
"""

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render import ReferenceSession, get_renderer  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = {
    name: ROOT / "tasks" / "reference_specs" / f"{name}.json"
    for name in ("form-001", "list-001")
}
SPEC_PATH = SPECS["form-001"]
SPEC = json.loads(SPEC_PATH.read_text())
NODE = shutil.which("node")

DOM_SHIM = r"""
const fs = require('fs');
function mkEl(tag) {
  return { tagName: tag.toUpperCase(), children: [], attrs: {}, _txt: '',
    set textContent(v) { this._txt = v }, get textContent() { return this._txt },
    setAttribute(k, v) { this.attrs[k] = v },
    getAttribute(k) { return this.attrs[k] ?? null },
    appendChild(c) { this.children.push(c); return c },
    addEventListener() {}, set innerHTML(v) { this.children = [] },
    get id() { return this.attrs.id || '' } };
}
const root = mkEl('div');
global.CSS = { escape: (s) => s };
global.document = { createElement: mkEl, getElementById: () => root,
  querySelector: () => root.children[0] || null,
  addEventListener() {}, readyState: 'complete' };
global.window = {};
window.__HOSTSHIFT_SPEC__ = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
eval(fs.readFileSync(process.argv[3], 'utf8'));

const api = window.__hostshift;
const script = JSON.parse(process.argv[4]);
const trace = [];
trace.push(snapshot());
for (const step of script) {
  api.invoke(step.id, step.value === undefined ? null : step.value);
  trace.push(snapshot());
}
function snapshot() {
  const f = api.facts();
  return {
    state: api.state(),
    error_visible: f.error_visible,
    empty_state_visible: f.empty_state_visible,
    enabled: f.enabled,
    field_values: f.field_values,
    actions: api.actions().map((a) => ({ id: a.id, enabled: a.enabled, value: a.value })),
  };
}
console.log(JSON.stringify(trace));
"""


def _js_trace(script: list[dict], spec_name: str = "form-001") -> list[dict]:
    spec_path = SPECS[spec_name]
    html = get_renderer("web").emit(json.loads(spec_path.read_text()))["index.html"]
    js = html.split("<script>")[2].split("</script>")[0]
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        (p / "runtime.js").write_text(js)
        (p / "shim.js").write_text(DOM_SHIM)
        out = subprocess.run(
            [NODE, str(p / "shim.js"), str(spec_path), str(p / "runtime.js"),
             json.dumps(script)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            raise AssertionError(f"web runtime crashed:\n{out.stderr[:1200]}")
        return json.loads(out.stdout)


def _py_trace(script: list[dict], spec_name: str = "form-001") -> list[dict]:
    s = ReferenceSession(json.loads(SPECS[spec_name].read_text()))

    def snap():
        f = s.ui_facts()
        return {
            "state": s.state(),
            "error_visible": f["error_visible"],
            "empty_state_visible": f["empty_state_visible"],
            "enabled": f["enabled"],
            "field_values": f["field_values"],
            "actions": [{"id": a["id"], "enabled": a["enabled"], "value": a["value"]}
                        for a in s.actions()],
        }

    trace = [snap()]
    for step in script:
        s.invoke(step["id"], step.get("value"))
        trace.append(snap())
    return trace


SCRIPTS = {
    "happy_path": [
        {"id": "name", "value": "Dana Reyes"},
        {"id": "email", "value": "dana@example.com"},
        {"id": "message", "value": "Please call me back"},
    ],
    "invalid_then_corrected": [
        {"id": "email", "value": "bogus"},
        {"id": "name", "value": "Dana"},
        {"id": "email", "value": "dana@example.com"},
        {"id": "message", "value": "hello"},
    ],
    "premature_submit": [
        {"id": "submit"},
        {"id": "name", "value": "Dana"},
        {"id": "submit"},
    ],
    "completed_submit": [
        {"id": "name", "value": "Dana Reyes"},
        {"id": "email", "value": "dana@example.com"},
        {"id": "message", "value": "Please call me back"},
        {"id": "submit"},
    ],
}

LIST_SCRIPTS = {
    "row_tap_and_resolve": [
        {"id": "tickets#0"},
        {"id": "resolve"},
    ],
    "row_tap_then_back_then_other_row": [
        {"id": "tickets#3"},
        {"id": "back"},
        {"id": "tickets#1"},
        {"id": "resolve"},
    ],
}


def _compare(label: str, spec_name: str = "form-001", scripts=None) -> None:
    script = (scripts or SCRIPTS)[label]
    js, py = _js_trace(script, spec_name), _py_trace(script, spec_name)
    assert len(js) == len(py), f"{label}: trace lengths differ"
    for i, (a, b) in enumerate(zip(js, py)):
        for key in ("error_visible", "empty_state_visible", "field_values",
                    "enabled", "actions"):
            assert a[key] == b[key], (
                f"{label} step {i}: JS and Python disagree on {key}\n"
                f"  js = {a[key]}\n  py = {b[key]}"
            )
        assert a["state"].get("collections") == b["state"].get("collections"), (
            f"{label} step {i}: collections diverged"
        )


def test_agreement_happy_path():
    _compare("happy_path")


def test_agreement_invalid_then_corrected():
    _compare("invalid_then_corrected")


def test_agreement_premature_submit():
    """A disabled submit must be inert in both runtimes. If one fires and the
    other does not, every task with a validation gate is unscoreable."""
    _compare("premature_submit")


def test_agreement_completed_submit():
    """Exercises action sequences and $state templates across both runtimes."""
    _compare("completed_submit")


def test_agreement_row_tap_and_resolve():
    """Row actions and $row templates. Reimplemented independently in JS, so
    this is where a divergence would most plausibly hide."""
    _compare("row_tap_and_resolve", "list-001", LIST_SCRIPTS)


def test_agreement_row_navigation_round_trip():
    _compare("row_tap_then_back_then_other_row", "list-001", LIST_SCRIPTS)


if __name__ == "__main__":
    import traceback

    if not NODE:
        print("SKIP  node not available; cross-implementation agreement unverified")
        sys.exit(0)

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
