"""SR-OUT-01..05 — `render` stage entry point.

Builds the final `ExplainedRubricFile` from the `score` stage outputs and
writes it to disk under DR-DAT-08's atomic-write discipline (write to
`<output>.tmp`, fsync, rename). The explanation is constructed from the
findings + proposed-changes graph: each `QualityCriterion` gets exactly
one `CriterionSection` whose `unaddressed_finding_refs` is computed
post-application per DR-IM-08.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.audit.hashing import _canonical
from grading_rubric.config.settings import Settings
from grading_rubric.models.deliverable import ExplainedRubricFile
from grading_rubric.models.explanation import CriterionSection, Explanation
from grading_rubric.models.findings import QualityCriterion
from grading_rubric.models.proposed_change import ApplicationStatus
from grading_rubric.scorer.models import ScoreOutputs

STAGE_ID = "render"


class RenderOutputs(BaseModel):
    model_config = ConfigDict(strict=True)

    output_path: Path
    explained_rubric: ExplainedRubricFile


def _build_explanation(scored: ScoreOutputs) -> Explanation:
    """Assemble the per-criterion sections + post-application unaddressed refs.

    DR-IM-08: a finding is *unaddressed* iff no APPLIED change references
    it via `source_findings`. Computed post-application so a finding with
    multiple drafts where one is grounding-dropped (or canonical-order
    dropped) is not over-marked.
    """

    findings = scored.proposed.findings
    changes = scored.proposed.proposed_changes

    applied_finding_refs: set[UUID] = set()
    for c in changes:
        if c.application_status == ApplicationStatus.APPLIED:
            applied_finding_refs.update(c.source_findings)

    sections: dict[QualityCriterion, CriterionSection] = {}
    for criterion in QualityCriterion:
        crit_findings = [f for f in findings if f.criterion == criterion]
        crit_finding_ids = [f.id for f in crit_findings]

        crit_changes = [c for c in changes if c.primary_criterion == criterion]
        crit_change_ids = [c.id for c in crit_changes]

        unaddressed = [
            f.id for f in crit_findings if f.id not in applied_finding_refs
        ]

        if not crit_findings and not crit_changes:
            narrative = (
                f"No issues of {criterion.value} were found in the rubric; "
                f"no changes were proposed for this criterion."
            )
        else:
            applied_count = sum(
                1
                for c in crit_changes
                if c.application_status == ApplicationStatus.APPLIED
            )
            narrative = (
                f"{len(crit_findings)} finding(s) of {criterion.value}; "
                f"{applied_count} applied change(s); "
                f"{len(unaddressed)} unaddressed finding(s) carried forward "
                f"to the explanation."
            )

        sections[criterion] = CriterionSection(
            criterion=criterion,
            finding_refs=crit_finding_ids,
            change_refs=crit_change_ids,
            unaddressed_finding_refs=unaddressed,
            narrative=narrative,
        )

    summary = (
        f"Assessed the rubric against three quality criteria "
        f"({', '.join(c.value for c in QualityCriterion)}); "
        f"produced {len(findings)} finding(s) and {len(changes)} "
        f"proposed change(s)."
    )
    return Explanation(summary=summary, by_criterion=sections, cross_cutting=[])


def _atomic_write_json(path: Path, payload: dict) -> None:
    """DR-DAT-08 atomic write: tmp file + fsync + rename."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(_canonical(payload), indent=2, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def render_stage(
    inputs: ScoreOutputs,
    *,
    output_path: Path,
    run_id: UUID | None = None,
    started_at: datetime | None = None,
    settings: Settings,
    audit_emitter: AuditEmitter,
) -> RenderOutputs:
    audit_emitter.stage_start(STAGE_ID)

    proposed = inputs.proposed
    parsed = proposed.assessed.parsed

    explanation = _build_explanation(inputs)

    explained = ExplainedRubricFile(
        schema_version=settings.deliverable_schema_version,
        generated_at=started_at or datetime.now(UTC),
        run_id=run_id or uuid4(),
        starting_rubric=proposed.starting_rubric,
        improved_rubric=proposed.improved_rubric,
        findings=proposed.findings,
        proposed_changes=proposed.proposed_changes,
        explanation=explanation,
        quality_scores=inputs.quality_scores,
        previous_quality_scores=None,
        evidence_profile=proposed.assessed.evidence_profile,
    )

    _atomic_write_json(output_path, explained.model_dump(mode="json"))

    audit_emitter.stage_end(STAGE_ID, status="success")
    return RenderOutputs(output_path=output_path, explained_rubric=explained)


render_stage.stage_id = STAGE_ID  # type: ignore[attr-defined]
