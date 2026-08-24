"""The measurement-integrity guards.

These exist so that simulated sessions can never quietly produce paper
numbers and so renderer/host profile mismatches fail loudly. They are the
harness's honesty rails; they get their own tests.

Every test here manages HOSTSHIFT_ALLOW_SIMULATED explicitly (snapshot,
unset, restore). Other suites legitimately set it at import time to exercise
simulated sessions; these tests must stay correct regardless of who else has
touched the environment -- a guard that depends on execution order is not a
guard.
"""

import contextlib
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.render import (
    ReferenceSession,
    SimulatedComposeSession,
    get_renderer,
    open_session,
)
from hostshift.render.base import RenderError
from hostshift.render.session import assert_measurable

SPEC = {
    "version": "0.2", "title": "t", "entry": "main",
    "state": {"x": {"type": "string", "default": ""}},
    "collections": {},
    "screens": [{"id": "main", "title": "T", "children": [
        {"kind": "field", "id": "f", "label": "F", "bind": "x"},
    ]}],
}


def _spec():
    return json.loads(json.dumps(SPEC))


@contextlib.contextmanager
def _no_simulated_flag():
    """Run with HOSTSHIFT_ALLOW_SIMULATED unset, restoring whatever was there."""
    saved = os.environ.pop("HOSTSHIFT_ALLOW_SIMULATED", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = saved


def test_assert_measurable_rejects_simulated_by_default():
    with _no_simulated_flag():
        s = SimulatedComposeSession(_spec())
        try:
            assert_measurable(s)
            raised = False
        except RenderError:
            raised = True
        finally:
            s.close()
        assert raised


def test_assert_measurable_allows_simulated_with_env():
    os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"
    try:
        s = SimulatedComposeSession(_spec())
        try:
            assert_measurable(s)  # must not raise
        finally:
            s.close()
    finally:
        os.environ.pop("HOSTSHIFT_ALLOW_SIMULATED", None)


def test_assert_measurable_rejects_reference_session_too():
    # ReferenceSession is the no-host control: useful for separating a wrong
    # spec from a mangled one, but it is not a host rendering, so it must not
    # produce paper numbers either.
    with _no_simulated_flag():
        s = ReferenceSession(_spec())
        try:
            assert_measurable(s)
            raised = False
        except RenderError:
            raised = True
        finally:
            s.close()
        assert raised


def test_get_renderer_unknown_host_raises():
    try:
        get_renderer("dos")
        raised = False
    except (KeyError, ValueError, RenderError):
        raised = True
    assert raised


def test_open_session_refuses_naive_renderer_on_device_host():
    # The naive renderer exists to model platform defaults; running it against
    # a real device session would conflate renderer negligence with host
    # capability, so the facade refuses the combination -- before any launch
    # attempt, and regardless of whether Playwright is installed.
    with _no_simulated_flag():
        try:
            open_session(_spec(), "web", renderer="naive", simulated=False)
            raised = False
        except RenderError:
            raised = True
        assert raised, "naive-on-device must be refused by the facade itself"


def test_naive_refusal_names_the_reason():
    # The refusal is about the renderer arm, not a missing dependency: the
    # message must say so, or users debug Playwright instead of their flags.
    with _no_simulated_flag():
        try:
            open_session(_spec(), "web", renderer="naive", simulated=False)
            message = ""
        except RenderError as exc:
            message = str(exc)
        assert "naive" in message


def test_reference_session_is_marked_simulated():
    s = ReferenceSession(_spec())
    try:
        assert s.simulated is True
    finally:
        s.close()


if __name__ == "__main__":
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = skipped = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except unittest.SkipTest as exc:
            skipped += 1
            print(f"  SKIP  {fn.__name__}  ({exc})")
        except Exception:
            failed += 1
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
    ran = len(fns) - failed - skipped
    print(f"\n{ran}/{len(fns)} passed, {skipped} skipped")
    sys.exit(1 if failed else 0)
