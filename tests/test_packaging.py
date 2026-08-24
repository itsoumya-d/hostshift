"""Packaging and entry-point guarantees.

HostShift must work identically from a repository checkout and from a wheel
installed into site-packages. These tests pin the contract: the console
script exists, `python -m hostshift` works, the default suite resolves to a
file that exists, and the wheel-shipped suite copy can never silently drift
from the source of truth in tasks/.
"""

import pathlib
import subprocess
import sys
import tomllib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_version_is_declared_consistently():
    import hostshift

    metadata = _pyproject()["project"]
    assert hostshift.__version__ == metadata["version"]


def test_console_script_entry_point_is_declared():
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts.get("hostshift") == "hostshift.runner:main"


def test_python_m_hostshift_version_works():
    proc = subprocess.run(
        [sys.executable, "-m", "hostshift", "--version"],
        capture_output=True, text=True, cwd=ROOT, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "hostshift" in proc.stdout


def test_default_suite_resolves_to_an_existing_file():
    from hostshift.runner import SUITE

    path = pathlib.Path(SUITE)
    assert path.exists(), f"default suite does not exist: {SUITE}"
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 100, "shipped suite unexpectedly shrank"


def test_packaged_suite_copy_matches_source_of_truth():
    """The wheel ships hostshift/data/suite_v1.jsonl because a wheel cannot
    reach tasks/ outside site-packages. Drift between the copy and the
    canonical file would make installed runs differ from checkout runs, so
    any edit to one without the other fails here."""
    canonical = ROOT / "tasks" / "suite_v1.jsonl"
    packaged = ROOT / "hostshift" / "data" / "suite_v1.jsonl"
    if not (canonical.exists() and packaged.exists()):
        raise unittest.SkipTest("checkout layout not present")
    assert canonical.read_bytes() == packaged.read_bytes()


def test_genai_extra_targets_the_sdk_the_code_imports():
    """harness.py imports `from google import genai` -- the google-genai SDK.
    The extra once named the legacy google-generativeai package, which cannot
    satisfy that import; this pins the fix."""
    extras = _pyproject()["project"]["optional-dependencies"]
    assert any(dep.startswith("google-genai") for dep in extras["genai"])
    assert not any(dep.startswith("google-generativeai") for dep in extras["genai"])


def test_pytest_scoped_to_this_benchmarks_tests():
    """A bare `pytest` at the workspace root must not try to collect the
    sibling autopilot-fde project (separate venv, separate deps)."""
    ini = _pyproject().get("tool", {}).get("pytest", {}).get("ini_options", {})
    assert ini.get("testpaths") == ["tests"]


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
