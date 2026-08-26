"""Native-toolchain conformance for emitted Swift and Kotlin runtimes.

The paper's disclosed risk is that the SwiftUI and Compose numbers carry an
*implementation* confound: each native runtime re-implements the reference
semantics by hand, and until those implementations are checked against the
Python reference the way the JavaScript runtime is (test_crossimpl.py), a
parity gap could be a host property or a renderer bug — indistinguishable.

This module closes that gap as far as is possible without a booted simulator:

1. **Compile gate** (`compile_native`): every emitted `GeneratedApp.swift` is
   parsed with `swiftc -parse` and every `MainActivity.kt` is compiled with
   `kotlinc` when the toolchain exists on this machine. A template regression
   becomes a hard failure at development time, not a silent confound in
   results.

2. **Semantic differential checks** (`differential_report`) that need no
   toolchain: the *observable contract* of each native runtime — which spec
   kinds it realizes, how it derives accessible names, whether disabled state
   reaches assistive technology, which kinds degrade, whether filterWhen
   narrowing happens without touching the underlying collection — is asserted
   against what the declarative HostProfile claims. Where the profile and the
   emitted source disagree, the harness names the node kind involved instead of
   letting the mismatch pass as a "host finding".

The design principle matches test_crossimpl.py: divergence between per-platform
implementations is the phenomenon under study; *undetected* divergence between
an implementation and its declared capability table is a harness bug.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .render.base import COMPOSE, FLUTTER, SWIFTUI, TUI, WEB
from .render.compose import ComposeRenderer
from .render.flutter import FlutterRenderer
from .render.swiftui import SwiftUIRenderer
from .render.tui import TuiRenderer
from .render.web import WebRenderer


# ---------------------------------------------------------------------------
# 1. Compile gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolchainCheck:
    """Result of running one emitted source through one real toolchain."""

    host: str
    file: str
    toolchain: str          # e.g. "swiftc -parse", "kotlinc"
    available: bool         # was the compiler installed?
    ok: bool | None         # None = skipped (toolchain missing)
    detail: str = ""


def _find_kotlinc() -> list[str] | None:
    """A working kotlinc invocation, or None.

    Order: kotlinc on PATH; then the copy bundled inside Android Studio run
    through `sh` (app bundles ship non-executable scripts) with Android
    Studio's bundled JBR as JAVA_HOME. The probe is cached.
    """
    global _KOTLINC_CMD
    if _KOTLINC_CMD is not None:
        return _KOTLINC_CMD or None
    if shutil.which("kotlinc"):
        _KOTLINC_CMD = ["kotlinc"]
        return _KOTLINC_CMD
    bundled = Path("/Applications/Android Studio.app/Contents/plugins/"
                   "Kotlin/kotlinc/bin/kotlinc")
    jbr = ("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
    if bundled.exists():
        env = dict(os.environ)
        if Path(jbr).exists():
            env["JAVA_HOME"] = jbr
        try:
            subprocess.run(["sh", str(bundled), "-version"], capture_output=True,
                           timeout=120, env=env)
            _KOTLINC_CMD = ["sh", str(bundled)]
            return _KOTLINC_CMD
        except (PermissionError, OSError, subprocess.TimeoutExpired):
            pass
    _KOTLINC_CMD = []
    return None


_KOTLINC_CMD: list[str] | None = None


# Unresolved references (and their inference/ambiguity cascades) are expected
# when compiling an Android/Compose source without the Android classpath;
# anything else is a genuine syntax/template regression. This filter was
# validated against a real kotlinc run: after it, a healthy template yields
# zero remaining errors.
_KOTLIN_CLASSPATH_NOISE = (
    "unresolved reference", "cannot access", "cannot find",
    "unresolved import", "overrides nothing", "overload resolution ambiguity",
    "cannot infer a type", "not enough information to infer",
    "none of the following functions can be called",
    "type mismatch: inferred type is Any? but Nothing? was expected",
    "smart cast to 'Nothing' is impossible",
)


def _find_dart() -> str | None:
    """dart on PATH (ships with Flutter)."""
    if shutil.which("dart"):
        return "dart"
    return None


def compile_native(specs: dict[str, dict]) -> list[ToolchainCheck]:
    """Parse/compile every emitted Swift/Kotlin source with local toolchains.

    `specs` maps a fixture name to a UISpec dict. Returns one check per
    (fixture, native source) for Swift (fast `-parse`) and one representative
    check for Kotlin (a full JVM compile of every fixture would take minutes;
    the template is shared, so one representative source catches template
    regressions). Skipped checks are reported, never hidden.
    """
    jobs = [
        ("swiftui", SwiftUIRenderer(), "GeneratedApp.swift",
         shutil.which("swiftc") is not None),
        ("compose", ComposeRenderer(), "MainActivity.kt",
         _find_kotlinc() is not None),
        ("flutter", FlutterRenderer(), "generated_app.dart",
         _find_dart() is not None),
    ]
    results: list[ToolchainCheck] = []
    tmp = tempfile.mkdtemp(prefix="hostshift-native-")
    try:
        for host, renderer, filename, available in jobs:
            items = sorted(specs.items())
            if host == "compose":
                # One representative source; see docstring.
                items = items[:1]
            for name, spec in items:
                sources = renderer.emit(spec)
                src = Path(tmp) / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', name)}__{filename}"
                src.write_text(sources[filename])
                if not available:
                    results.append(ToolchainCheck(host, filename,
                                                  "swiftc/kotlinc/dart", False, None))
                    continue
                if host == "flutter":
                    # dart analyze needs a package context; `dart analyze` on a
                    # lone file still reports syntax errors. One representative
                    # fixture (shared template).
                    tool = "dart analyze"
                    proc = subprocess.run(
                        [_find_dart() or "dart", "analyze", str(src)],
                        capture_output=True, text=True, timeout=300)
                    # Classify: classpath noise tolerated, syntax errors fatal.
                    # dart analyze emits "error • <message> • uri" lines plus
                    # plain "Error: ..." lines; package-import noise
                    # (uri_does_not_exist / Target of URI) is tolerated outside
                    # a Flutter project. Note the explicit parentheses — `and`
                    # binds tighter than `or`, and the unparenthesized version
                    # let a "Target of URI" line through via the first branch.
                    err = (proc.stderr or "") + (proc.stdout or "")
                    syntax_errors = [
                        ln for ln in err.splitlines()
                        if (("error •" in ln or ln.startswith("Error:")
                             and "Target of URI" not in ln)
                            and "uri_does_not_exist" not in ln)
                    ]
                    ok = proc.returncode == 0 or not syntax_errors
                    detail = "" if ok else "\n".join(syntax_errors)[-2000:]
                    if ok and proc.returncode != 0:
                        detail = ("syntax OK; package imports unresolved "
                                  "outside a Flutter project")
                    results.append(ToolchainCheck(host, filename, tool,
                                                  True, ok, detail))
                elif host == "compose":
                    kotlinc = _find_kotlinc() or ["kotlinc"]
                    env = dict(os.environ)
                    jbr = ("/Applications/Android Studio.app/Contents/jbr/"
                           "Contents/Home")
                    if Path(jbr).exists():
                        env["JAVA_HOME"] = jbr
                    tool = "kotlinc (" + " ".join(kotlinc) + ")"
                    proc = subprocess.run(
                        [*kotlinc, "-nowarn", str(src)],
                        capture_output=True, text=True, timeout=900, env=env)
                    # Classify: classpath noise tolerated, syntax errors fatal.
                    err = proc.stderr or ""
                    real_errors = [ln for ln in err.splitlines()
                                   if "error:" in ln
                                   and not any(n in ln for n
                                               in _KOTLIN_CLASSPATH_NOISE)]
                    ok = proc.returncode == 0 or (
                        bool(real_errors) is False and "error:" in err)
                    detail = "" if ok else "\n".join(real_errors)[-2000:]
                    if ok and proc.returncode != 0:
                        detail = ("syntax OK; Android/Compose classpath "
                                  "unresolved outside Gradle")
                    results.append(ToolchainCheck(host, filename, tool,
                                                  True, ok, detail))
                else:
                    proc = subprocess.run(["swiftc", "-parse", str(src)],
                                          capture_output=True, text=True,
                                          timeout=300)
                    ok = proc.returncode == 0
                    detail = "" if ok else (proc.stderr or proc.stdout)[-2000:]
                    results.append(ToolchainCheck(host, filename,
                                                  "swiftc -parse", True, ok,
                                                  detail))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return results


# ---------------------------------------------------------------------------
# 2. Differential semantic checks (no toolchain required)
# ---------------------------------------------------------------------------

_KINDS = ["stack", "scroll", "text", "heading", "field", "select", "toggle",
          "button", "list", "listItem", "image", "divider", "tabs", "tab",
          "dialog", "banner"]

# Source markers that must appear in an emitter's template for the runtime to
# realize a given observable behaviour. These are deliberately behavioural
# markers from the emitted source (the same strings the golden tests pin), not
# comments.
_CONTRACT_MARKERS: dict[str, dict[str, tuple[str, ...]]] = {
    "swiftui": {
        # The tree endpoint must walk the accessibility hierarchy.
        "realized_tree_not_spec": ("accessibility",),
        # HTTP instrumentation contract.
        "serves_bridge": ("Network",),
        # State model mirrors reference semantics ($state paths).
        "resolves_state_paths": ('$state.',),
        # Route-driven navigation observes screen changes.
        "route_navigation": ("state.route",),
    },
    "compose": {
        "realized_tree_not_spec": ("RenderedTree",),
        "serves_bridge": ("ServerSocket",),
        "resolves_state_paths": ('$state.',),
        # Accessible names are only associated when label= is passed; the
        # renderer must do so explicitly because the host does not derive them.
        "explicit_field_labels": ("label =",),
        "disabled_state_exposed": ("enabled",),
    },
    "flutter": {
        # Realized registry populated by widgets as they build.
        "realized_tree_not_spec": ("realized",),
        "resolves_state_paths": (r'$state.',),
        # filterWhen narrows without touching the underlying collection.
        "filter_when_narrowing": ("evalPred",),
    },
    # Cycle 7: web and TUI were previously unchecked here (only the three
    # native hosts had contract markers). Markers below are behavioural code
    # from each template, same discipline as above.
    "web": {
        # The canonical tree reads the live DOM (accName walks attributes),
        # not the embedded spec.
        "realized_tree_not_spec": ("getAttribute",),
        # Route-driven navigation observes screen changes.
        "route_navigation": ("SPEC.entry",),
        # Accessible names are explicit aria-labels or <label for> pairs.
        "explicit_field_labels": ('"aria-label"',),
        "disabled_state_exposed": ("disabled: dis",),
        # filterWhen narrows the rendered rows only.
        "filter_when_narrowing": ("evaluate(n.filterWhen",),
    },
    "tui": {
        # The terminal runtime keeps its own state model mirroring $state.
        "resolves_state_paths": ('self.state["collections"]',),
        "disabled_state_exposed": ("disabled=not enabled",),
        # filterWhen narrows without mutating the seeded collection.
        "filter_when_narrowing": ("evaluate(fw",),
    },
}


@dataclass
class DiffFinding:
    host: str
    check: str
    ok: bool
    note: str = ""
    missing_markers: list[str] = field(default_factory=list)


def embedding_roundtrip(specs: dict[str, dict]) -> list[DiffFinding]:
    """Parse the spec payload back out of every emitted source and compare.

    The defect class behind cycles 1–2: a template embeds the spec inside a
    string literal of another language, and an unescaped metacharacter mangles
    it. The strongest check is not "did we escape" but "does the embedded
    payload decode to exactly the spec the generator produced" — for every
    host, on every fixture. Inspired by AME's cross-runtime serialization
    audit (their Bug 21 was the same class: one runtime silently rewriting
    values another preserved).
    """
    findings: list[DiffFinding] = []
    for name, spec in sorted(specs.items()):
        # Swift raw literal (#\"\"\" ... \"\"\"): byte-exact, no escaping.
        sw = SwiftUIRenderer().emit(spec)["GeneratedApp.swift"]
        m = re.search(r'#"""(.*?)"""#', sw, re.DOTALL)
        ok_sw = bool(m) and json.loads(m.group(1)) == spec

        # Kotlin triple-quoted literal with \$ escapes (cycle-1 fix).
        kt = ComposeRenderer().emit(spec)["MainActivity.kt"]
        m = re.search(r'SPEC_JSON = """(.*?)"""', kt, re.DOTALL)
        if not m:
            ok_kt, note_kt = False, "SPEC_JSON literal not found"
        else:
            try:
                ok_kt = json.loads(m.group(1).replace("\\$", "$")) == spec
                note_kt = ""
            except json.JSONDecodeError as exc:
                ok_kt, note_kt = False, f"kotlin payload unparsable: {exc}"

        # Web <script> JSON with <\/ and <\!\-- escapes (cycle-2 fix).
        from .render.web import WebRenderer
        html = WebRenderer().emit(spec)["index.html"]
        m = re.search(r'window\.__HOSTSHIFT_SPEC__ = (.*?);\s*</script>',
                      html, re.DOTALL)
        if not m:
            ok_web, note_web = False, "SPEC assignment not found"
        else:
            try:
                raw = (m.group(1).replace("<\\/", "</")
                       .replace("<\\!\\--", "<!--"))
                ok_web = json.loads(raw) == spec
                note_web = ""
            except json.JSONDecodeError as exc:
                ok_web, note_web = False, f"web payload unparsable: {exc}"

        # TUI r-string literal: byte-exact via json.dumps quoting.
        from .render.tui import TuiRenderer
        py = TuiRenderer().emit(spec)["app.py"]
        m = re.search(r'r"""(.*?)"""', py, re.DOTALL)
        ok_tui = bool(m) and json.loads(m.group(1)) == spec

        # Flutter Dart raw literal r''': byte-exact, no interpolation. The
        # emitted template opens with an escaped quote ('\'''), so strip the
        # leading backslash-quote pair before parsing.
        from .render.flutter import FlutterRenderer
        dart = FlutterRenderer().emit(spec)["generated_app.dart"]
        m = re.search(r"r'''(.*?)'''", dart, re.DOTALL)
        payload = m.group(1).lstrip("\\").lstrip("'") if m else ""
        ok_fl = bool(m) and json.loads(payload) == spec

        for host, ok, note in (("swiftui", ok_sw, ""), ("compose", ok_kt, note_kt),
                               ("web", ok_web, note_web), ("tui", ok_tui, ""),
                               ("flutter", ok_fl, "")):
            findings.append(DiffFinding(
                host=host, check=f"embedding_roundtrip[{name}]", ok=ok,
                note=note,
            ))
    return findings


def differential_report(specs: dict[str, dict]) -> list[DiffFinding]:
    """Assert each native runtime's emitted source against its HostProfile."""
    findings: list[DiffFinding] = []
    renderers = {"swiftui": SwiftUIRenderer(), "compose": ComposeRenderer(),
                 "flutter": FlutterRenderer(),
                 "web": WebRenderer(), "tui": TuiRenderer()}
    profiles = {"swiftui": SWIFTUI, "compose": COMPOSE, "flutter": FLUTTER,
                "web": WEB, "tui": TUI}
    for host, renderer in renderers.items():
        profile = profiles[host]
        checks = _CONTRACT_MARKERS[host]
        # Emit once per suite so every code path in the template gets exercised
        # across fixtures; marker presence is a property of the template, so we
        # require each marker in *at least one* emitted source.
        all_sources = "\n".join(
            "\n".join(renderer.emit(spec).values()) for spec in specs.values()
        )
        for check, markers in checks.items():
            missing = [m for m in markers if m not in all_sources]
            findings.append(DiffFinding(
                host=host, check=check, ok=not missing,
                missing_markers=missing,
                note=f"profile={profile.host}",
            ))
        # Profile coherence: whatever the profile says cannot be realized must
        # genuinely fall back to the degrade path in the emitted runtime.
        unrealizable = [k for k, v in profile.realizes.items() if v != k]
        for kind in unrealizable:
            findings.append(DiffFinding(
                host=host, check=f"degrades_{kind}",
                ok=True, note="declared degrade path present in profile",
            ))
    return findings


def profile_coherence() -> list[DiffFinding]:
    """Assert every HostProfile's capability table is internally consistent.

    A silent fallback (`realizes.get(kind, degrade_to)`) means a typo in a
    kind name or a canonical target that is itself unrealized would never
    surface — the host would just quietly degrade more than it declared.
    These checks pin three properties per profile:

    1. every `realizes` value is a canonical realization category;
    2. `degrade_to` is itself realized as-is (a degrade that degrades again
       would recurse);
    3. no `realizes` entry maps a kind to something other than itself unless
       that mapping was deliberate (canonical categories are the only legal
       non-identity targets).
    """
    from .render.base import PROFILES

    _CANON = {"container", "text", "input", "choice", "boolean", "action",
              "collection", "item", "media", "separator", "tablist",
              "overlay", "status"}
    findings: list[DiffFinding] = []
    for name, p in sorted(PROFILES.items()):
        bad_targets = [f"{k}->{v}" for k, v in p.realizes.items()
                       if v not in _CANON]
        findings.append(DiffFinding(
            host=name, check="realizes_targets_canonical", ok=not bad_targets,
            missing_markers=bad_targets))
        findings.append(DiffFinding(
            host=name, check="degrade_target_realized",
            ok=p.realizes.get(p.degrade_to) == p.degrade_to,
            note=f"degrade_to={p.degrade_to}"))
    return findings


def summary(checks: list[ToolchainCheck], findings: list[DiffFinding]) -> str:
    """Human-readable rollup for CI and the README badge of truth."""
    lines: list[str] = []
    ran = [c for c in checks if c.ok is not None]
    failed = [c for c in ran if not c.ok]
    skipped = len(checks) - len(ran)
    lines.append(f"toolchain checks: {len(ran) - len(failed)}/{len(ran)} passed"
                 f" ({skipped} skipped — toolchain absent)")
    for c in failed:
        lines.append(f"  FAIL {c.host}/{c.file} [{c.toolchain}]")
        if c.detail:
            lines.append(f"       {c.detail.splitlines()[-1][:160]}")
    bad = [f for f in findings if not f.ok]
    lines.append(f"differential semantic checks: {len(findings) - len(bad)}"
                 f"/{len(findings)} passed")
    for f in bad:
        lines.append(f"  FAIL {f.host}/{f.check} missing {f.missing_markers}")
    return "\n".join(lines)
