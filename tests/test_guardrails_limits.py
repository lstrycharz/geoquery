"""RunBudget — cost cap + retry cap."""

from __future__ import annotations

import pytest

from guardrails import BudgetExceeded, RetryExceeded, RunBudget


def test_records_spend_and_blocks_when_projected_exceeds_cap():
    budget = RunBudget(max_cost_usd=1.0)
    budget.check_can_spend(0.4)
    budget.record_spend(0.4)
    budget.check_can_spend(0.5)
    budget.record_spend(0.5)
    with pytest.raises(BudgetExceeded):
        budget.check_can_spend(0.2)


def test_register_attempt_returns_attempt_count():
    budget = RunBudget(max_cost_usd=10.0)
    assert budget.register_attempt("define_icp") == 1
    assert budget.register_attempt("define_icp") == 2


def test_register_attempt_raises_after_max():
    budget = RunBudget(max_cost_usd=10.0)
    budget.register_attempt("x")
    budget.register_attempt("x")
    budget.register_attempt("x")
    with pytest.raises(RetryExceeded):
        budget.register_attempt("x")


def test_attempt_counters_are_per_skill():
    budget = RunBudget(max_cost_usd=10.0)
    for _ in range(3):
        budget.register_attempt("a")
    assert budget.register_attempt("b") == 1
