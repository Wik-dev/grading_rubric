"""Shared primitive type aliases per § 4.1.

All identifier fields are real `uuid.UUID` instances at runtime (DR-DAT-06),
not strings. The aliases below exist for documentation; semantically they are
all UUIDs and are interchangeable at runtime, so `mypy` can catch swaps but
Pydantic will not.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue as _PydanticJsonValue

RubricId = UUID
CriterionId = UUID
LevelId = UUID
FindingId = UUID
ChangeId = UUID
OperationId = UUID
RunId = UUID

# § 4.1: any JSON-serialisable value. Re-exported from pydantic so its
# recursive schema is the (well-tested) one Pydantic ships with.
JsonValue = _PydanticJsonValue
