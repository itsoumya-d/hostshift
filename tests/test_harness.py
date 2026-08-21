"""Harness tests: records, repair loop, operators, protocol conformance."""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import hostshift.harness as harness_mod
from hostshift.harness import (
    AccessibilityTreeOperator,
    Artifact,
    ComputerUseOperator,
    RunRecord,
    Store,
    repair,
)
from hostshift.render.base import Session as BaseSession
from hostshift.render.session import ReferenceSession

SPEC = {
    "version": "0.2", "title": "t", "entry": "main",
    "state": {
        "x": {"type": "string", "default": ""},
        "on": {"type": "boolean", "default": False},
    },
    "collections": {},
    "screens": [{"id": "main", "title": "T", "children": [
        {"kind": "field", "id": "f", "label": "F", "bind": "x"},
        {"kind": "toggle", "id": "tg", "label": "T", "bind": "on"},
        {"kind": "button", "id": "go", "label": "Go"},
    ]}],
}


def _spec():
    return json.loads(json.dumps(SPEC))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def test_store_artifact_round_trip():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        a = Artifact(task_id="t1", condition="B-schema", generator="g",
                     host=None, payload="{}")
        store.save_artifact(a)
        loaded = store.load_artifact("t1", "B-schema", "g", None)
        assert loaded is not None and loaded.payload == "{}"


def test_store_runlog_round_trip():
    with tempfile.TemporaryDirectory() as d:
        store = Store(d)
        r = RunRecord(task_id="t1", condition="A-freeform", generator="g",
                      host="web", operator="op", success=True, steps=4)
        store.record(r)
        runs = store.all_runs()
        assert len(runs) == 1 and runs[0].success and runs[0].steps == 4


def test_store_empty_log_reads_empty():
    with tempfile.TemporaryDirectory() as d:
        assert Store(d).all_runs() == []


# ---------------------------------------------------------------------------
# Repair loop
# ---------------------------------------------------------------------------

def test_repair_accepts_valid_first_pass():
    a = Artifact(task_id="t", condition="c", generator="g", host=None, payload="p")
    out = repair(a, validate=lambda x: (True, ""), regenerate=lambda x, d: x)
    assert out.valid and out.repair_rounds == 0


def test_repair_uses_budget_and_marks_invalid_on_exhaustion():
    a = Artifact(task_id="t", condition="c", generator="g", host=None, payload="p")
    calls = {"regen": 0}

    def regen(x, diag):
        calls["regen"] += 1
        return Artifact(**{**{f: getattr(x, f) for f in
                              ("task_id", "condition", "generator", "host", "payload")}},
                       )

    out = repair(a, validate=lambda x: (False, "bad"), regenerate=regen, max_rounds=3)
    assert calls["regen"] == 3
    assert out.valid is False


def test_repair_succeeds_after_one_fix():
    a = Artifact(task_id="t", condition="c", generator="g", host=None, payload="p")
    state = {"n": 0}

    def validate(x):
        state["n"] += 1
        return (state["n"] > 1, "")

    out = repair(a, validate=validate, regenerate=lambda x, d: x)
    assert out.valid and out.repair_rounds == 1


# ---------------------------------------------------------------------------
# AccessibilityTreeOperator
# ---------------------------------------------------------------------------

class FakeSession:
    """Minimal session speaking the canonical action contract."""

    host = "fake"

    def __init__(self, actions_per_step):
        self.actions_per_step = actions_per_step
        self.invoked = []
        self.step = 0

    def actions(self):
        return self.actions_per_step[min(self.step, len(self.actions_per_step) - 1)]

    def invoke(self, node_id, value=None):
        self.invoked.append((node_id, value))
        self.step += 1

    def widget_tree(self): ...
    def state(self): return {}
    def ui_facts(self): return {}

    def close(self): ...


def test_a11y_operator_fills_fields_then_toggles_then_buttons():
    sess = FakeSession([
        [
            {"id": "go", "kind": "action", "name": "Go", "enabled": True,
             "value": None, "options": []},
            {"id": "f", "kind": "input", "name": "Full name", "enabled": True,
             "value": "", "options": []},
            {"id": "tg", "kind": "boolean", "name": "Opt in", "enabled": True,
             "value": False, "options": []},
        ],
    ])
    steps = AccessibilityTreeOperator().run(sess, "goal", max_steps=10)
    # order: input filled first, then boolean toggled, then button pressed
    assert [i for i, _ in sess.invoked] == ["f", "tg", "go"]
    filled_value = sess.invoked[0][1]
    assert filled_value and "full-name" in filled_value
    assert sess.invoked[1][1] is True
    assert steps == 3


def test_a11y_operator_understands_spec_vocabulary():
    """Regression: real renderers report spec kinds ('field'/'button'), the
    policy speaks canonical kinds. Device verification caught the operator
    silently doing nothing against every shipped session; both vocabularies
    must drive it."""
    sess = FakeSession([
        [
            {"id": "f", "kind": "field", "name": "Full name", "enabled": True,
             "value": "", "options": []},
            {"id": "sel", "kind": "select", "name": "Tier", "enabled": True,
             "value": None, "options": ["free", "pro"]},
            {"id": "tg", "kind": "toggle", "name": "Opt in", "enabled": True,
             "value": False, "options": []},
            {"id": "go", "kind": "button", "name": "Go", "enabled": True,
             "value": None, "options": []},
        ],
    ])
    steps = AccessibilityTreeOperator().run(sess, "goal", max_steps=10)
    assert [i for i, _ in sess.invoked] == ["f", "sel", "tg", "go"]
    assert sess.invoked[1][1] == "free"  # first option chosen for a select
    assert steps == 4


def test_a11y_operator_never_repeats_an_action():
    actions = [{"id": "go", "kind": "action", "name": "Go", "enabled": True,
                "value": None, "options": []}]
    sess = FakeSession([actions])
    steps = AccessibilityTreeOperator().run(sess, "goal", max_steps=10)
    assert len(sess.invoked) == 1 and steps == 1


def test_a11y_operator_skips_disabled():
    sess = FakeSession([
        [{"id": "off", "kind": "input", "name": "N", "enabled": False,
          "value": "", "options": []}],
    ])
    steps = AccessibilityTreeOperator().run(sess, "goal", max_steps=5)
    assert steps == 0 and sess.invoked == []


def test_a11y_operator_choice_prefers_first_option():
    sess = FakeSession([
        [{"id": "c", "kind": "choice", "name": "Pick", "enabled": True,
          "value": "", "options": ["Red", "Blue"]}],
    ])
    AccessibilityTreeOperator().run(sess, "goal", max_steps=5)
    assert sess.invoked == [("c", "Red")]


# ---------------------------------------------------------------------------
# ComputerUseOperator
# ---------------------------------------------------------------------------

class _FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return type("R", (), {"text": r})()


def _operator_with(monkey_models):
    harness_mod.time.sleep = lambda s: None  # no real backoff waits in tests
    op = ComputerUseOperator(api_key_env="HOME")  # any set env var
    op._client = type("C", (), {"models": monkey_models})()
    return op


def test_computer_use_operator_drives_invoke_then_done():
    models = _FakeModels([
        '{"op": "invoke", "id": "f", "value": "hi"}',
        '{"op": "done"}',
    ])
    op = _operator_with(models)
    sess = FakeSession([[{"id": "f", "kind": "input", "name": "F",
                          "enabled": True, "value": "", "options": []}]])
    steps = op.run(sess, "fill the field", max_steps=5)
    assert sess.invoked == [("f", "hi")]
    assert steps == 2


def test_computer_use_operator_raises_after_retries_not_silent_done():
    models = _FakeModels([RuntimeError("boom")] * 4)
    op = _operator_with(models)
    sess = FakeSession([[]])
    try:
        op.run(sess, "goal", max_steps=3)
        raised = False
    except RuntimeError:
        raised = True
    assert raised, "API failure must surface, not become a fabricated done"
    assert models.calls == 4  # initial attempt + 3 retries


def test_computer_use_operator_requires_api_key(monkeypatch=None):
    import os
    env_key = "_HOSTSHIFT_TEST_NO_KEY_"
    os.environ.pop(env_key, None)
    op = ComputerUseOperator(api_key_env=env_key)
    sess = FakeSession([[]])
    try:
        op.run(sess, "goal", max_steps=1)
        raised = False
    except RuntimeError:
        raised = True
    assert raised


# ---------------------------------------------------------------------------
# Protocol conformance across the two Session definitions
# ---------------------------------------------------------------------------

def test_reference_session_satisfies_both_session_protocols():
    s = ReferenceSession(_spec())
    try:
        assert isinstance(s, BaseSession)  # runtime_checkable protocol
    finally:
        s.close()


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
