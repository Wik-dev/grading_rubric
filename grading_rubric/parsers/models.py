"""Stage-local input/output shapes for the `ingest` and `parse_inputs` stages.

Per DR-DAT-01 these live next to the stages that own them, **not** in
`grading_rubric.models`. They are not part of the codegen surface and the SPA
never sees them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from grading_rubric.models.audit import InputProvenance
from grading_rubric.models.rubric import EvidenceProfile, Rubric


class IngestInputs(BaseModel):
    """Raw on-disk inputs handed in by the CLI / orchestrator."""

    model_config = ConfigDict(strict=True)

    exam_question_path: Path
    teaching_material_paths: list[Path] = []
    starting_rubric_path: Path | None = None
    starting_rubric_inline: str | None = None
    student_copy_paths: list[Path] = []


class IngestOutputs(BaseModel):
    """Result of `ingest`: provenance + initial evidence profile.

    The actual file bytes are not embedded; only role-tagged paths/markers and
    SHA-256 digests. Downstream stages re-read the bytes when they need them.
    """

    model_config = ConfigDict(strict=True)

    input_provenance: InputProvenance
    evidence_profile: EvidenceProfile
    inputs: IngestInputs


class ParsedInputs(BaseModel):
    """Result of `parse_inputs`: structured text + an initial rubric.

    `starting_rubric` is `None` for the SR-IN-05 *no starting rubric* form
    (which `assess` then handles via the DR-AS-15 from-scratch path).
    `synthetic_rubric_for_from_scratch` carries a placeholder rubric the
    propose stage uses as the *target* of an `ADD_NODE` sequence; it is the
    same shape as a real `Rubric` but with no criteria.
    """

    model_config = ConfigDict(strict=True)

    ingest: IngestOutputs
    exam_question_text: str
    teaching_material_text: str
    starting_rubric: Rubric | None
    synthetic_rubric_for_from_scratch: Rubric | None
    student_copies_text: list[str] = []
