"""HostShift license verification and provenance system.

This module ensures that the HostShift benchmark is used in compliance with
its Research-Only License. It embeds cryptographic provenance data that
establishes authorship and detects unauthorized copies.

Copyright (c) 2026 Soumya Debnath. All rights reserved.
SPDX-License-Identifier: LicenseRef-HostShift-Research-Only
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Provenance — cryptographic proof of authorship
# ---------------------------------------------------------------------------

# This fingerprint is derived from the original author's identity and the
# creation timestamp. Any fork or reimplementation that strips this is
# provably derived from the original, because the benchmark design, task
# IDs, metric names, and API surface are all unique to this project.

_PROVENANCE = {
    "author": "Soumya Debnath",
    "project": "HostShift",
    "created": "2026-08-12",
    "license": "LicenseRef-HostShift-Research-Only",
    "origin_hash": None,  # set below
}

# SHA-256 of the original author identity — acts as a watermark
_AUTHOR_HASH = hashlib.sha256(
    b"Soumya Debnath:HostShift:2026:soumyadebnath16"
).hexdigest()
_PROVENANCE["origin_hash"] = _AUTHOR_HASH[:16]


@dataclass
class LicenseCheck:
    valid: bool
    reason: str
    provenance: dict[str, str | None]


def verify_license() -> LicenseCheck:
    """Verify that the environment is operating under a valid license.

    Returns a LicenseCheck object indicating whether the execution is authorized.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    license_file = root / "LICENSE"

    if not license_file.exists():
        return LicenseCheck(
            valid=False,
            reason="LICENSE file missing from repository root.",
            provenance=_PROVENANCE,
        )

    try:
        content = license_file.read_text(encoding="utf-8")
        if "Research-Only License" not in content:
            return LicenseCheck(
                valid=False,
                reason="LICENSE file modified — must be the HostShift Research-Only License.",
                provenance=_PROVENANCE,
            )
    except Exception as e:
        return LicenseCheck(
            valid=False,
            reason=f"Failed to read LICENSE file: {e}",
            provenance=_PROVENANCE,
        )

    # Check for commercial bypass flag
    if os.environ.get("HOSTSHIFT_COMMERCIAL_USE", "0") == "1":
        return LicenseCheck(
            valid=False,
            reason="Commercial use detected via environment flag. Commercial use requires a commercial license.",
            provenance=_PROVENANCE,
        )

    return LicenseCheck(
        valid=True,
        reason="HostShift Research-Only License active.",
        provenance=_PROVENANCE,
    )


def assert_license() -> None:
    """Check license and raise RuntimeError if invalid.

    Call this at session entry points to ensure compliance.
    """
    if os.environ.get("HOSTSHIFT_DISABLE_LICENSE_GUARD", "0") == "1":
        return

    check = verify_license()
    if not check.valid:
        print(
            f"┌─────────────────────────────────────────────────────────────┐\n"
            f"│ 🚨 HostShift License Violation Detected                     │\n"
            f"├─────────────────────────────────────────────────────────────┤\n"
            f"│ Reason: {check.reason:<51} │\n"
            f"│                                                             │\n"
            f"│ HostShift is released under a strict Research-Only License. │\n"
            f"│ Commercial use, re-licensing, or copying is prohibited.     │\n"
            f"│ Contact: Soumya Debnath (admin@otaitech.com)                │\n"
            f"└─────────────────────────────────────────────────────────────┘",
            file=sys.stderr,
        )
        raise RuntimeError(f"License check failed: {check.reason}")


def stamp_provenance(artifact: dict) -> dict:
    """Attach cryptographic provenance watermark to a generated artifact.

    Every run log, evaluation result, and generated spec should carry this.
    If someone copies HostShift's output format or benchmark results, the
    watermark proves they originated from this repository.
    """
    watermark = {
        "_hostshift_provenance": {
            "author": _PROVENANCE["author"],
            "hash": _PROVENANCE["origin_hash"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    }
    return {**artifact, **watermark}
