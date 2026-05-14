"""Build data/episodic.demo.db — committed snapshot used by the deployed
Streamlit dashboard (Streamlit Cloud has no live `data/episodic.db`).

Seeds 30 runs across 14 days with realistic cost / pass-rate distributions so
all four dashboard pages render against non-empty data.

Run on demand:

    python scripts/build_demo_db.py

The script is idempotent — it deletes the existing demo DB and rebuilds from
scratch. Real `data/episodic.db` is untouched.
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from memory.episodic import EpisodicMemory, SkillInvocationRecord  # noqa: E402

DEMO_DB_PATH = PROJECT_ROOT / "data" / "episodic.demo.db"

# A representative spread of public-company / market pairs. Matches the
# regression-dataset slugs so the dashboard reads "the same companies you see
# in the cassettes" — coherent narrative for a reader skimming both.
_COMPANIES = [
    ("Notion", "B2B SaaS knowledge management"),
    ("Linear", "B2B SaaS project management"),
    ("Glossier", "DTC beauty"),
    ("Stripe", "payments infrastructure"),
    ("Webflow", "no-code design platform"),
    ("HubSpot", "small-business CRM"),
    ("Vercel", "frontend cloud hosting"),
    ("Patagonia", "DTC outdoor apparel"),
    ("Shopify", "e-commerce platform"),
    ("Figma", "collaborative product design"),
    ("Mailchimp", "email marketing for SMBs"),
    ("Slack", "team messaging"),
    ("Airbnb", "vacation rental marketplace"),
    ("DoorDash", "on-demand food delivery"),
    ("Duolingo", "mobile language learning"),
]

_SKILLS = [
    ("research_company", "claude-sonnet-4-6"),
    ("define_icp", "claude-sonnet-4-6"),
    ("generate_geo_query_list", "claude-haiku-4-5"),
    ("score_queries", "claude-sonnet-4-6"),
    ("select_priority_query", "claude-sonnet-4-6"),
    ("analyze_serp", "claude-sonnet-4-6"),
    ("draft_content_brief", "claude-sonnet-4-6"),
]

# Per-skill pass-rate baseline. Most are flawless; a couple have realistic
# failure modes that the Evals + Tools pages will surface.
_BASE_PASS_RATES = {
    "research_company": 1.00,
    "define_icp": 1.00,
    "generate_geo_query_list": 0.94,  # buyer-realism judge sometimes flags
    "score_queries": 1.00,
    "select_priority_query": 0.97,
    "analyze_serp": 0.92,  # the contract bug surfaced in chunk-4 path 2
    "draft_content_brief": 0.96,
}


def _seed(rng: random.Random, memory: EpisodicMemory) -> None:
    now = datetime.now(UTC)
    completed_run_ids: list[str] = []  # for seeding the review queue
    for day_offset in range(13, -1, -1):  # 14 days, oldest first
        day_start = now - timedelta(days=day_offset)
        # v3 chunk 10: a gentle upward quality ramp over the 14-day window, so
        # the Learning Curve page shows the system getting better over time
        # (synthetic — this is demo data). 0.0 on the oldest day, 1.0 on today.
        day_progress = (13 - day_offset) / 13.0
        runs_today = rng.randint(1, 4)  # uneven volume per day
        for _ in range(runs_today):
            company, market = rng.choice(_COMPANIES)
            started = day_start + timedelta(minutes=rng.randint(0, 23 * 60))
            run = memory.start_run(company=company, market=market)
            # Backdate the row to the simulated day; the auto-now value would
            # bunch everything into today.
            with memory._connect() as conn:
                conn.execute(
                    "UPDATE runs SET started_at = ? WHERE id = ?",
                    (started.isoformat(), run.id),
                )

            cumulative_cost = 0.0
            run_failed = False
            for skill_name, model in _SKILLS:
                # Skip remaining skills if a prior one's "tool failure" path fired.
                if run_failed:
                    break
                # Ramp the base pass rate by day progress: early runs are
                # noisier, later runs cleaner.
                base = min(1.0, _BASE_PASS_RATES[skill_name] * (0.85 + 0.15 * day_progress))
                eval_passed = rng.random() < base
                # 2% of invocations simulate a tool fault (eval_passed = NULL).
                if rng.random() < 0.02:
                    eval_passed_val: bool | None = None
                    run_failed = True
                else:
                    eval_passed_val = eval_passed

                input_tokens = rng.randint(1500, 6000)
                output_tokens = rng.randint(400, 2000)
                # Rough Sonnet/Haiku cost — same shape as estimate_cost(), but
                # this is seed data so exactness doesn't matter.
                in_rate = 0.80 if "haiku" in model else 3.00
                out_rate = 4.00 if "haiku" in model else 15.00
                cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
                cumulative_cost += cost

                memory.log_skill_invocation(
                    SkillInvocationRecord(
                        run_id=run.id,
                        skill_name=skill_name,
                        attempt=1 if eval_passed else 2,
                        model=model,
                        input_json="{}",
                        started_at=started.isoformat(),
                        eval_passed=eval_passed_val,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost,
                        duration_ms=rng.randint(2000, 30000),
                    )
                )

            status = "failed" if run_failed else "completed"
            memory.finish_run(
                run_id=run.id,
                status=status,
                total_cost_usd=cumulative_cost,
                brief_path=(
                    f"briefs/{run.id[:8]}_{company.lower()}_demo.md" if not run_failed else None
                ),
            )
            if not run_failed:
                completed_run_ids.append(run.id)

    # Seed a handful of pending sampled reviews (~10% of completed runs) so
    # the Review_Queue page lands non-empty. A couple already-reviewed rows
    # too, to populate the eventual divergence chart.
    sample_count = max(2, len(completed_run_ids) // 10)
    sampled = rng.sample(completed_run_ids, sample_count)
    for run_id in sampled:
        memory.start_human_review(run_id=run_id)
    # Mark one of them as reviewed with a low rating so chunk 8's divergence
    # detector has something to flag in the demo data.
    if sampled:
        review = memory.get_pending_reviews(limit=1)
        if review:
            memory.record_human_review(
                review_id=review[0]["id"],
                rating_overall=2,
                ratings_by_dim={"brand_voice": 4, "intent_fit": 2, "actionability": 2},
                notes="judges said this passed but the angle was generic and key points abstract",
            )

    # v3 chunk 10: a few merged meta-agent proposals across the window so the
    # Learning Curve page has annotations. Two measured, one reverted — the
    # loop closes both directions, and the demo shows that.
    _seed_meta_proposals(memory, now)


def _seed_meta_proposals(memory: EpisodicMemory, now: datetime) -> None:
    proposals = [
        (10, "drift:score_queries", "prompt", "measured"),
        (7, "drift:draft_content_brief", "rubric", "reverted"),
        (3, "winning_patterns:stale", "prompt", "measured"),
    ]
    for days_ago, target_pattern, change_type, status in proposals:
        merged_at = now - timedelta(days=days_ago)
        created_at = merged_at - timedelta(days=1)
        pid = memory.record_meta_proposal(
            target_pattern=target_pattern,
            change_type=change_type,
            hypothesis=f"meta-agent proposal for {target_pattern}",
            branch=f"meta-agent/{target_pattern.replace(':', '-')}",
            pr_number=100 + days_ago,
            created_at=created_at.isoformat(),
        )
        memory.update_meta_proposal(pid, status=status, merged_at=merged_at.isoformat())


def main() -> None:
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DEMO_DB_PATH.exists():
        DEMO_DB_PATH.unlink()
    memory = EpisodicMemory(DEMO_DB_PATH)
    rng = random.Random(42)  # deterministic seed → same demo every build
    _seed(rng, memory)
    print(f"wrote {DEMO_DB_PATH}")


if __name__ == "__main__":
    main()
