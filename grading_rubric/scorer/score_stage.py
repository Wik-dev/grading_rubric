"""DR-SCR-01..04 — `score` stage entry point.

Wraps the `Scorer` Protocol selection (DR-SCR-04) and the
`ScoringEvidence` → `ScoringResult` call (DR-SCR-01) into the standard
stage shape so the orchestrator can chain it after `propose`.
"""

from __future__ import annotations

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.improve.models import ProposeOutputs
from grading_rubric.scorer.models import ScoreOutputs, ScoringEvidence
from grading_rubric.scorer.scorer import make_scorer

STAGE_ID = "score"


def score_stage(
    inputs: ProposeOutputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ScoreOutputs:
    audit_emitter.stage_start(STAGE_ID)

    parsed = inputs.assessed.parsed
    evidence = ScoringEvidence(
        rubric=inputs.improved_rubric,
        exam_question_text=parsed.exam_question_text,
        teaching_material_text=parsed.teaching_material_text,
        student_copies_text=parsed.student_copies_text,
        findings=inputs.findings,
    )

    scorer = make_scorer(settings)
    result = scorer.score_rubric(
        evidence, settings=settings, audit_emitter=audit_emitter
    )

    audit_emitter.stage_end(STAGE_ID, status="success")
    return ScoreOutputs(
        proposed=inputs,
        quality_scores=result.quality_scores,
        scorer_id=result.scorer_id,
        scorer_version=result.scorer_version,
    )


score_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
