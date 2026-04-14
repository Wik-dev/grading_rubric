"""Pydantic response + input schemas for propose-stage gateway calls.

Stage-local per DR-DAT-01. Used by `_plan_drafts_llm()` in `stage.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ── Output schema (what the LLM returns) ─────────────────────────────────


class LlmDraftEntry(BaseModel):
    """One proposed change from the LLM planner."""

    model_config = ConfigDict(strict=True)

    operation: str  # REPLACE_FIELD | UPDATE_POINTS | ADD_NODE | REMOVE_NODE | REORDER_NODES
    primary_criterion: str  # ambiguity | applicability | discrimination_power
    source_finding_ids: list[str] = Field(default_factory=list)
    rationale: str
    confidence_score: float  # 0.0–1.0
    payload: dict = Field(default_factory=dict)


class LlmPlannerOutput(BaseModel):
    """Full planner output from the propose_planner prompt."""

    model_config = ConfigDict(strict=True)

    decision: str
    drafts: list[LlmDraftEntry] = Field(default_factory=list)


# ── Input schema (what we send to the gateway) ──────────────────────────


class LlmPlannerInput(BaseModel):
    """Inputs for the propose_planner prompt."""

    model_config = ConfigDict(strict=True)

    rubric_json: str
    findings_json: str
    evidence_profile_json: str
    criterion_paths_json: str
    teaching_material_text: str
    simulation_summary: str = ""
