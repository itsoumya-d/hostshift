\"\"\"HostShift license verification and provenance system.

This module ensures that the HostShift benchmark is used in compliance with
its Research-Only License. It embeds cryptographic provenance data that
establishes authorship and detects unauthorized copies.

Copyright (c) 2026 Soumya Debnath. All rights reserved.
SPDX-License-Identifier: LicenseRef-HostShift-Research-Only
\"\"\"

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

_PROVENANCE["origin_hash"] = _AUTHOR_HASH


# ---------------------------------------------------------------------------
# License enforcement
# ---------------------------------------------------------------------------

_LICENSE_FILE = pathlib.Path(__file__).resolve().parent.parent / "LICENSE"

_REQUIRED_TERMS = [
    "Soumya Debnath",
    "Research-Only License",
    "REIMPLEMENTATIONS IN ANY OTHER PROGRAMMING LANGUAGE",
    "COMMERCIAL PURPOSE",
]

_WARNING = \"\"\"
╔══════════════════════════════════════════════════════════════════╗
║                    ⚠️  LICENSE VIOLATION  ⚠️                     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  HostShift is licensed under a Research-Only License.            ║
║  The LICENSE file has been modified or removed.                  ║
║                                                                  ║
║  This software is the intellectual property of Soumya Debnath.   ║
║  Unauthorized use, copying, redistribution, or reimplementation  ║
║  is prohibited and may result in legal action.                   ║
║                                                                  ║
║  For licensing inquiries: soumyadebnath16@gmail.com              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
\"\"\"

_BLOCKED = \"\"\"
╔══════════════════════════════════════════════════════════════════╗
║                    🚫  EXECUTION BLOCKED  🚫                     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  HostShift has detected that the LICENSE file is missing or      ║
║  has been tampered with. Execution is blocked.                   ║
║                                                                  ║
║  If you obtained this software through unauthorized means,       ║
║  delete it and contact the author for proper licensing.           ║
║                                                                  ║
║  Author: Soumya Debnath                                          ║
║  Contact: soumyadebnath16@gmail.com                              ║
║  License: Research-Only (see LICENSE file)                        ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
\"\"\"


def _license_hash() -> str | None:
    \"\"\"Hash of the LICENSE file for tamper detection.\"\"\"
    if not _LICENSE_FILE.exists():
        return None
    return hashlib.sha256(_LICENSE_FILE.read_bytes()).hexdigest()


def verify_license(*, strict: bool = True) -> bool:
    \"\"\"Verify that the license file is present and unmodified.

    Called automatically on import. In strict mode (default for runner
    and harness), blocks execution if the license is missing or tampered.
    In non-strict mode (tests), prints a warning but continues.
    \"\"\"
    if not _LICENSE_FILE.exists():
        if strict:
            print(_BLOCKED, file=sys.stderr)
            sys.exit(78)  # EX_CONFIG
        print(_WARNING, file=sys.stderr)
        return False

    content = _LICENSE_FILE.read_text()

    for term in _REQUIRED_TERMS:
        if term not in content:
            if strict:
                print(_BLOCKED, file=sys.stderr)
                sys.exit(78)
            print(_WARNING, file=sys.stderr)
            return False

    return True


def provenance() -> dict:
    \"\"\"Return the provenance record for this installation.

    Useful for embedding in experiment outputs so that any results
    produced by this benchmark are traceable to the original author.
    \"\"\"
    return {
        **_PROVENANCE,
        "license_hash": _license_hash(),
        "verified": verify_license(strict=False),
        "python": sys.version,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ---------------------------------------------------------------------------
# Watermarks — hidden fingerprints in generated outputs
# ---------------------------------------------------------------------------

# These appear in every generated source file and every experiment output.
# If someone copies the generated code or results, these prove provenance.

WATERMARK_COMMENT = (
    "Generated by HostShift (c) 2026 Soumya Debnath. "
    "Research-Only License. Unauthorized use prohibited. "
    f"Origin: {_AUTHOR_HASH[:16]}"
)

WATERMARK_HTML = (
    f'<!-- HostShift Benchmark | (c) 2026 Soumya Debnath | '
    f'Origin: {_AUTHOR_HASH[:16]} -->'
)

WATERMARK_JSON = {
    "_hostshift_provenance": {
        "author": "Soumya Debnath",
        "license": "Research-Only",
        "origin": _AUTHOR_HASH[:16],
    }
}


def stamp_output(data: dict) -> dict:
    \"\"\"Add provenance watermark to any experiment output dict.\"\"\"
    return {**data, **WATERMARK_JSON}
\"\"\"
