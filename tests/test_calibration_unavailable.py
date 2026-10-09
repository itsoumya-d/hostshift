"""An empty normalized host set is missing evidence, not measured zero lock."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import runner  # noqa: E402
from hostshift.calibration import CalibrationRun, CalibrationStore, report  # noqa: E402
from hostshift.harness import CONDITION_B, RunRecord, Store  # noqa: E402
from hostshift.metrics import (  # noqa: E402
    TaskOutcome,
    calibration_report,
    host_lock_index,
    normalized_host_lock,
)


def _save_ceilings(root, results):
    store = CalibrationStore(root)
    for host, successes in results.items():
        run = CalibrationRun(host, f"synthetic/{host}", "synthetic")
        for i, success in enumerate(successes):
            run.record(f"cal-{i}", success)
        store.save(run)
    return store


def _outcomes():
    return [TaskOutcome("task-1", "web", True), TaskOutcome("task-1", "tui", False)]


def _unusable_ceilings():
    return ({"web": [], "tui": []},
            {"web": [False], "tui": [False]},
            {"compose": [True]})


def _run(argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = runner.main(argv)
    return code, output.getvalue()


def _save_runs(root):
    store = Store(root)
    for outcome in _outcomes():
        store.record(RunRecord(
            outcome.task_id, CONDITION_B, "synthetic", outcome.host, "synthetic",
            success=outcome.success,
        ))


def test_report_marks_zero_attempts_failures_and_unrelated_ceilings_unavailable():
    for results in _unusable_ceilings():
        with tempfile.TemporaryDirectory() as directory:
            store = _save_ceilings(directory, results)
            summary = report(_outcomes(), store)
        assert summary["raw_hli"] == 1.0
        assert summary["per_task_lock"] == 0.5
        assert summary["normalized_hli"] is None, (results, summary)
        assert summary["attributable_to_operator"] is None
        assert "UNCALIBRATED" in summary["status"]
        assert summary["ceilings"] == {h: 1.0 if any(v) else 0.0 for h, v in results.items()}


def test_report_without_benchmark_outcomes_cannot_infer_normalized_zero():
    with tempfile.TemporaryDirectory() as directory:
        summary = report([], _save_ceilings(directory, {"web": [True]}))
    assert summary["normalized_hli"] is None
    assert summary["attributable_to_operator"] is None


def test_low_level_report_does_not_expose_empty_hostlock_sentinel_as_measurement():
    raw = host_lock_index(_outcomes())
    normalized = normalized_host_lock(_outcomes(), {})
    assert normalized.per_host_ip == {}  # The internal metric contract is unchanged.
    summary = calibration_report({}, raw, normalized)
    assert summary["raw_hli"] == 1.0
    assert summary["normalized_hli"] is None
    assert summary["attributable_to_operator"] is None


def test_genuine_normalized_zero_and_observed_all_failures_remain_numeric():
    with tempfile.TemporaryDirectory() as directory:
        store = _save_ceilings(directory, {"web": [True, True], "tui": [True, False]})
        outcomes = [TaskOutcome(f"task-{i}", host, success)
                    for host, successes in {"web": [True, True], "tui": [True, False]}.items()
                    for i, success in enumerate(successes)]
        summary = report(outcomes, store)
        assert summary["raw_hli"] == 0.5
        assert summary["normalized_hli"] == 0.0
        assert summary["attributable_to_operator"] == 0.5
        assert "status" not in summary
        failures = [TaskOutcome(o.task_id, o.host, False) for o in outcomes]
        summary = report(failures, store)
        assert summary["normalized_hli"] == 0.0
        assert summary["attributable_to_operator"] == 0.0


def test_a_retained_host_does_not_become_an_empty_result():
    with tempfile.TemporaryDirectory() as directory:
        store = _save_ceilings(directory, {"web": [True], "tui": [False]})
        normalized = normalized_host_lock(_outcomes(), store.ceilings())
        summary = report(_outcomes(), store)
    assert normalized.per_host_ip == {"web": 1.0}
    assert summary["normalized_hli"] == 0.0


def test_partial_coverage_suppresses_attribution_but_preserves_subset_hli():
    for results in ({"web": [True]}, {"web": [True], "tui": [False]}):
        with tempfile.TemporaryDirectory() as directory:
            store = _save_ceilings(directory, results)
            normalized = normalized_host_lock(_outcomes(), store.ceilings())
            summary = report(_outcomes(), store)
        assert normalized.per_host_ip == {"web": 1.0}
        assert summary["raw_hli"] == 1.0
        assert summary["normalized_hli"] == normalized.hli == 0.0
        assert summary["attributable_to_operator"] is None, summary
        assert summary["excluded_hosts"] == ["tui"]
        assert "host sets differ" in summary["attribution_status"]
        assert "tui" in summary["attribution_status"]


def test_unrelated_extra_ceilings_do_not_suppress_valid_attribution():
    with tempfile.TemporaryDirectory() as directory:
        store = _save_ceilings(directory, {"web": [True], "tui": [True], "compose": [True]})
        summary = report(_outcomes(), store)
    assert summary["normalized_hli"] == 1.0
    assert summary["attributable_to_operator"] == 0.0
    assert not summary.get("excluded_hosts")


def test_report_cli_json_and_text_do_not_claim_unavailable_normalization():
    for results in _unusable_ceilings():
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _save_ceilings(root / "calibration", results)
            _save_runs(root / "experiment")
            args = ["--calibration", str(root / "calibration"), "report",
                    "--runs", str(root / "experiment"), "--boot", "20"]
            code, output = _run(args + ["--json"])
            assert code == 0, output
            summary = json.loads(output)["operator_calibration"]
            assert summary["normalized_hli"] is None
            assert summary["attributable_to_operator"] is None
            code, output = _run(args)
            assert code == 0, output
            table = output.split("TABLE 5", 1)[1]
            assert "UNCALIBRATED" in table
            assert "normalized HLI      0.000" not in table
            assert "attributable to the operator" not in table


def test_calibrate_cli_reports_unavailable_comparison_without_formatting_none():
    for results in _unusable_ceilings():
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _save_ceilings(root / "calibration", results)
            _save_runs(root / "experiment")
            code, output = _run(["--calibration", str(root / "calibration"),
                                 "calibrate", "--runs", str(root / "experiment")])
        assert code == 1, output
        assert "UNCALIBRATED" in output
        assert "normalized 0.000" not in output
        assert "of the apparent host-lock" not in output


def test_calibrate_can_still_list_ceilings_without_experiment_runs():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        _save_ceilings(root / "calibration", {"web": [False]})
        code, output = _run(["--calibration", str(root / "calibration"),
                             "calibrate", "--runs", str(root / "empty")])
    assert code == 0, output
    assert "web" in output and "0.000" in output


def test_partial_coverage_cli_reports_excluded_hosts_without_numeric_attribution():
    for results in ({"web": [True]}, {"web": [True], "tui": [False]}):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            _save_ceilings(root / "calibration", results)
            _save_runs(root / "experiment")
            common = ["--calibration", str(root / "calibration")]
            run_args = ["--runs", str(root / "experiment")]
            code, output = _run(common + ["report"] + run_args + ["--boot", "20", "--json"])
            assert code == 0, output
            summary = json.loads(output)["operator_calibration"]
            assert summary["normalized_hli"] == 0.0
            assert summary["attributable_to_operator"] is None
            assert summary["excluded_hosts"] == ["tui"]
            code, output = _run(common + ["report"] + run_args + ["--boot", "20"])
            assert code == 0, output
            table = output.split("TABLE 5", 1)[1]
            assert "normalized HLI      0.000" in table
            assert "excludes tui" in table and "host sets differ" in table
            assert "attributable to the operator, not the interface: 1.000" not in table
            code, output = _run(common + ["calibrate"] + run_args)
            assert code == 0, output
            assert "raw HLI 1.000  ->  normalized 0.000" in output
            assert "excludes tui" in output and "host sets differ" in output
            assert "of the apparent host-lock" not in output


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
