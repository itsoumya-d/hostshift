"""Renderer and semantics tests.

Two things are being protected here. First, that the reference interpreter is
right -- everything downstream is measured against it, so a bug in it silently
corrupts every host's score. Second, that the host profiles actually produce
*different* realizations: if every host lowered identically, host-lock would be
zero by construction and the benchmark would be measuring nothing.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.metrics import accessibility_parity, render_parity  # noqa: E402
from hostshift.render import (  # noqa: E402
    CAREFUL, COMPOSE, HOSTS, NAIVE, SWIFTUI, TUI, WEB,
    ReferenceSession, RenderError, assert_measurable, emit_all, get_renderer,
    intended_tree, open_session, realize, validate_spec,
)
from hostshift.render import semantics as sem  # noqa: E402
from hostshift.render.session import SimulatedSession  # noqa: E402
from hostshift.widgettree import from_spec  # noqa: E402

SPEC = json.loads(
    (pathlib.Path(__file__).resolve().parents[1]
     / "tasks" / "reference_specs" / "form-001.json").read_text()
)


# ------------------------------------------------------------- semantics

def test_reference_spec_validates():
    assert validate_spec(SPEC) == []


def test_initial_state_applies_declared_defaults():
    st = sem.initial_state(SPEC)
    assert st["name"] == "" and st["submitted"] is False
    assert st["collections"]["contacts"] == []
    assert st["route"] == "home"


def test_predicate_and_or_not():
    st = {"a": 1, "b": 0}
    assert sem.evaluate({"op": "and", "clauses": [
        {"op": "truthy", "left": "a"}, {"op": "falsy", "left": "b"}]}, st)
    assert sem.evaluate({"op": "or", "clauses": [
        {"op": "truthy", "left": "b"}, {"op": "truthy", "left": "a"}]}, st)
    assert not sem.evaluate({"op": "not", "clauses": [{"op": "truthy", "left": "a"}]}, st)


def test_ordering_against_missing_value_is_false_not_an_error():
    """Comparing an unfilled field is a normal state during data entry."""
    assert sem.evaluate({"op": "gt", "left": "nothing", "right": 3}, {}) is False


def test_actions_do_not_mutate_input_state():
    st = sem.initial_state(SPEC)
    before = json.dumps(st, sort_keys=True)
    sem.apply_action({"op": "set", "target": "name", "value": "x"}, st, SPEC)
    assert json.dumps(st, sort_keys=True) == before


def test_guarded_action_is_blocked():
    st = sem.initial_state(SPEC)
    out = sem.apply_action(
        {"op": "set", "target": "name", "value": "x",
         "guardWhen": {"op": "truthy", "left": "submitted"}}, st, SPEC)
    assert out["name"] == ""


def test_navigate_to_unknown_screen_raises():
    try:
        sem.apply_action({"op": "navigate", "target": "nowhere"},
                         sem.initial_state(SPEC), SPEC)
    except sem.SpecError:
        return
    raise AssertionError("expected SpecError")


def test_validate_spec_flags_unlabelled_control_and_bad_refs():
    bad = {
        "version": "0.2", "entry": "s", "state": {},
        "screens": [{"id": "s", "children": [
            {"kind": "button", "id": "b"},
            {"kind": "list", "id": "l", "of": "ghost"},
            {"kind": "field", "id": "f", "label": "F", "bind": "undeclared"},
        ]}],
    }
    problems = " | ".join(validate_spec(bad))
    assert "has no label" in problems
    assert "unknown collection" in problems
    assert "undeclared state" in problems


# --------------------------------------------------------------- session

def test_reference_session_drives_a_task_to_completion():
    """form-001, end to end, against the no-host control."""
    s = ReferenceSession(SPEC)
    assert s.state()["collections"]["contacts"] == []

    submit = next(a for a in s.actions() if a["id"] == "submit")
    assert submit["enabled"] is False, "submit must start disabled"

    s.invoke("name", "Dana Reyes")
    s.invoke("email", "dana@example.com")
    s.invoke("message", "Please call me back")

    submit = next(a for a in s.actions() if a["id"] == "submit")
    assert submit["enabled"] is True, "submit must enable once the form is valid"


def test_disabled_control_refuses_invocation():
    """A disabled control that still fires is a common lowering bug; the
    reference must not exhibit it, or hosts that do would look correct."""
    s = ReferenceSession(SPEC)
    s.invoke("submit")
    assert s.state()["collections"]["contacts"] == []


def test_error_banner_appears_only_for_a_malformed_email():
    s = ReferenceSession(SPEC)
    assert s.ui_facts()["error_visible"] is False
    s.invoke("email", "not-an-email")
    assert s.ui_facts()["error_visible"] is True
    s.invoke("email", "ok@example.com")
    assert s.ui_facts()["error_visible"] is False


def test_ui_facts_report_enablement_and_field_values():
    s = ReferenceSession(SPEC)
    s.invoke("name", "Dana")
    f = s.ui_facts()
    assert f["field_values"]["name"] == "Dana"
    assert f["enabled"]["submit"] is False


def test_session_rejects_a_structurally_broken_spec():
    try:
        ReferenceSession({"version": "0.2", "entry": "ghost", "screens": []})
    except RenderError:
        return
    raise AssertionError("expected RenderError")


# ------------------------------------------------------- host realization

def test_every_host_emits_sources():
    out = emit_all(SPEC)
    assert set(out) == set(HOSTS)
    for host, files in out.items():
        assert files, f"{host} emitted nothing"
        for path, src in files.items():
            assert len(src) > 400, f"{host}:{path} looks truncated"


def test_emitted_web_page_is_self_contained_and_embeds_the_spec():
    html = get_renderer("web").emit(SPEC)["index.html"]
    assert "__hostshift" in html, "instrumentation contract missing"
    assert '"entry":"home"' in html.replace(" ", "")
    assert "http://" not in html.split("<style>")[0], "must not fetch remote assets"


def test_emitted_sources_embed_the_spec_on_every_host():
    for host, files in emit_all(SPEC).items():
        blob = " ".join(files.values())
        assert "Contact us" in blob, f"{host} did not embed the spec"


def test_hosts_realize_the_same_spec_differently():
    """If every host lowered identically, host-lock would be zero by
    construction and the benchmark would measure nothing."""
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    trees = {p.host: realize(proj, p) for p in (WEB, SWIFTUI, COMPOSE, TUI)}
    kinds = {h: [n.kind for n in t.walk()] for h, t in trees.items()}
    assert kinds["web"] != kinds["tui"], "the terminal must lose something"


def test_terminal_cannot_realize_media():
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    web_kinds = [n.kind for n in realize(proj, WEB).walk()]
    tui_kinds = [n.kind for n in realize(proj, TUI).walk()]
    assert "media" in web_kinds
    assert "media" not in tui_kinds, "a terminal has no raster surface"


def _named_inputs(tree):
    return [n.name for n in tree.walk() if n.kind == "input"]


def test_compose_names_fields_only_when_the_renderer_does_the_work():
    """The defect the Android accessibility literature reports at scale: a
    field that is visually labelled and programmatically anonymous.

    Two axes decide the outcome. Compose does not associate a neighbouring
    label with a control, so a naive renderer leaves every input anonymous; a
    careful one passes `label=` and the names survive. Web needs neither,
    because the platform associates `<label for>` on its own. That contrast is
    the whole argument for separating renderer quality from host capability.
    """
    proj = sem.project(SPEC, sem.initial_state(SPEC))

    assert all(_named_inputs(realize(proj, WEB, NAIVE))), \
        "web associates <label for> unaided, so the naive arm loses nothing"
    assert all(_named_inputs(realize(proj, WEB, CAREFUL)))

    assert not any(_named_inputs(realize(proj, COMPOSE, NAIVE))), \
        "Compose needs an explicit label param; without it the fields are anonymous"
    assert all(_named_inputs(realize(proj, COMPOSE, CAREFUL))), \
        "a careful renderer passes label= and the names survive"


def test_no_renderer_can_rescue_a_host_with_no_accessibility_channel():
    """A terminal has nowhere to attach a name. Care cannot substitute for a
    missing channel, and pretending otherwise would hide a real host limit."""
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    assert not any(_named_inputs(realize(proj, TUI, NAIVE)))
    assert not any(_named_inputs(realize(proj, TUI, CAREFUL)))


def test_the_naive_renderer_drops_node_ids():
    """Identifier propagation is renderer work too. Without it the parity
    matcher falls back to positional matching."""
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    careful = [n.node_id for n in realize(proj, COMPOSE, CAREFUL).walk() if n.node_id]
    naive = [n.node_id for n in realize(proj, COMPOSE, NAIVE).walk() if n.node_id]
    assert careful and not naive


def test_accessibility_parity_separates_hosts_and_renderers():
    """Under a careful renderer only the terminal falls behind, because it is
    the only host with a hard limit. Under a naive one Compose falls behind
    too --- and that gap is renderer expertise, not platform capability."""
    intended = intended_tree(SPEC)
    proj = sem.project(SPEC, sem.initial_state(SPEC))

    careful = {p.host: accessibility_parity(intended, realize(proj, p, CAREFUL)).score
               for p in (WEB, SWIFTUI, COMPOSE, TUI)}
    naive = {p.host: accessibility_parity(intended, realize(proj, p, NAIVE)).score
             for p in (WEB, SWIFTUI, COMPOSE, TUI)}

    assert careful["web"] > careful["tui"], careful
    assert naive["compose"] < careful["compose"], (naive, careful)

    # Web is not immune to a naive renderer: an explicit a11yLabel and node-id
    # propagation are renderer work on every host. But the penalty is far
    # smaller, because the platform derives control names on its own. The size
    # of that difference is the effect the decomposition is there to measure.
    web_penalty = careful["web"] - naive["web"]
    compose_penalty = careful["compose"] - naive["compose"]
    assert compose_penalty > web_penalty * 2, (
        f"renderer care should matter far more on Compose "
        f"({compose_penalty:.3f}) than on web ({web_penalty:.3f})")


def test_render_parity_is_high_for_faithful_hosts_and_lower_for_the_terminal():
    intended = intended_tree(SPEC)
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    rp = {p.host: render_parity(intended, realize(proj, p, CAREFUL))
          for p in (WEB, SWIFTUI, COMPOSE, TUI)}
    assert rp["web"] > 0.99, rp
    # Only the terminal loses structure under a careful renderer: it cannot
    # realize media at all. The graphical hosts differ in naming, not shape.
    assert rp["tui"] < rp["web"], rp
    assert rp["compose"] > 0.99, rp


def test_hidden_nodes_do_not_count_against_a_host():
    """A host that correctly hides a conditional banner must not be penalised
    for the node's absence. This is why the reference is the projection rather
    than a static walk of the spec document."""
    static_ref = from_spec(SPEC)
    projected_ref = intended_tree(SPEC)
    assert static_ref.size() > projected_ref.size(), "fixture must have hidden nodes"
    proj = sem.project(SPEC, sem.initial_state(SPEC))
    web = realize(proj, WEB)
    assert render_parity(projected_ref, web) > render_parity(static_ref, web)


def test_terminal_does_not_report_enablement_so_probes_are_unobservable():
    """Reporting 'unobservable' rather than False keeps 'wrong' distinct from
    'could not be seen', which the failure taxonomy depends on."""
    s = open_session(SPEC, "tui", simulated=True)
    assert "enabled" not in s.ui_facts()
    assert "enabled" in open_session(SPEC, "web", simulated=True).ui_facts()


# ---------------------------------------------------------------- guards

def test_simulated_sessions_are_refused_for_results():
    s = open_session(SPEC, "compose", simulated=True)
    assert isinstance(s, SimulatedSession)
    try:
        assert_measurable(s)
    except RenderError as exc:
        assert "simulated" in str(exc)
        return
    raise AssertionError("a simulated session must not pass assert_measurable")


def test_override_allows_simulated_sessions_explicitly():
    assert_measurable(open_session(SPEC, "web", simulated=True), allow_simulated=True)


def test_unknown_host_raises():
    try:
        get_renderer("holograph")
    except RenderError:
        return
    raise AssertionError("expected RenderError")


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
