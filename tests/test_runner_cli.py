"""Runner CLI smoke tests. Drives main(argv) directly in a temp cwd so the
real runs/ directory is never touched."""

import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import runner


def _in_tmp():
    return tempfile.TemporaryDirectory()


def _run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = runner.main(argv)
    return code, buf.getvalue()


def test_lint_passes_on_shipped_suite():
    code, out = _run(["lint"])
    assert code == 0, out


def test_plan_prints_matrix_and_cost():
    code, out = _run(["plan", "--generators", "m1,m2"])
    assert code == 0
    assert "m1" in out and "$" in out


def test_demo_is_isolated_from_real_log():
    with _in_tmp() as d:
        real = pathlib.Path(d) / "runs"
        real.mkdir()
        (real / "runs.jsonl").write_text('{"keep": true}\n')
        code, out = _run(["--runs", str(real), "demo", "--repeats", "1",
                          "--out", str(real / "demo")])
        assert code == 0, out
        # synthetic data went to the demo store only
        demo_lines = (real / "demo" / "runs.jsonl").read_text().strip().splitlines()
        assert len(demo_lines) > 100
        assert json.loads((real / "runs.jsonl").read_text()) == {"keep": True}


def test_report_reads_a_store(tmp=None):
    with _in_tmp() as d:
        store = pathlib.Path(d) / "runs"
        code, _ = _run(["--runs", str(store), "demo", "--repeats", "1",
                        "--out", str(store)])
        assert code == 0
        code, out = _run(["--runs", str(store), "report", "--boot", "200"])
        assert code == 0, out
        assert "TABLE 1" in out


def test_report_accepts_runs_on_either_side_of_the_subcommand():
    """`--runs` must work before AND after `report`; a subparser default
    silently clobbering the global value is the classic argparse trap."""
    with _in_tmp() as d:
        store = pathlib.Path(d) / "runs"
        code, _ = _run(["--runs", str(store), "demo", "--repeats", "1",
                        "--out", str(store)])
        assert code == 0
        for argv in (
            ["report", "--runs", str(store), "--boot", "150"],
            ["--runs", str(store), "report", "--boot", "150"],
        ):
            code, out = _run(argv)
            assert code == 0, (argv, out)
            assert "TABLE 1" in out


def test_coverage_self_check_runs():
    # Without an external corpus the command reports the home-ground
    # self-check and stops: it never pretends a corpus number was measured.
    # The run itself succeeded, so the exit code is 0 -- the honesty lives in
    # what is (and is not) printed, not in a failure code.
    code, out = _run(["coverage"])
    assert code == 0, out
    assert "Self-check" in out and "100/100" in out
    assert "No external corpus supplied." in out
    assert "--corpus" in out


def test_version_flag():
    from hostshift import __version__

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), unittest.mock.patch(
            "sys.argv", ["hostshift", "--version"]):
        try:
            runner.main(["--version"])
        except SystemExit as e:
            assert e.code == 0
    assert __version__ in buf.getvalue()


def test_hosts_command_prints_profile_table():
    code, out = _run(["hosts"])
    assert code == 0, out
    for host in ("web", "swiftui", "compose", "tui"):
        assert host in out
    assert "names from label" in out


def test_report_json_matches_text_tables():
    with _in_tmp() as d:
        store = pathlib.Path(d) / "runs"
        code, _ = _run(["--runs", str(store), "demo", "--repeats", "1",
                        "--out", str(store)])
        assert code == 0
        code, out = _run(["report", "--runs", str(store), "--boot", "100",
                          "--json"])
        assert code == 0, out
        data = json.loads(out)
        assert data["meta"]["runs"] > 0
        assert data["meta"]["hosts"] == ["compose", "swiftui", "tui", "web"]
        t1 = data["interaction_parity_and_host_lock"]
        assert t1 and {"generator", "condition", "ip", "ip_ci95", "hli",
                       "hli_ci95", "per_task_lock"} <= set(t1[0])
        assert 0.0 <= t1[0]["ip"] <= 1.0
        assert len(data["condition_contrasts_mcnemar"]) == 3


def test_suite_lint_rejects_bad_criterion_kind():
    with _in_tmp() as d:
        suite = pathlib.Path(d) / "suite.jsonl"
        bad = {"id": "x-001", "category": "form_validation", "difficulty": "easy",
               "prompt": "p", "goal": "g",
               "criteria": [{"kind": "no_such_kind"}], "max_steps": 5}
        suite.write_text(json.dumps(bad) + "\n")
        code, out = _run(["--suite", str(suite), "lint"])
        assert code != 0


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
