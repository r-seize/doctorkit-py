"""doctorkit - terminal rendering.

All ANSI constants and output formatting live here.
No business logic, no I/O beyond writing to the provided stream.
"""
from __future__ import annotations

import xml.dom.minidom
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

from ._types import _FixRunResult, _Result

# ---------------------------------------------------------------------------
# ANSI escape codes
# ---------------------------------------------------------------------------

# Foreground colors - used for the summary line and inline tags (slow, etc.)
_COLORS: Dict[str, str] = {
    "ok":      "\033[32m",
    "warn":    "\033[33m",
    "fail":    "\033[31m",
    "skipped": "\033[90m",
    "error":   "\033[35m",
}

_RESET      = "\033[0m"
_BOLD       = "\033[1m"
_DIM        = "\033[2m"
_CLEAR_LINE = "\033[2K\r"  # erase current line, carriage-return

# ---------------------------------------------------------------------------
# Badge system - colored background labels instead of Unicode symbols
# ---------------------------------------------------------------------------

_BADGES: Dict[str, str] = {
    "ok":      "[GOOD]",
    "warn":    "[WARN]",
    "fail":    "[FAIL]",
    "skipped": "[SKIPPED]",
    "error":   "[ERROR]",
}

# Each entry is bg_color + fg_color (applied together before the label text)
_BADGE_COLORS: Dict[str, str] = {
    "ok":      "\033[42m\033[30m",   # green bg, black text
    "warn":    "\033[43m\033[30m",   # yellow bg, black text
    "fail":    "\033[41m\033[97m",   # red bg, bright-white text
    "skipped": "\033[44m\033[97m",   # blue bg, bright-white text
    "error":   "\033[45m\033[97m",   # magenta bg, bright-white text
}

# ---------------------------------------------------------------------------
# Fix badge system
# ---------------------------------------------------------------------------

_FIX_BADGES: Dict[str, str] = {
    "fixed":      "[FIXED]",
    "fix_failed": "[FIX FAILED]",
    "fix_error":  "[FIX ERROR]",
}

_FIX_BADGE_COLORS: Dict[str, str] = {
    "fixed":      "\033[42m\033[30m",   # green bg, black text
    "fix_failed": "\033[41m\033[97m",   # red bg, bright-white text
    "fix_error":  "\033[45m\033[97m",   # magenta bg, bright-white text
}

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _c(text: str, use_color: bool, color: str = "") -> str:
    """Wrap *text* with an ANSI *color* code if *use_color* is True."""
    return f"{color}{text}{_RESET}" if use_color and color else text


def _fix_badge(status: str, use_color: bool) -> str:
    """Return a colored-background label for a fix *status*."""
    label = _FIX_BADGES.get(status, f"[{status.upper()}]")
    if not use_color:
        return label
    color = _FIX_BADGE_COLORS.get(status, "")
    return f"{color}{label}{_RESET}"


def _badge(status: str, use_color: bool) -> str:
    """Return a colored-background label for *status*, or plain text if no color."""
    label = _BADGES.get(status, f"[{status.upper()}]")
    if not use_color:
        return label
    color = _BADGE_COLORS.get(status, "")
    return f"{color}{label}{_RESET}"


def _print_result(
    r: _Result,
    *,
    verbose: bool,
    use_color: bool,
    out: Any,
) -> None:
    b = _badge(r.status, use_color)

    if r.status == "ok":
        if r.is_slow:
            slow_tag = _c("<- slow", use_color, _COLORS["warn"])
            print(f"  {b} {r.name} ({r.duration_ms:.0f}ms) {slow_tag}", file=out)
        elif verbose:
            print(f"  {b} {r.name}: {r.message} ({r.duration_ms:.0f}ms)", file=out)
        else:
            print(f"  {b} {r.name}", file=out)
        return

    if r.status == "skipped":
        reason = f" ({r.skip_reason})" if r.skip_reason else ""
        print(
            f"  {b} {_c(r.name, use_color, _DIM)}{reason}",
            file=out,
        )
        return

    # fail / warn / error
    dur = f" ({r.duration_ms:.0f}ms)" if r.duration_ms else ""
    print(f"  {b} {r.name}: {r.message}{dur}", file=out)
    if r.hint:
        print(_c(f"    -> {r.hint}", use_color, _DIM), file=out)
    if r.status == "error" and verbose and r.exc_traceback:
        for line in r.exc_traceback.rstrip().splitlines():
            print(_c(f"    {line}", use_color, _DIM), file=out)


def _print_fix_section(
    results: List[_Result],
    *,
    use_color: bool,
    out: Any,
) -> None:
    """Print the [fixes] section for any result that has a fix_result."""
    fix_results = [r for r in results if r.fix_result is not None]
    if not fix_results:
        return
    print(f"\n{_c('[fixes]', use_color, _BOLD)}", file=out)
    for r in fix_results:
        fr: _FixRunResult = r.fix_result  # type: ignore[assignment]
        b = _fix_badge(fr.status, use_color)
        print(f"  {b} {r.name}: {fr.message}", file=out)
        if fr.status == "fix_error" and fr.exc_traceback:
            for line in fr.exc_traceback.rstrip().splitlines():
                print(_c(f"    {line}", use_color, _DIM), file=out)


def _render_junit_xml(results: List[_Result]) -> str:
    """Render check results as a JUnit XML string."""
    seen_tags: List[str] = []
    by_tag: Dict[str, List[_Result]] = {}
    for r in results:
        if r.tag not in by_tag:
            seen_tags.append(r.tag)
            by_tag[r.tag] = []
        by_tag[r.tag].append(r)

    root = ET.Element("testsuites")

    for tag in seen_tags:
        tag_results = by_tag[tag]
        suite = ET.SubElement(root, "testsuite")
        suite.set("name", tag)
        suite.set("tests", str(len(tag_results)))
        suite.set("failures", str(sum(1 for r in tag_results if r.status in ("fail", "error"))))
        suite.set("skipped", str(sum(1 for r in tag_results if r.status == "skipped")))
        suite.set("time", f"{sum(r.duration_ms for r in tag_results) / 1000:.3f}")

        for r in tag_results:
            tc = ET.SubElement(suite, "testcase")
            tc.set("name", r.name)
            tc.set("classname", tag)
            tc.set("time", f"{r.duration_ms / 1000:.3f}")

            if r.status == "skipped":
                el = ET.SubElement(tc, "skipped")
                if r.skip_reason:
                    el.set("message", r.skip_reason)
            elif r.status in ("fail", "error"):
                el = ET.SubElement(tc, "failure")
                el.set("message", r.message)
                if r.exc_traceback:
                    el.text = r.exc_traceback

    raw = ET.tostring(root, encoding="unicode")
    return xml.dom.minidom.parseString(raw).toprettyxml(indent="  ")
