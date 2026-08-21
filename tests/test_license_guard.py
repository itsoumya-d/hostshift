"""License/provenance module tests."""

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift import license_guard


def test_verify_license_valid_on_this_checkout():
    check = license_guard.verify_license()
    assert check.valid, check.reason
    assert check.provenance["code_license"] == "AGPL-3.0-or-later"
    assert check.provenance["data_license"] == "CC-BY-NC-SA-4.0"
    assert check.provenance["harness_fingerprint"]


def test_stamp_provenance_adds_traceability():
    out = license_guard.stamp_provenance({"run": 1})
    meta = out["_hostshift_provenance"]
    assert out["run"] == 1
    assert meta["project"] == "HostShift"
    assert "timestamp" in meta and "harness_fingerprint" in meta


def test_missing_license_files_reported_invalid():
    with tempfile.TemporaryDirectory() as d:
        empty = pathlib.Path(d)
        (empty / "hostshift").mkdir()
        check = license_guard.verify_license(root=empty)
        assert not check.valid
        assert "missing" in check.reason.lower()


def test_wrong_license_pair_reported_invalid():
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        (root / "hostshift").mkdir()
        (root / "LICENSE").write_text("MIT permission")
        (root / "LICENSE-DATA").write_text("public domain")
        check = license_guard.verify_license(root=root)
        assert not check.valid
        assert "AGPL" in check.reason


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
