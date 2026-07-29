"""cowork_api event types — the contract between cowork_api and the UI.

Per spec §3 (event stream) and §4 (PyQt integration).

The UI never sees raw Anthropic SDK chunks or tool_use blocks. It receives
a typed event stream that cowork_api emits from inside its streaming +
tool-use loop. Eight event types in canonical emission order during a
normal turn:

    MessageStarted        # first event in a turn
    TextDelta             # incremental text (multiple, accumulating)
    ToolUseStarted        # marker; UI can show indicator
    ToolUseInput          # streamed JSON fragment (optional; UI may ignore)
    ToolUseCompleted      # tool dispatch finished; UI updates marker
    TextDelta             # response continuation after tool result (more)
    MessageCompleted      # last event in a turn
    Error                 # surfaced for any failure (replaces normal flow)

The CLI entry-point serializes these as NDJSON (one JSON object per line)
on stdout, with a `type` discriminator field. Same event semantics; different
transport.

PyQt integration (CoworkClientSignals) is at the bottom of this file and is
optional — only available if PyQt6 is installed. cowork_api remains importable
in CLI contexts without PyQt.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional, Union


# === Event dataclasses (eight types, per spec §3) ===

@dataclass
class MessageStarted:
    """First event in a turn. UI typically clears any in-progress display
    and prepares to receive streamed text.
    """
    message_id: str
    conversation_id: str
    timestamp: str  # ISO-8601 UTC

    type: str = field(default="MessageStarted", init=False)


@dataclass
class TextDelta:
    """Incremental text to append to display. Multiple per turn, accumulating.

    UI's display widget appends this text to whatever it's already shown for
    the current turn. No re-rendering of prior text required.
    """
    text: str

    type: str = field(default="TextDelta", init=False)


@dataclass
class ToolUseStarted:
    """Cowork-cousin is about to use a tool. UI may show a marker/spinner
    in the conversation display.
    """
    tool_name: str        # "Read" | "Grep" | "Glob" | "write_to_voice_inbox"
    tool_use_id: str      # Anthropic-issued ID; opaque to UI

    type: str = field(default="ToolUseStarted", init=False)


@dataclass
class ToolUseInput:
    """Streamed JSON fragment of tool input.

    Optional event — emit if UI wants to display partial input as it streams.
    UI can safely ignore this event class entirely; semantics are unchanged.
    """
    tool_use_id: str
    partial_input_json: str

    type: str = field(default="ToolUseInput", init=False)


@dataclass
class ToolUseCompleted:
    """Tool dispatch finished. UI updates marker to done/error state.

    `result_summary` is a short human-readable string suitable for inline
    display (e.g., "Read 4500 bytes from active_knowledge/current.md") —
    NOT the raw tool result, which goes back to the model internally.
    """
    tool_use_id: str
    success: bool
    result_summary: str

    type: str = field(default="ToolUseCompleted", init=False)


@dataclass
class MessageCompleted:
    """Last event in a turn. UI typically marks the turn as done.

    `full_text` is the complete assembled response text (concatenation of all
    TextDelta events from the turn), provided as a convenience so UI doesn't
    have to track its own buffer if it doesn't want to.

    `stop_reason` is Anthropic-API stop reason: end_turn / tool_use /
    max_tokens / stop_sequence. UI can use this for state-machine logic.
    """
    message_id: str
    full_text: str
    stop_reason: str

    type: str = field(default="MessageCompleted", init=False)


@dataclass
class Error:
    """Surfaced when something goes wrong during streaming or tool dispatch.

    UI displays appropriately based on the recoverable flag. Non-recoverable
    errors (config error, auth error, max-tool-use-rounds exceeded) typically
    warrant a non-blocking status-bar message (per spec §11.5 / voice-cousin's
    substrate-eye call) and disable further send-message attempts until
    resolved. Recoverable errors (rate limit, transient network) typically
    warrant a retry affordance.
    """
    exception_type: str   # str(type(exception).__name__)
    message: str          # str(exception)
    recoverable: bool
    context: str          # human-readable context: "during streaming",
                          # "during tool dispatch", "during API call setup", etc.

    type: str = field(default="Error", init=False)


# === Union type for type hints ===

ConversationEvent = Union[
    MessageStarted,
    TextDelta,
    ToolUseStarted,
    ToolUseInput,
    ToolUseCompleted,
    MessageCompleted,
    Error,
]


# === NDJSON serialization for the CLI entry-point (per spec §3) ===

# Map type-discriminator strings to dataclass constructors for deserialization.
_EVENT_TYPE_MAP = {
    "MessageStarted": MessageStarted,
    "TextDelta": TextDelta,
    "ToolUseStarted": ToolUseStarted,
    "ToolUseInput": ToolUseInput,
    "ToolUseCompleted": ToolUseCompleted,
    "MessageCompleted": MessageCompleted,
    "Error": Error,
}


def event_to_jsonl(event: ConversationEvent) -> str:
    """Serialize an event to a single NDJSON line (no trailing newline).

    The output is a JSON object with a `type` discriminator field plus all
    dataclass fields. Used by the CLI entry-point to emit events to stdout.
    Caller is responsible for adding the trailing "\\n".
    """
    d = asdict(event)
    # asdict already includes the `type` field since it's a dataclass field.
    return json.dumps(d, ensure_ascii=False)


def event_from_jsonl(line: str) -> ConversationEvent:
    """Parse a single NDJSON line back into the appropriate event dataclass.

    Used by subprocess consumers of the CLI entry-point's stdout stream.
    The `type` discriminator field selects the dataclass constructor.

    Raises:
        ValueError: If the line is not valid JSON, missing `type` field,
            or has an unknown type discriminator.
    """
    try:
        d = json.loads(line)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON line: {e}") from e

    type_name = d.get("type")
    if type_name is None:
        raise ValueError("Event JSON missing 'type' discriminator field")

    constructor = _EVENT_TYPE_MAP.get(type_name)
    if constructor is None:
        raise ValueError(f"Unknown event type: {type_name!r}")

    # Strip the `type` field before passing to the dataclass constructor
    # (it's a non-init field on each dataclass).
    payload = {k: v for k, v in d.items() if k != "type"}
    return constructor(**payload)


def make_iso8601_utc_now() -> str:
    """Helper for MessageStarted timestamp construction.

    Returns ISO-8601 UTC timestamp with second precision (no microseconds).
    Example: "2026-05-14T10:55:00+00:00"
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# === PyQt integration (optional — only if PyQt6 is installed) ===
#
# Per spec §4: UI subscribes to these signals; cowork_api emits via
# emit_event_to_signals() which translates events to signal emissions.
# This bridge layer keeps the event-emission API substrate-independent
# while providing clean PyQt slot/signal integration when available.

try:
    # voice-bridge uses PySide6 (the Qt Company's official Python bindings),
    # not PyQt6 (Riverbank's alternative). Match that convention.
    from PySide6.QtCore import QObject, Signal as pyqtSignal

    class CoworkClientSignals(QObject):
        """Qt-compatible event surface for cowork_api.

        Connect slots from the UI to these signals. Each signal corresponds
        to one of the eight event types in events.py. Signal payloads are
        the dataclass field values (not the event objects themselves) so
        slot connections are type-explicit.

        Usage:
            signals = CoworkClientSignals()
            signals.text_delta.connect(self.append_to_display)
            signals.tool_use_started.connect(self.show_tool_marker)
            # ... etc.

            # Then create CoworkClient and route events through emit_event_to_signals:
            client = CoworkClient(...)
            await client.send_message(
                user_text,
                on_event=lambda e: emit_event_to_signals(signals, e),
            )
        """
        message_started = pyqtSignal(str, str, str)
        # message_id, conversation_id, timestamp

        text_delta = pyqtSignal(str)
        # text

        tool_use_started = pyqtSignal(str, str)
        # tool_name, tool_use_id

        tool_use_input = pyqtSignal(str, str)
        # tool_use_id, partial_input_json

        tool_use_completed = pyqtSignal(str, bool, str)
        # tool_use_id, success, result_summary

        message_completed = pyqtSignal(str, str, str)
        # message_id, full_text, stop_reason

        error = pyqtSignal(str, str, bool, str)
        # exception_type, message, recoverable, context

    def emit_event_to_signals(
        signals: "CoworkClientSignals",
        event: ConversationEvent,
    ) -> None:
        """Translate a ConversationEvent into the corresponding signal emission.

        Pass this as the on_event callback (or a lambda wrapping it) to
        CoworkClient.send_message. All signal emissions are thread-safe
        per Qt's automatic queued-connection-across-threads semantics —
        critical for asyncio + QThread integration (per voice-cousin
        substrate-eye answer #11.4).
        """
        if isinstance(event, MessageStarted):
            signals.message_started.emit(
                event.message_id,
                event.conversation_id,
                event.timestamp,
            )
        elif isinstance(event, TextDelta):
            signals.text_delta.emit(event.text)
        elif isinstance(event, ToolUseStarted):
            signals.tool_use_started.emit(event.tool_name, event.tool_use_id)
        elif isinstance(event, ToolUseInput):
            signals.tool_use_input.emit(
                event.tool_use_id,
                event.partial_input_json,
            )
        elif isinstance(event, ToolUseCompleted):
            signals.tool_use_completed.emit(
                event.tool_use_id,
                event.success,
                event.result_summary,
            )
        elif isinstance(event, MessageCompleted):
            signals.message_completed.emit(
                event.message_id,
                event.full_text,
                event.stop_reason,
            )
        elif isinstance(event, Error):
            signals.error.emit(
                event.exception_type,
                event.message,
                event.recoverable,
                event.context,
            )
        else:
            raise ValueError(f"Unknown event type: {type(event).__name__}")

except ImportError:
    # PyQt6 not available — CoworkClientSignals and emit_event_to_signals
    # simply not exported. The non-PyQt parts of events.py (dataclasses,
    # serialization) remain available.
    pass
