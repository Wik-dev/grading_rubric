"""§ 4.7 *Explanation* — teacher-facing structured rationale."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator

from grading_rubric.models.findings import QualityCriterion
from grading_rubric.models.types import ChangeId, FindingId


class CriterionSection(BaseModel):
    """A criterion-organised section of the explanation.

    Canonical SR-IM-06 *no improvement warranted* representation for one
    criterion: empty `finding_refs`, empty `change_refs`, narrative explaining
    why no issues were found. The Explanation invariant requires one section
    per `QualityCriterion` regardless of whether any findings were produced.
    """

    model_config = ConfigDict(strict=True)

    criterion: QualityCriterion
    finding_refs: list[FindingId] = []
    change_refs: list[ChangeId] = []
    unaddressed_finding_refs: list[FindingId] = []
    narrative: str


class CrossCuttingGroup(BaseModel):
    """Grouping over items already tagged in `by_criterion` (§ 4.7)."""

    model_config = ConfigDict(strict=True)

    title: str
    narrative: str
    finding_refs: list[FindingId]
    change_refs: list[ChangeId]


class Explanation(BaseModel):
    """The teacher-facing rationale, organised by quality criterion (§ 4.7)."""

    model_config = ConfigDict(strict=True)

    summary: str
    by_criterion: dict[QualityCriterion, CriterionSection]
    cross_cutting: list[CrossCuttingGroup] = []

    @model_validator(mode="after")
    def _check_invariants(self) -> Explanation:
        # § 4.7 invariant: by_criterion has exactly one entry per QualityCriterion.
        expected = set(QualityCriterion)
        if set(self.by_criterion.keys()) != expected:
            missing = expected - set(self.by_criterion.keys())
            extra = set(self.by_criterion.keys()) - expected
            raise ValueError(
                f"by_criterion must have one entry per QualityCriterion "
                f"(missing={sorted(c.value for c in missing)}, "
                f"extra={sorted(c.value for c in extra)})"
            )

        # cross-cutting refs must already appear in by_criterion sections.
        all_findings: set = set()
        all_changes: set = set()
        for section in self.by_criterion.values():
            all_findings.update(section.finding_refs)
            all_changes.update(section.change_refs)
        for group in self.cross_cutting:
            stray_f = set(group.finding_refs) - all_findings
            stray_c = set(group.change_refs) - all_changes
            if stray_f or stray_c:
                raise ValueError(
                    f"cross-cutting group {group.title!r} references items not "
                    f"present in by_criterion (findings={stray_f}, changes={stray_c})"
                )
        return self
