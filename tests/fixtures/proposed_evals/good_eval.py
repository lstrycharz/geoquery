"""Sample meta-agent-proposed eval — a *real* one that discriminates.

Used by tests/test_meta_evals.py to exercise trivial_eval_check's happy path:
it passes every known_good fixture and fails every known_bad fixture.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ContentBrief
from evals.deterministic import EvalResult


@dataclass
class BriefHasSubstantiveShape:
    name: str = "brief_has_substantive_shape"
    blocking: bool = False

    def evaluate(self, output: ContentBrief) -> EvalResult:
        fails: list[str] = []
        if not output.angle.strip():
            fails.append("angle is blank")
        if len(output.structure) < 3:
            fails.append("fewer than 3 structure sections")
        if len(output.key_points) < 3:
            fails.append("fewer than 3 key_points")
        return EvalResult(name=self.name, passed=not fails, failures=fails)
