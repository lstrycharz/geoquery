"""Post-merge attribution for the meta-agent — does the change actually help?

Two phases, both driven by GitHub Actions:

  snapshot_baseline  — fires on merge of a `meta-agent/*` PR. Records the merge
                       SHA + the pre-merge eval-score window into the proposal
                       row, status -> 'merged'.
  measure_proposal   — runs later (weekly, alongside the propose cron). Once
                       enough post-merge runs exist, compares the after-window
                       to the snapshotted before-window. status -> 'measured';
                       on a clearly-negative result it opens an auto-revert PR
                       (status -> 'reverted') so the loop closes both ways —
                       the meta-agent must not be able to ratchet only upward.

`meta/stats.py` does the honest arithmetic — no significance test, because the
sample sizes can't support one.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from memory import EpisodicMemory
from meta.github_pr import RevertPublisher
from meta.stats import EffectMeasurement, measure_effect

# An eval-score drop past this is "clearly negative" — worth an auto-revert PR
# (a human still reviews it). Smaller dips read as inconclusive, which at these
# sample sizes is usually the honest answer.
_CLEARLY_NEGATIVE_DELTA = -0.05

# Default number of post-merge runs required before a measurement is attempted.
_DEFAULT_REQUIRED_N = 20

# Default size of the pre-merge baseline window snapshotted at merge time.
_DEFAULT_BEFORE_LIMIT = 20


@dataclass(frozen=True)
class MeasurementOutcome:
    proposal_id: int
    status: str  # 'merged' (still pending) | 'measured' | 'reverted'
    effect: EffectMeasurement | None
    revert_pr_url: str | None


def snapshot_baseline(
    episodic: EpisodicMemory,
    *,
    pr_number: int,
    merged_at: str,
    merged_sha: str,
    before_limit: int = _DEFAULT_BEFORE_LIMIT,
) -> int:
    """On merge: freeze the pre-merge eval-score window so the later
    measurement compares against a stable baseline. Returns the proposal id."""
    proposal = episodic.get_meta_proposal_by_pr(pr_number)
    if proposal is None:
        raise ValueError(f"no meta_proposal recorded for PR #{pr_number}")
    before_scores = episodic.completed_run_scores(before=merged_at, limit=before_limit)
    episodic.update_meta_proposal(
        proposal["id"],
        status="merged",
        merged_at=merged_at,
        baseline_window_json=json.dumps({"merged_sha": merged_sha, "before_scores": before_scores}),
    )
    return proposal["id"]


def measure_proposal(
    episodic: EpisodicMemory,
    *,
    proposal_id: int,
    required_n: int = _DEFAULT_REQUIRED_N,
    revert_publisher: RevertPublisher | None = None,
) -> MeasurementOutcome:
    """Compare the post-merge window against the snapshotted baseline.

    Stays 'merged' (pending) until `required_n` post-merge runs exist. Then it
    measures: 'measured' on a neutral/positive result, 'reverted' (with an
    auto-revert PR) on a clearly-negative one.
    """
    proposal = episodic.get_meta_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f"no meta_proposal with id {proposal_id}")
    if proposal["status"] != "merged" or not proposal["merged_at"]:
        # Not in a measurable state (never merged, or already measured).
        return MeasurementOutcome(proposal_id, proposal["status"], None, None)

    snapshot = json.loads(proposal["baseline_window_json"])
    before_scores: list[float] = snapshot["before_scores"]
    merged_sha: str = snapshot["merged_sha"]

    after_scores = episodic.completed_run_scores(after=proposal["merged_at"])
    if len(after_scores) < required_n or not before_scores:
        return MeasurementOutcome(proposal_id, "merged", None, None)

    effect = measure_effect(before_scores, after_scores)
    if effect.delta < _CLEARLY_NEGATIVE_DELTA:
        revert_url = None
        if revert_publisher is not None:
            opened = revert_publisher.publish_revert(
                merge_sha=merged_sha,
                title=f"Revert meta-agent change for {proposal['target_pattern']}",
                body=_revert_body(proposal, effect),
            )
            revert_url = opened.url
        episodic.update_meta_proposal(proposal_id, status="reverted")
        return MeasurementOutcome(proposal_id, "reverted", effect, revert_url)

    episodic.update_meta_proposal(proposal_id, status="measured")
    return MeasurementOutcome(proposal_id, "measured", effect, None)


def measure_all(
    episodic: EpisodicMemory, *, revert_publisher: RevertPublisher | None = None
) -> list[MeasurementOutcome]:
    """Measure every merged-but-not-yet-measured proposal — the weekly pass."""
    return [
        measure_proposal(episodic, proposal_id=p["id"], revert_publisher=revert_publisher)
        for p in episodic.list_meta_proposals(status="merged")
    ]


def _revert_body(proposal: dict, effect: EffectMeasurement) -> str:
    powered = "UNDERPOWERED — " if effect.underpowered else ""
    return (
        f"Auto-revert: the meta-agent change for `{proposal['target_pattern']}` "
        f"measured clearly negative post-merge.\n\n"
        f"- before mean: {effect.before_mean:.3f} (n={effect.before_n})\n"
        f"- after mean: {effect.after_mean:.3f} (n={effect.after_n})\n"
        f"- delta: {effect.delta:+.3f} ({powered}effect size {effect.effect_size:+.2f})\n\n"
        f"Original hypothesis: {proposal['hypothesis']}\n\n"
        f"A human still reviews and merges this revert — the loop closes both "
        f"directions, but a person decides."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="meta.measure", description=__doc__)
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument(
        "--snapshot",
        action="store_true",
        help="freeze the baseline for a just-merged meta-agent PR",
    )
    sub.add_argument(
        "--measure-all",
        action="store_true",
        help="measure every merged-but-unmeasured proposal",
    )
    parser.add_argument("--pr", type=int, help="PR number (with --snapshot)")
    parser.add_argument("--sha", type=str, help="merge commit SHA (with --snapshot)")
    parser.add_argument("--merged-at", type=str, help="merge timestamp ISO (with --snapshot)")
    args = parser.parse_args(argv)

    from config import get_settings

    settings = get_settings()
    episodic = EpisodicMemory(db_path=settings.data_dir / "episodic.db")

    if args.snapshot:
        if not args.pr or not args.sha or not args.merged_at:
            parser.error("--snapshot needs --pr, --sha and --merged-at")
        pid = snapshot_baseline(
            episodic, pr_number=args.pr, merged_at=args.merged_at, merged_sha=args.sha
        )
        print(f"baseline snapshotted for proposal {pid} (PR #{args.pr})")
        return 0

    # --measure-all
    import os

    from meta.github_pr import GitHubPRPublisher

    revert_publisher: RevertPublisher | None = None
    token = os.getenv("GITHUB_META_AGENT_TOKEN", "")
    repo_slug = os.getenv("GITHUB_REPO", "")
    if token and repo_slug:
        revert_publisher = GitHubPRPublisher(repo_root=Path.cwd(), token=token, repo_slug=repo_slug)
    outcomes = measure_all(episodic, revert_publisher=revert_publisher)
    for o in outcomes:
        line = f"proposal {o.proposal_id}: {o.status}"
        if o.effect is not None:
            line += f" (delta {o.effect.delta:+.3f}, n={o.effect.after_n})"
        if o.revert_pr_url:
            line += f" — revert PR {o.revert_pr_url}"
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
