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
        assert s.llm_backend == "anthropic"
        assert s.llm_model_pinned == "claude-sonnet-4-20250514"
        assert s.max_iterations == 3
        assert s.scorer_backend == "llm_panel"
        assert s.schema_version == "1.0.0"
        assert s.assess_llm_concurrency == 4
        assert s.assess_llm_backend is None
        assert s.assess_llm_model_pinned is None

    def test_stub_backend(self) -> None:
        s = Settings.from_env({"GR_LLM_BACKEND": "stub"})
        assert s.llm_backend == "stub"

    def test_custom_values(self) -> None:
        env = {
            "GR_LLM_BACKEND": "openai",
            "GR_LLM_MODEL": "gpt-4o",
            "GR_LLM_TEMPERATURE": "0.3",
            "GR_LLM_TIMEOUT": "120",
            "GR_ASSESS_PANEL_SIZE": "6",
            "GR_ASSESS_LLM_CONCURRENCY": "2",
            "GR_ASSESS_LLM_BACKEND": "openai",
            "GR_ASSESS_LLM_MODEL": "gpt-5.4",
            "GR_MAX_ITERATIONS": "5",
            "OPENAI_API_KEY": "sk-test",
        }
        s = Settings.from_env(env)
        assert s.llm_backend == "openai"
        assert s.llm_model_pinned == "gpt-4o"
        assert s.llm_model_rubric_decomposition == "gpt-4o"
        assert s.llm_sampling_temperature == 0.3
        assert s.llm_call_timeout_seconds == 120
        assert s.assess_panel_size == 6
        assert s.assess_llm_concurrency == 2
        assert s.assess_llm_backend == "openai"
        assert s.assess_llm_model_pinned == "gpt-5.4"
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
                llm_backend="anthropic",
                llm_model_pinned="gpt-4o",
            )

    def test_openai_accepts_any_model(self) -> None:
        s = Settings(llm_backend="openai", llm_model_pinned="gpt-4o")
        assert s.llm_model_pinned == "gpt-4o"

    def test_stub_accepts_any_model(self) -> None:
        s = Settings(llm_backend="stub", llm_model_pinned="test-model")
        assert s.llm_model_pinned == "test-model"

    def test_empty_model_pinned_rejected(self) -> None:
        with pytest.raises(ValidationError, match="llm_model_pinned"):
            Settings(llm_backend="stub", llm_model_pinned="")

    def test_anthropic_assess_override_requires_claude_prefix(self) -> None:
        with pytest.raises(
            ValidationError, match="claude-\\*.*model identifier"
        ):
            Settings(
                llm_backend="openai",
                llm_model_pinned="gpt-5.4",
                assess_llm_backend="anthropic",
                assess_llm_model_pinned="gpt-4o",
            )
