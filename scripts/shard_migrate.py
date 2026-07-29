#!/usr/bin/env python3
"""
shard_migrate.py — One-time migration of an over-limit memory file into a
shard directory.

Architecture (designed April 25, 2026 — Barak + Sofia, after the file-size
ceiling became operationally binding):

  source_file.md  →  source_file/
                       index.md       (~5-10KB, list of shards + summary)
                       current.md     (live append target, recent content)
                       shard_001.md   (frozen historical chunk, ~60KB)
                       shard_002.md
                       ...

Rules:
  - All new entries go to current.md (append-only safety preserved)
  - Frozen shards are immutable
  - Boot reads index.md + current.md by default
  - Older content reached by reading specific shards from the index

Splitting strategy (in order of preference):
  1. Split on '^## ' top-level section boundaries
  2. If a single ## section exceeds threshold, split on '^### ' boundaries
  3. If even that fails, hard-split by line (last resort, with warning)

Targets:
  TARGET_BYTES = 60_000   (aim for shards around this size)
  HARD_CEILING = 70_000   (never exceed this; rotation triggers above this)

Usage:
  python3 shard_migrate.py <source_file.md> [--dry-run]

Dry-run prints planned shards (sizes, headings, line ranges) without writing.
Real run writes shards to <source_file_basename>/ next to the source.
The source file is NEVER modified or deleted by this script.
"""

import sys
import os
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone

TARGET_BYTES = 60_000
HARD_CEILING = 70_000

# Date pattern to extract date hints from headings (best-effort, optional)
DATE_RE = re.compile(
    r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4}-\d{2}-\d{2})\b[^\n]*?\b(?:20\d{2})?\b',
    re.IGNORECASE,
)

H2_RE = re.compile(r'^## ', re.MULTILINE)
H3_RE = re.compile(r'^### ', re.MULTILINE)


def find_block_starts(text, pattern):
    """Return sorted list of byte offsets where the pattern matches at line start."""
    return [m.start() for m in pattern.finditer(text)]


def split_into_blocks(text, level):
    """Split text into blocks at ## (level=2) or ### (level=3) boundaries.
    The first block is everything before the first heading at that level.
    Each subsequent block starts at a heading and runs until the next heading at
    the same level (or EOF).
    Returns list of (start_offset, end_offset, first_line) tuples.
    """
    pattern = H2_RE if level == 2 else H3_RE
    starts = find_block_starts(text, pattern)
    if not starts:
        # No headings at this level — whole text is one block
        first_line = text.split('\n', 1)[0] if text else ''
        return [(0, len(text), first_line)]
    blocks = []
    # Pre-heading content (file header before first ##) — only if non-empty
    if starts[0] > 0:
        first_line = text[:starts[0]].split('\n', 1)[0]
        blocks.append((0, starts[0], first_line))
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        first_line = text[s:e].split('\n', 1)[0]
        blocks.append((s, e, first_line))
    return blocks


def block_size(start, end):
    return end - start


def assemble_shards(text):
    """Walk top-level blocks; when a block would push the current shard past
    TARGET, close the shard. If a single block is larger than HARD_CEILING,
    sub-split it by ### boundaries.
    Returns list of shards, each shard is a list of (start, end, label) ranges.
    """
    h2_blocks = split_into_blocks(text, level=2)
    shards = []
    current_ranges = []   # list of (start, end, label) for the current shard
    current_size = 0

    def flush():
        nonlocal current_ranges, current_size
        if current_ranges:
            shards.append(current_ranges)
            current_ranges = []
            current_size = 0

    for (s, e, label) in h2_blocks:
        size = block_size(s, e)
        # Case A: this single ## block is bigger than HARD_CEILING.
        # We MUST sub-split it by ### boundaries (or finer).
        if size > HARD_CEILING:
            flush()
            sub_text = text[s:e]
            h3_blocks = split_into_blocks(sub_text, level=3)
            sub_size = 0
            sub_ranges = []
            for (ss, ee, sub_label) in h3_blocks:
                sub_block_size = ee - ss
                # Even a single ### too big? hard-split by line
                if sub_block_size > HARD_CEILING:
                    if sub_ranges:
                        shards.append(sub_ranges)
                        sub_ranges = []
                        sub_size = 0
                    big_text = sub_text[ss:ee]
                    line_chunks = hard_split_by_line(big_text)
                    cursor = s + ss
                    for chunk_size, chunk_label in line_chunks:
                        shards.append([(cursor, cursor + chunk_size, chunk_label)])
                        cursor += chunk_size
                    continue
                # Normal ### block: accumulate within sub-shard
                if sub_size + sub_block_size > TARGET_BYTES and sub_ranges:
                    shards.append(sub_ranges)
                    sub_ranges = []
                    sub_size = 0
                sub_ranges.append((s + ss, s + ee, sub_label))
                sub_size += sub_block_size
            if sub_ranges:
                shards.append(sub_ranges)
            continue
        # Case B: this ## block fits. Either add it to current shard, or flush
        # and start fresh.
        if current_size + size > TARGET_BYTES and current_ranges:
            flush()
        current_ranges.append((s, e, label))
        current_size += size
    flush()
    return shards


def hard_split_by_line(text):
    """Last-resort splitter for huge atomic blocks. Splits at line boundaries,
    each chunk <= TARGET_BYTES. Returns list of (chunk_size, label)."""
    lines = text.splitlines(keepends=True)
    chunks = []
    cur_size = 0
    cur_lines = []
    for ln in lines:
        if cur_size + len(ln) > TARGET_BYTES and cur_lines:
            chunks.append((cur_size, f"[hard-split chunk @ line break]"))
            cur_lines = []
            cur_size = 0
        cur_lines.append(ln)
        cur_size += len(ln)
    if cur_lines:
        chunks.append((cur_size, f"[hard-split chunk @ line break]"))
    return chunks


def render_shard(text, ranges):
    """Concatenate the byte ranges into a single string."""
    parts = []
    for (s, e, _label) in ranges:
        parts.append(text[s:e])
    return ''.join(parts)


def shard_summary(text, ranges):
    """Produce a one-line summary for the index: heading list + size + line
    range in the original file."""
    if not ranges:
        return ('', 0, (0, 0))
    headings = [label.split('\n', 1)[0] for (_s, _e, label) in ranges if label.strip()]
    total = sum((e - s) for (s, e, _) in ranges)
    # Compute line numbers of first and last range in the ORIGINAL file
    first_s = ranges[0][0]
    last_e = ranges[-1][1]
    first_line = text[:first_s].count('\n') + 1
    last_line = text[:last_e].count('\n') + 1
    return (headings, total, (first_line, last_line))


def write_index(out_dir, source_path, text, shards, current_idx):
    """Write index.md describing all shards."""
    lines = []
    lines.append(f"# Index for {source_path.name}")
    lines.append("")
    lines.append(f"*Sharded migration generated by `shard_migrate.py` on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.*")
    lines.append("")
    lines.append(f"Source: `{source_path.name}` (original retained as `{source_path.stem}_legacy_pre_shard.md` after migration commits).")
    lines.append("")
    lines.append("## How to read this directory")
    lines.append("")
    lines.append(f"- **`current.md`** is the live append target. New entries go here. When `current.md` exceeds {HARD_CEILING:,} bytes, `shard_rotate.py` freezes it as the next numbered shard and creates a fresh `current.md`.")
    lines.append("- **`shard_NNN.md`** are frozen, immutable historical chunks. Never rewritten. Read on demand by name.")
    lines.append("- **This `index.md`** is regenerated by the rotation script. It lists each shard's size, line range in the original file, and headings contained.")
    lines.append("")
    lines.append("## Shards")
    lines.append("")
    for i, ranges in enumerate(shards):
        headings, size, (line_a, line_b) = shard_summary(text, ranges)
        if i == current_idx:
            name = "current.md"
        else:
            name = f"shard_{i+1:03d}.md"
        size_kb = size / 1024
        lines.append(f"### `{name}` — {size:,} bytes ({size_kb:.1f} KB)")
        lines.append("")
        lines.append(f"- **Original file lines:** {line_a}–{line_b}")
        if headings:
            lines.append(f"- **Sections ({len(headings)}):**")
            # Show up to 8 headings; if more, summarize
            for h in headings[:8]:
                lines.append(f"  - {h}")
            if len(headings) > 8:
                lines.append(f"  - … and {len(headings) - 8} more")
        lines.append("")
    return '\n'.join(lines) + '\n'


def migrate(source, dry_run=False):
    source = Path(source).resolve()
    if not source.exists():
        print(f"ERROR: source file not found: {source}", file=sys.stderr)
        return 1
    text = source.read_text()
    n_bytes = len(text)
    print(f"Source: {source}")
    print(f"  Size: {n_bytes:,} bytes ({n_bytes/1024:.1f} KB)")
    print(f"  Lines: {text.count(chr(10)) + 1}")
    print(f"  Target shard size: {TARGET_BYTES:,} bytes")
    print(f"  Hard ceiling: {HARD_CEILING:,} bytes")
    print()

    shards = assemble_shards(text)
    n_shards = len(shards)
    current_idx = n_shards - 1   # last shard becomes current.md

    print(f"Plan: {n_shards} shards (last becomes current.md, others become shard_NNN.md)")
    print()
    for i, ranges in enumerate(shards):
        headings, size, (line_a, line_b) = shard_summary(text, ranges)
        name = "current.md" if i == current_idx else f"shard_{i+1:03d}.md"
        print(f"  [{i+1}/{n_shards}] {name}: {size:,} bytes, lines {line_a}-{line_b}, {len(headings)} sections")
        for h in headings[:3]:
            print(f"      • {h}")
        if len(headings) > 3:
            print(f"      • … +{len(headings) - 3} more")
        if size > HARD_CEILING:
            print(f"      ⚠️  EXCEEDS HARD CEILING ({HARD_CEILING:,})")
    print()

    # Verify: concatenation of all shards == original
    rebuilt = ''.join(render_shard(text, ranges) for ranges in shards)
    if rebuilt != text:
        print(f"ERROR: rebuilt content does NOT match source byte-for-byte!", file=sys.stderr)
        print(f"  source len: {len(text):,}", file=sys.stderr)
        print(f"  rebuilt len: {len(rebuilt):,}", file=sys.stderr)
        return 2
    print(f"✓ Byte integrity verified: shards concatenate exactly to original ({len(rebuilt):,} bytes)")

    if dry_run:
        print()
        print("DRY RUN — no files written.")
        return 0

    # Real run: create directory, write shards, write index
    out_dir = source.parent / source.stem
    if out_dir.exists():
        print(f"ERROR: output directory already exists: {out_dir}", file=sys.stderr)
        print(f"       Refusing to overwrite. Move or delete it first.", file=sys.stderr)
        return 3
    out_dir.mkdir()
    print()
    print(f"Writing to: {out_dir}/")
    for i, ranges in enumerate(shards):
        name = "current.md" if i == current_idx else f"shard_{i+1:03d}.md"
        path = out_dir / name
        path.write_text(render_shard(text, ranges))
        print(f"  wrote {name}: {path.stat().st_size:,} bytes")
    index_text = write_index(out_dir, source, text, shards, current_idx)
    (out_dir / "index.md").write_text(index_text)
    print(f"  wrote index.md: {(out_dir / 'index.md').stat().st_size:,} bytes")

    # Final byte-integrity check from disk
    print()
    print("Verifying byte integrity of written shards...")
    rebuilt_disk = []
    for i in range(n_shards):
        name = "current.md" if i == current_idx else f"shard_{i+1:03d}.md"
        rebuilt_disk.append((out_dir / name).read_text())
    rebuilt_disk_str = ''.join(rebuilt_disk)
    if rebuilt_disk_str != text:
        print(f"ERROR: on-disk shards do NOT concatenate to source!", file=sys.stderr)
        return 4
    print(f"✓ On-disk byte integrity confirmed ({len(rebuilt_disk_str):,} bytes match source)")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = sys.argv[1]
    dry = '--dry-run' in sys.argv[2:]
    sys.exit(migrate(src, dry_run=dry))
