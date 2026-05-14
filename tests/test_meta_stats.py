"""meta/stats.py — effect-size measurement (no scipy, no t-test theater)."""

from __future__ import annotations

import pytest

from meta.stats import EffectMeasurement, measure_effect


def test_measure_effect_reports_before_after_means_and_delta():
    result = measure_effect([0.4, 0.5, 0.6], [0.6, 0.7, 0.8])
    assert isinstance(result, EffectMeasurement)
    assert result.before_mean == pytest.approx(0.5)
    assert result.after_mean == pytest.approx(0.7)
    assert result.delta == pytest.approx(0.2)
    assert result.before_n == 3
    assert result.after_n == 3


def test_measure_effect_positive_delta_gives_positive_effect_size():
    result = measure_effect([0.3, 0.4, 0.5], [0.6, 0.7, 0.8])
    assert result.effect_size > 0


def test_measure_effect_negative_delta_gives_negative_effect_size():
    result = measure_effect([0.7, 0.8, 0.9], [0.3, 0.4, 0.5])
    assert result.delta < 0
    assert result.effect_size < 0


def test_measure_effect_flags_underpowered_below_min_n():
    small = measure_effect([0.5] * 5, [0.6] * 10, min_n=30)
    assert small.underpowered is True
    big = measure_effect([0.5] * 5, [0.6] * 35, min_n=30)
    assert big.underpowered is False


def test_measure_effect_zero_variance_does_not_divide_by_zero():
    result = measure_effect([0.5] * 10, [0.5] * 10)
    assert result.delta == 0.0
    assert result.effect_size == 0.0


def test_measure_effect_rejects_empty_samples():
    with pytest.raises(ValueError):
        measure_effect([], [0.5])
    with pytest.raises(ValueError):
        measure_effect([0.5], [])
