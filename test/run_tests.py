#!/usr/bin/env python3
"""Run the WikiOracle test suite and produce an HTML summary.

Usage:
    source .venv/bin/activate
    PYTHONPATH="nanochat:$(pwd)/bin" python3 test/run_tests.py

Or via make:
    make test

Writes ./output/test_<YYYYMMDD_HHMM>.html with pass/fail/skip counts,
per-module breakdown, and any captured warnings.
"""

import datetime
import html
import io
import os
import sys
import time
import unittest
from pathlib import Path

_project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project))
sys.path.insert(0, str(_project / "bin"))

from test.nanochat_server import (
    DEFAULT_TEST_NANO_PORT,
    ENV_NANOCHAT_BOOT_ERROR,
    ENV_NANOCHAT_LOG,
    ENV_NANOCHAT_URL,
    NanoChatServer,
)

# ANSI colour codes (disabled when not a tty)
_USE_COLOR = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()
_GREEN = "\033[32m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_CYAN = "\033[36m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""

# Test modules in execution order (matches Makefile)
_TEST_MODULES = [
    "test.test_wikioracle_state",
    "test.test_prompt_bundle",
    "test.test_derived_truth",
    "test.test_authority",
    "test.test_stateless_contract",
    "test.test_hme_inference",
    "test.test_voting",
    "test.test_alpha_state",
    "test.test_degree_of_truth",
    "test.test_user_guid",
    "test.test_sensation",
    "test.test_spacetime",
    "test.test_config_xml",
    "test.test_state_xml",
    "test.test_ui_strings",
    "test.test_tree_branch",
    "test.test_online_llm",
    "test.test_online_vote",
    # test_online_training excluded: requires torch + NanoChat checkpoint (use `make test-train`)
]

_SHARED_NANOCHAT_MODULES = {"test.test_online_vote"}


class _TestRecord:
    """Stores the result of a single test method."""
    __slots__ = ("module", "cls", "method", "status", "message", "elapsed")

    def __init__(self, module, cls, method, status, message="", elapsed=0.0):
        self.module = module
        self.cls = cls
        self.method = method
        self.status = status      # "pass", "fail", "error", "skip"
        self.message = message
        self.elapsed = elapsed


class _HTMLResult(unittest.TestResult):
    """Collects test results into _TestRecord objects."""

    def __init__(self):
        super().__init__()
        self.records: list[_TestRecord] = []
        self._start_time = 0.0
        self._current_class = None
        self._class_start_time = 0.0

    def startTestRun(self):
        super().startTestRun()
        self._class_start_time = time.monotonic()

    def startTest(self, test):
        super().startTest(test)
        test_class = type(test)
        if test_class is not self._current_class:
            # First test in a new class — include setUpClass time
            self._current_class = test_class
            self._start_time = self._class_start_time
        else:
            self._start_time = time.monotonic()

    def stopTest(self, test):
        super().stopTest(test)
        self._class_start_time = time.monotonic()

    def _record(self, test, status, message=""):
        elapsed = time.monotonic() - self._start_time
        module = type(test).__module__
        cls = type(test).__name__
        method = test._testMethodName
        self.records.append(_TestRecord(module, cls, method, status, message, elapsed))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "fail", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skip", reason)


def _load_suite(module_names: list[str]) -> unittest.TestSuite:
    """Load test modules into a TestSuite."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in module_names:
        try:
            suite.addTests(loader.loadTestsFromName(name))
        except Exception as e:
            print(f"  [WARN] Could not load {name}: {e}", file=sys.stderr)
    return suite


def _run_modules(module_names: list[str], stderr_capture: io.StringIO) -> _HTMLResult:
    """Load and run modules, capturing stderr and returning structured results."""
    suite = _load_suite(module_names)
    result = _HTMLResult()

    # Tee stdout/stderr to capture [WikiOracle] log lines while still printing
    old_stderr = sys.stderr
    old_stdout = sys.stdout
    tee_err = io.StringIO()
    tee_out = io.StringIO()

    class _Tee:
        def __init__(self, primary, secondary):
            self._p = primary
            self._s = secondary
        def write(self, data):
            self._p.write(data)
            self._s.write(data)
        def flush(self):
            self._p.flush()
            self._s.flush()

    sys.stderr = _Tee(old_stderr, tee_err)
    sys.stdout = _Tee(old_stdout, tee_out)
    try:
        # Run with our custom result; print verbose output manually
        suite.run(result)
        # Print colour-coded summary to stderr for console visibility
        _tag = {
            "pass":  f"{_GREEN}ok{_RESET}",
            "fail":  f"{_RED}FAIL{_RESET}",
            "error": f"{_RED}ERROR{_RESET}",
            "skip":  f"{_YELLOW}skip{_RESET}",
        }
        for r in result.records:
            extra = f" ({r.message[:80]})" if r.status == "skip" else ""
            print(f"{r.method} ({r.cls}) ... {_tag[r.status]}{extra}", file=old_stderr)
        n_pass = sum(1 for r in result.records if r.status == "pass")
        n_fail = sum(1 for r in result.records if r.status in ("fail", "error"))
        n_skip = sum(1 for r in result.records if r.status == "skip")
        parts = [f"{_BOLD}Ran {len(result.records)} tests{_RESET}"]
        if n_pass:
            parts.append(f"{_GREEN}{n_pass} passed{_RESET}")
        if n_fail:
            parts.append(f"{_RED}{n_fail} failed{_RESET}")
        if n_skip:
            parts.append(f"{_YELLOW}{n_skip} skipped{_RESET}")
        print(" — ".join(parts), file=old_stderr)
    finally:
        sys.stderr = old_stderr
        sys.stdout = old_stdout

    stderr_capture.write(tee_err.getvalue())
    stderr_capture.write(tee_out.getvalue())
    return result


def _clear_suite_env() -> None:
    for name in (ENV_NANOCHAT_URL, ENV_NANOCHAT_BOOT_ERROR, ENV_NANOCHAT_LOG):
        os.environ.pop(name, None)


def _start_suite_services(module_names: list[str]) -> NanoChatServer | None:
    """Start shared services once for modules that require them."""
    _clear_suite_env()
    if not _SHARED_NANOCHAT_MODULES.intersection(module_names):
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


def _generate_html(result: _HTMLResult, captured_output: str,
                   elapsed_total: float) -> str:
    """Build the HTML report string."""
    now = datetime.datetime.now()

    all_records = list(result.records)

    passed = sum(1 for r in all_records if r.status == "pass")
    failed = sum(1 for r in all_records if r.status == "fail")
    errors = sum(1 for r in all_records if r.status == "error")
    skipped = sum(1 for r in all_records if r.status == "skip")
    total = len(all_records)

    status_icon = {
        "pass": "&#x2705;",   # green check
        "fail": "&#x274C;",   # red X
        "error": "&#x1F4A5;", # explosion
        "skip": "&#x23ED;",   # skip
    }
    status_class = {
        "pass": "pass",
        "fail": "fail",
        "error": "error",
        "skip": "skip",
    }

    # Group by module
    by_module: dict[str, list[_TestRecord]] = {}
    for r in all_records:
        by_module.setdefault(r.module, []).append(r)

    # Extract [WikiOracle] warnings
    wo_warnings = [
        line for line in captured_output.splitlines()
        if "[WikiOracle]" in line
    ]

    rows = []
    for module, records in by_module.items():
        mod_short = module.replace("test.", "")
        mod_passed = sum(1 for r in records if r.status == "pass")
        mod_total = len(records)
        mod_status = "pass" if all(r.status in ("pass", "skip") for r in records) else "fail"

        rows.append(f'<tr class="module-header {status_class[mod_status]}">')
        rows.append(f'  <td colspan="4"><strong>{html.escape(mod_short)}</strong> '
                     f'({mod_passed}/{mod_total})</td>')
        rows.append('</tr>')

        for r in records:
            rows.append(f'<tr class="{status_class[r.status]}">')
            rows.append(f'  <td class="icon">{status_icon[r.status]}</td>')
            rows.append(f'  <td>{html.escape(r.cls)}.{html.escape(r.method)}</td>')
            rows.append(f'  <td class="time">{r.elapsed:.3f}s</td>')
            msg_cell = html.escape(r.message[:200]) if r.message else ""
            rows.append(f'  <td class="msg">{msg_cell}</td>')
            rows.append('</tr>')

    table_body = "\n".join(rows)

    warn_section = ""
    if wo_warnings:
        warn_items = "\n".join(
            f"<li>{html.escape(w.strip())}</li>" for w in wo_warnings
        )
        warn_section = f"""
    <details>
      <summary>Runtime warnings ({len(wo_warnings)})</summary>
      <ul class="warnings">{warn_items}</ul>
    </details>"""

    overall = "PASS" if (failed + errors) == 0 else "FAIL"
    overall_class = "pass" if overall == "PASS" else "fail"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WikiOracle Test Report — {now.strftime('%Y-%m-%d %H:%M')}</title>
<style>
  :root {{ --pass: #d4edda; --fail: #f8d7da; --skip: #fff3cd; --error: #f5c6cb; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .meta {{ color: #666; margin-bottom: 1.5rem; }}
  .summary {{ display: flex; gap: 1.5rem; margin-bottom: 1.5rem; flex-wrap: wrap; }}
  .summary .card {{ padding: 1rem 1.5rem; border-radius: 8px; font-size: 1.1rem; }}
  .summary .card.pass {{ background: var(--pass); }}
  .summary .card.fail {{ background: var(--fail); }}
  .summary .card.skip {{ background: var(--skip); }}
  .summary .overall {{ font-weight: bold; font-size: 1.3rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #e0e0e0; }}
  th {{ background: #f8f9fa; }}
  tr.pass {{ background: #f0faf0; }}
  tr.fail, tr.error {{ background: #fdf0f0; }}
  tr.skip {{ background: #fffbe6; }}
  tr.module-header {{ background: #f0f0f0; }}
  tr.module-header.fail {{ background: #fce4e4; }}
  .icon {{ width: 1.5rem; text-align: center; }}
  .time {{ width: 5rem; text-align: right; font-variant-numeric: tabular-nums; }}
  .msg {{ font-size: 0.85rem; color: #888; max-width: 300px; overflow: hidden;
          text-overflow: ellipsis; white-space: nowrap; }}
  details {{ margin-bottom: 1rem; }}
  summary {{ cursor: pointer; font-weight: 600; }}
  .warnings {{ font-family: monospace; font-size: 0.85rem; list-style: none; padding: 0; }}
  .warnings li {{ padding: 0.2rem 0; border-bottom: 1px solid #eee; }}
  footer {{ color: #999; font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>WikiOracle Test Report</h1>
<p class="meta">{now.strftime('%Y-%m-%d %H:%M:%S')} &mdash; {elapsed_total:.1f}s total</p>

<div class="summary">
  <div class="card overall {overall_class}">{overall}</div>
  <div class="card pass">{passed} passed</div>
  <div class="card fail">{failed + errors} failed</div>
  <div class="card skip">{skipped} skipped</div>
</div>

<table>
<thead>
  <tr><th></th><th>Test</th><th class="time">Time</th><th>Info</th></tr>
</thead>
<tbody>
{table_body}
</tbody>
</table>

{warn_section}

<footer>Generated by test/run_tests.py &mdash; provider: wikioracle (local)</footer>
</body>
</html>
"""


def main():
    os.chdir(_project)

    output_dir = _project / "output"
    output_dir.mkdir(exist_ok=True)

    t0 = time.monotonic()
    captured = io.StringIO()

    print(f"{_BOLD}WikiOracle Test Suite{_RESET}")
    shared_nanochat = _start_suite_services(_TEST_MODULES)
    try:
        result = _run_modules(_TEST_MODULES, captured)
    finally:
        if shared_nanochat is not None:
            print(f"{_CYAN}Stopping shared NanoChat...{_RESET}", file=sys.stderr)
            shared_nanochat.stop()
        _clear_suite_env()

    elapsed = time.monotonic() - t0

    # Generate HTML
    html_content = _generate_html(result, captured.getvalue(), elapsed)

    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    out_path = output_dir / f"test_{date_str}.html"
    out_path.write_text(html_content, encoding="utf-8")
    print(f"\n{_CYAN}HTML report:{_RESET} {out_path}")

    ok = len(result.failures) + len(result.errors) == 0
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
