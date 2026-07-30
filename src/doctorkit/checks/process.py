"""doctorkit.checks.process - command availability and version check factories."""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, Optional, Tuple

from .._types import CheckResult


def command_check(
    cmd: str,
    *,
    min_version: Optional[str] = None,
    version_flag: str = "--version",
) -> Callable[[], CheckResult]:
    """Return a check function that verifies *cmd* is on PATH.

    If *min_version* is given (e.g. "18.0"), the reported version must be
    greater than or equal to it.  Version strings are compared numerically
    segment by segment (X.Y.Z).
    """
    def _check() -> CheckResult:
        path = shutil.which(cmd)
        if path is None:
            return CheckResult(
                status="fail",
                message=f"{cmd} not found on PATH",
                hint=f"Install {cmd} and ensure it is on your PATH",
            )

        if min_version is None:
            return CheckResult(status="ok", message=f"{cmd} found at {path}")

        try:
            result = subprocess.run(
                [cmd, version_flag],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = (result.stdout + result.stderr).strip().split("\n")[0]
            version = _extract_version(first_line)

            if version is None:
                return CheckResult(
                    status="warn",
                    message=f"{cmd} found but version unreadable: {first_line!r}",
                )
            if _version_gte(version, min_version):
                return CheckResult(status="ok", message=f"{cmd} {version}")
            return CheckResult(
                status="fail",
                message=f"{cmd} {version} is below minimum {min_version}",
                hint=f"Upgrade {cmd} to {min_version} or higher",
            )
        except Exception as exc:  # noqa: BLE001
            return CheckResult(
                status="warn",
                message=f"{cmd} found but version check failed: {exc}",
            )

    return _check


def _extract_version(text: str) -> Optional[str]:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", text)
    return m.group(1) if m else None


def _version_gte(v: str, minimum: str) -> bool:
    def parse(s: str) -> Tuple[int, ...]:
        return tuple(int(x) for x in s.split("."))
    try:
        return parse(v) >= parse(minimum)
    except ValueError:
        return False
