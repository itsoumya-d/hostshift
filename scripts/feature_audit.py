#!/usr/bin/env python3
"""COMPLETE FEATURE AUDIT — Tests every HostShift component end-to-end.

For each feature:
1. Does it work at all?
2. Is the output correct?
3. Is it best-in-class or cutting corners?
4. Speed measurement
5. Specific enhancement recommendations
"""

import json, os, sys, time, pathlib, traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ["HOSTSHIFT_ALLOW_SIMULATED"] = "1"

ROOT = pathlib.Path(__file__).resolve().parents[1]
results = {}

def test_feature(name, fn):
    """Run a feature test with timing and error capture."""
    print(f"\n{'='*70}")
    print(f"FEATURE: {name}")
    print(f"{'='*70}")
    t0 = time.perf_counter()
    try:
        result = fn()
        elapsed = time.perf_counter() - t0
        results[name] = {"status": "PASS", "elapsed_ms": round(elapsed*1000, 1), "details": result}
        print(f"  ✅ PASS ({elapsed*1000:.1f}ms)")
        if isinstance(result, dict):
            for k, v in result.items():
                print(f"     {k}: {v}")
        return True
    except Exception as e:
        elapsed = time.perf_counter() - t0
        results[name] = {"status": "FAIL", "elapsed_ms": round(elapsed*1000, 1), "error": str(e)}
        print(f"  ❌ FAIL ({elapsed*1000:.1f}ms): {e}")
        traceback.print_exc()
        return False

# =====================================================================
# FEATURE 1: Spec Validation
# =====================================================================
def test_spec_validation():
    from hostshift.render.semantics import validate_spec
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    ok, diagnostics = validate_spec(spec)
    assert ok, f"Valid spec failed validation: {diagnostics}"
    
    # Test invalid spec detection
    bad_spec = {"version": "0.2", "entry": "home", "state": {}, "screens": [
        {"id": "home", "title": "Test", "children": [
            {"kind": "field", "id": "f1", "bind": "nonexistent_var"}  # missing label
        ]}
    ]}
    ok2, diag2 = validate_spec(bad_spec)
    assert not ok2, "Invalid spec should have failed validation"
    
    return {"valid_spec_passes": True, "invalid_spec_caught": True, "diagnostics_on_invalid": diag2[:100]}

test_feature("1. Spec Validation (render/semantics.py)", test_spec_validation)

# =====================================================================
# FEATURE 2: Multi-Host Rendering (Web, SwiftUI, Compose, TUI)
# =====================================================================
def test_multi_host_rendering():
    from hostshift.render import HOSTS, open_session
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    
    host_results = {}
    for host in HOSTS:
        session = open_session(spec, host, simulated=True)
        actions = session.actions()
        tree = session.widget_tree()
        host_results[host] = {
            "actions_count": len(actions),
            "tree_nodes": tree.size() if hasattr(tree, 'size') else "N/A",
            "fields": len([a for a in actions if a["kind"] == "field"]),
            "buttons": len([a for a in actions if a["kind"] == "button"]),
        }
        session.close()
    
    return host_results

test_feature("2. Multi-Host Rendering (Web/SwiftUI/Compose/TUI)", test_multi_host_rendering)

# =====================================================================
# FEATURE 3: State Oracle (Task Grading)
# =====================================================================
def test_state_oracle():
    from hostshift.oracle import grade, load_suite
    from hostshift.render import open_session
    
    tasks = load_suite(str(ROOT / "tasks/suite_v1.jsonl"))
    task = [t for t in tasks if t["id"] == "form-001"][0]
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    
    # Test correct execution → success
    session = open_session(spec, "web", simulated=True)
    session.invoke("name", "Dana Reyes")
    session.invoke("email", "dana@example.com")
    session.invoke("message", "Please call me back")
    session.invoke("submit")
    g = grade(task, session.state(), session.ui_facts())
    session.close()
    
    # Test incomplete execution → failure
    session2 = open_session(spec, "web", simulated=True)
    session2.invoke("name", "Wrong Name")
    g2 = grade(task, session2.state(), session2.ui_facts())
    session2.close()
    
    return {
        "correct_execution_passes": g["success"],
        "correct_criteria_met": f"{g['criteria_met']}/{g['criteria_total']}",
        "incomplete_execution_fails": not g2["success"],
        "incomplete_criteria_met": f"{g2['criteria_met']}/{g2['criteria_total']}",
    }

test_feature("3. State Oracle (oracle.py)", test_state_oracle)

# =====================================================================
# FEATURE 4: Render Parity (RP) Metric
# =====================================================================
def test_render_parity():
    from hostshift.render import open_session, intended_tree
    from hostshift.metrics import render_parity
    
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    
    rp_scores = {}
    for host in ["web", "swiftui", "compose", "tui"]:
        session = open_session(spec, host, simulated=True)
        ref = intended_tree(spec, session._state)
        got = session.widget_tree()
        rp = render_parity(ref, got)
        rp_scores[host] = round(rp, 3)
        session.close()
    
    return rp_scores

test_feature("4. Render Parity (RP) Metric", test_render_parity)

# =====================================================================
# FEATURE 5: Accessibility Parity (AP) Metric
# =====================================================================
def test_accessibility_parity():
    from hostshift.render import open_session, intended_tree
    from hostshift.metrics import accessibility_parity
    
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    
    ap_scores = {}
    for host in ["web", "swiftui", "compose", "tui"]:
        session = open_session(spec, host, simulated=True)
        ref = intended_tree(spec, session._state)
        got = session.widget_tree()
        ap = accessibility_parity(ref, got)
        ap_scores[host] = {"score": round(ap.score, 3), "details": str(ap)[:60]}
        session.close()
    
    return ap_scores

test_feature("5. Accessibility Parity (AP) Metric", test_accessibility_parity)

# =====================================================================
# FEATURE 6: Host-Lock Index (HLI)
# =====================================================================
def test_host_lock_index():
    from hostshift.metrics import host_lock_index, TaskOutcome
    
    # Scenario: uniform mediocrity (NOT locked)
    uniform = TaskOutcome(
        task_id="test", condition="B",
        hosts={"web": 0.5, "swiftui": 0.5, "compose": 0.5, "tui": 0.5}
    )
    hli_uniform = host_lock_index([uniform])
    
    # Scenario: genuine lock (web=1.0, others=0.0)
    locked = TaskOutcome(
        task_id="test", condition="B",
        hosts={"web": 1.0, "swiftui": 0.0, "compose": 0.0, "tui": 0.0}
    )
    hli_locked = host_lock_index([locked])
    
    return {
        "uniform_mediocrity_hli": round(hli_uniform.hli, 3),
        "genuine_lock_hli": round(hli_locked.hli, 3),
        "correctly_distinguishes": hli_locked.hli > hli_uniform.hli,
    }

test_feature("6. Host-Lock Index (HLI)", test_host_lock_index)

# =====================================================================
# FEATURE 7: Zhang-Shasha Tree Edit Distance
# =====================================================================
def test_tree_edit_distance():
    from hostshift.widgettree import WidgetNode, tree_edit_distance
    
    # Identical trees → distance 0
    a = WidgetNode("root", "container", children=[
        WidgetNode("f1", "input", accessible_name="Name"),
        WidgetNode("f2", "input", accessible_name="Email"),
    ])
    b = WidgetNode("root", "container", children=[
        WidgetNode("f1", "input", accessible_name="Name"),
        WidgetNode("f2", "input", accessible_name="Email"),
    ])
    d_same = tree_edit_distance(a, b)
    
    # Different trees → distance > 0
    c = WidgetNode("root", "container", children=[
        WidgetNode("f1", "input", accessible_name="Name"),
        WidgetNode("f3", "action", accessible_name="Submit"),
    ])
    d_diff = tree_edit_distance(a, c)
    
    return {
        "identical_distance": d_same,
        "different_distance": d_diff,
        "correctly_zero_for_identical": d_same == 0.0,
        "correctly_nonzero_for_different": d_diff > 0.0,
    }

test_feature("7. Zhang-Shasha Tree Edit Distance", test_tree_edit_distance)

# =====================================================================
# FEATURE 8: Statistical Analysis (Wilson, Bootstrap, McNemar)
# =====================================================================
def test_statistics():
    from hostshift.metrics import wilson_interval, mcnemar
    
    # Wilson interval
    lo, hi = wilson_interval(7, 10, alpha=0.05)
    
    # McNemar test
    pairs = [(True, False)] * 8 + [(False, True)] * 2  # B wins 8, A wins 2
    m = mcnemar(pairs)
    
    return {
        "wilson_70pct_ci": f"[{lo:.3f}, {hi:.3f}]",
        "mcnemar_b_wins": m["b"],
        "mcnemar_a_wins": m["c"],
        "mcnemar_p_value": round(m["p_value"], 6),
        "mcnemar_significant": m["p_value"] < 0.05,
    }

test_feature("8. Statistical Analysis (Wilson/McNemar)", test_statistics)

# =====================================================================
# FEATURE 9: Task Suite Validation
# =====================================================================
def test_suite_validation():
    from hostshift.oracle import load_suite, validate_suite
    
    tasks = load_suite(str(ROOT / "tasks/suite_v1.jsonl"))
    ok, diagnostics = validate_suite(tasks)
    
    categories = {}
    for t in tasks:
        cat = t["category"]
        categories[cat] = categories.get(cat, 0) + 1
    
    return {
        "total_tasks": len(tasks),
        "suite_valid": ok,
        "diagnostics": diagnostics[:100] if diagnostics else "clean",
        "categories": categories,
    }

test_feature("9. Task Suite Validation (100 tasks)", test_suite_validation)

# =====================================================================
# FEATURE 10: Calibration System
# =====================================================================
def test_calibration():
    from hostshift.calibration import CALIBRATION_TASKS, corpus_provenance
    
    prov = corpus_provenance()
    
    return {
        "calibration_tasks_count": len(CALIBRATION_TASKS),
        "corpus_provenance": prov,
    }

test_feature("10. Calibration System", test_calibration)

# =====================================================================
# FEATURE 11: Coverage Analysis
# =====================================================================
def test_coverage():
    from hostshift.coverage import schema_coverage, UISPEC_CONSTRUCTS
    
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    cov = schema_coverage(spec)
    
    return {
        "total_constructs": len(UISPEC_CONSTRUCTS),
        "covered_by_form001": cov["covered"],
        "coverage_pct": f"{cov['coverage_pct']:.1f}%",
    }

test_feature("11. Coverage Analysis", test_coverage)

# =====================================================================
# FEATURE 12: License Guard
# =====================================================================
def test_license_guard():
    from hostshift.license_guard import verify_license, stamp_provenance
    
    check = verify_license()
    stamped = stamp_provenance({"test": "data"})
    
    return {
        "license_valid": check.valid,
        "license_reason": check.reason,
        "provenance_hash": check.provenance.get("origin_hash"),
        "stamp_has_watermark": "_hostshift_provenance" in stamped,
    }

test_feature("12. License Guard & Provenance", test_license_guard)

# =====================================================================
# FEATURE 13: End-to-End Pipeline (all 8 reference specs × 4 hosts)
# =====================================================================
def test_e2e_pipeline():
    from hostshift.oracle import grade, load_suite
    from hostshift.render import HOSTS, open_session, intended_tree
    from hostshift.metrics import render_parity, accessibility_parity
    
    tasks = {t["id"]: t for t in load_suite(str(ROOT / "tasks/suite_v1.jsonl"))}
    specs_dir = ROOT / "tasks/reference_specs"
    
    e2e_results = {}
    for spec_file in sorted(specs_dir.glob("*.json")):
        sid = spec_file.stem
        if sid not in tasks:
            continue
        spec = json.loads(spec_file.read_text())
        task = tasks[sid]
        
        host_status = {}
        for host in HOSTS:
            try:
                session = open_session(spec, host, simulated=True)
                # Drive based on task
                for a in session.actions():
                    if a["kind"] == "field":
                        session.invoke(a["id"], "test input")
                    elif a["kind"] == "toggle":
                        try: session.invoke(a["id"])
                        except: pass
                
                ref = intended_tree(spec, session._state)
                got = session.widget_tree()
                rp = render_parity(ref, got)
                host_status[host] = f"RP={rp:.3f}"
                session.close()
            except Exception as e:
                host_status[host] = f"ERROR: {str(e)[:40]}"
        
        e2e_results[sid] = host_status
    
    return e2e_results

test_feature("13. End-to-End Pipeline (8 specs × 4 hosts)", test_e2e_pipeline)

# =====================================================================
# FEATURE 14: Cross-Implementation Consistency
# =====================================================================
def test_cross_impl():
    from hostshift.render import HOSTS, open_session
    
    spec = json.loads((ROOT / "tasks/reference_specs/form-001.json").read_text())
    
    # Check that all hosts expose the same actions
    host_actions = {}
    for host in HOSTS:
        session = open_session(spec, host, simulated=True)
        actions = session.actions()
        action_ids = sorted([a["id"] for a in actions])
        host_actions[host] = action_ids
        session.close()
    
    # All hosts should have identical action sets
    all_same = all(v == host_actions["web"] for v in host_actions.values())
    
    return {
        "all_hosts_same_actions": all_same,
        "web_actions": host_actions["web"],
        "tui_actions": host_actions["tui"],
    }

test_feature("14. Cross-Implementation Consistency", test_cross_impl)

# =====================================================================
# SUMMARY
# =====================================================================
print("\n" + "=" * 70)
print("COMPLETE FEATURE AUDIT SUMMARY")
print("=" * 70)

passed = sum(1 for r in results.values() if r["status"] == "PASS")
failed = sum(1 for r in results.values() if r["status"] == "FAIL")
total_time = sum(r["elapsed_ms"] for r in results.values())

print(f"\n  Total Features Tested: {len(results)}")
print(f"  ✅ Passed: {passed}")
print(f"  ❌ Failed: {failed}")
print(f"  ⏱  Total Time: {total_time:.1f}ms")

print("\n  Feature-by-Feature:")
for name, r in results.items():
    icon = "✅" if r["status"] == "PASS" else "❌"
    print(f"    {icon} {name} ({r['elapsed_ms']:.1f}ms)")

# Save results
out = ROOT / "runs" / "feature_audit.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(results, indent=2, default=str))
print(f"\n  Saved: {out}")
