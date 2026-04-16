"""Unit tests — DR-ARC-09 Settings.

Tests the `from_env` factory, frozen-model invariant, and model-pin
validation. No network access needed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from grading_rubric.config.settings import Settings


class TestSettingsFromEnv:
    """DR-ARC-09: Settings.from_env reads from a dict of env vars."""

    def test_defaults(self) -> None:
        s = Settings.from_env({})
        assert s.ocr_backend == "anthropic"
        assert s.ocr_model == "claude-sonnet-4-20250514"
        assert s.max_iterations == 3
        assert s.schema_version == "1.0.0"
        assert s.simulation_concurrency == 4
        assert s.simulation_backend == "openai"
        assert s.simulation_model == "gpt-5.4"

    def test_stub_backend(self) -> None:
        s = Settings.from_env({"GR_OCR_BACKEND": "stub"})
        assert s.ocr_backend == "stub"

    def test_custom_values(self) -> None:
        env = {
            "GR_OCR_BACKEND": "openai",
            "GR_OCR_MODEL": "gpt-4o",
            "GR_LLM_TIMEOUT": "120",
            "GR_SIMULATION_PANEL_SIZE": "6",
            "GR_SIMULATION_CONCURRENCY": "2",
            "GR_SIMULATION_BACKEND": "openai",
            "GR_SIMULATION_MODEL": "gpt-5.4",
            "GR_MAX_ITERATIONS": "5",
            "OPENAI_API_KEY": "sk-test",
        }
        s = Settings.from_env(env)
        assert s.ocr_backend == "openai"
        assert s.ocr_model == "gpt-4o"
        assert s.reasoning_model == "gpt-4o"  # inherits from ocr_model when ocr_backend is openai
        assert s.llm_call_timeout_seconds == 120
        assert s.simulation_panel_size == 6
        assert s.simulation_concurrency == 2
        assert s.simulation_backend == "openai"
        assert s.simulation_model == "gpt-5.4"
        assert s.max_iterations == 5
        assert s.openai_api_key == "sk-test"


class TestSettingsFrozen:
    """DR-ARC-09: Settings is frozen — no mutation after construction."""

    def test_frozen(self) -> None:
        s = Settings.from_env({})
        with pytest.raises(ValidationError):
            s.max_iterations = 99  # type: ignore[misc]


class TestSettingsModelPinValidation:
    """DR-ARC-09: anthropic backend requires a claude-* model identifier."""

    def test_anthropic_requires_claude_prefix(self) -> None:
        with pytest.raises(
            ValidationError, match="claude-\\*.*model identifier"
        ):
            Settings(
                ocr_backend="anthropic",
                ocr_model="gpt-4o",
            )

    def test_openai_accepts_any_model(self) -> None:
        s = Settings(ocr_backend="openai", ocr_model="gpt-4o")
        assert s.ocr_model == "gpt-4o"

    def test_stub_accepts_any_model(self) -> None:
        s = Settings(ocr_backend="stub", ocr_model="test-model")
        assert s.ocr_model == "test-model"

    def test_empty_model_pinned_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ocr_model"):
            Settings(ocr_backend="stub", ocr_model="")

    def test_anthropic_simulation_override_requires_claude_prefix(self) -> None:
        with pytest.raises(
            ValidationError, match="claude-\\*.*model identifier"
        ):
            Settings(
                ocr_backend="openai",
                ocr_model="gpt-5.4",
                simulation_backend="anthropic",
                simulation_model="gpt-4o",
            )
