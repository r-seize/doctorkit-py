"""Comprehensive tests for doctorkit Python implementation."""
import io
import json
import time

import pytest

import os
import tempfile

from doctorkit import Doctor, CheckResult, FixResult, RunResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doctor() -> Doctor:
    return Doctor()


def _run_json(d: Doctor, **kwargs) -> tuple[int, dict]:
    out = io.StringIO()
    code = d.run(json_output=True, output=out, **kwargs)
    return code, json.loads(out.getvalue())


def _run_text(d: Doctor, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    code = d.run(output=out, **kwargs)
    return code, out.getvalue()


# ---------------------------------------------------------------------------
# Basic statuses
# ---------------------------------------------------------------------------


class TestBasicStatuses:
    def test_ok_returns_exit_0(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return CheckResult(status="ok", message="all good")

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["status"] == "ok"
        assert data["checks"][0]["message"] == "all good"

    def test_warn_returns_exit_0(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return CheckResult(status="warn", message="something odd", hint="check logs")

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["status"] == "warn"
        assert data["checks"][0]["hint"] == "check logs"
        assert data["summary"]["warn"] == 1

    def test_fail_returns_exit_1(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return CheckResult(status="fail", message="broken")

        code, _ = _run_json(d)
        assert code == 1

    def test_exception_returns_exit_2(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            raise RuntimeError("oops")

        code, data = _run_json(d)
        assert code == 2
        assert data["checks"][0]["status"] == "error"
        assert "oops" in data["checks"][0]["message"]

    def test_none_return_treated_as_ok(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return None

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["status"] == "ok"

    def test_string_return_treated_as_ok(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return "everything fine"

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["message"] == "everything fine"

    def test_warn_does_not_set_fail_in_summary(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _check():
            return CheckResult(status="warn", message="meh")

        code, data = _run_json(d)
        assert data["summary"]["fail"] == 0
        assert data["summary"]["warn"] == 1
        assert code == 0


# ---------------------------------------------------------------------------
# Dependencies and cascade skip
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_skip_when_dep_fails(self):
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            return CheckResult(status="fail", message="dep failed")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        code, data = _run_json(d)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["dep"] == "fail"
        assert statuses["child"] == "skipped"
        assert code == 1

    def test_cascade_skip(self):
        d = _doctor()

        @d.check("a", tag="t")
        def _a():
            return CheckResult(status="fail", message="a failed")

        @d.check("b", tag="t", depends_on=["a"])
        def _b():
            return CheckResult(status="ok", message="ok")

        @d.check("c", tag="t", depends_on=["b"])
        def _c():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["a"] == "fail"
        assert statuses["b"] == "skipped"
        assert statuses["c"] == "skipped"

    def test_no_skip_on_warn_dependency(self):
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            return CheckResult(status="warn", message="warning")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["child"] == "ok"

    def test_dependency_reordering(self):
        d = _doctor()
        order: list = []

        @d.check("b", tag="t", depends_on=["a"])
        def _b():
            order.append("b")
            return CheckResult(status="ok", message="ok")

        @d.check("a", tag="t")
        def _a():
            order.append("a")
            return CheckResult(status="ok", message="ok")

        _run_json(d)
        assert order.index("a") < order.index("b")

    def test_skip_when_dep_errored(self):
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            raise RuntimeError("crash")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["dep"] == "error"
        assert statuses["child"] == "skipped"


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_check_times_out(self):
        d = _doctor()

        @d.check("slow", tag="t", timeout=0.1)
        def _slow():
            time.sleep(10)

        code, data = _run_json(d)
        assert code == 1
        assert data["checks"][0]["status"] == "fail"
        assert "timeout" in data["checks"][0]["message"]

    def test_fast_check_does_not_timeout(self):
        d = _doctor()

        @d.check("fast", tag="t", timeout=5)
        def _fast():
            return CheckResult(status="ok", message="done")

        code, _ = _run_json(d)
        assert code == 0

    def test_timeout_duration_recorded(self):
        d = _doctor()

        @d.check("slow", tag="t", timeout=0.1)
        def _slow():
            time.sleep(10)

        _, data = _run_json(d)
        assert data["checks"][0]["duration_ms"] >= 100


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


class TestRetries:
    def test_retry_succeeds_on_third_attempt(self):
        d = _doctor()
        calls: list = []

        @d.check("flaky", tag="t", retries=2, retry_delay=0)
        def _flaky():
            calls.append(1)
            if len(calls) < 3:
                return CheckResult(status="fail", message="not yet")
            return CheckResult(status="ok", message="finally")

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["status"] == "ok"
        assert len(calls) == 3

    def test_retries_exhausted_stays_fail(self):
        d = _doctor()
        calls: list = []

        @d.check("always-fail", tag="t", retries=2, retry_delay=0)
        def _always_fail():
            calls.append(1)
            return CheckResult(status="fail", message="nope")

        code, data = _run_json(d)
        assert code == 1
        assert data["checks"][0]["status"] == "fail"
        assert len(calls) == 3

    def test_no_retry_on_ok(self):
        d = _doctor()
        calls: list = []

        @d.check("fine", tag="t", retries=2, retry_delay=0)
        def _fine():
            calls.append(1)
            return CheckResult(status="ok", message="ok")

        _run_json(d)
        assert len(calls) == 1

    def test_retry_on_exception(self):
        d = _doctor()
        calls: list = []

        @d.check("crash-then-ok", tag="t", retries=1, retry_delay=0)
        def _crash():
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("first attempt crash")
            return CheckResult(status="ok", message="recovered")

        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["status"] == "ok"
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_only_tag_filter(self):
        d = _doctor()

        @d.check("net-check", tag="network")
        def _net():
            return CheckResult(status="ok", message="ok")

        @d.check("auth-check", tag="auth")
        def _auth():
            return CheckResult(status="fail", message="no key")

        code, data = _run_json(d, only=["network"])
        assert code == 0
        assert len(data["checks"]) == 1
        assert data["checks"][0]["name"] == "net-check"

    def test_skip_name_filter(self):
        d = _doctor()

        @d.check("check-a", tag="t")
        def _a():
            return CheckResult(status="ok", message="ok")

        @d.check("check-b", tag="t")
        def _b():
            return CheckResult(status="fail", message="fail")

        code, data = _run_json(d, skip=["check-b"])
        assert code == 0
        assert len(data["checks"]) == 1
        assert data["checks"][0]["name"] == "check-a"

    def test_only_empty_result(self):
        d = _doctor()

        @d.check("c", tag="network")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, only=["auth"])
        assert data["checks"] == []


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_shape(self):
        d = _doctor()

        @d.check("net", tag="network")
        def _net():
            return CheckResult(status="ok", message="reachable")

        @d.check("auth", tag="auth")
        def _auth():
            return CheckResult(status="fail", message="missing key", hint="set key")

        code, data = _run_json(d)
        assert "checks" in data
        assert "summary" in data
        assert "exit_code" in data
        assert data["exit_code"] == code == 1
        assert data["summary"]["ok"] == 1
        assert data["summary"]["fail"] == 1

        auth = next(c for c in data["checks"] if c["name"] == "auth")
        assert auth["hint"] == "set key"
        assert auth["tag"] == "auth"
        assert "duration_ms" in auth
        assert "is_slow" in auth

    def test_json_exit_code_0(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="ok")

        code, data = _run_json(d)
        assert code == 0
        assert data["exit_code"] == 0

    def test_json_exit_code_1(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="bad")

        code, data = _run_json(d)
        assert code == 1
        assert data["exit_code"] == 1

    def test_json_exit_code_2(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            raise Exception("boom")

        code, data = _run_json(d)
        assert code == 2
        assert data["exit_code"] == 2

    def test_json_skipped_check_appears(self):
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            return CheckResult(status="fail", message="fail")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["child"] == "skipped"
        assert data["summary"]["skipped"] == 1


# ---------------------------------------------------------------------------
# warn_only
# ---------------------------------------------------------------------------


class TestWarnOnly:
    def test_warn_only_downgrades_fail_to_warn(self):
        d = _doctor()

        @d.check("optional", tag="t", warn_only=True)
        def _opt():
            return CheckResult(status="fail", message="not critical")

        code, data = _run_json(d)
        assert data["checks"][0]["status"] == "warn"
        assert code == 0

    def test_warn_only_keeps_ok(self):
        d = _doctor()

        @d.check("c", tag="t", warn_only=True)
        def _c():
            return CheckResult(status="ok", message="fine")

        code, data = _run_json(d)
        assert data["checks"][0]["status"] == "ok"
        assert code == 0


# ---------------------------------------------------------------------------
# fail_fast
# ---------------------------------------------------------------------------


class TestFailFast:
    def test_stops_after_first_failure(self):
        d = _doctor()
        executed: list = []

        @d.check("a", tag="t")
        def _a():
            executed.append("a")
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            executed.append("b")
            return CheckResult(status="ok", message="ok")

        @d.check("c", tag="t")
        def _c():
            executed.append("c")
            return CheckResult(status="ok", message="ok")

        _run_json(d, fail_fast=True)
        assert "a" in executed
        assert "b" not in executed
        assert "c" not in executed

    def test_marks_unexecuted_as_skipped(self):
        d = _doctor()

        @d.check("a", tag="t")
        def _a():
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, fail_fast=True)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["a"] == "fail"
        assert statuses["b"] == "skipped"

    def test_exit_code_still_1(self):
        d = _doctor()

        @d.check("a", tag="t")
        def _a():
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            return CheckResult(status="ok", message="ok")

        code, _ = _run_json(d, fail_fast=True)
        assert code == 1

    def test_stops_on_error(self):
        d = _doctor()
        executed: list = []

        @d.check("a", tag="t")
        def _a():
            executed.append("a")
            raise RuntimeError("crash")

        @d.check("b", tag="t")
        def _b():
            executed.append("b")
            return CheckResult(status="ok", message="ok")

        code, _ = _run_json(d, fail_fast=True)
        assert "b" not in executed
        assert code == 2


# ---------------------------------------------------------------------------
# slow_threshold_ms
# ---------------------------------------------------------------------------


class TestSlowThreshold:
    def test_flags_slow_ok_check_globally(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            time.sleep(0.06)
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, slow_threshold_ms=10)
        assert data["checks"][0]["is_slow"] is True
        assert data["summary"]["slow"] == 1

    def test_no_flag_below_threshold(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, slow_threshold_ms=10000)
        assert data["checks"][0]["is_slow"] is False
        assert data["summary"]["slow"] == 0

    def test_per_check_threshold_overrides_global(self):
        d = _doctor()

        @d.check("c", tag="t", slow_threshold_ms=10000)
        def _c():
            time.sleep(0.06)
            return CheckResult(status="ok", message="ok")

        # global = 1ms would flag, but per-check = 10s won't
        _, data = _run_json(d, slow_threshold_ms=1)
        assert data["checks"][0]["is_slow"] is False

    def test_does_not_flag_fail_as_slow(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            time.sleep(0.06)
            return CheckResult(status="fail", message="fail")

        _, data = _run_json(d, slow_threshold_ms=1)
        assert data["checks"][0]["is_slow"] is False

    def test_slow_visible_in_text_output(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            time.sleep(0.06)
            return CheckResult(status="ok", message="ok")

        _, text = _run_text(d, slow_threshold_ms=10)
        assert "slow" in text
        assert "ms" in text


# ---------------------------------------------------------------------------
# add() - programmatic registration
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_registers_check(self):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="via add"), tag="t")
        code, data = _run_json(d)
        assert code == 0
        assert data["checks"][0]["name"] == "c"

    def test_add_supports_all_options(self):
        d = _doctor()
        calls: list = []

        def _fn():
            calls.append(1)
            if len(calls) < 2:
                return CheckResult(status="fail", message="retry me")
            return CheckResult(status="ok", message="ok")

        d.add("c", _fn, tag="t", retries=1, retry_delay=0)
        code, _ = _run_json(d)
        assert code == 0
        assert len(calls) == 2

    def test_add_and_check_coexist(self):
        d = _doctor()
        d.add("via-add", lambda: CheckResult(status="ok", message="ok"), tag="t")

        @d.check("via-decorator", tag="t")
        def _via_deco():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d)
        names = [c["name"] for c in data["checks"]]
        assert "via-add" in names
        assert "via-decorator" in names

    def test_add_in_loop(self):
        d = _doctor()
        for i in range(3):
            port = 8000 + i
            d.add(f"port-{port}", lambda p=port: CheckResult(status="ok", message=f"port {p}"), tag="ports")
        _, data = _run_json(d)
        assert len(data["checks"]) == 3


# ---------------------------------------------------------------------------
# list_checks
# ---------------------------------------------------------------------------


class TestListChecks:
    def test_returns_all_registered(self):
        d = _doctor()

        @d.check("net", tag="network", timeout=3, depends_on=["x"])
        def _net():
            return CheckResult(status="ok", message="ok")

        @d.check("auth", tag="auth", warn_only=True)
        def _auth():
            return CheckResult(status="ok", message="ok")

        infos = d.list_checks()
        assert len(infos) == 2
        net = next(i for i in infos if i.name == "net")
        assert net.tag == "network"
        assert net.timeout == 3
        assert net.depends_on == ["x"]
        auth = next(i for i in infos if i.name == "auth")
        assert auth.warn_only is True

    def test_empty_when_no_checks(self):
        d = _doctor()
        assert d.list_checks() == []

    def test_list_does_not_execute_checks(self):
        d = _doctor()
        ran = [False]

        @d.check("c", tag="t")
        def _c():
            ran[0] = True
            return CheckResult(status="ok", message="ok")

        d.list_checks()
        assert ran[0] is False

    def test_returned_copy_is_independent(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="ok")

        infos = d.list_checks()
        infos[0].depends_on.append("injected")
        assert d.list_checks()[0].depends_on == []


# ---------------------------------------------------------------------------
# Human output
# ---------------------------------------------------------------------------


class TestHumanOutput:
    def test_verbose_shows_ok_message(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="great message")

        _, text = _run_text(d, verbose=True)
        assert "great message" in text

    def test_default_compresses_ok(self):
        d = _doctor()

        @d.check("mycheck", tag="t")
        def _c():
            return CheckResult(status="ok", message="this should be hidden")

        _, text = _run_text(d)
        assert "this should be hidden" not in text
        assert "mycheck" in text

    def test_quiet_hides_check_detail(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="broken detail", hint="fix it now")

        _, text = _run_text(d, quiet=True)
        assert "broken detail" not in text
        assert "fix it now" not in text

    def test_quiet_shows_summary(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="broken")

        _, text = _run_text(d, quiet=True)
        assert "fail" in text

    def test_hint_visible_on_fail(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="no key", hint="export KEY=...")

        _, text = _run_text(d, verbose=True)
        assert "export KEY=..." in text

    def test_hint_visible_on_warn(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="warn", message="low", hint="upgrade please")

        _, text = _run_text(d, verbose=True)
        assert "upgrade please" in text

    def test_tag_header_in_output(self):
        d = _doctor()

        @d.check("c", tag="network")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, text = _run_text(d)
        assert "network" in text

    def test_summary_counts_correct(self):
        d = _doctor()

        @d.check("a", tag="t")
        def _a():
            return CheckResult(status="ok", message="ok")

        @d.check("b", tag="t")
        def _b():
            return CheckResult(status="warn", message="warn")

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="fail")

        _, text = _run_text(d)
        assert "1 ok" in text
        assert "1 warn" in text
        assert "1 fail" in text

    def test_verbose_shows_traceback_on_error(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            raise ValueError("kaboom details")

        _, text = _run_text(d, verbose=True)
        assert "kaboom details" in text

    def test_slow_count_in_summary(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            time.sleep(0.06)
            return CheckResult(status="ok", message="ok")

        _, text = _run_text(d, slow_threshold_ms=10)
        assert "slow" in text


# ---------------------------------------------------------------------------
# max_failures
# ---------------------------------------------------------------------------


class TestMaxFailures:
    def test_stops_after_max_failures(self):
        d = _doctor()
        executed: list = []

        @d.check("a", tag="t")
        def _a():
            executed.append("a")
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            executed.append("b")
            return CheckResult(status="fail", message="fail")

        @d.check("c", tag="t")
        def _c():
            executed.append("c")
            return CheckResult(status="ok", message="ok")

        _run_json(d, max_failures=2)
        assert "a" in executed
        assert "b" in executed
        assert "c" not in executed

    def test_max_failures_1_same_as_fail_fast(self):
        d = _doctor()
        executed: list = []

        @d.check("a", tag="t")
        def _a():
            executed.append("a")
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            executed.append("b")
            return CheckResult(status="ok", message="ok")

        _run_json(d, max_failures=1)
        assert "a" in executed
        assert "b" not in executed

    def test_max_failures_skips_remaining(self):
        d = _doctor()

        @d.check("a", tag="t")
        def _a():
            return CheckResult(status="fail", message="fail")

        @d.check("b", tag="t")
        def _b():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, max_failures=1)
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["b"] == "skipped"


# ---------------------------------------------------------------------------
# global_timeout
# ---------------------------------------------------------------------------


class TestGlobalTimeout:
    def test_skips_checks_after_timeout(self):
        d = _doctor()

        @d.check("fast", tag="t")
        def _fast():
            time.sleep(0.05)
            return CheckResult(status="ok", message="ok")

        @d.check("second", tag="t")
        def _second():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, global_timeout=0.01)
        # fast runs (first check always runs), second is skipped
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["fast"] == "ok"
        assert statuses["second"] == "skipped"

    def test_first_check_always_runs(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, global_timeout=0.0)
        # Even with 0s global_timeout, first check runs
        assert data["checks"][0]["status"] == "ok"

    def test_skip_reason_mentions_global_timeout(self):
        d = _doctor()

        @d.check("slow", tag="t")
        def _slow():
            time.sleep(0.05)
            return CheckResult(status="ok", message="ok")

        @d.check("second", tag="t")
        def _second():
            return CheckResult(status="ok", message="ok")

        _, data = _run_json(d, global_timeout=0.01)
        second = next(c for c in data["checks"] if c["name"] == "second")
        assert second["status"] == "skipped"


# ---------------------------------------------------------------------------
# Parallel execution (max_concurrency)
# ---------------------------------------------------------------------------


class TestParallel:
    def test_parallel_all_ok(self):
        d = _doctor()

        for name in ["a", "b", "c"]:
            d.add(name, lambda: CheckResult(status="ok", message="ok"), tag="t")

        code, data = _run_json(d, max_concurrency=3)
        assert code == 0
        assert len(data["checks"]) == 3
        assert all(c["status"] == "ok" for c in data["checks"])

    def test_parallel_respects_dependencies(self):
        d = _doctor()
        order: list = []

        @d.check("dep", tag="t")
        def _dep():
            order.append("dep")
            return CheckResult(status="ok", message="ok")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            order.append("child")
            return CheckResult(status="ok", message="ok")

        code, _ = _run_json(d, max_concurrency=4)
        assert code == 0
        assert order.index("dep") < order.index("child")

    def test_parallel_fail_propagates(self):
        d = _doctor()
        d.add("a", lambda: CheckResult(status="fail", message="fail"), tag="t")
        d.add("b", lambda: CheckResult(status="ok", message="ok"), tag="t")

        code, data = _run_json(d, max_concurrency=2)
        assert code == 1
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["a"] == "fail"
        assert statuses["b"] == "ok"

    def test_parallel_cascade_skip(self):
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            return CheckResult(status="fail", message="fail")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        code, data = _run_json(d, max_concurrency=4)
        assert code == 1
        statuses = {c["name"]: c["status"] for c in data["checks"]}
        assert statuses["child"] == "skipped"


# ---------------------------------------------------------------------------
# JUnit XML output
# ---------------------------------------------------------------------------


class TestJunitXml:
    def _run_junit(self, d: Doctor, **kwargs) -> tuple[int, str]:
        out = io.StringIO()
        code = d.run(junit_xml=True, output=out, **kwargs)
        return code, out.getvalue()

    def test_valid_xml(self):
        import xml.etree.ElementTree as ET
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, xml_str = self._run_junit(d)
        root = ET.fromstring(xml_str.strip().split("\n", 1)[1])  # skip xml declaration
        assert root.tag == "testsuites"

    def test_ok_check_in_xml(self):
        import xml.etree.ElementTree as ET
        d = _doctor()

        @d.check("my-check", tag="network")
        def _c():
            return CheckResult(status="ok", message="ok")

        _, xml_str = self._run_junit(d)
        # strip xml declaration line for parsing
        body = "\n".join(xml_str.strip().splitlines()[1:])
        root = ET.fromstring(body)
        suite = root.find(".//testsuite[@name='network']")
        assert suite is not None
        tc = suite.find(".//testcase[@name='my-check']")
        assert tc is not None
        assert tc.find("failure") is None

    def test_fail_check_has_failure_element(self):
        import xml.etree.ElementTree as ET
        d = _doctor()

        @d.check("broken", tag="t")
        def _c():
            return CheckResult(status="fail", message="broken")

        _, xml_str = self._run_junit(d)
        body = "\n".join(xml_str.strip().splitlines()[1:])
        root = ET.fromstring(body)
        tc = root.find(".//testcase[@name='broken']")
        assert tc is not None
        failure = tc.find("failure")
        assert failure is not None
        assert failure.get("message") == "broken"

    def test_skipped_check_has_skipped_element(self):
        import xml.etree.ElementTree as ET
        d = _doctor()

        @d.check("dep", tag="t")
        def _dep():
            return CheckResult(status="fail", message="fail")

        @d.check("child", tag="t", depends_on=["dep"])
        def _child():
            return CheckResult(status="ok", message="ok")

        _, xml_str = self._run_junit(d)
        body = "\n".join(xml_str.strip().splitlines()[1:])
        root = ET.fromstring(body)
        tc = root.find(".//testcase[@name='child']")
        assert tc is not None
        assert tc.find("skipped") is not None

    def test_exit_code_preserved(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="fail")

        code, _ = self._run_junit(d)
        assert code == 1

    def test_grouped_by_tag(self):
        import xml.etree.ElementTree as ET
        d = _doctor()

        @d.check("a", tag="network")
        def _a():
            return CheckResult(status="ok", message="ok")

        @d.check("b", tag="auth")
        def _b():
            return CheckResult(status="ok", message="ok")

        _, xml_str = self._run_junit(d)
        body = "\n".join(xml_str.strip().splitlines()[1:])
        root = ET.fromstring(body)
        suites = root.findall("testsuite")
        names = [s.get("name") for s in suites]
        assert "network" in names
        assert "auth" in names


# ---------------------------------------------------------------------------
# Fix callbacks
# ---------------------------------------------------------------------------


class TestFixCallbacks:
    def test_fix_runs_on_failed_check(self):
        d = _doctor()
        fixed: list = []

        def _fix():
            fixed.append(True)
            return FixResult(status="fixed", message="repaired")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="broken")

        code, data = _run_json(d, fix=True)
        assert code == 1
        assert len(fixed) == 1
        assert data["checks"][0]["fix_status"] == "fixed"
        assert data["checks"][0]["fix_message"] == "repaired"

    def test_fix_not_run_on_ok_check(self):
        d = _doctor()
        called: list = []

        def _fix():
            called.append(True)

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="ok", message="fine")

        _run_json(d, fix=True)
        assert len(called) == 0

    def test_fix_not_run_when_fix_false(self):
        d = _doctor()
        called: list = []

        def _fix():
            called.append(True)

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="fail")

        _run_json(d, fix=False)
        assert len(called) == 0

    def test_fix_failed_status_propagated(self):
        d = _doctor()

        def _fix():
            return FixResult(status="fix_failed", message="could not repair")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="broken")

        _, data = _run_json(d, fix=True)
        assert data["checks"][0]["fix_status"] == "fix_failed"
        assert data["checks"][0]["fix_message"] == "could not repair"

    def test_fix_error_on_exception(self):
        d = _doctor()

        def _fix():
            raise RuntimeError("fix blew up")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="broken")

        _, data = _run_json(d, fix=True)
        assert data["checks"][0]["fix_status"] == "fix_error"
        assert "fix blew up" in data["checks"][0]["fix_message"]

    def test_fix_string_return_treated_as_fixed(self):
        d = _doctor()

        def _fix():
            return "exported the key"

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="missing key")

        _, data = _run_json(d, fix=True)
        assert data["checks"][0]["fix_status"] == "fixed"
        assert data["checks"][0]["fix_message"] == "exported the key"

    def test_fix_none_when_no_fix_fn(self):
        d = _doctor()

        @d.check("c", tag="t")
        def _c():
            return CheckResult(status="fail", message="broken")

        _, data = _run_json(d, fix=True)
        assert data["checks"][0]["fix_status"] is None
        assert data["checks"][0]["fix_message"] is None

    def test_fix_section_in_human_output(self):
        d = _doctor()

        def _fix():
            return FixResult(status="fixed", message="patched it")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="fail", message="broken")

        _, text = _run_text(d, fix=True)
        assert "[fixes]" in text
        assert "[FIXED]" in text
        assert "patched it" in text

    def test_fix_section_absent_when_no_failures(self):
        d = _doctor()

        def _fix():
            return FixResult(status="fixed", message="not needed")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            return CheckResult(status="ok", message="all good")

        _, text = _run_text(d, fix=True)
        assert "[fixes]" not in text

    def test_has_fix_in_list_checks(self):
        d = _doctor()

        def _fix():
            pass

        @d.check("with-fix", tag="t", fix_fn=_fix)
        def _a():
            return CheckResult(status="ok", message="ok")

        @d.check("without-fix", tag="t")
        def _b():
            return CheckResult(status="ok", message="ok")

        infos = {c.name: c for c in d.list_checks()}
        assert infos["with-fix"].has_fix is True
        assert infos["without-fix"].has_fix is False

    def test_fix_via_add(self):
        d = _doctor()
        fixed: list = []

        def _check():
            return CheckResult(status="fail", message="broken")

        def _fix():
            fixed.append(True)
            return FixResult(status="fixed", message="done")

        d.add("c", _check, tag="t", fix_fn=_fix)

        _, data = _run_json(d, fix=True)
        assert len(fixed) == 1
        assert data["checks"][0]["fix_status"] == "fixed"

    def test_fix_only_runs_on_error_checks_too(self):
        d = _doctor()
        fixed: list = []

        def _fix():
            fixed.append(True)
            return FixResult(status="fixed", message="cleaned up")

        @d.check("c", tag="t", fix_fn=_fix)
        def _c():
            raise RuntimeError("crash")

        _, data = _run_json(d, fix=True)
        assert len(fixed) == 1
        assert data["checks"][0]["fix_status"] == "fixed"


# ---------------------------------------------------------------------------
# run_detailed()
# ---------------------------------------------------------------------------


class TestRunDetailed:
    def test_returns_run_result(self):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="good"), tag="t")
        result = d.run_detailed(output=io.StringIO())
        assert isinstance(result, RunResult)

    def test_exit_code_and_summary(self):
        d = _doctor()
        d.add("ok", lambda: CheckResult(status="ok", message="ok"), tag="t")
        d.add("fail", lambda: CheckResult(status="fail", message="bad"), tag="t")
        result = d.run_detailed(output=io.StringIO())
        assert result.exit_code == 1
        assert result.summary.ok == 1
        assert result.summary.fail == 1
        assert result.summary.warn == 0
        assert result.summary.skipped == 0

    def test_checks_list_has_all_fields(self):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="fine"), tag="mygroup")
        result = d.run_detailed(output=io.StringIO())
        rec = result.checks[0]
        assert rec.name == "c"
        assert rec.tag == "mygroup"
        assert rec.status == "ok"
        assert rec.message == "fine"
        assert rec.is_slow is False
        assert rec.fix_status is None
        assert rec.fix_message is None

    def test_skip_reason_populated(self):
        d = _doctor()
        d.add("dep", lambda: CheckResult(status="fail", message="fail"), tag="t")
        d.add("child", lambda: CheckResult(status="ok", message="ok"), tag="t", depends_on=["dep"])
        result = d.run_detailed(output=io.StringIO())
        child = next(r for r in result.checks if r.name == "child")
        assert child.status == "skipped"
        assert "dep" in (child.skip_reason or "")

    def test_fix_status_populated(self):
        d = _doctor()
        d.add(
            "c",
            lambda: CheckResult(status="fail", message="broken"),
            tag="t",
            fix_fn=lambda: FixResult(status="fixed", message="repaired"),
        )
        result = d.run_detailed(fix=True, output=io.StringIO())
        assert result.checks[0].fix_status == "fixed"
        assert result.checks[0].fix_message == "repaired"

    def test_total_ms_is_float(self):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="ok"), tag="t")
        result = d.run_detailed(output=io.StringIO())
        assert isinstance(result.total_ms, float)
        assert result.total_ms >= 0


# ---------------------------------------------------------------------------
# File output (json_file, junit_file)
# ---------------------------------------------------------------------------


class TestFileOutput:
    def test_json_file_written(self, tmp_path):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="ok"), tag="t")
        out_file = tmp_path / "results.json"
        d.run(json_file=str(out_file), output=io.StringIO())
        data = json.loads(out_file.read_text())
        assert data["checks"][0]["name"] == "c"
        assert data["exit_code"] == 0

    def test_json_file_alongside_human_output(self, tmp_path):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="ok"), tag="t")
        out_file = tmp_path / "results.json"
        out = io.StringIO()
        d.run(json_file=str(out_file), output=out)
        assert out_file.exists()
        assert "[t]" in out.getvalue()  # human output still on stdout

    def test_json_file_alongside_json_output(self, tmp_path):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="fail", message="bad"), tag="t")
        out_file = tmp_path / "results.json"
        code, data = _run_json(d, json_file=str(out_file))
        assert code == 1
        file_data = json.loads(out_file.read_text())
        assert file_data["exit_code"] == 1

    def test_junit_file_written(self, tmp_path):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="fail", message="broken"), tag="suite")
        out_file = tmp_path / "results.xml"
        d.run(junit_file=str(out_file), output=io.StringIO())
        xml = out_file.read_text()
        assert "<testsuites>" in xml
        assert 'name="suite"' in xml
        assert "<failure" in xml

    def test_both_files_written_in_one_run(self, tmp_path):
        d = _doctor()
        d.add("c", lambda: CheckResult(status="ok", message="ok"), tag="t")
        json_path = tmp_path / "r.json"
        xml_path = tmp_path / "r.xml"
        d.run(json_file=str(json_path), junit_file=str(xml_path), output=io.StringIO())
        assert json_path.exists()
        assert xml_path.exists()

    def test_json_file_includes_fix_fields(self, tmp_path):
        d = _doctor()
        d.add(
            "c",
            lambda: CheckResult(status="fail", message="broken"),
            tag="t",
            fix_fn=lambda: "repaired",
        )
        out_file = tmp_path / "results.json"
        d.run(fix=True, json_file=str(out_file), output=io.StringIO())
        data = json.loads(out_file.read_text())
        assert data["checks"][0]["fix_status"] == "fixed"
        assert data["checks"][0]["fix_message"] == "repaired"
