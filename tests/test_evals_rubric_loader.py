"""Rubric loader — reads evals/rubrics/<name>.md, substitutes {placeholders}.

Mirrors the existing skills.base.load_prompt pattern for skills/prompts/.
"""

from __future__ import annotations

import pytest

from evals.rubric_loader import RUBRICS_DIR, load_rubric


def test_load_rubric_returns_file_contents(tmp_path, monkeypatch):
    rubric = tmp_path / "demo.md"
    rubric.write_text("hello rubric\n", encoding="utf-8")
    monkeypatch.setattr("evals.rubric_loader.RUBRICS_DIR", tmp_path)
    assert load_rubric("demo") == "hello rubric\n"


def test_load_rubric_substitutes_placeholders(tmp_path, monkeypatch):
    rubric = tmp_path / "demo.md"
    rubric.write_text("Threshold: {threshold}%, mode: {mode}", encoding="utf-8")
    monkeypatch.setattr("evals.rubric_loader.RUBRICS_DIR", tmp_path)
    rendered = load_rubric("demo", threshold="70", mode="strict")
    assert rendered == "Threshold: 70%, mode: strict"


def test_load_rubric_raises_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.rubric_loader.RUBRICS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_rubric("nonexistent_rubric")


def test_load_rubric_raises_on_missing_placeholder(tmp_path, monkeypatch):
    rubric = tmp_path / "demo.md"
    rubric.write_text("Threshold: {threshold}%", encoding="utf-8")
    monkeypatch.setattr("evals.rubric_loader.RUBRICS_DIR", tmp_path)
    # Missing substitution: must raise, not silently leave the brace in the prompt.
    with pytest.raises(KeyError):
        load_rubric("demo")


def test_rubrics_dir_points_into_evals_package():
    # Sanity: the production-mode RUBRICS_DIR resolves under the evals package.
    assert RUBRICS_DIR.name == "rubrics"
    assert RUBRICS_DIR.parent.name == "evals"
