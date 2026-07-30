"""doctorkit - Doctor class.

Orchestrates registration, filtering, execution order, and output.
Delegates to _executor for running checks and _renderer for display.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from ._types import (
    CheckInfo,
    CheckRecord,
    CheckResult,
    RunResult,
    RunSummary,
    _CheckDef,
    _Result,
)
from ._executor import _run_check, _run_fix, _topo_sort, _compute_waves
from ._renderer import (
    _BOLD,
    _CLEAR_LINE,
    _COLORS,
    _RESET,
    _c,
    _print_fix_section,
    _print_result,
    _render_junit_xml,
)

_F = TypeVar("_F", bound=Callable[..., Any])


class Doctor:
    """Health-check engine.

    Register checks with ``@doctor.check(...)`` (decorator API) or
    ``doctor.add(...)`` (programmatic API), then call ``doctor.run()``.
    """

    def __init__(self) -> None:
        self._checks: List[_CheckDef] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def check(
        self,
        name: str,
        *,
        tag: str = "general",
        depends_on: Optional[List[str]] = None,
        warn_only: bool = False,
        timeout: float = 5.0,
        retries: int = 0,
        retry_delay: float = 1.0,
        slow_threshold_ms: Optional[float] = None,
        fix_fn: Optional[Callable[[], Any]] = None,
    ) -> Callable[[_F], _F]:
        """Decorator that registers a check function."""

        def _decorator(fn: _F) -> _F:
            self._checks.append(
                _CheckDef(
                    name=name,
                    fn=fn,  # type: ignore[arg-type]
                    tag=tag,
                    depends_on=depends_on or [],
                    warn_only=warn_only,
                    timeout=timeout,
                    retries=retries,
                    retry_delay=retry_delay,
                    slow_threshold_ms=slow_threshold_ms,
                    fix_fn=fix_fn,
                )
            )
            return fn

        return _decorator

    def add(
        self,
        name: str,
        fn: Callable[[], Any],
        *,
        tag: str = "general",
        depends_on: Optional[List[str]] = None,
        warn_only: bool = False,
        timeout: float = 5.0,
        retries: int = 0,
        retry_delay: float = 1.0,
        slow_threshold_ms: Optional[float] = None,
        fix_fn: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Programmatic alternative to ``@doctor.check``.

        Useful when check functions are dynamically generated or when the
        decorator syntax is inconvenient (e.g. inside a loop).
        """
        self._checks.append(
            _CheckDef(
                name=name,
                fn=fn,
                tag=tag,
                depends_on=depends_on or [],
                warn_only=warn_only,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
                slow_threshold_ms=slow_threshold_ms,
                fix_fn=fix_fn,
            )
        )

    def list_checks(self) -> List[CheckInfo]:
        """Return metadata for all registered checks without executing them."""
        return [
            CheckInfo(
                name=c.name,
                tag=c.tag,
                depends_on=list(c.depends_on),
                warn_only=c.warn_only,
                timeout=c.timeout,
                retries=c.retries,
                retry_delay=c.retry_delay,
                slow_threshold_ms=c.slow_threshold_ms,
                has_fix=c.fix_fn is not None,
            )
            for c in self._checks
        ]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
        quiet: bool = False,
        verbose: bool = False,
        json_output: bool = False,
        junit_xml: bool = False,
        fail_fast: bool = False,
        max_failures: Optional[int] = None,
        slow_threshold_ms: Optional[float] = None,
        global_timeout: Optional[float] = None,
        max_concurrency: int = 1,
        fix: bool = False,
        json_file: Optional[str] = None,
        junit_file: Optional[str] = None,
        output: Any = None,
    ) -> int:
        """Execute checks and print results.

        Returns:
            ``0`` - all checks ok or warn.
            ``1`` - at least one check failed.
            ``2`` - at least one check raised an unexpected exception.
        """
        exit_code, _, _ = self._execute(
            only=only,
            skip=skip,
            quiet=quiet,
            verbose=verbose,
            json_output=json_output,
            junit_xml=junit_xml,
            fail_fast=fail_fast,
            max_failures=max_failures,
            slow_threshold_ms=slow_threshold_ms,
            global_timeout=global_timeout,
            max_concurrency=max_concurrency,
            fix=fix,
            json_file=json_file,
            junit_file=junit_file,
            output=output,
        )
        return exit_code

    def run_detailed(
        self,
        *,
        only: Optional[List[str]] = None,
        skip: Optional[List[str]] = None,
        quiet: bool = False,
        verbose: bool = False,
        json_output: bool = False,
        junit_xml: bool = False,
        fail_fast: bool = False,
        max_failures: Optional[int] = None,
        slow_threshold_ms: Optional[float] = None,
        global_timeout: Optional[float] = None,
        max_concurrency: int = 1,
        fix: bool = False,
        json_file: Optional[str] = None,
        junit_file: Optional[str] = None,
        output: Any = None,
    ) -> RunResult:
        """Execute checks and return structured results.

        Accepts the same parameters as :py:meth:`run`.  The return value
        gives programmatic access to every check result, summary counts,
        and the exit code - without having to capture and parse stdout.

        Returns:
            :py:class:`RunResult` with ``exit_code``, ``summary``,
            ``checks`` (one :py:class:`CheckRecord` per check), and
            ``total_ms``.
        """
        exit_code, all_results, total_ms = self._execute(
            only=only,
            skip=skip,
            quiet=quiet,
            verbose=verbose,
            json_output=json_output,
            junit_xml=junit_xml,
            fail_fast=fail_fast,
            max_failures=max_failures,
            slow_threshold_ms=slow_threshold_ms,
            global_timeout=global_timeout,
            max_concurrency=max_concurrency,
            fix=fix,
            json_file=json_file,
            junit_file=junit_file,
            output=output,
        )
        return RunResult(
            exit_code=exit_code,
            summary=RunSummary(
                ok=sum(1 for r in all_results if r.status == "ok"),
                warn=sum(1 for r in all_results if r.status == "warn"),
                fail=sum(1 for r in all_results if r.status in ("fail", "error")),
                skipped=sum(1 for r in all_results if r.status == "skipped"),
                slow=sum(1 for r in all_results if r.is_slow),
            ),
            checks=[
                CheckRecord(
                    name=r.name,
                    status=r.status,
                    message=r.message,
                    hint=r.hint,
                    tag=r.tag,
                    duration_ms=r.duration_ms,
                    is_slow=r.is_slow,
                    skip_reason=r.skip_reason,
                    fix_status=r.fix_result.status if r.fix_result else None,
                    fix_message=r.fix_result.message if r.fix_result else None,
                )
                for r in all_results
            ],
            total_ms=total_ms,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _execute(
        self,
        *,
        only: Optional[List[str]],
        skip: Optional[List[str]],
        quiet: bool,
        verbose: bool,
        json_output: bool,
        junit_xml: bool,
        fail_fast: bool,
        max_failures: Optional[int],
        slow_threshold_ms: Optional[float],
        global_timeout: Optional[float],
        max_concurrency: int,
        fix: bool,
        json_file: Optional[str],
        junit_file: Optional[str],
        output: Any,
    ) -> Tuple[int, List[_Result], float]:
        """Core execution logic. Returns (exit_code, all_results, total_ms)."""
        out = output if output is not None else sys.stdout
        use_color = (
            not json_output
            and not junit_xml
            and hasattr(out, "isatty")
            and out.isatty()
        )
        use_spinner = use_color and not quiet and max_concurrency == 1

        checks = list(self._checks)
        if only:
            only_set = set(only)
            checks = [c for c in checks if c.tag in only_set]
        if skip:
            skip_set = set(skip)
            checks = [c for c in checks if c.name not in skip_set]

        checks = _topo_sort(checks)

        if max_concurrency > 1:
            waves = _compute_waves(checks)
        else:
            waves = [[c] for c in checks]

        done: Dict[str, _Result] = {}
        all_results: List[_Result] = []
        error_occurred = False
        current_tag: Optional[str] = None
        stopped_early = False
        fail_count = 0
        t0_total = time.monotonic()

        for wave in waves:
            to_run: List[_CheckDef] = []
            skip_reason_map: Dict[str, str] = {}

            for cd in wave:
                reason: Optional[str] = None

                if stopped_early:
                    reason = "fail_fast: stopped after first failure"
                elif (
                    global_timeout is not None
                    and all_results
                    and (time.monotonic() - t0_total) > global_timeout
                ):
                    reason = "global timeout exceeded"
                else:
                    for dep in cd.depends_on:
                        dep_r = done.get(dep)
                        if dep_r is None:
                            continue
                        if dep_r.status in ("fail", "error"):
                            reason = f"depends on '{dep}' which failed"
                            break
                        if dep_r.status == "skipped":
                            reason = f"depends on '{dep}' which was skipped"
                            break

                if reason:
                    skip_reason_map[cd.name] = reason
                else:
                    to_run.append(cd)

            run_result_map: Dict[str, _Result] = {}

            if max_concurrency > 1 and len(to_run) > 1:
                workers = min(max_concurrency, len(to_run))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_cd = {executor.submit(_run_check, cd): cd for cd in to_run}
                    for future in concurrent.futures.as_completed(future_to_cd):
                        cd_f = future_to_cd[future]
                        run_result_map[cd_f.name] = future.result()
            else:
                for cd in to_run:
                    if use_spinner:
                        out.write(f"  ⟳ {cd.name}: running...")
                        out.flush()
                    r = _run_check(cd)
                    if use_spinner:
                        out.write(_CLEAR_LINE)
                        out.flush()
                    run_result_map[cd.name] = r

            for cd in wave:
                if cd.name in skip_reason_map:
                    r = _Result(
                        name=cd.name,
                        status="skipped",
                        message="",
                        hint=None,
                        tag=cd.tag,
                        duration_ms=0.0,
                        skip_reason=skip_reason_map[cd.name],
                    )
                else:
                    r = run_result_map[cd.name]
                    if r.status == "error":
                        error_occurred = True
                    if cd.warn_only and r.status == "fail":
                        r = dataclasses.replace(r, status="warn")
                    threshold = (
                        cd.slow_threshold_ms
                        if cd.slow_threshold_ms is not None
                        else slow_threshold_ms
                    )
                    if threshold is not None and r.status == "ok" and r.duration_ms > threshold:
                        r = dataclasses.replace(r, is_slow=True)

                    if r.status in ("fail", "error"):
                        fail_count += 1
                        if fail_fast or (max_failures is not None and fail_count >= max_failures):
                            stopped_early = True

                done[cd.name] = r
                all_results.append(r)

                if not json_output and not junit_xml and not quiet:
                    if cd.tag != current_tag:
                        current_tag = cd.tag
                        print(
                            f"\n{_c(f'[{current_tag}]', use_color, _BOLD)}",
                            file=out,
                        )
                    _print_result(r, verbose=verbose, use_color=use_color, out=out)

        total_ms = (time.monotonic() - t0_total) * 1000

        ok_n = sum(1 for r in all_results if r.status == "ok")
        warn_n = sum(1 for r in all_results if r.status == "warn")
        fail_n = sum(1 for r in all_results if r.status in ("fail", "error"))
        skip_n = sum(1 for r in all_results if r.status == "skipped")
        slow_n = sum(1 for r in all_results if r.is_slow)

        exit_code = 2 if error_occurred else (1 if fail_n > 0 else 0)

        def_by_name: Dict[str, _CheckDef] = {c.name: c for c in checks}

        if fix:
            for i, r in enumerate(all_results):
                if r.status not in ("fail", "error"):
                    continue
                cd_fix = def_by_name.get(r.name)
                if cd_fix is None or cd_fix.fix_fn is None:
                    continue
                fr = _run_fix(cd_fix.fix_fn)
                all_results[i] = dataclasses.replace(r, fix_result=fr)

        # Build JSON payload (always, so it's available for file output even
        # when json_output=False).
        _payload = {
            "checks": [
                {
                    "name": r.name,
                    "status": r.status,
                    "message": r.message,
                    "hint": r.hint,
                    "tag": r.tag,
                    "duration_ms": round(r.duration_ms, 1),
                    "is_slow": r.is_slow,
                    "fix_status": r.fix_result.status if r.fix_result else None,
                    "fix_message": r.fix_result.message if r.fix_result else None,
                }
                for r in all_results
            ],
            "summary": {
                "ok": ok_n,
                "warn": warn_n,
                "fail": fail_n,
                "skipped": skip_n,
                "slow": slow_n,
            },
            "exit_code": exit_code,
        }

        if junit_xml:
            print(_render_junit_xml(all_results), file=out)
        elif json_output:
            print(json.dumps(_payload, indent=2), file=out)
        else:
            parts: List[str] = []
            if ok_n:
                parts.append(_c(f"{ok_n} ok", use_color, _COLORS["ok"]))
            if warn_n:
                parts.append(_c(f"{warn_n} warn", use_color, _COLORS["warn"]))
            if fail_n:
                parts.append(_c(f"{fail_n} fail", use_color, _COLORS["fail"]))
            if skip_n:
                parts.append(_c(f"{skip_n} skipped", use_color, _COLORS["skipped"]))
            if slow_n:
                parts.append(_c(f"{slow_n} slow", use_color, _COLORS["warn"]))
            print(f"\n{', '.join(parts)} - {total_ms:.0f}ms total", file=out)
            if fix:
                _print_fix_section(all_results, use_color=use_color, out=out)

        # File output - additive, independent of stdout output format.
        if json_file:
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(_payload, f, indent=2)
        if junit_file:
            with open(junit_file, "w", encoding="utf-8") as f:
                f.write(_render_junit_xml(all_results))

        return exit_code, all_results, total_ms
