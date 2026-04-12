"""DR-SCR-05 — `train_scorer` train-button stub.

The v1 deliverable does not actually train any model. This callable is the
build-time wiring that makes the *train button* real per CLAUDE.md § 6 #5:
it validates inputs, emits one operation event with status `skipped` and
error code `STUB_NOT_TRAINED`, and writes a placeholder artefact file. It
does **not** call `gateway.measure(...)` and consumes no LLM tokens.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.audit.hashing import canonical_json, hash_text
from grading_rubric.config.settings import Settings
from grading_rubric.scorer.models import TrainedScorerArtefact, TrainingEvidence

STAGE_ID = "train-scorer"
SCORER_ID = "trained_model.v0"


def train_scorer(
    training_evidence: TrainingEvidence,
    *,
    settings: Settings,
    audit_emitter: AuditEmitter,
    artefact_path: Path,
) -> TrainedScorerArtefact:
    audit_emitter.stage_start(STAGE_ID)

    inputs_hash = hash_text(canonical_json(training_evidence.model_dump(mode="json")))
    training_run_id = str(uuid4())

    audit_emitter.record_operation(
        {
            "stage_id": STAGE_ID,
            "operation_id": str(uuid4()),
            "kind": "ml_inference",
            "status": "skipped",
            "details_kind": "ml_inference",
            "started_at": datetime.now(UTC).isoformat(),
            "ended_at": datetime.now(UTC).isoformat(),
            "error": {
                "code": "STUB_NOT_TRAINED",
                "message": (
                    "train_scorer is a stub in v1: the train-button "
                    "capability is wired end-to-end but no model is fit "
                    "for this delivery (CLAUDE.md § 6 #5)."
                ),
            },
            "details": {
                "scorer_id": SCORER_ID,
                "training_run_id": training_run_id,
                "inputs_hash": inputs_hash,
            },
        }
    )

    placeholder = {
        "scorer_id": SCORER_ID,
        "training_run_id": training_run_id,
        "inputs_hash": inputs_hash,
        "stub_marker": "STUB_NOT_TRAINED",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    artefact_path.parent.mkdir(parents=True, exist_ok=True)
    artefact_path.write_text(json.dumps(placeholder, indent=2), encoding="utf-8")

    audit_emitter.stage_end(STAGE_ID, status="skipped")
    return TrainedScorerArtefact(
        artefact_path=artefact_path,
        training_run_id=training_run_id,
        scorer_id=SCORER_ID,
        metrics={},
    )


train_scorer.stage_id = STAGE_ID  # type: ignore[attr-defined]
