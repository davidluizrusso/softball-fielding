"""Immutable identity and proof-language helpers for optimized lineups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from secrets import token_hex
import unicodedata


def ascii_slug(value: str, *, fallback: str = "custom") -> str:
    """Return a compact, filename-safe ASCII slug."""

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or fallback


@dataclass(frozen=True)
class ResultIdentity:
    """Metadata captured once for one authoritative optimization result."""

    setup_label: str
    profile_label: str
    profile_key: str
    created_at: datetime
    snapshot_id: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("Result creation time must include a timezone.")
        normalized_snapshot_id = self.snapshot_id.strip().casefold()
        if not re.fullmatch(r"[a-f0-9]{8}", normalized_snapshot_id):
            raise ValueError("Result snapshot IDs must contain eight hexadecimal characters.")
        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )
        object.__setattr__(self, "snapshot_id", normalized_snapshot_id)

    @property
    def created_at_text(self) -> str:
        return self.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    @property
    def timestamp_token(self) -> str:
        return self.created_at.strftime("%Y%m%dT%H%M%SZ")

    @property
    def filename(self) -> str:
        return (
            f"{ascii_slug(self.setup_label)}_{ascii_slug(self.profile_key)}_"
            f"{self.timestamp_token}_{self.snapshot_id}.csv"
        )


def create_result_identity(
    setup_label: str,
    profile_label: str,
    profile_key: str,
    *,
    created_at: datetime | None = None,
    snapshot_id: str | None = None,
) -> ResultIdentity:
    """Capture a new identity for a newly optimized result."""

    return ResultIdentity(
        setup_label=setup_label,
        profile_label=profile_label,
        profile_key=profile_key,
        created_at=created_at or datetime.now(timezone.utc),
        snapshot_id=snapshot_id or token_hex(4),
    )


def solver_status_explanation(status: str) -> str:
    """Explain successful CP-SAT proof status in game-day language."""

    normalized = status.strip().upper()
    if normalized == "OPTIMAL":
        return (
            "Legal, authoritative lineup for the current inputs. Every documented "
            "optimization priority was proven optimal."
        )
    if normalized == "FEASIBLE":
        return (
            "Legal, authoritative lineup for the current inputs. Not every possible "
            "improvement was proven within the configured search budget."
        )
    raise ValueError(f"Unsupported successful solver status: {status!r}.")
