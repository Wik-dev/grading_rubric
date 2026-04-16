"""§ 4.8 *Provenance: AuditBundle* — typed view populated by the L3 harvester.

These shapes are **not** written by L1 task code. They define the contract
between the L3 harvester (`validance_integration/harvester.py`, DR-INT-05) and the SPA /
`ExplainedRubricFile` consumers (DR-DAT-07a). On Path A (single-stage CLI
inspection) no `AuditBundle` is produced.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.models.findings import AssessmentFinding
from grading_rubric.models.proposed_change import ProposedChange
from grading_rubric.models.rubric import EvidenceProfile, Rubric
from grading_rubric.models.types import (
    ChangeId,
    FindingId,
    JsonValue,
    OperationId,
    RubricId,
    RunId,
)


class StageStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class OperationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageRecord(BaseModel):
    model_config = ConfigDict(strict=True)

    stage_id: str
    started_at: datetime
    ended_at: datetime
    status: StageStatus
    operation_ids: list[OperationId] = []


class OperationKind(StrEnum):
    """Closed enum of operation kinds the audit layer understands (§ 4.8)."""

    LLM_CALL = "llm_call"
    OCR_CALL = "ocr_call"
    ML_INFERENCE = "ml_inference"
    TOOL_CALL = "tool_call"
    HUMAN_DECISION = "human_decision"
    AGENT_STEP = "agent_step"
    DETERMINISTIC = "deterministic"


class LlmCallDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.LLM_CALL] = OperationKind.LLM_CALL
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    schema_id: str
    schema_hash: str
    model: str
    temperature: float
    samples: int
    tokens_in: int
    tokens_out: int
    rate_limit_retries: int = 0
    raw_responses: list[JsonValue]


class OcrCallDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.OCR_CALL] = OperationKind.OCR_CALL
    backend: str
    pages: int
    underlying_operation_id: OperationId | None = None


class MlInferenceDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.ML_INFERENCE] = OperationKind.ML_INFERENCE
    model_id: str
    model_version: str
    confidence: float | None = None


class ToolCallDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.TOOL_CALL] = OperationKind.TOOL_CALL
    tool_name: str
    arguments_digest: str


class HumanDecisionDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.HUMAN_DECISION] = OperationKind.HUMAN_DECISION
    actor: str
    prompt_shown: str
    decision: str


class AgentStepDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.AGENT_STEP] = OperationKind.AGENT_STEP
    agent_id: str
    step_index: int
    action: str


class DeterministicDetails(BaseModel):
    model_config = ConfigDict(strict=True)

    kind: Literal[OperationKind.DETERMINISTIC] = OperationKind.DETERMINISTIC
    function: str
    library_version: str | None = None


OperationDetails = Annotated[
    LlmCallDetails | OcrCallDetails | MlInferenceDetails | ToolCallDetails | HumanDecisionDetails | AgentStepDetails | DeterministicDetails,
    Field(discriminator="kind"),
]


class ErrorRecord(BaseModel):
    model_config = ConfigDict(strict=True)

    code: str
    message: str
    stage_id: str | None = None
    operation_id: OperationId | None = None


class OperationRecord(BaseModel):
    """The full per-operation record (lives in a per-operation detail block)."""

    model_config = ConfigDict(strict=True)

    id: OperationId
    stage_id: str
    started_at: datetime
    ended_at: datetime
    status: OperationStatus
    attempt: int = 1
    retry_of: OperationId | None = None
    inputs_digest: str
    outputs_digest: str | None
    details: OperationDetails
    error: ErrorRecord | None = None


class OperationSummary(BaseModel):
    """Index entry for an operation in the audit bundle (§ 4.8)."""

    model_config = ConfigDict(strict=True)

    id: OperationId
    stage_id: str
    started_at: datetime
    ended_at: datetime
    status: OperationStatus
    attempt: int = 1
    retry_of: OperationId | None = None
    inputs_digest: str
    outputs_digest: str | None
    details_kind: OperationKind
    details_path: str
    error: ErrorRecord | None = None


class IterationSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    iteration: int
    rubric_id: RubricId
    rubric_snapshot: Rubric
    quality_scores: list[CriterionScore]  # noqa: F821 — forward to deliverable
    finding_ids: list[FindingId]
    applied_change_ids: list[ChangeId] = []
    measured_at: datetime


class InputSourceKind(StrEnum):
    FILE = "file"
    INLINE_TEXT = "inline_text"


class InputSource(BaseModel):
    """Role-agnostic provenance for one input artefact (§ 4.8)."""

    model_config = ConfigDict(strict=True)

    kind: InputSourceKind
    path: str | None = None
    marker: str | None = None
    hash: str


class InputProvenance(BaseModel):
    model_config = ConfigDict(strict=True)

    exam_question: InputSource
    teaching_material: list[InputSource] = []
    starting_rubric: InputSource | None = None
    student_copies: list[InputSource] = []


class AuditBundle(BaseModel):
    """Typed view of a Validance run's audit chain (§ 4.8)."""

    model_config = ConfigDict(strict=True)

    run_id: RunId
    schema_version: str
    started_at: datetime
    ended_at: datetime
    status: Literal["success", "partial", "failed"]
    input_provenance: InputProvenance
    evidence_profile: EvidenceProfile
    stages: list[StageRecord]
    operations: list[OperationSummary]
    findings: list[AssessmentFinding]
    proposed_changes: list[ProposedChange]
    iteration_history: list[IterationSnapshot] = []
    output_file_path: str | None = None
    errors: list[ErrorRecord] = []
