"""§ 4.6 *ProposedChange* — discriminated union over operation kinds."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.models.findings import ConfidenceIndicator, QualityCriterion
from grading_rubric.models.rubric import RubricCriterion, RubricLevel, RubricTarget
from grading_rubric.models.types import (
    ChangeId,
    CriterionId,
    FindingId,
    JsonValue,
    LevelId,
    OperationId,
)


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"


class TeacherDecision(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class NodeKind(StrEnum):
    CRITERION = "criterion"
    LEVEL = "level"


class _ProposedChangeBase(BaseModel):
    """Common envelope shared by every `ProposedChange` variant.

    `application_status` and `teacher_decision` keep system and human decisions
    cleanly separable (SR-OUT-05 + SR-IM-01). `source_operations` is the audit-
    join key into the operation chain (DR-IM-07 wrap step).
    """

    model_config = ConfigDict(strict=True)

    id: ChangeId
    primary_criterion: QualityCriterion
    source_findings: list[FindingId]
    rationale: str
    confidence: ConfidenceIndicator
    application_status: ApplicationStatus
    teacher_decision: TeacherDecision | None = None
    source_operations: list[OperationId] = []


class ReplaceFieldChange(_ProposedChangeBase):
    operation: Literal["REPLACE_FIELD"] = "REPLACE_FIELD"
    target: RubricTarget
    before: JsonValue | None
    after: JsonValue


class UpdatePointsChange(_ProposedChangeBase):
    operation: Literal["UPDATE_POINTS"] = "UPDATE_POINTS"
    target: RubricTarget
    before: float | None
    after: float


class AddNodeChange(_ProposedChangeBase):
    operation: Literal["ADD_NODE"] = "ADD_NODE"
    parent_path: list[CriterionId]
    insert_index: int
    node_kind: NodeKind
    node: RubricCriterion | RubricLevel


class RemoveNodeChange(_ProposedChangeBase):
    operation: Literal["REMOVE_NODE"] = "REMOVE_NODE"
    criterion_path: list[CriterionId]
    level_id: LevelId | None = None
    node_kind: NodeKind
    removed_snapshot: RubricCriterion | RubricLevel


class ReorderNodesChange(_ProposedChangeBase):
    operation: Literal["REORDER_NODES"] = "REORDER_NODES"
    parent_path: list[CriterionId]
    node_kind: NodeKind
    before_order: list[UUID]
    after_order: list[UUID]


ProposedChange = Annotated[
    ReplaceFieldChange | UpdatePointsChange | AddNodeChange | RemoveNodeChange | ReorderNodesChange,
    Field(discriminator="operation"),
]
