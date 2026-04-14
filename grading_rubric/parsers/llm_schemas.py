"""Pydantic schemas for parse-stage gateway calls."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DecomposedCriterion(BaseModel):
    """One criterion extracted from a free-text rubric."""

    model_config = ConfigDict(strict=True)

    name: str
    description: str
    scoring_guidance: str = ""
    points: float
    is_penalty: bool = False
    penalty_trigger: str = ""
    sub_criteria: list["DecomposedCriterion"] = Field(default_factory=list)


class DecomposedRubric(BaseModel):
    """Structured rubric extracted from free text by the parse stage."""

    model_config = ConfigDict(strict=True)

    title: str
    total_points: float
    criteria: list[DecomposedCriterion] = Field(default_factory=list)
    penalizations: list[DecomposedCriterion] = Field(default_factory=list)
    parsing_notes: str = ""


class DecomposeRubricInput(BaseModel):
    """Inputs for the decompose_rubric prompt."""

    model_config = ConfigDict(strict=True)

    rubric_text: str
    exam_question_text: str = ""
    teaching_material_text: str = ""


DecomposedCriterion.model_rebuild()
