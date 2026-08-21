"""TED kernel performance study — Python baseline vs optional Mojo port.

Protocol (from research/MOJO.md):

1. Benchmark on realistic trees drawn from tasks/reference_specs plus seeded
   synthetic trees at several sizes; report medians.
2. The Python kernel in hostshift.widgettree stays the reference oracle; any
   Mojo result is cross-checked against it before being timed for the record.
3. The Mojo port (ted.mojo) communicates through a deliberately dumb file
   fixture: postorder kind codes + leftmost-leaf indices as integer CSV. No
   JSON parsing needed on the Mojo side (the 1.0 stdlib has none).

Usage:

    python3 benchmark.py                     # Python baseline + correctness checks
    python3 benchmark.py --emit fixtures/    # write fixture cases for the Mojo runner
    python3 benchmark.py --with-mojo ./ted_bench
                                             # verify + time a compiled Mojo runner

Exit code is nonzero if any correctness check fails. Timing numbers go to
stdout as a table; paste them into README.md when they change materially.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hostshift.widgettree import Widget, from_spec, tree_edit_distance  # noqa: E402

SIZES = (16, 64, 128, 256)
REPEATS = 15
SEED = 20260829


def load_reference_trees() -> list[Widget]:
    trees = []
    for path in sorted((ROOT / "tasks" / "reference_specs").glob("*.json")):
        try:
            spec = json.loads(path.read_text())
            trees.append(from_spec(spec))
        except (json.JSONDecodeError, ValueError):
            continue
    return trees


def synthetic_tree(rng: random.Random, n_nodes: int) -> Widget:
    """A random canonical-shaped tree with ~n_nodes nodes."""
    root = Widget(kind="container", name="screen")
    frontier: list[Widget] = [root]
    made = 1
    leaf_kinds = ("text", "input", "action", "boolean")
    while made < n_nodes:
        parent = rng.choice(frontier)
        if rng.random() < 0.25 and len(frontier) > 1:
            frontier.remove(parent)
            continue
        if rng.random() < 0.35 and made + 2 <= n_nodes:
            child = Widget(kind="container", name=f"stack{made}")
            grand = Widget(kind=rng.choice(leaf_kinds), name=f"leaf{made}")
            child.children.append(grand)
            made += 2
            parent.children.append(child)
            frontier.append(child)
        else:
            parent.children.append(
                Widget(kind=rng.choice(leaf_kinds), name=f"leaf{made}"))
            made += 1
    return root


def perturbed_copy(tree: Widget, rng: random.Random, edits: int) -> Widget:
    """A structural near-miss: substitute some leaf kinds, drop others --
    the shape of divergence a real host realization produces."""
    clone = _strip_names(tree)
    for _ in range(edits):
        candidates = [n for n in clone.walk() if n is not clone]
        if len(candidates) < 2:
            break
        node = rng.choice(candidates)
        if node.children:
            continue  # never turn an interior container into noise
        if rng.random() < 0.6:
            others = [k for k in LEAF_KINDS if k != node.kind]
            node.kind = rng.choice(others)
        else:
            parent = next(p for p in clone.walk() if node in p.children)
            parent.children.remove(node)
    return clone


LEAF_KINDS = ("text", "input", "action", "boolean", "choice")


def _clone(w: Widget) -> Widget:
    return Widget(kind=w.kind, name=w.name, node_id=w.node_id,
                  focusable=w.focusable,
                  children=[_clone(c) for c in w.children])


def _strip_names(w: Widget) -> Widget:
    """Structural clone: kinds and shape only.

    The study measures *structural* TED so the same quantity exists in both
    language ports (the file-fixture format carries no strings, and the Mojo
    1.0 stdlib has no JSON/string machinery worth depending on here). The
    production metric in hostshift.widgettree additionally charges 0.5 when an
    accessible name drifts while the kind survives -- that half-term is
    documented there and deliberately out of scope for this kernel study.
    """
    return Widget(kind=w.kind, name=None, node_id=None,
                  focusable=w.focusable,
                  children=[_strip_names(c) for c in w.children])


def median_ms(fn, repeats: int = REPEATS) -> float:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(times)


def check_correctness(pairs) -> None:
    """Invariants the reference kernel must hold before any timing counts."""
    for a, b in pairs[:20]:
        d_ab = tree_edit_distance(a, b)
        d_ba = tree_edit_distance(b, a)
        assert abs(d_ab - d_ba) < 1e-9, "TED must be symmetric"
        assert tree_edit_distance(a, a) == 0.0, "TED(a, a) must be zero"
        norm = 1.0 - d_ab / max(a.size(), b.size())
        assert 0.0 <= norm <= 1.0, "normalized parity escaped [0, 1]"


# ---------------------------------------------------------------------------
# Fixture emission for the Mojo runner (integer CSV, no JSON needed there)
# ---------------------------------------------------------------------------


def emit_fixtures(out_dir: pathlib.Path, pairs: list[tuple[Widget, Widget]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, (a, b) in enumerate(pairs):
        expected = tree_edit_distance(a, b)
        _write_tree_csv(out_dir / f"case_{i:03d}_a.csv", a)
        _write_tree_csv(out_dir / f"case_{i:03d}_b.csv", b)
        (out_dir / f"case_{i:03d}_expected.txt").write_text(f"{expected:.6f}\n")


def _write_tree_csv(path: pathlib.Path, tree: Widget) -> None:
    """Postorder rows: <kind_code> <leftmost_leaf_postorder_index>. One line each."""
    nodes, leftmost = _postorder(tree)
    lines = []
    for node, lm in zip(nodes, leftmost):
        lines.append(f"{KIND_CODE.index(node.kind)} {lm}")
    path.write_text("\n".join(lines) + "\n")


# Canonical-kind codes, in a fixed order shared with ted.mojo. Changing this
# order invalidates emitted fixtures; regenerate them after any change.
KIND_CODE = [
    "container", "text", "input", "choice", "boolean", "action",
    "collection", "item", "media", "separator", "tablist", "overlay",
    "status",
]


def _postorder(root: Widget) -> tuple[list[Widget], list[int]]:
    nodes: list[Widget] = []
    leftmost: list[int] = []

    def visit(node: Widget) -> int:
        first_lm = None
        for c in node.children:
            lm = visit(c)
            if first_lm is None:
                first_lm = lm
        idx = len(nodes)
        nodes.append(node)
        leftmost.append(first_lm if first_lm is not None else idx)
        return leftmost[idx]

    visit(root)
    return nodes, leftmost


# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ted-benchmark")
    ap.add_argument("--emit", type=pathlib.Path, default=None,
                    help="emit fixture cases for the Mojo runner into this dir")
    ap.add_argument("--with-mojo", dest="mojo_bin", default=None,
                    help="path to a compiled ted.mojo runner; verify then time it")
    args = ap.parse_args(argv)

    rng = random.Random(SEED)
    labeled: list[tuple[str, Widget, Widget]] = []

    def structural(a: Widget, b: Widget) -> tuple[Widget, Widget]:
        return _strip_names(a), _strip_names(b)

    # Synthetic scaling ladder: identical size, growing structural difference.
    for n in SIZES:
        a = synthetic_tree(rng, n)
        b = perturbed_copy(a, rng, edits=max(1, n // 10))
        labeled.append((f"synthetic-n{n}", *structural(a, b)))

    # Real artifacts: reference-spec trees against each other (worst-case
    # unrelated pair at UI scale).
    refs = load_reference_trees()
    if len(refs) >= 3:
        labeled.append(("ref-first-vs-last",
                        *structural(refs[0], refs[-1])))
        labeled.append(("ref-mid-vs-last",
                        *structural(refs[len(refs) // 2], refs[-1])))

    pairs = [(a, b) for _, a, b in labeled]

    print(f"correctness checks over {min(len(pairs), 20)} pairs ...")
    check_correctness(pairs)
    print("ok\n")

    print(f"{'pair':<28}{'|a|':>5}{'|b|':>5}{'TED':>9}{'median ms':>11}")
    print("-" * 58)
    for label, a, b in labeled:
        d = tree_edit_distance(a, b)
        ms = median_ms(lambda a=a, b=b: tree_edit_distance(a, b))
        print(f"{label:<28}{a.size():>5}{b.size():>5}{d:>9.1f}{ms:>11.2f}")

    if args.emit:
        emit_fixtures(args.emit, pairs)
        n_cases = len(pairs)
        print(f"\nwrote {n_cases} fixture cases to {args.emit}")

    if args.mojo_bin:
        if not pathlib.Path(args.mojo_bin).exists():
            print(f"\nmojo runner not found at {args.mojo_bin}; build it with:")
            print("  mojo build ted.mojo -o ted_bench")
            return 1
        print(f"\nverifying mojo runner against the python oracle ({len(pairs)} cases)...")
        ok = True
        for i in range(len(pairs)):
            fa = pathlib.Path(f"case_{i:03d}_a.csv")
            fb = pathlib.Path(f"case_{i:03d}_b.csv")
            fe = pathlib.Path(f"case_{i:03d}_expected.txt")
            if not (fa.exists() and fb.exists() and fe.exists()):
                emit_fixtures(pathlib.Path("."), pairs)
            got = subprocess.run(
                [args.mojo_bin, str(fa), str(fb)],
                capture_output=True, text=True, check=True).stdout.strip()
            want = float(fe.read_text().strip())
            if abs(float(got) - want) > 1e-4:
                print(f"  MISMATCH case {i}: mojo={got} python={want}")
                ok = False
        if not ok:
            return 1
        print("all cases agree")

    print("\nPython is the reference oracle; see README.md for the protocol.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
