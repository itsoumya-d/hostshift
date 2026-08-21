"""Row actions, action sequences, and value templates.

These three capabilities were added after the first reference spec exposed that
UISpec 0.2 could not express list-detail navigation -- the `list_detail`
category, 13 of the 100 tasks -- and could not build a record from form state.
They are load-bearing for most of the suite, so they get their own tests.

The last test in this file is the one that matters most: a null check that a
correct spec driven by a perfect operator produces zero host-lock. If that ever
fails, the benchmark is manufacturing its own headline finding.
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("HOSTSHIFT_ALLOW_SIMULATED", "1")

from hostshift.metrics import TaskOutcome, host_lock_index  # noqa: E402
from hostshift.oracle import grade, load_suite  # noqa: E402
from hostshift.render import (  # noqa: E402
    HOSTS,
    ReferenceSession,
    RenderError,
    open_session,
    validate_spec,
)
from hostshift.render import semantics as sem  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
LIST = json.loads((ROOT / "tasks" / "reference_specs" / "list-001.json").read_text())
FORM = json.loads((ROOT / "tasks" / "reference_specs" / "form-001.json").read_text())
SUITE = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}


# ----------------------------------------------------------- templates

def test_state_template_resolves():
    st = {"name": "Dana", "nested": {"x": 7}}
    assert sem.expand("$state.name", st) == "Dana"
    assert sem.expand("$state.nested.x", st) == 7
    assert sem.expand("$state.missing", st) is None


def test_row_and_payload_templates_resolve():
    assert sem.expand("$row.title", {}, {"title": "T"}) == "T"
    assert sem.expand("$payload", {}, None, "P") == "P"


def test_templates_resolve_recursively_inside_records():
    st = {"a": 1, "b": "two"}
    out = sem.expand({"x": "$state.a", "deep": {"y": "$state.b"}, "lit": "plain"}, st)
    assert out == {"x": 1, "deep": {"y": "two"}, "lit": "plain"}


def test_non_template_strings_pass_through_untouched():
    assert sem.expand("just a $ sign", {}) == "just a $ sign"
    assert sem.expand("price is $5", {}) == "price is $5"


# ----------------------------------------------------------- sequences

def test_action_sequence_threads_state():
    spec = {"version": "0.2", "entry": "s",
            "state": {"a": {"type": "number", "default": 0},
                      "b": {"type": "number", "default": 0}},
            "screens": [{"id": "s", "children": []}]}
    st = sem.initial_state(spec)
    st = sem.apply_actions([{"op": "set", "target": "a", "value": 5},
                            {"op": "set", "target": "b", "from": "a"}], st, spec)
    assert st["a"] == 5 and st["b"] == 5


def test_form_submit_builds_a_record_from_state():
    """The failure that motivated templates: a submit button could append to a
    collection but had no way to say what to append."""
    s = ReferenceSession(FORM)
    s.invoke("name", "Dana Reyes")
    s.invoke("email", "dana@example.com")
    s.invoke("message", "Please call me back")
    s.invoke("submit")
    rows = s.state()["collections"]["contacts"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Dana Reyes"
    assert rows[0]["email"] == "dana@example.com"
    assert s.state()["submitted"] is True


# ---------------------------------------------------------- row actions

def test_list_spec_validates():
    assert validate_spec(LIST) == []


def test_rowaction_without_rowlabel_is_rejected():
    """A row a user can activate must be nameable, or assistive technology has
    nothing to announce and the operator has nothing to select by."""
    bad = json.loads(json.dumps(LIST))
    for n in bad["screens"][0]["children"]:
        if n.get("id") == "tickets":
            del n["rowLabel"]
    assert any("rowLabel" in p for p in validate_spec(bad))


def test_rowaction_on_a_non_list_is_rejected():
    bad = {"version": "0.2", "entry": "s", "screens": [{"id": "s", "children": [
        {"kind": "button", "id": "b", "label": "B",
         "rowAction": {"op": "navigate", "target": "s"}}]}]}
    assert any("has no rows" in p for p in validate_spec(bad))


def test_rows_are_exposed_as_addressable_actions():
    s = ReferenceSession(LIST)
    rows = [a for a in s.actions() if a["kind"] == "listItem"]
    assert len(rows) == 5
    assert rows[0]["id"] == "tickets#0"
    assert rows[0]["name"] == "Printer offline"


def test_tapping_a_row_carries_that_row_into_state():
    s = ReferenceSession(LIST)
    s.invoke("tickets#2")
    assert s.state()["selectedTitle"] == "Badge reader dead"
    assert s.state()["route"] == "detail"


def test_row_index_out_of_range_raises():
    s = ReferenceSession(LIST)
    try:
        s.invoke("tickets#99")
    except RenderError:
        return
    raise AssertionError("expected RenderError")


def test_full_list_detail_round_trip_updates_only_the_chosen_row():
    s = ReferenceSession(LIST)
    row = next(a for a in s.actions()
               if a["kind"] == "listItem" and a["name"] == "Printer offline")
    s.invoke(row["id"])
    s.invoke("resolve")

    tickets = s.state()["collections"]["tickets"]
    assert s.state()["route"] == "list", "resolve must navigate back"
    assert len(tickets) == 5, "resolve must not add or drop rows"
    resolved = [t for t in tickets if t["status"] == "resolved"]
    assert len(resolved) == 1 and resolved[0]["title"] == "Printer offline"


def test_list_detail_task_grades_pass_against_the_oracle():
    s = ReferenceSession(LIST)
    s.invoke("tickets#0")
    s.invoke("resolve")
    g = grade(SUITE["list-001"], s.state(), s.ui_facts())
    assert g["success"], g["failures"]


def test_empty_state_appears_only_when_the_collection_empties():
    s = ReferenceSession(LIST)
    assert s.ui_facts()["empty_state_visible"] is False
    s._state["collections"]["tickets"] = []
    assert s.ui_facts()["empty_state_visible"] is True


def test_rows_are_reachable_by_name_on_every_host():
    """An operator selects rows by their accessible name. A host that fails to
    name rows makes every list-detail task unreachable there, which would be a
    finding -- but it must not be caused by the harness."""
    for host in HOSTS:
        s = open_session(LIST, host, simulated=True)
        names = [a["name"] for a in s.actions() if a["kind"] == "listItem"]
        assert "Printer offline" in names, f"{host} did not name its rows"


# -------------------------------------------------------------- null check

def test_correct_spec_and_perfect_operator_produce_zero_host_lock():
    """The most important test in the repository.

    Host-lock must come from generated specs and a fallible operator, never
    from the harness. If a hand-written correct spec driven by a flawless
    scripted operator shows nonzero lock, the benchmark is manufacturing its own
    headline finding and every number it reports is suspect.
    """
    outcomes = []
    for host in HOSTS:
        # form-001
        s = open_session(FORM, host, simulated=True)
        s.invoke("name", "Dana Reyes")
        s.invoke("email", "dana@example.com")
        s.invoke("message", "Please call me back")
        s.invoke("submit")
        outcomes.append(TaskOutcome(
            "form-001", host, grade(SUITE["form-001"], s.state(), s.ui_facts())["success"]))

        # list-001
        s = open_session(LIST, host, simulated=True)
        row = next(a for a in s.actions()
                   if a["kind"] == "listItem" and a["name"] == "Printer offline")
        s.invoke(row["id"])
        s.invoke("resolve")
        outcomes.append(TaskOutcome(
            "list-001", host, grade(SUITE["list-001"], s.state(), s.ui_facts())["success"]))

    assert all(o.success for o in outcomes), \
        [f"{o.task_id}/{o.host}" for o in outcomes if not o.success]
    lock = host_lock_index(outcomes)
    assert lock.hli == 0.0, f"harness is manufacturing host-lock: {lock.as_row()}"
    assert lock.per_task_lock == 0.0, f"harness is manufacturing lock: {lock.as_row()}"


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
