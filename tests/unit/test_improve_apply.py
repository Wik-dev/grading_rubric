"""Unit tests for improve stage apply functions: leaf-to-branch promotion,
REMOVE_NODE, and conflict resolution.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from grading_rubric.improve.models import ProposedChangeDraft
from grading_rubric.improve.stage import (
    _add_node_to_rubric,
    _remove_node_from_rubric,
    _step1_conflict_resolution,
    _step3_apply_and_wrap,
)
from grading_rubric.models.findings import ConfidenceIndicator, ConfidenceLevel, QualityCriterion
from grading_rubric.models.rubric import Rubric, RubricCriterion

# ── Deterministic UUIDs ─────────────────────────────────────────────────────

RUBRIC_ID = UUID("aaaaaaaa-0000-0000-0000-000000000099")
ROOT_ID = UUID("cccccccc-0000-0000-0000-000000000010")
LEAF_ID = UUID("cccccccc-0000-0000-0000-000000000020")
SIBLING_ID = UUID("cccccccc-0000-0000-0000-000000000030")
FINDING_ID = UUID("ffffffff-0000-0000-0000-000000000099")


def _confidence() -> ConfidenceIndicator:
    return ConfidenceIndicator(
        score=0.8, level=ConfidenceLevel.HIGH, rationale="test"
    )


def _make_rubric_with_leaf() -> Rubric:
    """A rubric with one root criterion containing a 1.5-point leaf."""
    return Rubric(
        id=RUBRIC_ID,
        schema_version="1.0.0",
        title="Test",
        total_points=1.5,
        criteria=[
            RubricCriterion(
                id=ROOT_ID,
                name="Root",
                description="Root criterion",
                points=1.5,
                sub_criteria=[
                    RubricCriterion(
                        id=LEAF_ID,
                        name="Leaf to split",
                        description="A leaf criterion",
                        points=1.5,
                    ),
                ],
            ),
        ],
    )


def _make_rubric_two_children() -> Rubric:
    """A rubric with one root that has two leaf children."""
    return Rubric(
        id=RUBRIC_ID,
        schema_version="1.0.0",
        title="Test",
        total_points=3.0,
        criteria=[
            RubricCriterion(
                id=ROOT_ID,
                name="Root",
                description="Root criterion",
                points=3.0,
                sub_criteria=[
                    RubricCriterion(
                        id=LEAF_ID,
                        name="Leaf A",
                        description="First leaf",
                        points=1.5,
                    ),
                    RubricCriterion(
                        id=SIBLING_ID,
                        name="Leaf B",
                        description="Second leaf",
                        points=1.5,
                    ),
                ],
            ),
        ],
    )


def _draft(
    operation: str,
    payload: dict,
    *,
    primary_criterion: QualityCriterion = QualityCriterion.DISCRIMINATION_POWER,
) -> ProposedChangeDraft:
    return ProposedChangeDraft(
        operation=operation,
        payload=payload,
        primary_criterion=primary_criterion,
        source_findings=[FINDING_ID],
        rationale="test",
        confidence=_confidence(),
    )


# ── Leaf-to-branch promotion ────────────────────────────────────────────────


class TestLeafToBranchPromotion:
    """ADD_NODE targeting a leaf criterion promotes it to a branch.

    The leaf's points should remain unchanged (sum of new children = original).
    """

    def test_split_leaf_preserves_total_points(self) -> None:
        rubric = _make_rubric_with_leaf()
        original_total = rubric.total_points

        # Three ADD_NODEs targeting the LEAF (not ROOT). The leaf becomes
        # a branch with three 0.5-point children.
        drafts = [
            _draft("ADD_NODE", {
                "parent_path": [str(ROOT_ID), str(LEAF_ID)],
                "insert_index": i,
                "node_kind": "criterion",
                "node": {
                    "name": f"Sub-check {i}",
                    "description": f"Observable dimension {i}",
                    "points": 0.5,
                },
            })
            for i in range(3)
        ]

        current = deepcopy(rubric)
        for d in drafts:
            current, applied = _add_node_to_rubric(current, d)
            assert applied

        # Leaf is now a branch with 3 children.
        root = current.criteria[0]
        leaf_now_branch = root.sub_criteria[0]
        assert len(leaf_now_branch.sub_criteria) == 3
        assert leaf_now_branch.points == pytest.approx(1.5)
        assert root.points == pytest.approx(1.5)
        assert current.total_points == pytest.approx(original_total)

    def test_split_leaf_children_are_correct(self) -> None:
        rubric = _make_rubric_with_leaf()

        drafts = [
            _draft("ADD_NODE", {
                "parent_path": [str(ROOT_ID), str(LEAF_ID)],
                "insert_index": i,
                "node_kind": "criterion",
                "node": {
                    "name": f"Sub-check {i}",
                    "description": f"Observable dimension {i}",
                    "points": 0.5,
                },
            })
            for i in range(3)
        ]

        current = deepcopy(rubric)
        for d in drafts:
            current, _ = _add_node_to_rubric(current, d)

        leaf_now_branch = current.criteria[0].sub_criteria[0]
        child_names = [c.name for c in leaf_now_branch.sub_criteria]
        assert child_names == ["Sub-check 0", "Sub-check 1", "Sub-check 2"]

    def test_split_leaf_round_trip_validates(self) -> None:
        """The rubric after splitting must pass Rubric.model_validate."""
        rubric = _make_rubric_with_leaf()

        drafts = [
            _draft("ADD_NODE", {
                "parent_path": [str(ROOT_ID), str(LEAF_ID)],
                "insert_index": i,
                "node_kind": "criterion",
                "node": {
                    "name": f"Sub-check {i}",
                    "description": f"Observable dimension {i}",
                    "points": 0.5,
                },
            })
            for i in range(3)
        ]

        current = deepcopy(rubric)
        for d in drafts:
            current, _ = _add_node_to_rubric(current, d)

        # Round-trip through JSON to verify Rubric model_validate passes.
        validated = Rubric.model_validate_json(current.model_dump_json())
        assert validated.total_points == pytest.approx(1.5)
        assert len(validated.criteria[0].sub_criteria[0].sub_criteria) == 3


# ── REMOVE_NODE ──────────────────────────────────────────────────────────────


class TestRemoveNode:

    def test_remove_leaf_adjusts_parent_and_total(self) -> None:
        rubric = _make_rubric_two_children()
        draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
            "node_kind": "criterion",
        })

        new_rubric, snapshot, applied = _remove_node_from_rubric(rubric, draft)

        assert applied
        assert snapshot is not None
        assert snapshot.name == "Leaf A"
        # Parent should now have only one child.
        assert len(new_rubric.criteria[0].sub_criteria) == 1
        assert new_rubric.criteria[0].sub_criteria[0].id == SIBLING_ID
        # Parent points = remaining child.
        assert new_rubric.criteria[0].points == pytest.approx(1.5)
        assert new_rubric.total_points == pytest.approx(1.5)

    def test_remove_nonexistent_criterion_is_noop(self) -> None:
        rubric = _make_rubric_two_children()
        fake_id = str(uuid4())
        draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID), fake_id],
            "node_kind": "criterion",
        })

        new_rubric, snapshot, applied = _remove_node_from_rubric(rubric, draft)

        assert not applied
        assert snapshot is None
        assert len(new_rubric.criteria[0].sub_criteria) == 2

    def test_remove_root_criterion(self) -> None:
        """Removing a root-level criterion adjusts total_points."""
        rubric = Rubric(
            id=RUBRIC_ID,
            schema_version="1.0.0",
            title="Test",
            total_points=5.0,
            criteria=[
                RubricCriterion(id=ROOT_ID, name="A", description="A", points=3.0),
                RubricCriterion(id=SIBLING_ID, name="B", description="B", points=2.0),
            ],
        )
        draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID)],
            "node_kind": "criterion",
        })

        new_rubric, snapshot, applied = _remove_node_from_rubric(rubric, draft)

        assert applied
        assert snapshot.name == "A"
        assert len(new_rubric.criteria) == 1
        assert new_rubric.total_points == pytest.approx(2.0)


# ── Conflict resolution ──────────────────────────────────────────────────────


class TestConflictResolution:

    def test_remove_supersedes_replace_on_same_target(self) -> None:
        replace_draft = _draft(
            "REPLACE_FIELD",
            {
                "target": {
                    "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
                    "field": "description",
                },
                "before": "old",
                "after": "new",
            },
            primary_criterion=QualityCriterion.AMBIGUITY,
        )
        remove_draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
            "node_kind": "criterion",
        })

        drafts = [replace_draft, remove_draft]
        _, superseded = _step1_conflict_resolution(drafts)

        assert 0 in superseded  # REPLACE_FIELD superseded
        assert 1 not in superseded  # REMOVE_NODE kept

    def test_remove_supersedes_add_on_descendant(self) -> None:
        child_id = str(uuid4())
        add_draft = _draft("ADD_NODE", {
            "parent_path": [str(ROOT_ID), str(LEAF_ID)],
            "insert_index": 0,
            "node_kind": "criterion",
            "node": {"name": "X", "description": "X", "points": 0.5},
        })
        remove_draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
            "node_kind": "criterion",
        })

        drafts = [add_draft, remove_draft]
        _, superseded = _step1_conflict_resolution(drafts)

        assert 0 in superseded

    def test_no_remove_means_no_supersession(self) -> None:
        replace_draft = _draft(
            "REPLACE_FIELD",
            {
                "target": {
                    "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
                    "field": "description",
                },
                "before": "old",
                "after": "new",
            },
            primary_criterion=QualityCriterion.AMBIGUITY,
        )
        add_draft = _draft("ADD_NODE", {
            "parent_path": [str(ROOT_ID), str(LEAF_ID)],
            "insert_index": 0,
            "node_kind": "criterion",
            "node": {"name": "X", "description": "X", "points": 0.5},
        })

        drafts = [replace_draft, add_draft]
        _, superseded = _step1_conflict_resolution(drafts)

        assert superseded == set()


# ── Full pipeline round-trip ─────────────────────────────────────────────────


class TestApplyAndWrapRemoveNode:

    def test_remove_node_produces_remove_node_change(self) -> None:
        rubric = _make_rubric_two_children()
        draft = _draft("REMOVE_NODE", {
            "criterion_path": [str(ROOT_ID), str(LEAF_ID)],
            "node_kind": "criterion",
        })

        improved, changes = _step3_apply_and_wrap(rubric, [draft], set())

        assert len(changes) == 1
        change = changes[0]
        assert change.operation == "REMOVE_NODE"
        assert change.application_status.value == "applied"
        assert change.removed_snapshot.name == "Leaf A"
        assert improved.total_points == pytest.approx(1.5)
