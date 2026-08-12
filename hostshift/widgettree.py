"""Canonical widget tree + tree edit distance.

The portability claim in HostShift rests on being able to compare, structurally,
what a host *actually rendered* against what the specification *asked for* --
and to do so in a vocabulary that is not biased toward any one host. That is
what this module provides.

Every host adapter (React DOM, SwiftUI view hierarchy, Compose semantics tree,
TUI widget tree) lowers its native hierarchy into `Widget` nodes drawn from
CANONICAL_KINDS. Render Parity is then 1 - normalized tree edit distance
between the realized tree and the spec-intended tree.

Tree edit distance is Zhang-Shasha (1989), which gives an optimal mapping under
insert/delete/relabel with ordered children -- the right model here, because UI
sibling order is semantically meaningful (focus order, reading order).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

# The canonical vocabulary. Deliberately small. A construct earns a place here
# only if all four reference hosts can realize it faithfully; anything else
# would let a host "win" parity by rendering something the others cannot.
CANONICAL_KINDS = {
    "container",   # stack / scroll / any pure grouping
    "text",        # static text, including headings
    "input",       # free text or numeric entry
    "choice",      # select, radio group, picker
    "boolean",     # toggle, switch, checkbox
    "action",      # button, tappable row with an action
    "collection",  # list / table
    "item",        # a row within a collection
    "media",       # image
    "separator",
    "tablist",
    "overlay",     # dialog, sheet, modal
    "status",      # banner, error, toast
}

# How each host's native node types lower into the canonical vocabulary.
# Kept as data (not code) so that adding a host is a table edit, and so the
# mapping itself can be published as an artifact and argued with.
HOST_LOWERING: dict[str, dict[str, str]] = {
    "web": {
        "div": "container", "section": "container", "main": "container",
        "form": "container", "nav": "container", "span": "text", "p": "text",
        "h1": "text", "h2": "text", "h3": "text", "label": "text",
        "input:text": "input", "input:number": "input", "textarea": "input",
        "select": "choice", "input:radio": "choice",
        "input:checkbox": "boolean",
        "button": "action", "a": "action",
        "ul": "collection", "ol": "collection", "table": "collection",
        "li": "item", "tr": "item",
        "img": "media", "hr": "separator",
        "[role=tablist]": "tablist", "dialog": "overlay",
        "[role=alert]": "status", "[role=status]": "status",
    },
    "swiftui": {
        "VStack": "container", "HStack": "container", "ZStack": "container",
        "ScrollView": "container", "Form": "container", "Group": "container",
        "Text": "text", "Label": "text",
        "TextField": "input", "SecureField": "input", "TextEditor": "input",
        "Picker": "choice", "Menu": "choice",
        "Toggle": "boolean",
        "Button": "action", "NavigationLink": "action",
        "List": "collection", "ForEach": "collection",
        "Row": "item",
        "Image": "media", "AsyncImage": "media", "Divider": "separator",
        "TabView": "tablist", "Sheet": "overlay", "Alert": "overlay",
    },
    "compose": {
        "Column": "container", "Row": "container", "Box": "container",
        "Surface": "container", "Scaffold": "container",
        "LazyColumn": "collection", "LazyRow": "collection",
        "Text": "text",
        "TextField": "input", "OutlinedTextField": "input",
        "DropdownMenu": "choice", "ExposedDropdownMenuBox": "choice",
        "Switch": "boolean", "Checkbox": "boolean",
        "Button": "action", "TextButton": "action", "IconButton": "action",
        "ListItem": "item",
        "Image": "media", "Icon": "media",
        "Divider": "separator", "HorizontalDivider": "separator",
        "TabRow": "tablist", "AlertDialog": "overlay", "ModalBottomSheet": "overlay",
        "Snackbar": "status",
    },
    "tui": {
        "Box": "container", "Vertical": "container", "Horizontal": "container",
        "Static": "text", "Label": "text",
        "Input": "input", "Select": "choice", "Checkbox": "boolean",
        "Button": "action", "ListView": "collection", "ListItem": "item",
        "Rule": "separator", "Tabs": "tablist", "Modal": "overlay",
    },
}

# The spec's own node kinds lower into the same vocabulary, giving us the
# "intended" tree to compare realized trees against.
SPEC_LOWERING: dict[str, str] = {
    "stack": "container", "scroll": "container",
    "text": "text", "heading": "text",
    "field": "input", "select": "choice", "toggle": "boolean",
    "button": "action", "list": "collection", "listItem": "item",
    "image": "media", "divider": "separator",
    "tabs": "tablist", "tab": "item",
    "dialog": "overlay", "banner": "status",
}


@dataclass
class Widget:
    """A node in a canonical widget tree."""

    kind: str
    name: str | None = None          # accessible name, if the host exposed one
    node_id: str | None = None       # spec id, when traceable
    focusable: bool = False
    children: list["Widget"] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in CANONICAL_KINDS:
            raise ValueError(
                f"{self.kind!r} is not canonical; extend CANONICAL_KINDS "
                f"deliberately or fix the host lowering table"
            )

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def size(self) -> int:
        return sum(1 for _ in self.walk())


def from_spec(spec: dict) -> Widget:
    """Build the intended canonical tree from a UISpec document.

    This is the reference every host is scored against. Note that it is derived
    from the spec alone -- no host is privileged as ground truth, which is the
    whole point.
    """

    def conv(node: dict) -> Widget:
        kind = SPEC_LOWERING.get(node.get("kind", ""), "container")
        return Widget(
            kind=kind,
            name=node.get("a11yLabel") or node.get("label"),
            node_id=node.get("id"),
            focusable=kind in {"input", "choice", "boolean", "action"},
            children=[conv(c) for c in node.get("children", []) or []],
        )

    screens = spec.get("screens", [])
    entry = spec.get("entry")
    target = next((s for s in screens if s.get("id") == entry), screens[0] if screens else None)
    if target is None:
        return Widget(kind="container")
    return Widget(
        kind="container",
        name=target.get("title") or spec.get("title"),
        node_id=target.get("id"),
        children=[conv(c) for c in target.get("children", []) or []],
    )


def lower(host: str, native_kind: str) -> str:
    """Lower a host-native node type into the canonical vocabulary."""
    table = HOST_LOWERING.get(host)
    if table is None:
        raise KeyError(f"no lowering table for host {host!r}")
    return table.get(native_kind, "container")


# --------------------------------------------------------------------------
# Zhang-Shasha ordered tree edit distance
# --------------------------------------------------------------------------

def default_relabel_cost(a: Widget, b: Widget) -> float:
    """Cost of turning node `a` into node `b`.

    Kind mismatch is a full-cost edit: rendering a button as static text is a
    functional break, not a cosmetic one. Accessible-name mismatch is charged at
    half, because a wrong label degrades but does not remove the affordance.
    """
    if a.kind != b.kind:
        return 1.0
    if _norm(a.name) != _norm(b.name):
        return 0.5
    return 0.0


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def tree_edit_distance(
    a: Widget,
    b: Widget,
    relabel: Callable[[Widget, Widget], float] = default_relabel_cost,
    insert_cost: float = 1.0,
    delete_cost: float = 1.0,
) -> float:
    """Optimal ordered tree edit distance (Zhang & Shasha, 1989).

    O(|a| * |b| * min(depth(a), leaves(a)) * min(depth(b), leaves(b))).
    Fine at UI-tree scale (hundreds of nodes).
    """
    an, al, akr = _postorder_index(a)
    bn, bl, bkr = _postorder_index(b)
    m, n = len(an), len(bn)

    treedist = [[0.0] * n for _ in range(m)]

    for i in akr:
        for j in bkr:
            _forest_distance(
                i, j, an, bn, al, bl, treedist, relabel, insert_cost, delete_cost
            )
    return treedist[m - 1][n - 1] if m and n else float(max(m, n))


def _postorder_index(root: Widget) -> tuple[list[Widget], list[int], list[int]]:
    """Return (postorder nodes, leftmost-leaf index per node, keyroots)."""
    nodes: list[Widget] = []
    leftmost: list[int] = []

    def visit(node: Widget) -> int:
        first_child_lm: int | None = None
        for c in node.children:
            lm = visit(c)
            if first_child_lm is None:
                first_child_lm = lm
        idx = len(nodes)
        nodes.append(node)
        leftmost.append(first_child_lm if first_child_lm is not None else idx)
        return leftmost[idx]

    if root is not None:
        visit(root)

    seen: set[int] = set()
    keyroots: list[int] = []
    for i in range(len(nodes) - 1, -1, -1):
        if leftmost[i] not in seen:
            seen.add(leftmost[i])
            keyroots.append(i)
    keyroots.sort()
    return nodes, leftmost, keyroots


def _forest_distance(
    i: int,
    j: int,
    an: Sequence[Widget],
    bn: Sequence[Widget],
    al: Sequence[int],
    bl: Sequence[int],
    treedist: list[list[float]],
    relabel: Callable[[Widget, Widget], float],
    ins: float,
    dele: float,
) -> None:
    li, lj = al[i], bl[j]
    rows, cols = i - li + 2, j - lj + 2
    fd = [[0.0] * cols for _ in range(rows)]

    for x in range(1, rows):
        fd[x][0] = fd[x - 1][0] + dele
    for y in range(1, cols):
        fd[0][y] = fd[0][y - 1] + ins

    for x in range(1, rows):
        for y in range(1, cols):
            ni, nj = li + x - 1, lj + y - 1
            if al[ni] == li and bl[nj] == lj:
                fd[x][y] = min(
                    fd[x - 1][y] + dele,
                    fd[x][y - 1] + ins,
                    fd[x - 1][y - 1] + relabel(an[ni], bn[nj]),
                )
                treedist[ni][nj] = fd[x][y]
            else:
                px = al[ni] - li
                py = bl[nj] - lj
                fd[x][y] = min(
                    fd[x - 1][y] + dele,
                    fd[x][y - 1] + ins,
                    fd[px][py] + treedist[ni][nj],
                )


def normalized_ted(a: Widget, b: Widget, **kw) -> float:
    """Tree edit distance normalized to [0, 1] by the larger tree size.

    Normalizing by max(|a|,|b|) (rather than |a|+|b|) keeps the metric
    interpretable: 1.0 means "nothing survived", 0.0 means "structurally
    identical".
    """
    denom = max(a.size(), b.size()) or 1
    return min(1.0, tree_edit_distance(a, b, **kw) / denom)
