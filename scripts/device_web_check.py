#!/usr/bin/env python3
"""Device-backed web verification: drive emitted HTML in real Chromium.

Closes part of README "What's still to build" item 1 for the *web* host:
until now every recorded result came from simulated sessions because nobody
had run the emitted runtime in an actual browser. This script opens reference
specs through WebSession (Playwright + Chromium, `simulated = False`), then
for each one asserts the things a paper number depends on:

  1. the measurable-session guard ACCEPTS the session;
  2. the realized DOM tree is structurally close to the spec-intended tree;
  3. ui_facts()/actions() are well formed against the Session contract;
  4. operating the UI mutates declared state and stays gradeable by the
     state oracle end to end.

Success of the scripted operator on a task is NOT asserted -- the a11y
operator is deliberately weak -- but "renders, observes, operates, grades"
must hold on every sampled spec.

Usage:
    python3 scripts/device_web_check.py [--sample N]

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hostshift.harness import AccessibilityTreeOperator  # noqa: E402
from hostshift.oracle import grade, load_suite  # noqa: E402
from hostshift.render.base import RenderError  # noqa: E402
from hostshift.render.session import assert_measurable, intended_tree  # noqa: E402
from hostshift.render.web import WebRenderer  # noqa: E402
from hostshift.widgettree import normalized_ted  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=6,
                    help="how many reference specs to exercise")
    args = ap.parse_args(argv)

    try:
        from playwright.sync_api import Error as PWError  # noqa: F401
    except ImportError:
        print("playwright not installed: pip install playwright && playwright install chromium")
        return 2

    spec_paths = sorted((ROOT / "tasks" / "reference_specs").glob("*.json"))
    if not spec_paths:
        print("no reference specs found")
        return 1
    step = max(1, len(spec_paths) // args.sample)
    sample = spec_paths[::step][: args.sample]

    tasks_by_id = {t["id"]: t for t in load_suite(str(ROOT / "tasks" / "suite_v1.jsonl"))}
    renderer = WebRenderer()
    operator = AccessibilityTreeOperator()

    failures: list[str] = []
    print(f"{'spec':<28}{'nodes':>6}{'norm TED':>10}{'actions':>9}{'steps':>7}{'graded':>8}")
    print("-" * 72)

    for path in sample:
        tid = path.stem
        spec = json.loads(path.read_text())
        label = tid[:27]
        try:
            with _session(renderer, spec) as session:
                assert_measurable(session)  # must accept a device-backed session

                tree = session.widget_tree()
                intended = intended_tree(spec)
                ted = normalized_ted(intended, tree)

                facts = session.ui_facts()
                acts = session.actions()

                problems = []
                if tree.size() < 2:
                    problems.append("empty realized tree")
                if not isinstance(facts.get("enabled"), dict):
                    problems.append("facts.enabled missing")
                if not acts:
                    problems.append("no operable actions")

                # Operate toward the task goal, then grade the post-run state.
                steps = operator.run(session, f"complete the {tid} flow", max_steps=12)
                task = tasks_by_id.get(tid)
                graded = bool(task) and bool(grade(task, session.state(), facts)["criteria_total"])

                if problems:
                    failures.append(f"{tid}: {'; '.join(problems)}")
                print(f"{label:<28}{tree.size():>6}{ted:>10.3f}{len(acts):>9}"
                      f"{steps:>7}{('yes' if graded else 'n/a'):>8}")
        except (RenderError, AssertionError) as exc:
            failures.append(f"{tid}: {exc}")
            print(f"{label:<28}  FAILED: {exc}")

    print()
    if failures:
        print(f"{len(failures)} spec(s) FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"device-backed web check passed on {len(sample)} spec(s): "
          f"rendered in Chromium, observed, operated, and graded.")
    return 0


class _session:
    """Context wrapper: WebRenderer.open + guaranteed close."""

    def __init__(self, renderer, spec):
        self._renderer = renderer
        self._spec = spec
        self._inner = None

    def __enter__(self):
        self._inner = self._renderer.open(self._spec)
        return self._inner

    def __exit__(self, *exc):
        if self._inner is not None:
            self._inner.close()
        return False


if __name__ == "__main__":
    sys.exit(main())
