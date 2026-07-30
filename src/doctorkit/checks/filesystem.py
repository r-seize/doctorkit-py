"""doctorkit.checks.filesystem - file and directory check factories."""
from __future__ import annotations

import os
from typing import Callable

from .._types import CheckResult


def dir_exists_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is an existing directory."""
    def _check() -> CheckResult:
        if os.path.isdir(path):
            return CheckResult(status="ok", message=f"{path} exists")
        if os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} exists but is not a directory",
            )
        return CheckResult(
            status="fail",
            message=f"{path} does not exist",
            hint=f"Run: mkdir -p {path}",
        )

    return _check


def file_exists_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is an existing file."""
    def _check() -> CheckResult:
        if os.path.isfile(path):
            return CheckResult(status="ok", message=f"{path} exists")
        if os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} exists but is not a file",
            )
        return CheckResult(
            status="fail",
            message=f"{path} not found",
        )

    return _check


def writable_check(path: str) -> Callable[[], CheckResult]:
    """Return a check function that verifies *path* is writable by the current user."""
    def _check() -> CheckResult:
        if not os.path.exists(path):
            return CheckResult(
                status="fail",
                message=f"{path} does not exist",
                hint=f"Run: mkdir -p {path}",
            )
        if os.access(path, os.W_OK):
            return CheckResult(status="ok", message=f"{path} is writable")
        return CheckResult(
            status="fail",
            message=f"{path} is not writable",
            hint=f"Run: chmod u+w {path}",
        )

    return _check
