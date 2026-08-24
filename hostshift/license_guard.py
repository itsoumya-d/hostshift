"""Provenance stamping for HostShift run records.

Licensing is declared by the files at the repository root (LICENSE: AGPL-3.0
for code; LICENSE-DATA: CC BY-NC-SA 4.0 for benchmark artifacts) and does not
need -- and does not get -- a runtime enforcement mechanism.

What run records do need is provenance: who produced them, with which version
of the harness, and when. `stamp_provenance` attaches that to an artifact so
that published runs are traceable back to the exact code that generated them.
"""

from __future__ import annotations

import hashlib
import pathlib
import time
from dataclasses import dataclass

from . import __version__

_LICENSE_ROOT = pathlib.Path(__file__).resolve().parents[1]


@dataclass
class LicenseCheck:
    valid: bool
    reason: str
    provenance: dict[str, str | None]


def _version_stamp() -> str:
    """A stable fingerprint of the harness source, not of any person."""
    h = hashlib.sha256()
    for mod in sorted((_LICENSE_ROOT / "hostshift").rglob("*.py")):
        h.update(mod.read_bytes())
    return h.hexdigest()[:16]


def verify_license(root: pathlib.Path | None = None) -> LicenseCheck:
    """Report which licenses govern this checkout.

    Valid means: the expected dual-license pair is present and readable.
    This is an informational check for run records, not a gate.
    """
    root = root or _LICENSE_ROOT
    code = root / "LICENSE"
    data = root / "LICENSE-DATA"
    if not code.exists() or not data.exists():
        return LicenseCheck(
            valid=False,
            reason="LICENSE or LICENSE-DATA missing from repository root.",
            provenance={},
        )
    try:
        code_text = code.read_text(encoding="utf-8")
        data_text = data.read_text(encoding="utf-8")
    except OSError as exc:
        return LicenseCheck(
            valid=False, reason=f"Failed to read license files: {exc}", provenance={}
        )

    ok_code = "AFFERO GENERAL PUBLIC LICENSE" in code_text
    ok_data = "CC-BY-NC-SA-4.0" in data_text or "CC BY-NC-SA" in data_text
    if not (ok_code and ok_data):
        return LicenseCheck(
            valid=False,
            reason="License files do not match the expected AGPL-3.0 + CC BY-NC-SA 4.0 pair.",
            provenance={},
        )
    return LicenseCheck(
        valid=True,
        reason="Code: AGPL-3.0-or-later. Benchmark data: CC BY-NC-SA 4.0.",
        provenance={
            "code_license": "AGPL-3.0-or-later",
            "data_license": "CC-BY-NC-SA-4.0",
            "harness_fingerprint": _version_stamp(),
        },
    )


def stamp_provenance(artifact: dict) -> dict:
    """Attach provenance metadata to a generated artifact.

    Every run log, evaluation result, and published spec should carry this so
    that results are traceable to the harness version that produced them.
    """
    check = verify_license()
    watermark = {
        "_hostshift_provenance": {
            "project": "HostShift",
            "harness_version": __version__,
            "code_license": "AGPL-3.0-or-later",
            "data_license": "CC-BY-NC-SA-4.0",
            "harness_fingerprint": check.provenance.get("harness_fingerprint"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    }
    return {**artifact, **watermark}
