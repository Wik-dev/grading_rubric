"""DR-LLM-09 *Backend pluggability*.

Each backend implements a thin `LlmBackend` protocol with a single
`create_message(...)` method. Backends do **not** know about prompts, schemas,
retries, or audit — those concerns belong to the gateway, not the backend.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from grading_rubric.config.settings import Settings


class RawMessageResponse(BaseModel):
    """Backend-agnostic shape returned by `LlmBackend.create_message`."""

    tool_input: dict[str, Any]
    tokens_in: int
    tokens_out: int
    rate_limit_retries: int = 0


class MessageAttachment(BaseModel):
    """A local file attached to a gateway call.

    The backend reads bytes from `path`; audit logging records only metadata
    and digests, never the base64 payload.
    """

    path: Path
    media_type: str

    @classmethod
    def from_path(cls, path: Path) -> MessageAttachment:
        guessed = mimetypes.guess_type(path.name)[0]
        media_type = guessed or "application/octet-stream"
        if path.suffix.lower() == ".pdf":
            media_type = "application/pdf"
        return cls(path=path, media_type=media_type)


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
        attachments: list[MessageAttachment] | None = None,
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
        attachments: list[MessageAttachment] | None = None,
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
                    "different backend (set Settings.ocr_backend)."
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
        attachments: list[MessageAttachment] | None = None,
    ) -> RawMessageResponse:
        client = self._client_lazy()
        retries = 0
        last_exc: Exception | None = None
        while retries <= max_rate_limit_retries:
            try:
                content: list[dict[str, Any]] = [{"type": "text", "text": user}]
                for attachment in attachments or []:
                    encoded = base64.standard_b64encode(
                        attachment.path.read_bytes()
                    ).decode("ascii")
                    if attachment.media_type == "application/pdf":
                        content.append(
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": attachment.media_type,
                                    "data": encoded,
                                },
                            }
                        )
                    elif attachment.media_type.startswith("image/"):
                        content.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": attachment.media_type,
                                    "data": encoded,
                                },
                            }
                        )
                    else:
                        raise RuntimeError(
                            f"unsupported LLM attachment media type: {attachment.media_type}"
                        )

                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    temperature=temperature,
                    system=system or "",
                    messages=[{"role": "user", "content": content}],
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


class OpenAIBackend:
    """OpenAI backend using Chat Completions tool calling."""

    name = "openai"

    def __init__(self, *, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: Any | None = None

    def _client_lazy(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "openai SDK not installed; install `openai` or use a "
                    "different backend (set Settings.ocr_backend)."
                ) from e
            if not self._api_key:
                raise RuntimeError("OPENAI_API_KEY is not set")
            self._client = OpenAI(api_key=self._api_key)
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
        attachments: list[MessageAttachment] | None = None,
    ) -> RawMessageResponse:
        client = self._client_lazy()
        retries = 0
        last_exc: Exception | None = None

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append(
            {
                "role": "user",
                "content": self._message_content(user, attachments or []),
            }
        )

        while retries <= max_rate_limit_retries:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    max_completion_tokens=4096,
                    temperature=temperature,
                    messages=messages,
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "description": "Structured output for grading_rubric",
                                "parameters": tool_schema,
                            },
                        }
                    ],
                    tool_choice={"type": "function", "function": {"name": tool_name}},
                    timeout=timeout_seconds,
                )
            except Exception as e:  # noqa: BLE001 — backend-agnostic surface
                status = getattr(e, "status_code", None)
                if status == 429 and retries < max_rate_limit_retries:
                    retries += 1
                    last_exc = e
                    continue
                raise

            choice = resp.choices[0] if resp.choices else None
            message = getattr(choice, "message", None)
            tool_calls = getattr(message, "tool_calls", None) or []
            tool_input: dict[str, Any] = {}
            if tool_calls:
                import json  # noqa: PLC0415

                arguments = getattr(tool_calls[0].function, "arguments", "{}") or "{}"
                tool_input = json.loads(arguments)
            usage = getattr(resp, "usage", None)
            tokens_in = getattr(usage, "prompt_tokens", 0) or 0
            tokens_out = getattr(usage, "completion_tokens", 0) or 0
            return RawMessageResponse(
                tool_input=tool_input,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                rate_limit_retries=retries,
            )
        raise RuntimeError(
            f"rate-limit retries exhausted after {retries} attempts"
        ) from last_exc

    @staticmethod
    def _message_content(
        user: str, attachments: list[MessageAttachment]
    ) -> str | list[dict[str, Any]]:
        if not attachments:
            return user

        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for attachment in attachments:
            encoded = base64.standard_b64encode(
                attachment.path.read_bytes()
            ).decode("ascii")
            if attachment.media_type.startswith("image/"):
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{attachment.media_type};base64,{encoded}"
                        },
                    }
                )
            else:
                raise RuntimeError(
                    "OpenAI chat-completions backend supports image OCR attachments "
                    f"only, got {attachment.media_type}"
                )
        return content


def make_backend(settings: Settings) -> LlmBackend:
    """Build the backend selected by `Settings.ocr_backend`."""

    if settings.ocr_backend == "stub":
        return StubBackend()
    if settings.ocr_backend == "anthropic":
        return AnthropicBackend(api_key=settings.anthropic_api_key)
    if settings.ocr_backend == "openai":
        return OpenAIBackend(api_key=settings.openai_api_key)
    raise ValueError(f"unknown ocr_backend {settings.ocr_backend!r}")
