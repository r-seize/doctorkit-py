#!/usr/bin/env python3
"""Example usage of doctorkit.

Demonstrates:
- Built-in check factories (env, filesystem, process, network)
- Fix callbacks
- warn_only checks
- depends_on dependency chains

Run:
    python examples/basic.py
    python examples/basic.py --json
    python examples/basic.py --verbose
    python examples/basic.py --only auth
    python examples/basic.py --skip dns-lookup
    python examples/basic.py --quiet
    python examples/basic.py --fail-fast
    python examples/basic.py --fix
    python examples/basic.py --list
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from doctorkit import Doctor
from doctorkit.checks.env import env_check
from doctorkit.checks.filesystem import dir_exists_check, writable_check
from doctorkit.checks.network import dns_check, http_check
from doctorkit.checks.process import command_check

doctor = Doctor()

# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------

doctor.add(
    "network-reachable",
    http_check("https://example.com", timeout=5),
    tag="network",
    slow_threshold_ms=2000,
)

doctor.add(
    "dns-lookup",
    dns_check("api.anthropic.com"),
    tag="network",
    depends_on=["network-reachable"],
)

# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

doctor.add(
    "api-key-set",
    env_check("ANTHROPIC_API_KEY", hint="Run: export ANTHROPIC_API_KEY=sk-ant-..."),
    tag="auth",
    depends_on=["network-reachable"],
)

doctor.add(
    "api-key-format",
    env_check("ANTHROPIC_API_KEY", pattern=r"sk-ant-.+"),
    tag="auth",
    depends_on=["api-key-set"],
    warn_only=True,
)

# ---------------------------------------------------------------------------
# filesystem
# ---------------------------------------------------------------------------

doctor.add(
    "config-dir",
    dir_exists_check(os.path.expanduser("~/.config")),
    tag="filesystem",
    fix_fn=lambda: os.makedirs(os.path.expanduser("~/.config"), exist_ok=True) or "created ~/.config",
)

doctor.add(
    "tmp-writable",
    writable_check("/tmp"),
    tag="filesystem",
)

# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

doctor.add(
    "python",
    command_check("python3", min_version="3.9"),
    tag="tools",
)

doctor.add(
    "git",
    command_check("git"),
    tag="tools",
)

# ---------------------------------------------------------------------------
# entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose your environment.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--only", nargs="+", metavar="TAG", help="Run only these tags.")
    parser.add_argument("--skip", nargs="+", metavar="CHECK", help="Skip checks by name.")
    parser.add_argument("--quiet", action="store_true", help="Print summary only.")
    parser.add_argument("--verbose", action="store_true", help="Show all checks with detail.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on first failure.")
    parser.add_argument("--fix", action="store_true", help="Run fix callbacks after failures.")
    parser.add_argument("--list", action="store_true", help="List registered checks and exit.")
    args = parser.parse_args()

    if args.list:
        for info in doctor.list_checks():
            deps = f" -> depends on {info.depends_on}" if info.depends_on else ""
            fix = " [fixable]" if info.has_fix else ""
            print(f"  [{info.tag}] {info.name}{deps}{fix}")
        sys.exit(0)

    code = doctor.run(
        only=args.only,
        skip=args.skip,
        quiet=args.quiet,
        verbose=args.verbose,
        json_output=args.json,
        fail_fast=args.fail_fast,
        fix=args.fix,
    )
    sys.exit(code)
