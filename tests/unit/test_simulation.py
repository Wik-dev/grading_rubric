from __future__ import annotations

import pytest

from grading_rubric.assess.engines import (
    AmbiguityEngine,
    ApplicabilityEngine,
    DiscriminationEngine,
    scores_from_simulation,
)
from grading_rubric.assess.simulation import (
    CriterionGradeEntry,
    PairwiseComparisonEntry,
    ResponseSource,
    SimulationEvidence,
    SimulationResponse,
    _build_criterion_path_index,
    _require_llm,
    _stratified_pair_indices,
    run_grader_simulation,
)
from grading_rubric.audit.emitter import NullEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.backends import StubBackend
from grading_rubric.gateway.gateway import Gateway
from grading_rubric.models.findings import QualityCriterion, QualityMethod

from tests.conftest import CRIT_A_ID, CRIT_B_ID, RUBRIC_ID


def _settings() -> Settings:
    return Settings(llm_backend="stub", llm_model_pinned="stub-test-model")


def _sim(minimal_rubric) -> SimulationEvidence:
    index = _build_criterion_path_index(minimal_rubric)
    crit_a = str(CRIT_A_ID)
    crit_b = str(CRIT_B_ID)
    return SimulationEvidence(
        rubric_id=RUBRIC_ID,
        response_set=[
            SimulationResponse(
                text="weak answer",
                source=ResponseSource.SYNTHETIC,
                quality_tier="weak",
            ),
            SimulationResponse(
                text="strong answer",
                source=ResponseSource.SYNTHETIC,
                quality_tier="strong",
            ),
        ],
        personas_used=["strict", "lenient"],
        criterion_path_index=index,
        criterion_ids=list(index.keys()),
        grade_entries=[
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=0,
                persona_idx=0,
                grade=0.00,
                justification="strict floor because the criterion does not fit",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=0,
                persona_idx=1,
                grade=1.00,
                justification="lenient ceiling because the criterion might fit",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=1,
                persona_idx=0,
                grade=0.85,
                justification="strong",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=1,
                persona_idx=1,
                grade=0.90,
                justification="strong",
            ),
            CriterionGradeEntry(
                criterion_id=crit_b,
                response_idx=0,
                persona_idx=0,
                grade=0.30,
                justification="strict midscale reading",
            ),
            CriterionGradeEntry(
                criterion_id=crit_b,
                response_idx=0,
                persona_idx=1,
                grade=0.70,
                justification="lenient midscale reading",
            ),
            CriterionGradeEntry(
                criterion_id=crit_b,
                response_idx=1,
                persona_idx=0,
                grade=0.55,
                justification="flat",
            ),
            CriterionGradeEntry(
                criterion_id=crit_b,
                response_idx=1,
                persona_idx=1,
                grade=0.55,
                justification="flat",
            ),
        ],
        pairwise_results=[
            PairwiseComparisonEntry(
                response_a_idx=0,
                response_b_idx=1,
                winner="B",
                confidence=0.9,
                reason="strong is better but criterion scores are flat",
                ambiguity_attributed=True,
                affected_criterion_ids=[crit_b],
            )
        ],
    )


def test_require_llm_fails_on_stub() -> None:
    with pytest.raises(RuntimeError, match="requires a real LLM backend"):
        _require_llm(_settings())


def test_ambiguity_from_simulation(minimal_rubric) -> None:
    findings = AmbiguityEngine().measure_from_simulation(
        _sim(minimal_rubric), rubric=minimal_rubric, settings=_settings()
    )
    assert any(f.criterion == QualityCriterion.AMBIGUITY for f in findings)
    assert all(f.measurement.method == QualityMethod.LLM_PANEL_AGREEMENT for f in findings)


def test_applicability_from_simulation(minimal_rubric) -> None:
    findings = ApplicabilityEngine().measure_from_simulation(
        _sim(minimal_rubric), rubric=minimal_rubric, settings=_settings()
    )
    assert any("applicability gap" in f.observation for f in findings)
    assert all(f.measurement.method == QualityMethod.SYNTHETIC_COVERAGE for f in findings)


def test_discrimination_from_simulation(minimal_rubric) -> None:
    findings = DiscriminationEngine().measure_from_simulation(
        _sim(minimal_rubric), rubric=minimal_rubric, settings=_settings()
    )
    assert any(f.criterion == QualityCriterion.DISCRIMINATION_POWER for f in findings)
    assert any(f.criterion == QualityCriterion.AMBIGUITY for f in findings)


def test_scores_from_simulation(minimal_rubric) -> None:
    scores = scores_from_simulation(_sim(minimal_rubric), rubric=minimal_rubric, settings=_settings())
    assert {s.criterion for s in scores} == set(QualityCriterion)
    assert all(s.method == QualityMethod.GRADER_SIMULATION for s in scores)


def test_pairwise_winner_with_near_equal_scores_lowers_discrimination(minimal_rubric) -> None:
    score = next(
        s
        for s in scores_from_simulation(_sim(minimal_rubric), rubric=minimal_rubric, settings=_settings())
        if s.criterion == QualityCriterion.DISCRIMINATION_POWER
    )
    assert score.score < 0.5


def test_ambiguity_weights_borderline_responses_above_trivial_agreement(minimal_rubric) -> None:
    index = _build_criterion_path_index(minimal_rubric)
    crit_a = str(CRIT_A_ID)
    responses = [
        SimulationResponse(
            text=f"perfect {idx}",
            source=ResponseSource.SYNTHETIC,
            quality_tier="excellent",
            intended_score=0.95,
        )
        for idx in range(8)
    ]
    responses.append(
        SimulationResponse(
            text="borderline",
            source=ResponseSource.SYNTHETIC,
            quality_tier="average",
            intended_score=0.55,
        )
    )
    grade_entries = [
        CriterionGradeEntry(
            criterion_id=crit_a,
            response_idx=idx,
            persona_idx=persona_idx,
            grade=1.0,
            justification="clearly complete",
        )
        for idx in range(8)
        for persona_idx in range(2)
    ]
    grade_entries.extend(
        [
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=8,
                persona_idx=0,
                grade=0.30,
                justification="strict midscale boundary reading",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=8,
                persona_idx=1,
                grade=0.70,
                justification="lenient midscale boundary reading",
            ),
        ]
    )
    sim = SimulationEvidence(
        rubric_id=RUBRIC_ID,
        response_set=responses,
        personas_used=["strict", "lenient"],
        criterion_path_index=index,
        criterion_ids=[crit_a],
        grade_entries=grade_entries,
    )

    score = next(
        s
        for s in scores_from_simulation(sim, rubric=minimal_rubric, settings=_settings())
        if s.criterion == QualityCriterion.AMBIGUITY
    )
    assert score.score < 0.40


def test_ambiguity_score_low_confidence_without_midscale_responses(minimal_rubric) -> None:
    index = _build_criterion_path_index(minimal_rubric)
    crit_a = str(CRIT_A_ID)
    sim = SimulationEvidence(
        rubric_id=RUBRIC_ID,
        response_set=[
            SimulationResponse(
                text=f"perfect {idx}",
                source=ResponseSource.SYNTHETIC,
                quality_tier="excellent",
                intended_score=0.95,
            )
            for idx in range(5)
        ],
        personas_used=["strict", "generous"],
        criterion_path_index=index,
        criterion_ids=[crit_a],
        grade_entries=[
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=response_idx,
                persona_idx=persona_idx,
                grade=1.0,
                justification="clear full credit",
            )
            for response_idx in range(5)
            for persona_idx in range(2)
        ],
    )

    score = next(
        s
        for s in scores_from_simulation(sim, rubric=minimal_rubric, settings=_settings())
        if s.criterion == QualityCriterion.AMBIGUITY
    )

    assert score.score < 1.0
    assert score.confidence.level.value == "low"
    assert "fewer than 3 midscale responses" in score.confidence.rationale


def test_bimodal_edge_disagreement_counts_as_applicability_not_ambiguity(minimal_rubric) -> None:
    index = _build_criterion_path_index(minimal_rubric)
    crit_a = str(CRIT_A_ID)
    sim = SimulationEvidence(
        rubric_id=RUBRIC_ID,
        response_set=[
            SimulationResponse(text="applicable borderline", source=ResponseSource.REAL),
            SimulationResponse(text="criterion does not fit", source=ResponseSource.REAL),
        ],
        personas_used=["strict", "lenient"],
        criterion_path_index=index,
        criterion_ids=[crit_a],
        grade_entries=[
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=0,
                persona_idx=0,
                grade=0.50,
                justification="same applicable grade",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=0,
                persona_idx=1,
                grade=0.50,
                justification="same applicable grade",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=1,
                persona_idx=0,
                grade=0.0,
                justification="guessing because criterion does not fit",
            ),
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=1,
                persona_idx=1,
                grade=1.0,
                justification="different guess because criterion does not fit",
            ),
        ],
    )

    scores = {
        s.criterion: s
        for s in scores_from_simulation(sim, rubric=minimal_rubric, settings=_settings())
    }

    assert scores[QualityCriterion.AMBIGUITY].score == 0.75
    assert scores[QualityCriterion.AMBIGUITY].confidence.level.value == "low"
    assert scores[QualityCriterion.APPLICABILITY].score < 0.75


def test_synthetic_ceiling_effect_caps_discrimination(minimal_rubric) -> None:
    index = _build_criterion_path_index(minimal_rubric)
    crit_a = str(CRIT_A_ID)
    specs = [
        ("very_weak", 0.10, 0.20),
        ("below_average", 0.40, 0.95),
        ("average", 0.55, 0.95),
        ("excellent", 0.95, 1.00),
    ]
    sim = SimulationEvidence(
        rubric_id=RUBRIC_ID,
        response_set=[
            SimulationResponse(
                text=tier,
                source=ResponseSource.SYNTHETIC,
                quality_tier=tier,
                intended_score=intended,
            )
            for tier, intended, _actual in specs
        ],
        personas_used=["strict", "lenient"],
        criterion_path_index=index,
        criterion_ids=[crit_a],
        grade_entries=[
            CriterionGradeEntry(
                criterion_id=crit_a,
                response_idx=response_idx,
                persona_idx=persona_idx,
                grade=actual,
                justification="calibrated trace",
            )
            for response_idx, (_tier, _intended, actual) in enumerate(specs)
            for persona_idx in range(2)
        ],
    )

    score = next(
        s
        for s in scores_from_simulation(sim, rubric=minimal_rubric, settings=_settings())
        if s.criterion == QualityCriterion.DISCRIMINATION_POWER
    )
    assert score.score <= 0.60


def test_pairwise_sampling_is_stratified_not_response_zero_prefix() -> None:
    responses = [
        SimulationResponse(
            text=tier,
            source=ResponseSource.SYNTHETIC,
            quality_tier=tier,
            intended_score=intended,
        )
        for tier, intended in [
            ("very_weak", 0.10),
            ("weak", 0.25),
            ("below_average", 0.40),
            ("average", 0.55),
            ("above_average", 0.70),
            ("strong", 0.85),
            ("excellent", 0.95),
        ]
    ]

    pairs = _stratified_pair_indices(responses, 4)

    assert len(pairs) == 4
    assert any(a > 0 for a, _b in pairs)
    assert (2, 3) in pairs


def test_run_grader_simulation_with_injected_gateway(minimal_rubric) -> None:
    settings = Settings(
        llm_backend="stub",
        llm_model_pinned="stub-test-model",
        assess_target_response_count=1,
        assess_panel_size=1,
        assess_pairwise_sample_size=0,
    )
    gateway = Gateway(
        backend=StubBackend(
            canned_responses=[
                {
                    "grades": [
                        {
                            "criterion_path": [str(CRIT_A_ID)],
                            "grade": 0.5,
                            "justification": "partial",
                        },
                        {
                            "criterion_path": [str(CRIT_B_ID)],
                            "grade": 0.8,
                            "justification": "mostly complete",
                        },
                    ]
                }
            ]
        )
    )
    emitter = NullEmitter()
    sim = run_grader_simulation(
        minimal_rubric,
        "exam",
        "",
        ["student answer"],
        settings=settings,
        audit_emitter=emitter,
        gateway=gateway,
        stage_id="score",
    )
    assert len(sim.grade_entries) == 2
    assert sim.grade_entries[0].justification == "partial"
    assert all(
        event.stage_id == "score"
        for event in emitter.events
        if event.event_kind == "operation"
    )
