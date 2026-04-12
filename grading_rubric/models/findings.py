"""§ 4.5 *AssessmentFinding* and its supporting enums and shapes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from grading_rubric.models.rubric import RubricTarget
from grading_rubric.models.types import FindingId, OperationId, RubricId


class QualityCriterion(StrEnum):
    AMBIGUITY = "ambiguity"
    APPLICABILITY = "applicability"
    DISCRIMINATION_POWER = "discrimination_power"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _level_for_score(score: float) -> ConfidenceLevel:
    """§ 4.5 confidence-level thresholds (locked)."""

    if score < 0.40:
        return ConfidenceLevel.LOW
    if score < 0.75:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.HIGH


class ConfidenceIndicator(BaseModel):
    """A measurement-confidence indicator (§ 4.5).

    `level` is derived from `score` by the locked thresholds and is validated for
    consistency on construction. It exists as a field rather than a property so
    JSON Schema (§ 3.6) exposes it explicitly to the front-end (DR-DAT-04).
    """

    model_config = ConfigDict(strict=True)

    score: float
    level: ConfidenceLevel
    rationale: str

    @model_validator(mode="after")
    def _check_level(self) -> "ConfidenceIndicator":
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"confidence score {self.score} not in [0, 1]")
        expected = _level_for_score(self.score)
        if self.level != expected:
            raise ValueError(
                f"confidence level {self.level.value} inconsistent with "
                f"score {self.score} (expected {expected.value})"
            )
        return self

    @classmethod
    def from_score(cls, score: float, rationale: str) -> "ConfidenceIndicator":
        """Convenience constructor that derives `level` from `score`."""

        return cls(score=score, level=_level_for_score(score), rationale=rationale)


class QualityMethod(StrEnum):
    """Closed enum of measurement methods. § 4.5.

    Shared between `Measurement.method` (assess stage) and `CriterionScore.method`
    (score stage). The partition is by *which shape carries the field*, never by
    *which value the field can take* — `LLM_PANEL_AGREEMENT` is intentionally on
    both shapes (DR-AS-06 / DR-SCR-02).
    """

    LLM_PANEL_AGREEMENT = "llm_panel_agreement"
    PAIRWISE_CONSISTENCY = "pairwise_consistency"
    SYNTHETIC_COVERAGE = "synthetic_coverage"
    SCORE_DISTRIBUTION_SEPARATION = "score_distribution_separation"
    LINGUISTIC_SWEEP = "linguistic_sweep"


class Measurement(BaseModel):
    """One per-finding measurement record (§ 4.5)."""

    model_config = ConfigDict(strict=True)

    method: QualityMethod
    samples: int
    agreement: float | None = None


class AssessmentFinding(BaseModel):
    """A single observation about a rubric node (§ 4.5).

    Carries exactly one `criterion` (SR-AS-07). The `target` is `None` for
    rubric-wide findings, absence findings, and total-scale findings; the dual
    signal of SR-AS-10 is expressed via `linked_finding_ids`.
    """

    model_config = ConfigDict(strict=True)

    id: FindingId
    criterion: QualityCriterion
    severity: Severity
    target: RubricTarget | None
    observation: str
    evidence: str
    measurement: Measurement
    confidence: ConfidenceIndicator
    measured_against_rubric_id: RubricId
    iteration: int = 0
    source_operations: list[OperationId] = []
    linked_finding_ids: list[FindingId] = []
