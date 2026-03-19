#!/usr/bin/env python3
"""Run the WikiOracle test suite and produce an HTML report.

Usage:
    PYTHONPATH="basicmodel/bin:bin" python3 test/run_tests.py

Or via make:
    make test

Uses pytest with the Report class from basicmodel for HTML output.
"""

import io
import os
import sys
import time
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))
sys.path.insert(0, str(_project / "basicmodel" / "bin"))

import pytest
from util import ProjectPaths
from visualize import Report

from test.nanochat_server import (
    DEFAULT_TEST_NANO_PORT,
    ENV_NANOCHAT_BOOT_ERROR,
    ENV_NANOCHAT_LOG,
    ENV_NANOCHAT_URL,
    NanoChatServer,
)

# ANSI colour codes (disabled when not a tty)
_USE_COLOR = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
_CYAN = "\033[36m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""

# Modules that need NanoChatServer running
_SHARED_NANOCHAT_MODULES = {"test_online_vote"}


class ResultCollector:
    """Pytest plugin that collects test outcomes."""

    def __init__(self):
        self.results = []  # list of (nodeid, outcome, duration, message, stdout)
        self.start_time = None

    def pytest_sessionstart(self, session):
        self.start_time = time.time()

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or (report.when == "setup" and report.outcome == "error"):
            duration = report.duration
            if report.passed:
                outcome = "passed"
                msg = ""
            elif report.failed:
                outcome = "failed"
                msg = str(report.longrepr)[:200] if report.longrepr else ""
            elif report.skipped:
                if hasattr(report, 'wasxfail'):
                    outcome = "xfailed"
                    msg = report.wasxfail or ""
                else:
                    outcome = "skipped"
                    msg = str(report.longrepr)[:200] if report.longrepr else ""
            else:
                outcome = report.outcome
                msg = ""
            # Capture stdout from test
            stdout = ""
            for section_name, content in report.sections:
                if "stdout" in section_name.lower():
                    stdout += content
            self.results.append((report.nodeid, outcome, duration, msg, stdout))

    @property
    def elapsed(self):
        return time.time() - self.start_time if self.start_time else 0


class WarningCollector:
    """Pytest plugin that captures [WikiOracle] log lines from stderr."""

    def __init__(self):
        self.warnings = []

    def pytest_runtest_logreport(self, report):
        for section_name, content in report.sections:
            if "stderr" in section_name.lower() or "stdout" in section_name.lower():
                for line in content.splitlines():
                    if "[WikiOracle]" in line:
                        self.warnings.append(line.strip())


# ---------------------------------------------------------------------------
# NanoChatServer lifecycle
# ---------------------------------------------------------------------------

def _clear_suite_env():
    for name in (ENV_NANOCHAT_URL, ENV_NANOCHAT_BOOT_ERROR, ENV_NANOCHAT_LOG):
        os.environ.pop(name, None)


def _start_suite_services(test_dir):
    """Start shared NanoChatServer if any test files need it."""
    _clear_suite_env()
    # Check if any nanochat-dependent tests exist in the test directory
    test_files = [f.stem for f in Path(test_dir).glob("test_*.py")]
    if not _SHARED_NANOCHAT_MODULES.intersection(test_files):
        return None

    server = NanoChatServer(
        port=DEFAULT_TEST_NANO_PORT,
        log_path=_project / "output" / "test_nanochat.log",
    )
    print(f"{_CYAN}Starting shared NanoChat on port {server.port}...{_RESET}", file=sys.stderr)
    try:
        server.start()
    except Exception as exc:
        os.environ[ENV_NANOCHAT_BOOT_ERROR] = str(exc)
        print(f"{_YELLOW}[WARN] Shared NanoChat bootstrap failed.{_RESET}", file=sys.stderr)
        return None

    os.environ[ENV_NANOCHAT_URL] = server.url
    os.environ[ENV_NANOCHAT_LOG] = str(server.log_path)
    return server


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(test_dir=None):
    """Run pytest on the test directory and produce an HTML report."""
    if test_dir is None:
        test_dir = str(Path(__file__).resolve().parent)

    os.chdir(_project)
    output_dir = _project / "output"
    output_dir.mkdir(exist_ok=True)

    # Start shared services
    shared_nanochat = _start_suite_services(test_dir)

    collector = ResultCollector()
    warn_collector = WarningCollector()

    try:
        exit_code = pytest.main(
            [test_dir, "-v", "--tb=short",
             f"--ignore={os.path.abspath(__file__)}",
             "--ignore=test/nanochat_server.py",
             "--ignore=test/root_child_testpoint.py"],
            plugins=[collector, warn_collector],
        )
    finally:
        if shared_nanochat is not None:
            print(f"{_CYAN}Stopping shared NanoChat...{_RESET}", file=sys.stderr)
            shared_nanochat.stop()
        _clear_suite_env()

    # Build report
    report = Report()

    # Summary counts
    passed = sum(1 for r in collector.results if r[1] == "passed")
    failed = sum(1 for r in collector.results if r[1] == "failed")
    skipped = sum(1 for r in collector.results if r[1] == "skipped")
    xfailed = sum(1 for r in collector.results if r[1] == "xfailed")
    total = len(collector.results)

    summary_rows = [
        ["Total tests", str(total)],
        ["Passed", f'<span class="match">{passed}</span>'],
        ["Failed", f'<span class="mismatch">{failed}</span>' if failed else "0"],
    ]
    if xfailed:
        summary_rows.append(["Expected failures", f'<span style="color:#cc0">{xfailed}</span>'])
    if skipped:
        summary_rows.append(["Skipped", str(skipped)])
    summary_rows.extend([
        ["Duration", f"{collector.elapsed:.1f}s"],
        ["Exit code", str(exit_code)],
    ])
    report.add_table("WikiOracle Test Summary", ["Metric", "Value"], summary_rows)

    # Group results by test file
    by_file = {}
    for nodeid, outcome, duration, msg, stdout in collector.results:
        parts = nodeid.split("::", 1)
        filename = parts[0]
        testname = parts[1] if len(parts) > 1 else nodeid
        by_file.setdefault(filename, []).append((testname, outcome, duration, msg, stdout))

    # Per-file tables
    for filename, tests in sorted(by_file.items()):
        rows = []
        for testname, outcome, duration, msg, stdout in tests:
            if outcome == "passed":
                status = '<span class="match">PASS</span>'
            elif outcome == "failed":
                status = '<span class="mismatch">FAIL</span>'
            elif outcome == "xfailed":
                status = '<span style="color:#cc0">XFAIL</span>'
            elif outcome == "skipped":
                status = "SKIP"
            else:
                status = outcome.upper()
            row = [testname, status, f"{duration:.3f}s"]
            if msg:
                row.append(f"<pre>{msg[:200]}</pre>")
            else:
                row.append("")
            rows.append(row)
        report.add_table(filename, ["Test", "Status", "Duration", "Details"], rows)

    # [WikiOracle] warnings section
    if warn_collector.warnings:
        warn_rows = [[w] for w in warn_collector.warnings]
        report.add_table(
            f"Runtime Warnings ({len(warn_collector.warnings)})",
            ["Warning"], warn_rows)

    # Point Report output to wikioracle's output/ directory
    saved_output_dir = ProjectPaths.OUTPUT_DIR
    ProjectPaths.OUTPUT_DIR = str(output_dir)
    try:
        path = report.write_html()
    finally:
        ProjectPaths.OUTPUT_DIR = saved_output_dir
    return exit_code, path


if __name__ == "__main__":
    exit_code, path = generate_report()
    sys.exit(exit_code)
