"""doctorkit - type definitions.

Public types (CheckResult, FixResult, CheckInfo) are re-exported from __init__.py.
Internal types (_CheckDef, _FixRunResult, _Result) stay private to the package.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, List, Literal, Optional

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

CheckStatus = Literal["ok", "warn", "fail", "skipped", "error"]
FixStatus = Literal["fixed", "fix_failed"]


@dataclasses.dataclass
class CheckResult:
    """Value returned by a check function."""

    status: CheckStatus
    message: str
    hint: Optional[str] = None


@dataclasses.dataclass
class FixResult:
    """Value returned by a fix function."""

    status: FixStatus
    message: str


@dataclasses.dataclass
class CheckInfo:
    """Read-only metadata returned by :py:meth:`Doctor.list_checks`."""

    name: str
    tag: str
    depends_on: List[str]
    warn_only: bool
    timeout: float
    retries: int
    retry_delay: float
    slow_threshold_ms: Optional[float]
    has_fix: bool = False


# ---------------------------------------------------------------------------
# Internal types - NOT re-exported from __init__.py
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _CheckDef:
    name: str
    fn: Callable[[], Any]
    tag: str
    depends_on: List[str]
    warn_only: bool
    timeout: float
    retries: int
    retry_delay: float
    slow_threshold_ms: Optional[float]
    fix_fn: Optional[Callable[[], Any]] = None


@dataclasses.dataclass
class RunSummary:
    """Summary counts from a completed run."""
    ok: int
    warn: int
    fail: int
    skipped: int
    slow: int


@dataclasses.dataclass
class CheckRecord:
    """Public result for a single check, returned by :py:meth:`Doctor.run_detailed`."""
    name: str
    status: CheckStatus
    message: str
    hint: Optional[str]
    tag: str
    duration_ms: float
    is_slow: bool
    skip_reason: Optional[str]
    fix_status: Optional[str]
    fix_message: Optional[str]


@dataclasses.dataclass
class RunResult:
    """Rich return value from :py:meth:`Doctor.run_detailed`."""
    exit_code: int
    summary: RunSummary
    checks: List["CheckRecord"]
    total_ms: float


@dataclasses.dataclass
class _FixRunResult:
    status: Literal["fixed", "fix_failed", "fix_error"]
    message: str
    exc_traceback: Optional[str] = None


@dataclasses.dataclass
class _Result:
    name: str
    status: CheckStatus
    message: str
    hint: Optional[str]
    tag: str
    duration_ms: float
    skip_reason: Optional[str] = None
    is_slow: bool = False
    exc_traceback: Optional[str] = None  # populated only on status="error"
    fix_result: Optional[_FixRunResult] = None
