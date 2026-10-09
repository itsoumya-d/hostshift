"""Options checks require observed options, including negative-only probes."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.oracle import check, grade, load_suite  # noqa: E402


def _criterion(**changes):
    return {"kind": "options_contain", "field": "region",
            "not_contains": ["Ontario"], **changes}


def test_missing_options_do_not_pass_negative_only_checks():
    for facts in (None, {}, {"options": {}}, {"options": {"country": ["India"]}}):
        result = check(_criterion(), {}, facts)
        assert not result.passed, facts
        assert "host did not report options" in result.detail


def test_invalid_options_are_not_treated_as_observations():
    for options in (None, False, 0, "Karnataka", {"Karnataka": True}):
        result = check(_criterion(), {}, {"options": {"region": options}})
        assert not result.passed, options


def test_explicit_empty_options_are_valid_negative_evidence():
    assert check(_criterion(), {}, {"options": {"region": []}}).passed
    assert not check(_criterion(contains=["Karnataka"]), {},
                     {"options": {"region": []}}).passed


def test_observed_required_and_forbidden_options_preserve_behavior():
    criterion = _criterion(contains=["Karnataka"])
    assert check(criterion, {}, {"options": {"region": ["Karnataka"]}}).passed
    for options in (["Ontario"], ["Ontario", "Karnataka"], ["Kerala"]):
        assert not check(criterion, {}, {"options": {"region": options}}).passed


def test_shipped_dependent_probe_missing_observation_remains_diagnostic():
    suite = pathlib.Path(__file__).resolve().parents[1] / "tasks" / "suite_v1.jsonl"
    task = next(t for t in load_suite(str(suite)) if t["id"] == "dependent-001")
    state = {"address": {"country": "India", "region": "Karnataka"}}
    result = grade(task, state)
    assert result["success"] is True
    assert result["probes_total"] == 1 and result["probes_passed"] == 0
    assert "host did not report options" in result["probe_failures"][0]
    observed = grade(task, state, {"options": {"region": ["Karnataka"]}})
    assert observed["success"] is True and observed["probes_passed"] == 1


def test_missing_options_cannot_pass_hard_or_negative_criteria():
    for section in ("criteria", "negative_criteria"):
        task = {"id": "dependent-001", "criteria": [
            {"kind": "state_truthy", "path": "saved"}], section: [_criterion()]}
        result = grade(task, {"saved": True})
        assert result["success"] is False
        assert "host did not report options" in result["failures"][0]


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
