"""DR-ARC-04 — `run-pipeline` thin in-process orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from grading_rubric.audit.emitter import AuditEmitter, JsonLineEmitter
from grading_rubric.config.settings import Settings


class PipelineInputs(BaseModel):
    """Single bundle of paths the in-process pipeline reads from disk."""

    exam_question_path: Path
    teaching_material_paths: list[Path] = []
    starting_rubric_path: Path | None = None
    starting_rubric_inline: str | None = None
    student_copy_paths: list[Path] = []


class PipelineOutputs(BaseModel):
    """In-memory result of one in-process pipeline run."""

    explained_rubric_path: Path


def run_pipeline(
    *,
    pipeline_inputs: PipelineInputs,
    output_path: Path,
    settings: Settings,
    audit_emitter: AuditEmitter | None = None,
) -> PipelineOutputs:
    """Run all six stages in order: ingest → parse-inputs → assess → propose → score → render."""

    em = audit_emitter or JsonLineEmitter()

    # Late imports — keep `orchestrator` -> stages dependency one-way (DR-ARC-02).
    from grading_rubric.assess.stage import assess_stage
    from grading_rubric.improve.stage import propose_stage
    from grading_rubric.output.render_stage import render_stage
    from grading_rubric.parsers.ingest_stage import ingest_stage
    from grading_rubric.parsers.parse_stage import parse_inputs_stage
    from grading_rubric.scorer.score_stage import score_stage

    run_id = uuid4()
    started_at = datetime.now(UTC)

    em.stage_start("run-pipeline")

    # 1. ingest — produce InputProvenance + EvidenceProfile from the raw paths
    ingest_out = ingest_stage(
        pipeline_inputs, settings=settings, audit_emitter=em
    )

    # 2. parse-inputs — turn raw inputs into structured text + an initial rubric
    parsed = parse_inputs_stage(
        ingest_out, settings=settings, audit_emitter=em
    )

    # 3. assess — three-engine measurement loop, produces findings
    assessed = assess_stage(parsed, settings=settings, audit_emitter=em)

    # 4. propose — apply the three-step pipeline, produce ProposedChange records
    proposed = propose_stage(assessed, settings=settings, audit_emitter=em)

    # 5. score — produce the three CriterionScore records (DR-SCR-01/02)
    scored = score_stage(proposed, settings=settings, audit_emitter=em)

    # 6. render — write the ExplainedRubricFile to disk (SR-OUT-01..05)
    rendered = render_stage(
        scored,
        output_path=output_path,
        run_id=run_id,
        started_at=started_at,
        settings=settings,
        audit_emitter=em,
    )

    em.stage_end("run-pipeline", status="success")
    return PipelineOutputs(explained_rubric_path=rendered.output_path)
