"""Unit tests for stage-level contracts that do not require real LLM calls."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from grading_rubric.assess.llm_schemas import SynthesizedResponseSet
from grading_rubric.assess.stage import assess_stage
from grading_rubric.audit.emitter import NullEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.models.audit import InputProvenance, InputSource, InputSourceKind
from grading_rubric.models.findings import QualityCriterion
from grading_rubric.models.rubric import EvidenceProfile, Rubric, RubricCriterion
from grading_rubric.parsers.models import IngestInputs, IngestOutputs, ParsedInputs
from grading_rubric.parsers.parse_stage import parse_inputs_stage

from tests.conftest import RUBRIC_ID


def _stub_settings() -> Settings:
    return Settings(llm_backend="stub", llm_model_pinned="stub-test-model")


def _evidence() -> EvidenceProfile:
    return EvidenceProfile(
        starting_rubric_present=True,
        exam_question_present=True,
        teaching_material_present=False,
        student_copies_present=False,
        synthetic_responses_used=True,
    )


def _parsed(rubric: Rubric | None) -> ParsedInputs:
    ingest = IngestOutputs(
        input_provenance=InputProvenance(
            exam_question=InputSource(
                kind=InputSourceKind.INLINE_TEXT,
                path=None,
                marker="<inline:exam>",
                hash="a" * 64,
            ),
            teaching_material=[],
            starting_rubric=None,
            student_copies=[],
        ),
        evidence_profile=_evidence(),
        inputs=IngestInputs(exam_question_path=Path("/dev/null")),
    )
    return ParsedInputs(
        ingest=ingest,
        exam_question_text="Describe the bad actors strategy.",
        teaching_material_text="",
        starting_rubric=rubric,
        starting_rubric_raw_text=None,
        synthetic_rubric_for_from_scratch=(
            Rubric(
                id=uuid4(),
                schema_version="1.0.0",
                title="<from-scratch>",
                total_points=0.0,
                criteria=[],
            )
            if rubric is None
            else None
        ),
        student_copies_text=[],
    )


def test_assess_requires_llm_for_existing_rubric(minimal_rubric) -> None:
    with pytest.raises(RuntimeError, match="grader simulation requires"):
        assess_stage(_parsed(minimal_rubric), settings=_stub_settings(), audit_emitter=NullEmitter())


def test_assess_from_scratch_skips_simulation() -> None:
    result = assess_stage(_parsed(None), settings=_stub_settings(), audit_emitter=NullEmitter())
    assert result.rubric_under_assessment.criteria == []
    assert result.quality_scores == []
    assert "simulation cannot run" in result.simulation_summary
    assert len(result.findings) == 1
    assert result.findings[0].criterion == QualityCriterion.APPLICABILITY


class _FakeDocumentReader:
    def __init__(self) -> None:
        self.calls = []

    def read_text(
        self,
        path: Path,
        *,
        role: str,
        context_text: str,
        extracted_text_hint: str,
        settings: Settings,
        audit_emitter: NullEmitter,
    ) -> str:
        self.calls.append(
            {
                "path": path,
                "role": role,
                "context_text": context_text,
                "extracted_text_hint": extracted_text_hint,
            }
        )
        return f"vision text for {role}"


class _FakeRubricStructurer:
    def __init__(self, rubric: Rubric | None) -> None:
        self.rubric = rubric
        self.calls = []

    def structure_rubric(
        self,
        text: str,
        *,
        exam_question_text: str,
        teaching_material_text: str,
        settings: Settings,
        audit_emitter: NullEmitter,
    ) -> Rubric | None:
        self.calls.append(
            {
                "text": text,
                "exam_question_text": exam_question_text,
                "teaching_material_text": teaching_material_text,
            }
        )
        return self.rubric


def _ingest_outputs_for_parse(
    exam: Path,
    *,
    teaching: list[Path] | None = None,
    starting_rubric: Path | None = None,
    student_copies: list[Path] | None = None,
) -> IngestOutputs:
    return IngestOutputs(
        input_provenance=InputProvenance(
            exam_question=InputSource(
                kind=InputSourceKind.FILE,
                path=str(exam),
                marker=None,
                hash="a" * 64,
            ),
            teaching_material=[],
            starting_rubric=None,
            student_copies=[],
        ),
        evidence_profile=_evidence(),
        inputs=IngestInputs(
            exam_question_path=exam,
            teaching_material_paths=teaching or [],
            starting_rubric_path=starting_rubric,
            student_copy_paths=student_copies or [],
        ),
    )


def test_parse_uses_vision_for_teaching_material_pdf_even_with_text_layer(
    tmp_path: Path,
) -> None:
    exam = tmp_path / "exam.txt"
    teaching = tmp_path / "teaching.pdf"
    exam.write_text("exam text", encoding="utf-8")
    teaching.write_bytes(b"%PDF text layer")
    reader = _FakeDocumentReader()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "grading_rubric.parsers.parse_stage.read_any_text",
            lambda path: "diagram text layer" if path == teaching else "exam text",
        )
        parsed = parse_inputs_stage(
            _ingest_outputs_for_parse(exam, teaching=[teaching]),
            settings=_stub_settings(),
            audit_emitter=NullEmitter(),
            document_reader=reader,
        )

    assert parsed.teaching_material_text == "vision text for teaching_material"
    assert reader.calls[0]["role"] == "teaching_material"
    assert reader.calls[0]["extracted_text_hint"] == "diagram text layer"


def test_parse_uses_vision_for_textless_student_copy_pdf(tmp_path: Path) -> None:
    exam = tmp_path / "exam.txt"
    student = tmp_path / "student.pdf"
    exam.write_text("exam text", encoding="utf-8")
    student.write_bytes(b"%PDF scanned")
    reader = _FakeDocumentReader()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "grading_rubric.parsers.parse_stage.read_any_text",
            lambda path: "" if path == student else "exam text",
        )
        parsed = parse_inputs_stage(
            _ingest_outputs_for_parse(exam, student_copies=[student]),
            settings=_stub_settings(),
            audit_emitter=NullEmitter(),
            document_reader=reader,
        )

    assert parsed.student_copies_text == ["vision text for student_copy"]
    assert reader.calls[0]["role"] == "student_copy"


def test_parse_uses_vision_for_student_copy_pdf_even_with_text_layer(
    tmp_path: Path,
) -> None:
    exam = tmp_path / "exam.txt"
    student = tmp_path / "student.pdf"
    exam.write_text("exam text", encoding="utf-8")
    student.write_bytes(b"%PDF scanned")
    reader = _FakeDocumentReader()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "grading_rubric.parsers.parse_stage.read_any_text",
            lambda path: "garbled text layer" if path == student else "exam text",
        )
        parsed = parse_inputs_stage(
            _ingest_outputs_for_parse(exam, student_copies=[student]),
            settings=_stub_settings(),
            audit_emitter=NullEmitter(),
            document_reader=reader,
        )

    assert parsed.student_copies_text == ["vision text for student_copy"]
    assert reader.calls[0]["role"] == "student_copy"
    assert reader.calls[0]["extracted_text_hint"] == "garbled text layer"


def test_parse_structures_free_text_starting_rubric(tmp_path: Path) -> None:
    exam = tmp_path / "exam.txt"
    rubric_path = tmp_path / "rubric.txt"
    exam.write_text("Describe bad actors.", encoding="utf-8")
    rubric_path.write_text(
        "3 points total: 0.5 points each for category match and 0.5 points each "
        "for harmful impact across 3 actions.",
        encoding="utf-8",
    )
    structured = Rubric(
        id=uuid4(),
        schema_version="1.0.0",
        title="Structured rubric",
        total_points=3.0,
        criteria=[
            RubricCriterion(
                id=uuid4(),
                name="Category correspondence",
                description="Actions match chosen motivation categories.",
                points=1.5,
            ),
            RubricCriterion(
                id=uuid4(),
                name="Harmful impact",
                description="Actions explain concrete stakeholder harm.",
                points=1.5,
            ),
        ],
    )
    structurer = _FakeRubricStructurer(structured)

    parsed = parse_inputs_stage(
        _ingest_outputs_for_parse(exam, starting_rubric=rubric_path),
        settings=_stub_settings(),
        audit_emitter=NullEmitter(),
        rubric_structurer=structurer,
    )

    assert parsed.starting_rubric == structured
    assert parsed.starting_rubric_raw_text == rubric_path.read_text(encoding="utf-8")
    assert [c.name for c in parsed.starting_rubric.criteria] == [
        "Category correspondence",
        "Harmful impact",
    ]
    assert structurer.calls[0]["exam_question_text"] == "Describe bad actors."


def test_parse_free_text_rubric_falls_back_when_structuring_returns_none(
    tmp_path: Path,
) -> None:
    exam = tmp_path / "exam.txt"
    rubric_path = tmp_path / "rubric.txt"
    exam.write_text("Describe bad actors.", encoding="utf-8")
    rubric_path.write_text("Rubric: 3 points total for a complete answer.", encoding="utf-8")
    structurer = _FakeRubricStructurer(None)

    parsed = parse_inputs_stage(
        _ingest_outputs_for_parse(exam, starting_rubric=rubric_path),
        settings=_stub_settings(),
        audit_emitter=NullEmitter(),
        rubric_structurer=structurer,
    )

    assert parsed.starting_rubric is not None
    assert len(parsed.starting_rubric.criteria) == 1
    assert parsed.starting_rubric.criteria[0].name == "Teacher rubric (free-text)"


def test_synthesis_prompt_requires_wrong_category_sentinel() -> None:
    prompt = Path(
        "grading_rubric/gateway/prompts/assess_synthesize_responses.md"
    ).read_text(encoding="utf-8")

    assert "wrong_category_match" in prompt
    assert "Required category-mismatch sentinel" in prompt
    assert "category X" in prompt
    assert "category Y" in prompt
    assert "SmartCity" not in prompt


def test_synthesis_prompt_forces_below_average_degradation() -> None:
    prompt = Path(
        "grading_rubric/gateway/prompts/assess_synthesize_responses.md"
    ).read_text(encoding="utf-8")

    assert "`below_average` should likely grade in 0.30-0.50" in prompt
    assert "If it would grade above 0.60, it is too competent" in prompt
    assert "Reject and rewrite any `weak`, `below_average`, or `average`" in prompt
    assert "For `below_average`, target the shape of an answer" in prompt
    assert "one item must be clearly flawed" in prompt


def test_synthesis_prompt_inverts_length_by_quality() -> None:
    prompt = Path(
        "grading_rubric/gateway/prompts/assess_synthesize_responses.md"
    ).read_text(encoding="utf-8")

    assert "`weak`: 150-250 words" in prompt
    assert "`below_average`: 150-250 words" in prompt
    assert "`excellent`: 80-150 words" in prompt
    assert "Do not let response length increase with quality" in prompt
    assert "run-on sentences" in prompt
    assert "maybe" in prompt
    assert "I think" in prompt
    assert "it could be" in prompt


def test_synthesis_schema_accepts_auditable_self_check_notes() -> None:
    synthesized = SynthesizedResponseSet(
        responses=[],
        self_check_notes="weak response rewritten after calibration check",
    )

    assert synthesized.self_check_notes == "weak response rewritten after calibration check"
