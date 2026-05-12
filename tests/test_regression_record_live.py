"""Live-recording bootstrap — REAL Anthropic API. Costs real money.

Marker: `regression_record_live`. Excluded from default `pytest` so no spend
happens by accident. Each case ≈ $0.50 (one full agent run: 7 skills + 6
judge calls on real Sonnet/Haiku endpoints).

Typical usage:

    # Re-record just the 5 smoke cases (~$2.50):
    pytest -m regression_record_live -k 'notion or linear or glossier or stripe or webflow'

    # Re-record the entire 30-case dataset (~$15):
    pytest -m regression_record_live

    # Re-record one specific slug:
    pytest -m regression_record_live -k notion_b2b_saas

After recording, the existing `pytest -m regression_smoke` / `regression_full`
runs replay the new cassettes and should still pass — if a real prompt has a
flaw that flips an eval, the regression suite surfaces it loudly.

Requirements:
- `ANTHROPIC_API_KEY` set to a real, working key in `.env` or environment.
  (The fixture `live_settings` skips the test if the key is the test stub.)
- `MAX_COST_USD` is bumped per-case to $1.50 (a real Notion brief is ~$0.55;
  budgeted ceiling gives headroom for revisions). Edit `live_settings` if you
  want a tighter cap.

The live recording shares the same `record_case_to_disk` helper as the
fake-client bootstrap — only the inner client differs.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from anthropic import Anthropic

from evals.regression import record_case_to_disk
from tests.test_regression_record import _ALL_CASES


def _resolve_live_key() -> str | None:
    """Look for a real ANTHROPIC_API_KEY in (in order): shell env, then `.env`.

    The conftest preempts shell env with a `sk-ant-test` stub for safety, so we
    can't trust `os.environ` alone — we explicitly parse `.env` as a fallback.
    Returns None if no real key is found, which makes the fixture skip the test.
    """
    shell_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if shell_key and not shell_key.startswith("sk-ant-test"):
        return shell_key
    dotenv = Path(__file__).resolve().parent.parent / ".env"
    if not dotenv.is_file():
        return None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == "ANTHROPIC_API_KEY":
            val = v.strip().strip('"').strip("'")
            if val and not val.startswith("sk-ant-test"):
                return val
    return None


@pytest.fixture
def live_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated Settings that use the REAL ANTHROPIC_API_KEY from env or .env."""
    from config import Settings, reset_settings_for_tests

    real_key = _resolve_live_key()
    if not real_key:
        pytest.skip(
            "no real ANTHROPIC_API_KEY found in shell env or .env; skipping live recording."
        )
    monkeypatch.setenv("ANTHROPIC_API_KEY", real_key)
    monkeypatch.setenv("MAX_COST_USD", "1.50")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "briefs"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_settings_for_tests()
    settings = Settings()
    settings.ensure_dirs()
    yield settings
    reset_settings_for_tests()


@pytest.mark.regression_record_live
@pytest.mark.parametrize("slug,company,market,tier", _ALL_CASES)
def test_record_case_live(live_settings, stub_embedder, slug, company, market, tier):
    """Spend ~$0.50 to record one real-LLM cassette into regression_dataset/<slug>/."""
    client = Anthropic()
    record_case_to_disk(
        slug=slug,
        company=company,
        market=market,
        tier=tier,
        source="live-anthropic",
        client=client,
        settings=live_settings,
        embedder=stub_embedder,
        # SERP-page-content fetch is left stubbed for deterministic replay —
        # real-fetch + real-SERP recording is a deeper mode we can enable
        # later (cassette would need to capture web-fetch results too).
        fetch_page=lambda url: None,
    )


def test_live_recording_test_is_excluded_from_default_run():
    """Defense-in-depth: the marker must be in `addopts` deselect list."""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    src = pyproject.read_text()
    assert "regression_record_live" in src
    assert "not regression_record_live" in src
