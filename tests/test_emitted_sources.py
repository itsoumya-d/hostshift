"""Golden tests for emitted host sources.

Every bug these tests catch is a bug that shipped once already: the Compose
template emitted doubled braces and an orphaned duplicated fragment; the Swift
template declared SPEC before specJSON and embedded raw CR/LF control
characters inside string literals; neither native app rendered past its entry
screen. Emitted sources are program output -- they get checked like program
output.

When a real compiler is available (swiftc on macOS) the emitted Swift is also
parse-checked; otherwise that case skips rather than fails.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render.base import PROFILES
from hostshift.render.compose import ComposeRenderer
from hostshift.render.semantics import validate_spec
from hostshift.render.swiftui import SwiftUIRenderer
from hostshift.render.tui import TuiRenderer
from hostshift.render.web import WebRenderer

SPECS = sorted(pathlib.Path("tasks/reference_specs").glob("*.json"))[:6]
RENDERERS = {
    "web": WebRenderer(),
    "swiftui": SwiftUIRenderer(),
    "compose": ComposeRenderer(),
    "tui": TuiRenderer(),
}


def _emit_all():
    out = {}
    for path in SPECS:
        spec = json.loads(path.read_text())
        validate_spec(spec)
        for host, renderer in RENDERERS.items():
            files = renderer.emit(spec)
            assert files, f"{host} emitted nothing for {path.name}"
            out[(host, path.name)] = files
    return out


EMITTED = _emit_all()


def _sources(host, filename):
    """Emitted `filename` contents for every sampled spec on one host."""
    return [files[filename] for (h, _), files in sorted(EMITTED.items())
            if h == host]


def _names(host):
    return [name for (h, name) in sorted(EMITTED) if h == host]


# ---------------------------------------------------------------------------
# Cross-host
# ---------------------------------------------------------------------------

def test_every_host_emits_for_every_sampled_spec():
    assert len(EMITTED) == len(SPECS) * len(RENDERERS)


def test_profiles_cover_every_renderer_host():
    for host in RENDERERS:
        assert host in PROFILES


# ---------------------------------------------------------------------------
# Compose (Kotlin)
# ---------------------------------------------------------------------------

def test_kotlin_no_doubled_braces():
    # The original template mixed {{ and {{{{ escaping; the output contained
    # lines like `class SpecState {{` which is not Kotlin.
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert "{{" not in kt and "}}" not in kt, name


def test_kotlin_braces_and_parens_balanced():
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert kt.count("{") == kt.count("}"), f"brace imbalance in {name}"
        assert kt.count("(") == kt.count(")"), f"paren imbalance in {name}"


def test_kotlin_required_imports_and_single_definitions():
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert "import org.json.JSONArray" in kt, f"missing JSONArray import in {name}"
        assert "import org.json.JSONObject" in kt
        assert kt.count("fun reset()") == 1, f"duplicated reset() fragment in {name}"
        assert kt.count("class MainActivity") == 1


def test_kotlin_dollar_interpolation_escaped():
    # In Kotlin, "$payload" inside a string literal interpolates a variable.
    # Spec template references must be escaped as \$ so they stay literal.
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert '"\\$payload"' in kt, name
        assert '"\\$state."' in kt, name


def test_kotlin_navigation_observes_route():
    # The original app rendered only the entry screen, making multi-screen
    # tasks structurally unwinnable on this host.
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert "remember(state.route)" in kt, name
        assert "ScreenRoot(state)" in kt, name


def test_kotlin_tree_endpoint_reads_realized_registry():
    for name, kt in zip(_names("compose"), _sources("compose", "MainActivity.kt")):
        assert "object RenderedTree" in kt, name
        assert "/tree" in kt and "realizedTree(state)" in kt, name


# ---------------------------------------------------------------------------
# SwiftUI (Swift)
# ---------------------------------------------------------------------------

def test_swift_declaration_order():
    # The original emitted `let SPEC = ... specJSON ...` three lines before
    # `let specJSON` was declared.
    for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
        assert sw.index("let specJSON") < sw.index("let SPEC:"), name


def test_swift_no_raw_control_characters_in_string_literals():
    # Raw CR/LF inside a single-line Swift string literal will not compile;
    # the source must carry backslash escapes, not the characters themselves.
    for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
        assert "\r" not in sw, f"raw carriage return in {name}"
        assert "\\r\\n" in sw, f"expected escaped CRLF sequences in {name}"


def test_swift_action_contract_complete():
    for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
        for field in ('"id":', '"kind":', '"name":', '"enabled":', '"value":', '"options":'):
            assert field in sw, f"{field} missing from actions contract in {name}"


def test_swift_navigation_observes_route():
    for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
        assert "struct RootView" in sw, name
        assert "state.route" in sw, name
        assert "currentScreenChildren" not in sw, name


def test_swift_braces_balanced():
    for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
        assert sw.count("{") == sw.count("}"), f"brace imbalance in {name}"
        assert sw.count("(") == sw.count(")"), f"paren imbalance in {name}"


def test_swift_parses_under_swiftc_when_available():
    if shutil.which("swiftc") is None:
        print("  SKIP  swiftc not installed")
        return
    workdir = tempfile.mkdtemp(prefix="hostshift-swift-")
    try:
        for name, sw in zip(_names("swiftui"), _sources("swiftui", "GeneratedApp.swift")):
            src = pathlib.Path(workdir) / f"{re.sub(r'[^a-zA-Z0-9]+', '_', name)}.swift"
            src.write_text(sw)
            proc = subprocess.run(
                ["swiftc", "-parse", str(src)],
                capture_output=True, text=True, timeout=120,
            )
            assert proc.returncode == 0, (
                f"emitted Swift failed to parse for {name}:\n{proc.stderr[:2000]}"
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Web / TUI
# ---------------------------------------------------------------------------

def test_web_runtime_embeds_contract():
    for name, html in zip(_names("web"), _sources("web", "index.html")):
        assert "window.__hostshift" in html, name
        for fn in ("state()", "facts()", "tree()", "actions()", "invoke("):
            assert fn in html, f"{fn} missing from web runtime in {name}"


def test_tui_app_embeds_state_and_spec():
    for name, py in zip(_names("tui"), _sources("tui", "app.py")):
        assert "self.state" in py, name
        assert "SPEC" in py, name


if __name__ == "__main__":
    import traceback

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
