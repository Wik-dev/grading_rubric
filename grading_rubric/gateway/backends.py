"""DR-LLM-09 *Backend pluggability*.

Each backend implements a thin `LlmBackend` protocol with a single
`create_message(...)` method. Backends do **not** know about prompts, schemas,
retries, or audit — those concerns belong to the gateway, not the backend.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from grading_rubric.config.settings import Settings


class RawMessageResponse(BaseModel):
    """Backend-agnostic shape returned by `LlmBackend.create_message`."""

    tool_input: dict[str, Any]
    tokens_in: int
    tokens_out: int
    rate_limit_retries: int = 0


class LlmBackend(Protocol):
    """The minimal protocol the gateway depends on."""

    name: str

    def create_message(
        self,
        *,
        system: str | None,
        user: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        model: str,
        temperature: float,
        timeout_seconds: int,
        max_rate_limit_retries: int,
    ) -> RawMessageResponse: ...


class StubBackend:
    """A test backend that returns canned `tool_input` blocks.

    The default behaviour returns an empty dict; tests can subclass and
    override `create_message` to return whatever shape they want.
    """

    name = "stub"

    def __init__(self, canned_responses: list[dict[str, Any]] | None = None) -> None:
        self._canned = canned_responses or []
        self._cursor = 0

    def create_message(
        self,
        *,
        system: str | None,
        user: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        model: str,
        temperature: float,
        timeout_seconds: int,
        max_rate_limit_retries: int,
    ) -> RawMessageResponse:
        if self._cursor < len(self._canned):
            payload = self._canned[self._cursor]
            self._cursor += 1
        else:
            payload = {}
        return RawMessageResponse(
            tool_input=payload, tokens_in=0, tokens_out=0, rate_limit_retries=0
        )


class AnthropicBackend:
    """The default backend (DR-LLM-09).

    Imports the `anthropic` SDK lazily so unit tests that pass a `StubBackend`
    do not require the SDK to be installed (DR-LLM-10).
    """

    name = "anthropic"

    def __init__(self, *, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: Any | None = None

    def _client_lazy(self) -> Any:
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "anthropic SDK not installed; install `anthropic` or use a "
                    "different backend (set Settings.llm_backend)."
                ) from e
            if not self._api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def create_message(
        self,
        *,
        system: str | None,
        user: str,
        tool_name: str,
        tool_schema: dict[str, Any],
        model: str,
        temperature: float,
        timeout_seconds: int,
        max_rate_limit_retries: int,
    ) -> RawMessageResponse:
        client = self._client_lazy()
        retries = 0
        last_exc: Exception | None = None
        while retries <= max_rate_limit_retries:
            try:
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system or "",
                    messages=[{"role": "user", "content": user}],
                    tools=[
                        {
                            "name": tool_name,
                            "description": "Structured output for grading_rubric",
                            "input_schema": tool_schema,
                        }
                    ],
                    tool_choice={"type": "tool", "name": tool_name},
                    timeout=timeout_seconds,
                )
            except Exception as e:  # noqa: BLE001 — backend-agnostic surface
                # Anthropic SDK raises APIStatusError; we sniff the status_code attr.
                status = getattr(e, "status_code", None)
                if status == 429 and retries < max_rate_limit_retries:
                    retries += 1
                    last_exc = e
                    continue
                raise

            tool_input: dict[str, Any] = {}
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use":
                    tool_input = dict(block.input)
                    break
            usage = getattr(resp, "usage", None)
            tokens_in = getattr(usage, "input_tokens", 0) or 0
            tokens_out = getattr(usage, "output_tokens", 0) or 0
            return RawMessageResponse(
                tool_input=tool_input,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                rate_limit_retries=retries,
            )
        raise RuntimeError(
            f"rate-limit retries exhausted after {retries} attempts"
        ) from last_exc


def make_backend(settings: Settings) -> LlmBackend:
    """Build the backend selected by `Settings.llm_backend`."""

    if settings.llm_backend == "stub":
        return StubBackend()
    if settings.llm_backend == "anthropic":
        return AnthropicBackend(api_key=settings.anthropic_api_key)
    if settings.llm_backend == "openai":
        raise NotImplementedError("OpenAI backend not yet wired")
    raise ValueError(f"unknown llm_backend {settings.llm_backend!r}")
