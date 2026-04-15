"""E2E tests for the shared grader-simulation pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from grading_rubric.audit.emitter import NullEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.backends import RawMessageResponse
from grading_rubric.models.deliverable import ExplainedRubricFile
from grading_rubric.models.findings import QualityCriterion, QualityMethod
from grading_rubric.models.proposed_change import ApplicationStatus
from grading_rubric.orchestrator.pipeline import PipelineInputs, run_pipeline

from tests.conftest import CRIT_A_ID, CRIT_B_ID, LEVEL_A1_ID, LEVEL_A2_ID, RUBRIC_ID


class SmartStubBackend:
    """Schema-dispatching backend for the simulation path.

    The responses model the real architecture: the LLM grades answers under the
    teacher rubric and proposes edits. It never returns direct ambiguity,
    applicability, discrimination, or score judgments.
    """

    name = "smart_stub"

    def __init__(self) -> None:
        self._call_count: dict[str, int] = {}

    def create_message(
        self,
        *,
        system: str | None,
        user: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        model: str,
        temperature: float,
        timeout_seconds: int,
        max_rate_limit_retries: int,
        attachments: list | None = None,
    ) -> RawMessageResponse:
        self._call_count[tool_name] = self._call_count.get(tool_name, 0) + 1
        payload = self._dispatch(tool_name, self._call_count[tool_name], user)
        return RawMessageResponse(
            tool_input=payload,
            tokens_in=100,
            tokens_out=200,
            rate_limit_retries=0,
        )

    @staticmethod
    def _criterion_ids(prompt: str) -> list[str]:
        ids = re.findall(r"criterion_id:\s*([0-9a-f-]{36}(?:>[0-9a-f-]{36})*)", prompt)
        if ids:
            return list(dict.fromkeys(ids))
        ids = re.findall(r'"criterion_path"\s*:\s*\[\s*"([0-9a-f-]{36})"', prompt)
        return list(dict.fromkeys(ids)) or [str(CRIT_A_ID), str(CRIT_B_ID)]

    @staticmethod
    def _finding_ids(prompt: str) -> list[str]:
        findings_start = prompt.find("## Assessment findings")
        findings_text = prompt[findings_start:] if findings_start >= 0 else prompt
        return re.findall(r'"id"\s*:\s*"([0-9a-f-]{36})"', findings_text)

    def _dispatch(self, tool_name: str, call_number: int, user_prompt: str) -> dict:
        if tool_name == "SynthesizedResponseSet":
            return {
                "responses": [
                    {
                        "tier": tier,
                        "text": f"{tier} synthetic answer about stakeholders and adversarial actors.",
                        "intended_score": score,
                    }
                    for tier, score in [
                        ("weak", 0.2),
                        ("average", 0.5),
                        ("strong", 0.9),
                        ("weak", 0.25),
                        ("average", 0.55),
                        ("strong", 0.85),
                        ("weak", 0.15),
                    ]
                ],
                "self_check_notes": "Stub synthetic responses span weak, average, and strong tiers.",
            }

        if tool_name == "OcrDocumentResult":
            return {
                "text": "OCR transcript from attached document.",
                "confidence": 0.9,
                "unreadable_regions": [],
                "notes": "",
            }

        if tool_name == "GradingResult":
            crit_ids = self._criterion_ids(user_prompt)
            persona_offset = [0.0, 0.35, 0.10, 0.45][call_number % 4]
            response_band = (call_number // 4) % 3
            base = [0.25, 0.55, 0.75][response_band]
            grades = []
            for idx, criterion_id in enumerate(crit_ids[:2]):
                grade = max(0.0, min(1.0, base + persona_offset - (0.05 * idx)))
                grades.append(
                    {
                        "criterion_path": criterion_id.split(">"),
                        "grade": grade,
                        "justification": (
                            f"Persona {call_number} assigned {grade:.2f} from the rubric evidence."
                        ),
                    }
                )
            return {"grades": grades}

        if tool_name == "PairwiseVerdict":
            return {
                "winner": "A" if call_number % 2 else "B",
                "confidence": 0.70,
                "reason": "One answer gives more specific attack vectors, but the rubric scores are near equal.",
                "ambiguity_attributed": True,
                "affected_criterion_ids": [str(CRIT_A_ID)],
            }

        if tool_name == "LlmPlannerOutput":
            finding_ids = self._finding_ids(user_prompt)
            crit_ids = self._criterion_ids(user_prompt)
            if not finding_ids:
                return {"decision": "No grounded finding to change.", "drafts": []}
            return {
                "decision": "Clarify the vague criterion using observable evidence.",
                "drafts": [
                    {
                        "operation": "REPLACE_FIELD",
                        "primary_criterion": "ambiguity",
                        "source_finding_ids": finding_ids[:1],
                        "rationale": "The grader simulation showed disagreement on required evidence.",
                        "confidence_score": 0.85,
                        "payload": {
                            "target": {
                                "criterion_path": crit_ids[0].split(">"),
                                "field": "description",
                            },
                            "before": "Student demonstrates appropriate understanding of supply chain stakeholders",
                            "after": (
                                "Student identifies at least three supply-chain stakeholders "
                                "and explains each stakeholder's role using evidence from the answer."
                            ),
                        },
                    }
                ],
            }

        return {}


def _llm_settings(panel_size: int = 4) -> Settings:
    return Settings(
        llm_backend="anthropic",
        llm_model_pinned="claude-sonnet-4-20250514",
        anthropic_api_key="sk-test-e2e-key",
        assess_llm_backend="anthropic",
        assess_llm_model_pinned="claude-sonnet-4-20250514",
        assess_panel_size=panel_size,
        assess_target_response_count=6,
        assess_pairwise_sample_size=3,
    )


def _write_exam(tmp_path: Path) -> Path:
    path = tmp_path / "exam.txt"
    path.write_text(
        "Describe key supply-chain stakeholders and explain how adversarial actors exploit vulnerabilities.",
        encoding="utf-8",
    )
    return path


def _write_rubric_json(tmp_path: Path) -> Path:
    rubric_data = {
        "id": str(RUBRIC_ID),
        "schema_version": "1.0.0",
        "title": "Supply Chain Security Rubric",
        "total_points": 20.0,
        "criteria": [
            {
                "id": str(CRIT_A_ID),
                "name": "Stakeholder Identification",
                "description": "Student demonstrates appropriate understanding of supply chain stakeholders",
                "points": 10.0,
                "levels": [
                    {
                        "id": str(LEVEL_A1_ID),
                        "label": "Excellent",
                        "descriptor": "Thorough coverage",
                        "points": 10.0,
                    },
                    {
                        "id": str(LEVEL_A2_ID),
                        "label": "Poor",
                        "descriptor": "Minimal coverage",
                        "points": 0.0,
                    },
                ],
            },
            {
                "id": str(CRIT_B_ID),
                "name": "Threat Analysis",
                "description": "Identifies adversarial actors targeting the supply chain",
                "points": 10.0,
                "levels": [
                    {
                        "id": str(uuid4()),
                        "label": "Excellent",
                        "descriptor": "Detailed analysis",
                        "points": 10.0,
                    },
                    {
                        "id": str(uuid4()),
                        "label": "Weak",
                        "descriptor": "Surface-level",
                        "points": 0.0,
                    },
                ],
            },
        ],
    }
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(rubric_data), encoding="utf-8")
    return path


def _write_student_copies(tmp_path: Path) -> list[Path]:
    texts = [
        "Manufacturers, distributors, retailers and end users can each be attacked.",
        "Firmware compromise and counterfeit chips are supply-chain attack vectors.",
        "There are many people involved in making technology products.",
    ]
    paths = []
    for idx, text in enumerate(texts):
        path = tmp_path / f"student_{idx + 1}.txt"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def _load_erf(path: Path) -> ExplainedRubricFile:
    return ExplainedRubricFile.model_validate_json(path.read_text(encoding="utf-8"))


class TestSharedGraderSimulationE2E:
    def test_pipeline_uses_simulation_traces_for_findings_and_scores(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "output.json"
        smart_stub = SmartStubBackend()

        with patch("grading_rubric.gateway.gateway.make_backend", return_value=smart_stub):
            run_pipeline(
                pipeline_inputs=PipelineInputs(
                    exam_question_path=_write_exam(tmp_path),
                    starting_rubric_path=_write_rubric_json(tmp_path),
                    student_copy_paths=_write_student_copies(tmp_path),
                ),
                output_path=out,
                settings=_llm_settings(),
                audit_emitter=NullEmitter(),
            )

        erf = _load_erf(out)

        assert isinstance(erf, ExplainedRubricFile)
        assert len(erf.quality_scores) == 3
        assert erf.previous_quality_scores is not None
        assert {s.criterion for s in erf.quality_scores} == set(QualityCriterion)
        assert all(s.method == QualityMethod.GRADER_SIMULATION for s in erf.quality_scores)
        assert all(s.source_operation_id is not None for s in erf.quality_scores)

        methods = {finding.measurement.method for finding in erf.findings}
        assert QualityMethod.LLM_PANEL_AGREEMENT in methods
        assert QualityMethod.SYNTHETIC_COVERAGE in methods
        assert (
            QualityMethod.PAIRWISE_CONSISTENCY in methods
            or QualityMethod.SCORE_DISTRIBUTION_SEPARATION in methods
        )

        assert len(erf.proposed_changes) >= 1
        assert any(
            change.application_status == ApplicationStatus.APPLIED
            for change in erf.proposed_changes
        )

    def test_no_llm_configuration_fails_clearly(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="grader simulation requires"):
            run_pipeline(
                pipeline_inputs=PipelineInputs(
                    exam_question_path=_write_exam(tmp_path),
                    starting_rubric_path=_write_rubric_json(tmp_path),
                    student_copy_paths=_write_student_copies(tmp_path),
                ),
                output_path=tmp_path / "output.json",
                settings=Settings(llm_backend="stub", llm_model_pinned="stub-test-model"),
                audit_emitter=NullEmitter(),
            )

    def test_synthetic_responses_are_used_when_student_copies_are_absent(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "output.json"
        smart_stub = SmartStubBackend()

        with patch("grading_rubric.gateway.gateway.make_backend", return_value=smart_stub):
            run_pipeline(
                pipeline_inputs=PipelineInputs(
                    exam_question_path=_write_exam(tmp_path),
                    starting_rubric_path=_write_rubric_json(tmp_path),
                ),
                output_path=out,
                settings=_llm_settings(),
                audit_emitter=NullEmitter(),
            )

        erf = _load_erf(out)
        assert erf.evidence_profile.synthetic_responses_used is True
        assert len(erf.findings) >= 1

    def test_artifact_dir_persists_stage_and_simulation_outputs(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "output.json"
        artifact_dir = tmp_path / "artifacts"
        smart_stub = SmartStubBackend()

        with patch("grading_rubric.gateway.gateway.make_backend", return_value=smart_stub):
            run_pipeline(
                pipeline_inputs=PipelineInputs(
                    exam_question_path=_write_exam(tmp_path),
                    starting_rubric_path=_write_rubric_json(tmp_path),
                    student_copy_paths=_write_student_copies(tmp_path),
                ),
                output_path=out,
                settings=_llm_settings(),
                audit_emitter=NullEmitter(),
                artifact_dir=artifact_dir,
            )

        expected = [
            artifact_dir / "ingest" / "inputs.json",
            artifact_dir / "parse-inputs" / "extracted_exam_question.txt",
            artifact_dir / "assess" / "simulation_evidence.json",
            artifact_dir / "assess" / "grade_matrix.json",
            artifact_dir / "assess" / "pairwise_comparisons.json",
            artifact_dir / "assess" / "grade_distribution.json",
            artifact_dir / "propose" / "proposed_changes.json",
            artifact_dir / "score" / "simulation_evidence.json",
            artifact_dir / "score" / "before_after_scores.json",
            artifact_dir / "render" / "final_explained_rubric.json",
        ]
        for path in expected:
            assert path.exists(), path

        assess_responses = json.loads(
            (artifact_dir / "assess" / "responses.json").read_text(encoding="utf-8")
        )
        score_responses = json.loads(
            (artifact_dir / "score" / "responses.json").read_text(encoding="utf-8")
        )
        before_after = json.loads(
            (artifact_dir / "score" / "before_after_scores.json").read_text(
                encoding="utf-8"
            )
        )
        assert assess_responses == score_responses
        assert before_after["same_response_cohort"] is True

        grade_distribution = json.loads(
            (artifact_dir / "assess" / "grade_distribution.json").read_text(
                encoding="utf-8"
            )
        )
        assert grade_distribution["overall"]["count"] > 0
