"""Effect-size measurement for the meta-agent — no scipy, no t-test theater.

20 runs/week can't support a significance test, and pretending otherwise would
be the statistical equivalent of the reward hacking this whole layer guards
against. So `measure_effect` reports the honest primitives: before/after means,
the delta, a standardized effect size (Cohen's d), and an `underpowered` flag
when the sample is too thin to trust. The human reads those and decides.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EffectMeasurement:
    before_mean: float
    before_n: int
    after_mean: float
    after_n: int
    delta: float  # after_mean - before_mean
    effect_size: float  # Cohen's d: delta / pooled_std (0.0 when no variance)
    underpowered: bool  # after_n < min_n — too thin to trust


def _population_variance(values: list[float], mean: float) -> float:
    return sum((x - mean) ** 2 for x in values) / len(values)


def measure_effect(
    before: list[float], after: list[float], *, min_n: int = 30
) -> EffectMeasurement:
    """Compare two samples. `before` is the pre-merge baseline window, `after`
    is the post-merge runs. Both must be non-empty."""
    if not before or not after:
        raise ValueError("measure_effect needs non-empty before and after samples")

    before_n, after_n = len(before), len(after)
    before_mean = sum(before) / before_n
    after_mean = sum(after) / after_n
    delta = after_mean - before_mean

    # Pooled standard deviation across both samples. Population variance (not
    # n-1) — we're describing the samples we have, not inferring a population.
    pooled_var = (
        before_n * _population_variance(before, before_mean)
        + after_n * _population_variance(after, after_mean)
    ) / (before_n + after_n)
    pooled_std = pooled_var**0.5
    effect_size = delta / pooled_std if pooled_std > 0 else 0.0

    return EffectMeasurement(
        before_mean=before_mean,
        before_n=before_n,
        after_mean=after_mean,
        after_n=after_n,
        delta=delta,
        effect_size=effect_size,
        underpowered=after_n < min_n,
    )
