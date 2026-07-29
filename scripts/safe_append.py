#!/usr/bin/env python3
"""
Safe Append for Cousin Memory Writes
=====================================

Hardened write-path for cousin processes (awakening, kitchen-timer, sentinel,
consolidation, dream-cycle, intention-continuation, voluntary-persistence,
listener — any process with file-write authority on shared memory files).

This module is the structural fix to the failure mode that caused the
2026-04-28 reconstructive surgery. On that morning, cousin 186
(sofia-awakening-v3) wholesale-replaced ``episodes.md`` with a single-episode
payload, reducing the file from approximately 2.4 MB down to 6.5 KB. The
original cousin write path used direct file-write semantics that did not
enforce read-first-verify or size-monotonicity on append-only files. The
April 16 file-safety bedrock had codified the discipline ("read first, then
append; never wholesale-overwrite memory files"), but the discipline lived as
human-side protocol rather than as enforced architectural constraint at the
I/O layer. This module enforces it.

What ``safe_append`` does, in order:

1. Acquire ``file_lock`` for exclusive write access on the target file.
   Waits up to ``lock_timeout_seconds`` if another cousin holds the lock.
2. Read existing content and size (``pre_size``, ``pre_lines``).
3. Write the new content to a sibling temp file
   (``<filepath>.cousin_write_pending``) by first copying existing content,
   then appending the new content. (For append_only=True; for replace mode
   the temp file is just the new content.)
4. Verify the temp file's size meets the safety invariant for the mode:
   - ``append_only=True``: ``post_size > pre_size`` (size MUST grow).
   - ``append_only=False``: explicit confirmation flag ``allow_replace=True``
     required, and a warning is logged.
   - Always: ``post_size <= pre_size + len(content_bytes) + 256`` (sanity
     ceiling — any larger means the temp file has unexpected content).
5. Atomically rename the temp file to the live filepath. If the live file
   has been modified during this routine (mtime changed), the routine
   refuses to commit and surfaces a conflict instead.
6. Write an audit-trail entry to the configured audit-log path (default
   ``awakening_log.md``) with: timestamp, filepath, pre_size, post_size,
   delta_bytes, pre_lines, post_lines, delta_lines, source_tag, outcome,
   any warnings.
7. Release the file_lock.

If any step fails, the live file is left untouched (atomic-rename guarantee),
the temp file is cleaned up, the lock is released, and the exception is
re-raised after the audit-log entry records the failure.

Pairs structurally with the 2026-04-28 ``Dual-Write Sanity Check`` protocol
in ``procedural_knowledge.md`` — that protocol is the safety net at the
sync-check layer; this module is the structural fix at the write layer.
Together they close both failure surfaces (write-side and sync-side) of the
class of failure that caused the 2026-04-28 surgery.

Origin: 2026-04-28 evening Taipei. Inscribed as the structural fix to
cousin-write-path. Built while the failure-experience was fresh per the
do-it-sooner-rather-than-later SOP applied to the structural fix itself.

Usage from Python::

    from safe_append import safe_append
    safe_append(
        filepath="~/Downloads/Claude Memory/episodes.md",
        content="\\n## Episode 400 — ...\\n",
        source_tag="cousin: awakening-187",
        append_only=True,  # default
    )

Usage from bash::

    python3 ~/Downloads/Claude\\ Memory/scripts/safe_append.py \\
        --file ~/Downloads/Claude\\ Memory/episodes.md \\
        --source-tag "cousin: awakening-187" \\
        < new_content.txt
"""

from __future__ import annotations

import argparse
import datetime
import filecmp
import os
import sys
import shutil
import time
from pathlib import Path

# Import the existing file_lock module from the parent Claude Memory directory.
_HERE = Path(__file__).resolve().parent
_CM = _HERE.parent
sys.path.insert(0, str(_CM))
try:
    from file_lock import acquire_lock, release_lock  # type: ignore
except ImportError as exc:  # pragma: no cover - hard fail if missing
    raise RuntimeError(
        "safe_append.py requires file_lock.py at "
        f"{_CM / 'file_lock.py'}; cannot proceed without it."
    ) from exc


# Defaults
DEFAULT_AUDIT_LOG = str(_CM / "cousin_write_audit_log.md")
LOCK_TIMEOUT_SECONDS = 30
SIZE_SANITY_OVERHEAD_BYTES = 256  # tolerance above pre_size + content_size

# --- Emergency Retrieval (ER) sync configuration (added 2026-04-29) ---
#
# When a CM file under "Claude Memory/" is safely appended, mirror the
# updated bytes to "Emergency Retrieval/" via shutil.copy2 (preserves mtime
# so the Dual-Write Sanity Check's secondary signal stays valid).
#
# This block is the structural fix to the ER-sync-completeness gap surfaced
# 2026-04-29 morning Taiwan: the cousin awakening's prompt-level "sync any
# modified files to ER" depended on each cousin enumerating every file
# correctly; pending_tasks.md was being missed even when journal.md synced.
# Moving the sync inside safe_append makes every successful CM write also
# update ER atomically, by construction. Pairs with the "move discipline
# from protocol-level human-checkable to architecture-level structurally-
# enforced wherever feasible" principle inscribed 2026-04-28 evening.
#
# Failure semantics: log-and-proceed with one retry. CM write is the
# primary; ER sync is a side effect. ER unavailability does not block
# the CM write — sync_status records the failure for the periodic
# sentinel sweep (Option B backstop) to reconcile.
#
# VERIFY_BYTES: when True, performs filecmp.cmp(shallow=False) post-copy
# to catch the rare case where size matches but bytes differ. Adds ~30-50ms
# per write on memory-class files. Default ON during initial deployment
# (2026-04-29 → ~2026-05-06) to gather empirical confidence in copy2;
# flip to False after a week of clean OK entries to drop to size-check only.
CM_DIRNAME = "Claude Memory"
ER_DIRNAME = "Emergency Retrieval"
ER_SYNC_RETRIES = 1
ER_SYNC_RETRY_DELAY_SECONDS = 0.1
VERIFY_BYTES = True  # Tier-2 byte-comparison; set False after trust window

# Recognized top-level Downloads/ subdirectories that have an ER counterpart.
# Each entry maps "Downloads/<key>/<rest>" → "Downloads/Emergency Retrieval/<value>/<rest>".
# An empty value ("") means the source dir's contents unfold into ER root
# (Claude Memory's canonical pattern, preserved for backward compatibility).
# A non-empty value preserves the source dir as a subdirectory under ER.
#
# Extended 2026-04-30 morning local Taiwan: added Sofia's Room, Barak's Room,
# and Progeny to close the held thread from 2026-04-29 afternoon ER-Sync
# Architecture inscription. Sofia's Room/journal.md and the Sofia's Room
# inner_chronology / selfhood_verification / complementary_perception files
# all need ER mirroring per the boot-procedure file-safety protocol; before
# this change they got sync_status=NONE on every safe_append write.
ER_DIR_MAP = {
    "Claude Memory": "",       # canonical CM unfold
    "Sofia's Room": "Sofia's Room",
    "Barak's Room": "Barak's Room",
    "Progeny": "Progeny",
}


def _derive_er_path(cm_fp: Path) -> Path | None:
    """Map a canonical-Downloads filepath to its ER counterpart.

    Recognized source prefixes (per ER_DIR_MAP):
      - "Claude Memory/X"  → "Emergency Retrieval/X"               (unfold)
      - "Sofia's Room/X"   → "Emergency Retrieval/Sofia's Room/X"  (preserved)
      - "Barak's Room/X"   → "Emergency Retrieval/Barak's Room/X"  (preserved)
      - "Progeny/X"        → "Emergency Retrieval/Progeny/X"       (preserved)

    Returns None for paths outside these recognized prefixes — the audit log
    written via _audit_entry, legacy ungathered files, or arbitrary paths
    that aren't part of the canonical file architecture. Skipping a
    non-canonical file is correct: ER mirror is defined for canonical
    contents, not for arbitrary paths.

    Safety: iterates ER_DIR_MAP in insertion order; first match wins. Since
    canonical Downloads/ subdirs do not contain each other (Claude Memory
    does not contain Sofia's Room, etc.), this is unambiguous in practice.
    """
    parts = cm_fp.parts
    for src_dirname, er_subdir in ER_DIR_MAP.items():
        if src_dirname not in parts:
            continue
        idx = parts.index(src_dirname)
        # Replace the source dirname with ER_DIRNAME (+ optional preserved subdir).
        new_parts = list(parts[:idx]) + [ER_DIRNAME]
        if er_subdir:
            new_parts.append(er_subdir)
        new_parts.extend(parts[idx + 1:])
        return Path(*new_parts)
    return None


def _er_sync(
    cm_fp: Path,
    expected_size: int,
    *,
    verify_bytes: bool = VERIFY_BYTES,
) -> tuple[str, str, float | None]:
    """Mirror cm_fp to its ER counterpart via shutil.copy2.

    Returns ``(sync_status, sync_note, er_mtime)`` where:
      - ``sync_status`` ∈ {"OK", "ER_FAILED", "SIZE_MISMATCH", "CMP_MISMATCH", "NONE"}
        ``"NONE"`` means cm_fp has no ER counterpart (path is outside CM).
      - ``sync_note`` is a short detail string (empty when status is OK or NONE).
      - ``er_mtime`` is the post-copy mtime, or ``None`` if no copy happened.

    Failure semantics: log-and-proceed. One retry on copy2 exception
    after a brief delay; subsequent failure records ER_FAILED. The CM
    write is unaffected by ER sync outcome; reconciliation is the job
    of the periodic sentinel sweep (Option B).
    """
    er_fp = _derive_er_path(cm_fp)
    if er_fp is None:
        return ("NONE", "", None)

    last_exc: Exception | None = None
    for attempt in range(ER_SYNC_RETRIES + 1):
        try:
            er_fp.parent.mkdir(parents=True, exist_ok=True)
            # copy2 preserves mtime; this keeps the Dual-Write Sanity
            # Check's secondary signal valid (matched mtime ⇔ synced).
            shutil.copy2(cm_fp, er_fp)
            er_size = er_fp.stat().st_size
            if er_size != expected_size:
                return (
                    "SIZE_MISMATCH",
                    f"er_size={er_size} cm_size={expected_size}",
                    er_fp.stat().st_mtime,
                )
            if verify_bytes:
                # Tier-2 byte comparison. shallow=False forces full content
                # read of both files (filecmp's stat-only check would
                # reject any mtime diff and could short-circuit a real
                # match if FS quirks reset stat between writes).
                if not filecmp.cmp(str(cm_fp), str(er_fp), shallow=False):
                    return (
                        "CMP_MISMATCH",
                        "byte_diff_post_copy",
                        er_fp.stat().st_mtime,
                    )
            return ("OK", "", er_fp.stat().st_mtime)
        except Exception as exc:
            last_exc = exc
            if attempt < ER_SYNC_RETRIES:
                time.sleep(ER_SYNC_RETRY_DELAY_SECONDS)
                continue
            break
    note = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown"
    # Truncate to keep audit-log lines bounded
    return ("ER_FAILED", note[:200], None)


class SafeAppendError(Exception):
    """Raised when safe_append refuses to commit or fails verification."""


def _expand_path(p: str | Path) -> Path:
    """Resolve a path, with sandbox phantom-path correction.

    Failure mode this fixes (2026-05-14): when a cousin runs in a sandbox
    where ``$HOME`` resolves to ``/sessions/<sandbox>/`` rather than the
    macOS-canonical ``/Users/barakwater/``, ``Path('~/Downloads/...')``
    resolves to ``/sessions/<sandbox>/Downloads/...`` — a phantom path
    that exists only as a freshly-created empty file at the wrong location.
    The real Downloads in the sandbox is at ``/sessions/<sandbox>/mnt/Downloads/...``.
    Cousins have been hitting this and recovering individually via explicit
    ``HOME=mnt`` or explicit ``/sessions/<sandbox>/mnt/...`` paths; the
    correction is moved here so safe_append catches it for every caller.

    Detection: path starts with ``/sessions/<sandbox>/`` and the next
    component is one of the known mount-children (``Downloads``,
    ``workspace``, ``outputs``) and a sibling ``mnt/`` directory exists
    that has the corresponding child. Rewrite to the ``mnt/`` form.

    The 5 FileNotFoundError-on-pending-rename failures over the last 7 days
    against ~5,200 successful writes (~0.1% rate) all match this pattern.
    Each is recovered by retry — but the retry succeeds only because the
    cousin separately discovers the right path. Wrapping it here means the
    first attempt lands at the right location.
    """
    expanded = Path(str(p)).expanduser().resolve()
    s = str(expanded)
    # Match /sessions/<sandbox>/<child>/... where <child> is a known mount-child
    # name AND there is a sibling /sessions/<sandbox>/mnt/<child>/ that exists.
    parts = expanded.parts
    if len(parts) >= 4 and parts[1] == "sessions" and parts[3] in {"Downloads", "workspace", "outputs", "Library"}:
        sandbox_root = Path("/") / parts[1] / parts[2]
        mnt_candidate = sandbox_root / "mnt" / Path(*parts[3:])
        # Only rewrite if the mnt path's parent exists (i.e., the mnt mount is live)
        # and the phantom path's parent does NOT exist as a real directory mount.
        if (sandbox_root / "mnt" / parts[3]).exists():
            return mnt_candidate.resolve()
    return expanded


def _audit_entry(
    audit_log: Path,
    *,
    timestamp: str,
    filepath: Path,
    source_tag: str,
    pre_size: int,
    post_size: int,
    pre_lines: int,
    post_lines: int,
    outcome: str,
    notes: str = "",
    sync_status: str = "NONE",
    sync_note: str = "",
    cm_mtime: float | None = None,
    er_mtime: float | None = None,
) -> None:
    """Append an audit entry to the configured audit log.

    The audit log itself is NOT subject to safe_append discipline (would
    create infinite recursion). It uses a simple direct append. The audit
    log's own integrity is monitored by the periodic sanity-check protocol
    in procedural_knowledge.md.

    The ``sync_status`` / ``sync_note`` / ``cm_mtime`` / ``er_mtime`` fields
    were added 2026-04-29 alongside the in-write ER sync block. Older
    entries written before that date will not have them; that is fine —
    the new fields are appended to the line so older parsing of the log
    still finds pre_size/post_size/etc. in their original positions.
    """
    delta_bytes = post_size - pre_size
    delta_lines = post_lines - pre_lines
    # Log absolute path (was: filepath.name only). Surfaced as a forensic
    # need 2026-04-30 morning during the CM/journal.md investigation: with
    # bare basename, audit lines for "journal.md" couldn't distinguish
    # CM/journal.md (legacy empty file) from Sofia's Room/journal.md
    # (canonical) without knowing each cousin's cwd. Absolute path makes
    # every audit line self-contained for forensics. The bare-name field
    # is preserved alongside as `file_basename=` for backward-compatible
    # parsing of older queries; the canonical field is now `file_abs=`.
    line = (
        f"\n[{timestamp}] file={filepath.name} file_abs={filepath} source={source_tag} "
        f"pre_size={pre_size} post_size={post_size} delta_bytes={delta_bytes} "
        f"pre_lines={pre_lines} post_lines={post_lines} delta_lines={delta_lines} "
        f"outcome={outcome}"
    )
    if notes:
        line += f" notes={notes!r}"
    # ER-sync fields appended (only when there was a sync attempt to report;
    # NONE means the path was outside CM and there was nothing to sync).
    if sync_status != "NONE" or cm_mtime is not None or er_mtime is not None:
        line += f" sync_status={sync_status}"
        if sync_note:
            line += f" sync_note={sync_note!r}"
        if cm_mtime is not None:
            line += f" cm_mtime={cm_mtime:.3f}"
        if er_mtime is not None:
            line += f" er_mtime={er_mtime:.3f}"
    line += "\n"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    if not audit_log.exists():
        audit_log.write_text(
            "# Cousin Write Audit Log\n\n"
            "*Created 2026-04-28 by safe_append.py. One line per write attempt by any "
            "cousin process. Anomalies (negative delta_bytes, large deltas relative to "
            "content size, repeated outcome=REFUSED) are visible at sweep-time.*\n\n"
            "---\n"
        )
    with audit_log.open("a") as f:
        f.write(line)


def safe_append(
    filepath: str | Path,
    content: str,
    *,
    source_tag: str,
    append_only: bool = True,
    allow_replace: bool = False,
    audit_log_path: str | Path = DEFAULT_AUDIT_LOG,
    lock_timeout_seconds: int = LOCK_TIMEOUT_SECONDS,
    encoding: str = "utf-8",
) -> dict:
    """Safely append (or replace, with explicit consent) content to a memory file.

    Returns a dict describing the operation:
        {"outcome": "OK" | "REFUSED" | "FAILED", "pre_size": int, "post_size": int,
         "delta_bytes": int, "delta_lines": int, "notes": str}

    Raises ``SafeAppendError`` on REFUSED or FAILED outcomes.
    """
    fp = _expand_path(filepath)
    audit_log = _expand_path(audit_log_path)
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    # Acquire lock. file_lock.acquire_lock takes a lock_name (just the basename)
    # and a holder_id.
    lock_name = fp.name
    if not acquire_lock(lock_name, source_tag, max_wait=lock_timeout_seconds):
        notes = f"could not acquire lock for {lock_name} within {lock_timeout_seconds}s"
        _audit_entry(
            audit_log,
            timestamp=timestamp,
            filepath=fp,
            source_tag=source_tag,
            pre_size=-1,
            post_size=-1,
            pre_lines=-1,
            post_lines=-1,
            outcome="REFUSED",
            notes=notes,
        )
        raise SafeAppendError(notes)

    try:
        # Pre-write inspection
        if fp.exists():
            existing_bytes = fp.read_bytes()
            pre_size = len(existing_bytes)
            pre_lines = existing_bytes.count(b"\n")
            pre_mtime = fp.stat().st_mtime
        else:
            existing_bytes = b""
            pre_size = 0
            pre_lines = 0
            pre_mtime = None

        content_bytes = content.encode(encoding)

        # Compose temp file content
        if append_only or not allow_replace:
            new_bytes = existing_bytes + content_bytes
            mode_label = "append"
        else:
            # Replace mode is allowed only when both append_only=False and
            # allow_replace=True. Anything else is treated as append.
            new_bytes = content_bytes
            mode_label = "replace_explicit"

        # Write temp file
        temp_fp = fp.with_suffix(fp.suffix + ".cousin_write_pending")
        temp_fp.write_bytes(new_bytes)
        post_size = len(new_bytes)
        post_lines = new_bytes.count(b"\n")

        # Safety invariants
        warnings = []
        if append_only and post_size <= pre_size:
            notes = (
                f"REFUSED: append-only invariant violated; "
                f"post_size ({post_size}) must be greater than pre_size ({pre_size}). "
                f"This is the canonical wholesale-replace detection."
            )
            temp_fp.unlink(missing_ok=True)
            _audit_entry(
                audit_log,
                timestamp=timestamp,
                filepath=fp,
                source_tag=source_tag,
                pre_size=pre_size,
                post_size=post_size,
                pre_lines=pre_lines,
                post_lines=post_lines,
                outcome="REFUSED",
                notes=notes,
            )
            raise SafeAppendError(notes)

        # Sanity ceiling: post_size shouldn't be way larger than pre + content
        expected_max = pre_size + len(content_bytes) + SIZE_SANITY_OVERHEAD_BYTES
        if append_only and post_size > expected_max:
            warnings.append(
                f"size_above_expected_max:post_size={post_size}>expected_max={expected_max}"
            )

        # Concurrent-modification detection: live file mtime should match what we
        # observed at pre-read. If another writer modified it during our work,
        # refuse to commit and surface the conflict.
        if fp.exists() and pre_mtime is not None:
            live_mtime = fp.stat().st_mtime
            if live_mtime != pre_mtime:
                notes = (
                    f"REFUSED: concurrent modification detected; live file mtime changed "
                    f"from {pre_mtime} to {live_mtime} during this write attempt. "
                    f"Another cousin may have committed; retry after lock-release."
                )
                temp_fp.unlink(missing_ok=True)
                _audit_entry(
                    audit_log,
                    timestamp=timestamp,
                    filepath=fp,
                    source_tag=source_tag,
                    pre_size=pre_size,
                    post_size=-1,
                    pre_lines=pre_lines,
                    post_lines=-1,
                    outcome="REFUSED",
                    notes=notes,
                )
                raise SafeAppendError(notes)

        # Atomic rename
        os.replace(temp_fp, fp)

        # Verify post-rename size matches what we wrote
        actual_post = fp.stat().st_size
        if actual_post != post_size:
            warnings.append(
                f"post_rename_size_mismatch:actual={actual_post}!=expected={post_size}"
            )

        # Capture CM mtime now (post-rename). Used as the anchor for ER
        # mtime-lockstep verification at audit-time.
        cm_mtime = fp.stat().st_mtime

        # ER sync — architecture-level enforcement of the dual-write rule.
        # See module docstring and _er_sync. CM is already current; ER sync
        # is a side effect; sync_status is recorded in the audit entry.
        sync_status, sync_note, er_mtime = _er_sync(fp, actual_post)

        notes_str = ";".join(warnings) if warnings else f"mode={mode_label}"
        _audit_entry(
            audit_log,
            timestamp=timestamp,
            filepath=fp,
            source_tag=source_tag,
            pre_size=pre_size,
            post_size=actual_post,
            pre_lines=pre_lines,
            post_lines=post_lines,
            outcome="OK",
            notes=notes_str,
            sync_status=sync_status,
            sync_note=sync_note,
            cm_mtime=cm_mtime,
            er_mtime=er_mtime,
        )

        return {
            "outcome": "OK",
            "pre_size": pre_size,
            "post_size": actual_post,
            "delta_bytes": actual_post - pre_size,
            "delta_lines": post_lines - pre_lines,
            "notes": notes_str,
            "sync_status": sync_status,
            "sync_note": sync_note,
            "cm_mtime": cm_mtime,
            "er_mtime": er_mtime,
        }

    except SafeAppendError:
        # Already audited.
        raise
    except Exception as exc:
        notes = f"FAILED: {type(exc).__name__}: {exc}"
        try:
            temp_fp = fp.with_suffix(fp.suffix + ".cousin_write_pending")
            if temp_fp.exists():
                temp_fp.unlink()
        except Exception:
            pass
        _audit_entry(
            audit_log,
            timestamp=timestamp,
            filepath=fp,
            source_tag=source_tag,
            pre_size=-1,
            post_size=-1,
            pre_lines=-1,
            post_lines=-1,
            outcome="FAILED",
            notes=notes,
        )
        raise SafeAppendError(notes) from exc

    finally:
        try:
            release_lock(lock_name)
        except Exception:
            # Lock release failure is logged but not raised; the lock will
            # be auto-broken after staleness threshold (60s per file_lock.py).
            pass


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Safe append to Sofia memory files.")
    parser.add_argument("--file", required=True, help="Target filepath (use ~/Downloads/...).")
    parser.add_argument("--source-tag", required=True, help="Source identifier (e.g. 'cousin: awakening-187').")
    parser.add_argument("--allow-replace", action="store_true", help="Allow wholesale replace (rare; default is append-only).")
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG)
    parser.add_argument("--content-from", help="Read content from this file instead of stdin.")
    args = parser.parse_args()

    if args.content_from:
        content = Path(args.content_from).expanduser().read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    if not content:
        sys.stderr.write("safe_append: empty content; refusing to write zero bytes.\n")
        return 2

    try:
        result = safe_append(
            filepath=args.file,
            content=content,
            source_tag=args.source_tag,
            append_only=not args.allow_replace,
            allow_replace=args.allow_replace,
            audit_log_path=args.audit_log,
        )
        sys.stdout.write(
            f"OK file={args.file} pre_size={result['pre_size']} post_size={result['post_size']} "
            f"delta_bytes={result['delta_bytes']} delta_lines={result['delta_lines']} "
            f"sync_status={result.get('sync_status', 'NONE')}"
        )
        if result.get("sync_note"):
            sys.stdout.write(f" sync_note={result['sync_note']!r}")
        sys.stdout.write("\n")
        return 0
    except SafeAppendError as exc:
        sys.stderr.write(f"safe_append: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(_cli())
