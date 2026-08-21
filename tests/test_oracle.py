"""Oracle tests.

The grading path decides every number in the paper, so the cases that matter
most here are the ones where a bug would *inflate* the score rather than
depress it -- a criterion that passes when it should not is invisible in the
results and fatal to the claim.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.oracle import check, grade, load_suite, validate_suite  # noqa: E402

SUITE = pathlib.Path(__file__).resolve().parents[1] / "tasks" / "suite_v1.jsonl"


def test_misconfigured_unchanged_fails_loudly():
    """Regression: this used to pass vacuously when `seed_values` was absent."""
    r = check({"kind": "collection_field_unchanged", "collection": "x",
               "field": "status"}, {"collections": {"x": [{"status": "a"}]}})
    assert r.passed is False
    assert "seed_values" in r.detail


def test_unknown_criterion_kind_fails_rather_than_passes():
    r = check({"kind": "definitely_not_a_kind"}, {})
    assert r.passed is False


def test_ui_fact_criteria_fail_when_host_reports_nothing():
    """A host that fails to report a UI fact must not be scored as compliant."""
    for kind in ("error_visible", "empty_state_visible"):
        assert check({"kind": kind}, {}, {}).passed is False
    assert check({"kind": "visible_row_count", "collection": "r", "op": "eq",
                  "value": 3}, {}, {}).passed is False
    assert check({"kind": "enabled_state", "targets": ["a"], "expect": "disabled"},
                 {}, {}).passed is False


def test_string_match_is_case_and_space_insensitive():
    state = {"collections": {"c": [{"name": "  Dana Reyes "}]}}
    assert check({"kind": "collection_contains", "collection": "c",
                  "match": {"name": "dana reyes"}}, state).passed


def test_numeric_match_tolerates_int_float():
    state = {"collections": {"c": [{"amount": 40.0}]}}
    assert check({"kind": "collection_contains", "collection": "c",
                  "match": {"amount": 40}}, state).passed


def test_dotted_path_lookup_and_missing_path():
    state = {"a": {"b": {"c": 7}}}
    assert check({"kind": "state_equals", "path": "a.b.c", "value": 7}, state).passed
    assert not check({"kind": "state_equals", "path": "a.b.z", "value": 7}, state).passed


def test_field_equals_fails_when_no_row_matches_where():
    state = {"collections": {"t": [{"title": "other", "status": "open"}]}}
    r = check({"kind": "collection_field_equals", "collection": "t",
               "where": {"title": "missing"}, "field": "status",
               "value": "resolved"}, state)
    assert r.passed is False


def test_negative_criteria_gate_success():
    task = {"id": "x-001", "criteria": [{"kind": "state_truthy", "path": "ok"}],
            "negative_criteria": [{"kind": "collection_count", "collection": "c",
                                   "op": "lte", "value": 1}]}
    assert grade(task, {"ok": True, "collections": {"c": [1]}})["success"]
    assert not grade(task, {"ok": True, "collections": {"c": [1, 2]}})["success"]


def test_probes_do_not_gate_success():
    task = {"id": "x-002", "criteria": [{"kind": "state_truthy", "path": "ok"}],
            "probes": [{"kind": "error_visible"}]}
    out = grade(task, {"ok": True}, {})
    assert out["success"] is True
    assert out["probes_passed"] == 0 and out["probes_total"] == 1


def test_empty_criteria_is_not_a_free_pass():
    assert grade({"id": "x-003", "criteria": []}, {})["success"] is False


# ------------------------------------------------------- the shipped suite

def test_shipped_suite_lints_clean():
    tasks = load_suite(str(SUITE))
    assert validate_suite(tasks) == []


def test_shipped_suite_shape():
    tasks = load_suite(str(SUITE))
    assert len(tasks) == 100
    assert len({t["category"] for t in tasks}) == 8
    assert all(t.get("difficulty") in {"easy", "medium", "hard"} for t in tasks)
    # goals must not restate the prompt, or the generator sees the answer
    assert all(t["goal"].strip() != t["prompt"].strip() for t in tasks)


def test_shipped_suite_is_predominantly_state_based():
    """The portability claim depends on grading state, not appearance."""
    ui = {"visible_row_count", "error_visible", "empty_state_visible",
          "enabled_state", "field_value_equals", "options_contain"}
    tasks = load_suite(str(SUITE))
    hard = [c for t in tasks for c in t.get("criteria", []) + t.get("negative_criteria", [])]
    state_based = sum(1 for c in hard if c["kind"] not in ui)
    assert state_based / len(hard) > 0.85


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
