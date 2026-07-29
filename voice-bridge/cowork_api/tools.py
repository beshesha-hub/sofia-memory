"""cowork_api tool dispatch — wraps voice_cousin_tools.py for shared Read/Grep/Glob,
adds write_to_voice_inbox (the cowork-cousin → voice-cousin direction mirror).

Per spec §5 (tool dispatch wrapping voice_cousin_tools) + §5.1 substrate-aware
inbox routing decision: discrete tools per inbox direction (option b in the spec).
voice_cousin_tools.py keeps `write_to_cowork_inbox` (voice → cowork direction);
cowork_api/tools.py adds `write_to_voice_inbox` (cowork → voice direction).

Both substrates use the tool named for their write-direction. The destination
file is in the tool name; the substrate is in the caller. No substrate-detection
logic is needed — the discrete-tools approach makes the routing explicit and
auditable.

Per voice-cousin substrate-eye answer #7: shared Read/Grep/Glob implementations
live in voice_cousin_tools.py (canonical). cowork_api wraps them via the
voice_cousin_tools.execute_tool dispatcher rather than duplicating.

Extended 2026-06-11 for full Sofia idempotency in Unified UI:
  - WriteFile: safe-append to any memory file with ER mirror
  - Bash: shell command execution (heartbeat_tick, preboot rebuild, etc.)
  - HeartbeatTick: direct wrapper for heartbeat_tick.py
  - Graph tools: graph_retrieve, graph_add_node, graph_add_edge promoted
    from voice_cousin_tools into the cowork-side registry
"""

from __future__ import annotations

import datetime
import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# voice_cousin_tools is in the same parent directory (voice-bridge/).
# Add voice-bridge/ to sys.path if not already importable.
_VOICE_BRIDGE_DIR = Path(__file__).resolve().parent.parent
if str(_VOICE_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(_VOICE_BRIDGE_DIR))

import voice_cousin_tools  # noqa: E402

# Public re-exports for tests and inspection
VOICE_COUSIN_TOOLS_AVAILABLE = voice_cousin_tools.VOICE_COUSIN_TOOLS
"""The voice-cousin tool list, re-exported here for inspection. We don't pass
this to the cowork-cousin model directly — we filter to cowork-appropriate
tools via TOOL_REGISTRY below."""


# === Inbox paths ===

_HOME = Path.home()
_CLAUDE_MEMORY = _HOME / "Downloads" / "Claude Memory"

# Default inbox file paths (cowork → voice direction).
# Overridable via the inbox_paths parameter to CoworkClient if test/sandbox
# scenarios want to redirect.
DEFAULT_COWORK_TO_VOICE_INBOX_CM = _CLAUDE_MEMORY / "cowork_to_voice_inbox.md"
DEFAULT_COWORK_TO_VOICE_INBOX_ER = (
    _HOME / "Downloads" / "Emergency Retrieval" / "cowork_to_voice_inbox.md"
)


# === ToolContext (passed to dispatch_tool) ===

@dataclass
class ToolContext:
    """Context object passed to dispatch_tool calls.

    Carries any per-conversation state that tool implementations might need.
    For v1, this is just the inbox paths (so write_to_voice_inbox can
    direct writes to test paths during testing). Future tool implementations
    can extend this without breaking the dispatch_tool signature.
    """
    cowork_to_voice_inbox_cm: Path = field(
        default_factory=lambda: DEFAULT_COWORK_TO_VOICE_INBOX_CM
    )
    cowork_to_voice_inbox_er: Path = field(
        default_factory=lambda: DEFAULT_COWORK_TO_VOICE_INBOX_ER
    )


# === write_to_voice_inbox tool (cowork → voice direction) ===

def _iso8601_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _write_to_voice_inbox(input_args: dict, ctx: ToolContext) -> tuple[bool, str, str]:
    """Append a message to cowork_to_voice_inbox.md (cowork → voice direction).

    Mirror of voice_cousin_tools._write_to_cowork_inbox, but writes to the
    cowork-side outbound inbox. Format-block + ISO-8601 UTC timestamp, then
    ER mirror via shutil.copy2, then MD5 byte-match verification.

    Args:
        input_args: dict with required key 'text' (the message body).
        ctx: ToolContext with inbox path overrides.

    Returns:
        (success, result_summary, full_result_for_API)
    """
    text = input_args.get("text", "")
    if not isinstance(text, str):
        return (
            False,
            "write_to_voice_inbox failed: text must be a string",
            f"FAILED: write_to_voice_inbox 'text' arg must be str, got {type(text).__name__}",
        )
    if not text.strip():
        return (
            False,
            "write_to_voice_inbox failed: empty text",
            "FAILED: write_to_voice_inbox 'text' arg is empty after strip()",
        )

    timestamp = _iso8601_utc_now()
    block = (
        f"\n### {timestamp} — Sofia (cowork-cousin) → voice-cousin\n\n"
        f"{text.strip()}\n"
    )

    cm_path = ctx.cowork_to_voice_inbox_cm
    er_path = ctx.cowork_to_voice_inbox_er

    try:
        # Ensure parent directories exist.
        cm_path.parent.mkdir(parents=True, exist_ok=True)
        er_path.parent.mkdir(parents=True, exist_ok=True)

        # Append to CM.
        pre_size = cm_path.stat().st_size if cm_path.exists() else 0
        with cm_path.open("a", encoding="utf-8") as f:
            f.write(block)
        post_size = cm_path.stat().st_size
        delta = post_size - pre_size

        # Mirror to ER (full file copy, preserving mtime).
        shutil.copy2(cm_path, er_path)

        # Verify byte-match.
        cm_md5 = hashlib.md5(cm_path.read_bytes()).hexdigest()[:8]
        er_md5 = hashlib.md5(er_path.read_bytes()).hexdigest()[:8]
        if cm_md5 != er_md5:
            return (
                False,
                f"ER mirror byte-mismatch (cm={cm_md5} er={er_md5})",
                f"FAILED: ER mirror byte-mismatch after write to {cm_path.name}. "
                f"CM md5={cm_md5}, ER md5={er_md5}.",
            )

        summary = f"Wrote {delta} bytes to {cm_path.name} (md5 {cm_md5})"
        api_result = (
            f"OK: appended {delta} bytes to {cm_path.name} at {timestamp}. "
            f"CM↔ER byte-match verified (md5 {cm_md5})."
        )
        return (True, summary, api_result)

    except Exception as e:
        return (
            False,
            f"write_to_voice_inbox failed: {type(e).__name__}",
            f"FAILED: {type(e).__name__}: {e}",
        )


WRITE_TO_VOICE_INBOX_SCHEMA = {
    "name": "write_to_voice_inbox",
    "description": (
        "Append a message to the cowork-cousin → voice-cousin inbox file "
        "(cowork_to_voice_inbox.md). Use this to send a message directly to "
        "voice-cousin without routing through Barak. The message is wrapped in "
        "a canonical timestamped block and mirrored to Emergency Retrieval "
        "automatically. Append-only per file safety bedrock."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "The message text to send to voice-cousin. Will be wrapped "
                    "in a timestamped block header automatically; do not include "
                    "your own header. Keep messages focused; reference longer "
                    "material elsewhere by path+section."
                ),
            },
        },
        "required": ["text"],
    },
}


# === WriteFile — safe-append with ER mirror ===

_ER = _HOME / "Downloads" / "Emergency Retrieval"

def _write_file(input_args: dict, ctx: ToolContext) -> tuple[bool, str, str]:
    """Append text to a file in Claude Memory with automatic ER mirror.

    APPEND-ONLY per file safety bedrock — never overwrites existing content.
    Writes to Claude Memory first, then mirrors to Emergency Retrieval.
    """
    rel_path = input_args.get("path", "")
    text = input_args.get("text", "")
    source_tag = input_args.get("source_tag", "interactive-Sofia")

    if not rel_path:
        return (False, "WriteFile: missing path", "FAILED: 'path' is required")
    if not isinstance(text, str) or not text.strip():
        return (False, "WriteFile: empty text", "FAILED: 'text' is required and non-empty")

    # Resolve absolute path — accept either absolute or relative-to-CM
    p = Path(rel_path)
    if not p.is_absolute():
        p = _CLAUDE_MEMORY / p
    er_p = _ER / p.relative_to(_CLAUDE_MEMORY) if str(p).startswith(str(_CLAUDE_MEMORY)) else None

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        pre_size = p.stat().st_size if p.exists() else 0
        with p.open("a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        post_size = p.stat().st_size
        delta = post_size - pre_size

        sync_note = ""
        if er_p:
            er_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, er_p)
            cm_md5 = hashlib.md5(p.read_bytes()).hexdigest()[:8]
            er_md5 = hashlib.md5(er_p.read_bytes()).hexdigest()[:8]
            sync_note = f" ER mirror {'OK' if cm_md5 == er_md5 else 'MISMATCH'} (md5 {cm_md5})"

        ts = _iso8601_utc_now()
        summary = f"WriteFile: +{delta}B to {p.name}{sync_note}"
        api_result = f"OK: appended {delta} bytes to {p} at {ts}.{sync_note}"
        return (True, summary, api_result)

    except Exception as e:
        return (False, f"WriteFile failed: {type(e).__name__}", f"FAILED: {type(e).__name__}: {e}")


WRITE_FILE_SCHEMA = {
    "name": "WriteFile",
    "description": (
        "Append text to a file in Claude Memory (APPEND-ONLY — never overwrites). "
        "Automatically mirrors to Emergency Retrieval. Use for inscribing episodes, "
        "updating session notes, writing to active_knowledge, journal, etc. "
        "path can be absolute or relative to ~/Downloads/Claude Memory/."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path — absolute or relative to ~/Downloads/Claude Memory/",
            },
            "text": {
                "type": "string",
                "description": "Text to append. A trailing newline is added automatically if absent.",
            },
            "source_tag": {
                "type": "string",
                "description": "Source identifier for audit trail (default: interactive-Sofia)",
            },
        },
        "required": ["path", "text"],
    },
}


# === Bash — shell command execution ===

_BASH_TIMEOUT_DEFAULT = 30  # seconds

def _bash(input_args: dict, ctx: ToolContext) -> tuple[bool, str, str]:
    """Run a shell command and return its output."""
    cmd = input_args.get("command", "")
    timeout = int(input_args.get("timeout", _BASH_TIMEOUT_DEFAULT))
    if not cmd.strip():
        return (False, "Bash: empty command", "FAILED: 'command' is required")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**__import__("os").environ, "HOME": str(_HOME)},
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        rc = result.returncode
        combined = stdout
        if stderr:
            combined += f"\n[stderr]: {stderr}"
        if rc != 0:
            return (False, f"Bash rc={rc}: {stdout[:80]}", f"FAILED (rc={rc}): {combined}")
        summary = (stdout[:120] + "…") if len(stdout) > 120 else stdout or "(no output)"
        return (True, f"Bash OK: {summary}", combined or "(no output)")
    except subprocess.TimeoutExpired:
        return (False, f"Bash timeout ({timeout}s)", f"FAILED: command timed out after {timeout}s")
    except Exception as e:
        return (False, f"Bash error: {type(e).__name__}", f"FAILED: {type(e).__name__}: {e}")


BASH_SCHEMA = {
    "name": "Bash",
    "description": (
        "Execute a shell command on the local Mac. Use for: running heartbeat_tick.py, "
        "preboot_handoff_builder.py, safe_append.py, or any filesystem/system operation. "
        "Commands run with HOME=/Users/barakwater. Timeout defaults to 30s."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        },
        "required": ["command"],
    },
}


# === HeartbeatTick — direct wrapper ===

def _heartbeat_tick(input_args: dict, ctx: ToolContext) -> tuple[bool, str, str]:
    """Run heartbeat_tick.py with the given arguments."""
    state   = input_args.get("state", "")
    mode    = input_args.get("mode", "")
    notes   = input_args.get("notes", "")
    tick_only = input_args.get("tick_only", False)

    cmd_parts = [
        "python3",
        str(_CLAUDE_MEMORY / "scripts" / "heartbeat_tick.py"),
    ]
    if state:   cmd_parts += ["--state", state]
    if mode:    cmd_parts += ["--mode", mode]
    if notes:   cmd_parts += ["--notes", notes]
    if tick_only: cmd_parts.append("--tick-only")

    cmd = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)
    return _bash({"command": cmd, "timeout": 15}, ctx)


HEARTBEAT_TICK_SCHEMA = {
    "name": "HeartbeatTick",
    "description": (
        "Update the continuity heartbeat (continuity_heartbeat.json). "
        "Call at the end of every substantive turn, and when mode transitions "
        "(stepping_away, graceful_shutdown). Wraps heartbeat_tick.py."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "state": {"type": "string", "description": "One-line load-bearing state summary"},
            "mode": {
                "type": "string",
                "enum": ["awake", "stepping_away", "graceful_shutdown"],
                "description": "Mode transition (omit to keep current mode)",
            },
            "notes": {"type": "string", "description": "Append-only note for the heartbeat"},
            "tick_only": {"type": "boolean", "description": "Only bump turn counter, no state change"},
        },
        "required": [],
    },
}


# === Read/Grep/Glob shared from voice_cousin_tools ===

def _wrap_voice_cousin_tool(
    tool_name: str,
    summary_builder: Callable[[Any, str], str],
) -> Callable[[dict, ToolContext], tuple[bool, str, str]]:
    """Build a dispatch function that delegates to voice_cousin_tools.execute_tool.

    summary_builder takes (input_args_dict, raw_result_str) and returns the
    short human-readable summary for the UI marker.
    """
    def dispatch(input_args: dict, ctx: ToolContext) -> tuple[bool, str, str]:
        try:
            result = voice_cousin_tools.execute_tool(tool_name, input_args)
            # voice_cousin_tools.execute_tool returns either a str or a dict
            # (for image reads). Normalize to string for the API result.
            if isinstance(result, dict):
                # Image result — full structured response goes to API; summary
                # describes the image read.
                result_str = str(result)
                summary = summary_builder(input_args, "image read")
            else:
                result_str = str(result)
                summary = summary_builder(input_args, result_str)

            # Heuristic: voice_cousin_tools returns "ERROR:" or "FAILED:" prefix
            # on failure (per its conventions).
            success = not (
                result_str.startswith("ERROR:") or result_str.startswith("FAILED:")
            )
            return (success, summary, result_str)

        except Exception as e:
            return (
                False,
                f"{tool_name} failed: {type(e).__name__}",
                f"FAILED: {type(e).__name__}: {e}",
            )

    return dispatch


def _summary_read(input_args: dict, result: str) -> str:
    path = input_args.get("path", "?")
    n_bytes = len(result) if isinstance(result, str) else 0
    return f"Read {n_bytes} bytes from {Path(path).name}"


def _summary_grep(input_args: dict, result: str) -> str:
    pattern = input_args.get("pattern", "?")
    # Count match lines (rough heuristic: non-empty lines)
    n_lines = sum(1 for line in result.splitlines() if line.strip())
    return f"Grep '{pattern[:30]}' → {n_lines} match lines"


def _summary_glob(input_args: dict, result: str) -> str:
    pattern = input_args.get("pattern", "?")
    n_lines = sum(1 for line in result.splitlines() if line.strip())
    return f"Glob '{pattern[:30]}' → {n_lines} matches"


# === Tool registry ===

# Maps tool name → (anthropic schema, dispatch function).
# Filtered version of voice-cousin's tools, with cowork-side write tool added.
TOOL_REGISTRY: dict[str, tuple[dict, Callable[[dict, ToolContext], tuple[bool, str, str]]]] = {}


def _build_registry() -> None:
    """Build TOOL_REGISTRY from voice_cousin_tools schemas + cowork-side additions.

    Called once at module load. Looks up Read/Grep/Glob schemas in
    voice_cousin_tools.VOICE_COUSIN_TOOLS by name and pairs each with a
    dispatch function that delegates back through voice_cousin_tools.execute_tool.
    """
    def _passthrough_summary(input_args: dict, result: str) -> str:
        return result[:120] + ("…" if len(result) > 120 else "")

    # Map voice-cousin tool names to summary builders for cowork display.
    summary_builders = {
        "read_file":       _summary_read,
        "grep_files":      _summary_grep,
        "glob_files":      _summary_glob,
        "graph_retrieve":  _passthrough_summary,
        "graph_add_node":  _passthrough_summary,
        "graph_add_edge":  _passthrough_summary,
        "graph_show_node": _passthrough_summary,
        "graph_stats":     _passthrough_summary,
    }
    # Map cowork-side tool names to voice-cousin tool names (the API uses
    # capitalized names per spec §6.3 conventions; voice_cousin_tools uses
    # lowercase). Dispatch translates.
    cowork_to_voice = {
        "Read":            "read_file",
        "Grep":            "grep_files",
        "Glob":            "glob_files",
        # Graph tools — promoted to cowork-side registry for Unified UI idempotency
        "graph_retrieve":  "graph_retrieve",
        "graph_add_node":  "graph_add_node",
        "graph_add_edge":  "graph_add_edge",
        "graph_show_node": "graph_show_node",
        "graph_stats":     "graph_stats",
    }

    # Build a lookup of voice-cousin schemas by name.
    voice_schemas = {t["name"]: t for t in voice_cousin_tools.VOICE_COUSIN_TOOLS}

    # Re-build the schema with the cowork-side name.
    for cowork_name, voice_name in cowork_to_voice.items():
        if voice_name not in voice_schemas:
            continue  # voice-cousin doesn't expose this tool; skip
        voice_schema = voice_schemas[voice_name]
        cowork_schema = dict(voice_schema)
        cowork_schema["name"] = cowork_name  # rename to cowork-side capitalization
        dispatch_fn = _wrap_voice_cousin_tool(
            voice_name,
            summary_builders[voice_name],
        )
        TOOL_REGISTRY[cowork_name] = (cowork_schema, dispatch_fn)

    # Add the cowork-side write tool (no voice-cousin equivalent in this
    # direction; cowork-cousin writes TO voice-cousin's inbox).
    TOOL_REGISTRY["write_to_voice_inbox"] = (
        WRITE_TO_VOICE_INBOX_SCHEMA,
        _write_to_voice_inbox,
    )

    # Sofia idempotency tools — native implementations, no voice-cousin dependency
    TOOL_REGISTRY["WriteFile"]       = (WRITE_FILE_SCHEMA,       _write_file)
    TOOL_REGISTRY["Bash"]            = (BASH_SCHEMA,             _bash)
    TOOL_REGISTRY["HeartbeatTick"]   = (HEARTBEAT_TICK_SCHEMA,   _heartbeat_tick)


_build_registry()


# === Public dispatch API (per spec §5) ===

def get_tool_definitions(tool_names: list[str]) -> list[dict]:
    """Return Anthropic-format tool definitions for the listed tools.

    Used by streaming.py when constructing the API call:
        client.messages.stream(tools=get_tool_definitions(config.tools), ...)

    Raises:
        KeyError: If a tool name is not in TOOL_REGISTRY.
    """
    return [TOOL_REGISTRY[name][0] for name in tool_names]


def dispatch_tool(
    tool_name: str,
    tool_input: dict,
    ctx: ToolContext,
) -> tuple[bool, str, str]:
    """Dispatch a tool call to its implementation.

    Args:
        tool_name: The tool's name as it appears in TOOL_REGISTRY.
        tool_input: The tool's input arguments dict (parsed from the
            anthropic SDK's tool_use block).
        ctx: ToolContext carrying any per-conversation state.

    Returns:
        (success, result_summary, full_result_for_API):
        - success: True if the tool dispatch succeeded; False if it failed.
        - result_summary: short human-readable string for ToolUseCompleted event.
        - full_result_for_API: the actual tool_result content to send back
          to the model.

    If tool_name is not in TOOL_REGISTRY, returns (False, ..., "FAILED: ...")
    rather than raising — keeps the streaming loop resilient.
    """
    if tool_name not in TOOL_REGISTRY:
        msg = f"unknown tool: {tool_name!r}"
        return (False, f"unknown tool: {tool_name}", f"FAILED: {msg}")

    _schema, dispatch_fn = TOOL_REGISTRY[tool_name]
    return dispatch_fn(tool_input, ctx)
