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

    # ── OCR (parse stage) ────────────────────────────────────────────────
    ocr_backend: Literal["anthropic", "openai", "stub"] = "anthropic"
    ocr_model: str = "claude-sonnet-4-20250514"

    # ── Reasoning (rubric decomposition + proposal generation) ───────────
    reasoning_model: str | None = "claude-opus-4-6"

    # ── Grader simulation (assess + score stages) ────────────────────────
    simulation_backend: Literal["anthropic", "openai", "stub"] = "openai"
    simulation_model: str = "gpt-5.4"
    simulation_min_real_copies: int = 3
    simulation_pairwise_pairs: int = 10
    simulation_panel_size: int = 4
    simulation_target_responses: int = 10
    simulation_concurrency: int = 4

    # ── Shared LLM settings ──────────────────────────────────────────────
    llm_call_timeout_seconds: int = 300
    llm_rate_limit_max_retries: int = 3
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # ── Propose / improve stage ──────────────────────────────────────────
    max_iterations: int = 3

    # ── Pipeline ─────────────────────────────────────────────────────────
    schema_version: str = "1.0.0"
    request_id: str | None = None  # opaque correlation id when present

    # ── Output ───────────────────────────────────────────────────────────
    deliverable_schema_version: str = Field(default="1.0.0")

    @property
    def llm_available(self) -> bool:
        """Whether an LLM backend is configured and usable."""
        if self.ocr_backend == "stub":
            return False
        if self.ocr_backend == "anthropic" and not self.anthropic_api_key:
            return False
        return not (self.ocr_backend == "openai" and not self.openai_api_key)

    @model_validator(mode="after")
    def _check_pinned_model(self) -> Settings:
        if not self.ocr_model:
            raise ValueError("ocr_model must be set")
        if self.ocr_backend == "anthropic" and not self.ocr_model.startswith(
            "claude-"
        ):
            raise ValueError(
                f"anthropic backend requires a 'claude-*' model identifier, got "
                f"{self.ocr_model!r}"
            )
        if (
            self.simulation_backend == "anthropic"
            and self.simulation_model
            and not self.simulation_model.startswith("claude-")
        ):
            raise ValueError(
                f"anthropic simulation backend requires a 'claude-*' model identifier, got "
                f"{self.simulation_model!r}"
            )
        return self

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        """Build a `Settings` from a mapping (defaults to `os.environ`)."""

        e = env if env is not None else os.environ
        ocr_backend = e.get("GR_OCR_BACKEND", "anthropic")
        ocr_model = e.get("GR_OCR_MODEL", "claude-sonnet-4-20250514")
        reasoning_model = e.get("GR_REASONING_MODEL")
        if reasoning_model is None:
            reasoning_model = ocr_model if ocr_backend == "openai" else "claude-opus-4-6"
        return cls(
            ocr_backend=ocr_backend,  # type: ignore[arg-type]
            ocr_model=ocr_model,
            reasoning_model=reasoning_model,
            llm_call_timeout_seconds=int(e.get("GR_LLM_TIMEOUT", "300")),
            llm_rate_limit_max_retries=int(e.get("GR_LLM_RATE_LIMIT_RETRIES", "3")),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY"),
            openai_api_key=e.get("OPENAI_API_KEY"),
            simulation_backend=e.get("GR_SIMULATION_BACKEND", "openai"),  # type: ignore[arg-type]
            simulation_model=e.get("GR_SIMULATION_MODEL", "gpt-5.4"),
            simulation_min_real_copies=int(e.get("GR_SIMULATION_MIN_REAL_COPIES", "3")),
            simulation_pairwise_pairs=int(e.get("GR_SIMULATION_PAIRWISE_PAIRS", "10")),
            simulation_panel_size=int(e.get("GR_SIMULATION_PANEL_SIZE", "4")),
            simulation_target_responses=int(e.get("GR_SIMULATION_TARGET_RESPONSES", "10")),
            simulation_concurrency=int(e.get("GR_SIMULATION_CONCURRENCY", "4")),
            max_iterations=int(e.get("GR_MAX_ITERATIONS", "3")),
            schema_version=e.get("GR_SCHEMA_VERSION", "1.0.0"),
            request_id=e.get("GR_REQUEST_ID"),
            deliverable_schema_version=e.get("GR_DELIVERABLE_SCHEMA_VERSION", "1.0.0"),
        )
