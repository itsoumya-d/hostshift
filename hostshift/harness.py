"""Generation and operation harness.

Two adapter families, both deliberately thin:

  Generator -- turns a task prompt into an artifact, under condition A
               (freeform framework code, one generation per host) or condition B
               (one host-independent UISpec, rendered to every host).

  Operator  -- drives a rendered artifact toward the task goal and returns the
               post-run state snapshot plus the handful of UI facts the oracle
               needs.

Nothing here calls a model directly; every provider sits behind an adapter so
the experiment can be replayed from a cache and so a reviewer can swap in their
own model without touching the benchmark. All runs are recorded to disk, because
an unreproducible benchmark is an anecdote.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Protocol

HOSTS = ("web", "swiftui", "compose", "tui")

CONDITION_A = "A-freeform"      # model emits framework code directly, per host
CONDITION_B_NAIVE = "B-naive"   # one UISpec; first-pass runtime, platform defaults only
CONDITION_B = "B-schema"        # one UISpec; runtime that does the accessibility work

# Reported in this order. The middle arm is what makes the comparison honest:
# A vs B alone would credit the representation with work the renderer did.
CONDITIONS = (CONDITION_A, CONDITION_B_NAIVE, CONDITION_B)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Artifact:
    task_id: str
    condition: str
    generator: str
    host: str | None          # None for condition B (host-independent)
    payload: str              # source code, or serialized UISpec
    valid: bool = False       # parsed / compiled cleanly
    repair_rounds: int = 0
    gen_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None

    def key(self) -> str:
        raw = f"{self.task_id}|{self.condition}|{self.generator}|{self.host}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class RunRecord:
    task_id: str
    condition: str
    generator: str
    host: str
    operator: str
    success: bool = False
    steps: int = 0
    criteria_met: int = 0
    criteria_total: int = 0
    probes_passed: int = 0
    probes_total: int = 0
    render_parity: float | None = None
    a11y_parity: float | None = None
    failures: list[str] = field(default_factory=list)
    wall_ms: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Adapter protocols
# ---------------------------------------------------------------------------


class Generator(Protocol):
    name: str

    def generate_spec(self, task: dict) -> Artifact:
        """Condition B: emit one host-independent UISpec."""

    def generate_code(self, task: dict, host: str) -> Artifact:
        """Condition A: emit framework code for one host."""


class Renderer(Protocol):
    host: str

    def render(self, artifact: Artifact) -> "Session":
        """Bring the artifact up and return a live session."""


class Session(Protocol):
    def widget_tree(self):  # -> Widget
        """Canonical widget tree, lowered from the host's a11y/view hierarchy."""

    def state(self) -> dict:
        """Declared application state and collections, as JSON."""

    def ui_facts(self) -> dict:
        """Perceivability facts the oracle needs (errors, empty states,
        enablement, visible row counts) -- read from the accessibility tree, not
        from pixels, so the comparison stays host-fair."""

    def close(self) -> None: ...


class Operator(Protocol):
    name: str

    def run(self, session: Session, goal: str, max_steps: int) -> int:
        """Drive the session toward the goal. Returns steps taken."""


# ---------------------------------------------------------------------------
# Reference operator: Gemini computer-use
# ---------------------------------------------------------------------------


class ComputerUseOperator:
    """Operator backed by a computer-use model.

    Using a production computer-use model as the measurement instrument is a
    deliberate choice with a tradeoff worth stating in the paper: it makes the
    benchmark directly relevant to deployed agents, but it couples the numbers
    to one vendor's model. The mitigation is the accessibility-tree operator
    below, which is deterministic and model-free -- reporting both separates
    'this UI is inoperable' from 'this operator could not operate it'.
    """

    def __init__(self, model: str = "gemini-3.5-flash", api_key_env: str = "GEMINI_API_KEY"):
        self.name = model
        self.model = model
        self.api_key = os.environ.get(api_key_env)
        self._client = None

    def run(self, session: Session, goal: str, max_steps: int) -> int:
        if not self.api_key:
            raise RuntimeError(
                f"no API key in environment; set it before running the operator"
            )
        steps = 0
        while steps < max_steps:
            steps += 1
            action = self._next_action(session, goal, steps)
            if action is None or action.get("op") == "done":
                break
            self._apply(session, action)
        return steps

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _next_action(self, session: Session, goal: str, step: int) -> dict | None:
        """Ask the model for the next action given a screenshot + a11y tree.

        Implemented against the provider's computer-use tool. Kept as a single
        seam so the whole experiment can be re-run against a different operator
        by substituting this method.
        """
        from google.genai import types

        client = self._get_client()

        actions = session.actions()
        state = session.state()
        ui_facts = session.ui_facts()

        prompt = (
            f"Goal: {goal}\n"
            f"Step: {step}\n"
            f"Current state: {json.dumps(state)}\n"
            f"UI facts: {json.dumps(ui_facts)}\n"
            f"Available actions: {json.dumps(actions)}\n\n"
            "Based on the above, decide the next action to achieve the goal.\n"
            "Return a JSON object with one of the following formats:\n"
            "1. To perform an action: {\"op\": \"invoke\", \"id\": \"<node_id>\", \"value\": <optional_value>}\n"
            "2. If the goal is achieved: {\"op\": \"done\"}"
        )

        try:
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception:
            return {"op": "done"}

    def _apply(self, session: Session, action: dict) -> None:
        if action.get("op") == "invoke" and "id" in action:
            session.invoke(action["id"], action.get("value"))


class AccessibilityTreeOperator:
    """Deterministic, model-free operator.

    Walks the accessibility tree and executes a scripted policy derived from the
    task goal. Weaker than a computer-use model, but it has two properties the
    paper needs: it is free, and it is identical across hosts by construction,
    so any interaction-parity gap it reports is attributable to the interface
    rather than to model variance. Use it for the ablations, where the number of
    runs would otherwise make API cost prohibitive.
    """

    name = "a11y-scripted"

    def run(self, session: Session, goal: str, max_steps: int) -> int:
        steps = 0
        while steps < max_steps:
            actions = session.actions()
            if not actions:
                break
                
            action_taken = False
            
            # Scripted policy: fill fields, toggle toggles, click buttons in order
            for kind_group in [["text_field", "textfield", "input", "field"], ["toggle", "checkbox", "switch"], ["button", "action"]]:
                for act in actions:
                    kind = str(act.get("kind", "")).lower()
                    if kind in kind_group:
                        if kind in ["text_field", "textfield", "input", "field"] and not act.get("value"):
                            session.invoke(act["id"], "scripted input")
                            action_taken = True
                            break
                        elif kind in ["toggle", "checkbox", "switch"] and not act.get("value"):
                            session.invoke(act["id"], True)
                            action_taken = True
                            break
                        elif kind in ["button", "action"]:
                            session.invoke(act["id"], None)
                            action_taken = True
                            break
                if action_taken:
                    break
                    
            if not action_taken:
                break
                
            steps += 1
            
        return steps


# ---------------------------------------------------------------------------
# Repair loop (shared by both conditions -- this is the fairness control)
# ---------------------------------------------------------------------------


def repair(
    artifact: Artifact,
    validate,
    regenerate,
    max_rounds: int = 3,
) -> Artifact:
    """Iteratively repair an invalid artifact.

    Both conditions get the identical repair budget. This matters: a large part
    of any schema-versus-code advantage is that schema errors are machine-
    checkable, and if condition B silently got more repair attempts the result
    would be an artefact of the harness rather than a finding.
    """
    current = artifact
    for round_no in range(1, max_rounds + 1):
        ok, diagnostic = validate(current)
        if ok:
            current.valid = True
            return current
        current = regenerate(current, diagnostic)
        current.repair_rounds = round_no
    current.valid, _ = validate(current)[0], None
    return current


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class Store:
    """Append-only run log. Every artifact and every run lands on disk so the
    experiment is replayable and the released benchmark ships with its own
    evidence."""

    def __init__(self, root: str = "runs"):
        self.root = Path(root)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        self.runlog = self.root / "runs.jsonl"

    def save_artifact(self, a: Artifact) -> Path:
        p = self.root / "artifacts" / f"{a.key()}.json"
        p.write_text(json.dumps(asdict(a), indent=2))
        return p

    def load_artifact(self, task_id: str, condition: str, generator: str, host: str | None):
        probe = Artifact(task_id, condition, generator, host, payload="")
        p = self.root / "artifacts" / f"{probe.key()}.json"
        if p.exists():
            return Artifact(**json.loads(p.read_text()))
        return None

    def record(self, r: RunRecord) -> None:
        with self.runlog.open("a") as fh:
            fh.write(json.dumps({**asdict(r), "ts": int(time.time())}) + "\n")

    def all_runs(self) -> list[RunRecord]:
        if not self.runlog.exists():
            return []
        out = []
        for line in self.runlog.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                d.pop("ts", None)
                out.append(RunRecord(**d))
        return out
