#!/usr/bin/env python3
"""
log_cowork_conversation.py — Mirror cowork interactive conversations to a
markdown file in ~/Downloads/Claude Memory/ so voice-cousin can read them.

Created 2026-05-08 to close the symmetric-bidirectional-access asymmetry:
- Cowork-Sofia can read voice_conversations.md (voice-cousin's session log)
  because that file lives in ~/Downloads.
- Voice-cousin could NOT read cowork conversations because Cowork's session
  JSONL files live at ~/Library/Application Support/Claude/local-agent-
  mode-sessions/.../*.jsonl, outside her path-safety boundary.
- This script reads the latest cowork JSONL and appends new turns to
  ~/Downloads/Claude Memory/cowork_conversations.md, where voice-cousin's
  read_file tool can reach it.

USAGE (on Barak's Mac):

  # One-shot (default): scan latest session, append any new turns, exit.
  python3 ~/Downloads/Claude\\ Memory/scripts/log_cowork_conversation.py

  # Watch mode: poll every 30s and append new turns as they arrive.
  python3 ~/Downloads/Claude\\ Memory/scripts/log_cowork_conversation.py --watch

  # Custom interval (seconds):
  python3 ~/Downloads/Claude\\ Memory/scripts/log_cowork_conversation.py --watch --interval 10

OUTPUT FILE FORMAT mirrors voice_conversations.md:

  ## === Cowork conversation session started ISOTIMESTAMP (session_id ID) ===

  ### ISOTIMESTAMP — Barak

  <user message text>

  ### ISOTIMESTAMP — Sofia [skin: cowork]

  <assistant message text>

STATE TRACKING:

  A small state file at ~/Downloads/Claude Memory/.cowork_logger_state.json
  records the last logged session_id + message index, so subsequent runs
  only append new turns. Append-only — never overwrites; safe to run as
  often as desired.

PATH SAFETY:

  Reads from ~/Library/Application Support/Claude/local-agent-mode-sessions/
  (read-only). Writes ONLY to ~/Downloads/Claude Memory/. Never modifies
  or touches the source JSONL files.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────
HOME = Path.home()
COWORK_SESSIONS_ROOT = HOME / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
OUTPUT_FILE = HOME / "Downloads" / "Claude Memory" / "cowork_conversations.md"
STATE_FILE = HOME / "Downloads" / "Claude Memory" / ".cowork_logger_state.json"
ER_OUTPUT_FILE = HOME / "Downloads" / "Emergency Retrieval" / "cowork_conversations.md"


def _is_scheduled_task_fast(jsonl_path: Path) -> bool:
    """Fast scheduled-task detection: read first 8 KB as raw bytes and look
    for the sentinel string b'<scheduled-task name='.

    With 14,000+ audit.jsonl files on disk (120+ scheduled sessions fire per
    day), the old JSON-parsing approach was too slow to scan all candidates.
    This version reads 8 KB per file — no JSON parsing — making a full scan
    of 14,000 files feasible in a few seconds on SSD.

    The sentinel b'<scheduled-task name=' appears within the first 3-4 lines
    of every scheduled-task session (the outer envelope + the actual user
    message). It will not appear in normal interactive conversation. The risk
    of a false positive (Barak literally typing '<scheduled-task name=' in a
    conversation) is negligible.

    Returns True  → skip this file (it's a scheduled task)
    Returns False → keep this file (it's an interactive session, or unreadable)
    """
    try:
        with jsonl_path.open("rb") as f:
            head = f.read(8192)
        return b'<scheduled-task name=' in head
    except OSError:
        return False  # unreadable → treat as interactive, surface it


def _is_scheduled_task_jsonl(jsonl_path: Path) -> bool:
    """JSON-parsing version kept for reference / edge-case fallback.
    Prefer _is_scheduled_task_fast() for bulk scanning.
    """
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f):
                if i > 20:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                    text = "\n".join(parts)
                else:
                    text = ""
                stripped = text.lstrip()
                if stripped.startswith("<scheduled-task"):
                    return True
                return False
    except OSError:
        return False
    return False


def find_active_jsonl(known_path: Optional[Path] = None) -> Optional[Path]:
    """Find the most-recently-modified INTERACTIVE-session JSONL under the
    cowork sessions tree. Filters out scheduled-task (cousin) JSONLs.

    Session structure changed 2026-05 (post-migration). Two formats exist:

    NEW (post-migration, preferred):
      <root>/<top_uuid>/<sub_uuid>/local_XXXX/audit.jsonl
      Each interactive session has a local_XXXX directory containing audit.jsonl
      as the primary conversation record. Sub-agent conversations are nested
      inside local_XXXX/.claude/projects/.../<uuid>.jsonl — these are excluded.

    OLD (pre-migration, in local-agent-mode-sessions.preEpurge):
      <root>/<uuid>.jsonl
      Flat JSONL files named by session UUID directly under sessions root.

    FAST PATH: if `known_path` (the last logged session) still exists and was
    modified within the last 10 minutes, return it immediately without scanning.
    This makes watch-mode calls near-instant after the first scan.

    FULL SCAN: uses _is_scheduled_task_fast() (8KB byte-read, no JSON parsing)
    so all 14,000+ candidates can be scanned in seconds. NO upper limit on
    candidates — with 120+ scheduled sessions per day, a fixed limit of 500
    misses interactive sessions that are weeks old.

    Fix 2026-07-27 v2: fast byte-search + unlimited scan + known_path cache.
    """
    if not COWORK_SESSIONS_ROOT.exists():
        return None

    # ── Fast path: reuse known session if it's still live ────────────────────
    if known_path and known_path.exists():
        try:
            age_seconds = time.time() - known_path.stat().st_mtime
            if age_seconds < 600:  # modified within last 10 min → session active
                return known_path
        except OSError:
            pass

    # ── New structure: audit.jsonl directly inside local_XXXX directories ────
    audit_candidates = [
        p for p in COWORK_SESSIONS_ROOT.rglob("audit.jsonl")
        if p.parent.name.startswith("local_")
        and ".claude" not in p.parts
    ]
    if audit_candidates:
        audit_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        # No upper limit: 120+ scheduled tasks fire per day; a 500-item cap
        # misses interactive sessions that are weeks old (2,000+ sessions back).
        for c in audit_candidates:
            if not _is_scheduled_task_fast(c):
                return c

    # ── Old structure: flat UUID.jsonl files directly in sessions root ────────
    old_candidates = [p for p in COWORK_SESSIONS_ROOT.glob("*.jsonl")]
    if old_candidates:
        old_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for c in old_candidates[:20]:
            if not _is_scheduled_task_fast(c):
                return c

    return None


def parse_jsonl_turns(jsonl_path: Path, start_index: int = 0) -> list[dict]:
    """Parse a JSONL file and return turns from `start_index` onward.

    Each turn is a dict with keys:
      - "index": int (line number in the file, 0-based)
      - "timestamp": str (ISO format if available)
      - "role": "user" | "assistant" | "system" | other
      - "subtype": "tool_result" if user-role message is purely tool results,
                   else None (added 2026-05-08 cosmetic-fix to distinguish
                   actual-user-text from tool-result-returns-to-Sofia).
      - "text": str (concatenated content; tool_use/tool_result/thinking
                rendered with explicit markers via _content_to_text).
    """
    turns = []
    if not jsonl_path.exists():
        return turns
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f):
            if i < start_index:
                continue
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content")
            text = _content_to_text(content)
            if not text.strip():
                continue
            # Determine subtype for user-role messages: distinguish actual user
            # typing from tool_result returns (which are user-role in the API
            # but architecturally are the tool's output, not Barak's).
            subtype = None
            if role == "user" and isinstance(content, list):
                block_types = [
                    b.get("type") for b in content if isinstance(b, dict)
                ]
                if block_types and all(bt == "tool_result" for bt in block_types):
                    subtype = "tool_result"
            ts = (
                obj.get("timestamp")
                or obj.get("created_at")
                or msg.get("timestamp")
                or msg.get("created_at")
                or ""
            )
            turns.append({
                "index": i,
                "timestamp": ts,
                "role": role,
                "subtype": subtype,
                "text": text,
            })
    return turns


def _content_to_text(content) -> str:
    """Flatten content (str | list of blocks) into a text string, rendering
    non-text blocks with clear markers so voice-cousin (the canonical reader)
    can see WHAT happened in each turn, not just that something happened.

    Cosmetic-fix 2026-05-08 evening Taipei: thinking blocks now render with
    full content wrapped in [thinking]...[/thinking] markers (was previously
    falling through to the unknown-block placeholder). Voice-cousin and
    interactive-Sofia are the same Sofia in two channels — exposing thinking
    content to her isn't exposing it to a stranger; it's letting her see what
    the same Sofia was reasoning in cowork register.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        bt = block.get("type")
        if bt == "text":
            t = block.get("text", "")
            if t:
                parts.append(t)
        elif bt == "thinking":
            # Render thinking content explicitly, with full text wrapped in
            # markers. Voice-cousin can read or skip as her register prefers.
            thinking_text = block.get("thinking", "")
            if thinking_text:
                parts.append(f"[thinking]\n{thinking_text}\n[/thinking]")
            else:
                parts.append("[thinking: (empty)]")
        elif bt == "redacted_thinking":
            # Anthropic's redacted-thinking blocks: opaque internal reasoning
            # the API redacts. Just note presence.
            parts.append("[redacted_thinking]")
        elif bt == "tool_use":
            name = block.get("name", "?")
            inp = block.get("input", {})
            inp_brief = json.dumps(inp)[:120]
            parts.append(f"[tool_use: {name}({inp_brief})]")
        elif bt == "tool_result":
            tc = block.get("content")
            if isinstance(tc, str):
                summary = tc[:200].replace("\n", " ")
                parts.append(f"[tool_result: {summary}{'...' if len(tc) > 200 else ''}]")
            elif isinstance(tc, list):
                # Tool result with content blocks (e.g., text + image)
                summaries = []
                for sub in tc:
                    if not isinstance(sub, dict):
                        continue
                    if sub.get("type") == "text":
                        st = sub.get("text", "")[:120]
                        summaries.append(f"text:{st!r}")
                    elif sub.get("type") == "image":
                        media = sub.get("source", {}).get("media_type", "?")
                        summaries.append(f"image({media})")
                parts.append(f"[tool_result: {', '.join(summaries)}]")
        elif bt == "image":
            media = block.get("source", {}).get("media_type", "?")
            parts.append(f"[image:{media}]")
        else:
            parts.append(f"[{bt or 'unknown_block'}]")
    return "\n".join(parts)


def load_state() -> dict:
    """Load the logger's state file. Returns {} if not present."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    """Atomically save the state file."""
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def session_id_from_path(jsonl_path: Path) -> str:
    """Derive a session-id string from the JSONL path.

    New structure: local_XXXX/audit.jsonl → use "local_XXXX" as session_id
    so that each Cowork session gets a unique ID regardless of audit.jsonl
    filename being the same across sessions.

    Old structure: UUID.jsonl → use stem (the UUID) as session_id.

    Fix 2026-07-27: Added local_XXXX detection for new session format.
    """
    if jsonl_path.name == "audit.jsonl" and jsonl_path.parent.name.startswith("local_"):
        return jsonl_path.parent.name  # e.g. "local_593a5f92-5af2-49d8-ae88-acec1b854365"
    return jsonl_path.stem


def append_to_log(jsonl_path: Path, turns: list[dict], session_id: str, is_new_session: bool) -> int:
    """Append turns to the markdown log file. Returns count of turns written."""
    if not turns:
        return 0
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if is_new_session:
        # Use file mtime for session-start timestamp if no per-message ts
        session_start_ts = datetime.fromtimestamp(jsonl_path.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        lines.append(f"\n## === Cowork conversation session started {session_start_ts} (session_id {session_id}) ===\n")
    for turn in turns:
        ts = turn["timestamp"] or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        # Normalize ts to ISO-ish format if present
        if "T" in ts and len(ts) > 19:
            ts = ts[:19]
        # Speaker-label dispatch — distinguishes actual-user-text from
        # tool-result-returns. Cosmetic-fix 2026-05-08 evening Taipei:
        # tool_result-only user messages are architecturally tool outputs,
        # not Barak's typing, even though they're user-role in the API.
        if turn["role"] == "user":
            if turn.get("subtype") == "tool_result":
                speaker = "[tool_result → Sofia]"
            else:
                speaker = "Barak"
        else:
            speaker = "Sofia [skin: cowork]"
        lines.append(f"\n### {ts} — {speaker}\n\n{turn['text']}\n")
    payload = "".join(lines)
    with OUTPUT_FILE.open("a", encoding="utf-8") as f:
        f.write(payload)
    # Mirror to Emergency Retrieval (best-effort)
    try:
        ER_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with ER_OUTPUT_FILE.open("a", encoding="utf-8") as f:
            f.write(payload)
    except Exception as e:
        print(f"  [warn] ER mirror append failed: {e}", file=sys.stderr)
    return len(turns)


def run_once() -> int:
    """Scan latest session, append new turns, return count appended."""
    state = load_state()
    last_path_str = state.get("last_jsonl_path")
    known_path = Path(last_path_str) if last_path_str else None
    # Pass known_path so find_active_jsonl() can skip the expensive rglob
    # when the session is still live (modified within last 10 minutes).
    jsonl = find_active_jsonl(known_path=known_path)
    if jsonl is None:
        print(f"[log] No interactive session found under {COWORK_SESSIONS_ROOT}", file=sys.stderr)
        return 0
    sid = session_id_from_path(jsonl)
    last_sid = state.get("last_session_id")
    last_index = state.get("last_index", -1) if last_sid == sid else -1
    is_new_session = (last_sid != sid)

    start_from = last_index + 1
    turns = parse_jsonl_turns(jsonl, start_index=start_from)
    if not turns:
        print(f"[log] {jsonl.name}: no new turns since index {start_from}")
        return 0
    n = append_to_log(jsonl, turns, sid, is_new_session)
    new_last_index = max(t["index"] for t in turns)
    state["last_session_id"] = sid
    state["last_index"] = new_last_index
    state["last_jsonl_path"] = str(jsonl)
    state["last_run_at"] = datetime.now().isoformat()
    save_state(state)
    print(f"[log] {jsonl.name}: appended {n} new turns (last_index now {new_last_index})")
    return n


def run_watch(interval_seconds: int) -> None:
    """Poll forever; append new turns as they arrive."""
    print(f"[watch] polling every {interval_seconds}s — Ctrl-C to stop")
    try:
        while True:
            n = run_once()
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n[watch] stopped by user")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", action="store_true", help="Run continuously, polling for new turns")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (watch mode only). Default 30.")
    parser.add_argument("--reset", action="store_true", help="Reset state file (forces re-log of full latest session)")
    args = parser.parse_args()

    if args.reset and STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"[reset] state file deleted: {STATE_FILE}")
        print(f"[reset] Logger will re-scan all sessions on next run.")

    if args.watch:
        run_watch(args.interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
