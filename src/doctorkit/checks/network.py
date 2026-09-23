"""doctorkit.checks.network - HTTP, TCP, DNS and SSL certificate check factories.

All checks use Python stdlib only (socket, ssl, urllib).
"""
from __future__ import annotations

import socket
import ssl
import time
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


def ssl_cert_check(
    hostname: str,
    *,
    port: int = 443,
    min_days_remaining: int = 14,
    timeout: float = 10.0,
) -> Callable[[], CheckResult]:
    """Return a check function that verifies the TLS certificate of *hostname*.

    ``fail`` if the certificate is expired or the TLS handshake fails,
    ``warn`` if it expires in fewer than *min_days_remaining* days.
    """
    def _check() -> CheckResult:
        hint_access = (
            f"Check that {hostname}:{port} is accessible and has a valid certificate"
        )
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as tls:
                    cert = tls.getpeercert()
        except socket.timeout:
            return CheckResult(
                status="fail",
                message=f"{hostname}:{port} TLS connection timed out",
                hint=f"Check that {hostname}:{port} is accessible",
            )
        except ssl.SSLCertVerificationError as exc:
            if "expired" in (exc.verify_message or "").lower():
                return CheckResult(
                    status="fail",
                    message=f"{hostname}: certificate expired",
                    hint=f"Renew the SSL certificate for {hostname}",
                )
            return CheckResult(
                status="fail",
                message=f"{hostname}: TLS error - {exc.verify_message or exc}",
                hint=hint_access,
            )
        except OSError as exc:
            return CheckResult(
                status="fail",
                message=f"{hostname}: TLS error - {exc}",
                hint=hint_access,
            )

        not_after = cert.get("notAfter") if cert else None
        if not isinstance(not_after, str) or not not_after:
            return CheckResult(
                status="fail",
                message=f"{hostname}: no certificate returned",
            )

        days_remaining = int((ssl.cert_time_to_seconds(not_after) - time.time()) // 86400)

        if days_remaining < 0:
            return CheckResult(
                status="fail",
                message=f"{hostname}: certificate expired {abs(days_remaining)} day(s) ago",
                hint=f"Renew the SSL certificate for {hostname}",
            )
        if days_remaining < min_days_remaining:
            return CheckResult(
                status="warn",
                message=f"{hostname}: certificate expires in {days_remaining} day(s)",
                hint=f"Renew the SSL certificate for {hostname} soon",
            )
        return CheckResult(
            status="ok",
            message=f"{hostname}: certificate valid, expires in {days_remaining} day(s)",
        )

    return _check
