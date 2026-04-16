"""Tests for --input-root mode on the ingest CLI command.

Covers ADR-007 structured-input-root adapter and CLI mutual-exclusion logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from grading_rubric.cli.main import _build_inputs_from_root, main
from grading_rubric.parsers.models import IngestInputs

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture()
def input_root(tmp_path: Path) -> Path:
    """Create a minimal valid ADR-007 input root with one exam question."""
    root = tmp_path / "inputs"
    (root / "exam_question").mkdir(parents=True)
    eq = root / "exam_question" / "ExamQuestion.pdf"
    eq.write_bytes(b"%PDF-1.4 exam content")
    return root


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def ingest_json(tmp_path: Path) -> Path:
    """Create a minimal IngestInputs JSON file for --input mode."""
    eq = tmp_path / "exam.pdf"
    eq.write_bytes(b"%PDF-1.4 exam content")
    payload = {"exam_question_path": str(eq)}
    p = tmp_path / "ingest_inputs.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ── _build_inputs_from_root adapter tests ──────────────────────────────────


class TestBuildInputsFromRoot:
    def test_minimal_exam_only(self, input_root: Path) -> None:
        inputs = _build_inputs_from_root(input_root)
        assert isinstance(inputs, IngestInputs)
        assert inputs.exam_question_path.name == "ExamQuestion.pdf"
        assert inputs.teaching_material_paths == []
        assert inputs.student_copy_paths == []
        assert inputs.starting_rubric_path is None

    def test_all_roles_populated(self, input_root: Path) -> None:
        # teaching_material (multiple)
        tm_dir = input_root / "teaching_material"
        tm_dir.mkdir()
        (tm_dir / "chapter1.pdf").write_bytes(b"ch1")
        (tm_dir / "chapter2.pdf").write_bytes(b"ch2")

        # student_copy (multiple)
        sc_dir = input_root / "student_copy"
        sc_dir.mkdir()
        (sc_dir / "Student1.pdf").write_bytes(b"s1")
        (sc_dir / "Student2.pdf").write_bytes(b"s2")
        (sc_dir / "Student3.pdf").write_bytes(b"s3")

        # starting_rubric (one)
        sr_dir = input_root / "starting_rubric"
        sr_dir.mkdir()
        (sr_dir / "rubric.pdf").write_bytes(b"rubric")

        inputs = _build_inputs_from_root(input_root)
        assert inputs.exam_question_path.name == "ExamQuestion.pdf"
        assert len(inputs.teaching_material_paths) == 2
        assert len(inputs.student_copy_paths) == 3
        assert inputs.starting_rubric_path is not None
        assert inputs.starting_rubric_path.name == "rubric.pdf"

    def test_missing_exam_question_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "inputs"
        root.mkdir()
        # no exam_question directory
        with pytest.raises(Exception, match="exam_question.*no files"):
            _build_inputs_from_root(root)

    def test_empty_exam_question_dir_fails(self, tmp_path: Path) -> None:
        root = tmp_path / "inputs"
        (root / "exam_question").mkdir(parents=True)
        with pytest.raises(Exception, match="exam_question.*no files"):
            _build_inputs_from_root(root)

    def test_multiple_exam_questions_fails(self, input_root: Path) -> None:
        (input_root / "exam_question" / "ExamQuestion2.pdf").write_bytes(b"pdf2")
        with pytest.raises(Exception, match="exactly one file"):
            _build_inputs_from_root(input_root)

    def test_multiple_starting_rubrics_fails(self, input_root: Path) -> None:
        sr_dir = input_root / "starting_rubric"
        sr_dir.mkdir()
        (sr_dir / "rubric1.pdf").write_bytes(b"r1")
        (sr_dir / "rubric2.pdf").write_bytes(b"r2")
        with pytest.raises(Exception, match="at most one file"):
            _build_inputs_from_root(input_root)

    def test_file_order_is_deterministic(self, input_root: Path) -> None:
        sc_dir = input_root / "student_copy"
        sc_dir.mkdir()
        # Create in reverse order
        for name in ["Zara.pdf", "Alice.pdf", "Mike.pdf"]:
            (sc_dir / name).write_bytes(name.encode())

        inputs = _build_inputs_from_root(input_root)
        names = [p.name for p in inputs.student_copy_paths]
        assert names == sorted(names)

    def test_directories_inside_role_are_ignored(self, input_root: Path) -> None:
        tm_dir = input_root / "teaching_material"
        tm_dir.mkdir()
        (tm_dir / "subdir").mkdir()
        (tm_dir / "chapter.pdf").write_bytes(b"ch")

        inputs = _build_inputs_from_root(input_root)
        assert len(inputs.teaching_material_paths) == 1
        assert inputs.teaching_material_paths[0].name == "chapter.pdf"


# ── CLI mutual-exclusion tests ─────────────────────────────────────────────


class TestCliMutualExclusion:
    def test_both_input_and_input_root_fails(
        self, runner: CliRunner, input_root: Path, ingest_json: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "ingest",
                "--input", str(ingest_json),
                "--input-root", str(input_root),
                "--output", str(tmp_path / "out.json"),
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_neither_input_nor_input_root_fails(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            main,
            ["ingest", "--output", str(tmp_path / "out.json")],
        )
        assert result.exit_code != 0
        assert "either --input or --input-root" in result.output


# ── CLI end-to-end tests ───────────────────────────────────────────────────


class TestCliInputRootEndToEnd:
    def test_input_root_produces_output(
        self, runner: CliRunner, input_root: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            main,
            ["ingest", "--input-root", str(input_root), "--output", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "input_provenance" in data
        assert "evidence_profile" in data

    def test_existing_input_json_still_works(
        self, runner: CliRunner, ingest_json: Path, tmp_path: Path
    ) -> None:
        out = tmp_path / "out.json"
        result = runner.invoke(
            main,
            ["ingest", "--input", str(ingest_json), "--output", str(out)],
        )
        assert result.exit_code == 0, result.output
        assert out.exists()
