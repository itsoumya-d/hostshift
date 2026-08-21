from __future__ import annotations

from .widgettree import Widget, normalized_ted


def layout_coherence_score(tree: Widget) -> float:
    """Measures whether the widget tree has a logical layout."""
    score_components = []

    # 1. No duplicate IDs
    ids = [n.node_id for n in tree.walk() if n.node_id]
    dup_ratio = 1.0 - (len(set(ids)) / len(ids)) if ids else 0.0
    score_components.append(1.0 - dup_ratio)

    # 2. Reasonable depth
    def max_depth(node: Widget) -> int:
        if not node.children:
            return 1
        return 1 + max((max_depth(c) for c in node.children), default=0)

    depth = max_depth(tree)
    # Reasonable depth (not > 10 levels)
    depth_score = 1.0 if depth <= 10 else max(0.0, 1.0 - (depth - 10) * 0.1)
    score_components.append(depth_score)

    # 3. Heading before content (not orphaned headings at bottom)
    orphans = 0
    containers = 0
    for n in tree.walk():
        if n.kind == "container" and n.children:
            containers += 1
            # A text node at the very end after interactive elements might be an orphaned heading
            if n.children[-1].kind == "text" and any(
                c.kind in ("input", "choice", "boolean", "action") for c in n.children[:-1]
            ):
                orphans += 1
    orphan_score = 1.0 if containers == 0 else 1.0 - (orphans / containers)
    score_components.append(orphan_score)

    # 4. Submit/action buttons after their associated fields
    bad_actions = 0
    action_containers = 0
    for n in tree.walk():
        kids = [c.kind for c in n.children]
        if "action" in kids and any(k in ("input", "choice", "boolean") for k in kids):
            action_containers += 1
            first_action = kids.index("action")
            last_input = max(
                [i for i, k in enumerate(kids) if k in ("input", "choice", "boolean")] + [-1])
            if first_action < last_input:
                bad_actions += 1
    action_order_score = 1.0 if action_containers == 0 else 1.0 - (bad_actions / action_containers)
    score_components.append(action_order_score)

    return sum(score_components) / len(score_components) if score_components else 1.0

def information_density_score(tree: Widget) -> float:
    """Measures whether the UI is neither too sparse nor too cluttered."""
    nodes = list(tree.walk())
    if not nodes:
        return 0.0

    # Ratio of interactive elements to total elements
    interactive = sum(
        1 for n in nodes
        if n.focusable or n.kind in ("action", "input", "choice", "boolean", "item"))
    ratio = interactive / len(nodes)
    if 0.1 <= ratio <= 0.8:
        interact_score = 1.0
    else:
        interact_score = max(0.0, 1.0 - abs(ratio - 0.5))

    # Ratio of labelled elements to total interactive elements
    labelled_interactive = sum(
        1 for n in nodes
        if (n.focusable or n.kind in ("action", "input", "choice", "boolean", "item"))
        and n.name)
    labelled_ratio = labelled_interactive / interactive if interactive > 0 else 1.0

    # Reasonable number of children per container (2-15 ideal)
    containers = [n for n in nodes if n.kind == "container"]
    bad_children_counts = 0
    for c in containers:
        if not (2 <= len(c.children) <= 15) and len(c.children) > 0:
            bad_children_counts += 1
    child_score = 1.0 - (bad_children_counts / len(containers)) if containers else 1.0

    return (interact_score + labelled_ratio + child_score) / 3.0

def cross_host_visual_consistency(trees: list[Widget]) -> float:
    """Given widget trees from multiple hosts, measures how consistent the visual structure is."""
    if not trees or len(trees) <= 1:
        return 1.0

    scores = []
    base_tree = trees[0]
    for t in trees[1:]:
        ted = normalized_ted(base_tree, t)
        scores.append(1.0 - ted)

    return sum(scores) / len(scores)

def combined_visual_fidelity_score(tree: Widget, other_trees: list[Widget] = None) -> float:
    """Weighted average of Layout Coherence, Information Density, and Cross-Host Consistency."""
    lcs = layout_coherence_score(tree)
    ids = information_density_score(tree)

    if other_trees and len(other_trees) > 0:
        chc = cross_host_visual_consistency([tree] + other_trees)
        return (lcs * 0.4) + (ids * 0.4) + (chc * 0.2)
    else:
        # If no other trees, just average the two
        return (lcs * 0.5) + (ids * 0.5)
