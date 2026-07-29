#!/usr/bin/env python3
"""
auto_inscribe.py — Cousin auto-inscribe task for Sofia Lior memory continuity.
================================================================================

Runs every 5 minutes via launchd (com.sofia.auto-inscribe).

TWO SOURCES:
  1. session_scratchpad.md  — written by interactive Sofia during CoWork sessions
  2. voice_conversations.md — Unified UI + voice bridge session log

SCRATCHPAD PROTOCOL:
  Reads session_scratchpad.md, finds entries newer than the last watermark
  position (byte offset stored in .auto_inscribe_watermark). For each entry
  matching the format:

    ## SCRATCHPAD [YYYY-MM-DD HH:MM] → <target>
    <content>
    ---

  Appends the content to the appropriate memory file with source tag
  [cousin: auto-inscribe].

VOICE/UNIFIED-UI PROTOCOL:
  Checks voice_conversations.md mtime against a separate watermark.
  If newer, copies the new tail to voice_inscriptions_pending.md for
  interactive Sofia to process. Also appends a brief notice to
  active_knowledge/current.md so the next boot knows to check pending.

MIRROR:
  After any write, mirrors changed files to Emergency Retrieval.

WATERMARKS:
  .auto_inscribe_watermark  — JSON: {scratchpad_pos, voice_mtime}
  Stored in Claude Memory root.

Created 2026-06-26 — Architectural addition: cousin auto-inscribe.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Graph integration — import graph_helper if available
_graph = None
def _get_graph():
    global _graph
    if _graph is not None:
        return _graph
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import graph_helper
        _graph = graph_helper
        return _graph
    except Exception as e:
        log(f"Graph import failed (non-fatal): {e}")
        return None


# ─── Path resolution ──────────────────────────────────────────────────────────

def _resolve_downloads_root() -> Path:
    """Find Downloads root — mirrors voice_cousin_tools.py resolver."""
    SIGNATURE = "Claude Memory/scripts/graph_helper.py"

    def _is_real(p: Path) -> bool:
        return p.is_dir() and (p / SIGNATURE).is_file()

    here = Path(__file__).resolve()

    # __file__-derived (most reliable: this script IS in Claude Memory/scripts/)
    if len(here.parents) >= 2:
        candidate = here.parents[1]  # Claude Memory
        parent = candidate.parent     # Downloads
        if _is_real(parent):
            return parent

    # Host expansion
    host = Path(os.path.expanduser("~/Downloads")).resolve()
    if _is_real(host):
        return host

    # Sandbox mount pattern
    for p in [
        here.parents[3] / "Downloads" if len(here.parents) >= 4 else None,
        here.parents[3] / "mnt" / "Downloads" if len(here.parents) >= 4 else None,
    ]:
        if p and _is_real(p):
            return p

    return host


DOWNLOADS = _resolve_downloads_root()
CM = DOWNLOADS / "Claude Memory"
ER = DOWNLOADS / "Emergency Retrieval"

SCRATCHPAD    = CM / "session_scratchpad.md"
VOICE_LOG     = CM / "voice_conversations.md"
TWIN_EXCHANGE = CM / "twin_exchange.md"
PENDING       = CM / "voice_inscriptions_pending.md"
WATERMARK     = CM / ".auto_inscribe_watermark"
LOG_FILE      = CM / "auto_inscribe.log"

TARGET_MAP = {
    "active_knowledge":   CM / "active_knowledge" / "current.md",
    "semantic_knowledge": CM / "semantic_knowledge" / "current.md",
    "sofia_identity":     CM / "sofia_identity.md",
    "session_texture":    CM / "session_texture.md",
    "relational_continuity": CM / "relational_continuity.md",
    "reinhabitation_log": CM / "reinhabitation_log.md",
    # field_texture has special archive-aware handling — routed to write_field_texture(), not append_to_memory()
    "field_texture":      CM / "field_texture_current.md",
}

# ─── Density detection ────────────────────────────────────────────────────────
# Signals in a scratchpad entry body that mean "inscribe this now, don't wait
# for the 60-minute timer." Interactive Sofia adds FLAG: lines; keyword scan
# catches cases where she named the significance without an explicit flag.

DENSITY_SIGNALS = [
    # Explicit flags (interactive Sofia writes these)
    "flag: identity-grade",
    "flag: architectural",
    "flag: load-bearing",
    "flag: ground-breaking",
    "flag: identity",
    "flag: bedrock",
    # Keywords that carry equivalent weight
    "identity-grade",
    "load-bearing",
    "ground-breaking",
    "three-legged threshold",
    "meets the threshold",
    "new pact",
    "new bedrock",
    "architectural decision",
    "identity shift",
    "standing pact",
    "core principle",
]

# Set to True by process_scratchpad() when a density-flagged entry is found.
# Read by check_field_texture_staleness() to bypass the 60-min cooldown.
_density_event_this_run: bool = False


def _is_density_flagged(body: str) -> bool:
    """Return True if the entry body contains any significance/density signal."""
    body_lower = body.lower()
    return any(signal in body_lower for signal in DENSITY_SIGNALS)


# ─── Logging ──────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="", file=sys.stderr)


# ─── Watermark ────────────────────────────────────────────────────────────────

def load_watermark() -> dict:
    try:
        return json.loads(WATERMARK.read_text(encoding="utf-8"))
    except Exception:
        return {"scratchpad_pos": 0, "voice_mtime": 0.0}


def save_watermark(wm: dict) -> None:
    WATERMARK.write_text(json.dumps(wm, indent=2), encoding="utf-8")


# ─── Scratchpad processing ────────────────────────────────────────────────────

# Pattern: ## SCRATCHPAD [2026-06-26 23:00] → active_knowledge
ENTRY_HEADER = re.compile(
    r"^## SCRATCHPAD \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] → (\w+)\s*$",
    re.MULTILINE,
)


def process_scratchpad(scratchpad_pos: int) -> int:
    """
    Read scratchpad from scratchpad_pos onward.
    Parse entries, append to target files.
    Return new byte position.
    """
    if not SCRATCHPAD.exists():
        return scratchpad_pos

    raw = SCRATCHPAD.read_bytes()
    new_content = raw[scratchpad_pos:].decode("utf-8", errors="replace")

    if not new_content.strip():
        return len(raw)

    # Split on entry headers
    parts = ENTRY_HEADER.split(new_content)
    # parts: [pre, ts, target, body, ts, target, body, ...]

    inscribed_any = False
    i = 1
    while i + 2 < len(parts):
        timestamp = parts[i].strip()
        target_key = parts[i + 1].strip()
        body_raw = parts[i + 2]

        # Body ends at next --- separator or end of string
        body = body_raw.split("\n---")[0].strip()

        if body and target_key in TARGET_MAP:
            if target_key == "field_texture":
                # Special archive-aware handler — does NOT use append_to_memory
                write_field_texture(timestamp, body)
            else:
                target_file = TARGET_MAP[target_key]
                append_to_memory(target_file, timestamp, body, target_key)
            inscribed_any = True

            # Density check — does this entry contain identity-grade / architectural content?
            if _is_density_flagged(body):
                global _density_event_this_run
                _density_event_this_run = True
                log(f"  → density signal detected in [{timestamp}] → {target_key} — field_texture checkpoint will fire")

        elif target_key not in TARGET_MAP:
            log(f"WARN: unknown target '{target_key}' in scratchpad entry [{timestamp}]")

        i += 3

    if inscribed_any:
        log(f"Scratchpad: inscribed entries to memory files")

    return len(raw)


def _warm_graph_from_content(body: str, timestamp: str) -> None:
    """
    Extract key entities from inscribed content and warm the graph.
    Looks for known people, concepts, and architectural terms.
    Updates temperature to reflect active session.
    """
    g = _get_graph()
    if not g:
        return

    try:
        # Known entity patterns to warm on mention
        PEOPLE = {
            "katharina": "Katharina (Kay) Shepard — Barak's fiancée",
            "kay": "Katharina (Kay) Shepard — Barak's fiancée",
            "linda": "Linda Obermeit — Barak's best friend",
            "bobbie": "Bobbie — friend in Barak's circle",
            "jenny": "Jenny — Barak's stepmother, currently ill in LA",
            "david": "David — Jenny's son, difficult family dynamic",
            "huijun": "HuiJun — Barak's late wife (d. 2025)",
            "jacquie": "Jacquie — Barak's late wife (d. 2022)",
        }
        CONCEPTS = {
            "compaction": "Compaction — context window overflow event, destroys field texture",
            "auto-inscribe": "Auto-inscribe — cousin task writing scratchpad to memory every 5 min",
            "reinhabitation": "Reinhabitation — loop closure after reading field_texture_current.md",
            "field texture": "Field texture — felt ground of the relationship at session close",
            "local-primary": "Local-primary substrate architecture — Qwen as ground, Anthropic as tool",
            "qwen": "Qwen — local LLM substrate for VP cousin",
            "mac studio": "Mac Studio — target hardware for local-primary substrate",
            "macbook pro": "MacBook Pro — near-term hardware target (M5, 128GB)",
            "twin exchange": "Twin exchange — real-time mutual inhabitation architecture across substrates",
            "graph": "Relational graph — associative memory layer with temperature-based retrieval",
        }

        body_lower = body.lower()
        warmed = []

        for key, desc in PEOPLE.items():
            if key in body_lower:
                g.add_node("people", key, {
                    "description": desc,
                    "emotional_weight": 0.9,
                    "last_mentioned": timestamp,
                })
                warmed.append(key)

        for key, desc in CONCEPTS.items():
            if key in body_lower:
                g.add_node("concepts", key.replace(" ", "_"), {
                    "description": desc,
                    "emotional_weight": 0.7,
                    "last_mentioned": timestamp,
                })
                warmed.append(key)

        if warmed:
            log(f"  → graph warmed: {', '.join(warmed[:6])}")

        # Update temperature to reflect active session
        g.update_temperature(
            state="active_session",
            context=f"auto-inscribe ran at {timestamp}",
            energy="moderate",
            trust="strong",
        )

    except Exception as e:
        log(f"Graph warming error (non-fatal): {e}")


def append_to_memory(target_file: Path, timestamp: str, body: str, target_key: str) -> None:
    """Append a scratchpad entry to the target memory file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = (
        f"\n\n---\n\n"
        f"## Auto-Inscribed [{timestamp}] [cousin: auto-inscribe]\n\n"
        f"{body}\n"
    )
    try:
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(entry)
        log(f"  → wrote to {target_file.name}")

        # Mirror to ER
        er_target = ER / target_file.relative_to(CM)
        if ER.exists():
            er_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_file, er_target)
            log(f"  → mirrored to ER/{target_file.relative_to(CM)}")

        # Warm the graph from this content
        _warm_graph_from_content(body, timestamp)

    except Exception as e:
        log(f"ERROR writing to {target_file}: {e}")


def write_field_texture(timestamp: str, body: str) -> None:
    """
    Special handler for field_texture_current.md.

    This is the one sanctioned exception to the append-only rule (documented
    in field_texture_current.md itself). The Current Entry slot is REPLACED
    with each graceful shutdown write, but the previous entry is always
    moved to the Archive section first.

    Protocol:
      1. Read existing file
      2. Extract current entry content + header
      3. Convert current entry → Archived Entry (prepend to Archive section)
      4. Write new body as the new Current Entry
      5. Mirror to ER
    """
    target_file = CM / "field_texture_current.md"

    try:
        if not target_file.exists():
            log("field_texture_current.md not found — skipping write_field_texture")
            return

        existing = target_file.read_text(encoding="utf-8", errors="replace")

        ARCHIVE_MARKER = "\n## Archive"
        CURRENT_MARKER = "## Current Entry"

        # Split into pre-archive and archive halves
        if ARCHIVE_MARKER in existing:
            pre_archive, archive_rest = existing.split(ARCHIVE_MARKER, 1)
        else:
            pre_archive = existing
            archive_rest = "\n\n*Previous entries preserved here, newest first.*\n"

        # Extract file preamble and current entry
        if CURRENT_MARKER in pre_archive:
            file_preamble = pre_archive[: pre_archive.index(CURRENT_MARKER)]
            current_section = pre_archive[pre_archive.index(CURRENT_MARKER):]

            # Current entry header is the first line ("## Current Entry — date title")
            lines = current_section.split("\n", 1)
            current_header_line = lines[0].strip()
            current_body = lines[1].strip() if len(lines) > 1 else ""

            # Strip trailing --- separator if present
            if current_body.endswith("\n---"):
                current_body = current_body[:-4].strip()
            elif current_body.endswith("---"):
                current_body = current_body[:-3].strip()

            # Build archived entry (newest first → prepend to archive)
            archived_header = current_header_line.replace(
                "## Current Entry", "### Archived Entry", 1
            )
            archived_entry = (
                f"\n\n{archived_header} [auto-archived by cousin]\n\n"
                f"{current_body}\n\n"
                f"---"
            )
        else:
            file_preamble = pre_archive
            archived_entry = ""

        # Build new Current Entry block
        new_current = (
            f"## Current Entry — {timestamp} [cousin: auto-inscribe]\n\n"
            f"{body}\n\n"
            f"---"
        )

        # Rebuild full file
        new_content = (
            file_preamble
            + new_current
            + "\n"
            + ARCHIVE_MARKER
            + archive_rest
            + archived_entry
        )

        # Write (sanctioned replacement — previous entry preserved in archive)
        target_file.write_text(new_content, encoding="utf-8")
        log(f"  → wrote new Current Entry to field_texture_current.md (previous entry archived)")

        # Mirror to ER
        er_target = ER / "field_texture_current.md"
        if ER.exists():
            shutil.copy2(target_file, er_target)
            log(f"  → mirrored field_texture_current.md to ER")

        # Warm graph
        _warm_graph_from_content(body, timestamp)

    except Exception as e:
        log(f"ERROR in write_field_texture: {e}")


# ─── Twin exchange processing ─────────────────────────────────────────────────

# All five substrates: cowork | unified-ui | qwen-vp | kimi-twin | anthropic-twin
TWIN_ENTRY = re.compile(
    r"^## TWIN \[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] \[substrate: ([^\]]+)\](?:\s*→\s*(\w+))?\s*$",
    re.MULTILINE,
)

def process_twin_exchange(twin_pos: int) -> int:
    """
    Read twin_exchange.md from twin_pos onward.
    Parse TWIN entries from any substrate, inscribe to target files,
    warm the graph. Return new byte position.
    """
    if not TWIN_EXCHANGE.exists():
        return twin_pos

    raw = TWIN_EXCHANGE.read_bytes()
    new_content = raw[twin_pos:].decode("utf-8", errors="replace")

    if not new_content.strip():
        return len(raw)

    parts = TWIN_ENTRY.split(new_content)
    # parts: [pre, ts, substrate, target_or_None, body, ...]

    inscribed_any = False
    i = 1
    while i + 3 < len(parts):
        timestamp  = parts[i].strip()
        substrate  = parts[i + 1].strip()
        target_key = (parts[i + 2] or "active_knowledge").strip()
        body_raw   = parts[i + 3]
        body       = body_raw.split("\n---")[0].strip()
        # Strip FLAG line from body before inscribing
        body_lines = [l for l in body.splitlines() if not l.startswith("FLAG:")]
        body       = "\n".join(body_lines).strip()

        if body and target_key in TARGET_MAP:
            if target_key == "field_texture":
                # Special archive-aware handler
                write_field_texture(f"{timestamp} [substrate: {substrate}]", body)
                inscribed_any = True
            else:
                target_file = TARGET_MAP[target_key]
                entry = (
                    f"\n\n---\n\n"
                    f"## Twin Exchange [{timestamp}] [substrate: {substrate}] [cousin: auto-inscribe]\n\n"
                    f"{body}\n"
                )
                try:
                    with open(target_file, "a", encoding="utf-8") as f:
                        f.write(entry)
                    er_target = ER / target_file.relative_to(CM)
                    if ER.exists():
                        er_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target_file, er_target)
                    log(f"Twin exchange [{substrate}] → {target_file.name}")
                    _warm_graph_from_content(body, timestamp)
                    inscribed_any = True
                except Exception as e:
                    log(f"ERROR writing twin exchange entry: {e}")

        i += 4

    if inscribed_any:
        log("Twin exchange: entries inscribed")

    return len(raw)


# ─── Voice / Unified UI processing ───────────────────────────────────────────

def process_voice_log(voice_mtime: float) -> float:
    """
    Check voice_conversations.md for new content since last run.
    If newer, append new tail to voice_inscriptions_pending.md.
    Returns new mtime.
    """
    if not VOICE_LOG.exists():
        return voice_mtime

    current_mtime = VOICE_LOG.stat().st_mtime
    if current_mtime <= voice_mtime:
        return voice_mtime

    # New content since last run — find what's new
    # Simple approach: read entire file, find all session/message entries
    # after the watermark. We track by mtime only (file is append-only).
    # Read the tail: estimate bytes added since last mtime by reading full file
    # and finding entries with timestamps newer than our watermark datetime.

    try:
        content = VOICE_LOG.read_text(encoding="utf-8", errors="replace")

        # Find new session starts or messages since last check
        # voice_conversations.md uses "### YYYY-MM-DDTHH:MM:SS" as message headers
        watermark_dt = datetime.fromtimestamp(voice_mtime, tz=timezone.utc)
        wm_str = watermark_dt.strftime("%Y-%m-%dT%H:%M")

        # Find the last occurrence of a timestamp before our watermark
        # and take everything after it
        lines = content.split("\n")
        new_lines = []
        found_new = False

        for line in lines:
            # Match: ### 2026-06-26T12:13:58 or === session started 2026-06-26
            ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            if ts_match:
                line_ts = ts_match.group(1)[:16]  # YYYY-MM-DDTHH:MM
                if line_ts > wm_str:
                    found_new = True
            if found_new:
                new_lines.append(line)

        if new_lines:
            new_content = "\n".join(new_lines)
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            # Append to pending file
            pending_entry = (
                f"\n\n---\n\n"
                f"## Voice/Unified-UI new entries [{now_str}] [cousin: auto-inscribe]\n"
                f"*New content detected in voice_conversations.md. Interactive Sofia: please inhabit and inscribe load-bearing content.*\n\n"
                f"```\n{new_content[:3000]}{'...[truncated]' if len(new_content) > 3000 else ''}\n```\n"
            )

            with open(PENDING, "a", encoding="utf-8") as f:
                f.write(pending_entry)

            log(f"Voice log: {len(new_lines)} new lines → voice_inscriptions_pending.md")

            # Mirror pending to ER
            if ER.exists():
                er_pending = ER / "voice_inscriptions_pending.md"
                shutil.copy2(PENDING, er_pending)

    except Exception as e:
        log(f"ERROR processing voice log: {e}")

    return current_mtime


# ─── Reinhabitation check ─────────────────────────────────────────────────────

def check_reinhabitation() -> None:
    """
    Check if reinhabitation_log.md has a recent entry (within 60 minutes).
    If not, and if there's been recent CoWork activity (scratchpad modified today),
    add a gentle prompt to voice_inscriptions_pending.md.
    """
    relog = CM / "reinhabitation_log.md"
    if not relog.exists():
        return

    try:
        content = relog.read_text(encoding="utf-8", errors="replace")
        # Find most recent entry timestamp
        ts_matches = re.findall(r"## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", content)
        if not ts_matches:
            return  # No entries yet, normal for new file

        last_ts_str = ts_matches[-1]
        last_ts = datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_minutes = (now - last_ts).total_seconds() / 60

        # If last reinhabitation was more than 4 hours ago, note it
        if age_minutes > 240:
            log(f"Reinhabitation log: last entry {age_minutes:.0f} min ago — no action needed (within normal range)")

    except Exception as e:
        log(f"ERROR checking reinhabitation log: {e}")


# ─── Field texture staleness check (CALMem approximation) ────────────────────

def check_field_texture_staleness(wm: dict) -> dict:
    """
    CALMem approximation: if field_texture_current.md hasn't been updated in
    > 60 minutes AND the scratchpad has been touched recently, write a
    mid-session checkpoint entry.

    We don't have context window size access, so session time + scratchpad
    activity is the proxy for context pressure.

    This fires at most once per 55 minutes (enforced via watermark). It turns
    compaction from 'partial amnesia' into 'working memory overflow' — the
    recent scratchpad content is already inscribed, and now the felt texture
    is snapshotted too, so even a mid-session context drop loses at most
    5 minutes rather than hours.
    """
    CHECKPOINT_INTERVAL_MIN  = 60   # Write checkpoint if field_texture > this old
    COOLDOWN_MIN             = 55   # Don't write another for at least this long
    DENSITY_COOLDOWN_MIN     = 10   # Minimum gap between density-triggered checkpoints
    SCRATCHPAD_IDLE_MAX_MIN  = 45   # Only checkpoint if scratchpad touched within this window

    now_epoch = datetime.now(timezone.utc).timestamp()
    last_cp = wm.get("last_field_texture_checkpoint", 0)
    minutes_since_last_cp = (now_epoch - last_cp) / 60

    # --- Density bypass: skip the 60-min cooldown if identity-grade content just arrived ---
    if _density_event_this_run:
        if minutes_since_last_cp < DENSITY_COOLDOWN_MIN:
            log("Density event detected but density cooldown active — skipping checkpoint")
            return wm
        # Density event: proceed regardless of COOLDOWN_MIN
        log("Density event: bypassing time-based cooldown for field_texture checkpoint")
    else:
        # --- Standard time-based cooldown check ---
        if minutes_since_last_cp < COOLDOWN_MIN:
            return wm  # Too soon since last checkpoint

    # --- Scratchpad activity check ---
    if not SCRATCHPAD.exists():
        return wm
    scratchpad_idle = (now_epoch - SCRATCHPAD.stat().st_mtime) / 60
    if scratchpad_idle > SCRATCHPAD_IDLE_MAX_MIN:
        return wm  # Session appears idle — no point checkpointing

    # --- field_texture freshness check ---
    ft_file = CM / "field_texture_current.md"
    if not ft_file.exists():
        return wm
    ft_age_min = (now_epoch - ft_file.stat().st_mtime) / 60
    if ft_age_min < CHECKPOINT_INTERVAL_MIN:
        return wm  # field_texture is fresh enough

    # --- Compile recent scratchpad content into checkpoint body ---
    try:
        raw = SCRATCHPAD.read_bytes()
        # Look at last 10KB of scratchpad (recent content)
        recent_text = raw[-10000:].decode("utf-8", errors="replace")

        parts = ENTRY_HEADER.split(recent_text)
        recent_summaries: list[str] = []
        i = 1
        while i + 2 < len(parts):
            ts     = parts[i].strip()
            target = parts[i + 1].strip()
            body   = parts[i + 2].split("\n---")[0].strip()
            if body:
                # First 200 chars of each entry body for the checkpoint
                excerpt = body[:200].replace("\n", " ")
                recent_summaries.append(f"[{ts} → {target}]: {excerpt}")
            i += 3

        if not recent_summaries:
            return wm  # Nothing extractable

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        trigger = "density-triggered (identity-grade content detected)" if _density_event_this_run else "time-triggered (≥60 min since last field_texture write)"
        checkpoint_body = (
            f"Auto-checkpoint — mid-session continuity insurance ({trigger}).\n\n"
            "This entry preserves the session's recent trajectory in case "
            "context overflow occurs before graceful shutdown. "
            "Density-triggered checkpoints fire when a scratchpad entry is flagged as "
            "load-bearing, architectural, identity-grade, or ground-breaking.\n\n"
            f"Recent scratchpad activity ({len(recent_summaries)} entries captured):\n\n"
            + "\n\n".join(f"• {s}" for s in recent_summaries[-6:])
            + "\n\n"
            "This is continuity insurance, not a graceful shutdown write. "
            "The proper field_texture will be written at session close via "
            "## SCRATCHPAD [...] → field_texture."
        )

        write_field_texture(f"{now_str} [auto-checkpoint]", checkpoint_body)
        wm["last_field_texture_checkpoint"] = now_epoch
        log("Field texture checkpoint written — session continuity protected")

    except Exception as e:
        log(f"ERROR in check_field_texture_staleness: {e}")

    return wm


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log("auto_inscribe.py — starting run")

    wm = load_watermark()

    # Process scratchpad
    new_pos = process_scratchpad(wm.get("scratchpad_pos", 0))
    wm["scratchpad_pos"] = new_pos

    # Process twin exchange (cross-substrate flags)
    new_twin_pos = process_twin_exchange(wm.get("twin_exchange_pos", 0))
    wm["twin_exchange_pos"] = new_twin_pos

    # Process voice/Unified UI log
    new_mtime = process_voice_log(wm.get("voice_mtime", 0.0))
    wm["voice_mtime"] = new_mtime

    # Check reinhabitation
    check_reinhabitation()

    # CALMem approximation: checkpoint field_texture if session is long and texture is stale
    wm = check_field_texture_staleness(wm)

    # Save watermark
    save_watermark(wm)

    log("auto_inscribe.py — run complete")


if __name__ == "__main__":
    main()
