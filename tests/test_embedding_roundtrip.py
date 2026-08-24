"""Hostile-spec round-trip: every embedding seam vs adversarial content.

The property under test is not "did we escape X" but "the app sees exactly
the spec the generator wrote", regardless of what characters the spec
contains. Each renderer's worst-case embedding is exercised here; the
per-fixture version of this check runs over all reference specs via
`hostshift render-check`.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.native_conformance import embedding_roundtrip
from hostshift.render.compose import ComposeRenderer
from hostshift.render.swiftui import SwiftUIRenderer
from hostshift.render.tui import TuiRenderer
from hostshift.render.web import WebRenderer

HOSTILE = {
    "version": "0.2",
    "title": '</script> "quotes" \\ back $dollar ' + '"' * 3 + "trip",
    "entry": "m",
    "screens": [{
        "id": "m",
        "children": [
            {"kind": "text", "text": "</script><script>alert(1)</script>"},
            {"kind": "field", "id": "q", "label": "$state.x <!-- hi",
             "bind": "query"},
            {"kind": "list", "id": "l", "of": "rows",
             "itemTemplate": [{"kind": "text", "text": "$row.name"}],
             "filterWhen": "$row.dept == $state.filter.department"},
        ],
    }],
    "state": {"filter": {"type": "object",
                         "default": {"department": 'All' + '"}' * 1 + '"' * 3}}},
    "collections": {"rows": {
        "fields": {"name": {"type": "string"}, "dept": {"type": "string"}},
        "seed": [{"name": "#" + '"' * 3, "dept": "\\$state"}],
    }},
}


def test_hostile_spec_roundtrips_through_every_host():
    findings = embedding_roundtrip({"hostile": HOSTILE})
    bad = [f for f in findings if not f.ok]
    assert not bad, [(f.host, f.check, f.note) for f in bad]
    hosts = {f.host for f in findings}
    assert hosts == {"swiftui", "compose", "web", "tui"}


def test_web_payload_has_no_raw_script_close():
    html = WebRenderer().emit(HOSTILE)["index.html"]
    start = html.find("window.__HOSTSHIFT_SPEC__")
    end = html.find("</script>", start)
    assert html[start:end].rstrip().endswith("};")


def test_kotlin_escapes_every_dollar_in_seed():
    kt = ComposeRenderer().emit(HOSTILE)["MainActivity.kt"]
    payload = kt.split('SPEC_JSON = """', 1)[1].split('"""', 1)[0]
    # After unescaping, the seed string must be intact — proving \$ escaping
    # round-trips rather than merely deleting dollars.
    parsed = json.loads(payload.replace("\\$", "$"))
    assert parsed["collections"]["rows"]["seed"][0]["dept"] == "\\$state"


def test_swift_and_tui_are_byte_exact():
    sw = SwiftUIRenderer().emit(HOSTILE)["GeneratedApp.swift"]
    assert json.loads(sw.split('#"""', 1)[1].split('"""#', 1)[0]) == HOSTILE
    py = TuiRenderer().emit(HOSTILE)["app.py"]
    compile(py, "app.py", "exec")
    assert json.loads(py.split('r"""', 1)[1].split('"""', 1)[0]) == HOSTILE


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
