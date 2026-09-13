"""Device-backed TUI session: the real Textual app, not the stand-in.

`SimulatedTuiSession` covers the pipeline path for every other test. These tests
drive the real `TuiSession`, which runs the generated Textual application on a
worker thread and marshals synchronous reads across to its event loop. That
indirection is the part no other test touches, and it is where row invocation
silently diverged: ids assigned after mount are not indexed by Textual's DOM
query, so `invoke("<list>#0")` raised `NoMatches` instead of clicking the row.
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render.base import RenderError  # noqa: E402
from hostshift.render.tui import (  # noqa: E402
    TuiRenderer,
    TuiSession,
    widget_from_textual,
)

SPEC = {
    "version": "0.2",
    "title": "TUI session coverage",
    "entry": "main",
    "state": {
        "name": {"type": "string", "default": ""},
        "plan": {"type": "enum", "options": ["Free", "Pro"], "default": "Free"},
        "agree": {"type": "boolean", "default": False},
    },
    "collections": {
        "tasks": {
            "seed": [{"title": "Alpha", "done": True}, {"title": "Beta", "done": False}],
        },
    },
    "screens": [{
        "id": "main",
        "title": "Main",
        "children": [
            {"kind": "heading", "id": "heading", "label": "Hello"},
            {"kind": "text", "id": "body", "label": "Body"},
            {"kind": "divider", "id": "divider"},
            {"kind": "banner", "id": "errorBanner", "tone": "error", "label": "Bad"},
            {"kind": "banner", "id": "emptyBanner", "tone": "empty", "label": "None"},
            {"kind": "image", "id": "logo", "label": "Logo", "a11yLabel": "Company logo"},
            {"kind": "field", "id": "nameInput", "label": "Name", "bind": "name"},
            {"kind": "select", "id": "planSelect", "label": "Plan", "bind": "plan"},
            {"kind": "toggle", "id": "agreeToggle", "label": "Agree", "bind": "agree"},
            {"kind": "button", "id": "goButton", "label": "Go"},
            {"kind": "list", "id": "taskList", "of": "tasks",
             "filterWhen": {"op": "eq", "left": "$row.done", "right": True}},
            {"kind": "container", "id": "row", "axis": "horizontal",
             "children": [{"kind": "text", "id": "rowText", "label": "Row"}]},
            {"kind": "container", "id": "column",
             "children": [{"kind": "text", "id": "columnText", "label": "Column"}]},
        ],
    }],
}


def _open():
    try:
        return TuiRenderer().open(SPEC)
    except RenderError as exc:
        if "needs Textual" in str(exc):
            raise unittest.SkipTest("the terminal host needs Textual") from exc
        raise


def _facts(session):
    return session.ui_facts()


def _actions(session):
    return {a["id"]: a for a in session.actions() if "#" not in a["id"]}


# --------------------------------------------------------------- renderer

def test_renderer_open_returns_a_device_backed_session():
    session = _open()
    try:
        assert isinstance(session, TuiSession)
        assert session.simulated is False
        assert session.host == "tui"
    finally:
        session.close()


def test_renderer_open_without_textual_raises_render_error():
    import hostshift.render.tui as tui

    class _Unavailable:
        def __init__(self, spec):
            raise ImportError("textual is not installed")

    original = tui.TuiSession
    tui.TuiSession = _Unavailable
    try:
        try:
            TuiRenderer().open(SPEC)
        except RenderError:
            return
        raise AssertionError("expected RenderError when Textual is unavailable")
    finally:
        tui.TuiSession = original


# ------------------------------------------------------------ live reads

def test_session_lowers_the_live_widget_tree():
    session = _open()
    try:
        tree = session.widget_tree()
        assert tree.kind == "container"
        by_id = {c.node_id: c for c in tree.children}
        assert by_id["heading"].kind == "text"
        assert by_id["heading"].name == "Hello"
        assert by_id["divider"].kind == "separator"
        assert by_id["logo"].kind == "text"
        assert by_id["logo"].name == "[image: Company logo]"
        assert by_id["nameInput"].kind == "input"
        assert by_id["nameInput"].name is None  # no a11y-name channel in a terminal
        assert by_id["planSelect"].kind == "choice"
        assert by_id["agreeToggle"].kind == "boolean"
        assert by_id["goButton"].kind == "action"
        assert by_id["taskList"].kind == "collection"
        assert by_id["taskList"].children[0].children[0].name == "Alpha"
        assert [c.kind for c in by_id["row"].children] == ["text"]
        assert [c.kind for c in by_id["column"].children] == ["text"]
    finally:
        session.close()


def test_session_reports_state_facts_and_actions():
    session = _open()
    try:
        state = session.state()
        assert state["name"] == ""
        assert state["plan"] == "Free"
        assert state["collections"]["tasks"][0]["title"] == "Alpha"

        facts = _facts(session)
        assert facts["error_visible"] is True
        assert facts["empty_state_visible"] is True
        assert facts["enabled"]["nameInput"] is True
        assert facts["enabled"]["goButton"] is True
        assert facts["field_values"]["nameInput"] == ""
        assert {"Free", "Pro"} <= set(facts["options"]["planSelect"])
        assert facts["visible_rows"]["taskList"] == 1

        actions = _actions(session)
        assert actions["nameInput"]["kind"] == "input"
        assert actions["nameInput"]["name"] is None
        assert actions["planSelect"]["kind"] == "choice"
        assert {"Free", "Pro"} <= set(actions["planSelect"]["options"])
        assert actions["agreeToggle"]["kind"] == "boolean"
        assert actions["goButton"]["kind"] == "action"
        assert actions["goButton"]["name"] == "Go"

        rows = [a for a in session.actions() if a["kind"] == "listItem"]
        assert len(rows) == 1
        assert rows[0]["id"] == "taskList#0"
        assert rows[0]["name"] == "Alpha"
    finally:
        session.close()


# -------------------------------------------------------------- invoking

def test_session_invoke_updates_control_values():
    session = _open()
    try:
        session.invoke("nameInput", "ada")
        assert _facts(session)["field_values"]["nameInput"] == "ada"

        session.invoke("planSelect", "Pro")
        assert _facts(session)["field_values"]["planSelect"] == "Pro"

        session.invoke("agreeToggle", True)
        assert _actions(session)["agreeToggle"]["value"] is True

        session.invoke("agreeToggle")  # a click toggles the checkbox back
        assert _actions(session)["agreeToggle"]["value"] is False

        session.invoke("goButton")  # clickable button must not raise
    finally:
        session.close()


def test_session_invoke_addresses_list_rows_without_raising():
    session = _open()
    try:
        session.invoke("taskList#0")   # the row that was raising NoMatches
        session.invoke("taskList#99")  # out of range: ignored
        session.invoke("missing#0")    # unknown list: ignored
        session.invoke("missing")      # unknown widget: ignored
    finally:
        session.close()


def test_session_close_is_safe_and_idempotent():
    TuiSession.__new__(TuiSession).close()  # never opened: no-op

    session = _open()
    session.close()
    session.close()


# ----------------------------------------------------- lowering fixtures

def _node(cls_name, node_id=None, label=None, renderable=None, children=()):
    node = type(cls_name, (), {})()
    node.id = node_id
    node.label = label
    node.renderable = renderable
    node.children = list(children)
    return node


def test_widget_from_textual_lowers_fixtures_without_an_event_loop():
    tree = _node("Screen", node_id="_default", children=[
        _node("Static", node_id="heading", renderable="Hello"),
        _node("Input", node_id="nameInput", label="Name"),
        _node("Checkbox", node_id="agree", label="Agree"),
        _node("ListView", node_id="list", children=[
            _node("ListItem", children=[_node("Label", renderable="Row one")]),
        ]),
        _node("MysteryWidget", node_id="mystery"),
    ])
    lowered = widget_from_textual(tree)
    assert lowered.kind == "container"

    by_id = {c.node_id: c for c in lowered.children}
    assert by_id["heading"].kind == "text"
    assert by_id["heading"].name == "Hello"
    assert by_id["nameInput"].kind == "input"
    assert by_id["nameInput"].name is None  # TUI does not derive names from labels
    assert by_id["agree"].kind == "boolean"
    assert by_id["agree"].name == "Agree"
    assert by_id["list"].kind == "collection"
    assert by_id["mystery"].kind == "container"

    item = by_id["list"].children[0]
    assert item.kind == "item"
    assert item.children[0].kind == "text"
    assert item.children[0].name == "Row one"


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  SKIP  {fn.__name__}  ({exc})")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    ran = len(fns) - failed - skipped
    print(f"\n{ran}/{len(fns)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)
