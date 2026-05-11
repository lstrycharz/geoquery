"""RunBudget — single source of truth for cost cap + retry cap during a run.

Threaded through the orchestrator and every Skill. Skills check budget before
each external call; the budget raises if the projected next cost would exceed
the cap, so partial spend is recorded and the run aborts cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_RETRIES_PER_SKILL = 3


class BudgetExceeded(RuntimeError):
    """Raised when projected_next + total would exceed MAX_COST_USD."""


class RetryExceeded(RuntimeError):
    """Raised when a skill exhausts MAX_RETRIES_PER_SKILL attempts."""


@dataclass
class RunBudget:
    max_cost_usd: float
    spent_usd: float = 0.0
    attempts: dict[str, int] = field(default_factory=dict)

    def check_can_spend(self, projected_usd: float) -> None:
        if self.spent_usd + projected_usd > self.max_cost_usd:
            raise BudgetExceeded(
                f"cost cap ${self.max_cost_usd:.2f} would be exceeded "
                f"(spent ${self.spent_usd:.4f} + projected ${projected_usd:.4f})"
            )

    def record_spend(self, actual_usd: float) -> None:
        self.spent_usd += actual_usd

    def register_attempt(self, skill_name: str) -> int:
        """Increment attempt counter for a skill. Returns the new attempt number (1-indexed).
        Raises RetryExceeded after MAX_RETRIES_PER_SKILL."""
        current = self.attempts.get(skill_name, 0) + 1
        if current > MAX_RETRIES_PER_SKILL:
            raise RetryExceeded(
                f"skill {skill_name!r} exhausted {MAX_RETRIES_PER_SKILL} attempts"
            )
        self.attempts[skill_name] = current
        return current
