"""Sample meta-agent-proposed eval — a trivially-failing one.

trivial_eval_check must REJECT this too: it fails the known_good corpus, so
it would block healthy work. An always-fail eval is as useless as an
always-pass one.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief
from evals.deterministic import EvalResult


@dataclass
class AlwaysFails:
    name: str = "always_fails"
    blocking: bool = False

    def evaluate(self, output: ContentBrief) -> EvalResult:
        return EvalResult(name=self.name, passed=False, failures=["always fails"])
