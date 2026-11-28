"""Conformance and end-to-end tests for the evaluate-ui-portability agent skill."""

from __future__ import annotations

import io
import pathlib
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.runner import main


def _skill_path() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    return here.parent / "skills" / "evaluate-ui-portability" / "SKILL.md"


def _extract_steps(text: str) -> list[tuple[int, str]]:
    matches = re.findall(r"(?m)^\s*(\d+)[.)]\s+([\s\S]*?)(?=(?:^\s*\d+[.)]|\Z))", text)
    return [(int(m[0]), m[1].strip()) for m in matches]


def test_skill_structure_normal():
    path = _skill_path()
    assert path.exists(), f"Skill file not found at {path}"
    content = path.read_text(encoding="utf-8")
    assert "Use this skill when" in content, "Missing trigger paragraph"
    steps = _extract_steps(content)
    assert len(steps) >= 5, f"Expected at least 5 numbered steps, got {len(steps)}"
    for idx, (num, body) in enumerate(steps, start=1):
        assert num == idx, f"Step numbering mismatch: expected {idx}, got {num}"
        cmds = re.findall(r"`python -m hostshift ([^`]+)`", body)
        assert len(cmds) >= 1, f"Step {num} does not contain an executable hostshift command"


def test_skill_steps_execution_e2e():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc_lint = main(["lint"])
        assert rc_lint == 0, f"Lint step failed with rc={rc_lint}"
        rc_plan = main(["plan", "--generators", "gemini,claude", "--repeats", "1"])
        assert rc_plan == 0, f"Plan step failed with rc={rc_plan}"
        rc_cov = main(["coverage"])
        assert rc_cov == 0, f"Coverage step failed with rc={rc_cov}"
    out = buf.getvalue()
    assert "suite is well formed" in out
    assert "tasks" in out


def test_skill_invalid_suite_error():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "bad-task", "category": "unknown", "title": "Bad"}\n')
        tmp_name = f.name
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--suite", tmp_name, "lint"])
        assert rc == 1, f"Expected lint to fail on invalid suite, got rc={rc}"
        assert "problems:" in buf.getvalue()
    finally:
        pathlib.Path(tmp_name).unlink(missing_ok=True)


def test_skill_empty_suite_boundary():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("")
        tmp_name = f.name
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--suite", tmp_name, "lint"])
        assert rc == 0, f"Expected lint to succeed on empty suite, got rc={rc}"
        assert "0 tasks, 0 categories" in buf.getvalue()
    finally:
        pathlib.Path(tmp_name).unlink(missing_ok=True)


def test_skill_malformed_json_error():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write("{bad json\n")
        tmp_name = f.name
    try:
        threw = False
        try:
            main(["--suite", tmp_name, "lint"])
        except Exception:
            threw = True
        assert threw, "Expected malformed JSON line to raise an exception"
    finally:
        pathlib.Path(tmp_name).unlink(missing_ok=True)


def test_skill_missing_store_report_failure():
    with tempfile.TemporaryDirectory() as tmp_dir:
        non_existent = pathlib.Path(tmp_dir) / "does_not_exist"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["report", "--runs", str(non_existent)])
        assert rc == 1, f"Expected report on missing store to fail with rc=1, got rc={rc}"
        assert "no runs recorded yet" in buf.getvalue()


def test_skill_property_commands_use_registered_subcommands():
    content = _skill_path().read_text(encoding="utf-8")
    cmds = re.findall(r"`python -m hostshift ([^`]+)`", content)
    registered = {"lint", "plan", "report", "calibrate", "coverage", "demo", "hosts", "render-check", "export-sql"}
    for cmd in cmds:
        subcmd = cmd.strip().split()[0]
        assert subcmd in registered, f"Command '{subcmd}' is not a registered hostshift subcommand"


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
