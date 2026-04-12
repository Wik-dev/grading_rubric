"""DR-IO-04..08 — `parse_inputs` stage.

Reads the role-tagged file (or inline-text) sources from `IngestOutputs`,
extracts text, and produces `ParsedInputs`. The starting-rubric path may be
either (a) a JSON file already conforming to `Rubric` (the structured form),
(b) a free-text rubric the propose stage will treat as guidance only, or
(c) absent — in which case `starting_rubric` is `None` and the propose stage
runs the from-scratch path (DR-IM-01 path 2).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.models.rubric import Rubric
from grading_rubric.parsers.file_io import read_any_text
from grading_rubric.parsers.models import IngestOutputs, ParsedInputs

STAGE_ID = "parse-inputs"


def _try_parse_rubric_json(text: str) -> Rubric | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        return Rubric.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


def _empty_rubric(title: str) -> Rubric:
    return Rubric(
        id=uuid4(),
        schema_version="1.0.0",
        title=title,
        total_points=0.0,
        criteria=[],
    )


def parse_inputs_stage(
    inputs: IngestOutputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> ParsedInputs:
    audit_emitter.stage_start(STAGE_ID)

    exam_text = read_any_text(inputs.inputs.exam_question_path)

    teaching_text_parts: list[str] = []
    for p in inputs.inputs.teaching_material_paths:
        teaching_text_parts.append(read_any_text(p))
    teaching_text = "\n\n---\n\n".join(t for t in teaching_text_parts if t)

    starting_rubric: Rubric | None = None
    if inputs.inputs.starting_rubric_inline is not None:
        starting_rubric = _try_parse_rubric_json(inputs.inputs.starting_rubric_inline)
        # If inline text is not valid JSON, leave the rubric as None and let
        # the propose stage treat the inline text as free-text guidance via
        # the from-scratch path. This is the SR-IN-05 inline form.
    elif inputs.inputs.starting_rubric_path is not None:
        text = read_any_text(inputs.inputs.starting_rubric_path)
        starting_rubric = _try_parse_rubric_json(text)
        # Same fallback for path-based rubrics that aren't structured JSON.

    synthetic_rubric: Rubric | None = None
    if starting_rubric is None:
        synthetic_rubric = _empty_rubric(title="<from-scratch>")

    student_texts: list[str] = []
    for p in inputs.inputs.student_copy_paths:
        student_texts.append(read_any_text(p))

    audit_emitter.stage_end(STAGE_ID, status="success")

    return ParsedInputs(
        ingest=inputs,
        exam_question_text=exam_text,
        teaching_material_text=teaching_text,
        starting_rubric=starting_rubric,
        synthetic_rubric_for_from_scratch=synthetic_rubric,
        student_copies_text=student_texts,
    )


parse_inputs_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
