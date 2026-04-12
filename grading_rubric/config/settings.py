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
    llm_model_pinned: str = "claude-sonnet-4-6-20251001"
    llm_sampling_temperature: float = 0.7
    llm_call_timeout_seconds: int = 60
    llm_rate_limit_max_retries: int = 3
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Assess stage ───────────────────────────────────────────────────────
    assess_min_real_copies: int = 3
    assess_pairwise_sample_size: int = 10
    assess_discrimination_variance_target: float = 0.04
    assess_panel_size: int = 4

    # ── Propose / improve stage ────────────────────────────────────────────
    max_iterations: int = 3

    # ── Score stage (DR-SCR) ───────────────────────────────────────────────
    scorer_backend: Literal["llm_panel", "trained_model"] = "llm_panel"
    scorer_panel_size: int = 5
    trained_scorer_artefact_path: str | None = None

    # ── Pipeline ───────────────────────────────────────────────────────────
    schema_version: str = "1.0.0"
    request_id: str | None = None  # opaque correlation id when present

    # ── Output ─────────────────────────────────────────────────────────────
    deliverable_schema_version: str = Field(default="1.0.0")

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
        return self

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        """Build a `Settings` from a mapping (defaults to `os.environ`)."""

        e = env if env is not None else os.environ
        return cls(
            llm_backend=e.get("GR_LLM_BACKEND", "anthropic"),  # type: ignore[arg-type]
            llm_model_pinned=e.get("GR_LLM_MODEL", "claude-sonnet-4-6-20251001"),
            llm_sampling_temperature=float(e.get("GR_LLM_TEMPERATURE", "0.7")),
            llm_call_timeout_seconds=int(e.get("GR_LLM_TIMEOUT", "60")),
            llm_rate_limit_max_retries=int(e.get("GR_LLM_RATE_LIMIT_RETRIES", "3")),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY"),
            openai_api_key=e.get("OPENAI_API_KEY"),
            assess_min_real_copies=int(e.get("GR_ASSESS_MIN_REAL_COPIES", "3")),
            assess_pairwise_sample_size=int(e.get("GR_ASSESS_PAIRWISE_SAMPLE_SIZE", "10")),
            assess_discrimination_variance_target=float(
                e.get("GR_ASSESS_DISCRIMINATION_VARIANCE_TARGET", "0.04")
            ),
            assess_panel_size=int(e.get("GR_ASSESS_PANEL_SIZE", "4")),
            max_iterations=int(e.get("GR_MAX_ITERATIONS", "3")),
            scorer_backend=e.get("GR_SCORER_BACKEND", "llm_panel"),  # type: ignore[arg-type]
            scorer_panel_size=int(e.get("GR_SCORER_PANEL_SIZE", "5")),
            trained_scorer_artefact_path=e.get("GR_TRAINED_SCORER_ARTEFACT_PATH"),
            schema_version=e.get("GR_SCHEMA_VERSION", "1.0.0"),
            request_id=e.get("GR_REQUEST_ID"),
            deliverable_schema_version=e.get("GR_DELIVERABLE_SCHEMA_VERSION", "1.0.0"),
        )
