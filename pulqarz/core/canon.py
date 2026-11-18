"""Canonical JSON and hashing for the ledger hash chain (pure, no I/O).

Every entry is hashed as ``sha256(prev_hash + canonical_json(body))``. Canonical JSON means: keys
sorted, no spaces, UTF-8 kept as is, and only strings, integers, lists and objects allowed. Floats and
booleans are refused, so money can never sneak in as a float. The JS port (shared/core.js) does exactly
the same; shared/test_vectors.json proves both agree.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS = "0" * 64


def _check(value: Any, path: str = "$") -> None:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{path}: only str, int, list and dict are allowed in canonical JSON")
    if isinstance(value, int):
        if abs(value) > 2**53 - 1:  # must survive a round trip through a JS number
            raise ValueError(f"{path}: integer out of the safe range")
        return
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: object keys must be strings")
            _check(item, f"{path}.{key}")
        return
    raise TypeError(f"{path}: unsupported type {type(value).__name__}")


def canonical(obj: Any) -> str:
    """Deterministic JSON text for ``obj``."""
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def entry_hash(prev: str, body: dict) -> str:
    return sha256_hex(prev + canonical(body))


def seal(hash_hex: str) -> str:
    """Short, human-readable form of a hash, shown on the "muhr" (seal): ``A1B2-C3D4``."""
    return f"{hash_hex[:4]}-{hash_hex[4:8]}".upper()
