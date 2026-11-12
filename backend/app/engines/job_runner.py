"""Load job fixtures and produce a simple success/fail result."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "watermark_ts" not in data or "rows" not in data:
        raise ValueError("fixture must contain watermark_ts and rows")
    if not isinstance(data["rows"], list):
        raise ValueError("rows must be a list")
    return data


def run_fixture_job(path: Path) -> dict[str, Any]:
    payload = load_fixture(path)
    flags = payload.get("flags") or {}
    if not isinstance(flags, dict):
        raise ValueError("fixture flags must be an object when present")
    return {
        "ok": True,
        "watermark_ts": payload["watermark_ts"],
        "artifact_rows": len(payload["rows"]),
        "flags": flags,
        "sample": payload["rows"][:3],
    }
