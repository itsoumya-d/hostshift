"""Native conformance: toolchain gates + differential semantic checks.

The headline test is the Kotlin dollar-sign escape: UISpec state references
are literally `$state.x` / `$row.x`, and Kotlin interpolates `$name` inside
triple-quoted literals. A renderer that interpolates the spec JSON unescaped
compiles a filterWhen predicate into garbage — or fails to compile at all.
This was found by driving kotlinc over emitted sources, not by reading code.
"""

import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.native_conformance import (
    compile_native,
    differential_report,
)
from hostshift.render.compose import ComposeRenderer
from hostshift.render.swiftui import SwiftUIRenderer


FILTER_SPEC = {
    "version": "0.2",
    "title": "Employee directory",
    "entry": "directory",
    "state": {
        "filter": {"type": "object", "default": {"department": "All"}},
    },
    "collections": {
        "employees": {
            "fields": {"name": {"type": "string"}, "dept": {"type": "string"}},
            "seed": [
                {"name": "Ada", "dept": "Eng"},
                {"name": "Grace", "dept": "Ops"},
            ],
        }
    },
    "screens": [{
        "id": "directory",
        "title": "Directory",
        "children": [{
            "kind": "list", "id": "roster", "of": "employees",
            "itemTemplate": [{"kind": "text", "text": "$row.name"}],
            "filterWhen": "$row.dept == $state.filter.department",
        }],
    }],
}

PLAIN_SPEC = {
    "version": "0.2",
    "title": "Counter",
    "entry": "main",
    "screens": [{
        "id": "main",
        "children": [
            {"kind": "heading", "text": "Counter"},
            {"kind": "button", "id": "inc", "label": "Increment"},
        ],
    }],
}


def test_kotlin_escapes_state_dollars():
    """`$state.` must survive into the emitted Kotlin as an escaped literal."""
    kt = ComposeRenderer().emit(FILTER_SPEC)["MainActivity.kt"]
    assert "\\$state.filter.department" in kt
    assert "\\$row.dept" in kt
    # And the raw (unescaped) form must not appear inside SPEC_JSON's quotes.
    assert '"$row.dept' not in kt.split('SPEC_JSON = """')[1].split('"""')[0]


def test_swift_heredoc_preserves_state_dollars():
    """Swift raw literals (#\"\"\"...\"\"\") need no escaping; verify round-trip."""
    sw = SwiftUIRenderer().emit(FILTER_SPEC)["GeneratedApp.swift"]
    assert "$state.filter.department" in sw
    assert "\\$state" not in sw  # escaping would corrupt Swift raw strings


def test_compile_native_runs_and_reports():
    checks = compile_native({"filter": FILTER_SPEC, "plain": PLAIN_SPEC})
    swift = [c for c in checks if c.host == "swiftui"]
    for c in swift:
        if shutil.which("swiftc") is None:
            assert c.ok is None  # skipped, reported not hidden
        else:
            assert c.ok is True, f"{c.toolchain} failed: {c.detail[:400]}"
    compose = [c for c in checks if c.host == "compose"]
    assert len(compose) == 1  # one representative source
    for c in compose:
        # Either skipped (no kotlinc) or passed; never silently failed.
        assert c.ok in (None, True), f"{c.toolchain}: {c.detail[:400]}"


def test_differential_checks_pass_on_current_templates():
    findings = differential_report({"filter": FILTER_SPEC})
    bad = [f for f in findings if not f.ok]
    assert not bad, [f"{f.host}/{f.check} missing {f.missing_markers}" for f in bad]
    # Compose must be checked for explicit labels (host does not derive them);
    # SwiftUI has no such marker because its profile derives names.
    hosts = {f.host for f in findings}
    assert hosts == {"swiftui", "compose"}


def test_web_escapes_script_closing_tags():
    """A `</script>` inside spec content must not terminate the embedded
    <script> block (spec truncation + XSS vector). Found by the cycle-2
    escaping-seam audit."""
    from hostshift.render.web import WebRenderer

    hostile = {"version": "0.2", "title": "t", "entry": "m",
               "screens": [{"id": "m", "children": [
                   {"kind": "text", "text": "</script><script>alert(1)</script>"},
               ]}]}
    html = WebRenderer().emit(hostile)["index.html"]
    start = html.find("window.__HOSTSHIFT_SPEC__")
    end = html.find("</script>", start)
    block = html[start:end]
    assert block.rstrip().endswith("};"), "SPEC script block truncated early"
    assert "</scr" + "ipt>" not in block, "unescaped </script> inside payload"


def test_tui_raw_string_survives_hostile_spec():
    """The TUI embeds the spec in an r\"\"\" literal; json.dumps quoting must
    keep it parseable even with quotes, backslashes and triple quotes."""
    from hostshift.render.tui import TuiRenderer

    hostile = {"version": "0.2", "title": 'q " \\ x', "entry": "m",
               "screens": [{"id": "m", "children": [
                   {"kind": "text", "text": 'say """ hi'},
               ]}]}
    src = TuiRenderer().emit(hostile)["app.py"]
    compile(src, "app.py", "exec")
    payload = src.split('r"""', 1)[1].split('"""', 1)[0]
    import json as _json
    parsed = _json.loads(payload)
    assert parsed["title"] == 'q " \\ x'


if __name__ == "__main__":
    import traceback

    failed = 0
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    raise SystemExit(1 if failed else 0)
