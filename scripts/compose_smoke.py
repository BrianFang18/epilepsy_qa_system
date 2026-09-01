"""Run opt-in compose integration tests and emit aggregate-only JSON."""

from __future__ import annotations

import io
import json
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_TEST_ROOT = PROJECT_ROOT / "tests" / "integration"


class AggregatePlugin:
    """Collect counts without retaining failure text, test bodies, or configuration."""

    def __init__(self) -> None:
        self.collected = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = 0

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected = len(session.items)

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            self.errors += 1

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when == "call":
            if report.passed:
                self.passed += 1
            elif report.failed:
                self.failed += 1
            elif report.skipped:
                self.skipped += 1
        elif report.when == "setup":
            if report.skipped:
                self.skipped += 1
            elif report.failed:
                self.errors += 1
        elif report.when == "teardown" and report.failed:
            self.errors += 1

    def counts(self) -> dict[str, int]:
        return {
            "collected": self.collected,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _status(exit_code: int, aggregate: AggregatePlugin) -> str:
    if exit_code == int(pytest.ExitCode.OK):
        if aggregate.collected > 0 and aggregate.skipped >= aggregate.collected:
            return "skipped"
        return "passed"
    if exit_code == int(pytest.ExitCode.TESTS_FAILED):
        return "failed"
    if exit_code == int(pytest.ExitCode.INTERRUPTED):
        return "interrupted"
    if exit_code == int(pytest.ExitCode.INTERNAL_ERROR):
        return "internal_error"
    if exit_code == int(pytest.ExitCode.USAGE_ERROR):
        return "usage_error"
    if exit_code == int(pytest.ExitCode.NO_TESTS_COLLECTED):
        return "no_tests"
    return "internal_error"


def main() -> int:
    """Use pytest's stable exit codes while suppressing all non-aggregate output."""
    sys.dont_write_bytecode = True
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    aggregate = AggregatePlugin()
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    started = time.monotonic()
    try:
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            result = pytest.main(
                [
                    "-q",
                    "--tb=no",
                    "--disable-warnings",
                    "-p",
                    "no:cacheprovider",
                    "-m",
                    "integration",
                    str(INTEGRATION_TEST_ROOT),
                ],
                plugins=[aggregate],
            )
        exit_code = int(result)
    except KeyboardInterrupt:
        exit_code = int(pytest.ExitCode.INTERRUPTED)
    except BaseException:
        exit_code = int(pytest.ExitCode.INTERNAL_ERROR)

    payload = {
        "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
        "exit_code": exit_code,
        "status": _status(exit_code, aggregate),
        "tests": aggregate.counts(),
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
