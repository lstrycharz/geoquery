"""scripts/regression_summary.py — junit XML → markdown for the CI gate."""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not on sys.path by default — make it importable for the test.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from regression_summary import _format, _parse_junit, main  # noqa: E402

PASS_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="3" failures="0" errors="0" skipped="0" time="6.5">
  <testcase classname="tests.test_regression" name="test_smoke[notion]" time="1.0"/>
  <testcase classname="tests.test_regression" name="test_smoke[stripe]" time="1.1"/>
  <testcase classname="tests.test_regression" name="test_smoke[webflow]" time="1.2"/>
</testsuite>
"""

FAIL_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="2" failures="1" errors="0" skipped="0" time="5.2">
  <testcase classname="tests.test_regression" name="test_full[hubspot]" time="1.0"/>
  <testcase classname="tests.test_regression" name="test_full[shopify]" time="1.1">
    <failure message="composite score collapsed; angle drift">…trace…</failure>
  </testcase>
</testsuite>
"""

WRAPPED_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite tests="1" failures="0" errors="0" skipped="0" time="3.0">
    <testcase classname="tests.x" name="y" time="3.0"/>
  </testsuite>
</testsuites>
"""


def test_parse_returns_none_when_file_missing(tmp_path):
    assert _parse_junit(tmp_path / "nope.xml", "smoke") is None


def test_parse_counts_pass_and_duration(tmp_path):
    path = tmp_path / "smoke.xml"
    path.write_text(PASS_XML)
    stats = _parse_junit(path, "Smoke")
    assert stats is not None
    assert stats.total == 3
    assert stats.passed == 3
    assert stats.failed == 0
    assert stats.duration_s == 6.5
    assert stats.failures == []


def test_parse_extracts_failures_with_truncated_message(tmp_path):
    path = tmp_path / "full.xml"
    path.write_text(FAIL_XML)
    stats = _parse_junit(path, "Full")
    assert stats is not None
    assert stats.failed == 1
    assert stats.passed == 1
    assert len(stats.failures) == 1
    name, msg = stats.failures[0]
    assert "test_full[shopify]" in name
    assert "composite score collapsed" in msg


def test_parse_handles_testsuites_wrapper(tmp_path):
    path = tmp_path / "wrapped.xml"
    path.write_text(WRAPPED_XML)
    stats = _parse_junit(path, "Smoke")
    assert stats is not None
    assert stats.total == 1
    assert stats.failed == 0


def test_format_pass_path_announces_no_regressions(tmp_path):
    smoke = _parse_junit_text(PASS_XML, tmp_path / "s.xml", "Smoke")
    out = _format([smoke], baseline_ref="abc123")
    assert "Regression gate · ✅ passed" in out
    assert "No regressions detected." in out
    assert "abc123" in out
    assert "| Smoke | 3 | 3 | 0 | 0 |" in out


def test_format_fail_path_lists_failures_and_recovery_steps(tmp_path):
    smoke = _parse_junit_text(PASS_XML, tmp_path / "s.xml", "Smoke")
    full = _parse_junit_text(FAIL_XML, tmp_path / "f.xml", "Full")
    out = _format([smoke, full], baseline_ref=None)
    assert "Regression gate · ❌ failed" in out
    assert "Failed cases (1)" in out
    assert "test_full[shopify]" in out
    assert "regression_record" in out  # the recovery instruction is present


def test_main_emits_markdown_to_stdout(tmp_path, capsys):
    s = tmp_path / "s.xml"
    s.write_text(PASS_XML)
    f = tmp_path / "f.xml"
    f.write_text(FAIL_XML)
    exit_code = main(["--smoke-xml", str(s), "--full-xml", str(f), "--baseline-ref", "origin/main"])
    assert exit_code == 0  # render-only; CI's pytest steps decide success
    captured = capsys.readouterr().out
    assert "Regression gate" in captured
    assert "origin/main" in captured


def test_main_handles_missing_artifacts_gracefully(tmp_path, capsys):
    exit_code = main(["--smoke-xml", str(tmp_path / "nope.xml")])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no results" in out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_junit_text(xml: str, path: Path, tier: str):
    path.write_text(xml)
    return _parse_junit(path, tier)
