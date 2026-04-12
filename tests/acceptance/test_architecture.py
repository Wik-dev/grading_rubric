"""Acceptance tests — architectural invariants.

These tests verify the V-shape's highest-level constraints: the
separation between layers, the naming boundary, and structural
properties that a code reviewer would check on sight.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestLayerSeparation:
    """DR-ARC-07: L1 has zero validance imports."""

    def test_no_validance_imports_in_l1(self) -> None:
        """grep for 'import validance' or 'from validance' in the L1 package."""
        l1_dir = REPO_ROOT / "grading_rubric"
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "-E",
                r"^(import validance|from validance)",
                str(l1_dir),
            ],
            capture_output=True,
            text=True,
        )
        matches = result.stdout.strip()
        assert matches == "", (
            f"DR-ARC-07 violation: L1 package imports from validance:\n{matches}"
        )

    def test_no_validance_imports_in_l2(self) -> None:
        """L2 Docker images must not import validance either."""
        docker_dir = REPO_ROOT / "docker"
        if not docker_dir.exists():
            pytest.skip("docker/ directory not present")
        result = subprocess.run(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "-E",
                r"^(import validance|from validance)",
                str(docker_dir),
            ],
            capture_output=True,
            text=True,
        )
        matches = result.stdout.strip()
        assert matches == "", (
            f"DR-ARC-07 violation: L2 imports from validance:\n{matches}"
        )


class TestFrontendIsolation:
    """DR-UI-01: the SPA has no Python in its build."""

    def test_no_python_files_in_frontend_src(self) -> None:
        frontend_src = REPO_ROOT / "frontend" / "src"
        if not frontend_src.exists():
            pytest.skip("frontend/src not present")
        py_files = list(frontend_src.rglob("*.py"))
        assert py_files == [], (
            f"DR-UI-01 violation: Python files in frontend/src: {py_files}"
        )


class TestModelCoverage:
    """DR-DAT-01: all model files live in grading_rubric/models/."""

    def test_model_files_present(self) -> None:
        models_dir = REPO_ROOT / "grading_rubric" / "models"
        expected_files = [
            "types.py",
            "rubric.py",
            "findings.py",
            "proposed_change.py",
            "explanation.py",
            "deliverable.py",
            "audit.py",
        ]
        for name in expected_files:
            assert (models_dir / name).exists(), (
                f"Missing model file: models/{name}"
            )


class TestL3BoundaryFiles:
    """DR-INT-01: L3 integration files live in validance/ (top-level)."""

    def test_l3_files_present(self) -> None:
        validance_dir = REPO_ROOT / "validance"
        expected_files = ["workflow.py", "proposals.py", "harvester.py", "register.py"]
        for name in expected_files:
            assert (validance_dir / name).exists(), (
                f"Missing L3 file: validance/{name}"
            )

    def test_no_init_py_namespace_package(self) -> None:
        """PEP 420: validance/ must NOT have __init__.py (namespace pkg)."""
        validance_dir = REPO_ROOT / "validance"
        assert not (validance_dir / "__init__.py").exists(), (
            "validance/__init__.py must not exist (PEP 420 namespace package)"
        )
