"""Pydantic response + input schemas for assess-stage gateway calls.

These are the `output_schema` and `inputs` shapes passed to `Gateway.measure()`.
They live in the assess sub-package per DR-DAT-01 (stage-local shapes).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ── Output schemas (what the LLM returns) ────────────────────────────────


class CriterionGrade(BaseModel):
    """One grader's grade on a single criterion."""

    model_config = ConfigDict(strict=True)

    criterion_path: list[str]
    grade: float = Field(ge=0.0, le=1.0)  # 0.0–1.0
    justification: str


class GradingResult(BaseModel):
    """DR-AS-06 — grader panel per-response result."""

    model_config = ConfigDict(strict=True)

    grades: list[CriterionGrade] = Field(default_factory=list)


class PairwiseVerdict(BaseModel):
    """DR-AS-09 — head-to-head comparison of two responses."""

    model_config = ConfigDict(strict=True)

    winner: str  # A | B | EQUAL
    confidence: float = Field(ge=0.0, le=1.0)  # 0.0–1.0
    reason: str
    ambiguity_attributed: bool = False
    affected_criterion_ids: list[str] = Field(default_factory=list)


class SynthesizedResponse(BaseModel):
    """One synthetic student response at a specific quality tier."""

    model_config = ConfigDict(strict=True)

    tier: str  # weak | average | strong
    text: str
    intended_score: float = Field(ge=0.0, le=1.0)  # 0.0–1.0


class SynthesizedResponseSet(BaseModel):
    """DR-AS — synthetic student responses for discrimination testing."""

    model_config = ConfigDict(strict=True)

    responses: list[SynthesizedResponse] = Field(default_factory=list)
    self_check_notes: str


# ── Input schemas (what we send to the gateway) ─────────────────────────


class GraderPanelInputs(BaseModel):
    """Inputs for the ambiguity_grade_with_rubric prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    teaching_material_text: str = ""
    response_text: str
    persona_description: str
    criterion_names: str


class PairwiseInputs(BaseModel):
    """Inputs for the discrimination_pairwise_compare prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    teaching_material_text: str = ""
    response_a_text: str
    response_b_text: str


class SynthesizeInputs(BaseModel):
    """Inputs for the assess_synthesize_responses prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    exam_question_text: str
    teaching_material_text: str = ""
    tier_count: str
