"""Schema coverage classifier.

The classifier exists to quantify a bias, so its own biases matter. Two
directions are tested: it must not flag ordinary CRUD-shaped requests as out of
scope (which would overstate coverage of an external corpus), and it must still
catch the capabilities UISpec genuinely cannot express (which would understate
the limitation).

Both failure modes were present in the first version and are pinned here.
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.coverage import (  # noqa: E402
    IN_SCOPE,
    OUT_OF_SCOPE,
    VERDICTS,
    analyse,
    classify,
    format_report,
    load_corpus,
    suite_self_check,
)

SUITE = str(pathlib.Path(__file__).resolve().parents[1] / "tasks" / "suite_v1.jsonl")


# ------------------------------------------------------------- specificity

def test_ordinary_crud_requests_are_expressible():
    for prompt in [
        "A settings screen with three toggles and a language picker",
        "Support tickets list with a detail screen and a resolve button",
        "A contact form with name, email and a submit button",
        "A searchable table of employees with a department filter",
        "A two-step import flow where step one selects a format and step two confirms",
    ]:
        verdict, blocking, _ = classify(prompt)
        assert verdict == "expressible", f"{prompt!r} -> {verdict} {blocking}"


def test_a_billing_address_is_not_a_payment():
    """Regression. Matching the bare word 'billing' flagged an ordinary address
    form as a payment integration and understated coverage."""
    assert classify("A form with a billing address block")[0] == "expressible"
    assert "payments" in classify("Checkout that charges the card via Stripe")[1]


def test_an_evocative_noun_is_not_an_animation():
    """Regression. `\\bspring\\b` matched the caption 'Spring morning'."""
    assert classify("Set the photo caption to Spring morning")[1] == []
    assert "animation_motion" in classify("A spring animation on the sheet")[1]


def test_sorting_results_is_not_drag_reordering():
    """Regression. Matching 'reorder' flagged a sort control."""
    assert classify("A sort control that reorders the results by date")[1] == []
    assert "drag_reorder" in classify("Drag to reorder the playlist")[1]


def test_conjugated_verbs_still_match_in_scope_constructs():
    """Regression. Trailing word boundaries missed 'selects' and 'confirms',
    dropping a genuine request out of the denominator entirely."""
    for prompt in ("The user selects a format", "The user confirms the choice",
                   "Choosing an option", "Filtering the list"):
        assert classify(prompt)[0] != "not_an_app_request", prompt


# ------------------------------------------------------------- sensitivity

def test_genuinely_unsupported_capabilities_are_caught():
    cases = {
        "A kanban board where you drag cards between columns": "drag_reorder",
        "A photo editor with a drawing canvas": "canvas_drawing",
        "A dashboard with revenue charts": "data_visualisation",
        "A store locator with a map": "maps_geo",
        "Scan a QR code to check in": "camera_media_capture",
        "A rich text editor with a formatting toolbar": "rich_text_editing",
        "Real-time collaboration with live cursors": "realtime_collaboration",
        "Sign in with Google": "auth_provider",
        "An infinite scroll feed with pull to refresh": "custom_layout",
    }
    for prompt, expected in cases.items():
        assert expected in classify(prompt)[1], f"{prompt!r} missed {expected}"


def test_a_mixed_request_is_partial_not_binary():
    """A request whose core is expressible but which also asks for something
    unsupported must land in the middle, or coverage is misstated in whichever
    direction happens to be convenient."""
    verdict, blocking, matched = classify(
        "A list of stores with a detail screen and a map showing each location")
    assert verdict == "partial"
    assert "maps_geo" in blocking and matched


def test_non_requests_are_excluded_from_the_denominator():
    assert classify("the weather is nice today")[0] == "not_an_app_request"


# ------------------------------------------------------------ corpus rules

def _corpus(rows) -> str:
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for r in rows:
        fh.write(json.dumps(r) + "\n")
    fh.close()
    return fh.name


def test_corpus_requires_a_source_for_every_prompt():
    path = _corpus([{"id": "p1", "prompt": "A list of tasks"}])
    try:
        load_corpus(path)
    except ValueError as exc:
        assert "source" in str(exc)
        return
    raise AssertionError("a prompt without provenance must be rejected")


def test_corpus_refuses_prompts_authored_by_this_project():
    """A coverage study run against prompts written for the study proves
    nothing. Making that impossible by accident is worth the strictness."""
    path = _corpus([{"id": "p1", "prompt": "A list", "source": "hostshift-suite"}])
    try:
        load_corpus(path)
    except ValueError as exc:
        assert "externally authored" in str(exc)
        return
    raise AssertionError("self-authored corpora must be rejected")


def test_analyse_computes_coverage_over_app_requests_only():
    path = _corpus([
        {"id": "a", "prompt": "A settings screen with toggles", "source": "ext"},
        {"id": "b", "prompt": "A kanban board with drag and drop", "source": "ext"},
        {"id": "c", "prompt": "the weather is nice", "source": "ext"},
    ])
    summary = analyse(load_corpus(path))
    assert summary["n"] == 3
    assert summary["app_requests"] == 2, "non-requests must leave the denominator"
    assert summary["coverage_full"] == 0.5


def test_report_says_loudly_when_there_is_no_hand_audit():
    path = _corpus([{"id": "a", "prompt": "A list of tasks", "source": "ext"}])
    text = format_report(analyse(load_corpus(path)))
    assert "NO HAND AUDIT" in text


def test_report_shows_agreement_when_audited():
    path = _corpus([
        {"id": "a", "prompt": "A settings screen with toggles", "source": "ext",
         "hand_audited": "expressible"},
        {"id": "b", "prompt": "A map of stores", "source": "ext",
         "hand_audited": "expressible"},   # deliberately disagrees
    ])
    summary = analyse(load_corpus(path))
    assert summary["hand_audited"] == 2
    assert summary["classifier_agreement"] == 0.5


# ----------------------------------------------------------- self-check

def test_the_suite_is_fully_expressible_which_is_the_point():
    """Not a result -- a measurement of the bias.

    The suite was written against the schema, so near-total self-coverage is
    expected. Stating it as a number makes the home-ground advantage explicit
    and gives the external corpus something to be compared against.
    """
    r = suite_self_check(SUITE)
    assert r["n"] == 100
    assert r["self_coverage"] >= 0.98, r["flagged"]


def test_taxonomies_are_disjoint_and_non_empty():
    assert set(OUT_OF_SCOPE) & set(IN_SCOPE) == set()
    assert all(pats for pats in OUT_OF_SCOPE.values())
    assert all(pats for pats in IN_SCOPE.values())
    assert set(VERDICTS) == {"expressible", "partial", "out_of_scope",
                             "not_an_app_request"}


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
