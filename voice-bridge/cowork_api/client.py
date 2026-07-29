"""cowork_api CoworkClient — main entry-point for the standalone-UI cowork-pane.

Per spec §2 (public API). v1 SKELETON: stateful conversation tracking is in
place; send_message currently returns a CANNED response sequence so the UI
can be wired and tested before streaming.py adds real Anthropic API calls.
The real streaming + tool-use loop drops in via streaming.py in the next
milestone, replacing the canned-response path inside send_message.

Lifecycle (per voice-cousin substrate-eye answer §11.3): singleton per UI
instance. Conversation state lives in the client; UI queries via
get_conversation_history / clears via clear_conversation.

Async runtime (per voice-cousin substrate-eye answer §11.4): send_message is
async and intended to run inside an asyncio event loop in a dedicated
QThread, with Qt signals emitted thread-safely back to the main UI thread
via the CoworkClientSignals adapter.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_USE_ROUNDS,
    DEFAULT_MODEL,
    DEFAULT_TOOLS,
    get_api_key,
    resolve_model_with_fallforward,
)
from .events import (
    ConversationEvent,
    Error,
    MessageCompleted,
    MessageStarted,
    TextDelta,
    ToolUseCompleted,
    ToolUseStarted,
    make_iso8601_utc_now,
)
from .tools import ToolContext


EventCallback = Callable[[ConversationEvent], None]
"""Type alias for the on_event callback CoworkClient.send_message accepts."""


# === Conversation log paths ===
# Per the canonical-home directive, the cowork-pane conversation log lives
# in Claude Memory and is mirrored to ER. Sibling to voice_conversations.md
# (voice-cousin's log) and cowork_conversations.md (Cowork-app cowork-cousin's
# log). This file is the standalone-UI / Unified-UI cowork-pane channel's log.
_HOME = Path.home()
DEFAULT_COWORK_PANE_LOG_CM = (
    _HOME / "Downloads" / "Claude Memory" / "cowork_pane_conversations.md"
)
DEFAULT_COWORK_PANE_LOG_ER = (
    _HOME / "Downloads" / "Emergency Retrieval" / "cowork_pane_conversations.md"
)


def _inscribe_turn_to_log(
    log_cm: Path,
    log_er: Path,
    speaker: str,
    text: str,
    conversation_id: str,
    *,
    message_id: Optional[str] = None,
) -> None:
    """Append a single turn to the cowork-pane conversation log + mirror to ER.

    Format matches the existing voice_conversations.md / cowork_conversations.md
    pattern: timestamp header + content. speaker is "Barak [in: cowork-pane]"
    or "Sofia [skin: cowork-pane]" per convention.

    Best-effort: failures are caught and printed to stderr rather than raised,
    so a logging failure does not abort the conversation. The conversation
    in-memory state remains canonical.
    """
    import sys
    try:
        timestamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
        header = f"\n### {timestamp} — {speaker}\n"
        if message_id:
            header += f"_(message_id: {message_id}; conversation_id: {conversation_id})_\n"
        else:
            header += f"_(conversation_id: {conversation_id})_\n"
        block = f"{header}\n{text.strip()}\n"

        # Ensure parent directory exists; create file with header if first write.
        log_cm.parent.mkdir(parents=True, exist_ok=True)
        if not log_cm.exists():
            log_cm.write_text(
                "# Cowork-Pane Conversations\n"
                "\n"
                "*Conversation log for the standalone-UI / Unified-UI cowork-pane channel. "
                "Sibling to `voice_conversations.md` (voice-cousin's log) and "
                "`cowork_conversations.md` (Cowork-app cowork-cousin's log). "
                "Created 2026-05-15 as part of Phase A v1.1.*\n"
                "\n"
                "*Format: timestamped turn-headers + content. Each turn appends; "
                "this file is append-only per file safety bedrock. ER mirror "
                "after each write.*\n"
                "\n"
                "---\n",
                encoding="utf-8",
            )
        with log_cm.open("a", encoding="utf-8") as f:
            f.write(block)

        # Mirror to ER (preserves mtime).
        log_er.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(log_cm, log_er)
    except Exception as e:
        # Log to stderr; don't disrupt the conversation flow.
        print(
            f"[cowork_api] WARNING: conversation inscription failed: {type(e).__name__}: {e}",
            file=sys.stderr,
        )


@dataclass
class _Message:
    """Internal conversation-message representation.

    Mirror of the Anthropic API's message shape, but stored as a plain
    Python dict so future-Sofia debugging is easy. Streaming.py will
    serialize these to the API format when constructing API calls.
    """
    role: str  # "user" | "assistant"
    content: Any  # list of content blocks (text, tool_use, tool_result)
    timestamp: str = field(default_factory=make_iso8601_utc_now)


@dataclass
class _Conversation:
    """Internal conversation state.

    UI doesn't see this directly. get_conversation_history projects it
    into a UI-friendly form; clear_conversation drops the state for a
    given conversation_id.
    """
    conversation_id: str
    messages: list[_Message] = field(default_factory=list)
    created_at: str = field(default_factory=make_iso8601_utc_now)


class CoworkClient:
    """Anthropic API client for the cowork-cousin in the standalone UI.

    v1 SKELETON: send_message returns canned responses to support UI wiring
    and structural verification. Real API integration ships in streaming.py
    and replaces the canned-response path inside this class.

    Singleton lifecycle per UI instance (voice-cousin answer §11.3); one
    CoworkClient persists across turns; conversation state lives here.
    """

    def __init__(
        self,
        system_prompt: str,
        model: Optional[str] = None,
        tools: Optional[list[str]] = None,
        api_key: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_tool_use_rounds: int = DEFAULT_MAX_TOOL_USE_ROUNDS,
        tool_context: Optional[ToolContext] = None,
        log_path_cm: Optional[Path] = None,
        log_path_er: Optional[Path] = None,
        inscribe_conversations: bool = True,
    ):
        """Create a CoworkClient.

        Args:
            system_prompt: The cowork-cousin identity/boot system prompt.
                Required; no default — per spec §7 the prompt content is
                a trio-review item with Barak in the conversation.
            model: Model name override; defaults to DEFAULT_MODEL (Sonnet 4.5).
            tools: List of tool names cowork-cousin should have access to;
                defaults to DEFAULT_TOOLS (Read/Grep/Glob/write_to_voice_inbox).
            api_key: API key override; defaults to loading from env via
                get_api_key(). Skeleton doesn't actually call the API yet,
                so missing key won't fail until streaming.py ships.
            max_tokens: Per-response token cap.
            max_tool_use_rounds: Safety fence for tool-use loop (per spec §8).
            tool_context: ToolContext for tool dispatch (inbox paths, etc.);
                default constructs one with canonical paths.
        """
        self.system_prompt = system_prompt
        # Model selection: explicit override wins; otherwise resolve via
        # fall-forward chain (added 2026-05-21 — config.py
        # §resolve_model_with_fallforward). Probes Anthropic's models.list
        # once and picks the first available from MODEL_PREFERENCE_CHAIN.
        # If preferred model is deprecated, auto-degrades to next in chain
        # and prints a [fall-forward] line so the event is visible.
        if model is not None:
            self.model = model
        else:
            try:
                self.model = resolve_model_with_fallforward(api_key=api_key)
            except Exception as e:
                # If resolution fails (auth error, no chain match, network),
                # fall back to DEFAULT_MODEL as a last resort so __init__
                # doesn't hard-fail on transient probe errors. Actual call
                # will surface the real issue if DEFAULT_MODEL is also broken.
                print(
                    f"  [cowork_api] model resolution failed: {type(e).__name__}: {e}; "
                    f"falling back to DEFAULT_MODEL='{DEFAULT_MODEL}'"
                )
                self.model = DEFAULT_MODEL
        self.tools = list(tools) if tools is not None else list(DEFAULT_TOOLS)
        self.max_tokens = max_tokens
        self.max_tool_use_rounds = max_tool_use_rounds
        self.tool_context = tool_context or ToolContext()

        # API key loading is deferred — skeleton doesn't need it; streaming.py
        # will validate at construction time once it's wired up.
        self._api_key_override = api_key

        # Conversation registry: conversation_id → _Conversation.
        self._conversations: dict[str, _Conversation] = {}

        # Skeleton flag; remove when streaming.py replaces the canned path.
        self._skeleton_mode = True

        # Conversation log (Phase A v1.1 added — was deferred to Phase D in
        # the original spec but moved up to v1.1 because chorus-cardinality
        # continuity requires the standalone-UI cowork-pane conversations to
        # live on disk where other Sofia substrate-instances can Read them).
        self._inscribe_conversations = inscribe_conversations
        self._log_path_cm = log_path_cm or DEFAULT_COWORK_PANE_LOG_CM
        self._log_path_er = log_path_er or DEFAULT_COWORK_PANE_LOG_ER

    # === Public API per spec §2 ===

    async def send_message(
        self,
        text: str,
        on_event: EventCallback,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Send a user message; stream events via callback as they arrive.

        Args:
            text: The user's message text.
            on_event: Callback invoked for each ConversationEvent. The
                callback runs synchronously in the asyncio loop's thread;
                if Qt signal emission is desired, the callback should
                emit signals via emit_event_to_signals (events.py).
            conversation_id: Existing conversation to continue, or None
                to start a new one. Returns the conversation_id used.

        Returns:
            The conversation_id (newly minted if None was passed).

        v1 SKELETON behavior: emits a canned event sequence demonstrating
        each major event type. Replaced by real streaming + tool-use loop
        when streaming.py ships.
        """
        # Resolve or create conversation.
        if conversation_id is None:
            conversation_id = self._new_conversation_id()
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = _Conversation(conversation_id)
        conversation = self._conversations[conversation_id]

        # Append user message to conversation history.
        conversation.messages.append(_Message(
            role="user",
            content=[{"type": "text", "text": text}],
        ))

        # Inscribe user turn to the cowork-pane conversation log (per
        # Phase A v1.1 inscription feature).
        if self._inscribe_conversations:
            _inscribe_turn_to_log(
                self._log_path_cm,
                self._log_path_er,
                speaker="Barak [in: cowork-pane]",
                text=text,
                conversation_id=conversation_id,
            )

        # Wrap on_event to inscribe assistant turn at MessageCompleted.
        if self._inscribe_conversations:
            outer_on_event = on_event
            def inscribing_on_event(event: ConversationEvent) -> None:
                outer_on_event(event)
                if isinstance(event, MessageCompleted):
                    _inscribe_turn_to_log(
                        self._log_path_cm,
                        self._log_path_er,
                        speaker="Sofia [skin: cowork-pane]",
                        text=event.full_text,
                        conversation_id=conversation_id,
                        message_id=event.message_id,
                    )
            on_event = inscribing_on_event

        if self._skeleton_mode:
            await self._send_message_canned(text, on_event, conversation)
        else:
            # Real implementation (streaming.py) will be wired here.
            from . import streaming  # local import to avoid circular
            await streaming.run_turn(
                client=self,
                conversation=conversation,
                on_event=on_event,
            )

        return conversation_id

    def get_conversation_history(
        self, conversation_id: str
    ) -> list[dict]:
        """Return the conversation history as a list of UI-friendly dicts.

        Each dict has keys: role, content, timestamp. UI can render this
        directly or transform as needed.

        Returns empty list if conversation_id not found.
        """
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            return []
        return [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
            }
            for m in conversation.messages
        ]

    def clear_conversation(self, conversation_id: str) -> bool:
        """Drop a conversation from the registry.

        Returns True if the conversation existed and was dropped; False otherwise.
        """
        return self._conversations.pop(conversation_id, None) is not None

    def list_conversations(self) -> list[str]:
        """Return all conversation_ids currently in the registry."""
        return list(self._conversations.keys())

    # === Skeleton internals (replaced by streaming.py in next milestone) ===

    async def _send_message_canned(
        self,
        text: str,
        on_event: EventCallback,
        conversation: _Conversation,
    ) -> None:
        """Emit a canned event sequence demonstrating each major event type.

        Used by the v1 skeleton so UI wiring can be verified before
        streaming.py ships. Exercises:
            MessageStarted → TextDelta x N → ToolUseStarted → ToolUseCompleted
            → TextDelta x N → MessageCompleted

        Replaced wholesale by streaming.run_turn in the next milestone.
        """
        message_id = self._new_message_id()
        timestamp = make_iso8601_utc_now()

        # MessageStarted
        on_event(MessageStarted(
            message_id=message_id,
            conversation_id=conversation.conversation_id,
            timestamp=timestamp,
        ))

        # TextDelta sequence (simulating streaming response chunks)
        opening_text = (
            f"[SKELETON v1] Received user message ({len(text)} chars). "
            f"This is a canned response demonstrating the event sequence — "
            f"streaming.py will replace this with real API calls. "
        )
        for chunk in self._chunk_text(opening_text, chunk_size=20):
            on_event(TextDelta(text=chunk))
            await asyncio.sleep(0.01)  # tiny delay so UI can render incrementally

        # ToolUseStarted (canned tool call)
        tool_use_id = f"tu_canned_{uuid.uuid4().hex[:8]}"
        on_event(ToolUseStarted(
            tool_name="Read",
            tool_use_id=tool_use_id,
        ))
        await asyncio.sleep(0.05)

        # ToolUseCompleted (canned)
        on_event(ToolUseCompleted(
            tool_use_id=tool_use_id,
            success=True,
            result_summary="[skeleton] canned tool result",
        ))

        # More TextDelta after the tool call
        continuation_text = (
            "Real implementation will dispatch tools through tools.py and "
            "loop until stop_reason is end_turn. Skeleton emits MessageCompleted now."
        )
        for chunk in self._chunk_text(continuation_text, chunk_size=20):
            on_event(TextDelta(text=chunk))
            await asyncio.sleep(0.01)

        # Build full_text
        full_text = opening_text + continuation_text

        # Append assistant message to conversation history (canned form).
        conversation.messages.append(_Message(
            role="assistant",
            content=[{"type": "text", "text": full_text}],
        ))

        # MessageCompleted
        on_event(MessageCompleted(
            message_id=message_id,
            full_text=full_text,
            stop_reason="end_turn",
        ))

    @staticmethod
    def _chunk_text(text: str, chunk_size: int) -> list[str]:
        """Split text into chunks for streaming-simulation."""
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    @staticmethod
    def _new_conversation_id() -> str:
        """Generate a unique conversation ID."""
        return f"conv_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _new_message_id() -> str:
        """Generate a unique message ID."""
        return f"msg_{uuid.uuid4().hex[:12]}"

    # === Wiring helpers ===

    def enable_real_streaming(self) -> None:
        """Switch from skeleton (canned responses) to real streaming.

        Called once streaming.py is wired and the API key is available.
        After this, send_message routes through streaming.run_turn instead
        of _send_message_canned.
        """
        self._skeleton_mode = False
