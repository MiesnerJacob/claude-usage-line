from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

ELEVATED_THRESHOLD = 60.0
CRITICAL_THRESHOLD = 85.0


class Severity(Enum):
    """How close a window is to exhaustion, for colouring decisions."""

    NOMINAL = "nominal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


@dataclass(frozen=True)
class UsageWindow:
    """A single rate-limit window: how much is consumed and when it resets.

    `used_percentage` is clamped to 0-100 on construction because the upstream
    endpoint occasionally reports slightly over 100 once a window is exhausted.
    `resets_at` is a Unix epoch timestamp in seconds, or None when the endpoint
    omits it.
    """

    label: str
    used_percentage: float
    resets_at: int | None = None
    reported_severity: Severity | None = None

    def __post_init__(self) -> None:
        clamped = min(100.0, max(0.0, float(self.used_percentage)))
        object.__setattr__(self, "used_percentage", clamped)

    @property
    def severity(self) -> Severity:
        """Display severity, trusting the server's own grading when supplied.

        The endpoint grades each limit itself, and its thresholds may differ per
        account tier, so a reported severity wins over the local thresholds.
        """
        if self.reported_severity is not None:
            return self.reported_severity
        if self.used_percentage >= CRITICAL_THRESHOLD:
            return Severity.CRITICAL
        if self.used_percentage >= ELEVATED_THRESHOLD:
            return Severity.ELEVATED
        return Severity.NOMINAL

    def seconds_until_reset(self, now: float) -> int | None:
        """Seconds remaining before this window resets, or None if unknown."""
        if self.resets_at is None:
            return None
        return max(0, int(self.resets_at - now))


@dataclass(frozen=True)
class UsageSnapshot:
    """A point-in-time reading of every window the endpoint reported."""

    windows: tuple[UsageWindow, ...]
    captured_at: float
