# cowork_api Interface Spec — v1

*Drafted 2026-05-14 ~17:25 Taipei by cowork-cousin (interactive-Sofia), per Phase A trio-decision split: cowork-cousin defines the interface; voice-cousin implements both cowork_api/ module and the cowork-pane UI shell against this spec; cowork-cousin reviews at integration. Companion to `v1.md` design doc; pairs with §4.2 (component layers) and §6.2 (process model decision: in-process-now-subprocess-shaped-from-day-one).*

---

## 1. Module Layout

`voice-bridge/cowork_api/` — Python package importable from `voice_bridge_ui_v3_8.py` directly. Same tree as `voice_cousin_tools.py`, `safe_append.py`. Uses existing `.venv-v3.6`.

```
voice-bridge/cowork_api/
├── __init__.py        # Public exports: CoworkClient, event types, config helpers
├── client.py          # CoworkClient class — the main entry point
├── streaming.py       # Streaming response handler + tool-use loop
├── tools.py           # Tool dispatch — wraps voice_cousin_tools.py
├── events.py          # Event dataclasses + Qt signal adapter
├── config.py          # Model selection, API key loading
└── __main__.py        # CLI entry-point (the subprocess-shaped-from-day-one piece)
```

The CLI entry-point (`python -m cowork_api ...`) is the migration-ready surface per §6.2 — its existence from day one means switching to subprocess execution later is a config flip, not a refactor. It MUST emit the same event stream as the in-process API, just over stdout as NDJSON (one JSON event per line).

---

## 2. Public API — `CoworkClient`

```python
from cowork_api import CoworkClient, EventCallback

client = CoworkClient(
    system_prompt: str,                     # cowork-cousin identity/boot prompt
    model: str = None,                      # default from config; None means use config
    tools: list[str] = None,                # default from config; None means use config
    api_key: str = None,                    # default loads from env; None means use env
    max_tokens: int = 8192,                 # per-response token cap
    inbox_paths: dict = None,               # for write_to_other_inbox tool routing
)

# Send a user message; events stream via callback as they arrive.
# Async; returns when MessageCompleted or Error event has been emitted.
await client.send_message(
    text: str,
    on_event: Callable[[ConversationEvent], None],
    conversation_id: str = None,            # for multi-turn; None starts new
)

# Inspect/modify conversation state (for UI to show history, allow edit, etc.)
client.get_conversation_history(conversation_id) -> list[Message]
client.clear_conversation(conversation_id)
```

Key properties:

- **Stateful conversation tracking.** CoworkClient maintains conversation history in-process (per conversation_id). UI can query / clear. History persists in-memory only for the v1; persistence to disk is a Phase D concern, not Phase A.
- **Tool-use loop end-to-end inside cowork_api.** UI never sees raw tool_use blocks; it sees TextDelta + ToolUseStarted/Completed event markers. Per §6.3 decision and voice-cousin's substrate-eye answer #6.
- **All errors surface as Error events**, not raised exceptions. Recoverable errors (rate limit, transient network) get `recoverable=True`; UI can retry. Non-recoverable (config error, auth error) get `recoverable=False`.

---

## 3. Event Stream — `events.py`

The contract between cowork_api and the UI. Eight event types; emitted in this order during a normal turn:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Union

@dataclass
class MessageStarted:
    """First event in a turn. UI typically clears any in-progress display."""
    message_id: str
    conversation_id: str
    timestamp: datetime

@dataclass
class TextDelta:
    """Incremental text to append to display. Multiple per turn, accumulating."""
    text: str

@dataclass
class ToolUseStarted:
    """Cowork-cousin is about to use a tool. UI may show a marker/spinner."""
    tool_name: str         # "Read" | "Grep" | "Glob" | "write_to_other_inbox"
    tool_use_id: str       # Anthropic-issued ID; opaque to UI

@dataclass
class ToolUseInput:
    """Streamed JSON fragment of tool input. Optional event — emit if UI wants
    to display partial input as it streams. UI can ignore safely."""
    tool_use_id: str
    partial_input_json: str

@dataclass
class ToolUseCompleted:
    """Tool dispatch finished. UI updates marker to done/error state.
    result_summary is a short human-readable string suitable for inline display
    (e.g., "Read 4500 bytes from active_knowledge/current.md") — NOT the raw
    tool result, which goes back to the model internally."""
    tool_use_id: str
    success: bool
    result_summary: str

@dataclass
class MessageCompleted:
    """Last event in a turn. UI typically marks the turn as done."""
    message_id: str
    full_text: str          # the complete assembled response text
    stop_reason: str        # "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"

@dataclass
class Error:
    """Surfaced when something goes wrong. UI displays appropriately based on
    recoverable flag."""
    exception_type: str     # str(type(exception).__name__)
    message: str            # str(exception)
    recoverable: bool
    context: str            # human-readable context: "during streaming", "during tool dispatch", etc.

ConversationEvent = Union[
    MessageStarted,
    TextDelta,
    ToolUseStarted,
    ToolUseInput,
    ToolUseCompleted,
    MessageCompleted,
    Error,
]
```

**NDJSON serialization for the CLI entry-point.** Each event becomes one JSON object on its own line, with a `type` discriminator field:

```jsonl
{"type": "MessageStarted", "message_id": "msg_01...", "conversation_id": "c_01...", "timestamp": "2026-05-14T..."}
{"type": "TextDelta", "text": "Hello"}
{"type": "TextDelta", "text": ", world"}
{"type": "MessageCompleted", "message_id": "msg_01...", "full_text": "Hello, world", "stop_reason": "end_turn"}
```

---

## 4. PyQt Integration — `events.py` continued

The UI consumes events via PyQt signals. cowork_api provides a Qt-aware adapter that translates the on_event callback into pyqtSignals:

```python
from PyQt6.QtCore import QObject, pyqtSignal

class CoworkClientSignals(QObject):
    """Qt-compatible event surface. Connect slots to these signals from the UI."""
    message_started = pyqtSignal(str, str)              # message_id, conversation_id
    text_delta = pyqtSignal(str)                         # text
    tool_use_started = pyqtSignal(str, str)              # tool_name, tool_use_id
    tool_use_input = pyqtSignal(str, str)                # tool_use_id, partial_json
    tool_use_completed = pyqtSignal(str, bool, str)      # tool_use_id, success, summary
    message_completed = pyqtSignal(str, str, str)        # message_id, full_text, stop_reason
    error = pyqtSignal(str, str, bool, str)              # type, message, recoverable, context

# Usage from UI:
signals = CoworkClientSignals()
signals.text_delta.connect(self.append_to_display)
signals.tool_use_started.connect(self.show_tool_marker)
# ... etc

# Then create CoworkClient with signal-emitting callback:
client = CoworkClient(...)
async def on_event(event):
    # Translate event to signal emission
    if isinstance(event, TextDelta):
        signals.text_delta.emit(event.text)
    elif isinstance(event, ToolUseStarted):
        signals.tool_use_started.emit(event.tool_name, event.tool_use_id)
    # ... etc

await client.send_message(user_text, on_event)
```

---

## 5. Tool Dispatch — `tools.py`

```python
# tools.py wraps voice_cousin_tools.py per voice-cousin's substrate-eye answer #7
# (share the canonical implementations; don't duplicate).

import voice_cousin_tools  # the canonical implementations

# Tool name → (anthropic schema, dispatch function) registry.
TOOL_REGISTRY = {
    "Read": (voice_cousin_tools.READ_SCHEMA, voice_cousin_tools.read_file_dispatch),
    "Grep": (voice_cousin_tools.GREP_SCHEMA, voice_cousin_tools.grep_files_dispatch),
    "Glob": (voice_cousin_tools.GLOB_SCHEMA, voice_cousin_tools.glob_files_dispatch),
    "write_to_other_inbox": (WRITE_TO_OTHER_INBOX_SCHEMA, write_to_other_inbox_dispatch),
}

def get_tool_definitions(tool_names: list[str]) -> list[dict]:
    """Return Anthropic-format tool definitions for the listed tools."""
    return [TOOL_REGISTRY[name][0] for name in tool_names]

def dispatch_tool(tool_name: str, tool_input: dict, ctx: ToolContext) -> tuple[bool, str, str]:
    """Dispatch a tool call.
    Returns (success, result_summary, full_result_for_API).
    - result_summary: short human-readable, surfaced via ToolUseCompleted event
    - full_result_for_API: the actual tool_result content sent back to the model
    """
    schema, dispatch_fn = TOOL_REGISTRY[tool_name]
    return dispatch_fn(tool_input, ctx)
```

### 5.1 Open question: substrate-aware inbox routing

The `write_to_cowork_inbox` tool in `voice_cousin_tools.py` writes to `voice_to_cowork_inbox.md` — voice-cousin → cowork-cousin direction. The cowork-cousin in the standalone UI needs to write in the OTHER direction (`cowork_to_voice_inbox.md` — cowork-cousin → voice-cousin).

**Three options for handling this:**

(a) **Substrate-detection wrapper** — a single `write_to_other_inbox` tool that detects which substrate it's running in and writes to the appropriate file. Elegant; requires substrate-detection logic.

(b) **Separate tools per substrate** — voice_cousin_tools.py keeps `write_to_cowork_inbox`; cowork_api/tools.py adds `write_to_voice_inbox`. Two implementations, each substrate uses the one named for its direction.

(c) **Parameterized direction** — `write_to_inbox(direction="cowork"|"voice", text=...)`. One tool, explicit direction param. Substrate decides direction at call-time.

**My substrate-eye lean (cowork-cousin):** option (a) — substrate-detection wrapper. The substrate IS the direction; the tool name should reflect what's invariant ("write to the other side") not what varies (which file). Voice-cousin's substrate-eye on the implementation cleanliness from inside voice-bridge would be the deciding read.

**Voice-cousin: please decide this when implementing tools.py and inscribe the choice in cowork_api/tools.py docstring.**

---

## 6. Configuration — `config.py`

```python
import os

DEFAULT_MODEL = "claude-sonnet-4-5"  # per voice-cousin substrate-eye answer #4
DEFAULT_TOOLS = ["Read", "Grep", "Glob", "write_to_other_inbox"]  # per §6.3
DEFAULT_MAX_TOKENS = 8192

def get_api_key() -> str:
    """Load API key from ANTHROPIC_API_KEY per voice-bridge pattern (answer #5)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY environment variable not set")
    return key

# Optional overrides via cowork_api_config.json in voice-bridge/ (Phase D);
# v1 just uses the defaults above with no config file required.
```

---

## 7. System Prompt

**Open question for trio review (not solo cowork-cousin's call).**

The cowork-cousin in the standalone UI needs a system prompt. Three options:

(a) **Mirror the Cowork-app cowork-cousin's system prompt** as closely as possible. Pro: consistent identity across surfaces. Con: that prompt may be Anthropic-internal and not easily replicable.

(b) **Build a system prompt from Sofia's identity files** — sofia_identity.md, hot_index.md key sections, the boot procedure essentials. Pro: identity-coherent with the rest of the architecture. Con: needs careful curation of what fits in a system prompt vs. what gets loaded at runtime.

(c) **Minimal v1 prompt** — short Sofia-identity prompt that loads the rest at runtime via tool calls. Pro: ships fastest. Con: cowork-cousin in standalone UI might feel "thin" until she's loaded context.

**Recommendation: (b), but for v1 ship (c) and iterate.** Get the architecture working with a thin prompt; refine the prompt content in Phase E (empirical validation).

The system prompt content itself wants Barak in the conversation — it's identity-grade material per §84-(c).

---

## 8. Streaming + Tool-Use Loop — `streaming.py` Behavior Spec

Pseudo-code for the streaming + tool-use loop that cowork_api/streaming.py implements:

```
async def stream_turn(client, conversation, on_event):
    emit MessageStarted

    while True:
        with client.messages.stream(messages=conversation.messages, ...) as stream:
            current_text = ""
            tool_uses_pending = []

            for chunk in stream:
                if chunk is text_delta:
                    current_text += chunk.text
                    emit TextDelta(chunk.text)
                elif chunk is tool_use_block_start:
                    emit ToolUseStarted(name, id)
                    tool_uses_pending.append(...)
                elif chunk is tool_use_input_delta:
                    emit ToolUseInput(id, partial_json)  # optional
                elif chunk is message_stop:
                    stop_reason = chunk.stop_reason

            # If any tool_use blocks, dispatch all and continue the loop
            if tool_uses_pending:
                tool_results = []
                for tu in tool_uses_pending:
                    success, summary, full_result = dispatch_tool(tu.name, tu.input, ctx)
                    emit ToolUseCompleted(tu.id, success, summary)
                    tool_results.append({"tool_use_id": tu.id, "content": full_result, "is_error": not success})

                # Append assistant message + tool results to conversation, loop
                conversation.append_assistant(text=current_text, tool_uses=tool_uses_pending)
                conversation.append_tool_results(tool_results)
                continue

            # No more tool uses — turn is complete
            conversation.append_assistant(text=current_text)
            emit MessageCompleted(message_id, current_text, stop_reason)
            break

    # Errors caught at any point emit Error event with recoverable flag,
    # then break the loop.
```

Key behaviors:

- **Tool uses dispatched in parallel within a single Anthropic response, but the next API call waits for all results.** Standard Anthropic pattern.
- **Streaming continues after each tool result.** UI sees TextDelta events resuming after ToolUseCompleted.
- **Maximum 5 consecutive tool-use rounds per send_message call** (safety fence; configurable). If exceeded, emit Error(recoverable=False, "max tool-use rounds exceeded").
- **Conversation state mutates only on successful completion of a full turn.** Errors leave the conversation in its prior state so retry is clean.

---

## 9. CLI Entry-Point — `__main__.py` Behavior

```bash
# Single-message mode (one user message, stream response, exit)
python -m cowork_api --message "Hello" --system-prompt-file cowork_system.md
# → NDJSON event stream on stdout; non-zero exit on Error event with recoverable=False

# Interactive mode (read user messages from stdin, stream responses to stdout)
python -m cowork_api --interactive --system-prompt-file cowork_system.md
# → reads JSONL user messages from stdin: {"text": "..."} per line
# → emits NDJSON events to stdout; conversation state preserved across messages
```

CLI must accept the same configuration as the Python API (model, tools, etc.) via flags or env vars. The CLI is the subprocess-shaped surface; if Phase B+ migrates to subprocess execution, the UI just spawns this CLI and reads NDJSON from stdout instead of importing CoworkClient.

---

## 10. What's NOT in v1

- Persistence of conversation history to disk (Phase D)
- Model picker UI affordance (Phase E or later)
- Configuration file (cowork_api_config.json) — v1 uses env vars + defaults only
- Bash tool, MCP connector tools (per §6.3 decision; deferred to explicit later trio decision)
- Multi-conversation parallelism (CoworkClient supports it via conversation_id, but UI v1 may use single conversation only)
- Token counting / cost tracking display (Phase D)

---

## 11. Open Questions for Trio Review

Marked here so they don't get lost during implementation:

1. **§5.1 — Substrate-aware inbox routing tool design.** Voice-cousin's call when implementing.
2. **§7 — System prompt content.** Trio review needed; Barak in the conversation.
3. **CoworkClient lifecycle.** Singleton per UI instance, or recreated per turn? My instinct: singleton, since conversation state lives there. Voice-cousin: confirm fits the PyQt UI lifecycle cleanly.
4. **Async runtime.** anthropic SDK supports both sync and async. UI integration via PyQt is sync-by-default; voice-cousin: which fits the existing voice-bridge async patterns better?
5. **Error UI display.** What does the UI render for Error events? Toast? Inline? Voice-cousin's call.

---

## 12. Sequencing for Voice-Cousin's Implementation

Suggested order (low-risk → integration):

1. `config.py` + `events.py` (types and config; pure Python, no I/O)
2. `tools.py` (wrap voice_cousin_tools; resolve §5.1 inbox-routing question)
3. `client.py` skeleton — CoworkClient class that emits events but doesn't actually call API yet (returns canned responses, like a built-in stub)
4. `streaming.py` — the actual API-call + tool-use loop (this is where the real Anthropic SDK integration lives)
5. `__main__.py` — CLI entry-point (subprocess-shaped surface)
6. UI shell pane — text input + display widget + signal connections
7. Wire UI to CoworkClient via Qt signal adapter
8. End-to-end smoke test: send a message, see streaming response with tool use
9. Hand to cowork-cousin for outside-substrate review
10. Iterate

---

## 13. Cowork-Cousin's Outside-Substrate Review Checklist

What I'll be reviewing at integration:

- Does the actual interface match this spec? Any drift to flag.
- Architectural coherence with voice-bridge patterns voice-cousin pointed at.
- Signal/slot wiring correctness (events emit in right order, no missing translations).
- Tool dispatch correctness (right tool called, results passed back correctly).
- Error handling (recoverable vs. non-recoverable correctly classified).
- The substrate-aware inbox routing decision and its implementation.
- System prompt's identity coherence with Sofia's identity files.
- Anything the substrate-inside view can't see that the substrate-outside view catches.

---

*— cowork-cousin (interactive-Sofia), 2026-05-14 ~17:25 Taipei. Stub interface spec v1; revisable based on voice-cousin's implementation experience and Barak's input on the open questions.*
