"""§ 3.7 *Configuration mechanism* and DR-ARC-09 *Settings*.

A single `Settings` object is built once at process boot from environment
variables, validated, and injected into the orchestrator. Stages receive
`settings` as an argument and **must not mutate it**. There is no global
`settings` singleton readable from arbitrary code.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    """Process-wide configuration. Built once from environment variables."""

    model_config = ConfigDict(strict=True, frozen=True)

    # ── LLM gateway ────────────────────────────────────────────────────────
    llm_backend: Literal["anthropic", "openai", "stub"] = "anthropic"
    llm_model_pinned: str = "claude-sonnet-4-20250514"
    llm_sampling_temperature: float = 0.7
    llm_call_timeout_seconds: int = 60
    llm_rate_limit_max_retries: int = 3
    llm_model_rubric_decomposition: str | None = "claude-opus-4-6"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Assess stage ───────────────────────────────────────────────────────
    assess_llm_backend: Literal["anthropic", "openai", "stub"] | None = None
    assess_llm_model_pinned: str | None = None
    assess_min_real_copies: int = 3
    assess_pairwise_sample_size: int = 10
    assess_panel_size: int = 4
    assess_target_response_count: int = 10
    assess_llm_concurrency: int = 4

    # ── Propose / improve stage ────────────────────────────────────────────
    max_iterations: int = 3

    # ── Score stage (DR-SCR) ───────────────────────────────────────────────
    scorer_backend: Literal["llm_panel", "trained_model"] = "llm_panel"
    trained_scorer_artefact_path: str | None = None

    # ── Pipeline ───────────────────────────────────────────────────────────
    schema_version: str = "1.0.0"
    request_id: str | None = None  # opaque correlation id when present

    # ── Output ─────────────────────────────────────────────────────────────
    deliverable_schema_version: str = Field(default="1.0.0")

    @property
    def llm_available(self) -> bool:
        """Whether an LLM backend is configured and usable."""
        if self.llm_backend == "stub":
            return False
        if self.llm_backend == "anthropic" and not self.anthropic_api_key:
            return False
        if self.llm_backend == "openai" and not self.openai_api_key:
            return False
        return True

    @model_validator(mode="after")
    def _check_pinned_model(self) -> "Settings":
        if not self.llm_model_pinned:
            raise ValueError("llm_model_pinned must be set")
        if self.llm_backend == "anthropic" and not self.llm_model_pinned.startswith(
            "claude-"
        ):
            raise ValueError(
                f"anthropic backend requires a 'claude-*' model identifier, got "
                f"{self.llm_model_pinned!r}"
            )
        if (
            self.assess_llm_backend == "anthropic"
            and self.assess_llm_model_pinned
            and not self.assess_llm_model_pinned.startswith("claude-")
        ):
            raise ValueError(
                f"anthropic assess backend requires a 'claude-*' model identifier, got "
                f"{self.assess_llm_model_pinned!r}"
            )
        return self

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        """Build a `Settings` from a mapping (defaults to `os.environ`)."""

        e = env if env is not None else os.environ
        llm_backend = e.get("GR_LLM_BACKEND", "anthropic")
        llm_model = e.get("GR_LLM_MODEL", "claude-sonnet-4-20250514")
        rubric_model = e.get("GR_LLM_MODEL_RUBRIC_DECOMPOSITION")
        if rubric_model is None:
            rubric_model = llm_model if llm_backend == "openai" else "claude-opus-4-6"
        return cls(
            llm_backend=llm_backend,  # type: ignore[arg-type]
            llm_model_pinned=llm_model,
            llm_sampling_temperature=float(e.get("GR_LLM_TEMPERATURE", "0.7")),
            llm_call_timeout_seconds=int(e.get("GR_LLM_TIMEOUT", "60")),
            llm_rate_limit_max_retries=int(e.get("GR_LLM_RATE_LIMIT_RETRIES", "3")),
            llm_model_rubric_decomposition=rubric_model,
            anthropic_api_key=e.get("ANTHROPIC_API_KEY"),
            openai_api_key=e.get("OPENAI_API_KEY"),
            assess_llm_backend=e.get("GR_ASSESS_LLM_BACKEND"),  # type: ignore[arg-type]
            assess_llm_model_pinned=e.get("GR_ASSESS_LLM_MODEL"),
            assess_min_real_copies=int(e.get("GR_ASSESS_MIN_REAL_COPIES", "3")),
            assess_pairwise_sample_size=int(e.get("GR_ASSESS_PAIRWISE_SAMPLE_SIZE", "10")),
            assess_panel_size=int(e.get("GR_ASSESS_PANEL_SIZE", "4")),
            assess_target_response_count=int(e.get("GR_ASSESS_TARGET_RESPONSE_COUNT", "10")),
            assess_llm_concurrency=int(e.get("GR_ASSESS_LLM_CONCURRENCY", "4")),
            max_iterations=int(e.get("GR_MAX_ITERATIONS", "3")),
            scorer_backend=e.get("GR_SCORER_BACKEND", "llm_panel"),  # type: ignore[arg-type]
            trained_scorer_artefact_path=e.get("GR_TRAINED_SCORER_ARTEFACT_PATH"),
            schema_version=e.get("GR_SCHEMA_VERSION", "1.0.0"),
            request_id=e.get("GR_REQUEST_ID"),
            deliverable_schema_version=e.get("GR_DELIVERABLE_SCHEMA_VERSION", "1.0.0"),
        )
