"""The synthetic demo supports every integer step budget accepted by lint."""

import contextlib
import hashlib
import io
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import runner  # noqa: E402


def _task(budget, task_id="demo-001"):
    return {
        "id": task_id, "category": "settings", "difficulty": "easy",
        "prompt": "Show an enabled switch and a save button.",
        "goal": "Save the enabled setting.",
        "criteria": [{"kind": "state_truthy", "path": "saved"}],
        "max_steps": budget,
    }


def _run(argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = runner.main(argv)
    return code, output.getvalue()


def _demo(root, tasks):
    suite = root / "suite.jsonl"
    suite.write_text("".join(json.dumps(task) + "\n" for task in tasks))
    code, output = _run(["--suite", str(suite), "lint"])
    assert code == 0, output
    real = root / "experiment"
    real.mkdir()
    sentinel = '{"keep": true}\n'
    (real / "runs.jsonl").write_text(sentinel)
    destination = root / "demo"
    code, output = _run([
        "--suite", str(suite), "--runs", str(real),
        "--calibration", str(root / "calibration"), "demo",
        "--repeats", "1", "--seed", "17", "--out", str(destination),
    ])
    assert code == 0, output
    assert "SYNTHETIC DATA" in output
    assert (real / "runs.jsonl").read_text() == sentinel
    rows = [json.loads(line) for line in (destination / "runs.jsonl").read_text().splitlines()]
    assert len(rows) == len(tasks) * 3 * 4 * 3  # generators x hosts x conditions
    assert {row["operator"] for row in rows} == {"synthetic"}
    return rows, destination


def test_demo_supports_lint_valid_four_step_tasks():
    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        rows, destination = _demo(root, [_task(4)])
        assert {row["steps"] for row in rows} == {4}
        code, output = _run([
            "--calibration", str(root / "calibration"), "report",
            "--runs", str(destination), "--json", "--boot", "20",
        ])
        assert code == 0, output
        assert json.loads(output)["meta"]["runs"] == 36


def test_demo_supports_lint_valid_five_step_tasks():
    with tempfile.TemporaryDirectory() as directory:
        rows, _ = _demo(pathlib.Path(directory), [_task(5)])
        assert {row["steps"] for row in rows} == {5}


def test_demo_preserves_seeded_outputs_for_existing_step_ranges():
    # Captured from unchanged main with seed=17, one repeat, and the fixture
    # above. Only the wall-clock timestamp is removed. All other run fields
    # and random draws must remain identical for existing budgets >= 6.
    expected = {
        6: "088f24241c9ce9c984b06ea2967dcd101bb526215656bfdf2d330420a1550eb2",
        18: "ba8fe1039772f65e03e9b6d4c28a75c71931b637d2edd43f0721e9b218f34de6",
    }
    for budget, digest in expected.items():
        with tempfile.TemporaryDirectory() as directory:
            rows, _ = _demo(pathlib.Path(directory), [_task(budget)])
        assert all(6 <= row["steps"] <= budget for row in rows)
        for row in rows:
            row.pop("ts")
        encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == digest


def test_demo_respects_each_budget_in_a_mixed_custom_suite():
    tasks = [_task(budget, f"demo-{i:03d}")
             for i, budget in enumerate((4, 5, 6, 18), start=1)]
    budgets = {task["id"]: task["max_steps"] for task in tasks}
    with tempfile.TemporaryDirectory() as directory:
        rows, _ = _demo(pathlib.Path(directory), tasks)
    for row in rows:
        budget = budgets[row["task_id"]]
        assert min(6, budget) <= row["steps"] <= budget


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS {name}")
        except Exception as error:
            failed += 1
            print(f"  FAIL {name}: {error}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(bool(failed))
