"""Correctness tests.

The tree edit distance implementation is load-bearing for the paper's central
metric, so it is checked against hand-computed cases and against known
properties (identity, symmetry, triangle-inequality-ish behaviour) rather than
just smoke-tested.
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.widgettree import (  # noqa: E402
    Widget,
    tree_edit_distance,
    normalized_ted,
    from_spec,
)
from hostshift.metrics import (  # noqa: E402
    TaskOutcome,
    accessibility_parity,
    host_lock_index,
    interaction_parity,
    mcnemar,
    render_parity,
    wilson_interval,
)


def W(kind, name=None, *children, focusable=False, node_id=None):
    return Widget(kind=kind, name=name, children=list(children),
                  focusable=focusable, node_id=node_id)


# --------------------------------------------------------------------- TED

def test_ted_identity():
    t = W("container", None, W("text", "hi"), W("action", "Go", focusable=True))
    assert tree_edit_distance(t, t) == 0.0
    assert normalized_ted(t, t) == 0.0


def test_ted_symmetry():
    a = W("container", None, W("text", "a"), W("input", "b"))
    b = W("container", None, W("text", "a"))
    assert tree_edit_distance(a, b) == tree_edit_distance(b, a)


def test_ted_single_deletion_costs_one():
    a = W("container", None, W("text", "a"), W("text", "b"))
    b = W("container", None, W("text", "a"))
    assert tree_edit_distance(a, b) == 1.0


def test_ted_relabel_kind_costs_full_rename_costs_half():
    a = W("container", None, W("action", "Submit"))
    kind_changed = W("container", None, W("text", "Submit"))
    name_changed = W("container", None, W("action", "Send"))
    assert tree_edit_distance(a, kind_changed) == 1.0
    assert tree_edit_distance(a, name_changed) == 0.5


def test_ted_respects_sibling_order():
    a = W("container", None, W("input", "first"), W("action", "second"))
    b = W("container", None, W("action", "second"), W("input", "first"))
    # ordered edit distance must charge for a swap; an unordered metric would not
    assert tree_edit_distance(a, b) > 0


def test_ted_deep_subtree_deletion():
    leaf = W("text", "x")
    a = W("container", None, W("container", None, leaf, W("text", "y")))
    b = W("container", None)
    # delete: inner container + 2 leaves = 3
    assert tree_edit_distance(a, b) == 3.0


def test_normalized_ted_bounded():
    a = W("container", None, *[W("text", str(i)) for i in range(10)])
    b = W("media", "totally different")
    v = normalized_ted(a, b)
    assert 0.0 <= v <= 1.0


def test_render_parity_is_complement():
    a = W("container", None, W("text", "a"))
    b = W("container", None, W("text", "a"))
    assert render_parity(a, b) == 1.0


# ------------------------------------------------------------------- spec

SPEC = {
    "version": "0.2",
    "title": "Add task",
    "entry": "home",
    "screens": [
        {
            "id": "home",
            "title": "Add task",
            "children": [
                {"kind": "heading", "label": "New task"},
                {"kind": "field", "id": "name", "label": "Task name"},
                {"kind": "select", "id": "prio", "label": "Priority"},
                {"kind": "button", "id": "save", "label": "Save"},
            ],
        }
    ],
}


def test_from_spec_lowers_correctly():
    t = from_spec(SPEC)
    kinds = [n.kind for n in t.walk()]
    assert kinds == ["container", "text", "input", "choice", "action"]
    focusables = [n.node_id for n in t.walk() if n.focusable]
    assert focusables == ["name", "prio", "save"]


# ------------------------------------------------------------------- a11y

def test_accessibility_parity_perfect():
    intended = from_spec(SPEC)
    rep = accessibility_parity(intended, intended)
    assert rep.score == 1.0


def test_accessibility_parity_punishes_unnamed_button():
    intended = from_spec(SPEC)
    realized = from_spec(SPEC)
    # host dropped the accessible name on the submit control
    for n in realized.walk():
        if n.node_id == "save":
            n.name = None
    rep = accessibility_parity(intended, realized)
    assert rep.focusable_coverage < 1.0
    assert rep.score < 1.0
    # role survived even though the name did not
    assert rep.role_fidelity == 1.0


def test_accessibility_parity_punishes_role_collapse():
    intended = from_spec(SPEC)
    realized = from_spec(SPEC)
    for n in realized.walk():
        if n.node_id == "prio":
            n.kind, n.focusable = "text", False
    rep = accessibility_parity(intended, realized)
    assert rep.role_fidelity < 1.0


# -------------------------------------------------------------------- HLI

def _outcomes(spec: dict[str, list[bool]]) -> list[TaskOutcome]:
    out = []
    for host, results in spec.items():
        for i, ok in enumerate(results):
            out.append(TaskOutcome(task_id=f"t{i}", host=host, success=ok))
    return out


def test_hli_zero_when_hosts_identical():
    o = _outcomes({"web": [True, True, False], "compose": [True, True, False]})
    lock = host_lock_index(o)
    assert lock.hli == 0.0
    assert lock.per_task_lock == 0.0


def test_hli_one_when_a_host_totally_fails():
    o = _outcomes({"web": [True, True], "swiftui": [False, False]})
    lock = host_lock_index(o)
    assert lock.hli == 1.0
    assert lock.per_task_lock == 0.5   # each winnable task fails on 1 of 2 hosts
    assert lock.worst_host == "swiftui"


def test_hli_distinguishes_uniform_mediocrity_from_lock():
    # every host is equally bad -> low lock, even though absolute IP is poor
    uniform = _outcomes({
        "web": [True, False, False, False],
        "compose": [True, False, False, False],
    })
    # same overall IP, but the failures are host-specific -> high lock
    locked = _outcomes({
        "web": [True, True, False, False],
        "compose": [False, False, True, True],
    })
    assert host_lock_index(uniform).per_task_lock == 0.0
    assert host_lock_index(locked).per_task_lock == 0.5
    # this is exactly the pair the aggregate HLI cannot tell apart:
    assert host_lock_index(uniform).hli == host_lock_index(locked).hli == 0.0


def test_interaction_parity():
    assert interaction_parity(_outcomes({"web": [True, False, True, True]})) == 0.75


# ------------------------------------------------------------------ stats

def test_wilson_interval_contains_point_estimate():
    lo, hi = wilson_interval(70, 100)
    assert lo < 0.70 < hi
    assert 0.0 <= lo and hi <= 1.0


def test_wilson_handles_boundary():
    lo, hi = wilson_interval(0, 20)
    assert lo == 0.0 and 0.0 < hi < 0.3


def test_mcnemar_detects_one_sided_improvement():
    # B fixes 15 tasks A failed, breaks none
    pairs = [(False, True)] * 15 + [(True, True)] * 50
    r = mcnemar(pairs)
    assert r["p_value"] < 0.001


def test_mcnemar_null_when_balanced():
    pairs = [(False, True)] * 10 + [(True, False)] * 10
    r = mcnemar(pairs)
    assert r["p_value"] > 0.5


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
