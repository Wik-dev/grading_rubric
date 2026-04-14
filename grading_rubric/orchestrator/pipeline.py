"""DR-ARC-04 — `run-pipeline` thin in-process orchestrator."""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from grading_rubric.assess.simulation import SimulationEvidence
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
    artifact_dir: Path | None = None


def _write_artifact_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        prepared = payload.model_dump(mode="json")
    else:
        prepared = _prepare_artifact_json(payload)
    text = json.dumps(prepared, indent=2, ensure_ascii=False, default=str)
    path.write_text(text, encoding="utf-8")


def _prepare_artifact_json(payload):
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, list):
        return [_prepare_artifact_json(item) for item in payload]
    if isinstance(payload, tuple):
        return [_prepare_artifact_json(item) for item in payload]
    if isinstance(payload, dict):
        return {str(key): _prepare_artifact_json(value) for key, value in payload.items()}
    return payload


def _write_artifact_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _simulation_distribution(sim: SimulationEvidence) -> dict:
    grades = [entry.grade for entry in sim.grade_entries]

    def stats(values: list[float]) -> dict:
        return {
            "count": len(values),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "mean": statistics.mean(values) if values else None,
            "stdev": statistics.stdev(values) if len(values) >= 2 else 0.0,
        }

    by_criterion: dict[str, list[float]] = {}
    by_response: dict[str, list[float]] = {}
    by_persona: dict[str, list[float]] = {}
    for entry in sim.grade_entries:
        by_criterion.setdefault(entry.criterion_id, []).append(entry.grade)
        by_response.setdefault(str(entry.response_idx), []).append(entry.grade)
        by_persona.setdefault(str(entry.persona_idx), []).append(entry.grade)

    return {
        "overall": stats(grades),
        "by_criterion": {key: stats(values) for key, values in by_criterion.items()},
        "by_response": {key: stats(values) for key, values in by_response.items()},
        "by_persona": {key: stats(values) for key, values in by_persona.items()},
    }


def _write_simulation_artifacts(root: Path, sim: SimulationEvidence) -> None:
    _write_artifact_json(root / "simulation_evidence.json", sim)
    _write_artifact_json(
        root / "synthetic_responses.json",
        [
            item.model_dump(mode="json")
            for item in sim.response_set
            if item.source == "synthetic"
        ],
    )
    _write_artifact_json(
        root / "responses.json",
        [item.model_dump(mode="json") for item in sim.response_set],
    )
    _write_artifact_json(
        root / "grade_matrix.json",
        [entry.model_dump(mode="json") for entry in sim.grade_entries],
    )
    _write_artifact_json(
        root / "pairwise_comparisons.json",
        [entry.model_dump(mode="json") for entry in sim.pairwise_results],
    )
    _write_artifact_json(root / "grade_distribution.json", _simulation_distribution(sim))


def run_pipeline(
    *,
    pipeline_inputs: PipelineInputs,
    output_path: Path,
    settings: Settings,
    audit_emitter: AuditEmitter | None = None,
    artifact_dir: Path | None = None,
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
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        _write_artifact_json(
            artifact_dir / "run_metadata.json",
            {
                "run_id": str(run_id),
                "started_at": started_at.isoformat(),
                "output_path": str(output_path),
                "settings": {
                    "llm_backend": settings.llm_backend,
                    "llm_model_pinned": settings.llm_model_pinned,
                    "llm_model_rubric_decomposition": settings.llm_model_rubric_decomposition,
                    "assess_target_response_count": settings.assess_target_response_count,
                    "assess_panel_size": settings.assess_panel_size,
                    "assess_pairwise_sample_size": settings.assess_pairwise_sample_size,
                    "llm_sampling_temperature": settings.llm_sampling_temperature,
                    "llm_call_timeout_seconds": settings.llm_call_timeout_seconds,
                    "llm_rate_limit_max_retries": settings.llm_rate_limit_max_retries,
                },
            },
        )

    em.stage_start("run-pipeline")

    # 1. ingest — produce InputProvenance + EvidenceProfile from the raw paths
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "ingest" / "inputs.json", pipeline_inputs)
    ingest_out = ingest_stage(
        pipeline_inputs, settings=settings, audit_emitter=em
    )
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "ingest" / "outputs.json", ingest_out)

    # 2. parse-inputs — turn raw inputs into structured text + an initial rubric
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "parse-inputs" / "inputs.json", ingest_out)
    parsed = parse_inputs_stage(
        ingest_out, settings=settings, audit_emitter=em
    )
    if artifact_dir is not None:
        parse_dir = artifact_dir / "parse-inputs"
        _write_artifact_json(parse_dir / "outputs.json", parsed)
        _write_artifact_text(parse_dir / "extracted_exam_question.txt", parsed.exam_question_text)
        _write_artifact_text(parse_dir / "extracted_teaching_material.txt", parsed.teaching_material_text)
        _write_artifact_json(parse_dir / "extracted_starting_rubric.json", parsed.starting_rubric)
        _write_artifact_json(parse_dir / "student_copies_text.json", parsed.student_copies_text)

    # 3. assess — three-engine measurement loop, produces findings
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "assess" / "inputs.json", parsed)
    assessed = assess_stage(parsed, settings=settings, audit_emitter=em)
    if artifact_dir is not None:
        assess_dir = artifact_dir / "assess"
        _write_artifact_json(assess_dir / "outputs.json", assessed)
        _write_artifact_json(assess_dir / "findings.json", assessed.findings)
        _write_artifact_json(assess_dir / "quality_scores.json", assessed.quality_scores)
        _write_artifact_text(assess_dir / "simulation_summary.txt", assessed.simulation_summary)
        if assessed.simulation_evidence is not None:
            _write_simulation_artifacts(assess_dir, assessed.simulation_evidence)

    # 4. propose — apply the three-step pipeline, produce ProposedChange records
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "propose" / "inputs.json", assessed)
    proposed = propose_stage(assessed, settings=settings, audit_emitter=em)
    if artifact_dir is not None:
        propose_dir = artifact_dir / "propose"
        _write_artifact_json(propose_dir / "outputs.json", proposed)
        _write_artifact_json(propose_dir / "findings.json", proposed.findings)
        _write_artifact_json(propose_dir / "proposed_changes.json", proposed.proposed_changes)
        _write_artifact_json(propose_dir / "improved_rubric.json", proposed.improved_rubric)

    # 5. score — produce the three CriterionScore records (DR-SCR-01/02)
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "score" / "inputs.json", proposed)
    scored = score_stage(proposed, settings=settings, audit_emitter=em)
    if artifact_dir is not None:
        score_dir = artifact_dir / "score"
        _write_artifact_json(score_dir / "outputs.json", scored)
        _write_artifact_json(score_dir / "quality_scores.json", scored.quality_scores)
        _write_artifact_json(score_dir / "previous_quality_scores.json", scored.previous_quality_scores)
        _write_artifact_json(
            score_dir / "before_after_scores.json",
            {
                "previous_quality_scores": [
                    s.model_dump(mode="json") for s in (scored.previous_quality_scores or [])
                ],
                "quality_scores": [s.model_dump(mode="json") for s in scored.quality_scores],
                "same_response_cohort": (
                    assessed.simulation_evidence is not None
                    and scored.simulation_evidence is not None
                    and [
                        r.model_dump(mode="json")
                        for r in assessed.simulation_evidence.response_set
                    ]
                    == [
                        r.model_dump(mode="json")
                        for r in scored.simulation_evidence.response_set
                    ]
                ),
            },
        )
        if scored.simulation_evidence is not None:
            _write_simulation_artifacts(score_dir, scored.simulation_evidence)

    # 6. render — write the ExplainedRubricFile to disk (SR-OUT-01..05)
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "render" / "inputs.json", scored)
    rendered = render_stage(
        scored,
        output_path=output_path,
        run_id=run_id,
        started_at=started_at,
        settings=settings,
        audit_emitter=em,
    )
    if artifact_dir is not None:
        _write_artifact_json(artifact_dir / "render" / "outputs.json", rendered)
        _write_artifact_json(
            artifact_dir / "render" / "final_explained_rubric.json",
            rendered.explained_rubric,
        )

    em.stage_end("run-pipeline", status="success")
    return PipelineOutputs(
        explained_rubric_path=rendered.output_path,
        artifact_dir=artifact_dir,
    )
