"""DR-ARC-08 — `grading-rubric-cli` console-script entry point.

Seven subcommands realising the per-stage CLI surface of § 3.10:

  ingest          IngestInputs  JSON → IngestOutputs   JSON
  parse-inputs    IngestOutputs JSON → ParsedInputs    JSON
  assess          ParsedInputs  JSON → AssessOutputs   JSON
  propose         AssessOutputs JSON → ProposeOutputs  JSON
  score           ProposeOutputs JSON → ScoreOutputs   JSON
  render          ScoreOutputs   JSON → ExplainedRubricFile JSON
  run-pipeline    IngestInputs JSON OR --exam-question/--starting-rubric/...
                                    → ExplainedRubricFile JSON

Each per-stage subcommand is a thin shell: read the input JSON, call the
stage callable through the `Stage` protocol, write the output JSON. Per
DR-ARC-09 a single `Settings` is built once at process boot from the
environment and injected into the stage call.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

import click
from pydantic import BaseModel

from grading_rubric.assess.models import AssessOutputs
from grading_rubric.assess.stage import assess_stage
from grading_rubric.audit.emitter import AuditEmitter, JsonLineEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.improve.models import ProposeOutputs
from grading_rubric.improve.stage import propose_stage
from grading_rubric.orchestrator.pipeline import PipelineInputs, run_pipeline
from grading_rubric.output.render_stage import render_stage
from grading_rubric.parsers.ingest_stage import ingest_stage
from grading_rubric.parsers.models import IngestInputs, IngestOutputs, ParsedInputs
from grading_rubric.parsers.parse_stage import parse_inputs_stage
from grading_rubric.scorer.models import ScoreOutputs
from grading_rubric.scorer.score_stage import score_stage

# ── Helpers ──────────────────────────────────────────────────────────────


_M = TypeVar("_M", bound=BaseModel)


def _read_model(path: Path, model_cls: type[_M]) -> _M:
    """Load a Pydantic model from a JSON file using JSON-mode validation.

    JSON-mode validation (`model_validate_json`) accepts the JSON-native
    coercions Pydantic v2 ships (e.g. string → `Path`, ISO-8601 string →
    `datetime`) even under `ConfigDict(strict=True)`, while the Python-mode
    validator on a `dict` would reject them.
    """

    if not path.exists():
        raise click.ClickException(f"input file not found: {path}")
    try:
        return model_cls.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(
            f"failed to parse {model_cls.__name__} from {path}: {exc}"
        ) from exc


def _write_json(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model to disk as JSON (pretty-printed)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        model.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )


def _make_emitter() -> AuditEmitter:
    return JsonLineEmitter(sink=sys.stderr)


class _TeeSink:
    def __init__(self, *sinks) -> None:
        self._sinks = sinks

    def write(self, text: str) -> int:
        for sink in self._sinks:
            sink.write(text)
        return len(text)

    def flush(self) -> None:
        for sink in self._sinks:
            sink.flush()


def _make_artifact_emitter(artifact_dir: Path | None) -> tuple[AuditEmitter, object | None]:
    if artifact_dir is None:
        return _make_emitter(), None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    audit_file = (artifact_dir / "audit.jsonl").open("w", encoding="utf-8")
    return JsonLineEmitter(sink=_TeeSink(sys.stderr, audit_file)), audit_file


def _settings() -> Settings:
    return Settings.from_env()


# ── CLI group ────────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="grading-rubric")
def main() -> None:
    """Grading Rubric Studio — per-stage CLI (DR-ARC-08)."""


# ── 1. ingest ────────────────────────────────────────────────────────────


def _build_inputs_from_root(root: Path) -> IngestInputs:
    """Build ``IngestInputs`` from an ADR-007 directory layout.

    Expected structure::

        root/
          exam_question/      — required, exactly one file
          teaching_material/  — optional, zero or more files
          student_copy/       — optional, zero or more files
          starting_rubric/    — optional, zero or one file
    """

    def _files_in(role: str) -> list[Path]:
        d = root / role
        if not d.is_dir():
            return []
        return sorted(p for p in d.iterdir() if p.is_file())

    # exam_question — required, exactly one
    eq_files = _files_in("exam_question")
    if len(eq_files) == 0:
        raise click.ClickException(
            f"exam_question role is required but {root / 'exam_question'} "
            "contains no files"
        )
    if len(eq_files) > 1:
        raise click.ClickException(
            f"exam_question must contain exactly one file, "
            f"found {len(eq_files)}: {[p.name for p in eq_files]}"
        )

    # starting_rubric — optional, at most one
    sr_files = _files_in("starting_rubric")
    if len(sr_files) > 1:
        raise click.ClickException(
            f"starting_rubric must contain at most one file, "
            f"found {len(sr_files)}: {[p.name for p in sr_files]}"
        )

    return IngestInputs(
        exam_question_path=eq_files[0],
        teaching_material_paths=_files_in("teaching_material"),
        student_copy_paths=_files_in("student_copy"),
        starting_rubric_path=sr_files[0] if sr_files else None,
    )


@main.command("ingest")
@click.option("--input", "input_path", type=click.Path(path_type=Path), default=None)
@click.option("--input-root", "input_root", type=click.Path(path_type=Path), default=None)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_ingest(
    input_path: Path | None,
    input_root: Path | None,
    output_path: Path,
) -> None:
    """Read raw inputs, build InputProvenance + EvidenceProfile."""

    if input_path is not None and input_root is not None:
        raise click.ClickException(
            "--input and --input-root are mutually exclusive"
        )
    if input_path is None and input_root is None:
        raise click.ClickException(
            "either --input or --input-root must be provided"
        )

    if input_path is not None:
        inputs = _read_model(input_path, IngestInputs)
    else:
        assert input_root is not None
        inputs = _build_inputs_from_root(input_root)

    out = ingest_stage(inputs, settings=_settings(), audit_emitter=_make_emitter())
    _write_json(output_path, out)
    click.echo(str(output_path))


# ── 2. parse-inputs ──────────────────────────────────────────────────────


@main.command("parse-inputs")
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_parse_inputs(input_path: Path, output_path: Path) -> None:
    """Extract text from ingested inputs; produce ParsedInputs."""

    inputs = _read_model(input_path, IngestOutputs)
    out = parse_inputs_stage(
        inputs, settings=_settings(), audit_emitter=_make_emitter()
    )
    _write_json(output_path, out)
    click.echo(str(output_path))


# ── 3. assess ────────────────────────────────────────────────────────────


@main.command("assess")
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_assess(input_path: Path, output_path: Path) -> None:
    """Run the three measurement engines, produce AssessOutputs."""

    inputs = _read_model(input_path, ParsedInputs)
    out = assess_stage(inputs, settings=_settings(), audit_emitter=_make_emitter())
    _write_json(output_path, out)
    click.echo(str(output_path))


# ── 4. propose ───────────────────────────────────────────────────────────


@main.command("propose")
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_propose(input_path: Path, output_path: Path) -> None:
    """Run the three-step DR-IM-07 pipeline, produce ProposeOutputs."""

    inputs = _read_model(input_path, AssessOutputs)
    out = propose_stage(inputs, settings=_settings(), audit_emitter=_make_emitter())
    _write_json(output_path, out)
    click.echo(str(output_path))


# ── 5. score ─────────────────────────────────────────────────────────────


@main.command("score")
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_score(input_path: Path, output_path: Path) -> None:
    """Score the improved rubric against the three quality criteria."""

    inputs = _read_model(input_path, ProposeOutputs)
    out = score_stage(inputs, settings=_settings(), audit_emitter=_make_emitter())
    _write_json(output_path, out)
    click.echo(str(output_path))


# ── 6. render ────────────────────────────────────────────────────────────


@main.command("render")
@click.option("--input", "input_path", type=click.Path(path_type=Path), required=True)
@click.option("--output", "output_path", type=click.Path(path_type=Path), required=True)
def cmd_render(input_path: Path, output_path: Path) -> None:
    """Build the ExplainedRubricFile and write it atomically."""

    inputs = _read_model(input_path, ScoreOutputs)
    render_stage(
        inputs,
        output_path=output_path,
        run_id=uuid4(),
        started_at=datetime.now(UTC),
        settings=_settings(),
        audit_emitter=_make_emitter(),
    )
    click.echo(str(output_path))


# ── 7. run-pipeline ──────────────────────────────────────────────────────


@main.command("run-pipeline")
@click.option(
    "--input",
    "input_path",
    type=click.Path(path_type=Path),
    default=None,
    help="JSON file matching IngestInputs (alternative to the path flags).",
)
@click.option("--exam-question", type=click.Path(path_type=Path), default=None)
@click.option(
    "--teaching-material",
    "teaching_material",
    type=click.Path(path_type=Path),
    multiple=True,
)
@click.option("--starting-rubric", type=click.Path(path_type=Path), default=None)
@click.option(
    "--starting-rubric-inline",
    type=str,
    default=None,
    help="Inline starting rubric (JSON or free text). SR-IN-05.",
)
@click.option(
    "--student-copy",
    "student_copy",
    type=click.Path(path_type=Path),
    multiple=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Where the ExplainedRubricFile JSON will be written.",
)
@click.option(
    "--artifact-dir",
    "artifact_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional directory for per-stage artifacts and audit.jsonl.",
)
def cmd_run_pipeline(
    input_path: Path | None,
    exam_question: Path | None,
    teaching_material: tuple[Path, ...],
    starting_rubric: Path | None,
    starting_rubric_inline: str | None,
    student_copy: tuple[Path, ...],
    output_path: Path,
    artifact_dir: Path | None,
) -> None:
    """Chain the six stages in order via the in-process orchestrator (DR-ARC-04)."""

    if input_path is not None:
        pipeline_inputs = _read_model(input_path, PipelineInputs)
    else:
        if exam_question is None:
            raise click.ClickException(
                "either --input or --exam-question must be provided"
            )
        pipeline_inputs = PipelineInputs(
            exam_question_path=exam_question,
            teaching_material_paths=list(teaching_material),
            starting_rubric_path=starting_rubric,
            starting_rubric_inline=starting_rubric_inline,
            student_copy_paths=list(student_copy),
        )

    emitter, audit_file = _make_artifact_emitter(artifact_dir)
    try:
        result = run_pipeline(
            pipeline_inputs=pipeline_inputs,
            output_path=output_path,
            settings=_settings(),
            audit_emitter=emitter,
            artifact_dir=artifact_dir,
        )
    finally:
        if audit_file is not None:
            audit_file.close()
    click.echo(str(result.explained_rubric_path))


if __name__ == "__main__":
    main()
