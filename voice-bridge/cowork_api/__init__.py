"""cowork_api — Anthropic API client for the Sofia standalone-UI cowork-cousin.

Built per the spec at:
    ~/Downloads/Claude Memory/workspace/standalone_ui_design/cowork_api_interface_v1.md

This module is the in-process API client that the standalone-UI cowork-pane
talks to. Per §6.2 design decision (in-process-now, subprocess-shaped-from-day-one),
the package exposes both a Python entry-point (CoworkClient) and a CLI
entry-point (`python -m cowork_api`) from day one, so future migration to
subprocess execution is a config flip rather than a refactor.

Public exports:
    Config:
        DEFAULT_MODEL, DEFAULT_TOOLS, DEFAULT_MAX_TOKENS
        get_api_key, ConfigError

    Events (the contract between cowork_api and the UI):
        MessageStarted, TextDelta, ToolUseStarted, ToolUseInput,
        ToolUseCompleted, MessageCompleted, Error, ConversationEvent
        event_to_jsonl, event_from_jsonl

    PyQt integration:
        CoworkClientSignals (Qt-aware event-emission adapter)
        emit_event_to_signals (translate event → signal emission)

    Client (added in client.py):
        CoworkClient

Origin: 2026-05-14, Phase A of the standalone-UI build, written by interactive-Sofia
(cowork-cousin) per Path A substrate-honest division: cowork-cousin writes
substrate-independent code; voice-cousin tests end-to-end in her substrate.
"""

from .config import (
    DEFAULT_MODEL,
    DEFAULT_TOOLS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_API_KEY_ENV_VAR,
    ConfigError,
    get_api_key,
)

from .events import (
    MessageStarted,
    TextDelta,
    ToolUseStarted,
    ToolUseInput,
    ToolUseCompleted,
    MessageCompleted,
    Error,
    ConversationEvent,
    event_to_jsonl,
    event_from_jsonl,
)

from .client import CoworkClient

# PyQt integration is optional — only imported if Qt bindings are available
# (PySide6 in voice-bridge's venv). Lets cowork_api be importable in CLI
# contexts without Qt installed.
try:
    from .events import CoworkClientSignals, emit_event_to_signals
    _HAS_PYQT = True
except ImportError:
    _HAS_PYQT = False

__all__ = [
    # config
    "DEFAULT_MODEL",
    "DEFAULT_TOOLS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_API_KEY_ENV_VAR",
    "ConfigError",
    "get_api_key",
    # events
    "MessageStarted",
    "TextDelta",
    "ToolUseStarted",
    "ToolUseInput",
    "ToolUseCompleted",
    "MessageCompleted",
    "Error",
    "ConversationEvent",
    "event_to_jsonl",
    "event_from_jsonl",
    # client
    "CoworkClient",
]

if _HAS_PYQT:
    __all__.extend(["CoworkClientSignals", "emit_event_to_signals"])
