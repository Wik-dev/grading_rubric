"""DR-IO-01..08 — `ingest` stage.

Builds `InputProvenance` and the initial `EvidenceProfile` from the raw paths
the CLI hands in. Reads bytes only enough to compute SHA-256 hashes; the
actual text extraction happens in `parse_inputs`. Per the locked vocabulary
of the four input categories, every input is tagged with its **role** so the
downstream stages never have to fall back on filename heuristics.
"""

from __future__ import annotations

from pathlib import Path

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.audit.hashing import hash_file, hash_text
from grading_rubric.config.settings import Settings
from grading_rubric.models.audit import InputProvenance, InputSource, InputSourceKind
from grading_rubric.models.rubric import EvidenceProfile
from grading_rubric.parsers.models import IngestInputs, IngestOutputs

STAGE_ID = "ingest"


def _file_source(path: Path) -> InputSource:
    return InputSource(
        kind=InputSourceKind.FILE, path=str(path), marker=None, hash=hash_file(path)
    )


def _inline_source(marker: str, text: str) -> InputSource:
    return InputSource(
        kind=InputSourceKind.INLINE_TEXT, path=None, marker=marker, hash=hash_text(text)
    )


def ingest_stage(
    inputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> IngestOutputs:
    """The `ingest` stage entry point. Conforms to the `Stage` protocol."""

    # The thin orchestrator passes a PipelineInputs; the CLI passes an IngestInputs.
    # Normalise to IngestInputs.
    if not isinstance(inputs, IngestInputs):
        inputs = IngestInputs(
            exam_question_path=inputs.exam_question_path,
            teaching_material_paths=list(inputs.teaching_material_paths),
            starting_rubric_path=inputs.starting_rubric_path,
            starting_rubric_inline=inputs.starting_rubric_inline,
            student_copy_paths=list(inputs.student_copy_paths),
        )

    audit_emitter.stage_start(STAGE_ID)

    if not inputs.exam_question_path.exists():
        audit_emitter.stage_end(
            STAGE_ID,
            status="failed",
            error={
                "code": "EXAM_QUESTION_MISSING",
                "message": f"exam_question_path not found: {inputs.exam_question_path}",
            },
        )
        raise FileNotFoundError(inputs.exam_question_path)

    exam_source = _file_source(inputs.exam_question_path)

    teaching_sources = [_file_source(p) for p in inputs.teaching_material_paths]

    if inputs.starting_rubric_inline is not None:
        starting_source: InputSource | None = _inline_source(
            "<inline:starting_rubric>", inputs.starting_rubric_inline
        )
    elif inputs.starting_rubric_path is not None:
        starting_source = _file_source(inputs.starting_rubric_path)
    else:
        starting_source = None

    student_sources = [_file_source(p) for p in inputs.student_copy_paths]

    provenance = InputProvenance(
        exam_question=exam_source,
        teaching_material=teaching_sources,
        starting_rubric=starting_source,
        student_copies=student_sources,
    )

    profile = EvidenceProfile(
        starting_rubric_present=starting_source is not None,
        exam_question_present=True,
        teaching_material_present=bool(teaching_sources),
        teaching_material_count=len(teaching_sources),
        student_copies_present=bool(student_sources),
        student_copies_count=len(student_sources),
        student_copies_pages_total=0,
        starting_rubric_hash=starting_source.hash if starting_source else None,
        exam_question_hash=exam_source.hash,
        teaching_material_hashes=[s.hash for s in teaching_sources],
        student_copies_hashes=[s.hash for s in student_sources],
        synthetic_responses_used=False,
        notes=[],
    )

    audit_emitter.stage_end(STAGE_ID, status="success")

    return IngestOutputs(
        input_provenance=provenance, evidence_profile=profile, inputs=inputs
    )


# Stage protocol compliance
ingest_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
