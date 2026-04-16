"""DR-LLM-01 — the single LLM seam (`gateway.measure(...)`)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.audit.hashing import canonical_json, hash_object, hash_text
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.backends import LlmBackend, MessageAttachment, make_backend
from grading_rubric.gateway.prompts import PromptRegistry

T = TypeVar("T", bound=BaseModel)


class GatewayError(RuntimeError):
    """Base class for all gateway-side errors."""


class GatewayValidationError(GatewayError):
    """DR-LLM-04 — both validation attempts failed."""


class GatewayTimeoutError(GatewayError):
    """DR-LLM-07 — backend timed out."""


class MeasurementResult(BaseModel, Generic[T]):
    """DR-LLM-01 return shape."""

    samples: list[T]
    operation_id: UUID
    aggregate: T | None = None


class Gateway:
    """The only place in the codebase that imports an LLM SDK client (DR-ARC-05)."""

    def __init__(
        self,
        *,
        backend: LlmBackend | None = None,
        prompts: PromptRegistry | None = None,
    ) -> None:
        self._backend = backend
        self._prompts = prompts or PromptRegistry()

    # ── Public surface ─────────────────────────────────────────────────────
    def measure(
        self,
        *,
        prompt_id: str,
        inputs: BaseModel,
        output_schema: type[T],
        samples: int = 1,
        model: str | None = None,
        temperature: float | None = None,
        settings: Settings,
        audit_emitter: AuditEmitter,
        stage_id: str = "unknown",
        attachments: list[MessageAttachment] | None = None,
    ) -> MeasurementResult[T]:
        """DR-LLM-01 — the only public LLM seam."""

        backend = self._backend or make_backend(settings)
        prompt, rendered_user = self._prompts.render(
            prompt_id, inputs.model_dump(mode="json")
        )

        # DR-LLM-06: temperature is 0.0 when samples == 1, else from settings.
        # Callers may override this for controlled simulations where single
        # samples still need persona diversity.
        temperature = (
            temperature
            if temperature is not None
            else 0.0 if samples == 1 else 0.7
        )
        chosen_model = model or settings.ocr_model

        tool_schema = output_schema.model_json_schema()
        schema_hash = hash_text(canonical_json(tool_schema))
        schema_id = f"{output_schema.__module__}.{output_schema.__name__}@{prompt.prompt_version}"

        operation_id = uuid4()
        started_at = datetime.now(UTC)

        validated: list[T] = []
        raw_responses: list[dict[str, Any]] = []
        tokens_in_total = 0
        tokens_out_total = 0
        rate_limit_retries_total = 0

        for _ in range(samples):
            try:
                resp = backend.create_message(
                    system=None,
                    user=rendered_user,
                    tool_name=output_schema.__name__,
                    tool_schema=tool_schema,
                    model=chosen_model,
                    temperature=temperature,
                    timeout_seconds=settings.llm_call_timeout_seconds,
                    max_rate_limit_retries=settings.llm_rate_limit_max_retries,
                    attachments=attachments,
                )
            except TimeoutError as e:
                self._emit_failure(
                    audit_emitter=audit_emitter,
                    stage_id=stage_id,
                    operation_id=operation_id,
                    prompt=prompt,
                    schema_id=schema_id,
                    schema_hash=schema_hash,
                    model=chosen_model,
                    temperature=temperature,
                    samples=samples,
                    inputs=inputs,
                    raw_responses=raw_responses,
                    started_at=started_at,
                    tokens_in=tokens_in_total,
                    tokens_out=tokens_out_total,
                    rate_limit_retries=rate_limit_retries_total,
                    error_code="TIMEOUT",
                    error_message=str(e),
                    attachments=attachments or [],
                )
                raise GatewayTimeoutError(str(e)) from e

            tokens_in_total += resp.tokens_in
            tokens_out_total += resp.tokens_out
            rate_limit_retries_total += resp.rate_limit_retries
            raw_responses.append(resp.tool_input)

            try:
                instance = output_schema.model_validate(resp.tool_input)
            except ValidationError:
                # DR-LLM-04: at most one validation retry.
                try:
                    resp2 = backend.create_message(
                        system=(
                            "The previous tool-use response failed strict validation. "
                            "Re-emit the same tool call but conform exactly to the "
                            "schema this time."
                        ),
                        user=rendered_user,
                        tool_name=output_schema.__name__,
                        tool_schema=tool_schema,
                        model=chosen_model,
                        temperature=temperature,
                        timeout_seconds=settings.llm_call_timeout_seconds,
                        max_rate_limit_retries=settings.llm_rate_limit_max_retries,
                        attachments=attachments,
                    )
                    tokens_in_total += resp2.tokens_in
                    tokens_out_total += resp2.tokens_out
                    rate_limit_retries_total += resp2.rate_limit_retries
                    raw_responses.append(resp2.tool_input)
                    instance = output_schema.model_validate(resp2.tool_input)
                except ValidationError as e:
                    self._emit_failure(
                        audit_emitter=audit_emitter,
                        stage_id=stage_id,
                        operation_id=operation_id,
                        prompt=prompt,
                        schema_id=schema_id,
                        schema_hash=schema_hash,
                        model=chosen_model,
                        temperature=temperature,
                        samples=samples,
                        inputs=inputs,
                        raw_responses=raw_responses,
                        started_at=started_at,
                        tokens_in=tokens_in_total,
                        tokens_out=tokens_out_total,
                        rate_limit_retries=rate_limit_retries_total,
                        error_code="VALIDATION",
                        error_message=str(e),
                        attachments=attachments or [],
                    )
                    raise GatewayValidationError(str(e)) from e

            validated.append(instance)

        ended_at = datetime.now(UTC)

        # DR-LLM-08: emit a fully-populated LlmCallDetails on success.
        audit_emitter.record_operation(
            {
                "id": str(operation_id),
                "stage_id": stage_id,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "status": "success",
                "attempt": 1,
                "retry_of": None,
                "inputs_digest": hash_object(inputs.model_dump(mode="json")),
                "outputs_digest": hash_object(
                    [v.model_dump(mode="json") for v in validated]
                ),
                "details": {
                    "kind": "llm_call",
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.prompt_version,
                    "prompt_hash": prompt.prompt_hash,
                    "schema_id": schema_id,
                    "schema_hash": schema_hash,
                    "model": chosen_model,
                    "temperature": temperature,
                    "samples": samples,
                    "tokens_in": tokens_in_total,
                    "tokens_out": tokens_out_total,
                    "rate_limit_retries": rate_limit_retries_total,
                    "inputs": inputs.model_dump(mode="json"),
                    "attachments": self._attachment_metadata(attachments or []),
                    "rendered_user_prompt": rendered_user,
                    "raw_responses": raw_responses,
                },
                "error": None,
            }
        )

        aggregate = validated[0] if samples == 1 and validated else None
        return MeasurementResult[T](
            samples=validated, operation_id=operation_id, aggregate=aggregate
        )

    # ── Internal ───────────────────────────────────────────────────────────
    def _emit_failure(
        self,
        *,
        audit_emitter: AuditEmitter,
        stage_id: str,
        operation_id: UUID,
        prompt: Any,
        schema_id: str,
        schema_hash: str,
        model: str,
        temperature: float,
        samples: int,
        inputs: BaseModel,
        raw_responses: list[dict[str, Any]],
        started_at: datetime,
        tokens_in: int,
        tokens_out: int,
        rate_limit_retries: int,
        error_code: str,
        error_message: str,
        attachments: list[MessageAttachment],
    ) -> None:
        audit_emitter.record_operation(
            {
                "id": str(operation_id),
                "stage_id": stage_id,
                "started_at": started_at.isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "status": "failed",
                "attempt": 1,
                "retry_of": None,
                "inputs_digest": hash_object(inputs.model_dump(mode="json")),
                "outputs_digest": None,
                "details": {
                    "kind": "llm_call",
                    "prompt_id": prompt.prompt_id,
                    "prompt_version": prompt.prompt_version,
                    "prompt_hash": prompt.prompt_hash,
                    "schema_id": schema_id,
                    "schema_hash": schema_hash,
                    "model": model,
                    "temperature": temperature,
                    "samples": samples,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "rate_limit_retries": rate_limit_retries,
                    "inputs": inputs.model_dump(mode="json"),
                    "attachments": self._attachment_metadata(attachments or []),
                    "rendered_user_prompt": self._prompts.render(
                        prompt.prompt_id, inputs.model_dump(mode="json")
                    )[1],
                    "raw_responses": raw_responses,
                },
                "error": {
                    "code": error_code,
                    "message": error_message,
                    "stage_id": stage_id,
                    "operation_id": str(operation_id),
                },
            }
        )

    @staticmethod
    def _attachment_metadata(attachments: list[MessageAttachment]) -> list[dict[str, Any]]:
        return [
            {
                "path": str(attachment.path),
                "media_type": attachment.media_type,
                "size_bytes": attachment.path.stat().st_size,
                "sha256": hashlib.sha256(attachment.path.read_bytes()).hexdigest(),
            }
            for attachment in attachments
        ]
