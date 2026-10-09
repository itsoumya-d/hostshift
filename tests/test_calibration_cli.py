"""Calibration selection must stay consistent from CLI input to report output."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import runner  # noqa: E402
from hostshift.calibration import CalibrationRun, CalibrationStore  # noqa: E402
from hostshift.harness import CONDITION_B, RunRecord, Store  # noqa: E402


def _run(argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = runner.main(argv)
    return code, output.getvalue()


def _save_calibration(root, tui_successes=1):
    store = CalibrationStore(root)
    for host, successes in (("web", 2), ("tui", tui_successes)):
        run = CalibrationRun(host, f"synthetic/{host}", "synthetic")
        for i in range(2):
            run.record(f"cal-{i}", i < successes)
        store.save(run)


def _save_runs(root):
    store = Store(root)
    for host, successes in (("web", 2), ("tui", 1)):
        for i in range(2):
            store.record(RunRecord(
                task_id=f"task-{i}", condition=CONDITION_B,
                generator="synthetic", host=host, operator="synthetic",
                success=i < successes,
            ))


def test_report_uses_selected_calibration_in_json_and_text():
    for conflicting_default in (False, True):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            _save_calibration("selected")
            _save_runs("experiment")
            if conflicting_default:
                _save_calibration("runs/calibration", tui_successes=2)
            args = ["--calibration", "selected", "report", "--runs", "experiment",
                    "--boot", "20"]
            code, output = _run(args + ["--json"])
            assert code == 0, output
            summary = json.loads(output)["operator_calibration"]
            assert summary["ceilings"] == {"tui": 0.5, "web": 1.0}
            assert summary["raw_hli"] == 0.5
            assert summary["normalized_hli"] == 0.0
            code, output = _run(args)
            assert code == 0, output
            assert "normalized HLI      0.000" in output
            if not conflicting_default:
                assert not pathlib.Path("runs/calibration").exists()


def test_calibrate_normalizes_with_the_same_store_as_its_ceiling_table():
    for conflicting_default in (False, True):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            _save_calibration("selected")
            _save_runs("experiment")
            if conflicting_default:
                _save_calibration("runs/calibration", tui_successes=2)
            code, output = _run(["--calibration", "selected", "calibrate",
                                 "--runs", "experiment"])
            assert code == 0, output
            assert "raw HLI 0.500  ->  normalized 0.000" in output
            assert "0.500 of the apparent host-lock" in output
            if not conflicting_default:
                assert not pathlib.Path("runs/calibration").exists()


def test_empty_selected_calibration_does_not_borrow_the_default():
    with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
        _save_calibration("runs/calibration")
        _save_runs("experiment")
        code, output = _run(["--calibration", "empty", "report", "--runs", "experiment",
                             "--boot", "20", "--json"])
        assert code == 0, output
        summary = json.loads(output)["operator_calibration"]
        assert summary["normalized_hli"] is None
        assert "UNCALIBRATED" in summary["status"]
        code, output = _run(["--calibration", "empty", "calibrate", "--runs", "experiment"])
        assert code == 1, output
        assert "No calibration runs recorded." in output


def test_demo_report_honors_selected_calibration():
    with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
        _save_calibration("selected")
        _save_calibration("runs/calibration", tui_successes=2)
        pathlib.Path("suite.jsonl").write_text(json.dumps({
            "id": "synthetic-001", "criteria": [], "max_steps": 6,
        }) + "\n")
        code, output = _run(["--calibration", "selected", "--suite", "suite.jsonl",
                             "demo", "--out", "synthetic-runs", "--repeats", "1"])
        assert code == 0, output
        assert "operator ceilings   {'tui': 0.5, 'web': 1.0}" in output
        assert "SYNTHETIC DATA" in output
        assert "no operator ceiling for compose, swiftui" in output


def test_default_calibration_remains_available_when_not_overridden():
    with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
        _save_calibration("runs/calibration")
        _save_runs("experiment")
        code, output = _run(["report", "--runs", "experiment", "--boot", "20", "--json"])
        assert code == 0, output
        summary = json.loads(output)["operator_calibration"]
        assert summary["ceilings"] == {"tui": 0.5, "web": 1.0}
        assert summary["normalized_hli"] == 0.0
        code, output = _run(["calibrate", "--runs", "experiment"])
        assert code == 0, output
        assert "raw HLI 0.500  ->  normalized 0.000" in output


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
