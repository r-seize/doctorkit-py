# doctorkit · Python

> Health-check engine for CLI tools - declare checks, get structured diagnostics with zero dependencies.

**Also available in TypeScript/Node.js** -> [doctorkit-ts](https://github.com/r-seize/doctorkit-ts)


## Table of contents

- [What is doctorkit?](#what-is-doctorkit)
- [Install](#install)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Check registration](#check-registration)
  - [Decorator syntax](#decorator-syntax)
  - [Programmatic syntax (add)](#programmatic-syntax-add)
  - [Check parameters](#check-parameters)
  - [Return values](#return-values)
- [Running checks](#running-checks)
  - [Run parameters](#run-parameters)
  - [Filtering: only and skip](#filtering-only-and-skip)
  - [Dependency chains](#dependency-chains)
  - [Timeouts and retries](#timeouts-and-retries)
  - [Parallel execution (max_concurrency)](#parallel-execution-max_concurrency)
  - [Slow check detection](#slow-check-detection)
  - [Stop early: fail_fast and max_failures](#stop-early-fail_fast-and-max_failures)
  - [Global timeout](#global-timeout)
  - [File output](#file-output)
  - [Programmatic access: run_detailed()](#programmatic-access-run_detailed)
- [Output formats](#output-formats)
  - [Human output (default)](#human-output-default)
  - [Verbose mode](#verbose-mode)
  - [Quiet mode](#quiet-mode)
  - [JSON output](#json-output)
  - [JUnit XML output](#junit-xml-output)
- [Exit codes](#exit-codes)
- [Listing checks without running](#listing-checks-without-running)
- [Fix callbacks](#fix-callbacks)
- [Built-in check library](#built-in-check-library)
- [CLI: doctorkit init](#cli-doctorkit-init)
- [API reference](#api-reference)
- [Also available in TypeScript](#also-available-in-typescript)


## What is doctorkit?

Every serious CLI eventually ships a `doctor` subcommand - a self-diagnostic that tells users exactly why something isn't working. The problem: every team reimplements the same mechanics from scratch.

**doctorkit** is that shared engine. You declare the checks; it handles everything else:

- Running checks grouped by tag with live terminal output
- Skipping downstream checks when a dependency fails (no point checking auth if the network is down)
- Per-check timeouts with configurable retries
- Parallel wave-based execution across independent checks
- Flagging checks that pass but take too long
- Emitting structured JSON or JUnit XML for CI pipelines
- Consistent exit codes (`0` ok, `1` fail, `2` exception in a check)
- Stopping early when a threshold of failures is reached

It ships **zero** domain checks and has **zero** runtime dependencies. It has no opinion about what your tool needs to verify - that's entirely up to you.

```
[network]
  [GOOD] network-reachable
  [GOOD] dns-lookup

[auth]
  [FAIL] api-key-set: ANTHROPIC_API_KEY is not set (12ms)
    -> Run: export ANTHROPIC_API_KEY=sk-ant-...
  [SKIPPED] api-key-format (depends on 'api-key-set' which failed)

[filesystem]
  [GOOD] config-dir
  [GOOD] tmp-writable

2 ok, 1 fail, 1 skipped - 347ms total
```


## Install

```bash
pip install doctorkit-core
```

Requires Python >= 3.9. Zero runtime dependencies.


## Quick start

```python
import os
import sys
from doctorkit import Doctor, CheckResult

doctor = Doctor()


@doctor.check("network-reachable", tag="network", timeout=5)
def check_network_reachable():
    import urllib.request
    try:
        urllib.request.urlopen("https://example.com", timeout=3)
        return CheckResult(status="ok", message="internet reachable")
    except Exception as e:
        return CheckResult(
            status="fail",
            message=f"cannot reach internet: {e}",
            hint="Check your network connection or proxy settings.",
        )


# Only runs if network-reachable passed
@doctor.check("api-key-set", tag="auth", depends_on=["network-reachable"])
def check_api_key():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return CheckResult(
            status="fail",
            message="ANTHROPIC_API_KEY is not set",
            hint="Run: export ANTHROPIC_API_KEY=sk-ant-...",
        )
    return CheckResult(status="ok", message=f"API key found ({key[:8]}...)")


# warn_only: failure is downgraded to warn, exit code stays 0
@doctor.check("config-dir", tag="filesystem", warn_only=True)
def check_config_dir():
    path = os.path.expanduser("~/.config")
    if not os.path.isdir(path):
        return CheckResult(status="fail", message=f"{path} missing", hint=f"mkdir -p {path}")
    return CheckResult(status="ok", message=f"{path} found")


# Wire into your CLI parser - doctorkit never owns the CLI
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument("--only", nargs="+")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()

    if args.list:
        for info in doctor.list_checks():
            print(f"{info.tag}/{info.name}")
        sys.exit(0)

    sys.exit(
        doctor.run(
            json_output=args.json,
            only=args.only,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    )
```


## How it works

1. You register checks with `@doctor.check(...)` (decorator) or `doctor.add(...)` (programmatic). Each check has a name, a tag (group), optional dependencies, and a callable.
2. When you call `doctor.run()`, doctorkit topologically sorts the checks to respect their `depends_on` relationships, then executes them.
3. If a check's dependency has `fail`, `error`, or `skipped` status, the check is cascade-skipped automatically.
4. Results are printed live grouped by tag with colored symbols. At the end, a summary line shows counts and total duration.
5. The return value of `run()` is an integer exit code you can pass to `sys.exit()`.


## Check registration

### Decorator syntax

```python
@doctor.check("my-check", tag="network", timeout=10)
def check_something():
    # return a CheckResult, a string, or None
    return CheckResult(status="ok", message="looking good")
```

The decorator is **transparent**: it returns the original function unchanged, so type checkers (Pylance, mypy) retain its full signature.

### Programmatic syntax (add)

```python
# Useful inside loops or when generating checks dynamically
for port in [5432, 6379, 9200]:
    doctor.add(
        f"port-{port}",
        make_port_check(port),
        tag="deps",
    )
```

`add()` accepts the same keyword arguments as `@doctor.check`.

### Check parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Unique identifier shown in output |
| `tag` | `str` | `"general"` | Category for visual grouping and `only` filter |
| `depends_on` | `list[str]` | `[]` | Check names that must not have failed before this one runs |
| `warn_only` | `bool` | `False` | Downgrade a `fail` result to `warn` - exit code stays `0` |
| `timeout` | `float` | `5.0` | Seconds before the check is abandoned and recorded as `fail` |
| `retries` | `int` | `0` | Extra attempts on failure (0 = one attempt total) |
| `retry_delay` | `float` | `1.0` | Seconds to wait between retries |
| `slow_threshold_ms` | `float \| None` | `None` | Flag this check as slow if it passes but takes longer than this many ms. Overrides any global threshold. |
| `fix_fn` | `callable \| None` | `None` | Optional repair function. Called automatically when `run(fix=True)` and this check fails. See [Fix callbacks](#fix-callbacks). |

### Return values

A check function may return:

| Return value | Recorded as |
|---|---|
| `CheckResult(status="ok", message="...")` | ok |
| `CheckResult(status="warn", message="...", hint="...")` | warn |
| `CheckResult(status="fail", message="...", hint="...")` | fail |
| A string | ok, with that string as message |
| `None` | ok |
| Raises an exception | error (exit code 2) |

The `hint` field appears indented below the check line - use it for actionable fix instructions.


## Running checks

### Run parameters

```python
exit_code = doctor.run(
    only=["network", "auth"],      # run only these tags
    skip=["slow-check"],           # skip these check names
    quiet=False,                   # summary only
    verbose=False,                 # full detail including durations
    json_output=False,             # structured JSON output
    junit_xml=False,               # JUnit XML output (for CI)
    json_file="results.json",      # also write JSON to this file
    junit_file="results.xml",      # also write JUnit XML to this file
    fail_fast=False,               # stop after first failure
    max_failures=3,                # stop after 3 cumulative failures
    slow_threshold_ms=500,         # flag checks taking over 500ms
    global_timeout=30.0,           # skip remaining after 30s wall-clock
    max_concurrency=4,             # run up to 4 checks in parallel
    output=sys.stdout,             # where to write (defaults to sys.stdout)
)
```

### Filtering: only and skip

```python
# Run only the "network" and "auth" groups
doctor.run(only=["network", "auth"])

# Skip specific checks by name
doctor.run(skip=["slow-check", "optional-check"])
```

`only` matches the check's `tag`. `skip` matches the check's `name`. Both can be combined.

### Dependency chains

When check B declares `depends_on=["a"]`, doctorkit:
1. Automatically runs A before B regardless of registration order.
2. Cascade-skips B (and anything depending on B) if A has status `fail`, `error`, or `skipped`.
3. Allows B to run normally if A has status `warn`.

```python
@doctor.check("db-reachable", tag="database")
def check_db():
    ...

# Only runs if db-reachable passed
@doctor.check("db-migrated", tag="database", depends_on=["db-reachable"])
def check_migrations():
    ...

# Only runs if both above passed
@doctor.check("db-seeded", tag="database", depends_on=["db-migrated"])
def check_seed_data():
    ...
```

Cycles are silently broken (the involved check still runs).

### Timeouts and retries

```python
@doctor.check(
    "flaky-api",
    tag="external",
    timeout=10,       # fail if the check takes more than 10s
    retries=3,        # retry up to 3 times on fail or exception
    retry_delay=2.0,  # wait 2s between retries
)
def check_external_api():
    import urllib.request
    resp = urllib.request.urlopen("https://api.example.com/health", timeout=8)
    if resp.status != 200:
        return CheckResult(status="fail", message=f"HTTP {resp.status}")
    return CheckResult(status="ok", message="API healthy")
```

On timeout, the check is immediately recorded as `fail` (`"timeout after Xs"`). Each retry starts a fresh attempt; if any attempt returns `ok` or `warn`, the loop stops early. Timeout is enforced with a background thread - your check function runs in the thread, and the timeout waits on a threading event.

### Parallel execution (max_concurrency)

By default, checks run sequentially. Set `max_concurrency` to run independent checks in parallel:

```python
doctor.run(max_concurrency=8)
```

doctorkit uses **wave-based DAG scheduling** backed by `concurrent.futures.ThreadPoolExecutor`:
- Wave 0: all checks with no dependencies
- Wave 1: checks whose dependencies are all in wave 0
- Wave N: checks whose dependencies are all in earlier waves

All checks within the same wave are independent and run concurrently up to `max_concurrency` threads. Waves are executed in order, so dependency constraints are always respected.

This is particularly useful when checks involve I/O: network calls, database pings, file-system probes. For CPU-bound checks, the GIL limits true parallelism - use threads for I/O, processes for CPU.

### Slow check detection

Flag checks that pass but take too long:

```python
# Global threshold: any check taking over 500ms is flagged
doctor.run(slow_threshold_ms=500)
```

```python
# Per-check override: takes precedence over the global threshold
@doctor.check("cold-cache-query", tag="database", slow_threshold_ms=2000)
def check_cold_cache():
    ...  # allow up to 2s for this one
```

Slow checks appear with `<- slow` and their duration even in non-verbose mode. The summary line includes a `slow` count.

### Stop early: fail_fast and max_failures

```python
# Stop after the very first failure
doctor.run(fail_fast=True)

# Stop after 3 cumulative failures/errors
doctor.run(max_failures=3)
```

After stopping, all remaining checks are recorded as `skipped` in the output. `fail_fast=True` is equivalent to `max_failures=1`.

### Global timeout

Stop scheduling new checks once the total wall-clock time exceeds the budget:

```python
# If the run takes more than 30s, remaining unstarted checks are skipped
doctor.run(global_timeout=30.0)
```

The first check always runs regardless. Running checks are not interrupted - the timeout only prevents new checks from starting.

### File output

Write results to a file independently of what is printed to stdout:

```python
# Write JSON to a file - human output still goes to stdout
doctor.run(json_file="results/checks.json")

# Write JUnit XML to a file for CI artifact upload
doctor.run(junit_file="test-results/doctorkit.xml")

# Both files at once, human output on stdout
doctor.run(json_file="results.json", junit_file="results.xml")

# json_file + json_output stdout are independent
doctor.run(json_output=True, json_file="results.json")
```

`json_file` and `junit_file` are fully independent of the `json_output` and `junit_xml` stdout options. All combinations are valid.

### Programmatic access: run_detailed()

Use `run_detailed()` to get structured data from the run instead of just an exit code:

```python
from doctorkit import Doctor, RunResult

result: RunResult = doctor.run_detailed()

print(result.exit_code)       # 0, 1, or 2
print(result.summary.ok)      # count of passing checks
print(result.summary.fail)    # count of failed checks
print(result.total_ms)        # total wall-clock time in ms

for check in result.checks:
    if check.status == "fail":
        print(f"{check.name}: {check.message}")

sys.exit(result.exit_code)
```

Accepts exactly the same parameters as `run()`. Both produce identical output - the only difference is what they return.


## Output formats

### Human output (default)

Checks are printed grouped by tag as they complete. Each check line starts with a colored badge:

| Badge | Background | Meaning |
|-------|-----------|---------|
| `[GOOD]` | green | ok |
| `[WARN]` | yellow | warn |
| `[FAIL]` | red | fail |
| `[ERROR]` | magenta | unexpected exception in the check |
| `[SKIPPED]` | blue | skipped (cascade or early stop) |

Badges are colored only when writing to a TTY. In non-TTY mode (CI, pipes, redirects) the plain text label is used.

```
[network]
  [GOOD] network-reachable
  [FAIL] dns-lookup: NXDOMAIN (34ms)
    -> Check your /etc/resolv.conf

[auth]
  [SKIPPED] api-key-set (depends on 'dns-lookup' which failed)

1 ok, 1 fail, 1 skipped - 201ms total
```

### Verbose mode

`verbose=True` shows the message and duration for every check, not just failures. Exceptions include the full Python traceback.

```
[network]
  [GOOD] network-reachable: internet reachable (45ms)
  [FAIL] dns-lookup: NXDOMAIN (34ms)
    -> Check your /etc/resolv.conf
    Traceback (most recent call last):
      ...
    socket.gaierror: [Errno -2] Name or service not known
```

### Quiet mode

`quiet=True` hides all check detail and prints only the summary line:

```
1 ok, 1 fail, 1 skipped - 201ms total
```

### JSON output

`json_output=True` emits a single JSON object to stdout. No human-readable output is produced.

```json
{
  "checks": [
    {
      "name": "api-key-set",
      "status": "fail",
      "message": "ANTHROPIC_API_KEY is not set",
      "hint": "Run: export ANTHROPIC_API_KEY=sk-ant-...",
      "tag": "auth",
      "duration_ms": 12.0,
      "is_slow": false,
      "fix_status": null,
      "fix_message": null
    }
  ],
  "summary": {
    "ok": 1,
    "warn": 0,
    "fail": 1,
    "skipped": 1,
    "slow": 0
  },
  "exit_code": 1
}
```

### JUnit XML output

`junit_xml=True` emits JUnit-compatible XML - readable by most CI systems (GitHub Actions, Jenkins, GitLab CI, etc.).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="auth" tests="2" failures="1" skipped="0" time="0.045">
    <testcase name="api-key-set" classname="auth" time="0.012">
      <failure message="ANTHROPIC_API_KEY is not set"/>
    </testcase>
    <testcase name="api-key-format" classname="auth" time="0.000">
      <skipped message="depends on 'api-key-set' which failed"/>
    </testcase>
  </testsuite>
</testsuites>
```

Checks are grouped into `<testsuite>` elements by tag. Skipped checks include the cascade reason. Failed checks include the message and traceback when available.


## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checks ok or warn |
| `1` | At least one check failed |
| `2` | At least one check raised an unexpected exception (bug in the check itself) |


## Listing checks without running

Inspect registered checks without executing them - useful for `--list` flags:

```python
infos = doctor.list_checks()
# [
#   CheckInfo(name="network-reachable", tag="network", depends_on=[], timeout=5.0, ...),
#   CheckInfo(name="api-key-set", tag="auth", depends_on=["network-reachable"], ...),
# ]

for info in infos:
    print(f"{info.tag}/{info.name}")
```

`list_checks()` returns a list of `CheckInfo` dataclasses. Mutations to the returned list do not affect the doctor instance.


## Fix callbacks

Register a repair function alongside any check. When you call `doctor.run(fix=True)`, doctorkit automatically runs the fix for every check that returned `fail` or raised an exception.

Fixes always run sequentially after the main check loop, regardless of `max_concurrency`. This keeps system modifications predictable and output unambiguous.

```python
from doctorkit import Doctor, CheckResult, FixResult

doctor = Doctor()


@doctor.check(
    "api-key-set",
    tag="auth",
    fix_fn=lambda: FixResult(status="fixed", message="Opened .env for editing - paste your key and save"),
)
def check_api_key():
    import os
    if not os.getenv("ANTHROPIC_API_KEY"):
        return CheckResult(
            status="fail",
            message="ANTHROPIC_API_KEY is not set",
            hint="Run: export ANTHROPIC_API_KEY=sk-ant-...",
        )
    return CheckResult(status="ok", message="API key found")


exit_code = doctor.run(fix=True)
```

Output when the check fails:

```
[auth]
  [FAIL] api-key-set: ANTHROPIC_API_KEY is not set (2ms)
    -> Run: export ANTHROPIC_API_KEY=sk-ant-...

1 fail - 5ms total

[fixes]
  [FIXED] api-key-set: Opened .env for editing - paste your key and save
```

Fix function return values:

| Return value | Displayed as |
|---|---|
| `FixResult(status="fixed", message="...")` | `[FIXED]` - green background |
| `FixResult(status="fix_failed", message="...")` | `[FIX FAILED]` - red background |
| A string | `[FIXED]` with that string as message |
| `None` | `[FIXED]` |
| Raises an exception | `[FIX ERROR]` - magenta background |

Fix functions do not affect the check's status or the run's exit code. The exit code always reflects the check results only.

In JSON mode (`json_output=True`), each check entry gains two additional fields:

```json
{
  "name": "api-key-set",
  "status": "fail",
  "fix_status": "fixed",
  "fix_message": "Opened .env for editing - paste your key and save",
  ...
}
```

`fix_status` and `fix_message` are `null` if no fix was attempted for that check.

The `has_fix` field on `CheckInfo` (returned by `list_checks()`) indicates whether a fix function is registered.


## Built-in check library

`doctorkit.checks` is an optional, zero-dependency library of ready-made check factories built entirely on Python's standard library. Import only what you need - nothing is auto-imported when you `import doctorkit`.

### network

```python
from doctorkit.checks.network import http_check, tcp_check, dns_check

# HTTP HEAD request - verifies URL responds with expected status
doctor.add("api-health", http_check("https://api.example.com/health"), tag="network")
doctor.add("api-v2",     http_check("https://api.example.com/v2", expected_status=401), tag="network")

# TCP connection - verifies a port is open and accepting connections
doctor.add("postgres", tcp_check("localhost", 5432), tag="deps")
doctor.add("redis",    tcp_check("localhost", 6379, timeout=3.0), tag="deps")

# DNS resolution
doctor.add("dns-api", dns_check("api.example.com"), tag="network")
```

### env

```python
from doctorkit.checks.env import env_check, envfile_check, envfile_vars_check

# Verify an env var is set, optionally matching a regex
doctor.add("api-key",        env_check("ANTHROPIC_API_KEY"), tag="env")
doctor.add("api-key-format", env_check("ANTHROPIC_API_KEY", pattern=r"sk-ant-.+"), tag="env")

# Verify a .env file exists and is readable
doctor.add("dotenv", envfile_check(".env"), tag="env")

# Verify all variables defined in .env.example are present in .env or os.environ
doctor.add("env-vars", envfile_vars_check(".env.example", env_file=".env"), tag="env")
```

### filesystem

```python
from doctorkit.checks.filesystem import dir_exists_check, file_exists_check, writable_check

doctor.add("logs-dir",   dir_exists_check("logs"), tag="filesystem")
doctor.add("config",     file_exists_check("config.yaml"), tag="filesystem")
doctor.add("tmp-write",  writable_check("/tmp"), tag="filesystem")
```

### process

```python
from doctorkit.checks.process import command_check

# Verify a command exists on PATH, optionally enforce a minimum version
doctor.add("node",   command_check("node",   min_version="18.0"), tag="tools")
doctor.add("python", command_check("python3", min_version="3.9"), tag="tools")
doctor.add("docker", command_check("docker"), tag="tools")
doctor.add("git",    command_check("git",    min_version="2.0"), tag="tools")
```

`command_check` uses `shutil.which` to locate the command and `subprocess` to read its version output. No external dependencies required.


## CLI: doctorkit init

`doctorkit init` scans a project directory, detects what it contains, and generates a ready-to-run `doctor.py` with starter checks already wired up.

```bash
pip install doctorkit-core

# Scan current directory and write doctor.py
doctorkit init

# Scan a specific directory
doctorkit init path/to/project
```

What it detects and generates:

| File found | Checks generated |
|---|---|
| `package.json` | `node` and `npm` command checks |
| `pyproject.toml` / `requirements.txt` / `Pipfile` | `python3` command check |
| `docker-compose.yml` / `Dockerfile` | `docker` command check |
| `.env.example` / `.env` | `envfile_check` and per-variable `env_check` for recognized variable names (e.g. `DATABASE_URL`, `API_KEY`, `REDIS_URL`) |

The generated `doctor.py` is a starting point - open it and add the checks your project actually needs.

```bash
python doctor.py           # run all checks
python doctor.py --json    # JSON output for CI
```


## API reference

### `Doctor()`

Creates a new, empty doctor instance. Each CLI command or test suite typically creates its own.


### `@doctor.check(name, *, tag, depends_on, warn_only, timeout, retries, retry_delay, slow_threshold_ms, fix_fn)`

Decorator that registers a check function. See [Check parameters](#check-parameters) for all options.

```python
@doctor.check(
    "my-check",
    tag                  = "network",
    depends_on           = ["other-check"],
    warn_only            = False,
    timeout              = 5.0,
    retries              = 0,
    retry_delay          = 1.0,
    slow_threshold_ms    = None,
    fix_fn               = None,
)
def my_check():
    return CheckResult(status="ok", message="all good")
```


### `doctor.add(name, fn, *, tag, depends_on, warn_only, timeout, retries, retry_delay, slow_threshold_ms, fix_fn)`

Programmatic alternative to `@doctor.check`. Accepts the same keyword arguments.

```python
for port in [5432, 6379]:
    doctor.add(f"port-{port}", make_port_check(port), tag="database")
```


### `doctor.list_checks() -> list[CheckInfo]`

Returns metadata for all registered checks without running them.


### `doctor.run(...) -> int`

Executes all checks and returns an exit code. Full parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `only` | `list[str] \| None` | `None` | Run only checks whose `tag` is in this list |
| `skip` | `list[str] \| None` | `None` | Skip checks whose `name` is in this list |
| `quiet` | `bool` | `False` | Print only the summary line |
| `verbose` | `bool` | `False` | Show full detail on every check; errors include traceback |
| `json_output` | `bool` | `False` | Emit a JSON object instead of human output |
| `junit_xml` | `bool` | `False` | Emit JUnit XML instead of human output |
| `fail_fast` | `bool` | `False` | Stop after the first `fail` or `error` |
| `max_failures` | `int \| None` | `None` | Stop after this many cumulative failures/errors |
| `slow_threshold_ms` | `float \| None` | `None` | Flag passing checks that exceed this duration in ms |
| `global_timeout` | `float \| None` | `None` | Stop scheduling new checks after this many seconds |
| `max_concurrency` | `int` | `1` | Maximum checks to run in parallel (wave-based) |
| `fix` | `bool` | `False` | Run fix callbacks for failed checks after the main loop. See [Fix callbacks](#fix-callbacks). |
| `output` | file | `sys.stdout` | Where to write output |
| `json_file` | `str \| None` | `None` | Write JSON results to this file path, independently of stdout format |
| `junit_file` | `str \| None` | `None` | Write JUnit XML to this file path, independently of stdout format |


### `doctor.run_detailed(...) -> RunResult`

Same as `run()` but returns a `RunResult` dataclass instead of a bare exit code. Accepts the same parameters.

```python
from doctorkit import RunResult

result: RunResult = doctor.run_detailed(verbose=True)
sys.exit(result.exit_code)
```


### `RunResult`

```python
from doctorkit import RunResult

@dataclass
class RunResult:
    exit_code: int
    summary: RunSummary
    checks: list[CheckRecord]
    total_ms: float
```


### `RunSummary`

```python
from doctorkit import RunSummary

@dataclass
class RunSummary:
    ok: int
    warn: int
    fail: int
    skipped: int
    slow: int
```


### `CheckRecord`

```python
from doctorkit import CheckRecord

@dataclass
class CheckRecord:
    name: str
    status: str             # "ok", "warn", "fail", "error", or "skipped"
    message: str
    hint: str | None
    tag: str
    duration_ms: float
    is_slow: bool
    skip_reason: str | None
    fix_status: str | None
    fix_message: str | None
```


### `CheckResult`

```python
from doctorkit import CheckResult

CheckResult(
    status="ok" | "warn" | "fail",
    message="human-readable description",
    hint="optional actionable fix",  # shown indented below for fail/warn
)
```


### `FixResult`

```python
from doctorkit import FixResult

FixResult(
    status="fixed" | "fix_failed",
    message="description of what was done or why it failed",
)
```

Returned by fix functions. A raised exception is automatically caught and recorded as `fix_error`.


### `CheckInfo`

Returned by `list_checks()`. Read-only dataclass with all check metadata fields, including `has_fix: bool` which is `True` when a fix function is registered for that check.


## Also available in TypeScript

The TypeScript implementation is spec-identical: same output format, same JSON structure, same exit codes, same API surface.

-> **[doctorkit-ts - TypeScript/Node.js package](https://github.com/r-seize/doctorkit-ts)**

```bash
npm install doctorkit-core
```



## License

BSD 2-Clause License