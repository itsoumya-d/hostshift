import sys
import os
import time
import json
from dataclasses import dataclass

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))

from hostshift.oracle import check, grade, CriterionResult
from hostshift.metrics import (
    render_parity, accessibility_parity, wilson_interval,
    host_lock_index, TaskOutcome, A11yReport
)
from hostshift.widgettree import Widget, tree_edit_distance
from hostshift.render import open_session, SpecError

def measure(fn, *args, **kwargs):
    start = time.perf_counter()
    try:
        res = fn(*args, **kwargs)
        err = None
    except Exception as e:
        res = None
        err = e
    duration = time.perf_counter() - start
    return res, err, duration

def run_test(name, fn):
    print(f"--- {name} ---")
    start = time.perf_counter()
    try:
        res = fn()
        duration = time.perf_counter() - start
        if res is True or res is None:
            print(f"PASS ({duration*1000:.2f}ms)")
        else:
            print(f"FAIL: {res} ({duration*1000:.2f}ms)")
    except Exception as e:
        duration = time.perf_counter() - start
        print(f"FAIL: exception {e} ({duration*1000:.2f}ms)")
    print()

def test_oracle_edge_cases():
    print("=== ORACLE EDGE CASES ===")
    
    def empty_state():
        c = {"kind": "state_equals", "path": "user.id", "value": 42}
        res = check(c, {})
        return res.passed == False
    run_test("Empty state -> should fail gracefully", empty_state)

    def extra_keys():
        c = {"kind": "state_equals", "path": "user.id", "value": 42}
        res = check(c, {"user": {"id": 42, "name": "bob"}, "other": 1})
        return res.passed == True
    run_test("State with extra keys -> should still match", extra_keys)

    def case_sensitivity():
        c = {"kind": "collection_contains", "collection": "users", "match": {"name": "ALICE"}}
        res = check(c, {"users": [{"name": "alice"}]})
        return res.passed == True
    run_test("Case sensitivity in collection_contains matching", case_sensitivity)

    def numeric_precision():
        c = {"kind": "state_equals", "path": "val", "value": 1.0}
        res1 = check(c, {"val": 0.99999})
        res2 = check(c, {"val": 0.999999999999})
        return res1.passed == False and res2.passed == True
    run_test("Numeric precision (0.99999 vs 1.0)", numeric_precision)

    def unicode_values():
        c = {"kind": "state_equals", "path": "val", "value": "✓"}
        res = check(c, {"val": "✓"})
        return res.passed == True
    run_test("Unicode values in state", unicode_values)

    def deeply_nested():
        c = {"kind": "state_equals", "path": "a.b.c.d.e", "value": 1}
        res = check(c, {"a": {"b": {"c": {"d": {"e": 1}}}}})
        return res.passed == True
    run_test("Deeply nested state paths (a.b.c.d.e)", deeply_nested)

    def missing_vs_empty_collection():
        c = {"kind": "collection_count", "collection": "users", "value": 0}
        res_missing = check(c, {})
        res_empty = check(c, {"users": []})
        return res_missing.passed == True and res_empty.passed == True
    run_test("Missing collection vs empty collection", missing_vs_empty_collection)

    def negative_criteria():
        t = {
            "id": "t1",
            "negative_criteria": [
                {"kind": "state_equals", "path": "error", "value": True}
            ]
        }
        res_fail = grade(t, {"error": True})
        res_pass = grade(t, {"error": False})
        return res_fail["success"] == False and res_pass["success"] == True
    run_test("Negative criteria behavior", negative_criteria)

    def zero_criteria():
        t = {"id": "t1", "criteria": []}
        res = grade(t, {})
        return res["success"] == False
    run_test("What happens with 0 criteria? (vacuous pass)", zero_criteria)

    def duplicate_criteria():
        t = {
            "id": "t1",
            "criteria": [
                {"kind": "state_equals", "path": "v", "value": 1},
                {"kind": "state_equals", "path": "v", "value": 1}
            ]
        }
        res = grade(t, {"v": 1})
        return res["success"] == True and res["criteria_met"] == 2 and res["criteria_total"] == 2
    run_test("What happens with duplicate criteria?", duplicate_criteria)

def test_metrics_edge_cases():
    print("=== METRICS EDGE CASES ===")

    def rp_empty():
        w1 = Widget("text")
        w2 = Widget("text")
        # Empty tree... well a widget tree needs at least 1 node usually, but let's see single node
        return render_parity(w1, w2) == 1.0
    run_test("render_parity with empty trees / single node", rp_empty)
    
    def rp_deep():
        def make_deep(n):
            root = Widget("container")
            cur = root
            for _ in range(n):
                child = Widget("container")
                cur.children.append(child)
                cur = child
            return root
        w1 = make_deep(100)
        w2 = make_deep(100)
        return render_parity(w1, w2) == 1.0
    run_test("render_parity with very deep trees (100 levels)", rp_deep)

    def rp_wide():
        w1 = Widget("container")
        w1.children = [Widget("text") for _ in range(100)]
        w2 = Widget("container")
        w2.children = [Widget("text") for _ in range(100)]
        return render_parity(w1, w2) == 1.0
    run_test("render_parity with very wide trees (100 children)", rp_wide)

    def ap_unnamed():
        w1 = Widget("container")
        w2 = Widget("container")
        w2.children = [Widget("boolean", focusable=True)] # unnamed boolean (button-like)
        res = accessibility_parity(w1, w2)
        return res.named == 0 and res.unnamed == 2
    run_test("accessibility_parity with all-unnamed nodes", ap_unnamed)

    def wilson_edges():
        try:
            edges = [
                wilson_interval(0, 0),
                wilson_interval(0, 1),
                wilson_interval(1, 1),
                wilson_interval(1000, 1000),
            ]
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("wilson_interval edge cases", wilson_edges)

    def hli_edges():
        o1 = TaskOutcome(task_id="1", host="web", success=True)
        h1 = host_lock_index([o1])
        o100 = [TaskOutcome(task_id=str(i), host="web", success=True) for i in range(100)]
        h100 = host_lock_index(o100)
        return h1 is not None and h100 is not None
    run_test("host_lock_index with 1 task, with 100 tasks", hli_edges)

    def ted_symm():
        w1 = Widget("container", children=[Widget("text")])
        w2 = Widget("container", children=[Widget("boolean")])
        return tree_edit_distance(w1, w2) == tree_edit_distance(w2, w1)
    run_test("tree_edit_distance symmetry", ted_symm)

    def ted_tri():
        w1 = Widget("container", children=[Widget("text")])
        w2 = Widget("container", children=[Widget("boolean")])
        w3 = Widget("container", children=[Widget("input")])
        d12 = tree_edit_distance(w1, w2)
        d23 = tree_edit_distance(w2, w3)
        d13 = tree_edit_distance(w1, w3)
        return d13 <= d12 + d23
    run_test("tree_edit_distance triangle inequality", ted_tri)

def test_rendering_edge_cases():
    print("=== RENDERING EDGE CASES ===")
    
    def no_screens():
        spec = {"version": "0.2", "screens": []}
        try:
            open_session(spec, "web", simulated=True)
            return "Should have failed on spec validation"
        except Exception as e:
            return True
    run_test("Spec with no screens", no_screens)

    def empty_screen():
        spec = {"version": "0.2", "screens": [{"id": "Main", "root": {"type": "container", "children": []}}], "entry": "Main"}
        sess = open_session(spec, "web", simulated=True)
        return True
    run_test("Spec with empty screen", empty_screen)

    def circular_nav():
        spec = {
            "version": "0.2",
            "screens": [
                {"id": "A", "root": {"type": "button", "label": "To B", "action": {"type": "navigate", "target": "B"}}},
                {"id": "B", "root": {"type": "button", "label": "To A", "action": {"type": "navigate", "target": "A"}}}
            ],
            "entry": "A"
        }
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Spec with circular navigation", circular_nav)

    def fifty_fields():
        fields = [{"type": "text_input", "field": f"f{i}"} for i in range(50)]
        spec = {"version": "0.2", "screens": [{"id": "Main", "root": {"type": "container", "children": fields}}], "entry": "Main"}
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Spec with 50 fields on one screen", fifty_fields)

    def nested_conditional():
        def make_nested(depth):
            if depth == 0:
                return {"type": "text", "text": "deep"}
            return {"type": "conditional", "condition": {"field": f"f{depth}", "equals": True}, "then": make_nested(depth-1)}
        spec = {"version": "0.2", "screens": [{"id": "Main", "root": make_nested(10)}], "entry": "Main"}
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Spec with deeply nested conditional visibility", nested_conditional)

    def nested_toggles():
        spec = {
            "version": "0.2",
            "screens": [
                {
                    "id": "Main",
                    "root": {
                        "type": "container",
                        "children": [
                            {"type": "checkbox", "field": "t1"},
                            {"type": "conditional", "condition": {"field": "t1", "equals": True}, "then": {"type": "checkbox", "field": "t2"}}
                        ]
                    }
                }
            ],
            "entry": "Main"
        }
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Toggle that enables/disables other toggles", nested_toggles)

    def button_chained_actions():
        actions = [{"type": "update_state", "field": f"f{i}", "value": True} for i in range(10)]
        spec = {
            "version": "0.2",
            "screens": [
                {
                    "id": "Main",
                    "root": {
                        "type": "button",
                        "label": "Click",
                        "action": {"type": "sequence", "actions": actions}
                    }
                }
            ],
            "entry": "Main"
        }
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Button with 10 chained actions", button_chained_actions)

    def large_collection():
        items = [{"id": str(i), "name": f"Item {i}"} for i in range(1000)]
        spec = {
            "version": "0.2",
            "state": {"items": {"type": "list", "default": items}},
            "screens": [
                {
                    "id": "Main",
                    "root": {
                        "type": "collection",
                        "collection": "items",
                        "template": {"type": "text", "text": "..."}
                    }
                }
            ],
            "entry": "Main"
        }
        try:
            sess = open_session(spec, "web", simulated=True)
            return True
        except Exception as e:
            return f"Failed: {e}"
    run_test("Collection with 1000 seed items", large_collection)

def test_performance():
    print("=== PERFORMANCE BENCHMARKS ===")
    
    def time_oracle_1000():
        t = {"id": "t1", "criteria": [{"kind": "state_equals", "path": "v", "value": 1}]}
        s = {"v": 1}
        start = time.perf_counter()
        for _ in range(1000):
            grade(t, s)
        return time.perf_counter() - start
    res = time_oracle_1000()
    print(f"Time 1000 oracle grade() calls: {res*1000:.2f}ms")

    def time_rp_1000():
        w1 = Widget("container", children=[Widget("text"), Widget("boolean")])
        w2 = Widget("container", children=[Widget("text"), Widget("boolean")])
        start = time.perf_counter()
        for _ in range(1000):
            render_parity(w1, w2)
        return time.perf_counter() - start
    res = time_rp_1000()
    print(f"Time 1000 render_parity() calls: {res*1000:.2f}ms")

    def time_rendering():
        spec = {"version": "0.2", "screens": [{"id": "Main", "root": {"type": "text", "text": "Hi"}}], "entry": "Main"}
        hosts = ["web", "swiftui", "compose", "tui"]
        start = time.perf_counter()
        for _ in range(100):
            for h in hosts:
                open_session(spec, h, simulated=True)
        return time.perf_counter() - start
    res = time_rendering()
    print(f"Time rendering a spec on all 4 hosts x 100: {res*1000:.2f}ms")

    def memory_footprint():
        import tracemalloc
        tracemalloc.start()
        items = [{"id": str(i)} for i in range(10000)]
        spec = {
            "version": "0.2",
            "state": {"items": {"type": "list", "default": items}},
            "screens": [{"id": "Main", "root": {"type": "collection", "collection": "items", "template": {"type": "text", "text": "a"}}}],
            "entry": "Main"
        }
        try:
            sess = open_session(spec, "web", simulated=True)
        except Exception:
            pass
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return f"Peak: {peak / 1024 / 1024:.2f} MB"
    res = memory_footprint()
    print(f"Memory footprint of a large session: {res}")


if __name__ == '__main__':
    os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"
    test_oracle_edge_cases()
    test_metrics_edge_cases()
    test_rendering_edge_cases()
    test_performance()
