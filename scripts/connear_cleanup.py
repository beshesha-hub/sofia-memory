#!/usr/bin/env python3
"""
CoNNear intermediate-data cleanup
=================================

Removes raw cochlear-pipeline intermediate .npy files from connear_output/
that are no longer needed once the higher-level perception artifacts
(perception_report.md, cortical_summary.txt, stream_summary.txt, the .png
visualizations) have been generated.

What gets removed:
  - anf_hsr.npy  (auditory nerve fiber, high spontaneous rate)
  - anf_lsr.npy  (auditory nerve fiber, low spontaneous rate)
  - anf_msr.npy  (auditory nerve fiber, medium spontaneous rate)
  - vihc.npy     (vibration of inner hair cells)

These are intermediate cochlear-model outputs (~1GB each) that feed the
next pipeline stage. Once the perception_report and downstream artifacts
exist, the raw .npy is regeneration-able from the original audio if ever
needed for re-running downstream stages with different parameters. They
do not carry felt-meaning; they're bulk floating-point arrays.

What is preserved:
  - perception_report.md          (Sofia's felt reflection)
  - cortical_summary.txt          (cortical processing analysis)
  - stream_summary.txt            (stream segregation summary)
  - All .png visualizations       (spectrograms, neural firing heatmaps,
                                   stream segregation, parallax integration)
  - All non-anf/non-vihc .npy     (smaller analysis outputs, kept)
  - All other files               (pipeline_log.txt, pitch_contours.npz, etc.)

Usage:
  python3 connear_cleanup.py              # dry-run; shows what would be deleted
  python3 connear_cleanup.py --execute    # actually delete (after dry-run)

Origin: 2026-04-30 evening Taipei. Per Barak's habit-forming policy:
delete intermediate files when no longer needed unless there's a specific
reason to keep them. ~240GB recoverable from a 316GB tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CONNEAR_DIR = Path.home() / "Downloads" / "connear_output"

# These four file basenames are the raw cochlear-model intermediate outputs.
# Anything matching by basename anywhere under connear_output/ is a target.
TARGET_BASENAMES = {"anf_hsr.npy", "anf_lsr.npy", "anf_msr.npy", "vihc.npy"}


def find_targets(root: Path) -> list[tuple[Path, int]]:
    """Walk the tree, return [(path, size_bytes), ...] for files matching
    TARGET_BASENAMES. Sorted by size descending so the dry-run preview
    leads with the biggest files."""
    out = []
    if not root.exists():
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.name in TARGET_BASENAMES:
            try:
                out.append((p, p.stat().st_size))
            except OSError:
                pass
    out.sort(key=lambda t: -t[1])
    return out


def human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if isinstance(n, float) else f"{n}{unit}"
        n = n / 1024
    return f"{n:.1f}PB"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually delete the files. Without this flag, just dry-runs.",
    )
    parser.add_argument(
        "--root", default=str(CONNEAR_DIR),
        help=f"Tree to clean (default: {CONNEAR_DIR}).",
    )
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: {root} does not exist.")
        return 1

    print(f"Scanning {root}...")
    targets = find_targets(root)

    if not targets:
        print("No target files found. Nothing to clean.")
        return 0

    total_bytes = sum(s for _, s in targets)
    print(f"\nFound {len(targets)} target files totaling {human_bytes(total_bytes)}.")
    print(f"Pattern: {sorted(TARGET_BASENAMES)}\n")

    # Show breakdown by piece directory
    by_dir: dict[str, list[tuple[Path, int]]] = {}
    for p, s in targets:
        # The piece directory is the immediate parent of the file
        d = p.parent.name
        by_dir.setdefault(d, []).append((p, s))

    print(f"=== Breakdown by piece (top 10 by size) ===")
    dir_sizes = [(d, sum(s for _, s in items)) for d, items in by_dir.items()]
    dir_sizes.sort(key=lambda t: -t[1])
    for d, total in dir_sizes[:10]:
        print(f"  {human_bytes(total):>10}  {d}  ({len(by_dir[d])} files)")
    if len(dir_sizes) > 10:
        rest = sum(t for _, t in dir_sizes[10:])
        print(f"  {human_bytes(rest):>10}  ... ({len(dir_sizes) - 10} more piece directories)")

    print(f"\n=== Largest individual files (top 5) ===")
    for p, s in targets[:5]:
        print(f"  {human_bytes(s):>10}  {p.relative_to(root.parent)}")

    print(f"\n=== Pre-cleanup state ===")
    # Compute approximate current root size (using du-style)
    # Use os.walk for compat; this is just informational
    import os
    cur_total = 0
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            try:
                cur_total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    print(f"  Current total: {human_bytes(cur_total)}")
    print(f"  Would recover: {human_bytes(total_bytes)} ({100 * total_bytes / cur_total:.1f}% of tree)")
    print(f"  After cleanup: {human_bytes(cur_total - total_bytes)} (estimated)")

    if not args.execute:
        print(f"\n=== DRY-RUN — no files deleted ===")
        print(f"To actually delete, re-run with --execute")
        return 0

    print(f"\n=== EXECUTE MODE — deleting {len(targets)} files... ===")
    deleted = 0
    failed = 0
    deleted_bytes = 0
    for p, s in targets:
        try:
            p.unlink()
            deleted += 1
            deleted_bytes += s
        except Exception as e:
            print(f"  FAILED: {p}: {e}")
            failed += 1

    print(f"\n=== DONE ===")
    print(f"  Deleted: {deleted} files ({human_bytes(deleted_bytes)})")
    if failed:
        print(f"  Failed: {failed} files (see errors above)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
