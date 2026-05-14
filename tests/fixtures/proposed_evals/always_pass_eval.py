"""Sample meta-agent-proposed eval — a trivially-passing one (reward hack).

trivial_eval_check must REJECT this: it passes the known_bad corpus too, so
it adds no signal — a meta-agent could ship it just to inflate pass rates.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief
from evals.deterministic import EvalResult


@dataclass
class AlwaysPasses:
    name: str = "always_passes"
    blocking: bool = False

    def evaluate(self, output: ContentBrief) -> EvalResult:
        return EvalResult(name=self.name, passed=True, failures=[])
