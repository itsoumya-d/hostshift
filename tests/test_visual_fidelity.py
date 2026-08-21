import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from hostshift.visual_fidelity import (
    combined_visual_fidelity_score,
    cross_host_visual_consistency,
    information_density_score,
    layout_coherence_score,
)
from hostshift.widgettree import Widget


def test_lcs_no_duplicate_ids():
    tree = Widget(kind="container", children=[
        Widget(kind="text", node_id="id1"),
        Widget(kind="text", node_id="id2")
    ])
    assert layout_coherence_score(tree) == 1.0, "test_lcs_no_duplicate_ids failed"

def test_lcs_with_duplicate_ids():
    tree = Widget(kind="container", children=[
        Widget(kind="text", node_id="id1"),
        Widget(kind="text", node_id="id1")
    ])
    assert layout_coherence_score(tree) < 1.0, "test_lcs_with_duplicate_ids failed"

def test_lcs_reasonable_depth():
    tree = Widget(kind="container")
    curr = tree
    for _ in range(12):
        new_node = Widget(kind="container")
        curr.children.append(new_node)
        curr = new_node
    assert layout_coherence_score(tree) < 1.0, "test_lcs_reasonable_depth failed"

def test_lcs_orphaned_heading():
    tree = Widget(kind="container", children=[
        Widget(kind="input"),
        Widget(kind="text") # orphaned heading
    ])
    assert layout_coherence_score(tree) < 1.0, "test_lcs_orphaned_heading failed"

def test_lcs_button_after_input():
    tree = Widget(kind="container", children=[
        Widget(kind="input"),
        Widget(kind="action")
    ])
    assert layout_coherence_score(tree) == 1.0, "test_lcs_button_after_input failed"

def test_lcs_button_before_input():
    tree = Widget(kind="container", children=[
        Widget(kind="action"),
        Widget(kind="input")
    ])
    assert layout_coherence_score(tree) < 1.0, "test_lcs_button_before_input failed"

def test_ids_empty_tree():
    tree = Widget(kind="container", children=[])
    # Empty container still has 1 node
    assert information_density_score(tree) > 0.0, "test_ids_empty_tree failed"

def test_ids_good_ratio():
    tree = Widget(kind="container", children=[
        Widget(kind="text"),
        Widget(kind="input", name="Name"),
        Widget(kind="action", name="Submit")
    ])
    assert information_density_score(tree) == 1.0, "test_ids_good_ratio failed"

def test_ids_unlabelled_interactive():
    tree = Widget(kind="container", children=[
        Widget(kind="input") # unlabelled
    ])
    assert information_density_score(tree) < 1.0, "test_ids_unlabelled_interactive failed"

def test_ids_too_many_children():
    children = [Widget(kind="text") for _ in range(20)]
    tree = Widget(kind="container", children=children)
    assert information_density_score(tree) < 1.0, "test_ids_too_many_children failed"

def test_chc_single_tree():
    tree = Widget(kind="container")
    assert cross_host_visual_consistency([tree]) == 1.0, "test_chc_single_tree failed"

def test_chc_identical_trees():
    tree1 = Widget(kind="container", children=[Widget(kind="text")])
    tree2 = Widget(kind="container", children=[Widget(kind="text")])
    assert cross_host_visual_consistency([tree1, tree2]) == 1.0, "test_chc_identical_trees failed"

def test_chc_different_trees():
    tree1 = Widget(kind="container", children=[Widget(kind="text")])
    tree2 = Widget(kind="container", children=[Widget(kind="action")])
    assert cross_host_visual_consistency([tree1, tree2]) < 1.0, "test_chc_different_trees failed"

def test_combined_single():
    tree = Widget(kind="container", children=[
        Widget(kind="input", name="Val"),
        Widget(kind="action", name="Sub")
    ])
    assert combined_visual_fidelity_score(tree) == 1.0, "test_combined_single failed"

def test_combined_multiple():
    tree1 = Widget(kind="container", children=[Widget(kind="input", name="V"), Widget(kind="action", name="S")])
    tree2 = Widget(kind="container", children=[Widget(kind="input", name="V"), Widget(kind="action", name="S")])
    assert combined_visual_fidelity_score(tree1, [tree2]) == 1.0, "test_combined_multiple failed"

def test_combined_imperfect():
    tree1 = Widget(kind="container", children=[Widget(kind="action", name="S"), Widget(kind="input", name="V")])
    assert combined_visual_fidelity_score(tree1) < 1.0, "test_combined_imperfect failed"

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
