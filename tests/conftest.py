"""Test fixtures: a fake Anthropic client backed by JSON cassettes.

A cassette is a JSON file at tests/fixtures/cassettes/<skill>.json with a
preset tool_use response. The fake client returns that response for any
messages.create call routed to the matching tool name. Tests stay free,
fast, and deterministic.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Add project root to path so test modules can import top-level packages.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure env-required settings load with safe defaults during tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

CASSETTES_DIR = Path(__file__).parent / "fixtures" / "cassettes"


@dataclass
class FakeToolUseBlock:
    type: str
    name: str
    input: dict[str, Any]
    id: str = "toolu_fake"


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FakeMessageResponse:
    content: list[FakeToolUseBlock]
    usage: FakeUsage
    stop_reason: str = "tool_use"


@dataclass
class FakeMessagesAPI:
    parent: FakeAnthropicClient

    def create(self, **kwargs: Any) -> FakeMessageResponse:
        tool_choice = kwargs.get("tool_choice") or {}
        tool_name: str | None = (
            tool_choice.get("name") if isinstance(tool_choice, dict) else None
        )
        # When tool_choice is not forced (e.g. tools/web_search lets the model pick
        # between a server tool and an emit_* client tool), find the emit_* tool in
        # the tools list and use it as the cassette key.
        if not tool_name:
            for tool in kwargs.get("tools") or []:
                name = tool.get("name") if isinstance(tool, dict) else None
                if isinstance(name, str) and name.startswith("emit_"):
                    tool_name = name
                    break
        if not tool_name or not tool_name.startswith("emit_"):
            raise AssertionError(
                "FakeAnthropic could not locate an emit_* tool to use as cassette key"
            )
        skill_name = tool_name[len("emit_") :]
        cassette = self.parent.cassettes.get(skill_name)
        if cassette is None:
            raise AssertionError(
                f"no cassette loaded for skill {skill_name!r}; "
                f"register one via load_cassette() in the test."
            )
        return FakeMessageResponse(
            content=[FakeToolUseBlock(type="tool_use", name=tool_name, input=cassette["input"])],
            usage=FakeUsage(
                input_tokens=cassette.get("input_tokens", 1000),
                output_tokens=cassette.get("output_tokens", 500),
            ),
        )


class FakeAnthropicClient:
    def __init__(self) -> None:
        self.cassettes: dict[str, dict[str, Any]] = {}
        self.messages = FakeMessagesAPI(parent=self)

    def load_cassette(self, skill_name: str) -> None:
        path = CASSETTES_DIR / f"{skill_name}.json"
        self.cassettes[skill_name] = json.loads(path.read_text(encoding="utf-8"))

    def set_cassette(self, skill_name: str, payload: dict[str, Any]) -> None:
        self.cassettes[skill_name] = payload


@pytest.fixture
def fake_client() -> FakeAnthropicClient:
    return FakeAnthropicClient()


@pytest.fixture
def tmp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated Settings that point at a fresh tmp dir + reset the global cache."""
    from config import Settings, reset_settings_for_tests  # local import to avoid early load

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("MAX_COST_USD", "3.0")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "briefs"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    reset_settings_for_tests()
    settings = Settings()
    settings.ensure_dirs()
    yield settings
    reset_settings_for_tests()
