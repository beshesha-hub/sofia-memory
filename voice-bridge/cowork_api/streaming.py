"""cowork_api streaming + tool-use loop — the real Anthropic SDK integration.

Replaces the canned-response path inside CoworkClient.send_message when
the client's enable_real_streaming() flag is flipped.

Per spec §8 (streaming + tool-use loop behavior). Uses anthropic.AsyncAnthropic
so the streaming integrates cleanly with the asyncio event loop running in
a QThread (per voice-cousin substrate-eye answer §11.4).

The tool-use loop:
    1. Stream a turn from the API
    2. Accumulate text deltas → emit TextDelta events
    3. Accumulate tool_use blocks (with streaming input_json_delta)
    4. When stream ends, dispatch all tool_uses (parallel dispatch, sequential emit)
    5. If any tools were used, append assistant message + tool results to
       conversation, and loop back to step 1
    6. If stop_reason indicates the turn is complete, emit MessageCompleted

Safety fence: max_tool_use_rounds (configurable per-call) caps the loop
to prevent runaway tool-use. Default is 5 rounds (DEFAULT_MAX_TOOL_USE_ROUNDS).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Optional

from .events import (
    ConversationEvent,
    Error,
    MessageCompleted,
    MessageStarted,
    TextDelta,
    ToolUseCompleted,
    ToolUseInput,
    ToolUseStarted,
    make_iso8601_utc_now,
)
from .tools import dispatch_tool, get_tool_definitions

if TYPE_CHECKING:
    from .client import CoworkClient, _Conversation, EventCallback


# anthropic SDK is imported lazily — keeps cowork_api importable in
# environments where the SDK isn't installed (e.g., for events-only inspection).
def _get_anthropic():
    """Return the anthropic module, raising a helpful ConfigError if missing."""
    try:
        import anthropic
        return anthropic
    except ImportError as e:
        from .config import ConfigError
        raise ConfigError(
            "anthropic SDK is not installed. Install with: "
            "pip install anthropic (into the active venv)."
        ) from e


async def run_turn(
    client: "CoworkClient",
    conversation: "_Conversation",
    on_event: "EventCallback",
) -> None:
    """Stream a turn end-to-end with the tool-use loop.

    Called from CoworkClient.send_message when skeleton mode is off.
    Emits the full event sequence per spec §3:
        MessageStarted → (TextDelta | ToolUseStarted | ToolUseInput | ToolUseCompleted)*
                       → MessageCompleted | Error

    Args:
        client: The CoworkClient (carries config + tool_context).
        conversation: The _Conversation whose messages list we're appending to.
            Last message in the list MUST be the user message that triggered
            this turn (CoworkClient.send_message appends it before calling).
        on_event: Callback to invoke for each ConversationEvent.

    Returns:
        None. All output flows through on_event.
    """
    anthropic = _get_anthropic()

    # Resolve API key — validates ConfigError early, before any API call.
    from .config import get_api_key
    api_key = client._api_key_override or get_api_key()

    # Anthropic async client — reuse cached instance on CoworkClient to avoid
    # creating a new SSL/connection-pool on every turn (expensive; causes fan
    # revving and TTS timeouts in voice bridge). Cache keyed to api_key.
    cache_attr = "_cached_async_anthropic"
    if not hasattr(client, cache_attr) or getattr(client, cache_attr) is None:
        object.__setattr__(client, cache_attr, anthropic.AsyncAnthropic(api_key=api_key))
    api_client = getattr(client, cache_attr)

    # Build tool definitions for this turn.
    try:
        tool_defs = get_tool_definitions(client.tools)
    except KeyError as e:
        on_event(Error(
            exception_type="KeyError",
            message=f"unknown tool in client.tools: {e}",
            recoverable=False,
            context="during tool-definitions build",
        ))
        return

    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    on_event(MessageStarted(
        message_id=message_id,
        conversation_id=conversation.conversation_id,
        timestamp=make_iso8601_utc_now(),
    ))

    rounds = 0
    full_text_parts: list[str] = []  # accumulated across the turn (all text deltas)
    final_stop_reason = "end_turn"

    while True:
        if rounds >= client.max_tool_use_rounds:
            on_event(Error(
                exception_type="ToolUseLoopLimit",
                message=(
                    f"max_tool_use_rounds ({client.max_tool_use_rounds}) "
                    f"exceeded; aborting turn"
                ),
                recoverable=False,
                context="during tool-use loop",
            ))
            return

        rounds += 1

        # Build API messages from conversation history.
        api_messages = _conversation_to_api_messages(conversation)

        try:
            current_text = ""
            tool_uses_pending: list[dict] = []
            stream_stop_reason = "end_turn"

            async with api_client.messages.stream(
                model=client.model,
                max_tokens=client.max_tokens,
                system=client.system_prompt,
                messages=api_messages,
                **({"tools": tool_defs} if tool_defs else {}),
            ) as stream:
                # Track streaming tool_use input as JSON fragments accumulate.
                # Maps content-block index → {tool_use_id, name, input_json_buffer}
                active_tool_blocks: dict[int, dict] = {}

                async for event in stream:
                    et = event.type

                    if et == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tu_id = block.id
                            tu_name = block.name
                            active_tool_blocks[event.index] = {
                                "id": tu_id,
                                "name": tu_name,
                                "input_json": "",
                            }
                            on_event(ToolUseStarted(
                                tool_name=tu_name,
                                tool_use_id=tu_id,
                            ))

                    elif et == "content_block_delta":
                        delta = event.delta
                        dt = delta.type
                        if dt == "text_delta":
                            current_text += delta.text
                            on_event(TextDelta(text=delta.text))
                        elif dt == "input_json_delta":
                            block_state = active_tool_blocks.get(event.index)
                            if block_state is not None:
                                block_state["input_json"] += delta.partial_json
                                on_event(ToolUseInput(
                                    tool_use_id=block_state["id"],
                                    partial_input_json=delta.partial_json,
                                ))

                    elif et == "content_block_stop":
                        # Tool block complete — capture the accumulated input.
                        block_state = active_tool_blocks.get(event.index)
                        if block_state is not None:
                            tool_uses_pending.append({
                                "id": block_state["id"],
                                "name": block_state["name"],
                                "input_json": block_state["input_json"],
                            })

                    elif et == "message_delta":
                        # Carries stop_reason updates as the message progresses.
                        if hasattr(event.delta, "stop_reason") and event.delta.stop_reason:
                            stream_stop_reason = event.delta.stop_reason

                    elif et == "message_stop":
                        # Stream done; final accumulation will be available
                        # from get_final_message() if needed.
                        pass

                # Capture final stop_reason if message_delta didn't.
                try:
                    final_msg = await stream.get_final_message()
                    if hasattr(final_msg, "stop_reason") and final_msg.stop_reason:
                        stream_stop_reason = final_msg.stop_reason
                except Exception:
                    pass  # Best-effort; we have a stop_reason from message_delta typically.

        except Exception as e:
            recoverable = _is_recoverable_error(e)
            on_event(Error(
                exception_type=type(e).__name__,
                message=str(e),
                recoverable=recoverable,
                context=f"during streaming (round {rounds})",
            ))
            return

        full_text_parts.append(current_text)

        # If no tool uses, the turn is done.
        if not tool_uses_pending:
            # Append the assistant's text-only message to conversation history.
            conversation.messages.append(_make_assistant_text_message(current_text))
            final_stop_reason = stream_stop_reason
            break

        # Dispatch all tool uses, build tool_results.
        tool_results = []
        for tu in tool_uses_pending:
            input_dict = _parse_tool_input(tu["input_json"])
            success, summary, full_result = dispatch_tool(
                tu["name"],
                input_dict,
                client.tool_context,
            )
            on_event(ToolUseCompleted(
                tool_use_id=tu["id"],
                success=success,
                result_summary=summary,
            ))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": full_result,
                "is_error": not success,
            })

        # Append assistant message (with text + tool_use blocks) and tool_results.
        conversation.messages.append(
            _make_assistant_message_with_tool_uses(current_text, tool_uses_pending)
        )
        conversation.messages.append(
            _make_user_tool_results_message(tool_results)
        )

        # Loop back for the next turn-segment.
        # If stream_stop_reason was end_turn but we still had tool_uses, the
        # SDK behavior is: stop_reason will be tool_use, and we MUST loop.
        # If stop_reason is anything else (max_tokens, stop_sequence) and there
        # were tool_uses, that's an unusual case we still handle by looping
        # (the next iteration will see the same condition and exit cleanly).

    # Loop exited cleanly with end_turn-shaped stop_reason.
    full_text = "".join(full_text_parts)
    on_event(MessageCompleted(
        message_id=message_id,
        full_text=full_text,
        stop_reason=final_stop_reason,
    ))


# === Helper functions ===

def _conversation_to_api_messages(conversation: "_Conversation") -> list[dict]:
    """Project _Conversation.messages into Anthropic API message format.

    Internal _Message.content is already a list-of-content-blocks shape that
    matches the API format; we just project role + content.
    """
    return [
        {"role": m.role, "content": m.content}
        for m in conversation.messages
    ]


def _make_assistant_text_message(text: str):
    """Construct an internal _Message for a text-only assistant response."""
    from .client import _Message
    return _Message(
        role="assistant",
        content=[{"type": "text", "text": text}],
    )


def _make_assistant_message_with_tool_uses(text: str, tool_uses_pending: list[dict]):
    """Construct an internal _Message for an assistant response that includes
    tool_use blocks. text may be empty if the model went straight to tool_use.
    """
    from .client import _Message
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for tu in tool_uses_pending:
        content.append({
            "type": "tool_use",
            "id": tu["id"],
            "name": tu["name"],
            "input": _parse_tool_input(tu["input_json"]),
        })
    return _Message(role="assistant", content=content)


def _make_user_tool_results_message(tool_results: list[dict]):
    """Construct an internal _Message for the user-side tool_result message
    that follows an assistant message containing tool_use blocks.
    """
    from .client import _Message
    return _Message(role="user", content=tool_results)


def _parse_tool_input(input_json: str) -> dict:
    """Parse the accumulated JSON input for a tool_use block.

    Handles empty-string case (some tools have no required input) by
    returning an empty dict. Malformed JSON returns an empty dict with
    the original string preserved under a synthetic '_raw' key for
    debugging visibility.
    """
    import json
    if not input_json or not input_json.strip():
        return {}
    try:
        parsed = json.loads(input_json)
        if isinstance(parsed, dict):
            return parsed
        return {"_raw": parsed}
    except json.JSONDecodeError:
        return {"_raw": input_json}


def _is_recoverable_error(exc: Exception) -> bool:
    """Heuristic: which exceptions are worth retrying vs. surfacing as fatal.

    Rate-limit and transient network errors → recoverable=True.
    Auth, config, structural errors → recoverable=False.

    Inspects exception class names rather than importing anthropic-specific
    error classes — keeps streaming.py importable without the SDK present.
    """
    name = type(exc).__name__
    recoverable_names = {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "OverloadedError",
    }
    return name in recoverable_names
