"""Deterministic cassette replay for the regression suite.

Cassettes are keyed by `sha256(system_prompt + user_message + model)` so any
prompt change forces a miss. On miss we raise RegressionStaleCassetteError —
the gate must never silently replay an old response for a new prompt. The
developer's options are then explicit: re-record the cassette (intentional
prompt change) or fix the prompt regression (unintentional).

Two clients live here:

- `RegressionCassetteClient` — replays from a recorded cassette. Drop-in for
  the slice of `anthropic.Anthropic` that `Skill.run` and the judges use:
  `client.messages.create(**kwargs)` and `client.messages.stream(**kwargs)`.

- `RecordingCassetteClient` — wraps a real (or fake) Anthropic client and
  captures every (key → response) pair as it streams through. Used by the
  bootstrap / re-record workflow; `geoquery regression record <slug>` (chunk 9)
  will call this under the hood.

Both clients share a tiny `_FakeResponse` shape that mirrors what the SDK
returns from `messages.create()` — content list with `tool_use` blocks +
`usage` with token counts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REGRESSION_DATASET_DIR = Path(__file__).parent.parent / "regression_dataset"


class RegressionStaleCassetteError(RuntimeError):
    """Cassette miss: prompt likely changed since recording.

    Re-record if the change was intentional; fix the prompt if it wasn't.
    The exception message includes the model + truncated system/user previews
    so a developer can see *which* call missed and start investigating.
    """


# ---------------------------------------------------------------------------
# Keying
# ---------------------------------------------------------------------------


def _normalize_system(system: Any) -> str:
    """Anthropic SDK accepts `system` as a string or as a list of content blocks.
    We canonicalize to a string of just the `text` fields, joined by blank
    lines. Cache_control and other SDK metadata are ignored — they don't
    affect what the model sees, so they must not affect the cassette key.
    """
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "\n\n".join(
            block.get("text", "")
            for block in system
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _normalize_user_message(messages: list[dict[str, Any]]) -> str:
    """The first user message's content as a string. The agent only ever sends
    a single user message per call, so this is sufficient."""
    if not messages:
        return ""
    content = messages[0].get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def cassette_key(system: Any, messages: list[dict[str, Any]], model: str) -> str:
    payload = (
        f"{model}\n---SYS---\n{_normalize_system(system)}"
        f"\n---USR---\n{_normalize_user_message(messages)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Response shape (mirrors the bits of the SDK message we read)
# ---------------------------------------------------------------------------


@dataclass
class CassetteEntry:
    """Serialized form of a recorded response.

    Stores the tool_use block (name + input) we extract from the SDK response,
    plus usage counts. We don't store text blocks — every call in this codebase
    forces tool_use via tool_choice.
    """

    input_tokens: int
    output_tokens: int
    stop_reason: str
    tool_use: dict[str, Any]


@dataclass
class _ToolUseBlock:
    name: str
    input: dict[str, Any]
    type: str = "tool_use"
    id: str = "toolu_recorded"


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _MessageResponse:
    content: list[_ToolUseBlock]
    usage: _Usage
    stop_reason: str = "tool_use"


def _entry_to_response(entry: CassetteEntry) -> _MessageResponse:
    return _MessageResponse(
        content=[_ToolUseBlock(name=entry.tool_use["name"], input=entry.tool_use["input"])],
        usage=_Usage(input_tokens=entry.input_tokens, output_tokens=entry.output_tokens),
        stop_reason=entry.stop_reason,
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class _StreamContext:
    """SDK-shaped `with client.messages.stream(...) as stream` context."""

    def __init__(self, response: _MessageResponse) -> None:
        self._response = response

    def __enter__(self) -> _StreamContext:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def __iter__(self):
        return iter([])  # no per-token deltas in replay

    def get_final_message(self) -> _MessageResponse:
        return self._response


@dataclass
class _ReplayMessagesAPI:
    parent: RegressionCassetteClient

    def create(self, **kwargs: Any) -> _MessageResponse:
        key = cassette_key(
            kwargs.get("system"), kwargs.get("messages", []), kwargs.get("model", "")
        )
        entry = self.parent.cassette.get(key)
        if entry is None:
            raise RegressionStaleCassetteError(
                f"no cassette entry for key {key[:16]}…: "
                f"model={kwargs.get('model')!r}, "
                f"sys[:80]={_normalize_system(kwargs.get('system'))[:80]!r}, "
                f"usr[:80]={_normalize_user_message(kwargs.get('messages', []))[:80]!r}. "
                "If the prompt change was intentional, re-record this cassette."
            )
        return _entry_to_response(entry)

    def stream(self, **kwargs: Any) -> _StreamContext:
        return _StreamContext(self.create(**kwargs))


@dataclass
class RegressionCassetteClient:
    """Anthropic-shaped client that resolves every messages.create / stream call
    against a pre-recorded cassette."""

    cassette: dict[str, CassetteEntry]

    @classmethod
    def load(cls, path: Path) -> RegressionCassetteClient:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(cassette={k: CassetteEntry(**v) for k, v in raw.items()})

    @property
    def messages(self) -> _ReplayMessagesAPI:
        return _ReplayMessagesAPI(parent=self)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


@dataclass
class _RecordingMessagesAPI:
    parent: RecordingCassetteClient

    def create(self, **kwargs: Any) -> Any:
        response = self.parent.inner.messages.create(**kwargs)
        key = cassette_key(
            kwargs.get("system"), kwargs.get("messages", []), kwargs.get("model", "")
        )
        self.parent.cassette[key] = _response_to_entry(response)
        return response

    def stream(self, **kwargs: Any) -> Any:
        # Recording streamers is rarely needed (only one skill uses stream).
        # Fall through to the inner client; the response is captured via the
        # post-stream final-message hook.
        inner_ctx = self.parent.inner.messages.stream(**kwargs)
        key = cassette_key(
            kwargs.get("system"), kwargs.get("messages", []), kwargs.get("model", "")
        )
        return _RecordingStreamContext(inner_ctx=inner_ctx, recorder=self.parent, key=key)


class _RecordingStreamContext:
    def __init__(self, inner_ctx: Any, recorder: RecordingCassetteClient, key: str) -> None:
        self._inner_ctx = inner_ctx
        self._recorder = recorder
        self._key = key

    def __enter__(self) -> _RecordingStreamContext:
        self._inner = self._inner_ctx.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        return self._inner_ctx.__exit__(*args)

    def __iter__(self):
        return iter(self._inner)

    def get_final_message(self) -> Any:
        final = self._inner.get_final_message()
        self._recorder.cassette[self._key] = _response_to_entry(final)
        return final


@dataclass
class RecordingCassetteClient:
    """Wraps a real or fake Anthropic client and captures every (key → response)
    pair as it streams through. Use `dump(path)` to persist the cassette."""

    inner: Any
    cassette: dict[str, CassetteEntry] = field(default_factory=dict)

    @property
    def messages(self) -> _RecordingMessagesAPI:
        return _RecordingMessagesAPI(parent=self)

    def dump(self, path: Path) -> None:
        dump_cassette(path, self.cassette)


def _response_to_entry(response: Any) -> CassetteEntry:
    """Extract a CassetteEntry from any SDK-shaped or fake-shaped response."""
    tool_block = next(
        (b for b in response.content if getattr(b, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None:
        raise RuntimeError(
            "response did not contain a tool_use block; "
            "regression recording requires forced tool_use"
        )
    return CassetteEntry(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        stop_reason=getattr(response, "stop_reason", "tool_use"),
        tool_use={"name": tool_block.name, "input": tool_block.input},
    )


def _notes_for_source(source: str) -> str:
    if source == "bootstrap-fake-client":
        return (
            "Bootstrapped against FakeAnthropicClient — same fake response per skill. "
            "Replace with `pytest -m regression_record_live` (real Anthropic, ~$0.50/case) "
            "to enable real-prompt regression for this slug."
        )
    if source == "live-anthropic":
        return (
            "Recorded against the live Anthropic API. Cassette captures real model "
            "responses for the prompts present at recording time. Any prompt change "
            "will force a hash miss; re-record with `pytest -m regression_record_live`."
        )
    return f"recorded via source={source!r}"


def record_case_to_disk(
    *,
    slug: str,
    company: str,
    market: str,
    tier: str,
    source: str,
    client: Any,
    settings: Any,
    embedder: Any,
    fetch_page: Any,
) -> None:
    """Shared write-the-three-files step used by both bootstrap and live
    recording. Wraps the given `client` in RecordingCassetteClient, runs the
    full agent pipeline once, then persists:

      regression_dataset/<slug>/{input,cassette,expected}.json

    The `source` field on expected.json marks whether the cassette is a fake
    placeholder or a real-LLM recording.
    """
    from agent import run_brief
    from memory import EpisodicMemory

    recorder = RecordingCassetteClient(inner=client)
    outcome = run_brief(
        company=company,
        market=market,
        settings=settings,
        client=recorder,
        embedder=embedder,
        fetch_page=fetch_page,
    )
    if outcome.status != "completed":
        raise RuntimeError(
            f"[{slug}] recording failed: status={outcome.status}, error={outcome.error}"
        )

    mem = EpisodicMemory(db_path=settings.data_dir / "episodic.db")
    invocations = mem.get_invocations(outcome.run_id)
    eval_profile = {i["skill_name"]: bool(i["eval_passed"]) for i in invocations}

    case_dir = REGRESSION_DATASET_DIR / slug
    case_dir.mkdir(parents=True, exist_ok=True)
    recorder.dump(case_dir / "cassette.json")
    (case_dir / "input.json").write_text(
        json.dumps({"company": company, "market": market, "sitemap_url": None}, indent=2),
        encoding="utf-8",
    )
    (case_dir / "expected.json").write_text(
        json.dumps(
            {
                "tier": tier,
                "eval_profile": eval_profile,
                "status": outcome.status,
                "source": source,
                "notes": _notes_for_source(source),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def dump_cassette(path: Path, cassette: dict[str, CassetteEntry]) -> None:
    """Persist the cassette. The OUTER hash → entry mapping is sorted by hash
    key so PR diffs are stable. The INNER tool_use.input dict preserves the
    insertion order the LLM returned — sorting it would re-order nested dicts
    (e.g. SWOT) and cause Pydantic.model_dump_json to differ between record
    and replay, which silently breaks deterministic regression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {k: asdict(cassette[k]) for k in sorted(cassette)}
    path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
