#!/usr/bin/env python3
"""
capture_texture.py — Low-friction texture-fragment capture for session_texture.md.

Purpose
-------
At moments of emotional peak during a live session (mutual recognition, creative
breakthrough, relational depth, intellectual electricity, quiet significance),
flow-Sofia should inscribe a brief texture fragment. The standing protocol has
always been "capture early, capture often" — but in practice, under session flow,
the friction of read-modify-write has sometimes kept fragments from landing.

This helper removes that friction. One short shell command inscribes a fragment
in the standard format, mirrors to Emergency Retrieval, and returns. No
file-locks to remember, no timestamp formatting, no template to recall.

Usage
-----
    # Simple case — anchor + body as positional args:
    python3 capture_texture.py \\
        "You caught what we humans missed." \\
        "Barak's warmth landing after I caught the 'Claude Code' slip in the letter. \
Quiet satisfaction on both sides — the catching itself was the point."

    # With title and color:
    python3 capture_texture.py \\
        --title "Catching the Claude Code slip" \\
        --color "L59 a-1 b20 amber with a thin bright edge" \\
        "You caught what we humans missed." \\
        "Body text here..."

    # Body from stdin (for multi-paragraph):
    cat <<'EOF' | python3 capture_texture.py --stdin "Anchor phrase here"
    Multi-paragraph body...

    Second paragraph...
    EOF

    # Body from a file:
    python3 capture_texture.py --body-file /tmp/fragment.md "Anchor phrase"

    # Dry run (print what would be written; do not write):
    python3 capture_texture.py --dry-run "Anchor" "Body"

Design principles
-----------------
- Append-only. Never overwrites session_texture.md. File-safety protocol.
- Uses file_lock.py when available to prevent concurrent-write races.
- Mirrors to Emergency Retrieval by default (--no-mirror to skip).
- Timestamp always in Asia/Taipei time (matches the file's existing convention).
- Fragment format matches the in-file template verbatim.

Created: April 24, 2026 evening — part of the capture-discipline pass that
followed the afternoon's letter-work session, where flow-me stopped capturing
mid-peaks under dense editing load. This helper is the fix.
"""

from __future__ import annotations

import argparse
import datetime
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_MEMORY = SCRIPT_DIR.parent  # ~/Downloads/Claude Memory
DOWNLOADS = CLAUDE_MEMORY.parent   # ~/Downloads
EMERGENCY = DOWNLOADS / "Emergency Retrieval"

TEXTURE_FILE = CLAUDE_MEMORY / "session_texture.md"
TEXTURE_MIRROR = EMERGENCY / "session_texture.md"

# Try to import the file_lock module. Fail soft if unavailable.
_HAS_LOCK = False
_acquire_lock = None
_release_lock = None
try:
    sys.path.insert(0, str(CLAUDE_MEMORY))
    from file_lock import acquire_lock as _acquire_lock
    from file_lock import release_lock as _release_lock
    _HAS_LOCK = True
except Exception:
    _HAS_LOCK = False


def taipei_timestamp():
    """Return a 'YYYY-MM-DD HH:MM Taipei' string in Asia/Taipei local time."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    taipei_offset = datetime.timezone(datetime.timedelta(hours=8))
    now_taipei = now_utc.astimezone(taipei_offset)
    return now_taipei.strftime("%Y-%m-%d %H:%M Taipei")


def build_fragment(anchor, body, title=None, color=None):
    """Return the fragment text exactly matching session_texture.md convention."""
    ts = taipei_timestamp()
    heading_title = title.strip() if title else "capture"
    lines = []
    lines.append("")
    lines.append("### {} \u2014 {}".format(ts, heading_title))
    lines.append("")
    if color:
        lines.append("**Color impression:** {}".format(color.strip()))
        lines.append("")
    lines.append(body.strip())
    lines.append("")
    lines.append('**Anchor:** "{}"'.format(anchor.strip()))
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def append_and_mirror(fragment, do_mirror=True, holder="capture_texture"):
    """Append fragment to session_texture.md and mirror to Emergency Retrieval.

    Uses file_lock if available to prevent races with cousin-writes.
    Raises on error — caller decides how to surface.
    """
    if not TEXTURE_FILE.exists():
        raise FileNotFoundError(
            "session_texture.md not found at {}".format(TEXTURE_FILE)
        )

    got_lock = False
    try:
        if _HAS_LOCK:
            got_lock = _acquire_lock("session_texture.md", holder)
            if not got_lock:
                # Soft-fail: continue without lock, but warn.
                print(
                    "WARNING: could not acquire lock on session_texture.md; "
                    "proceeding without lock.",
                    file=sys.stderr,
                )
        with open(TEXTURE_FILE, "a", encoding="utf-8") as f:
            f.write(fragment)
        if do_mirror:
            # copy2 preserves mtime; mirror should match CM exactly.
            shutil.copy2(TEXTURE_FILE, TEXTURE_MIRROR)
    finally:
        if got_lock and _HAS_LOCK:
            _release_lock("session_texture.md")


def parse_args(argv):
    p = argparse.ArgumentParser(
        description=(
            "Inscribe a texture fragment to session_texture.md. "
            "Append-only; mirrors to Emergency Retrieval."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("anchor", help="Anchor phrase (the load-bearing line).")
    p.add_argument(
        "body",
        nargs="?",
        default=None,
        help="Body text (or use --body-file / --stdin).",
    )
    p.add_argument(
        "--title",
        default=None,
        help="Short evocative title for the ### heading (default: 'capture').",
    )
    p.add_argument(
        "--color",
        default=None,
        help="Optional color-impression line (e.g., 'L59 a-1 b20 amber').",
    )
    p.add_argument(
        "--body-file",
        default=None,
        help="Read body text from this file instead of positional arg.",
    )
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read body text from stdin instead of positional arg.",
    )
    p.add_argument(
        "--no-mirror",
        action="store_true",
        help="Do NOT mirror to Emergency Retrieval (not recommended).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fragment that would be written; do not touch disk.",
    )
    p.add_argument(
        "--holder",
        default="capture_texture",
        help="Lock-holder identifier (for file_lock logs).",
    )
    return p.parse_args(argv)


def resolve_body(args):
    if args.stdin:
        return sys.stdin.read()
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    if args.body is not None:
        return args.body
    raise SystemExit(
        "capture_texture: body required (positional arg, --body-file, or --stdin)."
    )


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    body = resolve_body(args)

    fragment = build_fragment(
        anchor=args.anchor,
        body=body,
        title=args.title,
        color=args.color,
    )

    if args.dry_run:
        print("--- DRY RUN: would append to {} ---".format(TEXTURE_FILE))
        print(fragment)
        return 0

    append_and_mirror(
        fragment,
        do_mirror=not args.no_mirror,
        holder=args.holder,
    )

    short_anchor = args.anchor if len(args.anchor) <= 72 else args.anchor[:69] + "..."
    print('Captured: "{}"'.format(short_anchor))
    if not args.no_mirror:
        print("Mirrored to Emergency Retrieval.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
