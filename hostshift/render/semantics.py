"""Reference semantics for UISpec.

This module is the definition of what a spec *means*. Every host is judged
against it, so it is deliberately host-free: no rendering, no framework, no I/O.
Pure state in, pure state out.

Having one executable definition of correctness matters more here than it would
in an ordinary UI framework. Without it, "the SwiftUI build behaves differently
from the React build" is an argument about which one is right. With it, both are
measured against the same referee, and disagreement becomes a number.

The interpreter is also what powers the TUI host and the no-host control, which
is why it is worth keeping honest and well tested.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


class SpecError(ValueError):
    """Raised when a spec is structurally unusable.

    Deliberately loud. A generator that emits a malformed spec should be scored
    as having failed, not quietly rendered as an empty screen -- silently
    tolerating bad input would let condition B launder its failures into
    'the agent could not complete the task', which is a different claim.
    """


# ---------------------------------------------------------------------------
# State construction
# ---------------------------------------------------------------------------

_DEFAULTS = {"string": "", "number": 0, "boolean": False, "date": None, "enum": None}


def initial_state(spec: dict) -> dict:
    """Build the starting runtime state from a spec's declarations."""
    st: dict[str, Any] = {"collections": {}, "route": spec.get("entry"), "_events": []}

    for name, decl in (spec.get("state") or {}).items():
        _assign(st, name, decl.get("default", _DEFAULTS.get(decl.get("type"), None)))

    for name, decl in (spec.get("collections") or {}).items():
        st["collections"][name] = copy.deepcopy(decl.get("seed") or [])

    return st


def _assign(state: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = state
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def resolve(state: dict, path: str | None) -> Any:
    """Read a dotted path. Missing paths read as None rather than raising --
    a predicate over an unset field is a normal condition, not a bug.

    A leading ``$state.`` is accepted and stripped, so predicates can be
    written the same way action templates are ($state.filter.department).
    """
    if not path:
        return None
    if path.startswith("$state."):
        path = path[len("$state."):]
    if path.endswith(".length"):
        base = resolve(state, path[: -len(".length")])
        return len(base) if isinstance(base, (list, str, dict)) else None
    cur: Any = state
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, dict) and p in (cur.get("collections") or {}):
            cur = cur["collections"][p]
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def evaluate(pred: dict | None, state: dict, row: dict | None = None) -> bool:
    """Evaluate a predicate. A missing predicate is vacuously true, which is
    what `visibleWhen`/`enabledWhen` being absent should mean.

    When `row` is given (list `filterWhen` evaluation), a `$row.field` left
    operand reads from that row instead of the state tree.
    """
    if pred is None:
        return True
    op = pred.get("op")

    if op in ("and", "or"):
        clauses = pred.get("clauses") or []
        results = [evaluate(c, state, row) for c in clauses]
        return all(results) if op == "and" else any(results)
    if op == "not":
        clauses = pred.get("clauses") or []
        if len(clauses) != 1:
            raise SpecError("`not` takes exactly one clause")
        return not evaluate(clauses[0], state, row)

    left_path = pred.get("left")
    if row is not None and isinstance(left_path, str) and left_path.startswith("$row."):
        left = row.get(left_path[len("$row."):])
    else:
        left = resolve(state, left_path)
    right = pred.get("right")
    # The right operand may reference state ($state.path) -- e.g. a search box
    # bound to `query` compared against $row.name, or a numeric threshold held
    # in state. Literals pass through untouched.
    if isinstance(right, str) and right.startswith("$state."):
        right = resolve(state, right[len("$state."):])

    if op == "truthy":
        return bool(left)
    if op == "falsy":
        return not bool(left)
    if op == "nonempty":
        return left is not None and len(left) > 0 if hasattr(left, "__len__") else bool(left)
    if op == "matches":
        return bool(left is not None and re.search(str(right), str(left)))
    if op == "eq":
        return _loose_eq(left, right)
    if op == "ne":
        return not _loose_eq(left, right)

    if op in ("gt", "lt", "gte", "lte"):
        # Ordering against a missing value is false, not an exception: a
        # comparison on an unfilled field is a normal state during data entry.
        if left is None or right is None:
            return False
        try:
            a, b = float(left), float(right)
        except (TypeError, ValueError):
            a, b = str(left), str(right)
        return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[op]

    raise SpecError(f"unknown predicate op {op!r}")


def _loose_eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    if isinstance(a, str) and isinstance(b, str):
        return a.strip() == b.strip()
    return a == b


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


_TEMPLATE_PREFIXES = ("$state.", "$row.", "$payload")


def expand(value: Any, state: dict, row: dict | None = None, payload: Any = None) -> Any:
    """Resolve `$state.path`, `$row.field` and `$payload` inside an action value.

    Without this, an action cannot read anything -- a submit button can append a
    row to a collection but has no way to say *which* row, which makes the most
    common interaction in any form unexpressible. Templates are resolved
    recursively so a whole record can be assembled declaratively:

        {"op": "append", "target": "contacts",
         "value": {"name": "$state.name", "email": "$state.email"}}
    """
    if isinstance(value, str) and value.startswith(_TEMPLATE_PREFIXES):
        if value == "$payload":
            return payload
        if value.startswith("$state."):
            return resolve(state, value[len("$state."):])
        field = value[len("$row."):]
        return (row or {}).get(field)
    if isinstance(value, dict):
        return {k: expand(v, state, row, payload) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, state, row, payload) for v in value]
    return value


def apply_actions(
    actions: Any, state: dict, spec: dict, payload: Any = None, row: dict | None = None
) -> dict:
    """Apply a single action or a sequence, threading state through.

    Sequences matter because real controls do more than one thing: a submit
    button records a row *and* flips a confirmation flag. Forcing one action per
    control would push that composition into the host renderers, where each
    platform would invent its own answer -- exactly the divergence the benchmark
    is trying to attribute rather than create.
    """
    if actions is None:
        return state
    seq = actions if isinstance(actions, list) else [actions]
    st = state
    for a in seq:
        st = apply_action(a, st, spec, payload, row)
    return st


def apply_action(
    action: dict | None, state: dict, spec: dict, payload: Any = None,
    row: dict | None = None,
) -> dict:
    """Apply one action, returning a new state. Never mutates the input.

    Immutability is not stylistic here: the harness replays action sequences
    when diagnosing a failure, and in-place mutation would make a replay
    diverge from the original run.
    """
    if action is None:
        return state
    st = copy.deepcopy(state)

    if not evaluate(action.get("guardWhen"), st):
        st["_events"].append({"op": action.get("op"), "blocked": True})
        return st

    op = action.get("op")
    target = action.get("target")

    if op == "navigate":
        if target not in {s.get("id") for s in spec.get("screens", [])}:
            raise SpecError(f"navigate to unknown screen {target!r}")
        st["route"] = target

    elif op == "set":
        value = action["value"] if "value" in action else payload
        if action.get("from"):
            value = resolve(st, action["from"])
        _assign(st, target, expand(value, st, row, payload))

    elif op == "clear":
        decl = (spec.get("state") or {}).get(target, {})
        _assign(st, target, decl.get("default", _DEFAULTS.get(decl.get("type"))))

    elif op == "append":
        rows = st["collections"].setdefault(target, [])
        new_row = expand(action.get("value"), st, row, payload)
        if new_row is None:
            new_row = payload
        if not isinstance(new_row, dict):
            raise SpecError(f"append to {target!r} needs an object row")
        rows.append(copy.deepcopy(new_row))

    elif op == "remove":
        rows = st["collections"].get(target, [])
        match = expand(action.get("value"), st, row, payload) or payload or {}
        st["collections"][target] = [r for r in rows if not _row_matches(r, match)]

    elif op == "update":
        rows = st["collections"].get(target, [])
        spec_payload = expand(action.get("value"), st, row, payload) or payload or {}
        where = spec_payload.get("where", {})
        changes = spec_payload.get("set", {})
        for r in rows:
            if _row_matches(r, where):
                r.update(copy.deepcopy(changes))

    elif op == "submit":
        st["_events"].append({"op": "submit", "target": target})
        if target:
            _assign(st, target, True)

    elif op == "dismiss":
        st["_events"].append({"op": "dismiss", "target": target})
        if target:
            _assign(st, target, False)

    else:
        raise SpecError(f"unknown action op {op!r}")

    return st


def _row_matches(row: dict, match: dict) -> bool:
    return all(_loose_eq(row.get(k), v) for k, v in match.items())


# ---------------------------------------------------------------------------
# Screen projection
# ---------------------------------------------------------------------------


@dataclass
class ProjectedNode:
    """A spec node resolved against current state.

    Visibility and enablement are decided here, once, so that every host makes
    the same decision. If a host disagrees with this projection, that
    disagreement is the measurement -- not an implementation detail to paper
    over inside each renderer.
    """

    kind: str
    node_id: str | None
    label: str | None
    a11y: str | None
    tone: str | None
    enabled: bool
    focusable: bool
    bind: str | None
    value: Any
    options: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    action: Any = None
    row_action: Any = None
    row_label: str | None = None
    children: list[ProjectedNode] = field(default_factory=list)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


FOCUSABLE_KINDS = {"field", "select", "toggle", "button"}


def project(spec: dict, state: dict) -> ProjectedNode:
    """Project the current screen into a resolved node tree."""
    screens = spec.get("screens") or []
    if not screens:
        raise SpecError("spec has no screens")
    route = state.get("route") or spec.get("entry")
    screen = next((s for s in screens if s.get("id") == route), None)
    if screen is None:
        raise SpecError(f"route {route!r} matches no screen")

    def conv(node: dict) -> ProjectedNode | None:
        if not evaluate(node.get("visibleWhen"), state):
            return None
        kind = node.get("kind", "stack")
        bind = node.get("bind")
        declared = (spec.get("state") or {}).get(bind or "", {})
        pn = ProjectedNode(
            kind=kind,
            node_id=node.get("id"),
            label=node.get("label"),
            a11y=node.get("a11yLabel") or node.get("label"),
            tone=node.get("tone"),
            enabled=evaluate(node.get("enabledWhen"), state),
            focusable=kind in FOCUSABLE_KINDS,
            bind=bind,
            value=resolve(state, bind) if bind else None,
            options=list(declared.get("options") or []),
            action=node.get("action"),
            row_action=node.get("rowAction"),
            row_label=node.get("rowLabel"),
        )
        if kind == "list" and node.get("of"):
            rows = list((state.get("collections") or {}).get(node["of"], []))
            # filterWhen narrows what the list *shows* without touching the
            # underlying collection -- the declarative way to express a
            # filtered table. Rows failing the predicate are not rendered,
            # so visible_row_count sees the filtered count.
            fw = node.get("filterWhen")
            if fw is not None:
                rows = [r for r in rows if evaluate(fw, state, row=r)]
            pn.rows = rows
        for c in node.get("children") or []:
            got = conv(c)
            if got is not None:
                pn.children.append(got)
        return pn

    root = ProjectedNode(
        kind="screen", node_id=screen.get("id"), label=screen.get("title"),
        a11y=screen.get("title") or spec.get("title"), tone=None,
        enabled=True, focusable=False, bind=None, value=None,
    )
    for c in screen.get("children") or []:
        got = conv(c)
        if got is not None:
            root.children.append(got)
    return root


# ---------------------------------------------------------------------------
# UI facts
# ---------------------------------------------------------------------------


def ui_facts(spec: dict, state: dict) -> dict:
    """Derive the oracle's UI facts from a projection.

    These are the observations that genuinely cannot live in application state.
    Real hosts must produce the same shape by reading their accessibility tree;
    this is the reference implementation they are compared against.
    """
    root = project(spec, state)
    nodes = list(root.walk())

    banners = [n for n in nodes if n.kind == "banner"]
    facts: dict[str, Any] = {
        "error_visible": any(n.tone == "error" for n in banners),
        "empty_state_visible": any(n.tone == "empty" for n in banners),
        "enabled": {n.node_id: n.enabled for n in nodes if n.node_id and n.focusable},
        "field_values": {n.node_id: n.value for n in nodes
                         if n.node_id and n.kind in ("field", "select")},
        "options": {n.node_id: n.options for n in nodes if n.node_id and n.options},
        "visible_rows": {},
    }
    for n in nodes:
        if n.kind == "list" and n.rows is not None:
            key = n.node_id or "rows"
            facts["visible_rows"][key] = len(n.rows)
    # Also key visible_rows by collection name, since tasks assert on the
    # collection rather than on whatever id the generator happened to choose.
    for node in _spec_lists(spec):
        of = node.get("of")
        if of:
            proj = next((n for n in nodes if n.kind == "list" and n.node_id == node.get("id")), None)
            facts["visible_rows"][of] = len(proj.rows) if proj else 0
    return facts


def _iter_actions(node: dict):
    for key in ("action", "rowAction"):
        act = node.get(key)
        if act is None:
            continue
        yield from (act if isinstance(act, list) else [act])


def _spec_lists(spec: dict) -> list[dict]:
    out: list[dict] = []

    def walk(n: dict):
        if n.get("kind") == "list":
            out.append(n)
        for c in n.get("children") or []:
            walk(c)

    for s in spec.get("screens") or []:
        for c in s.get("children") or []:
            walk(c)
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_spec(spec: dict) -> list[str]:
    """Structural validation used as the repair loop's check for condition B.

    Both conditions get the same number of repair rounds; this is what
    condition B's rounds are spent against, and the freeform condition's
    equivalent is the framework compiler.
    """
    problems: list[str] = []
    if spec.get("version") != "0.2":
        problems.append(f"version must be '0.2', got {spec.get('version')!r}")

    screens = spec.get("screens") or []
    if not screens:
        problems.append("no screens")
    ids = [s.get("id") for s in screens]
    if len(set(ids)) != len(ids):
        problems.append("duplicate screen ids")
    if spec.get("entry") not in ids:
        problems.append(f"entry {spec.get('entry')!r} matches no screen")

    known_state = set((spec.get("state") or {}).keys())
    known_coll = set((spec.get("collections") or {}).keys())
    seen_node_ids: set[str] = set()

    def walk(n: dict, screen_id: str):
        kind = n.get("kind")
        nid = n.get("id")
        if nid:
            if nid in seen_node_ids:
                problems.append(f"duplicate node id {nid!r}")
            seen_node_ids.add(nid)
        if kind in FOCUSABLE_KINDS and not (n.get("label") or n.get("a11yLabel")):
            # Not fatal, but it is the single most common accessibility defect
            # in generated UI, so it is surfaced rather than tolerated.
            problems.append(f"{screen_id}: focusable {kind} {nid or '<anon>'} has no label")
        if kind == "list" and n.get("of") not in known_coll:
            problems.append(f"{screen_id}: list references unknown collection {n.get('of')!r}")
        if n.get("bind") and n["bind"].split(".")[0] not in known_state:
            problems.append(f"{screen_id}: bind to undeclared state {n['bind']!r}")
        if kind == "banner" and n.get("tone") not in (None, "info", "success", "error", "empty"):
            problems.append(f"{screen_id}: banner tone {n.get('tone')!r} invalid")
        for act in _iter_actions(n):
            if act.get("op") == "navigate" and act.get("target") not in ids:
                problems.append(
                    f"{screen_id}: navigate to unknown screen {act.get('target')!r}")
        if n.get("rowAction") and kind != "list":
            problems.append(f"{screen_id}: rowAction on a {kind}, which has no rows")
        if kind == "list" and n.get("rowAction") and not n.get("rowLabel"):
            # Rows a user can tap must be nameable, or the host has nothing to
            # announce and the operator has nothing to select by.
            problems.append(f"{screen_id}: list {nid or '<anon>'} has rowAction but no rowLabel")
        if "filterWhen" in n:
            if kind != "list":
                problems.append(f"{screen_id}: filterWhen on a {kind}, which has no rows")
            elif not isinstance(n["filterWhen"], dict) or "op" not in n["filterWhen"]:
                problems.append(
                    f"{screen_id}: list {nid or '<anon>'} filterWhen must be a predicate")
        for c in n.get("children") or []:
            walk(c, screen_id)

    for s in screens:
        for c in s.get("children") or []:
            walk(c, s.get("id", "?"))

    return problems
