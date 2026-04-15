"""DR-DAT-06 hashing rules.

Three cases:
- (a) *file* hashes are SHA-256 of the raw file bytes
- (b) *text content* hashes are SHA-256 of the UTF-8 encoding of the text
- (c) *structured-object* digests are SHA-256 of the canonical-JSON UTF-8
      encoding (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`,
      ISO-8601 datetime strings, UUIDs as their canonical hyphenated string).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID


def canonical(obj: Any) -> Any:
    """Recursive canonicalisation. UUIDs → str, datetimes → ISO-8601."""

    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: canonical(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [canonical(v) for v in obj]
    return obj


def hash_file(path: Path | str) -> str:
    """DR-DAT-06 case (a). SHA-256 of raw file bytes."""

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_text(text: str) -> str:
    """DR-DAT-06 case (b). SHA-256 of the UTF-8 encoding of the text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    """Canonical JSON encoding for case (c) digests.

    `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`,
    ISO-8601 datetime strings, UUIDs as their canonical hyphenated form.
    """

    return json.dumps(
        canonical(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def hash_object(obj: Any) -> str:
    """DR-DAT-06 case (c). SHA-256 of canonical-JSON UTF-8 encoding."""

    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
