"""Host renderers and session adapters.

    from hostshift.render import get_renderer, open_session

    r = get_renderer("web")
    files = r.emit(spec)              # {path: source}
    s = open_session(spec, "web")     # live, device-backed session

Device-backed sessions need their host present: Playwright for web, a simulator
or emulator plus the instrumentation bridge for SwiftUI and Compose, Textual for
the terminal. When one is unavailable, `open_session` raises rather than
silently substituting a simulated session -- an accidental substitution would
put modelled numbers into the results, which is not a recoverable mistake.

To exercise the pipeline without hosts, ask for simulation explicitly:

    open_session(spec, "compose", simulated=True)
"""

from __future__ import annotations

from .base import (
    CAREFUL,
    COMPOSE,
    NAIVE,
    PROFILES,
    RENDERERS,
    SWIFTUI,
    TUI,
    WEB,
    HostProfile,
    RendererProfile,
    RenderError,
    realize,
)
from .compose import ComposeRenderer, ComposeSession, SimulatedComposeSession
from .flutter import FlutterRenderer, SimulatedFlutterSession
from .semantics import SpecError, initial_state, project, ui_facts, validate_spec
from .session import (
    REFERENCE,
    ReferenceSession,
    SimulatedSession,
    assert_measurable,
    intended_tree,
)
from .swiftui import SimulatedSwiftUISession, SwiftUIRenderer, SwiftUISession
from .tui import SimulatedTuiSession, TuiRenderer, TuiSession
from .web import SimulatedWebSession, WebRenderer, WebSession

HOSTS = ("web", "swiftui", "compose", "flutter", "tui")

_RENDERERS = {
    "web": WebRenderer,
    "swiftui": SwiftUIRenderer,
    "compose": ComposeRenderer,
    "flutter": FlutterRenderer,
    "tui": TuiRenderer,
}

_SIMULATED = {
    "web": SimulatedWebSession,
    "swiftui": SimulatedSwiftUISession,
    "compose": SimulatedComposeSession,
    "flutter": SimulatedFlutterSession,
    "tui": SimulatedTuiSession,
}


def get_renderer(host: str):
    try:
        return _RENDERERS[host]()
    except KeyError:
        raise RenderError(f"unknown host {host!r}; known: {', '.join(HOSTS)}") from None


def emit_all(spec: dict) -> dict[str, dict[str, str]]:
    """Emit every host's sources for one spec. Useful for archiving the exact
    artifacts a run was scored against, which the release should include."""
    return {h: get_renderer(h).emit(spec) for h in HOSTS}


def open_session(spec: dict, host: str, *, simulated: bool = False,
                 renderer: str | RendererProfile = CAREFUL):
    """Open a session on `host`. Set simulated=True only for pipeline work.

    `renderer` selects the runtime-quality arm: "careful" does the platform's
    accessibility work explicitly, "naive" relies on host defaults. The pair
    isolates renderer expertise from the choice of representation.
    """
    if isinstance(renderer, str):
        try:
            renderer = RENDERERS[renderer]
        except KeyError:
            raise RenderError(
                f"unknown renderer {renderer!r}; known: {', '.join(RENDERERS)}") from None
    if simulated:
        if host not in _SIMULATED:
            raise RenderError(f"unknown host {host!r}")
        s = _SIMULATED[host](spec)
        s.renderer = renderer
        return s
    if renderer is not CAREFUL:
        raise RenderError(
            "device-backed sessions observe whatever the emitted app actually "
            "built; the naive arm needs a separately emitted naive app rather "
            "than a flag on the session")
    return get_renderer(host).open(spec)


__all__ = [
    "CAREFUL", "COMPOSE", "HOSTS", "NAIVE", "PROFILES", "RENDERERS",
    "RendererProfile", "SWIFTUI", "TUI", "WEB",
    "ComposeRenderer", "ComposeSession", "FlutterRenderer", "HostProfile",
    "ReferenceSession",
    "RenderError", "SimulatedComposeSession", "SimulatedSession",
    "SimulatedSwiftUISession", "SimulatedTuiSession", "SimulatedWebSession",
    "REFERENCE", "intended_tree",
    "SpecError", "SwiftUIRenderer", "SwiftUISession", "TuiRenderer", "TuiSession",
    "WebRenderer", "WebSession", "assert_measurable", "emit_all", "get_renderer",
    "initial_state", "open_session", "project", "realize", "ui_facts", "validate_spec",
]
