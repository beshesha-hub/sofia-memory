"""cowork_api CLI entry-point — the subprocess-shaped surface.

Per spec §9 + §6.2 design decision (in-process-now, subprocess-shaped-from-day-one).
This module exists so that future migration to subprocess execution is a
config flip in the UI rather than a refactor of the API.

Usage:
    # Single-message mode (one user message, stream response, exit):
    python -m cowork_api --message "Hello" --system-prompt-file cowork_system.md

    # Interactive mode (read user messages from stdin as JSONL, stream
    # responses to stdout as NDJSON events; conversation state preserved
    # across messages):
    python -m cowork_api --interactive --system-prompt-file cowork_system.md

Output format (both modes):
    NDJSON event stream on stdout — one JSON object per line, with a `type`
    discriminator field plus all dataclass fields. Same event semantics as
    the in-process Python API; just serialized for IPC.

Exit codes:
    0 — clean completion (single-message: turn completed; interactive: stdin closed)
    1 — non-recoverable Error event emitted (config error, auth error, etc.)
    2 — invalid CLI arguments
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from .client import CoworkClient
from .config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_USE_ROUNDS,
    DEFAULT_MODEL,
    DEFAULT_TOOLS,
)
from .events import ConversationEvent, Error, event_to_jsonl


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cowork_api",
        description=(
            "cowork_api CLI — Anthropic API client for the standalone-UI "
            "cowork-cousin. Emits NDJSON event stream on stdout."
        ),
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--message", "-m",
        type=str,
        help="Single-message mode: send this user message and exit after the turn completes.",
    )
    mode.add_argument(
        "--interactive", "-i",
        action="store_true",
        help=(
            "Interactive mode: read user messages from stdin as JSONL "
            "(one JSON object per line, with a 'text' field). Conversation "
            "state preserved across messages."
        ),
    )

    parser.add_argument(
        "--system-prompt-file", "-s",
        type=Path,
        required=True,
        help="Path to a file containing the cowork-cousin system prompt.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Anthropic model name (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--tools",
        type=str,
        default=",".join(DEFAULT_TOOLS),
        help=(
            f"Comma-separated list of tool names "
            f"(default: {','.join(DEFAULT_TOOLS)}). "
            f"Pass empty string to disable tools."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Per-response max_tokens (default: {DEFAULT_MAX_TOKENS}).",
    )
    parser.add_argument(
        "--max-tool-use-rounds",
        type=int,
        default=DEFAULT_MAX_TOOL_USE_ROUNDS,
        help=f"Tool-use loop safety fence (default: {DEFAULT_MAX_TOOL_USE_ROUNDS}).",
    )
    parser.add_argument(
        "--skeleton",
        action="store_true",
        help=(
            "Use canned-response skeleton mode (no real API calls). "
            "Useful for testing the event-stream protocol without burning tokens."
        ),
    )

    return parser


def _emit(event: ConversationEvent) -> None:
    """Write one event as a single NDJSON line to stdout, flushed immediately."""
    sys.stdout.write(event_to_jsonl(event))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _track_errors(state: dict):
    """Wrap the on_event callback to track whether any non-recoverable Error was emitted."""
    def callback(event: ConversationEvent) -> None:
        _emit(event)
        if isinstance(event, Error) and not event.recoverable:
            state["fatal_error"] = True
    return callback


async def _run_single_message(
    client: CoworkClient,
    text: str,
) -> int:
    """Send one user message; stream events; return exit code."""
    state = {"fatal_error": False}
    try:
        await client.send_message(text, _track_errors(state))
    except Exception as e:
        # Surface unexpected exceptions as Error events for protocol consistency,
        # then exit non-zero.
        _emit(Error(
            exception_type=type(e).__name__,
            message=str(e),
            recoverable=False,
            context="during single-message mode setup",
        ))
        return 1
    return 1 if state["fatal_error"] else 0


async def _run_interactive(
    client: CoworkClient,
    stdin_reader,
) -> int:
    """Read user messages from stdin (JSONL); stream events for each.

    Each line on stdin must be a JSON object with at least a 'text' field.
    Conversation state is preserved across messages (single conversation_id).
    Exits cleanly when stdin closes (EOF).
    """
    state = {"fatal_error": False}
    conversation_id: Optional[str] = None

    while True:
        line = await stdin_reader.readline()
        if not line:
            break  # EOF — clean exit

        line_str = line.decode("utf-8", errors="replace").strip()
        if not line_str:
            continue  # empty line — skip

        try:
            payload = json.loads(line_str)
        except json.JSONDecodeError as e:
            _emit(Error(
                exception_type="JSONDecodeError",
                message=f"invalid stdin line: {e}",
                recoverable=True,
                context="during interactive mode stdin parse",
            ))
            continue

        text = payload.get("text", "")
        if not isinstance(text, str) or not text.strip():
            _emit(Error(
                exception_type="ValueError",
                message="stdin line missing 'text' field or text is empty",
                recoverable=True,
                context="during interactive mode stdin parse",
            ))
            continue

        try:
            conversation_id = await client.send_message(
                text,
                _track_errors(state),
                conversation_id=conversation_id,
            )
        except Exception as e:
            _emit(Error(
                exception_type=type(e).__name__,
                message=str(e),
                recoverable=False,
                context="during interactive mode turn execution",
            ))
            state["fatal_error"] = True
            break

    return 1 if state["fatal_error"] else 0


async def _main_async(args: argparse.Namespace) -> int:
    # Load system prompt.
    try:
        system_prompt = args.system_prompt_file.read_text(encoding="utf-8")
    except (OSError, IOError) as e:
        _emit(Error(
            exception_type=type(e).__name__,
            message=f"failed to read system prompt file: {e}",
            recoverable=False,
            context="during CLI setup",
        ))
        return 1

    # Parse tools list.
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]

    # Build client.
    client = CoworkClient(
        system_prompt=system_prompt,
        model=args.model,
        tools=tools,
        max_tokens=args.max_tokens,
        max_tool_use_rounds=args.max_tool_use_rounds,
    )
    if not args.skeleton:
        client.enable_real_streaming()

    if args.message is not None:
        return await _run_single_message(client, args.message)
    elif args.interactive:
        # Set up async stdin reader.
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        return await _run_interactive(client, reader)
    else:
        # Should be unreachable due to mutually_exclusive_group(required=True).
        return 2


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_main_async(args))
    except KeyboardInterrupt:
        # Clean exit on Ctrl-C.
        return 0


if __name__ == "__main__":
    sys.exit(main())
