"""Host realization: the seam where portability is won or lost.

A renderer's job has two halves. The obvious half is producing something that
runs. The half that matters for this benchmark is *realization*: what the host's
widget hierarchy and accessibility tree actually end up containing.

Those differ even when every renderer is faithful, because hosts differ in what
they can express and in how they derive accessible names. Two examples that
recur throughout the results:

  - A terminal host has no image widget. Something has to happen to a `media`
    node, and whatever happens is a structural loss the spec did not ask for.
  - Web derives an input's accessible name from an associated label element.
    Compose derives it only when the renderer passes `label=`. A terminal
    derives nothing. Identical specs, three different accessibility outcomes.

Encoding these as declarative per-host tables rather than burying them in each
renderer keeps them auditable, which matters because a reviewer will want to
know whether an observed host gap is a property of the host or a bug in one
renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..widgettree import Widget
from .semantics import ProjectedNode


@dataclass(frozen=True)
class HostProfile:
    """What a host can express, and how it names things."""

    host: str

    # Spec kind -> canonical kind. A kind absent from this map has no native
    # realization on the host and falls back to `degrade_to`.
    realizes: dict[str, str]

    # Does the host give a control an accessible name from its visible label
    # automatically, without the renderer doing anything extra?
    derives_name_from_label: bool

    # Where unsupported constructs land.
    degrade_to: str = "text"

    # Does the host expose a disabled state to assistive technology, or does it
    # merely dim the control visually? A host that only dims will fail
    # `enabled_state` probes even when it behaves correctly, and that gap is a
    # genuine accessibility finding rather than a harness artifact.
    exposes_enabled_state: bool = True

    # Does the host preserve the spec's node ids into its tree? Hosts that drop
    # them force the parity matcher onto positional matching.
    preserves_ids: bool = True


_FULL = {
    "screen": "container", "stack": "container", "scroll": "container",
    "text": "text", "heading": "text",
    "field": "input", "select": "choice", "toggle": "boolean",
    "button": "action", "list": "collection", "listItem": "item",
    "image": "media", "divider": "separator",
    "tabs": "tablist", "tab": "item",
    "dialog": "overlay", "banner": "status",
}

WEB = HostProfile(
    host="web",
    realizes=dict(_FULL),
    derives_name_from_label=True,
    exposes_enabled_state=True,
    preserves_ids=True,
)

SWIFTUI = HostProfile(
    host="swiftui",
    realizes=dict(_FULL),
    # SwiftUI surfaces a TextField's placeholder as its accessibility label, so
    # a visible label alone does name the control.
    derives_name_from_label=True,
    exposes_enabled_state=True,
    # SwiftUI has no stable notion of an author-supplied DOM id; the renderer
    # attaches accessibilityIdentifier, which survives, so ids are preserved.
    preserves_ids=True,
)

COMPOSE = HostProfile(
    host="compose",
    realizes=dict(_FULL),
    # Compose only names a text field when the renderer passes `label=`; a
    # neighbouring Text composable does not associate. Renderers that forget
    # this produce unlabelled fields, which is precisely the defect the Android
    # accessibility literature reports at scale.
    derives_name_from_label=False,
    exposes_enabled_state=True,
    preserves_ids=True,
)

FLUTTER = HostProfile(
    host="flutter",
    realizes=dict(_FULL),
    # Flutter's TextField names itself from its InputDecoration.labelText --
    # the framework associates the label with the SemanticsNode, so like web
    # (and unlike raw Compose) the host derives the accessible name.
    derives_name_from_label=True,
    exposes_enabled_state=True,
    preserves_ids=True,
)

TUI = HostProfile(
    host="tui",
    realizes={
        k: v for k, v in _FULL.items()
        if k not in ("image",)          # no raster surface in a terminal
    },
    derives_name_from_label=False,
    degrade_to="text",
    # Terminal widget toolkits generally have no assistive-technology channel
    # at all; disabled controls are dimmed, not announced.
    exposes_enabled_state=False,
    preserves_ids=True,
)

PROFILES: dict[str, HostProfile] = {
    p.host: p for p in (WEB, SWIFTUI, COMPOSE, FLUTTER, TUI)}


# ---------------------------------------------------------------------------
# Renderer quality -- the axis that separates representation from expertise
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RendererProfile:
    """How much work the renderer does beyond the host's defaults.

    This exists to answer the sharpest objection to the schema-versus-code
    comparison: condition B is not merely a different *representation*, it is a
    representation plus a renderer the author wrote, debugged, and deliberately
    taught to pass `label=` to Compose text fields. Comparing that against
    model-authored code conflates two effects, and reporting the combination as
    evidence for declarative schemas would be overclaiming.

    Splitting renderer quality onto its own axis decomposes the effect:

        A         vs  B-naive    -> the representation, alone
        B-naive   vs  B          -> renderer expertise, alone
        A         vs  B          -> the deployment strategy, end to end

    The naive renderer is not a strawman. It does exactly what a competent
    engineer does on a first pass: builds the widget tree the spec asked for and
    relies on platform defaults for everything else. Every gap it exhibits is a
    gap a real first-pass runtime would have.
    """

    name: str

    # Attach an explicit accessible name even when the host would not derive
    # one from the visible label. On Compose this is the `label=` parameter; on
    # SwiftUI an explicit accessibilityLabel; in a terminal, nothing can help.
    sets_explicit_a11y: bool

    # Propagate spec node ids into the host tree (testTag,
    # accessibilityIdentifier, DOM id). Without them the parity matcher falls
    # back to positional matching.
    preserves_ids: bool


CAREFUL = RendererProfile("careful", sets_explicit_a11y=True, preserves_ids=True)

NAIVE = RendererProfile("naive", sets_explicit_a11y=False, preserves_ids=False)

RENDERERS: dict[str, RendererProfile] = {r.name: r for r in (CAREFUL, NAIVE)}


def realize(
    node: ProjectedNode,
    profile: HostProfile,
    renderer: RendererProfile = CAREFUL,
) -> Widget:
    """Lower a projected spec node into the host's canonical widget tree.

    This is what `Session.widget_tree()` returns for the reference renderers.
    Real device-backed sessions build the same structure by reading the live
    accessibility tree, so the two are directly comparable.

    Two independent axes govern the result. `profile` is what the *host* can
    express and derive; `renderer` is how much work the runtime does on top of
    those defaults. Keeping them separate is what lets the experiment attribute
    a parity gap to the platform or to the implementation rather than blaming
    whichever is convenient.
    """
    kind = profile.realizes.get(node.kind, profile.degrade_to)

    # Accessible name. Three ways a control can end up named:
    #   - the spec supplied an explicit a11yLabel AND the renderer bothers to
    #     attach it;
    #   - the host derives a name from the visible label on its own;
    #   - the node is inherently textual, where the content is the name.
    # A careful renderer also attaches the visible label explicitly on hosts
    # that would not associate it, which is the single highest-value thing a
    # generative-UI runtime can do for accessibility.
    inherently_textual = kind in ("text", "status", "item")

    if node.a11y and node.a11y != node.label and renderer.sets_explicit_a11y:
        name = node.a11y
    elif inherently_textual and node.label:
        name = node.label
    elif node.label and profile.derives_name_from_label:
        name = node.label
    elif node.label and renderer.sets_explicit_a11y and profile.host != "tui":
        # The renderer wires the label to the control itself. A terminal has no
        # accessibility channel to wire it to, so no amount of renderer care
        # helps there -- and pretending otherwise would hide a real limit.
        name = node.label
    else:
        name = None

    focusable = kind in {"input", "choice", "boolean", "action"}
    keep_ids = profile.preserves_ids and renderer.preserves_ids

    w = Widget(
        kind=kind,
        name=name,
        node_id=node.node_id if keep_ids else None,
        focusable=focusable,
    )

    # A list materializes one item per row. Hosts that virtualize long lists
    # expose only the realized window, which is itself a parity difference the
    # benchmark should be able to see.
    if node.kind == "list" and node.rows:
        tappable = bool(node.row_action)
        for i, row in enumerate(node.rows):
            label = row.get(node.row_label) if node.row_label else None
            w.children.append(Widget(
                kind="item",
                name=label or _row_label(row),
                node_id=f"{node.node_id}#{i}" if (node.node_id and keep_ids) else None,
                focusable=tappable,
            ))

    for c in node.children:
        w.children.append(realize(c, profile, renderer))
    return w


def _row_label(row: dict) -> str | None:
    for key in ("title", "name", "label", "subject", "email"):
        if isinstance(row.get(key), str):
            return row[key]
    return None


def host_ui_facts(reference: dict, profile: HostProfile) -> dict:
    """Adjust reference UI facts for what the host can actually expose.

    A host that cannot announce disabled state should not be credited with
    passing an `enabled_state` probe. Dropping the key (rather than reporting
    False) makes the oracle report 'host did not report enablement', which is
    the honest outcome and distinguishes 'wrong' from 'unobservable'.
    """
    facts = dict(reference)
    if not profile.exposes_enabled_state:
        facts = {k: v for k, v in facts.items() if k != "enabled"}
    return facts


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class Session(Protocol):
    """A live rendering of a spec on one host."""

    host: str

    def widget_tree(self) -> Widget: ...
    def state(self) -> dict: ...
    def ui_facts(self) -> dict: ...

    def actions(self) -> list[dict]:
        """Interactable elements, as the operator sees them.

        Each entry: {id, kind, name, enabled, value, options}. This is the
        action space both operators work against; keeping it identical across
        hosts is what makes an interaction-parity gap attributable to the
        interface rather than to the operator's view of it.
        """

    def invoke(self, node_id: str, value: object | None = None) -> None:
        """Activate a control, optionally supplying a value."""

    def close(self) -> None: ...


@runtime_checkable
class Renderer(Protocol):
    host: str

    def emit(self, spec: dict) -> dict[str, str]:
        """Produce host source files as {relative_path: contents}."""

    def open(self, spec: dict) -> Session:
        """Bring the spec up on this host and return a live session."""


class RenderError(RuntimeError):
    """Raised when a host cannot bring a spec up at all.

    Distinct from a task failure: a spec that will not render scores zero
    interaction parity, but for a reason the failure taxonomy should separate
    from a spec that renders and then misbehaves.
    """
