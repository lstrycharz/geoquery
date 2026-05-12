"""Golden eval runner — fully stubbed (no real API, no real run_brief)."""

from __future__ import annotations

from pathlib import Path

from agent import AgentOutcome
from evals.golden_set import (
    GoldenJudgeVerdict,
    GoldenReport,
    render_html_report,
    run_golden_set,
)


def _fake_run_brief(brief_path_root: Path):
    def _run(company: str, market: str, sitemap_url: str | None = None) -> AgentOutcome:
        path = brief_path_root / f"{company.lower()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# brief\n")
        return AgentOutcome(
            run_id=f"run-{company.lower()}",
            status="completed",
            brief_path=path,
            total_cost_usd=0.30,
        )

    return _run


def _fake_judge(pass_for: set[str]):
    def _judge(*, client, brief, icp_segment_label, expected_themes, budget):
        # Use the input_id-shape we pass via the brief reload helper; here we
        # piggyback by checking expected_themes' rationale text or just always
        # passing/failing based on the company name in the angle.
        passed = any(name in brief.angle.lower() for name in pass_for)
        return GoldenJudgeVerdict(
            icp_keywords_matched=expected_themes["icp_role_keywords"][:2] if passed else [],
            icp_keywords_missing=[] if passed else expected_themes["icp_role_keywords"],
            angle_keywords_matched=expected_themes["brief_angle_keywords"][:2] if passed else [],
            angle_keywords_missing=[] if passed else expected_themes["brief_angle_keywords"],
            overall_pass=passed,
            notes="" if passed else "fake judge says: not enough keywords matched",
        )

    return _judge


def _fake_load_brief(monkeypatch, angle_text: str):
    from contracts import ContentBrief

    fake_brief = ContentBrief(
        target_query="t",
        icp_segment_label="Director of Engineering",
        angle=angle_text,
        audience="x",
        structure=[],
        key_points=["a"],
        sources=["b"],
        recommended_length_words=1500,
    )
    from evals import golden_set

    monkeypatch.setattr(golden_set, "_load_brief_from_outcome", lambda outcome: fake_brief)


def test_golden_runs_each_input(tmp_path, fake_client, monkeypatch):
    _fake_load_brief(monkeypatch, angle_text="knowledge engineering single source")

    report = run_golden_set(
        run_brief=_fake_run_brief(tmp_path),
        client=fake_client,
        judge_brief=_fake_judge(pass_for={"engineering"}),
    )

    assert len(report.results) == 3
    assert report.results[0].run_status == "completed"
    assert report.pass_rate > 0


def test_golden_pass_rate_aggregates(tmp_path, fake_client, monkeypatch):
    """If the judge passes on every input, pass_rate is 1.0."""
    _fake_load_brief(monkeypatch, angle_text="engineering knowledge skincare")

    report = run_golden_set(
        run_brief=_fake_run_brief(tmp_path),
        client=fake_client,
        # Always pass: matches one keyword from every input's expected list.
        judge_brief=_fake_judge(pass_for={"engineering", "skincare"}),
    )
    assert report.pass_rate == 1.0


def test_golden_renders_html_report(tmp_path, fake_client, monkeypatch):
    _fake_load_brief(monkeypatch, angle_text="engineering and skincare")
    report = run_golden_set(
        run_brief=_fake_run_brief(tmp_path),
        client=fake_client,
        judge_brief=_fake_judge(pass_for={"engineering", "skincare"}),
    )
    html = render_html_report(report)
    assert "<title>Golden Eval Report" in html
    assert "Pass rate" in html
    for r in report.results:
        assert r.company in html


def test_golden_marks_failed_run_as_not_passed(fake_client, tmp_path, monkeypatch):
    """When a run aborts before producing a brief, the result is not passing."""

    def _abort(company: str, market: str, sitemap_url=None):
        return AgentOutcome(
            run_id="r", status="aborted_cost", brief_path=None, total_cost_usd=0.0, error="budget"
        )

    report = run_golden_set(
        run_brief=_abort,
        client=fake_client,
        judge_brief=_fake_judge(pass_for={"engineering"}),
    )
    assert all(not r.passed for r in report.results)
    assert isinstance(report, GoldenReport)
