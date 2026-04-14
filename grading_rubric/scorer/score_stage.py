"""DR-SCR — `score` stage entry point.

Re-runs the shared grader simulation against the improved rubric and converts
the resulting grade matrix into headline quality scores.
"""

from __future__ import annotations

from grading_rubric.assess.engines import scores_from_simulation
from grading_rubric.assess.simulation import run_grader_simulation
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.improve.models import ProposeOutputs
from grading_rubric.scorer.models import ScoreOutputs

STAGE_ID = "score"


def score_stage(
    inputs: ProposeOutputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ScoreOutputs:
    audit_emitter.stage_start(STAGE_ID)

    parsed = inputs.assessed.parsed

    improved_simulation = run_grader_simulation(
        inputs.improved_rubric,
        parsed.exam_question_text,
        parsed.teaching_material_text,
        parsed.student_copies_text,
        settings=settings,
        audit_emitter=audit_emitter,
        response_set=(
            inputs.assessed.simulation_evidence.response_set
            if inputs.assessed.simulation_evidence is not None
            else None
        ),
        stage_id=STAGE_ID,
    )
    improved_scores = scores_from_simulation(
        improved_simulation, rubric=inputs.improved_rubric, settings=settings
    )
    previous_scores = inputs.assessed.quality_scores or None

    audit_emitter.stage_end(STAGE_ID, status="success")
    return ScoreOutputs(
        proposed=inputs,
        quality_scores=improved_scores,
        previous_quality_scores=previous_scores,
        scorer_id="simulation.v1",
        scorer_version="1.0.0",
        simulation_evidence=improved_simulation,
    )


score_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
