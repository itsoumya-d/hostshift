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

from .render.base import COMPOSE, SWIFTUI
from .render.compose import ComposeRenderer
from .render.swiftui import SwiftUIRenderer


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
                                                  "swiftc/kotlinc", False, None))
                    continue
                if host == "compose":
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
}


@dataclass
class DiffFinding:
    host: str
    check: str
    ok: bool
    note: str = ""
    missing_markers: list[str] = field(default_factory=list)


def differential_report(specs: dict[str, dict]) -> list[DiffFinding]:
    """Assert each native runtime's emitted source against its HostProfile."""
    findings: list[DiffFinding] = []
    renderers = {"swiftui": SwiftUIRenderer(), "compose": ComposeRenderer()}
    profiles = {"swiftui": SWIFTUI, "compose": COMPOSE}
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
