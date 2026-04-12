"""LLM gateway sub-package — DR-ARC-05, DR-LLM-01..11."""

from grading_rubric.gateway.backends import (
    AnthropicBackend,
    LlmBackend,
    RawMessageResponse,
    StubBackend,
    make_backend,
)
from grading_rubric.gateway.gateway import (
    Gateway,
    GatewayError,
    GatewayTimeoutError,
    GatewayValidationError,
    MeasurementResult,
)
from grading_rubric.gateway.prompts import Prompt, PromptRegistry

__all__ = [
    "Gateway",
    "GatewayError",
    "GatewayValidationError",
    "GatewayTimeoutError",
    "MeasurementResult",
    "Prompt",
    "PromptRegistry",
    "LlmBackend",
    "RawMessageResponse",
    "StubBackend",
    "AnthropicBackend",
    "make_backend",
]


def measure(
    *,
    prompt_id: str,
    inputs,
    output_schema,
    samples: int = 1,
    model: str | None = None,
    settings,
    audit_emitter,
    stage_id: str = "unknown",
):
    """Module-level shorthand for `Gateway().measure(...)` (DR-LLM-01)."""

    return Gateway().measure(
        prompt_id=prompt_id,
        inputs=inputs,
        output_schema=output_schema,
        samples=samples,
        model=model,
        settings=settings,
        audit_emitter=audit_emitter,
        stage_id=stage_id,
    )
