"""Pydantic response + input schemas for assess-stage gateway calls.

These are the `output_schema` and `inputs` shapes passed to `Gateway.measure()`.
They live in the assess sub-package per DR-DAT-01 (stage-local shapes).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


# ── Output schemas (what the LLM returns) ────────────────────────────────


class SweepHit(BaseModel):
    """One problematic phrase found during a linguistic sweep."""

    model_config = ConfigDict(strict=True)

    criterion_path: list[str]
    field: str
    problematic_phrase: str
    issue_type: str  # vague_term | undefined_threshold | overlapping_levels | external_reference | missing_anchor
    severity: str  # low | medium | high
    explanation: str


class LinguisticSweepReport(BaseModel):
    """DR-AS-06 — full linguistic sweep output."""

    model_config = ConfigDict(strict=True)

    hits: list[SweepHit] = []


class CriterionGrade(BaseModel):
    """One grader's grade on a single criterion."""

    model_config = ConfigDict(strict=True)

    criterion_path: list[str]
    grade: float  # 0.0–1.0
    justification: str


class GradingResult(BaseModel):
    """DR-AS-06 — grader panel per-response result."""

    model_config = ConfigDict(strict=True)

    grades: list[CriterionGrade] = []


class CoverageVerdict(BaseModel):
    """DR-AS-07 — applicability coverage verdict for one response."""

    model_config = ConfigDict(strict=True)

    status: str  # covered | partial | uncovered
    covered_criteria: list[str] = []
    missing_dimension: str = ""
    evidence: str = ""


class CriterionScoreEntry(BaseModel):
    """Per-criterion score from a discrimination scoring call."""

    model_config = ConfigDict(strict=True)

    criterion_path: list[str]
    score: float  # 0.0–1.0
    justification: str


class RubricScoring(BaseModel):
    """DR-AS-08 — per-criterion scores for discrimination analysis."""

    model_config = ConfigDict(strict=True)

    criterion_scores: list[CriterionScoreEntry] = []
    overall_score: float = 0.0


class PairwiseVerdict(BaseModel):
    """DR-AS-09 — head-to-head comparison of two responses."""

    model_config = ConfigDict(strict=True)

    winner: str  # A | B | EQUAL
    confidence: float  # 0.0–1.0
    reason: str
    ambiguity_attributed: bool = False


class SynthesizedResponse(BaseModel):
    """One synthetic student response at a specific quality tier."""

    model_config = ConfigDict(strict=True)

    tier: str  # weak | average | strong
    text: str
    intended_score: float  # 0.0–1.0


class SynthesizedResponseSet(BaseModel):
    """DR-AS — synthetic student responses for discrimination testing."""

    model_config = ConfigDict(strict=True)

    responses: list[SynthesizedResponse] = []


# ── Input schemas (what we send to the gateway) ─────────────────────────


class LinguisticSweepInputs(BaseModel):
    """Inputs for the ambiguity_linguistic_sweep prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    vague_term_seed_list: str


class GraderPanelInputs(BaseModel):
    """Inputs for the ambiguity_grade_with_rubric prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    response_text: str
    persona_description: str
    criterion_names: str


class CoverageInputs(BaseModel):
    """Inputs for the applicability_cover_response prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    response_text: str
    evidence_context: str


class ScoringInputs(BaseModel):
    """Inputs for the discrimination_score_response prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    response_text: str
    criterion_names: str


class PairwiseInputs(BaseModel):
    """Inputs for the discrimination_pairwise_compare prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    response_a_text: str
    response_b_text: str


class SynthesizeInputs(BaseModel):
    """Inputs for the assess_synthesize_responses prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    exam_question_text: str
    tier_count: str
