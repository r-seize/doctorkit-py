"""doctorkit - check execution engine.

Responsible for running a single check (timeout, retries) and for
sorting checks in dependency order. No I/O here.
"""
from __future__ import annotations

import threading
import time
import traceback as _traceback
from typing import Any, Callable, Dict, List, Optional

from ._types import CheckResult, FixResult, _CheckDef, _FixRunResult, _Result


def _run_check(cd: _CheckDef) -> _Result:
    """Execute a check with timeout and retry logic. Never raises."""
    last: Optional[_Result] = None

    for attempt in range(cd.retries + 1):
        if attempt > 0:
            time.sleep(cd.retry_delay)

        t0 = time.monotonic()
        value_box: List[Any] = [None]
        exc_box: List[Optional[BaseException]] = [None]
        tb_box: List[Optional[str]] = [None]
        done_evt = threading.Event()

        def _worker() -> None:
            try:
                value_box[0] = cd.fn()
            except Exception as exc:  # noqa: BLE001
                exc_box[0] = exc
                tb_box[0] = _traceback.format_exc()
            finally:
                done_evt.set()

        threading.Thread(target=_worker, daemon=True).start()
        timed_out = not done_evt.wait(timeout=cd.timeout)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if timed_out:
            last = _Result(
                name=cd.name,
                status="fail",
                message=f"timeout after {cd.timeout:.0f}s",
                hint=None,
                tag=cd.tag,
                duration_ms=elapsed_ms,
            )
            continue  # retry

        if exc_box[0] is not None:
            last = _Result(
                name=cd.name,
                status="error",
                message=f"unexpected error: {exc_box[0]}",
                hint="This is a bug in the check itself, not in your environment.",
                tag=cd.tag,
                duration_ms=elapsed_ms,
                exc_traceback=tb_box[0],
            )
            continue  # retry

        raw = value_box[0]
        interim = _normalise(cd, raw, elapsed_ms)
        last = interim
        if interim.status in ("ok", "warn"):
            return interim
        # fail -> retry if attempts remain

    assert last is not None
    return last


def _topo_sort(checks: List[_CheckDef]) -> List[_CheckDef]:
    """Dependency-first topological sort; preserves registration order within a level.

    Cycles are silently ignored (the involved check is still included).
    """
    by_name: Dict[str, _CheckDef] = {c.name: c for c in checks}
    visited: set = set()
    temp: set = set()
    result: List[_CheckDef] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in temp:
            return  # cycle - skip to avoid infinite recursion
        cd = by_name.get(name)
        if cd is None:
            return
        temp.add(name)
        for dep in cd.depends_on:
            visit(dep)
        temp.discard(name)
        visited.add(name)
        result.append(cd)

    for c in checks:
        visit(c.name)

    return result


def _compute_waves(checks: List[_CheckDef]) -> List[List[_CheckDef]]:
    """Group topo-sorted checks into parallel waves.

    Wave 0 = no deps (or all deps external). Wave N = max(dep waves) + 1.
    Checks within the same wave are independent and safe to run in parallel.
    """
    if not checks:
        return []
    by_name: Dict[str, _CheckDef] = {c.name: c for c in checks}
    wave_of: Dict[str, int] = {}
    in_progress: set = set()

    def get_wave(name: str) -> int:
        if name in wave_of:
            return wave_of[name]
        if name in in_progress:
            return -1  # cycle guard
        cd = by_name.get(name)
        if cd is None:
            return -1  # external dep - treat as already satisfied
        in_progress.add(name)
        w = 0
        for dep in cd.depends_on:
            dw = get_wave(dep)
            if dw >= 0:
                w = max(w, dw + 1)
        in_progress.discard(name)
        wave_of[name] = w
        return w

    for c in checks:
        get_wave(c.name)

    max_wave = max(wave_of.values())
    waves: List[List[_CheckDef]] = [[] for _ in range(max_wave + 1)]
    for c in checks:
        waves[wave_of[c.name]].append(c)
    return waves


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_fix(fix_fn: Callable[[], Any]) -> _FixRunResult:
    """Execute a fix function. Never raises."""
    try:
        raw = fix_fn()
        if isinstance(raw, FixResult):
            return _FixRunResult(status=raw.status, message=raw.message)
        if isinstance(raw, str):
            return _FixRunResult(status="fixed", message=raw)
        return _FixRunResult(status="fixed", message="fixed")
    except Exception as exc:  # noqa: BLE001
        return _FixRunResult(
            status="fix_error",
            message=f"unexpected error: {exc}",
            exc_traceback=_traceback.format_exc(),
        )


def _normalise(cd: _CheckDef, raw: Any, elapsed_ms: float) -> _Result:
    if raw is None:
        return _Result(
            name=cd.name, status="ok", message="ok",
            hint=None, tag=cd.tag, duration_ms=elapsed_ms,
        )
    if isinstance(raw, str):
        return _Result(
            name=cd.name, status="ok", message=raw,
            hint=None, tag=cd.tag, duration_ms=elapsed_ms,
        )
    if isinstance(raw, CheckResult):
        return _Result(
            name=cd.name, status=raw.status, message=raw.message,
            hint=raw.hint, tag=cd.tag, duration_ms=elapsed_ms,
        )
    return _Result(
        name=cd.name, status="ok", message=str(raw),
        hint=None, tag=cd.tag, duration_ms=elapsed_ms,
    )
