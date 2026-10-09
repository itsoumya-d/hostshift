"""Malformed enablement criteria must not manufacture successful tasks."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import runner  # noqa: E402
from hostshift.oracle import check, grade, validate_suite  # noqa: E402


def _criterion(**changes):
    return {"kind": "enabled_state", "targets": ["save"], "expect": "enabled", **changes}


def _malformed():
    yield {"kind": "enabled_state", "expect": "enabled"}, "targets"
    yield {"kind": "enabled_state", "targets": ["save"]}, "expect"
    for targets in (None, [], "save", {"save": True}, 1, [None], [1], [""]):
        yield _criterion(targets=targets), "targets"
    for expect in (None, "enabeld", "", True, ["enabled"]):
        yield _criterion(expect=expect), "expect"


def _task(criterion, section="criteria"):
    task = {"id": "form-001", "category": "form_validation", "difficulty": "easy",
            "prompt": "A form with a save button.", "goal": "Check the save control.",
            "criteria": [{"kind": "state_truthy", "path": "saved"}], "max_steps": 8}
    task[section] = [criterion]
    return task


def test_malformed_enabled_state_fails_closed():
    for criterion, field in _malformed():
        for facts in ({}, {"enabled": {"save": False}}, {"enabled": {"save": True}}):
            result = check(criterion, {}, facts)
            assert result.passed is False, (criterion, facts)
            assert "misconfigured" in result.detail and field in result.detail


def test_malformed_enabled_state_cannot_pass_hard_criteria():
    for section in ("criteria", "negative_criteria"):
        for criterion, _ in _malformed():
            result = grade(_task(criterion, section), {"saved": True})
            assert result["success"] is False, (section, criterion)
            assert any("misconfigured" in failure for failure in result["failures"])


def test_malformed_probe_remains_diagnostic_without_passing():
    result = grade(_task(_criterion(targets=[]), "probes"), {"saved": True})
    assert result["success"] is True
    assert result["probes_passed"] == 0 and result["probes_total"] == 1
    assert "misconfigured" in result["probe_failures"][0]


def test_valid_enabled_and_disabled_require_all_targets():
    for expect, want in (("enabled", True), ("disabled", False)):
        criterion = _criterion(targets=["save", "submit"], expect=expect)
        assert check(criterion, {}, {"enabled": {"save": want, "submit": want}}).passed
        assert not check(criterion, {}, {"enabled": {"save": want, "submit": not want}}).passed
        assert not check(criterion, {}, {"enabled": {"save": want}}).passed
        assert not check(criterion, {}, {}).passed


def test_lint_rejects_malformed_enabled_state_in_every_section():
    for section in ("criteria", "negative_criteria", "probes"):
        for criterion, field in _malformed():
            problems = validate_suite([_task(criterion, section)])
            assert any("enabled_state" in p and field in p for p in problems), (
                section, criterion, problems)


def test_lint_accepts_valid_enabled_and_disabled_criteria():
    for section in ("criteria", "negative_criteria", "probes"):
        for expect in ("enabled", "disabled"):
            assert validate_suite([_task(_criterion(expect=expect), section)]) == []


def test_lint_cli_rejects_malformed_enabled_state():
    with tempfile.TemporaryDirectory() as directory:
        suite = pathlib.Path(directory) / "suite.jsonl"
        for criterion, field in _malformed():
            suite.write_text(json.dumps(_task(criterion)) + "\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = runner.main(["--suite", str(suite), "lint"])
            assert code == 1, (criterion, output.getvalue())
            assert "enabled_state" in output.getvalue() and field in output.getvalue()
            assert "suite is well formed" not in output.getvalue()


def test_lint_cli_preserves_valid_enabled_and_disabled():
    with tempfile.TemporaryDirectory() as directory:
        suite = pathlib.Path(directory) / "suite.jsonl"
        for expect in ("enabled", "disabled"):
            suite.write_text(json.dumps(_task(_criterion(expect=expect))) + "\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = runner.main(["--suite", str(suite), "lint"])
            assert code == 0 and "suite is well formed" in output.getvalue()


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
