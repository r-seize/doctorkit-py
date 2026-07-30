"""doctorkit CLI entry point."""
from __future__ import annotations

import sys

from ._init import cmd_init


_USAGE = """\
doctorkit <command> [args]

Commands:
  init [path]   Scan a project directory and generate a starter doctor.py.
                path defaults to the current directory.
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(_USAGE)
        return

    command = args[0]
    rest = args[1:]

    if command == "init":
        cmd_init(rest[0] if rest else ".")
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        sys.exit(1)
