"""predict_outcome — the Opus "30-day outcome judge" (v3 Mechanism 3).

Given a finished ContentBrief, predicts whether an article written to it would
have reached the top 10 within 30 days. This is a *simulated* signal — there is
no real ranking data behind it (see SELF_IMPROVEMENT.md). It runs as a batch
command (`geoquery predict-outcomes`) over a sampled subset, never on the
per-run hot path: Opus is ~5x Sonnet.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief, OutcomePrediction
from skills.base import Skill


@dataclass(frozen=True)
class PredictOutcomeInputs:
    brief: ContentBrief
    market: str


class PredictOutcome(Skill[PredictOutcomeInputs, OutcomePrediction]):
    name = "predict_outcome"
    model = "claude-opus-4-7"  # the spec's "stronger model" for outcome judging
    output_type = OutcomePrediction
    max_output_tokens = 1024  # a compact prediction + short reasoning

    def build_user_message(self, inputs: PredictOutcomeInputs) -> str:
        return (
            f"Market: {inputs.market}\n\n"
            f"Content brief:\n```json\n{inputs.brief.model_dump_json(indent=2)}\n```\n\n"
            "Predict the 30-day search outcome per the system instructions."
        )
