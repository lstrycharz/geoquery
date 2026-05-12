"""Revision loop — skill re-runs when its evaluators fail; aborts after retry cap."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from contracts import ICPSegmentList
from evals.deterministic import EvalResult
from guardrails import RetryExceeded, RunBudget
from skills.define_icp import DefineIcp, DefineIcpInputs


@dataclass
class StubEvaluator:
    """Evaluator that returns a pre-programmed list of pass/fail verdicts."""

    name: str = "stub"
    verdicts: list[bool] = field(default_factory=list)

    def evaluate(self, output: Any) -> EvalResult:
        if not self.verdicts:
            return EvalResult(name=self.name, passed=True)
        passed = self.verdicts.pop(0)
        return EvalResult(
            name=self.name,
            passed=passed,
            failures=[] if passed else ["stub failure"],
        )


def test_revision_loop_succeeds_on_second_attempt(fake_client, monkeypatch):
    fake_client.load_cassette("define_icp")
    stub = StubEvaluator(verdicts=[False, True])

    skill = DefineIcp(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    monkeypatch.setattr(skill, "make_evaluators", lambda _inputs: [stub])

    result = skill.run(DefineIcpInputs(company="X", market="Y"))

    assert isinstance(result.output, ICPSegmentList)
    assert result.attempt == 2
    assert result.eval_passed is True


def test_revision_loop_aborts_after_three_attempts(fake_client, monkeypatch):
    fake_client.load_cassette("define_icp")
    stub = StubEvaluator(verdicts=[False, False, False, False])

    skill = DefineIcp(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    monkeypatch.setattr(skill, "make_evaluators", lambda _inputs: [stub])

    with pytest.raises(RetryExceeded):
        skill.run(DefineIcpInputs(company="X", market="Y"))


def test_first_attempt_pass_skips_revision(fake_client, monkeypatch):
    fake_client.load_cassette("define_icp")

    class _AlwaysPass:
        name = "always_pass"

        def evaluate(self, output: Any) -> EvalResult:
            return EvalResult(name=self.name, passed=True)

    skill = DefineIcp(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    monkeypatch.setattr(skill, "make_evaluators", lambda _inputs: [_AlwaysPass()])

    result = skill.run(DefineIcpInputs(company="X", market="Y"))
    assert result.attempt == 1
    assert result.eval_passed is True
