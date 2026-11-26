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
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

HOSTS = ("web", "swiftui", "compose", "flutter", "tui")

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

    def render(self, artifact: Artifact) -> Session:
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

    def actions(self) -> list[dict]:
        """Interactable elements, as the operator sees them.

        Each entry: {id, kind, name, enabled, value, options}. Identical across
        hosts by contract (render/base.py); keeping the operator's view
        host-independent is what makes an interaction-parity gap attributable
        to the interface rather than to the operator.
        """

    def invoke(self, node_id: str, value: object | None = None) -> None:
        """Activate a control, optionally supplying a value."""

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
        self._types = None

    def run(self, session: Session, goal: str, max_steps: int) -> int:
        if not self.api_key:
            raise RuntimeError(
                "no API key in environment; set it before running the operator"
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
            from google.genai import types

            self._client = genai.Client(api_key=self.api_key)
            self._types = types
        return self._client

    def _next_action(self, session: Session, goal: str, step: int) -> dict | None:
        """Ask the model for the next action given state + UI facts.

        Implemented against the provider's JSON-mode API. Kept as a single
        seam so the whole experiment can be re-run against a different operator
        by substituting this method.

        Transient provider errors are retried with backoff; exhaustion raises,
        because silently converting an API outage into {"op": "done"} would
        record a fabricated task termination instead of a measurement failure.
        """
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
            '1. To perform an action: {"op": "invoke", "id": "<node_id>",'
            ' "value": <optional_value>}\n'
            '2. If the goal is achieved: {"op": "done"}'
        )

        last_exc: Exception | None = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=(
                        self._types.GenerateContentConfig(
                            response_mime_type="application/json")
                        if self._types is not None else None
                    ),
                )
                return json.loads(response.text)
            except Exception as exc:  # noqa: BLE001 - provider SDK raises broadly
                last_exc = exc
        raise RuntimeError(
            f"operator API failed after retries: {last_exc}"
        ) from last_exc

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

    # Normalized action kinds derived from the Session contract (render/base.py), in
    # the order the scripted policy prefers them: fill inputs, set choices and
    # toggles, tap list rows, then press buttons.
    _POLICY_ORDER = ("input", "choice", "boolean", "item", "action")

    # Sessions legitimately report either the spec vocabulary ("field",
    # "select", "toggle", "button") or the canonical one ("input", ...):
    # simulated sessions project spec nodes, device-backed sessions lower
    # native controls. Normalize both so the policy sees one vocabulary.
    _KIND_ALIASES = {
        "field": "input",
        "select": "choice",
        "toggle": "boolean",
        "button": "action",
        "listitem": "item",
    }

    @classmethod
    def _canonical_kind(cls, action: dict) -> str:
        raw = str(action.get("kind", "")).lower()
        return cls._KIND_ALIASES.get(raw, raw)

    def run(self, session: Session, goal: str, max_steps: int) -> int:
        steps = 0
        used: set[str] = set()
        while steps < max_steps:
            pending = [
                a for a in session.actions()
                if a.get("enabled", True) and a.get("id") not in used
            ]
            if not pending:
                break

            plan = next(
                (
                    a for kind in self._POLICY_ORDER
                    for a in pending if self._canonical_kind(a) == kind
                ),
                None,
            )
            if plan is None:
                break

            kind = self._canonical_kind(plan)
            if kind == "input":
                session.invoke(plan["id"], self._fill_value(plan))
            elif kind in ("choice", "boolean"):
                options = plan.get("options") or []
                value = options[0] if options else not bool(plan.get("value"))
                session.invoke(plan["id"], value)
            else:
                session.invoke(plan["id"], None)

            used.add(plan["id"])
            steps += 1
        return steps

    @staticmethod
    def _fill_value(action: dict) -> str:
        """A deterministic placeholder derived from the control's name."""
        name = str(action.get("name") or "value").strip().lower()
        return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "value"


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
    current.valid, _ = validate(current)
    return current


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class Store:
    """Append-only run log and immutable artifacts keyed by experiment cell.

    Saving an identical artifact is idempotent; different payload or metadata
    for an existing cell raises FileExistsError. Use separate run stores for
    distinct trials until an explicit multi-trial storage API is available.
    """

    def __init__(self, root: str = "runs"):
        self.root = Path(root)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        self.runlog = self.root / "runs.jsonl"

    def save_artifact(self, a: Artifact) -> Path:
        p = self.root / "artifacts" / f"{a.key()}.json"
        data = asdict(a)
        serialized = json.dumps(data, indent=2)
        temporary = None
        try:
            # Write completely before publishing. A same-directory hard link
            # atomically creates the final name without replacing a winner.
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=p.parent,
                prefix=f".{p.stem}.", suffix=".tmp", delete=False,
            ) as fh:
                temporary = Path(fh.name)
                fh.write(serialized)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(temporary, p)
            except FileExistsError:
                try:
                    existing = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeError):
                    existing = None
                if existing != data:
                    raise FileExistsError(
                        f"Artifact cell already exists with different contents: {p}. "
                        "Use a separate Store for a distinct trial."
                    ) from None
        finally:
            if temporary is not None:
                temporary.unlink()
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

    def export_sqlite(self, db_path: str | Path | None = None) -> Path:
        """Export run log and stored artifacts to a queryable SQLite database.

        Creates tables for runs, run_failures, and artifacts, plus views for
        quick summary aggregation across conditions and hosts.
        """
        import sqlite3

        out_path = Path(db_path) if db_path else self.root / "benchmark.db"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            out_path.unlink()

        conn = sqlite3.connect(str(out_path))
        with conn:
            conn.execute("""
                CREATE TABLE runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    generator TEXT NOT NULL,
                    host TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    steps INTEGER NOT NULL,
                    criteria_met INTEGER NOT NULL,
                    criteria_total INTEGER NOT NULL,
                    probes_passed INTEGER NOT NULL,
                    probes_total INTEGER NOT NULL,
                    render_parity REAL,
                    a11y_parity REAL,
                    wall_ms INTEGER NOT NULL,
                    error TEXT,
                    ts INTEGER
                )
            """)
            conn.execute("CREATE INDEX idx_runs_cond_host ON runs(condition, host)")
            conn.execute("CREATE INDEX idx_runs_task ON runs(task_id)")
            conn.execute("CREATE INDEX idx_runs_success ON runs(success)")

            conn.execute("""
                CREATE TABLE run_failures (
                    run_id INTEGER NOT NULL,
                    failure TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
                )
            """)

            conn.execute("""
                CREATE TABLE artifacts (
                    key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    generator TEXT NOT NULL,
                    host TEXT,
                    valid INTEGER NOT NULL,
                    repair_rounds INTEGER NOT NULL,
                    gen_ms INTEGER NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    error TEXT,
                    payload_len INTEGER NOT NULL
                )
            """)
            conn.execute("CREATE INDEX idx_art_task ON artifacts(task_id)")
            conn.execute("CREATE INDEX idx_art_cond ON artifacts(condition)")

            conn.execute("""
                CREATE VIEW v_summary AS
                SELECT
                    condition,
                    host,
                    COUNT(*) AS total_runs,
                    SUM(success) AS successes,
                    ROUND(AVG(success) * 100.0, 2) AS success_pct,
                    ROUND(AVG(steps), 2) AS avg_steps,
                    ROUND(AVG(render_parity), 3) AS avg_render_parity,
                    ROUND(AVG(a11y_parity), 3) AS avg_a11y_parity,
                    ROUND(AVG(wall_ms), 1) AS avg_wall_ms
                FROM runs
                GROUP BY condition, host
            """)

            conn.execute("""
                CREATE VIEW v_failures AS
                SELECT
                    failure,
                    COUNT(*) AS count
                FROM run_failures
                GROUP BY failure
                ORDER BY count DESC
            """)

            # Populate runs
            if self.runlog.exists():
                for line in self.runlog.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    ts = d.get("ts")
                    failures = d.get("failures") or []
                    cur = conn.execute("""
                        INSERT INTO runs (
                            task_id, condition, generator, host, operator,
                            success, steps, criteria_met, criteria_total,
                            probes_passed, probes_total, render_parity, a11y_parity,
                            wall_ms, error, ts
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        d.get("task_id", ""),
                        d.get("condition", ""),
                        d.get("generator", ""),
                        d.get("host", ""),
                        d.get("operator", ""),
                        1 if d.get("success") else 0,
                        d.get("steps", 0),
                        d.get("criteria_met", 0),
                        d.get("criteria_total", 0),
                        d.get("probes_passed", 0),
                        d.get("probes_total", 0),
                        d.get("render_parity"),
                        d.get("a11y_parity"),
                        d.get("wall_ms", 0),
                        d.get("error"),
                        ts,
                    ))
                    run_id = cur.lastrowid
                    for f in failures:
                        conn.execute("INSERT INTO run_failures (run_id, failure) VALUES (?, ?)", (run_id, f))

            # Populate artifacts
            art_dir = self.root / "artifacts"
            if art_dir.exists():
                for f in art_dir.glob("*.json"):
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        payload = data.get("payload") or ""
                        key = f.stem
                        conn.execute("""
                            INSERT OR REPLACE INTO artifacts (
                                key, task_id, condition, generator, host,
                                valid, repair_rounds, gen_ms, prompt_tokens,
                                completion_tokens, error, payload_len
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            key,
                            data.get("task_id", ""),
                            data.get("condition", ""),
                            data.get("generator", ""),
                            data.get("host"),
                            1 if data.get("valid") else 0,
                            data.get("repair_rounds", 0),
                            data.get("gen_ms", 0),
                            data.get("prompt_tokens", 0),
                            data.get("completion_tokens", 0),
                            data.get("error"),
                            len(payload),
                        ))
                    except Exception:
                        continue

        conn.close()
        return out_path

    def query_sql(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a SQL SELECT query against an export of this store."""
        import sqlite3

        db_path = self.export_sqlite()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
