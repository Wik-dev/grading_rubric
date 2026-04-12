"""Audit sub-package — DR-ARC-06, DR-OBS-01."""

from grading_rubric.audit.emitter import (
    AuditEmitter,
    AuditEvent,
    JsonLineEmitter,
    NullEmitter,
)
from grading_rubric.audit.hashing import (
    canonical_json,
    hash_file,
    hash_object,
    hash_text,
)

__all__ = [
    "AuditEmitter",
    "AuditEvent",
    "JsonLineEmitter",
    "NullEmitter",
    "canonical_json",
    "hash_file",
    "hash_object",
    "hash_text",
]
