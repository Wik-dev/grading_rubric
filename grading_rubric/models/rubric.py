"""§ 4.2 *Rubric*, § 4.3 *RubricTarget*, § 4.4 *EvidenceProfile*."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from grading_rubric.models.types import CriterionId, JsonValue, LevelId, RubricId


class RubricLevel(BaseModel):
    """One scoring level on a leaf criterion (e.g. *Excellent / Good / Fair / Poor*)."""

    model_config = ConfigDict(strict=True)

    id: LevelId
    slug: str | None = None
    label: str
    points: float
    descriptor: str


class RubricCriterion(BaseModel):
    """A node in the recursive rubric tree (§ 4.2)."""

    model_config = ConfigDict(strict=True)

    id: CriterionId
    slug: str | None = None
    name: str
    description: str
    scoring_guidance: str | None = None
    points: float | None = None
    weight: float | None = None
    additive: bool = True
    levels: list[RubricLevel] = []
    sub_criteria: list[RubricCriterion] = []


class Rubric(BaseModel):
    """A rubric tree of criteria with point allocations (§ 4.2)."""

    model_config = ConfigDict(strict=True)

    id: RubricId
    schema_version: str
    title: str
    exam_question_ref: str | None = None
    total_points: float
    criteria: list[RubricCriterion]
    metadata: dict[str, JsonValue] = {}

    @model_validator(mode="after")
    def _check_invariants(self) -> Rubric:
        # Check unique IDs and the additive-points invariant. § 4.2.
        seen_ids: set = set()

        def visit(c: RubricCriterion) -> None:
            if c.id in seen_ids:
                raise ValueError(f"duplicate criterion id {c.id}")
            seen_ids.add(c.id)
            if c.points is None:
                raise ValueError(
                    f"criterion {c.id} ({c.name!r}): points must be set on every node"
                )
            for lvl in c.levels:
                if lvl.id in seen_ids:
                    raise ValueError(f"duplicate level id {lvl.id}")
                seen_ids.add(lvl.id)
                if not (0.0 <= lvl.points <= c.points):
                    raise ValueError(
                        f"level {lvl.id} points {lvl.points} not in [0, {c.points}]"
                    )
            for child in c.sub_criteria:
                visit(child)
            if c.additive and c.sub_criteria:
                child_sum = sum((child.points or 0.0) for child in c.sub_criteria)
                if abs(child_sum - c.points) > 1e-6:
                    raise ValueError(
                        f"additive criterion {c.id}: points {c.points} != "
                        f"sum of children {child_sum}"
                    )

        for root in self.criteria:
            visit(root)

        root_sum = sum((c.points or 0.0) for c in self.criteria)
        if abs(root_sum - self.total_points) > 1e-6:
            raise ValueError(
                f"rubric total_points {self.total_points} != sum of root criterion "
                f"points {root_sum}"
            )
        return self


# Forward-ref the recursive list field — Pydantic v2 picks this up via PEP 563.
RubricCriterion.model_rebuild()


class RubricFieldName(StrEnum):
    NAME = "name"
    DESCRIPTION = "description"
    SCORING_GUIDANCE = "scoring_guidance"
    POINTS = "points"
    WEIGHT = "weight"
    LEVEL_LABEL = "level.label"
    LEVEL_DESCRIPTOR = "level.descriptor"
    LEVEL_POINTS = "level.points"


class RubricTarget(BaseModel):
    """Path-by-UUID address into a rubric (§ 4.3)."""

    model_config = ConfigDict(strict=True)

    criterion_path: list[CriterionId]
    level_id: LevelId | None = None
    field: RubricFieldName

    @model_validator(mode="after")
    def _check_invariants(self) -> RubricTarget:
        if not self.criterion_path:
            raise ValueError("criterion_path must be non-empty")
        level_field = self.field in {
            RubricFieldName.LEVEL_LABEL,
            RubricFieldName.LEVEL_DESCRIPTOR,
            RubricFieldName.LEVEL_POINTS,
        }
        if level_field and self.level_id is None:
            raise ValueError(f"field {self.field.value} requires level_id")
        if not level_field and self.level_id is not None:
            raise ValueError(
                f"level_id is only valid for level.* fields, not {self.field.value}"
            )
        return self


class EvidenceProfile(BaseModel):
    """Per-input artefact summary, populated by `ingest` and refined by `assess`.

    The `synthetic_responses_used` flag (§ 4.4) is set to `True` if and only if
    `assess` had to synthesise candidate responses to measure Discrimination
    Power because no real student copies were available.
    """

    model_config = ConfigDict(strict=True)

    starting_rubric_present: bool
    exam_question_present: bool
    teaching_material_present: bool
    teaching_material_count: int = 0
    student_copies_present: bool
    student_copies_count: int = 0
    student_copies_pages_total: int = 0

    starting_rubric_hash: str | None = None
    exam_question_hash: str | None = None
    teaching_material_hashes: list[str] = []
    student_copies_hashes: list[str] = []

    synthetic_responses_used: bool = False

    notes: list[str] = []
