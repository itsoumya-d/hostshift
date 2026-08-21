"""Session implementations.

Two families, and the distinction between them is load-bearing:

  SimulatedSession  -- runs the reference interpreter and applies a host's
                       realization rules analytically. It *models* what the host
                       would do.

  Device-backed      -- WebSession, SwiftUISession, ComposeSession, TuiSession.
                       They run the real thing and *observe* what the host
                       actually did.

Only the second kind may produce numbers in the paper. A simulated session
cannot discover that Compose drops an accessible name in a case the profile
table failed to anticipate -- it can only replay the table, which would turn the
results into a restatement of my own assumptions. The guard below makes using
one for results an explicit, deliberate act rather than an oversight.

Simulated sessions remain genuinely useful: they exercise the pipeline before
any device exists, they provide the no-host control condition, and they let the
task suite be debugged for free.
"""

from __future__ import annotations

import copy
import os

from ..widgettree import Widget
from . import semantics as sem
from .base import (
    CAREFUL,
    PROFILES,
    HostProfile,
    RendererProfile,
    RenderError,
    host_ui_facts,
    realize,
)

# The reference profile: full fidelity, nothing lost. Used for the control
# condition, which establishes the ceiling every real host is measured against.
REFERENCE = HostProfile(
    host="reference",
    realizes={
        "screen": "container", "stack": "container", "scroll": "container",
        "text": "text", "heading": "text", "field": "input", "select": "choice",
        "toggle": "boolean", "button": "action", "list": "collection",
        "listItem": "item", "image": "media", "divider": "separator",
        "tabs": "tablist", "tab": "item", "dialog": "overlay", "banner": "status",
    },
    derives_name_from_label=True,
    exposes_enabled_state=True,
    preserves_ids=True,
)


def intended_tree(spec: dict, state: dict | None = None) -> Widget:
    """The tree a host *should* have realized, given the current state.

    Render parity must be scored against this rather than against a static walk
    of the spec document. Specs contain conditionally visible nodes -- error
    banners, empty states, branch-specific steps -- and a host that correctly
    hides one would otherwise be penalised for the node's absence, turning
    correct behaviour into a parity loss. The reference profile is used so that
    no host's limitations leak into the thing every host is measured against.
    """
    st = sem.initial_state(spec) if state is None else state
    return realize(sem.project(spec, st), REFERENCE, CAREFUL)


class SimulatedSession:
    """Reference interpreter plus a host profile. Models, does not observe."""

    simulated = True

    def __init__(self, spec: dict, profile: HostProfile | str = REFERENCE,
                 renderer: RendererProfile = CAREFUL):
        if isinstance(profile, str):
            profile = PROFILES.get(profile) or REFERENCE
        problems = sem.validate_spec(spec)
        fatal = [p for p in problems if "has no label" not in p]
        if fatal:
            raise RenderError("; ".join(fatal[:4]))
        self.spec = copy.deepcopy(spec)
        self.profile = profile
        self.renderer = renderer
        self.host = profile.host
        self._state = sem.initial_state(self.spec)
        self._closed = False

    # -- observation ------------------------------------------------------

    def widget_tree(self) -> Widget:
        return realize(sem.project(self.spec, self._state), self.profile, self.renderer)

    def state(self) -> dict:
        st = copy.deepcopy(self._state)
        st.pop("_events", None)
        return st

    def ui_facts(self) -> dict:
        return host_ui_facts(sem.ui_facts(self.spec, self._state), self.profile)

    def actions(self) -> list[dict]:
        proj = sem.project(self.spec, self._state)
        out = []
        for n in proj.walk():
            if n.node_id and n.focusable:
                out.append({
                    "id": n.node_id,
                    "kind": n.kind,
                    "name": n.a11y or n.label,
                    "enabled": n.enabled,
                    "value": n.value,
                    "options": n.options,
                })
            # Tappable rows are addressed as "<listId>#<index>". Indexing rather
            # than naming keeps rows selectable when two of them share a label,
            # which seeded collections routinely do.
            if n.kind == "list" and n.row_action and n.node_id:
                for i, row in enumerate(n.rows):
                    out.append({
                        "id": f"{n.node_id}#{i}",
                        "kind": "listItem",
                        "name": str(row.get(n.row_label or "", "")) or None,
                        "enabled": n.enabled,
                        "value": None,
                        "options": [],
                    })
        return out

    # -- interaction ------------------------------------------------------

    def invoke(self, node_id: str, value: object | None = None) -> None:
        proj = sem.project(self.spec, self._state)

        if "#" in node_id:
            list_id, _, idx = node_id.partition("#")
            lst = next((n for n in proj.walk()
                        if n.node_id == list_id and n.kind == "list"), None)
            if lst is None or not lst.row_action:
                raise RenderError(f"no tappable list {list_id!r} on the current screen")
            try:
                row = lst.rows[int(idx)]
            except (ValueError, IndexError):
                raise RenderError(f"row {idx!r} out of range for {list_id!r}") from None
            if not lst.enabled:
                return
            self._state = sem.apply_actions(
                lst.row_action, self._state, self.spec, value, row)
            return

        node = next((n for n in proj.walk() if n.node_id == node_id), None)
        if node is None:
            raise RenderError(f"no such control {node_id!r} on the current screen")
        if not node.enabled:
            # A disabled control that still fires is one of the most common
            # lowering bugs, so the reference refuses -- otherwise a host that
            # got it wrong would look identical to one that got it right.
            return

        if node.kind in ("field", "select") and node.bind:
            self._state = sem.apply_action(
                {"op": "set", "target": node.bind, "value": value}, self._state, self.spec)
        elif node.kind == "toggle" and node.bind:
            new = (not bool(node.value)) if value is None else bool(value)
            self._state = sem.apply_action(
                {"op": "set", "target": node.bind, "value": new}, self._state, self.spec)

        if node.action:
            self._state = sem.apply_actions(
                node.action, self._state, self.spec, value)

    def close(self) -> None:
        self._closed = True


class ReferenceSession(SimulatedSession):
    """The no-host control: the spec's intended behaviour with zero lowering.

    Worth running for every task even though it is free. It separates
    'the generated spec was wrong' from 'the host mangled a correct spec',
    which is the distinction the failure taxonomy turns on and the first thing a
    reviewer will ask about a low interaction-parity number.
    """

    def __init__(self, spec: dict):
        super().__init__(spec, REFERENCE)


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def assert_measurable(session, *, allow_simulated: bool = False) -> None:
    """Refuse to record paper results from a simulated session.

    Set HOSTSHIFT_ALLOW_SIMULATED=1 to override for pipeline work. The override
    is intentionally noisy to set, because the failure it prevents -- publishing
    modelled numbers as measured ones -- is not recoverable after submission.
    """
    if not getattr(session, "simulated", False):
        return
    if allow_simulated or os.environ.get("HOSTSHIFT_ALLOW_SIMULATED") == "1":
        return
    raise RenderError(
        f"{type(session).__name__} for host {session.host!r} is simulated: it "
        f"replays the host profile table rather than observing a running host. "
        f"Results from it are not measurements. Use a device-backed session, or "
        f"set HOSTSHIFT_ALLOW_SIMULATED=1 if you are only exercising the pipeline."
    )
