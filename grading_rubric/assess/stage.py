"""DR-AS — `assess` stage entry point."""

from __future__ import annotations

from grading_rubric.assess.engines import (
    AmbiguityEngine,
    ApplicabilityEngine,
    DiscriminationEngine,
)
from grading_rubric.assess.models import AssessInputs, AssessOutputs
from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.parsers.models import ParsedInputs

STAGE_ID = "assess"


def assess_stage(
    inputs: ParsedInputs | AssessInputs,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> AssessOutputs:
    audit_emitter.stage_start(STAGE_ID)

    parsed: ParsedInputs = (
        inputs.parsed if isinstance(inputs, AssessInputs) else inputs
    )
    rubric = parsed.starting_rubric or parsed.synthetic_rubric_for_from_scratch
    assert rubric is not None  # at least one is set by parse_inputs

    # DR-AS-15 from-scratch path: a degenerate AssessOutputs with one HIGH
    # APPLICABILITY finding rather than refusing to run.
    if rubric.criteria == []:
        from grading_rubric.models.findings import (
            AssessmentFinding,
            ConfidenceIndicator,
            Measurement,
            QualityCriterion,
            QualityMethod,
            Severity,
        )
        from uuid import uuid4

        finding = AssessmentFinding(
            id=uuid4(),
            criterion=QualityCriterion.APPLICABILITY,
            severity=Severity.HIGH,
            target=None,
            observation="No starting rubric was provided; the propose stage will generate one from scratch.",
            evidence="parse_inputs returned an empty <from-scratch> rubric (SR-IN-05)",
            measurement=Measurement(
                method=QualityMethod.SYNTHETIC_COVERAGE, samples=0, agreement=None
            ),
            confidence=ConfidenceIndicator.from_score(
                0.20, "from-scratch path — no rubric to measure"
            ),
            measured_against_rubric_id=rubric.id,
            iteration=0,
            source_operations=[],
            linked_finding_ids=[],
        )
        # `assess` flips synthetic_responses_used per DR-AS-13 if no real copies.
        evidence = parsed.ingest.evidence_profile.model_copy(
            update={"synthetic_responses_used": True}
        )
        audit_emitter.stage_end(STAGE_ID, status="success")
        return AssessOutputs(
            parsed=parsed,
            rubric_under_assessment=rubric,
            findings=[finding],
            evidence_profile=evidence,
        )

    engines = [AmbiguityEngine(), ApplicabilityEngine(), DiscriminationEngine()]
    findings = []
    for engine in engines:
        findings.extend(
            engine.measure(
                rubric=rubric,
                evidence=parsed.ingest.evidence_profile,
                student_texts=parsed.student_copies_text,
                settings=settings,
                audit_emitter=audit_emitter,
            )
        )

    refined_evidence = parsed.ingest.evidence_profile.model_copy(
        update={
            "synthetic_responses_used": (
                len(parsed.student_copies_text) < settings.assess_min_real_copies
            )
        }
    )

    audit_emitter.stage_end(STAGE_ID, status="success")
    return AssessOutputs(
        parsed=parsed,
        rubric_under_assessment=rubric,
        findings=findings,
        evidence_profile=refined_evidence,
    )


assess_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
