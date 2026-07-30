"""doctorkit.checks.network - HTTP, TCP and DNS check factories.

All checks use Python stdlib only (socket, urllib).
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request
from typing import Callable

from .._types import CheckResult


def http_check(
    url: str,
    *,
    expected_status: int = 200,
    timeout: float = 10.0,
) -> Callable[[], CheckResult]:
    """Return a check function that verifies *url* responds with *expected_status*.

    Uses HTTP HEAD by default to avoid downloading the body.
    Falls back gracefully if the server rejects HEAD.
    """
    def _check() -> CheckResult:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = resp.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except urllib.error.URLError as exc:
            return CheckResult(
                status="fail",
                message=str(exc.reason),
                hint=f"Check that {url} is accessible",
            )
        except OSError as exc:
            return CheckResult(
                status="fail",
                message=str(exc),
                hint=f"Check that {url} is accessible",
            )

        if code == expected_status:
            return CheckResult(status="ok", message=f"HTTP {code}")
        return CheckResult(
            status="fail",
            message=f"HTTP {code} (expected {expected_status})",
            hint=f"URL: {url}",
        )

    return _check


def tcp_check(
    host: str,
    port: int,
    *,
    timeout: float = 5.0,
) -> Callable[[], CheckResult]:
    """Return a check function that opens a TCP connection to *host*:*port*."""
    def _check() -> CheckResult:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return CheckResult(status="ok", message=f"{host}:{port} reachable")
        except OSError as exc:
            return CheckResult(
                status="fail",
                message=f"{host}:{port} unreachable: {exc}",
                hint=f"Ensure the service is running on {host}:{port}",
            )

    return _check


def dns_check(hostname: str) -> Callable[[], CheckResult]:
    """Return a check function that resolves *hostname* via DNS."""
    def _check() -> CheckResult:
        try:
            socket.getaddrinfo(hostname, None)
            return CheckResult(status="ok", message=f"{hostname} resolved")
        except socket.gaierror as exc:
            return CheckResult(
                status="fail",
                message=f"DNS lookup failed for {hostname}: {exc}",
                hint="Check your DNS configuration or network connectivity",
            )

    return _check
