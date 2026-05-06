from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_string(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(value)


def parse_iso(value: Any) -> datetime:
    value = iso_string(value)
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def freshness_minutes(value: Any) -> float:
    updated = parse_iso(value)
    return max(0.0, (datetime.now(UTC) - updated).total_seconds() / 60)
