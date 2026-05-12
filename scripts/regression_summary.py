"""Render a Markdown summary of the regression workflow's pytest results.

Reads JUnit XML artifacts (smoke + full) and emits a single Markdown block
suitable for posting as a PR comment. The workflow at
`.github/workflows/regression.yml` invokes this with:

    python scripts/regression_summary.py \
        --smoke-xml junit-smoke.xml \
        --full-xml junit-full.xml \
        --baseline-ref <sha>

The output structure:

    ### Regression gate · <verdict>

    | Tier  | Total | Passed | Failed | Skipped | Duration |
    |-------|-------|--------|--------|---------|----------|
    | Smoke |   5   |   5    |   0    |    0    |   7.2s   |
    | Full  |  25   |  25    |   0    |    0    |  32.1s   |

    <details>
    <summary>Failed cases (N)</summary>

    - `<test_name>` — <first 200 chars of failure message>

    </details>

Stdout is the rendered markdown. Exit code is always zero — the parent
workflow decides whether to fail based on pytest exit codes, not on this
script. The script's only job is to render.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TierStats:
    tier: str
    total: int
    passed: int
    failed: int
    skipped: int
    duration_s: float
    failures: list[tuple[str, str]]  # (test_name, short message)


def _parse_junit(path: Path | None, tier: str) -> TierStats | None:
    """Read a junit XML file. Returns None if the file is missing (the
    upstream pytest step likely never ran)."""
    if path is None or not path.is_file():
        return None
    tree = ET.parse(path)
    root = tree.getroot()
    # JUnit may wrap the testsuite in a <testsuites> root, or be the suite
    # itself. Handle both.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    total = passed = failed = skipped = 0
    duration = 0.0
    failures: list[tuple[str, str]] = []
    for suite in suites:
        total += int(suite.attrib.get("tests", 0))
        failed += int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
        duration += float(suite.attrib.get("time", 0.0))
        for case in suite.findall("testcase"):
            # Use `is not None` — ElementTree elements warn on truthy checks.
            fail = case.find("failure")
            if fail is None:
                fail = case.find("error")
            if fail is not None:
                name = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '?')}"
                msg = (fail.attrib.get("message") or fail.text or "").strip()
                # Keep the comment tight — first 200 chars of the first line.
                msg = msg.splitlines()[0] if msg else ""
                if len(msg) > 200:
                    msg = msg[:197] + "…"
                failures.append((name, msg))
    passed = total - failed - skipped
    return TierStats(
        tier=tier,
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        duration_s=duration,
        failures=failures,
    )


def _format(stats_list: list[TierStats], baseline_ref: str | None) -> str:
    any_failed = any(s.failed > 0 for s in stats_list)
    verdict = "❌ failed" if any_failed else "✅ passed"
    lines: list[str] = []
    lines.append(f"### Regression gate · {verdict}")
    lines.append("")
    if baseline_ref:
        lines.append(f"_Baseline ref: `{baseline_ref}`_")
        lines.append("")
    lines.append("| Tier  | Total | Passed | Failed | Skipped | Duration |")
    lines.append("|-------|-------|--------|--------|---------|----------|")
    for s in stats_list:
        lines.append(
            f"| {s.tier} | {s.total} | {s.passed} | {s.failed} | "
            f"{s.skipped} | {s.duration_s:.1f}s |"
        )
    lines.append("")
    all_failures = [(s.tier, name, msg) for s in stats_list for name, msg in s.failures]
    if all_failures:
        lines.append("<details>")
        lines.append(f"<summary>Failed cases ({len(all_failures)})</summary>")
        lines.append("")
        for tier, name, msg in all_failures:
            short_name = name.split("::")[-1]
            suffix = f" — {msg}" if msg else ""
            lines.append(f"- **[{tier}]** `{short_name}`{suffix}")
        lines.append("")
        lines.append("</details>")
        lines.append("")
        lines.append(
            "If the failures are intentional (you changed a prompt and the "
            "regression baseline needs updating), re-record locally:\n\n"
            "```bash\npytest -m regression_record  # bootstrap cassettes (free)\n"
            "# OR, for real-LLM cassettes:\n"
            "pytest -m regression_record_live -k '<slug substrings>'\n```\n"
        )
    else:
        lines.append("No regressions detected.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-xml", type=Path, default=None)
    parser.add_argument("--full-xml", type=Path, default=None)
    parser.add_argument("--baseline-ref", type=str, default=None)
    args = parser.parse_args(argv)

    tiers: list[TierStats] = []
    smoke = _parse_junit(args.smoke_xml, "Smoke")
    full = _parse_junit(args.full_xml, "Full")
    if smoke is not None:
        tiers.append(smoke)
    if full is not None:
        tiers.append(full)
    if not tiers:
        print("### Regression gate · ⚠️ no results")
        print()
        print("No JUnit XML artifacts found — the pytest step likely never ran.")
        return 0

    print(_format(tiers, args.baseline_ref))
    return 0


if __name__ == "__main__":
    sys.exit(main())
