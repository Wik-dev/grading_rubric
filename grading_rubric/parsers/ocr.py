"""Gateway-backed OCR/document vision readers for parser fallbacks."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from grading_rubric.audit.emitter import AuditEmitter
from grading_rubric.config.settings import Settings
from grading_rubric.gateway.backends import MessageAttachment
from grading_rubric.gateway.gateway import Gateway

STAGE_ID = "parse-inputs"


class UnreadableRegion(BaseModel):
    model_config = ConfigDict(strict=True)

    page_index: int
    description: str


class OcrDocumentInputs(BaseModel):
    model_config = ConfigDict(strict=True)

    role: str
    source_name: str
    context_text: str = ""
    extracted_text_hint: str = ""


class OcrDocumentResult(BaseModel):
    model_config = ConfigDict(strict=True)

    text: str
    confidence: float
    unreadable_regions: list[UnreadableRegion] = Field(default_factory=list)
    notes: str = ""


class DocumentOcrReader(Protocol):
    def read_text(
        self,
        path: Path,
        *,
        role: str,
        context_text: str,
        extracted_text_hint: str,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> str: ...


class ClaudeDocumentOcrReader:
    """OCR/vision implementation using the same audited gateway as LLM calls."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._gateway = gateway or Gateway()

    def read_text(
        self,
        path: Path,
        *,
        role: str,
        context_text: str,
        extracted_text_hint: str,
        settings: Settings,
        audit_emitter: AuditEmitter,
    ) -> str:
        result = self._gateway.measure(
            prompt_id="ocr_document",
            inputs=OcrDocumentInputs(
                role=role,
                source_name=path.name,
                context_text=context_text,
                extracted_text_hint=extracted_text_hint,
            ),
            output_schema=OcrDocumentResult,
            samples=1,
            settings=settings,
            audit_emitter=audit_emitter,
            stage_id=STAGE_ID,
            attachments=[MessageAttachment.from_path(path)],
        )
        return result.aggregate.text.strip() if result.aggregate else ""


def is_ocr_candidate(path: Path) -> bool:
    return path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
