"""Production-side eval ops: sample stream (chunk 7) + drift detection (chunk 8).

Two responsibilities live here because they share the same domain — "what's
happening to runs after they leave the lab?" — and the same data source
(`memory.episodic.EpisodicMemory`). Splitting them into two files would have
been shallower, not cleaner.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory import EpisodicMemory


def maybe_sample_for_review(
    memory: EpisodicMemory,
    run_id: str,
    *,
    rate: float = 0.10,
    rng: random.Random | Callable[[], float] | None = None,
) -> int | None:
    """Roll a die. With probability `rate`, flag the given run for human review
    and return the new review id. Otherwise return None.

    `rng` accepts a `random.Random` instance or a zero-arg callable returning a
    float in [0, 1). Tests pass `lambda: 0.0` (always sample) or
    `lambda: 0.99` (never) to drive deterministic behavior.
    """
    if rate <= 0:
        return None
    if rate >= 1:
        draw = 0.0
    else:
        if rng is None:
            draw = random.random()
        elif isinstance(rng, random.Random):
            draw = rng.random()
        else:
            draw = float(rng())
    if draw >= rate:
        return None
    return memory.start_human_review(run_id=run_id)
