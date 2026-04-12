"""§ 4 contract data models. Pydantic v2 is the single source of truth (DR-DAT-01).

This sub-package contains *only* shapes that appear in `docs/design.md` § 4 — the
cross-stage Domain models, Provenance models, and Shared primitives that travel
along the L1↔L3 boundary, the audit-event stream, the deliverable, and the
codegen surface (DR-DAT-04). Stage-local input/output models live in their stage
sub-package next to the stage that owns them, never here.
"""

from grading_rubric.models.audit import (
    AgentStepDetails,
    AuditBundle,
    DeterministicDetails,
    ErrorRecord,
    HumanDecisionDetails,
    InputProvenance,
    InputSource,
    InputSourceKind,
    IterationSnapshot,
    LlmCallDetails,
    MlInferenceDetails,
    OcrCallDetails,
    OperationDetails,
    OperationKind,
    OperationRecord,
    OperationStatus,
    OperationSummary,
    StageRecord,
    StageStatus,
    ToolCallDetails,
)
from grading_rubric.models.deliverable import CriterionScore, ExplainedRubricFile
from grading_rubric.models.explanation import (
    CriterionSection,
    CrossCuttingGroup,
    Explanation,
)
from grading_rubric.models.findings import (
    AssessmentFinding,
    ConfidenceIndicator,
    ConfidenceLevel,
    Measurement,
    QualityCriterion,
    QualityMethod,
    Severity,
)
from grading_rubric.models.proposed_change import (
    AddNodeChange,
    ApplicationStatus,
    NodeKind,
    ProposedChange,
    RemoveNodeChange,
    ReorderNodesChange,
    ReplaceFieldChange,
    TeacherDecision,
    UpdatePointsChange,
)
from grading_rubric.models.rubric import (
    EvidenceProfile,
    Rubric,
    RubricCriterion,
    RubricFieldName,
    RubricLevel,
    RubricTarget,
)
from grading_rubric.models.types import (
    ChangeId,
    CriterionId,
    FindingId,
    JsonValue,
    LevelId,
    OperationId,
    RubricId,
    RunId,
)

# Resolve the forward reference IterationSnapshot.quality_scores → CriterionScore.
# Both modules are now loaded so the forward string can be resolved.
IterationSnapshot.model_rebuild(_types_namespace={"CriterionScore": CriterionScore})

__all__ = [
    # Type aliases
    "RubricId",
    "CriterionId",
    "LevelId",
    "FindingId",
    "ChangeId",
    "OperationId",
    "RunId",
    "JsonValue",
    # Rubric
    "Rubric",
    "RubricCriterion",
    "RubricLevel",
    "RubricTarget",
    "RubricFieldName",
    "EvidenceProfile",
    # Findings
    "AssessmentFinding",
    "QualityCriterion",
    "QualityMethod",
    "Severity",
    "ConfidenceLevel",
    "ConfidenceIndicator",
    "Measurement",
    # Proposed changes
    "ProposedChange",
    "ReplaceFieldChange",
    "UpdatePointsChange",
    "AddNodeChange",
    "RemoveNodeChange",
    "ReorderNodesChange",
    "ApplicationStatus",
    "TeacherDecision",
    "NodeKind",
    # Explanation
    "Explanation",
    "CriterionSection",
    "CrossCuttingGroup",
    # Audit
    "AuditBundle",
    "StageRecord",
    "StageStatus",
    "OperationKind",
    "OperationStatus",
    "OperationRecord",
    "OperationSummary",
    "OperationDetails",
    "LlmCallDetails",
    "OcrCallDetails",
    "MlInferenceDetails",
    "ToolCallDetails",
    "HumanDecisionDetails",
    "AgentStepDetails",
    "DeterministicDetails",
    "ErrorRecord",
    "IterationSnapshot",
    "InputSource",
    "InputSourceKind",
    "InputProvenance",
    # Deliverable
    "ExplainedRubricFile",
    "CriterionScore",
]
