"""The scripted operator must recognize tappable rows from real host actions."""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.harness import AccessibilityTreeOperator  # noqa: E402
from hostshift.oracle import grade, load_suite  # noqa: E402
from hostshift.render import HOSTS, ReferenceSession, RenderError, open_session  # noqa: E402
from hostshift.render.tui import TuiRenderer  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Session:
    def __init__(self, actions):
        self._actions = actions
        self.invoked = []

    def actions(self):
        return self._actions

    def invoke(self, node_id, value=None):
        self.invoked.append((node_id, value))


def _action(node_id, kind, **changes):
    return {"id": node_id, "kind": kind, "name": node_id, "enabled": True,
            "value": None, "options": [], **changes}


def test_operator_recognizes_spec_and_canonical_row_kinds():
    for kind in ("listItem", "listitem", "LISTITEM", "item", "ITEM"):
        session = _Session([_action("rows#0", kind)])
        steps = AccessibilityTreeOperator().run(session, "Open the row", max_steps=4)
        assert steps == 1, kind
        assert session.invoked == [("rows#0", None)], kind


def test_operator_keeps_rows_after_inputs_and_before_buttons():
    for row_kind in ("listItem", "item"):
        session = _Session([
            _action("go", "button"),
            _action("rows#0", row_kind),
            _action("agree", "toggle", value=False),
            _action("plan", "select", options=["Free", "Pro"]),
            _action("name", "field"),
        ])
        steps = AccessibilityTreeOperator().run(session, "Complete the form", max_steps=10)
        assert steps == 5, row_kind
        assert session.invoked == [("name", "name"), ("plan", "Free"),
                                   ("agree", True), ("rows#0", None), ("go", None)]


def test_operator_skips_disabled_rows_and_does_not_repeat_rows():
    session = _Session([
        _action("rows#0", "listItem", enabled=False),
        _action("rows#1", "listItem"),
        _action("rows#2", "item", enabled=False),
    ])
    steps = AccessibilityTreeOperator().run(session, "Open an available row", max_steps=10)
    assert steps == 1
    assert session.invoked == [("rows#1", None)]


def test_operator_row_actions_respect_step_budget():
    for budget in (0, 1, 2):
        session = _Session([_action(f"rows#{i}", "listItem") for i in range(3)])
        steps = AccessibilityTreeOperator().run(session, "Open rows", max_steps=budget)
        assert steps == budget
        assert session.invoked == [(f"rows#{i}", None) for i in range(budget)]


def _list_fixture():
    spec = json.loads((ROOT / "tasks" / "reference_specs" / "list-001.json").read_text())
    task = next(t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))
                if t["id"] == "list-001")
    return spec, task


def _complete_list_task(session, task):
    # Two actions are sufficient: open the first ticket, then resolve it.
    # This proves actual state transitions, rather than just kind normalization.
    steps = AccessibilityTreeOperator().run(session, task["goal"], max_steps=2)
    assert steps == 2
    result = grade(task, session.state(), session.ui_facts())
    assert result["success"], result["failures"]
    state = session.state()
    assert state["route"] == "list"
    assert [row["title"] for row in state["collections"]["tickets"]
            if row["status"] == "resolved"] == ["Printer offline"]


def test_operator_completes_shipped_list_task_on_reference_and_simulated_hosts():
    spec, task = _list_fixture()
    for host in ("reference", *HOSTS):
        session = (ReferenceSession(spec) if host == "reference"
                   else open_session(spec, host, simulated=True))
        try:
            _complete_list_task(session, task)
        finally:
            session.close()


def test_operator_invokes_rows_exposed_by_live_textual_app():
    spec, task = _list_fixture()
    try:
        session = TuiRenderer().open(spec)
    except RenderError as exc:
        if "needs Textual" in str(exc):
            raise unittest.SkipTest("the terminal host needs Textual") from exc
        raise
    try:
        assert session.simulated is False
        invoked = []
        original_invoke = session.invoke

        def record_invoke(node_id, value=None):
            invoked.append((node_id, value))
            original_invoke(node_id, value)

        session.invoke = record_invoke
        steps = AccessibilityTreeOperator().run(session, task["goal"], max_steps=1)
        assert steps == 1
        assert invoked == [("tickets#0", None)]
        # This checks dispatch to the live session. Generated TUI action semantics
        # are independent of the operator and are not asserted here.
    finally:
        session.close()


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    skipped = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  SKIP  {fn.__name__}: {exc}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed - skipped}/{len(tests)} passed ({skipped} skipped)")
    sys.exit(1 if failed else 0)
