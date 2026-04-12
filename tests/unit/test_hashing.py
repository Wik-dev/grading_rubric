"""Unit tests — DR-DAT-06 hashing rules.

Three cases from the design:
  (a) file hashes: SHA-256 of raw bytes
  (b) text hashes: SHA-256 of UTF-8 encoding
  (c) object digests: SHA-256 of canonical-JSON UTF-8 encoding

Determinism is the key property — re-running with the same input must
produce the same digest. Tests verify stability, not just correctness.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from grading_rubric.audit.hashing import (
    _canonical,
    canonical_json,
    hash_file,
    hash_object,
    hash_text,
)


class TestHashFile:
    """DR-DAT-06 case (a): SHA-256 of raw file bytes."""

    def test_known_content(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert hash_file(f) == expected

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert hash_file(f) == expected

    def test_binary_content(self, tmp_path: Path) -> None:
        data = bytes(range(256))
        f = tmp_path / "binary"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert hash_file(f) == expected

    def test_determinism(self, tmp_path: Path) -> None:
        f = tmp_path / "det.txt"
        f.write_text("deterministic")
        assert hash_file(f) == hash_file(f)


class TestHashText:
    """DR-DAT-06 case (b): SHA-256 of UTF-8 encoding."""

    def test_known_content(self) -> None:
        expected = hashlib.sha256("hello".encode("utf-8")).hexdigest()
        assert hash_text("hello") == expected

    def test_unicode(self) -> None:
        text = "Les résultats de l'évaluation"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert hash_text(text) == expected

    def test_empty_string(self) -> None:
        expected = hashlib.sha256(b"").hexdigest()
        assert hash_text("") == expected

    def test_determinism(self) -> None:
        assert hash_text("abc") == hash_text("abc")


class TestCanonicalJson:
    """DR-DAT-06 case (c): canonical-JSON determinism."""

    def test_sorted_keys(self) -> None:
        result = canonical_json({"b": 1, "a": 2})
        assert result == '{"a":2,"b":1}'

    def test_compact_separators(self) -> None:
        result = canonical_json({"x": [1, 2, 3]})
        assert " " not in result  # no spaces around separators

    def test_uuid_serialization(self) -> None:
        uid = UUID("12345678-1234-5678-1234-567812345678")
        result = canonical_json({"id": uid})
        assert "12345678-1234-5678-1234-567812345678" in result

    def test_datetime_serialization(self) -> None:
        dt = datetime(2026, 4, 12, 10, 30, 0)
        result = canonical_json({"ts": dt})
        assert "2026-04-12T10:30:00" in result

    def test_nested_canonicalization(self) -> None:
        uid = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        obj = {"outer": {"inner": uid, "list": [uid, "text"]}}
        result = canonical_json(obj)
        parsed = json.loads(result)
        assert parsed["outer"]["inner"] == str(uid)
        assert parsed["outer"]["list"][0] == str(uid)

    def test_key_order_determinism(self) -> None:
        """Same data with different insertion order produces same JSON."""
        a = canonical_json({"z": 1, "a": 2, "m": 3})
        b = canonical_json({"a": 2, "m": 3, "z": 1})
        assert a == b


class TestHashObject:
    """DR-DAT-06 case (c): object digests are deterministic."""

    def test_known_object(self) -> None:
        obj = {"key": "value"}
        digest = hash_object(obj)
        # Verify it's a valid hex SHA-256 digest.
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_determinism(self) -> None:
        obj = {"key": "value", "list": [1, 2, 3]}
        assert hash_object(obj) == hash_object(obj)

    def test_key_order_irrelevance(self) -> None:
        assert hash_object({"b": 1, "a": 2}) == hash_object({"a": 2, "b": 1})
