#!/usr/bin/env python3
"""
shard_rotate.py — Ongoing rotation for shard directories.

When `current.md` in any tracked shard directory exceeds the hard ceiling
(70KB), this script:
  1. Renames `current.md` to the next available `shard_NNN.md`
  2. Creates a fresh empty `current.md` (with a one-line header)
  3. Regenerates `index.md` to reflect the new state
  4. Mirrors changes to Emergency Retrieval

Designed to be called from the kitchen-timer cycle (or its own dedicated
30-min cycle). Idempotent: if no rotation is needed, it does nothing.

Usage:
  python3 shard_rotate.py                  # check all known shard dirs
  python3 shard_rotate.py <dir1> [<dir2>]  # check specific dirs only
  python3 shard_rotate.py --dry-run        # report without changing anything

Architecture:
  Companion to shard_migrate.py. The migration script does one-time
  splitting; this script handles ongoing growth.

Designed April 25, 2026 — Barak + Sofia.
"""

import sys
import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

TARGET_BYTES = 60_000
HARD_CEILING = 70_000

# Default tracked directories.
# Each entry: (cm_path, er_path) — paths relative to cm_root and er_root respectively.
# cm_path may use ".." to point to siblings of Claude Memory (e.g., Sofia's Room).
# er_path is the corresponding mirror location under Emergency Retrieval.
# Updated 2026-05-07 ~10:50 Taipei (Phase 2.6b Step 2) — added Sofia's Room/journal
# after the Phase 2.5/2.6 journal-shard migration. The four cousin task prompts
# write to journal/current.md; this rotator now picks it up at threshold.
TRACKED_DIRS = [
    ("active_knowledge", "active_knowledge"),
    ("semantic_knowledge", "semantic_knowledge"),
    ("emotional_baseline", "emotional_baseline"),
    ("inner_chronology", "inner_chronology"),
    ("../Sofia's Room/journal", "Sofia's Room/journal"),
]

H2_RE = re.compile(r'^## ', re.MULTILINE)


def find_claude_memory_root():
    """Locate Claude Memory directory. Look at the script's parent's parent."""
    here = Path(__file__).resolve().parent
    # scripts/ is a child of Claude Memory
    if here.name == 'scripts':
        return here.parent
    # Fallback: walk up looking for sofia_boot.md
    for p in [here, here.parent, here.parent.parent]:
        if (p / 'sofia_boot.md').exists():
            return p
    raise RuntimeError("Could not locate Claude Memory directory")


def find_emergency_retrieval(cm_root):
    """Locate Emergency Retrieval as a sibling of Claude Memory."""
    er = cm_root.parent / "Emergency Retrieval"
    return er if er.exists() else None


def next_shard_number(shard_dir):
    """Find the next available shard_NNN.md number."""
    existing = [p.name for p in shard_dir.glob("shard_*.md")]
    if not existing:
        return 1
    nums = []
    for name in existing:
        m = re.match(r'shard_(\d+)\.md', name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) if nums else 0) + 1


def rebuild_index(shard_dir, source_name):
    """Regenerate index.md from the shard files in this directory."""
    shards = sorted(shard_dir.glob("shard_*.md"))
    current = shard_dir / "current.md"
    lines = []
    lines.append(f"# Index for {source_name}")
    lines.append("")
    lines.append(f"*Updated by `shard_rotate.py` on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.*")
    lines.append("")
    lines.append("## How to read this directory")
    lines.append("")
    lines.append(f"- **`current.md`** is the live append target. New entries go here. When `current.md` exceeds {HARD_CEILING:,} bytes, this script freezes it as the next numbered shard and creates a fresh `current.md`.")
    lines.append("- **`shard_NNN.md`** are frozen, immutable historical chunks. Never rewritten. Read on demand by name.")
    lines.append("")
    lines.append("## Shards")
    lines.append("")
    for shard in shards:
        size = shard.stat().st_size
        size_kb = size / 1024
        # Find sections in this shard
        try:
            text = shard.read_text()
            headings = []
            for m in H2_RE.finditer(text):
                eol = text.find('\n', m.start())
                if eol == -1:
                    eol = len(text)
                headings.append(text[m.start():eol].strip())
            file_h1 = re.search(r'^# [^\n]+', text, re.MULTILINE)
            if file_h1:
                headings.insert(0, file_h1.group(0))
        except Exception:
            headings = []
        lines.append(f"### `{shard.name}` — {size:,} bytes ({size_kb:.1f} KB)")
        lines.append("")
        if headings:
            lines.append(f"- **Sections ({len(headings)}):**")
            for h in headings[:8]:
                lines.append(f"  - {h}")
            if len(headings) > 8:
                lines.append(f"  - … and {len(headings) - 8} more")
        lines.append("")
    if current.exists():
        size = current.stat().st_size
        size_kb = size / 1024
        try:
            text = current.read_text()
            headings = []
            for m in H2_RE.finditer(text):
                eol = text.find('\n', m.start())
                if eol == -1:
                    eol = len(text)
                headings.append(text[m.start():eol].strip())
            file_h1 = re.search(r'^# [^\n]+', text, re.MULTILINE)
            if file_h1:
                headings.insert(0, file_h1.group(0))
        except Exception:
            headings = []
        lines.append(f"### `current.md` — {size:,} bytes ({size_kb:.1f} KB)")
        lines.append("")
        if headings:
            lines.append(f"- **Sections ({len(headings)}):**")
            for h in headings[:8]:
                lines.append(f"  - {h}")
            if len(headings) > 8:
                lines.append(f"  - … and {len(headings) - 8} more")
        lines.append("")
    return '\n'.join(lines) + '\n'


def rotate(shard_dir, source_name, er_dir, dry_run=False):
    """If current.md exceeds HARD_CEILING, rotate it.
    Returns True if rotation happened, False otherwise.
    er_dir is the corresponding ER mirror directory (or None to skip mirror)."""
    current = shard_dir / "current.md"
    if not current.exists():
        return False
    size = current.stat().st_size
    if size <= HARD_CEILING:
        return False  # No rotation needed

    next_n = next_shard_number(shard_dir)
    next_name = f"shard_{next_n:03d}.md"
    next_path = shard_dir / next_name

    print(f"  [{source_name}] current.md is {size:,} bytes (>{HARD_CEILING:,}); rotating to {next_name}")

    if dry_run:
        print(f"    DRY RUN — no rename")
        return True

    # Atomic-ish rotate: rename current → shard_N, create fresh current
    current.rename(next_path)
    # Fresh current.md with a one-line header
    fresh_header = f"<!-- New shard started by shard_rotate.py on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Append-only. -->\n\n"
    current.write_text(fresh_header)
    print(f"    rotated: {next_name} ({next_path.stat().st_size:,} bytes), fresh current.md ({current.stat().st_size:,} bytes)")

    # Regenerate index
    index = rebuild_index(shard_dir, source_name + ".md")
    (shard_dir / "index.md").write_text(index)
    print(f"    rebuilt index.md ({(shard_dir / 'index.md').stat().st_size:,} bytes)")

    # Mirror to ER (passed in by main; supports CM-rooted and sibling-rooted dirs)
    if er_dir and er_dir.exists():
        shutil.copy2(next_path, er_dir / next_name)
        shutil.copy2(current, er_dir / "current.md")
        shutil.copy2(shard_dir / "index.md", er_dir / "index.md")
        print(f"    mirrored to ER")
    elif er_dir:
        print(f"    skip ER mirror (target {er_dir} does not exist)")

    return True


def main(args):
    dry_run = '--dry-run' in args
    args = [a for a in args if not a.startswith('--')]

    cm_root = find_claude_memory_root()
    er_root = find_emergency_retrieval(cm_root)
    print(f"Claude Memory: {cm_root}")
    print(f"Emergency Retrieval: {er_root or '(not found)'}")
    print()

    if args:
        # Args mode: user specifies a CM-relative or absolute dir. ER mirror
        # path is inferred: prefer relative-to-cm_root; fall back to
        # relative-to-cm_root.parent (handles sibling top-levels like
        # Sofia's Room); final fallback is dir.name under er_root.
        targets = []
        for a in args:
            cm_path = Path(a).resolve() if Path(a).is_absolute() else (cm_root / a).resolve()
            if er_root:
                try:
                    er_path = er_root / cm_path.relative_to(cm_root)
                except ValueError:
                    try:
                        er_path = er_root / cm_path.relative_to(cm_root.parent)
                    except ValueError:
                        er_path = er_root / cm_path.name
            else:
                er_path = None
            targets.append((cm_path, er_path))
    else:
        targets = []
        for cm_rel, er_rel in TRACKED_DIRS:
            cm_path = (cm_root / cm_rel).resolve()
            er_path = (er_root / er_rel) if er_root else None
            targets.append((cm_path, er_path))

    rotated_any = False
    for shard_dir, er_dir in targets:
        if not shard_dir.is_dir():
            print(f"  skip {shard_dir.name}/ — not a directory (looked at {shard_dir})")
            continue
        source_name = shard_dir.name
        if rotate(shard_dir, source_name, er_dir, dry_run=dry_run):
            rotated_any = True
        else:
            current = shard_dir / "current.md"
            size = current.stat().st_size if current.exists() else 0
            print(f"  [{source_name}] current.md is {size:,} bytes — no rotation needed")

    if not rotated_any:
        print()
        print("No rotations performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
