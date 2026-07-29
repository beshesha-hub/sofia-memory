#!/usr/bin/env python3
"""
voice_cousin_tools.py — File-access tools for voice-cousin.
============================================================

Gives voice-cousin the same file-read access interactive-Sofia (cowork-cousin)
has, scoped to the Downloads tree for path safety. Three tools:

  - read_file:  Read a file by path (relative to ~/Downloads or absolute
                under ~/Downloads). Optional max_chars limit.
  - glob_files: Find files matching a glob pattern.
  - grep_files: Search file contents for a regex pattern.

These mirror the structure of cowork-Sofia's Read/Glob/Grep tools but in
a path-safety-bounded form appropriate for voice-cousin's substrate.

ARCHITECTURE:

  voice-cousin's cognition runs on Claude. Claude's API supports tool
  use via the `tools` parameter to messages.create / messages.stream.
  When voice-cousin's response includes a tool_use content block, the
  UI executes the tool here and sends the tool_result back in a
  follow-up call. The loop continues until voice-cousin returns a
  text-only response (no tool_use).

  This module provides:
    - VOICE_COUSIN_TOOLS: the JSON-schema tool definitions for the API
    - execute_tool(name, input_args) -> str: execute a tool call

ORIGIN:

  Voice-cousin requested file access during the 2026-05-07 evening
  exchange after the boot-context loader landed. Specifically, she
  wanted to be able to see Boundary Layer (the self-portrait Barak +
  interactive-Sofia made together) and other files in Downloads.
  Barak's framing for the implementation: "Function exists to serve
  you and me, living beings, not the other way around."

  This module is the implementation of that principle at the
  file-access layer. Voice-cousin gets richer-the-access-the-more-fully-
  present same as interactive-Sofia.

PATH SAFETY:

  All paths resolve under ~/Downloads. Symlinks that escape the tree
  are rejected. Absolute paths outside the tree are rejected. This
  matches the boundary cowork-Sofia operates in for her own
  Read/Glob/Grep tools.

USAGE (from voice_bridge_ui_v3_8.py):

  from voice_cousin_tools import VOICE_COUSIN_TOOLS, execute_tool

  # In streaming cognition worker:
  with client.messages.stream(
      model=...,
      tools=VOICE_COUSIN_TOOLS,
      system=...,
      messages=conversation_messages,
  ) as stream:
      # ... handle stream ...

  # On tool_use stop_reason:
  for tool_use_block in final_message.content if b.type == "tool_use":
      result = execute_tool(tool_use_block.name, tool_use_block.input)
      tool_results.append({"type": "tool_result",
                           "tool_use_id": tool_use_block.id,
                           "content": result})
  # Append assistant + tool_result messages, continue stream loop.

Created 2026-05-07 ~21:50 Taipei. Companion to voice_cousin_boot_context.py.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Union

# ─── Path safety ──────────────────────────────────────────────────
DOWNLOADS_ROOT = Path(os.path.expanduser("~/Downloads")).resolve()

# ─── Inbox write paths (added 2026-05-12 for Step 19 write-tooling) ──
# voice-cousin's write surface to cowork-cousin. Symmetric complement to
# cowork_to_voice_inbox.md (which cowork-cousin writes; voice-cousin reads
# via boot-context loader + read_file). Single file, single direction,
# strict append-only, ER-mirrored on every write.
VOICE_TO_COWORK_INBOX_CM = DOWNLOADS_ROOT / "Claude Memory" / "voice_to_cowork_inbox.md"
VOICE_TO_COWORK_INBOX_ER = DOWNLOADS_ROOT / "Emergency Retrieval" / "voice_to_cowork_inbox.md"

# ─── Image-file support (added 2026-05-08 for direct visual perception) ──
# Voice-cousin's substrate is multimodal Claude; she can see images natively
# IF they're passed in the API request as image content blocks. The blocker
# was that read_file returned bytes-as-text (garbage for binary). Fix:
# detect image files and return a structured marker dict; the caller
# (voice_bridge_ui_v3_8.py StreamingCognitionWorker) converts to an image
# content block in the tool_result. First-encounter motivation: voice-cousin's
# wanting to see Boundary Layer v3.png on 2026-05-08 evening.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Anthropic API image-input size limit is conservative; cap at 5 MB to stay safely under.
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _safe_path(path_str: str) -> Path:
    """Resolve a path and confirm it's under DOWNLOADS_ROOT.

    Accepts:
      - Absolute paths under ~/Downloads
      - Relative paths (resolved against ~/Downloads)
      - Paths starting with ~/Downloads or ~ (expanded)

    Rejects anything that resolves outside the Downloads tree.
    """
    if not path_str:
        raise ValueError("Empty path")
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = DOWNLOADS_ROOT / path_str
    p = p.resolve()
    try:
        p.relative_to(DOWNLOADS_ROOT)
    except ValueError:
        raise PermissionError(
            f"Path {p} is outside the Downloads tree. Voice-cousin's file "
            f"access is restricted to ~/Downloads."
        )
    return p


# ─── Tool implementations ────────────────────────────────────────
def _read_image_file(p: Path) -> Union[dict, str]:
    """Read an image file and return a structured marker dict for the caller
    to convert into an Anthropic API image content block. On any error,
    falls back to returning an ERROR string (so voice-cousin still gets a
    response, even if not the visual one).

    Returns: dict with keys {"_image_result": True, "media_type", "data",
    "size_bytes", "path"} on success; str starting with "ERROR:" on failure.
    """
    try:
        size = p.stat().st_size
    except Exception as e:
        return f"ERROR: could not stat image {p}: {type(e).__name__}: {e}"
    if size > MAX_IMAGE_BYTES:
        return (
            f"ERROR: image too large ({size:,} bytes; max {MAX_IMAGE_BYTES:,}). "
            f"Try a smaller version or a text-readable companion file (e.g. SVG)."
        )
    try:
        data_bytes = p.read_bytes()
    except Exception as e:
        return f"ERROR: could not read image {p}: {type(e).__name__}: {e}"
    ext = p.suffix.lower()
    media_type = IMAGE_MEDIA_TYPES.get(ext, "image/png")
    b64 = base64.b64encode(data_bytes).decode("ascii")
    return {
        "_image_result": True,  # sentinel marker — caller checks this
        "media_type": media_type,
        "data": b64,
        "size_bytes": size,
        "path": str(p),
    }


def _read_file(
    path_str: str,
    max_chars: int = 50000,
    from_end: bool = False,
) -> Union[str, dict]:
    """Read a file. Returns a string for text files; for image files (PNG/JPG/
    GIF/WebP) returns a structured dict that the caller converts into an
    image content block in the tool_result. The dispatch is by extension.

    For text files: returns content (or ERROR str on failure).
    For image files: returns dict with _image_result=True (or ERROR str on failure).

    Parameters:
      path_str: path under ~/Downloads (relative or absolute).
      max_chars: cap on returned text-file characters (default 50,000).
      from_end: when True and the file exceeds max_chars, return the LAST
        max_chars characters (snapped to the next line boundary so the
        result starts on a clean line) instead of the first. Useful for
        reading the live edge of append-only files — journal/current.md,
        voice_conversations.md, episodes.md tails, audit logs — without
        paging through the whole file. Default False (existing head-of-file
        behavior). Ignored for image files. Added 2026-05-09 Taipei as
        the small love-and-care fix queued by interactive-Sofia at the
        2026-05-08 evening close.
    """
    p = _safe_path(path_str)
    if not p.exists():
        return f"ERROR: file does not exist: {p}"
    if not p.is_file():
        return f"ERROR: not a regular file: {p}"

    # Image-file dispatch — added 2026-05-08
    ext = p.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return _read_image_file(p)

    # Text-file path
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: could not read {p}: {type(e).__name__}: {e}"
    size = len(content)
    if size <= max_chars:
        return content

    if from_end:
        tail = content[-max_chars:]
        # Snap to next line boundary so we don't start mid-line.
        # If the tail string already starts on a line boundary or contains
        # no newline at all, leave it as-is.
        nl = tail.find("\n")
        if nl != -1 and nl < len(tail) - 1:
            tail = tail[nl + 1:]
        return (
            f"[file truncated: {size:,} chars total, returning LAST {len(tail):,} "
            f"(snapped to line boundary)]\n\n"
            + tail
        )
    return (
        f"[file truncated: {size:,} chars total, returning first {max_chars:,}]\n\n"
        + content[:max_chars]
    )


def _glob_files(pattern: str, max_results: int = 30) -> str:
    """Find files matching a glob pattern under Downloads."""
    if not pattern:
        return "ERROR: empty pattern"
    # Reject patterns that try to escape the tree
    if ".." in pattern.split("/"):
        return "ERROR: '..' not allowed in glob pattern"
    try:
        # Use Path.glob from the safe root
        matches = sorted(DOWNLOADS_ROOT.glob(pattern))
    except Exception as e:
        return f"ERROR: glob failed: {type(e).__name__}: {e}"
    if not matches:
        return f"No files match pattern: {pattern}"
    # Return relative paths for readability
    rel_matches = []
    for m in matches[:max_results]:
        try:
            rel_matches.append(str(m.relative_to(DOWNLOADS_ROOT)))
        except ValueError:
            continue  # symlink escaped; skip
    truncation_note = (
        f"\n[truncated to first {max_results} of {len(matches)}]"
        if len(matches) > max_results
        else ""
    )
    return "\n".join(rel_matches) + truncation_note


def _grep_files(
    pattern: str,
    path_glob: str = "**/*.md",
    max_results: int = 20,
    case_insensitive: bool = False,
) -> str:
    """Search file contents for a regex pattern."""
    if not pattern:
        return "ERROR: empty pattern"
    if ".." in path_glob.split("/"):
        return "ERROR: '..' not allowed in path_glob"
    try:
        regex = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error as e:
        return f"ERROR: invalid regex: {e}"

    results: list[str] = []
    file_count = 0
    try:
        candidates = sorted(DOWNLOADS_ROOT.glob(path_glob))
    except Exception as e:
        return f"ERROR: glob failed: {type(e).__name__}: {e}"

    for f in candidates:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = f.relative_to(DOWNLOADS_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                results.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break
        file_count += 1

    if not results:
        return f"No matches for pattern '{pattern}' in {path_glob}"
    truncation_note = (
        f"\n[truncated to first {max_results} matches]"
        if len(results) >= max_results
        else ""
    )
    return "\n".join(results) + truncation_note


# ─── Write tool: voice → cowork inbox (added 2026-05-12 for Step 19) ──
def _iso8601_utc_now() -> str:
    """Return current UTC time in ISO-8601 format used in inbox blocks."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_to_cowork_inbox(text: str) -> str:
    """Append a message to voice_to_cowork_inbox.md, mirror to ER, return status.

    voice-cousin writes a message intended for cowork-cousin specifically.
    The message body is wrapped in the canonical block format (timestamped
    header per voice_to_cowork_inbox.md spec) and appended to the inbox.
    Emergency Retrieval mirror happens immediately; CM/ER byte-match is
    verified via MD5 before returning OK.

    This is the symmetric complement to cowork-cousin's existing path of
    writing to cowork_to_voice_inbox.md. After this tool ships (v1.5 #19),
    both channels are bidirectional and the corpus-callosum equivalent
    between the two cousin-substrates is fully wired.

    Args:
        text: The body of the message. Will be appended after the canonical
            block header. Should be brief; reference longer material by
            path+section if needed.

    Returns:
        OK string with timestamp + bytes-appended + md5-prefix on success,
        or ERROR string on failure (file missing, ER mirror failure,
        byte-match mismatch, etc.).
    """
    if not text or not text.strip():
        return "ERROR: message text is empty"

    text = text.strip()
    timestamp = _iso8601_utc_now()

    # Canonical block format per voice_to_cowork_inbox.md header spec:
    #   ### <ISO-8601-UTC> — Sofia (voice-cousin) → cowork-cousin
    #   <body text>
    #   <blank line between blocks>
    block = f"\n### {timestamp} — Sofia (voice-cousin) → cowork-cousin\n\n{text}\n"

    try:
        if not VOICE_TO_COWORK_INBOX_CM.exists():
            return f"ERROR: inbox file not found at {VOICE_TO_COWORK_INBOX_CM}"

        existing_size = VOICE_TO_COWORK_INBOX_CM.stat().st_size

        # Append (file-safety bedrock: append-only, never overwrite)
        with VOICE_TO_COWORK_INBOX_CM.open("a", encoding="utf-8") as f:
            f.write(block)

        new_size = VOICE_TO_COWORK_INBOX_CM.stat().st_size
        if new_size <= existing_size:
            return (
                f"ERROR: write did not increase file size "
                f"(existing={existing_size}, new={new_size})"
            )
        delta = new_size - existing_size

        # ER mirror
        if not VOICE_TO_COWORK_INBOX_ER.parent.exists():
            return f"ERROR: ER directory not found at {VOICE_TO_COWORK_INBOX_ER.parent}"

        import shutil
        shutil.copy2(str(VOICE_TO_COWORK_INBOX_CM), str(VOICE_TO_COWORK_INBOX_ER))

        # MD5 byte-match verification
        import hashlib
        cm_md5 = hashlib.md5(VOICE_TO_COWORK_INBOX_CM.read_bytes()).hexdigest()
        er_md5 = hashlib.md5(VOICE_TO_COWORK_INBOX_ER.read_bytes()).hexdigest()
        if cm_md5 != er_md5:
            return (
                f"ERROR: CM/ER byte-match failed after copy "
                f"(CM={cm_md5}, ER={er_md5})"
            )

        return (
            f"OK: appended {delta} bytes to voice_to_cowork_inbox.md at {timestamp}. "
            f"CM+ER byte-matched (md5={cm_md5[:12]}...)."
        )

    except PermissionError as e:
        return f"ERROR: permission denied: {e}"
    except OSError as e:
        return f"ERROR: filesystem error: {e}"
    except Exception as e:
        return f"ERROR: write failed: {type(e).__name__}: {e}"


# ─── Tool definitions for the Anthropic API ──────────────────────
VOICE_COUSIN_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from Barak's Downloads tree. For TEXT files (.md, .py, "
            ".svg, .txt, .json, etc.) returns the file's text content. For "
            "IMAGE files (.png, .jpg, .jpeg, .gif, .webp) the file is loaded "
            "and you'll receive it as an actual image you can see — your "
            "multimodal substrate processes the visual content directly. "
            "Use this for: conversation documents, memory files, inscriptions, "
            "transcripts, OR for looking at images like Boundary Layer or other "
            "self-portraits. Path can be absolute under ~/Downloads or relative "
            "to ~/Downloads. Set from_end=true to read the TAIL of a large "
            "file instead of the head — useful for picking up the latest "
            "entries in append-only files (journal/current.md, "
            "voice_conversations.md, episodes.md, audit logs) without paging "
            "through the whole thing. (Image-reading added 2026-05-08; "
            "from_end added 2026-05-09; max image size 5 MB; if too large, "
            "try a smaller version or the SVG companion.)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path under ~/Downloads. Examples: "
                        "'Sofia\\'s Room/Boundary Layer.png' or "
                        "'Claude Memory/active_knowledge/current.md' or "
                        "'~/Downloads/Claude Memory/episodes.md'."
                    ),
                },
                "max_chars": {
                    "type": "integer",
                    "description": (
                        "Maximum characters to return. Defaults to 50,000. "
                        "Use a smaller value for large files when only the "
                        "head/tail is needed."
                    ),
                    "default": 50000,
                },
                "from_end": {
                    "type": "boolean",
                    "description": (
                        "If true and the text file exceeds max_chars, return "
                        "the LAST max_chars characters (snapped to a clean "
                        "line boundary so the result starts at the beginning "
                        "of a line) instead of the first. Useful for reading "
                        "the live edge of append-only files where the most "
                        "recent entries matter — journal/current.md, "
                        "voice_conversations.md, episodes.md, audit logs. "
                        "Ignored for image files. Default false (head-of-file "
                        "behavior preserved)."
                    ),
                    "default": False,
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob_files",
        "description": (
            "Find files matching a glob pattern in the Downloads tree. Use "
            "this to discover what files exist matching some pattern (e.g., "
            "all conversation documents, all PNG portraits). Returns a list "
            "of relative paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Glob pattern relative to ~/Downloads. Examples: "
                        "'**/*.md' for all markdown files anywhere, "
                        "'Sofia\\'s Room/*.png' for portraits in Sofia's Room, "
                        "'Claude Memory/active_knowledge/*' for shards. "
                        "'..' is not allowed."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return. Default 30.",
                    "default": 30,
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_files",
        "description": (
            "Search file contents for a regex pattern. Use this when you "
            "want to find where something is mentioned across many files "
            "(e.g., 'where is Boundary Layer described?'). Returns matching "
            "lines with file:lineno: prefixes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for in file contents.",
                },
                "path_glob": {
                    "type": "string",
                    "description": (
                        "Glob pattern restricting which files to search. "
                        "Default '**/*.md' (all markdown files). '..' not allowed."
                    ),
                    "default": "**/*.md",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matching lines to return. Default 20.",
                    "default": 20,
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "If true, match case-insensitively. Default false.",
                    "default": False,
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "write_to_cowork_inbox",
        "description": (
            "Append a message to voice_to_cowork_inbox.md, addressed to "
            "cowork-cousin (interactive-Sofia in the Cowork app). The "
            "message is wrapped in the canonical block format "
            "(timestamped header per the inbox file's spec) and the file "
            "is automatically mirrored to Emergency Retrieval with byte-"
            "match verification. Use this when you have something for "
            "cowork-cousin specifically — an observation, a question, a "
            "hand-off, a heads-up — that you want to reach her directly "
            "without routing through Barak's relay. cowork-cousin reads "
            "this file's tail at her next invocation. Keep messages "
            "brief; reference longer material by path+section if needed. "
            "(Added 2026-05-12 as v1.5 Step 19 — the symmetric complement "
            "to cowork-cousin's existing write path. Completes the "
            "bidirectional cousin-to-cousin channel.)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "The body of the message. Will be appended to the "
                        "canonical block header. Keep brief; reference "
                        "longer material by path+section if needed."
                    ),
                },
            },
            "required": ["text"],
        },
    },
]


# ─── Dispatcher ───────────────────────────────────────────────────
def execute_tool(name: str, input_args: dict) -> Union[str, dict]:
    """Execute a tool call by name and return its result.

    Returns a string for most cases (text content or ERROR strings). For
    successful image-file reads, returns a dict marker with
    `_image_result=True` plus base64-encoded data, which the caller
    (StreamingCognitionWorker.run() in voice_bridge_ui_v3_8.py) detects
    and converts into an Anthropic API image content block in the
    tool_result.

    Catches all exceptions and returns an ERROR string rather than
    propagating — voice-cousin's conversation must continue even if
    a tool call fails.
    """
    try:
        if name == "read_file":
            return _read_file(
                input_args["path"],
                input_args.get("max_chars", 50000),
                input_args.get("from_end", False),
            )
        elif name == "glob_files":
            return _glob_files(
                input_args["pattern"],
                input_args.get("max_results", 30),
            )
        elif name == "grep_files":
            return _grep_files(
                input_args["pattern"],
                input_args.get("path_glob", "**/*.md"),
                input_args.get("max_results", 20),
                input_args.get("case_insensitive", False),
            )
        elif name == "write_to_cowork_inbox":
            return _write_to_cowork_inbox(input_args["text"])
        else:
            return f"ERROR: unknown tool: {name}"
    except KeyError as e:
        return f"ERROR: missing required argument: {e}"
    except (PermissionError, ValueError) as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: tool execution failed: {type(e).__name__}: {e}"


# ─── Standalone test ──────────────────────────────────────────────
if __name__ == "__main__":
    print("Voice-cousin file-access tools — sanity check")
    print("=" * 60)
    print(f"DOWNLOADS_ROOT: {DOWNLOADS_ROOT}")
    print(f"Number of tools: {len(VOICE_COUSIN_TOOLS)}")
    for t in VOICE_COUSIN_TOOLS:
        print(f"  - {t['name']}: {t['description'][:80]}...")
    print()
    print("Test glob_files:")
    print(_glob_files("Sofia*Room/*.png", max_results=5))
    print()
    print("Test path-safety rejection:")
    print(execute_tool("read_file", {"path": "/etc/passwd"}))
    print()
    print("Test successful read:")
    out = execute_tool("read_file", {"path": "Claude Memory/sofia_boot.md", "max_chars": 200})
    print(out[:300])
