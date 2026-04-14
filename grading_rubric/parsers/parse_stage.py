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
from grading_rubric.parsers.ocr import ClaudeDocumentOcrReader, DocumentOcrReader, is_ocr_candidate
from grading_rubric.parsers.rubric_structuring import GatewayRubricStructurer, RubricStructurer

STAGE_ID = "parse-inputs"


def _try_parse_rubric_json(text: str) -> Rubric | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        # strict=False: JSON naturally represents UUIDs as strings, and the
        # Rubric model uses ConfigDict(strict=True) for construction-time
        # safety. Deserialization from wire JSON needs coercion.
        return Rubric.model_validate(data, strict=False)
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


def _extract_total_points(text: str) -> float:
    """Best-effort extraction of total points from free-text rubric."""
    import re

    # Match patterns like "total = 3 points", "total: 10", "/20", "(X points)"
    for pattern in [
        r"total\s*[=:]\s*(\d+(?:\.\d+)?)\s*(?:points?|pts?)?",
        r"(\d+(?:\.\d+)?)\s*points?\s*total",
        r"/\s*(\d+(?:\.\d+)?)\s*$",
        r"\((\d+(?:\.\d+)?)\s*points?\)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return float(m.group(1))
    return 0.0


def _rubric_from_freetext(text: str) -> Rubric:
    """Build a minimal structured Rubric from free-text guidance.

    Places the entire teacher-provided text into a single criterion so the
    assess engines have something concrete to measure.  The title signals
    that the structure was inferred, not author-provided.
    """
    from grading_rubric.models.rubric import RubricCriterion

    first_line = text.strip().split("\n", 1)[0][:80]
    total = _extract_total_points(text)
    return Rubric(
        id=uuid4(),
        schema_version="1.0.0",
        title=f"teacher-provided rubric: {first_line}",
        total_points=total,
        criteria=[
            RubricCriterion(
                id=uuid4(),
                name="Teacher rubric (free-text)",
                description=text.strip(),
                points=total,
            )
        ],
    )


def parse_inputs_stage(
    inputs: IngestOutputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
    document_reader: DocumentOcrReader | None = None,
    rubric_structurer: RubricStructurer | None = None,
) -> ParsedInputs:
    audit_emitter.stage_start(STAGE_ID)
    reader = document_reader or ClaudeDocumentOcrReader()
    structurer = rubric_structurer or GatewayRubricStructurer()

    def read_role_text(path: Path, *, role: str, context_text: str = "") -> str:
        extracted = read_any_text(path)
        suffix = path.suffix.lower()
        needs_vision = (
            is_ocr_candidate(path)
            and (
                not extracted.strip()
                or suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
                or (role in {"teaching_material", "student_copy"} and suffix == ".pdf")
            )
        )
        if not needs_vision:
            return extracted
        try:
            vision_text = reader.read_text(
                path,
                role=role,
                context_text=context_text,
                extracted_text_hint=extracted,
                settings=settings,
                audit_emitter=audit_emitter,
            )
        except Exception as exc:  # noqa: BLE001 - partial parsing policy
            audit_emitter.record_operation(
                {
                    "stage_id": STAGE_ID,
                    "kind": "ocr_failure",
                    "role": role,
                    "path": str(path),
                    "error": str(exc),
                }
            )
            return extracted
        return vision_text or extracted

    exam_text = read_role_text(inputs.inputs.exam_question_path, role="exam_question")

    teaching_text_parts: list[str] = []
    for p in inputs.inputs.teaching_material_paths:
        teaching_text_parts.append(
            read_role_text(p, role="teaching_material", context_text=exam_text)
        )
    teaching_text = "\n\n---\n\n".join(t for t in teaching_text_parts if t)

    starting_rubric: Rubric | None = None
    raw_text: str | None = None
    if inputs.inputs.starting_rubric_inline is not None:
        starting_rubric = _try_parse_rubric_json(inputs.inputs.starting_rubric_inline)
        if starting_rubric is None and inputs.inputs.starting_rubric_inline.strip():
            raw_text = inputs.inputs.starting_rubric_inline
            try:
                starting_rubric = structurer.structure_rubric(
                    raw_text,
                    exam_question_text=exam_text,
                    teaching_material_text=teaching_text,
                    settings=settings,
                    audit_emitter=audit_emitter,
                )
            except Exception as exc:  # noqa: BLE001 - parse keeps a robust fallback
                audit_emitter.record_operation(
                    {
                        "stage_id": STAGE_ID,
                        "kind": "rubric_structuring_failure",
                        "error": str(exc),
                    }
                )
            if starting_rubric is None:
                starting_rubric = _rubric_from_freetext(raw_text)
    elif inputs.inputs.starting_rubric_path is not None:
        text = read_role_text(
            inputs.inputs.starting_rubric_path,
            role="starting_rubric",
            context_text=exam_text,
        )
        starting_rubric = _try_parse_rubric_json(text)
        if starting_rubric is None and text.strip():
            raw_text = text
            try:
                starting_rubric = structurer.structure_rubric(
                    raw_text,
                    exam_question_text=exam_text,
                    teaching_material_text=teaching_text,
                    settings=settings,
                    audit_emitter=audit_emitter,
                )
            except Exception as exc:  # noqa: BLE001 - parse keeps a robust fallback
                audit_emitter.record_operation(
                    {
                        "stage_id": STAGE_ID,
                        "kind": "rubric_structuring_failure",
                        "path": str(inputs.inputs.starting_rubric_path),
                        "error": str(exc),
                    }
                )
            if starting_rubric is None:
                starting_rubric = _rubric_from_freetext(raw_text)

    synthetic_rubric: Rubric | None = None
    if starting_rubric is None:
        synthetic_rubric = _empty_rubric(title="<from-scratch>")

    student_texts: list[str] = []
    for p in inputs.inputs.student_copy_paths:
        student_texts.append(read_role_text(p, role="student_copy", context_text=exam_text))

    audit_emitter.stage_end(STAGE_ID, status="success")

    return ParsedInputs(
        ingest=inputs,
        exam_question_text=exam_text,
        teaching_material_text=teaching_text,
        starting_rubric=starting_rubric,
        starting_rubric_raw_text=raw_text,
        synthetic_rubric_for_from_scratch=synthetic_rubric,
        student_copies_text=student_texts,
    )


parse_inputs_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
