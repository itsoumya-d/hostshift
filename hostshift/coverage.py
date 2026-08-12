"""Schema coverage: what fraction of real requests can UISpec 0.2 express?

The objection this answers is that the task suite was written by the same person
who designed the schema, so every task is expressible in it by construction.
Condition B therefore competes on home ground, and any advantage it shows is an
upper bound on a biased sample.

The bias is real and cannot be argued away. What it can be is *quantified*: if
UISpec covers some measurable fraction of an independently-authored corpus of
application requests, and the suite is drawn from that covered region, then the
limitation becomes a stated scope condition rather than a hidden thumb on the
scale. If coverage turns out to be low, that is worth knowing before a reviewer
says it.

Two rules make this analysis worth anything:

  1. **The corpus must be externally authored.** Prompts written here, for this
     purpose, answer nothing. `load_corpus` records a source for every entry and
     the report refuses to run without one.
  2. **The classifier is a first pass, not a verdict.** Detection is by explicit
     capability patterns so it is deterministic and auditable, but natural
     language will defeat any pattern set. Hand-audit a stratified sample and
     report the agreement rate alongside the coverage figure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# What the schema cannot express
# ---------------------------------------------------------------------------

# Each entry: capability -> patterns that indicate a request needs it.
# Deliberately conservative. A pattern here should be something UISpec 0.2
# genuinely cannot represent, not merely something it represents awkwardly --
# inflating this list would understate coverage and flatter the objection.
OUT_OF_SCOPE: dict[str, list[str]] = {
    # Narrow deliberately: a sort control that *reorders results* is expressible;
    # only direct manipulation is not. The first pass at this matched the word
    # "reorder" and flagged an ordinary sort task.
    "drag_reorder": [r"\bdrag[- ]and[- ]drop", r"drag.{0,20}(to )?(reorder|rearrang)",
                     r"(reorder|rearrang).{0,20}by dragging", r"\bkanban\b",
                     r"sortable list", r"swipe to reorder", r"drag.{0,12}handle"],
    "canvas_drawing": [r"\bcanvas\b", r"\bdraw(ing)?\b", r"sketch", r"whiteboard",
                       r"annotat", r"signature"],
    "data_visualisation": [r"\bchart", r"\bgraph\b", r"plot\b", r"dashboard with",
                           r"visuali[sz]ation", r"sparkline", r"histogram"],
    "maps_geo": [r"\bmap\b", r"\bmaps\b", r"geoloc", r"latitude", r"marker",
                 r"directions", r"nearby"],
    "camera_media_capture": [r"\bcamera\b", r"take a photo", r"scan(ner|ning)?\b",
                             r"\bqr\b", r"barcode", r"record (audio|video)",
                             r"microphone"],
    "rich_text_editing": [r"rich text", r"wysiwyg", r"markdown editor",
                          r"text editor", r"formatting toolbar"],
    "realtime_collaboration": [r"real[- ]?time", r"collaborat", r"live cursor",
                               r"presence", r"websocket", r"multiplayer"],
    "file_handling": [r"\bupload", r"file picker", r"\battach a\b", r"\bdownload",
                      r"drag.{0,12}file"],
    "media_playback": [r"video player", r"audio player", r"playback", r"streaming video"],
    # A billing *address* is a form; taking money is not. The distinction is the
    # whole point -- flagging every mention of billing would understate coverage
    # on exactly the CRUD-shaped requests the schema handles well.
    "payments": [r"process(ing)? (a )?payment", r"take (a )?payment", r"credit card",
                 r"\bstripe\b", r"checkout with", r"charge the (customer|card)",
                 r"payment (gateway|processor|provider)"],
    "auth_provider": [r"oauth", r"sign in with", r"single sign[- ]?on", r"\bsso\b",
                      r"biometric", r"face ?id", r"fingerprint"],
    "notifications": [r"push notification", r"background sync", r"local notification"],
    # "Spring morning" is not a spring animation. Require the motion sense
    # explicitly rather than matching an evocative noun.
    "animation_motion": [r"\banimat(e|ed|ion|ions)\b", r"transition effect",
                         r"parallax", r"spring (animation|physics|curve)",
                         r"(swipe|pinch|drag|long[- ]press) gesture",
                         r"gesture recogni[sz]er", r"motion (spec|curve|design)"],
    "custom_layout": [r"masonry", r"carousel", r"infinite scroll", r"pull to refresh",
                      r"bottom sheet with", r"split view"],
    "device_hardware": [r"bluetooth", r"\bnfc\b", r"accelerometer", r"haptic",
                        r"offline sync"],
}

# Constructs the schema does express. Used to tell "no recognised UI at all"
# (probably not an application request) from "expressible".
#
# These are matched as prefixes rather than whole words. A false positive here
# only moves a prompt from "not an app request" into the denominator, where it
# will be judged on its blocking capabilities anyway; a false negative silently
# drops a real request from the study and distorts the coverage figure. The
# asymmetry is deliberate -- an earlier pass with trailing word boundaries
# failed to match "selects" and "confirms" and dropped a genuine request.
IN_SCOPE: dict[str, list[str]] = {
    "form": [r"\bform", r"\binput", r"\bfield", r"\bsubmit", r"\bvalidat",
             r"\benter\b", r"\btype\b"],
    "list": [r"\blist", r"\bitems?\b", r"\brows?\b", r"\bfeed\b", r"\bcatalog",
             r"\btable\b", r"\bgrid\b"],
    "detail": [r"\bdetail", r"\bview a\b", r"tap.{0,20}(to (see|open|view))",
               r"\bopen (a|an|the)\b"],
    "navigation": [r"\bscreens?\b", r"\bnavigat", r"\bback\b", r"\btabs?\b",
                   r"\bpages?\b", r"\bstep (one|two|three|\d)", r"\bwizard\b",
                   r"\bflow\b"],
    "toggle": [r"\btoggle", r"\bswitch", r"\bcheckbox", r"enable/disable",
               r"\bsettings?\b"],
    "selection": [r"\bdropdown", r"\bpicker", r"\bselect", r"\bchoose", r"\bchoic",
                  r"\bradio\b", r"\bpick\b", r"\boption"],
    "search_filter": [r"\bsearch", r"\bfilter", r"\bsort", r"\bquer"],
    "dialog": [r"\bdialog", r"\bmodal\b", r"\bconfirm", r"\bpopup\b", r"\bsheet\b"],
    "empty_error": [r"empty state", r"error (state|message)", r"loading state",
                    r"\brecords?\b", r"\bsaves?\b", r"\bcreat"],
}

VERDICTS = ("expressible", "partial", "out_of_scope", "not_an_app_request")


@dataclass
class PromptRecord:
    id: str
    prompt: str
    source: str
    verdict: str | None = None
    blocking: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    hand_audited: str | None = None      # a human's verdict, when one exists

    def agrees(self) -> bool | None:
        if self.hand_audited is None:
            return None
        return self.hand_audited == self.verdict


def _hits(text: str, patterns: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return sorted({cap for cap, pats in patterns.items()
                   if any(re.search(p, low) for p in pats)})


def classify(prompt: str) -> tuple[str, list[str], list[str]]:
    """First-pass verdict for one request.

    `partial` is the important middle category: a request whose core is
    expressible but which also asks for something the schema cannot do. Folding
    those into either extreme would misstate coverage in whichever direction
    happened to be convenient.
    """
    blocking = _hits(prompt, OUT_OF_SCOPE)
    matched = _hits(prompt, IN_SCOPE)

    if not matched and not blocking:
        return "not_an_app_request", blocking, matched
    if blocking and not matched:
        return "out_of_scope", blocking, matched
    if blocking:
        return "partial", blocking, matched
    return "expressible", blocking, matched


def load_corpus(path: str) -> list[PromptRecord]:
    """Read a JSONL corpus of `{id, prompt, source}`.

    `source` is mandatory and must not name this project. A coverage study run
    against prompts written for the study proves nothing, and making that
    impossible to do by accident is worth the strictness.
    """
    out: list[PromptRecord] = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        d = json.loads(line)
        for required in ("id", "prompt", "source"):
            if not d.get(required):
                raise ValueError(f"{path}:{i} missing {required!r}")
        if re.search(r"hostshift|uispec", str(d["source"]), re.I):
            raise ValueError(
                f"{path}:{i} source {d['source']!r} is this project. The corpus "
                f"must be externally authored or the study answers nothing."
            )
        out.append(PromptRecord(id=d["id"], prompt=d["prompt"], source=d["source"],
                                hand_audited=d.get("hand_audited")))
    return out


def analyse(records: list[PromptRecord]) -> dict:
    for r in records:
        r.verdict, r.blocking, r.matched = classify(r.prompt)

    n = len(records)
    counts = {v: sum(1 for r in records if r.verdict == v) for v in VERDICTS}
    app_requests = n - counts["not_an_app_request"]

    blocking_freq: dict[str, int] = {}
    for r in records:
        for cap in r.blocking:
            blocking_freq[cap] = blocking_freq.get(cap, 0) + 1

    audited = [r for r in records if r.hand_audited is not None]
    agreement = (sum(1 for r in audited if r.agrees()) / len(audited)) if audited else None

    return {
        "n": n,
        "sources": sorted({r.source for r in records}),
        "counts": counts,
        "app_requests": app_requests,
        "coverage_full": round(counts["expressible"] / app_requests, 4) if app_requests else None,
        "coverage_partial_or_better": round(
            (counts["expressible"] + counts["partial"]) / app_requests, 4)
            if app_requests else None,
        "top_blockers": sorted(blocking_freq.items(), key=lambda kv: -kv[1])[:8],
        "hand_audited": len(audited),
        "classifier_agreement": round(agreement, 4) if agreement is not None else None,
    }


def format_report(summary: dict) -> str:
    lines = [
        "Schema coverage of UISpec 0.2",
        "=" * 60,
        f"corpus            {summary['n']} prompts from {len(summary['sources'])} source(s)",
        f"                  {', '.join(summary['sources'])}",
        f"application reqs  {summary['app_requests']}",
        "",
        f"  fully expressible      {summary['counts']['expressible']}",
        f"  partially expressible  {summary['counts']['partial']}",
        f"  out of scope           {summary['counts']['out_of_scope']}",
        f"  not an app request     {summary['counts']['not_an_app_request']}",
        "",
    ]
    if summary["coverage_full"] is not None:
        lines += [
            f"COVERAGE  {summary['coverage_full']:.1%} fully, "
            f"{summary['coverage_partial_or_better']:.1%} at least partially",
            "",
        ]
    if summary["top_blockers"]:
        lines.append("most common blocking capabilities:")
        for cap, k in summary["top_blockers"]:
            lines.append(f"  {cap:<26}{k}")
        lines.append("")
    if summary["classifier_agreement"] is None:
        lines += [
            "NO HAND AUDIT. The classifier is pattern-based and will be wrong on",
            "natural language it did not anticipate. Hand-audit a stratified sample",
            "and record `hand_audited` before citing any figure above.",
        ]
    else:
        lines.append(f"classifier agreement with hand audit: "
                     f"{summary['classifier_agreement']:.1%} "
                     f"over {summary['hand_audited']} prompts")
    return "\n".join(lines)


def suite_self_check(suite_path: str) -> dict:
    """Run the classifier over HostShift's own task suite.

    Expected to come back at or near 100% expressible -- the suite was written
    against the schema. That is not a result, it is the *measurement of the
    bias*: it establishes the ceiling that an external corpus must be compared
    against, and it makes the size of the home-ground advantage explicit rather
    than leaving a reviewer to assert it.
    """
    records = []
    for line in Path(suite_path).read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        records.append(PromptRecord(id=t["id"], prompt=f"{t['prompt']} {t['goal']}",
                                    source="hostshift-suite"))
    for r in records:
        r.verdict, r.blocking, r.matched = classify(r.prompt)
    n = len(records)
    return {
        "n": n,
        "expressible": sum(1 for r in records if r.verdict == "expressible"),
        "partial": sum(1 for r in records if r.verdict == "partial"),
        "self_coverage": round(
            sum(1 for r in records if r.verdict == "expressible") / n, 4) if n else None,
        "flagged": [(r.id, r.blocking) for r in records if r.blocking][:10],
    }
