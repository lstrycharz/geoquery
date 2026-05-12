"""evals/regression.py — deterministic cassette replay for the agent.

Cassettes are keyed by sha256(system_prompt + user_message + model) so any
prompt change invalidates the key. On miss, we raise RegressionStaleCassetteError
loudly — the gate must never silently replay an old response for a new prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.regression import (
    CassetteEntry,
    RecordingCassetteClient,
    RegressionCassetteClient,
    RegressionStaleCassetteError,
    cassette_key,
    dump_cassette,
)

# ---------------------------------------------------------------------------
# cassette_key
# ---------------------------------------------------------------------------


def test_cassette_key_is_stable_for_same_inputs():
    k1 = cassette_key("sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6")
    k2 = cassette_key("sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6")
    assert k1 == k2


def test_cassette_key_changes_when_system_changes():
    k1 = cassette_key("sys-a", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6")
    k2 = cassette_key("sys-b", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6")
    assert k1 != k2


def test_cassette_key_changes_when_user_message_changes():
    k1 = cassette_key("sys", [{"role": "user", "content": "alpha"}], "claude-sonnet-4-6")
    k2 = cassette_key("sys", [{"role": "user", "content": "beta"}], "claude-sonnet-4-6")
    assert k1 != k2


def test_cassette_key_changes_when_model_changes():
    k1 = cassette_key("sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6")
    k2 = cassette_key("sys", [{"role": "user", "content": "hi"}], "claude-haiku-4-5")
    assert k1 != k2


def test_cassette_key_handles_multi_block_system():
    """Skills construct system as a list of text-blocks with cache_control. The
    keying must extract only `text` fields — cache_control is SDK metadata and
    must not affect the hash."""
    list_system = [
        {"type": "text", "text": "block-a"},
        {"type": "text", "text": "block-b", "cache_control": {"type": "ephemeral"}},
    ]
    k_list = cassette_key(list_system, [{"role": "user", "content": "hi"}], "m")
    k_str = cassette_key("block-a\n\nblock-b", [{"role": "user", "content": "hi"}], "m")
    assert k_list == k_str


def test_cassette_key_ignores_cache_control_field():
    a = [{"type": "text", "text": "x", "cache_control": {"type": "ephemeral"}}]
    b = [{"type": "text", "text": "x"}]
    assert cassette_key(a, [{"role": "user", "content": "hi"}], "m") == cassette_key(
        b, [{"role": "user", "content": "hi"}], "m"
    )


# ---------------------------------------------------------------------------
# RegressionCassetteClient (replay)
# ---------------------------------------------------------------------------


def _make_entry(name: str = "emit_demo", payload: dict[str, Any] | None = None) -> CassetteEntry:
    return CassetteEntry(
        input_tokens=1000,
        output_tokens=200,
        stop_reason="tool_use",
        tool_use={"name": name, "input": payload or {"hello": "world"}},
    )


def test_replay_returns_recorded_response():
    sys, msgs, model = "sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6"
    key = cassette_key(sys, msgs, model)
    client = RegressionCassetteClient(cassette={key: _make_entry()})

    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=sys,
        messages=msgs,
        tools=[{"name": "emit_demo", "description": "x", "input_schema": {}}],
        tool_choice={"type": "tool", "name": "emit_demo"},
    )
    assert response.stop_reason == "tool_use"
    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 200
    assert response.content[0].type == "tool_use"
    assert response.content[0].name == "emit_demo"
    assert response.content[0].input == {"hello": "world"}


def test_replay_raises_stale_cassette_on_miss():
    client = RegressionCassetteClient(cassette={})
    with pytest.raises(RegressionStaleCassetteError) as exc_info:
        client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "emit_x", "description": "x", "input_schema": {}}],
            tool_choice={"type": "tool", "name": "emit_x"},
        )
    # The error message must include enough context to diagnose the miss.
    msg = str(exc_info.value)
    assert "claude-sonnet-4-6" in msg
    assert "re-record" in msg.lower()


def test_replay_stream_returns_same_response_via_context():
    sys, msgs, model = "sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6"
    key = cassette_key(sys, msgs, model)
    client = RegressionCassetteClient(cassette={key: _make_entry()})
    with client.messages.stream(
        model=model,
        max_tokens=512,
        system=sys,
        messages=msgs,
        tools=[{"name": "emit_demo", "description": "x", "input_schema": {}}],
        tool_choice={"type": "tool", "name": "emit_demo"},
    ) as stream:
        list(stream)  # consume no events
        final = stream.get_final_message()
    assert final.content[0].input == {"hello": "world"}


# ---------------------------------------------------------------------------
# Load / dump roundtrip
# ---------------------------------------------------------------------------


def test_load_and_dump_roundtrip(tmp_path: Path):
    sys, msgs, model = "sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6"
    key = cassette_key(sys, msgs, model)
    path = tmp_path / "cassette.json"
    dump_cassette(path, {key: _make_entry()})
    loaded = RegressionCassetteClient.load(path)
    assert key in loaded.cassette
    assert loaded.cassette[key].tool_use["name"] == "emit_demo"


# ---------------------------------------------------------------------------
# RecordingCassetteClient
# ---------------------------------------------------------------------------


class _StubInnerClient:
    """Mimics the slice of Anthropic.client.messages.create we need to wrap."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _StubMessagesAPI(parent=self)


class _StubMessagesAPI:
    def __init__(self, parent: _StubInnerClient) -> None:
        self.parent = parent

    def create(self, **kwargs: Any):
        self.parent.calls.append(kwargs)
        from tests.conftest import FakeMessageResponse, FakeToolUseBlock, FakeUsage

        tool_name = kwargs["tool_choice"]["name"]
        return FakeMessageResponse(
            content=[FakeToolUseBlock(type="tool_use", name=tool_name, input={"ok": True})],
            usage=FakeUsage(input_tokens=1500, output_tokens=300),
        )


def test_recording_wraps_inner_and_captures_call(tmp_path: Path):
    inner = _StubInnerClient()
    recorder = RecordingCassetteClient(inner=inner)
    sys, msgs, model = "sys", [{"role": "user", "content": "hi"}], "claude-sonnet-4-6"
    response = recorder.messages.create(
        model=model,
        max_tokens=512,
        system=sys,
        messages=msgs,
        tools=[{"name": "emit_demo", "description": "x", "input_schema": {}}],
        tool_choice={"type": "tool", "name": "emit_demo"},
    )
    # Response passes through unchanged.
    assert response.content[0].input == {"ok": True}
    # Inner client was called.
    assert len(inner.calls) == 1
    # Cassette captured the keyed entry.
    expected_key = cassette_key(sys, msgs, model)
    assert expected_key in recorder.cassette
    entry = recorder.cassette[expected_key]
    assert entry.tool_use == {"name": "emit_demo", "input": {"ok": True}}
    assert entry.input_tokens == 1500


def test_recording_dump_writes_json(tmp_path: Path):
    inner = _StubInnerClient()
    recorder = RecordingCassetteClient(inner=inner)
    recorder.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "emit_demo", "description": "x", "input_schema": {}}],
        tool_choice={"type": "tool", "name": "emit_demo"},
    )
    out = tmp_path / "out.json"
    recorder.dump(out)
    raw = json.loads(out.read_text())
    assert isinstance(raw, dict)
    assert len(raw) == 1
    # Round-trippable.
    loaded = RegressionCassetteClient.load(out)
    assert len(loaded.cassette) == 1
