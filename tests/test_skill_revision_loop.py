"""Revision loop — consensus-gated judges, full-critique header, escalation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from contracts import ICPSegmentList
from evals.deterministic import EvalResult
from guardrails import RunBudget
from skills.base import SkillEscalation
from skills.define_icp import DefineIcp, DefineIcpInputs


@dataclass
class StubEvaluator:
    """Evaluator returning a pre-programmed list of pass/fail verdicts.

    `blocking=True` (the default) makes it a deterministic eval; `blocking=False`
    makes it a judge, subject to consensus gating.
    """

    name: str = "stub"
    verdicts: list[bool] = field(default_factory=list)
    blocking: bool = True

    def evaluate(self, output: Any) -> EvalResult:
        if not self.verdicts:
            return EvalResult(name=self.name, passed=True)
        passed = self.verdicts.pop(0)
        return EvalResult(
            name=self.name,
            passed=passed,
            failures=[] if passed else [f"{self.name} failure"],
        )


def _skill(fake_client, monkeypatch, evaluators):
    fake_client.load_cassette("define_icp")
    skill = DefineIcp(client=fake_client, budget=RunBudget(max_cost_usd=3.0))
    monkeypatch.setattr(skill, "make_evaluators", lambda _inputs: evaluators)
    return skill


def test_deterministic_failure_gates_a_revision(fake_client, monkeypatch):
    stub = StubEvaluator(verdicts=[False, True])
    skill = _skill(fake_client, monkeypatch, [stub])

    result = skill.run(DefineIcpInputs(company="X", market="Y"))

    assert isinstance(result.output, ICPSegmentList)
    assert result.attempt == 2
    assert result.eval_passed is True


def test_first_attempt_pass_skips_revision(fake_client, monkeypatch):
    skill = _skill(fake_client, monkeypatch, [StubEvaluator(verdicts=[True])])
    result = skill.run(DefineIcpInputs(company="X", market="Y"))
    assert result.attempt == 1
    assert result.eval_passed is True


def test_single_judge_failure_stays_advisory(fake_client, monkeypatch):
    """One of two judges failing is below the consensus threshold — no revision,
    the grumble is logged as advisory."""
    judge_a = StubEvaluator(name="judge_a", blocking=False, verdicts=[False])
    judge_b = StubEvaluator(name="judge_b", blocking=False, verdicts=[True])
    skill = _skill(fake_client, monkeypatch, [judge_a, judge_b])

    result = skill.run(DefineIcpInputs(company="X", market="Y"))

    assert result.attempt == 1
    assert result.eval_passed is True
    assert result.eval_failures == ["[ADVISORY] [judge_a] judge_a failure"]


def test_majority_judge_failure_gates_a_revision(fake_client, monkeypatch):
    """Both judges failing exceeds the consensus threshold — a revision fires."""
    judge_a = StubEvaluator(name="judge_a", blocking=False, verdicts=[False, True])
    judge_b = StubEvaluator(name="judge_b", blocking=False, verdicts=[False, True])
    skill = _skill(fake_client, monkeypatch, [judge_a, judge_b])

    result = skill.run(DefineIcpInputs(company="X", market="Y"))

    assert result.attempt == 2
    assert result.eval_passed is True


def test_revision_header_carries_every_failing_critique(fake_client, monkeypatch):
    """Full-critique header: when a revision fires, even a non-gating judge's
    failure goes into the header alongside the deterministic one."""
    captured_systems: list[Any] = []
    original_create = fake_client.messages.create

    def _recording_create(**kwargs):
        captured_systems.append(kwargs.get("system"))
        return original_create(**kwargs)

    monkeypatch.setattr(fake_client.messages, "create", _recording_create)

    det = StubEvaluator(name="det", blocking=True, verdicts=[False, True])
    judge_a = StubEvaluator(name="judge_a", blocking=False, verdicts=[False, True])
    judge_b = StubEvaluator(name="judge_b", blocking=False, verdicts=[True, True])
    skill = _skill(fake_client, monkeypatch, [det, judge_a, judge_b])

    skill.run(DefineIcpInputs(company="X", market="Y"))

    # Attempt 2's system prompt leads with the revision header block.
    revision_header = captured_systems[1][0]["text"]
    assert "[det]" in revision_header
    assert "[judge_a]" in revision_header  # non-gating judge, still in the header


def test_retry_exhaustion_raises_skill_escalation_with_attempt_history(fake_client, monkeypatch):
    stub = StubEvaluator(verdicts=[False, False, False, False])
    skill = _skill(fake_client, monkeypatch, [stub])

    with pytest.raises(SkillEscalation) as exc:
        skill.run(DefineIcpInputs(company="X", market="Y"))

    assert exc.value.skill_name == "define_icp"
    assert len(exc.value.attempt_failures) == 3  # three failed attempts captured
    assert exc.value.final_output_json is not None
