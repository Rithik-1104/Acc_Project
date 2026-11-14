import hashlib
import json
from typing import Any

def canonical_json_hash(payload: dict[str, Any]) -> str:
    """
    Computes a deterministic SHA-256 hash of a payload dictionary
    by sorting keys and formatting with standard separators.
    """
    canonical_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
