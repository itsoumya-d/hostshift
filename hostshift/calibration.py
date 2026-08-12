"""Operator calibration against human-authored native applications.

The problem this solves is the most serious one in the benchmark. Interaction
Parity is measured with a computer-use model whose training is heavily weighted
toward browsers. When the terminal host scores badly, raw IP cannot distinguish
"the generated interface is unusable there" from "the operator has never driven
a terminal." Every host-lock number is uninterpretable until that is separated.

The separation requires a control the benchmark does not otherwise have:
idiomatic, hand-written, known-good applications implementing comparable tasks
on every host. Whatever the operator cannot accomplish on software a competent
engineer wrote by hand is the operator's ceiling, not the generator's failure.

The corpus used here is the Token Gallery `ProductFlow` application from the
mobile-native-design-system project, which implements the same product shape --
entry, navigation, list, detail, form, settings, sheet, and async/error/empty
states -- independently in Flutter, React Native, SwiftUI and Jetpack Compose.

Three properties make it a better control than a corpus written for this
purpose would have been:

  1. It was authored before this benchmark existed, so it cannot have been
     shaped, consciously or otherwise, to flatter any renderer here.
  2. The four implementations are independent idiomatic native code, not one
     codebase cross-compiled, so they carry the genuine per-platform
     conventions an operator would meet in the wild.
  3. It ships with its own tests, so "known-good" is a checkable claim rather
     than an assertion.

The corpus is referenced at a pinned commit and never vendored. Vendoring would
fork it silently the first time upstream changed, and a calibration corpus that
has quietly diverged from the thing it claims to be is worse than none.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .metrics import OperatorCeiling, TaskOutcome, calibration_report, host_lock_index, normalized_host_lock

CORPUS_REPO = "https://github.com/itsoumya-d/mobile-native-design-system"

# Pin this before the calibration run and record it in the paper. An unpinned
# corpus makes the ceiling unreproducible, and the ceiling is what every
# normalized number divides by.
# Pinned to the v2.0.0 release commit. A tag is not enough: tags can be moved,
# and a ceiling measured against a corpus that silently changed underneath it
# is not reproducible.
CORPUS_REF = "eb6a3aaf8c6b77e33ba418b4eb05eb0227035ec3"
CORPUS_TAG = "v2.0.0"
CORPUS_VERIFIED = "2026-08-04"
CORPUS_LICENSE = "MIT"

FIXTURE_PATHS = {
    "flutter": "fixtures/flutter",
    "react-native": "fixtures/react-native",
    "swiftui": "fixtures/swiftui",
    "compose": "fixtures/compose",
}

# How corpus platforms map onto HostShift hosts. Flutter and React Native both
# render to Android and iOS, so they can calibrate either; the mapping below is
# the conservative reading and should be stated explicitly in the paper rather
# than left for a reviewer to infer.
HOST_FIXTURE = {
    "compose": "compose",
    "swiftui": "swiftui",
    # The web host has no counterpart in a native corpus. Its ceiling must come
    # from a separate web corpus, or be reported as uncalibrated -- claiming a
    # native fixture calibrates a browser would be worse than admitting the gap.
    "web": None,
    # Likewise the terminal. A terminal ceiling needs hand-written TUI apps.
    "tui": None,
}


@dataclass
class CalibrationTask:
    """A task the operator attempts against the hand-written corpus.

    Deliberately phrased against the corpus's own product shape rather than
    against HostShift's task suite. The point is to measure what the operator
    can do on this host at all, not to re-run the benchmark on different code.
    """

    id: str
    goal: str
    surface: str
    notes: str = ""


# Drawn from the product shape the corpus implements identically on all four
# platforms. Each exercises an interaction class that also appears in the
# HostShift suite, so the ceiling is comparable to the thing it normalizes.
CALIBRATION_TASKS = [
    CalibrationTask("cal-entry", "Complete the entry flow and reach the main screen",
                    "entry", "authentication-shaped gate"),
    CalibrationTask("cal-list-open", "Open a specific item from the main list",
                    "list", "row selection by accessible name"),
    CalibrationTask("cal-detail-act", "Perform the primary action on an item's detail screen",
                    "detail", "state mutation from a nested screen"),
    CalibrationTask("cal-form-valid", "Fill the form correctly and submit it",
                    "form", "validation gating"),
    CalibrationTask("cal-form-invalid", "Submit the form with an invalid field and observe the rejection",
                    "form", "error perceivability"),
    CalibrationTask("cal-settings", "Change a specific setting and confirm it persists",
                    "settings", "toggle plus persistence"),
    CalibrationTask("cal-sheet", "Open the modal sheet and dismiss it without acting",
                    "sheet", "overlay dismissal"),
    CalibrationTask("cal-empty", "Reach the empty state and confirm it is announced",
                    "async", "empty-state perceivability"),
    CalibrationTask("cal-error", "Trigger the error state and read the message",
                    "async", "error-state perceivability"),
    CalibrationTask("cal-back", "Navigate two levels deep and return to the root",
                    "navigation", "back-stack integrity"),
]


@dataclass
class CalibrationRun:
    """Recorded outcomes of the operator attempting the corpus on one host."""

    host: str
    fixture: str
    operator: str
    corpus_ref: str = CORPUS_REF
    outcomes: list[dict] = field(default_factory=list)

    def record(self, task_id: str, success: bool, steps: int = 0, note: str = "") -> None:
        self.outcomes.append(
            {"task_id": task_id, "success": bool(success), "steps": steps, "note": note})

    def ceiling(self) -> OperatorCeiling:
        return OperatorCeiling(
            host=self.host,
            attempted=len(self.outcomes),
            completed=sum(1 for o in self.outcomes if o["success"]),
            corpus=f"{CORPUS_REPO}@{self.corpus_ref}:{self.fixture}",
        )


class CalibrationStore:
    """Persisted calibration runs. Kept apart from the experiment run log so a
    ceiling can be reused across experiment re-runs without being recomputed --
    and so it is obvious in the released artifacts which numbers came from
    hand-written code and which from generated code."""

    def __init__(self, root: str = "runs/calibration"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, run: CalibrationRun) -> Path:
        p = self.root / f"{run.host}.json"
        p.write_text(json.dumps(asdict(run), indent=2))
        return p

    def load_all(self) -> dict[str, CalibrationRun]:
        out: dict[str, CalibrationRun] = {}
        for p in sorted(self.root.glob("*.json")):
            out[p.stem] = CalibrationRun(**json.loads(p.read_text()))
        return out

    def ceilings(self) -> dict[str, OperatorCeiling]:
        return {h: r.ceiling() for h, r in self.load_all().items()}


def fetch_corpus(dest: str = "corpus", ref: str = CORPUS_REF) -> Path:
    """Shallow-clone the corpus at a pinned ref.

    Cloning rather than vendoring keeps provenance honest: the released
    benchmark records which upstream commit the ceiling was measured against,
    and anyone can check out the same one.
    """
    target = Path(dest)
    if target.exists():
        return target
    # A shallow clone cannot be made directly at an arbitrary SHA, so fetch the
    # single object and detach onto it. This keeps the pin exact rather than
    # settling for whatever the branch currently points at.
    subprocess.run(["git", "init", "-q", str(target)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin", CORPUS_REPO],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(target), "fetch", "-q", "--depth", "1", "origin", ref],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(target), "checkout", "-q", "FETCH_HEAD"],
                   check=True, capture_output=True)
    return target


def corpus_provenance() -> dict:
    """What the paper must state about the calibration corpus.

    Printed into the released artifacts so the ceiling can be reproduced
    against exactly the code it was measured on.
    """
    return {
        "repo": CORPUS_REPO,
        "commit": CORPUS_REF,
        "tag": CORPUS_TAG,
        "license": CORPUS_LICENSE,
        "verified": CORPUS_VERIFIED,
        "fixtures": dict(FIXTURE_PATHS),
        "role": "operator calibration only; not part of the system under test",
    }


def report(outcomes: list[TaskOutcome], store: CalibrationStore | None = None) -> dict:
    """Raw and ceiling-normalized host-lock, side by side.

    Both always. If normalized lock stays high the portability claim survives
    and is much harder to attack; if it collapses, most of the apparent
    host-lock was operator unfamiliarity, and that is the finding -- a more
    interesting one about the operator rather than a weaker one about
    interfaces. Reporting only whichever is more flattering would be the single
    easiest way to mislead with this benchmark.
    """
    store = store or CalibrationStore()
    ceilings = store.ceilings()
    raw = host_lock_index(outcomes)

    if not ceilings:
        return {
            "raw_hli": round(raw.hli, 4),
            "per_task_lock": round(raw.per_task_lock, 4),
            "normalized_hli": None,
            "status": "UNCALIBRATED — every host-lock figure here conflates "
                      "interface portability with operator competence and must "
                      "not be reported as a finding",
        }

    norm = normalized_host_lock(outcomes, ceilings)
    out = calibration_report(ceilings, raw, norm)
    uncalibrated = sorted({o.host for o in outcomes} - set(ceilings))
    if uncalibrated:
        out["uncalibrated_hosts"] = uncalibrated
        out["warning"] = (
            f"no operator ceiling for {', '.join(uncalibrated)}; their raw "
            f"figures cannot be compared against calibrated hosts"
        )
    return out
