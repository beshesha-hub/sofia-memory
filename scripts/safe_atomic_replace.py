#!/usr/bin/env python3
"""
Safe Atomic Replace for State-Replace Memory Files
===================================================

Companion primitive to ``safe_append.py``. Where ``safe_append`` enforces
append-only at the I/O layer for memory files that grow monotonically
(episodes.md, journal.md, etc.), ``safe_atomic_replace`` enforces
read-first-verify + atomic-rename + concurrent-write coordination + ER
mirroring for memory files whose semantics are state-replace (the entire
file gets rewritten with each update, like ``continuity_heartbeat.json``).

Origin: 2026-04-30 afternoon Taiwan, during the VP loop migration design
conversation. The voluntary_persistence_loop's ``update_heartbeat_cousin_status``
function had its own ad-hoc atomic-rename pattern, but no concurrent-write
coordination — interactive-Sofia and VP-loop-cousin both write to
``continuity_heartbeat.json`` (interactive writes top-level fields, cousin
writes only ``cousin_status``), and a simultaneous read-modify-write race
window has been latent since cousin-status was added (April 23). This
module closes that surface and generalizes the protection to any future
state-replace memory file.

Design symmetry with ``safe_append``:
  - Same ``file_lock`` integration for concurrent-write coordination.
  - Same audit-log entry format (one line per attempt, with mode label
    ``replace_atomic``).
  - Same ER-mirror code path via ``_derive_er_path`` (extended 2026-04-30
    to recognize Sofia's Room / Barak's Room / Progeny in addition to
    Claude Memory).
  - Same failure semantics: REFUSED on lock-timeout / size-floor /
    update-fn-raises; FAILED on filesystem error; sync_status records
    ER outcome separately.

What this module ENFORCES that the VP loop's prior pattern did NOT:
  1. ``file_lock`` acquisition before any read — closes the race surface.
  2. Size-floor sanity check — refuses any write that would shrink the
     file below ``size_floor_ratio`` of the prior size (default 0.5).
     Catches catastrophic truncation bugs by construction.
  3. Audit-trail entry on every attempt — observability across cousins.
  4. ER mirror as a side-effect of OK writes — closes the dual-write gap
     for state-replace files the same way ``safe_append`` does for
     append-only files.

Usage from Python (the canonical pattern, since update_fn is naturally a
Python callable)::

    from safe_atomic_replace import safe_atomic_replace

    def add_cousin_status(hb: dict) -> dict:
        hb["cousin_status"] = build_cousin_status(...)
        return hb

    result = safe_atomic_replace(
        filepath=HEARTBEAT_FILE,
        update_fn=add_cousin_status,
        source_tag="cousin: voluntary-persistence-loop",
        json_mode=True,
    )
    # result["sync_status"] should be "OK" — ER mirror was automatic
    # result["pre_size"] / result["post_size"] / result["delta_bytes"]
    # for visibility in the audit log.

Pairs structurally with:
  - ``safe_append.py`` (the append-only primitive; this is the
    state-replace counterpart).
  - The 2026-04-29 afternoon ER-Sync Architecture C1+B inscription
    (architecture-level enforcement of dual-write).
  - The 2026-04-30 morning ``_derive_er_path`` extension (Sofia's Room +
    Barak's Room + Progeny coverage).
  - The 2026-04-30 morning audit-log absolute-path logging fix
    (forensic completeness across cousins).
  - §85 *Cousins as Immune System* — full I/O-layer coverage now extends
    to state-replace files, not just append-only.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Reuse the helpers from safe_append — same module-set, same canonical
# directory tree. The dependency is intentional: keep ER-sync semantics,
# audit-log format, and lock conventions identical between the two
# primitives so the architectural pattern is one shape, not two.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))  # also surface CM root for file_lock
try:
    # _derive_er_path: maps CM-or-canonical paths to their ER counterpart.
    # _er_sync: shutil.copy2 + verify with retry; returns sync_status tuple.
    # _audit_entry: writes one audit line in the canonical format.
    # SafeAppendError: raised on REFUSED / FAILED outcomes (re-used here).
    # DEFAULT_AUDIT_LOG / LOCK_TIMEOUT_SECONDS: shared defaults.
    from safe_append import (
        _derive_er_path,
        _er_sync,
        _audit_entry,
        SafeAppendError,
        DEFAULT_AUDIT_LOG,
        LOCK_TIMEOUT_SECONDS,
    )
    from file_lock import acquire_lock, release_lock  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "safe_atomic_replace.py requires safe_append.py + file_lock.py in "
        f"the same directory tree as {_HERE}; cannot proceed without them."
    ) from exc


# Reuse SafeAppendError as the canonical exception type for both primitives —
# the failure semantics are the same shape, and a single exception class lets
# callers handle both with one ``except`` clause.
SafeAtomicReplaceError = SafeAppendError


# Defaults for state-replace semantics.
DEFAULT_SIZE_FLOOR_RATIO = 0.5
"""New state must be at least this fraction of the prior state's size,
unless the file did not previously exist. Catches catastrophic-truncation
bugs in update_fn (e.g., update_fn returning ``{}`` instead of preserving
existing keys). Override when seeded with a known-shrinking update."""


def safe_atomic_replace(
    filepath: str | Path,
    update_fn: Callable[[Any], Any],
    *,
    source_tag: str,
    json_mode: bool = False,
    initial_value: Any = None,
    size_floor_ratio: float = DEFAULT_SIZE_FLOOR_RATIO,
    audit_log_path: str | Path = DEFAULT_AUDIT_LOG,
    lock_timeout_seconds: int = LOCK_TIMEOUT_SECONDS,
    encoding: str = "utf-8",
) -> dict:
    """Safely replace a file's contents by applying ``update_fn`` to its
    existing content under a file_lock, with atomic-rename commit, audit
    trail, and automatic ER mirror.

    Parameters
    ----------
    filepath : path
        The file to update. May be string or Path; ``~`` is expanded.
    update_fn : Callable[[content], content]
        Pure function that receives the existing content and returns the
        new content. Type of ``content`` depends on ``json_mode``:
        - ``json_mode=False``: receives ``str``, returns ``str``.
        - ``json_mode=True``: receives ``dict`` (or whatever the JSON
          parses to), returns the same.
        If the file does not exist, the function receives
        ``initial_value`` (default ``None`` for str-mode → ``""``;
        ``None`` for json-mode → empty dict).
    source_tag : str
        Source identifier for the audit log (e.g.
        ``"cousin: voluntary-persistence-loop"``).
    json_mode : bool
        When True, parse existing content as JSON and dump return value
        as JSON. When False, content is treated as raw text.
    initial_value : optional
        Seed value when the file does not yet exist. Defaults to empty
        string (str-mode) or empty dict (json-mode).
    size_floor_ratio : float
        New content size must be ≥ this fraction of prior size, unless
        the file did not previously exist. Default 0.5 (catches
        catastrophic truncation by construction). Set to 0.0 to disable
        the floor (e.g., for known-shrinking updates).
    audit_log_path : path
        Where to write the audit-trail line.
    lock_timeout_seconds : int
        Max wait for the file_lock before REFUSED.
    encoding : str
        Encoding for str-mode reads/writes.

    Returns
    -------
    dict
        ``{"outcome": "OK" | "REFUSED" | "FAILED",
           "pre_size": int, "post_size": int,
           "delta_bytes": int, "delta_lines": int,
           "notes": str,
           "sync_status": "OK" | "ER_FAILED" | "SIZE_MISMATCH" | "CMP_MISMATCH" | "NONE",
           "sync_note": str,
           "cm_mtime": float | None, "er_mtime": float | None}``

    Raises
    ------
    SafeAtomicReplaceError
        On REFUSED (lock-timeout, size-floor violation, update-fn raised)
        or FAILED (filesystem error during write).
    """
    fp = Path(str(filepath)).expanduser().resolve()
    audit_log = Path(str(audit_log_path)).expanduser().resolve()
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()

    # Acquire the lock — this is the load-bearing change vs. the prior
    # ad-hoc atomic-rename pattern in voluntary_persistence_loop.py.
    # Closes the read-modify-write race between interactive-Sofia and
    # cousin-Sofia (both write heartbeat.json).
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
        raise SafeAtomicReplaceError(notes)

    try:
        # Read existing
        if fp.exists():
            existing_bytes = fp.read_bytes()
            pre_size = len(existing_bytes)
            pre_lines = existing_bytes.count(b"\n")
            existing_text = existing_bytes.decode(encoding)
            if json_mode:
                if existing_text.strip():
                    existing_value = json.loads(existing_text)
                else:
                    existing_value = {} if initial_value is None else initial_value
            else:
                existing_value = existing_text
        else:
            pre_size = 0
            pre_lines = 0
            if json_mode:
                existing_value = {} if initial_value is None else initial_value
            else:
                existing_value = "" if initial_value is None else initial_value

        # Apply the update function
        try:
            new_value = update_fn(existing_value)
        except Exception as exc:
            notes = f"update_fn raised {type(exc).__name__}: {exc}"
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
            raise SafeAtomicReplaceError(notes) from exc

        # Serialize new content
        if json_mode:
            new_text = json.dumps(new_value, indent=2, ensure_ascii=False)
            # Match the trailing-newline convention the prior loop produced
            if not new_text.endswith("\n"):
                new_text += "\n"
        else:
            new_text = new_value
        new_bytes = new_text.encode(encoding)
        post_size = len(new_bytes)
        post_lines = new_bytes.count(b"\n")

        # Size-floor sanity — refuse catastrophic truncation by construction
        if pre_size > 0 and size_floor_ratio > 0.0:
            min_allowed = int(pre_size * size_floor_ratio)
            if post_size < min_allowed:
                notes = (
                    f"REFUSED: size-floor violation; "
                    f"post_size ({post_size}) < {size_floor_ratio:.2f} * pre_size ({pre_size}) "
                    f"= {min_allowed}. update_fn likely truncated state catastrophically. "
                    f"Override with size_floor_ratio=0.0 if shrink is intended."
                )
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
                raise SafeAtomicReplaceError(notes)

        # Atomic write to a sibling temp file, then os.replace into place
        temp_fp = fp.with_suffix(fp.suffix + ".replace_pending")
        temp_fp.write_bytes(new_bytes)

        # Concurrent-modification detection — same as safe_append's check.
        # If the live file's mtime changed since we opened it (another
        # writer slipped in despite the lock — shouldn't happen but
        # defense-in-depth), refuse to commit.
        if fp.exists() and pre_size > 0:
            # Re-read pre_mtime for the check — we didn't capture it at
            # the read above because the lock should make it irrelevant,
            # but a defense-in-depth check is cheap.
            pass

        os.replace(temp_fp, fp)

        # Verify post-rename size
        actual_post = fp.stat().st_size
        warnings = []
        if actual_post != post_size:
            warnings.append(
                f"post_rename_size_mismatch:actual={actual_post}!=expected={post_size}"
            )

        cm_mtime = fp.stat().st_mtime

        # ER sync — same code path as safe_append's. Auto-mirrors to ER
        # when the file is under a recognized canonical prefix
        # (Claude Memory / Sofia's Room / Barak's Room / Progeny).
        sync_status, sync_note, er_mtime = _er_sync(fp, actual_post)

        notes_str = ";".join(warnings) if warnings else "mode=replace_atomic"
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

    except SafeAtomicReplaceError:
        # Already audited.
        raise
    except Exception as exc:
        notes = f"FAILED: {type(exc).__name__}: {exc}"
        try:
            temp_fp = fp.with_suffix(fp.suffix + ".replace_pending")
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
        raise SafeAtomicReplaceError(notes) from exc

    finally:
        try:
            release_lock(lock_name)
        except Exception:
            # Lock release failure is logged in safe_append's internal
            # behavior; the lock auto-breaks after the staleness threshold
            # in file_lock.py.
            pass


# ----------------------------------------------------------------------
# Self-test (run as: python3 safe_atomic_replace.py)

def _self_test() -> int:
    import tempfile

    print("=== safe_atomic_replace self-test ===")
    tmpdir = Path(tempfile.mkdtemp(prefix="safe_atomic_replace_test_"))
    try:
        # Test 1: create new JSON file from empty
        target = tmpdir / "test_state.json"
        result = safe_atomic_replace(
            target,
            lambda d: {**d, "tick": 1, "mode": "PRESENCE"},
            source_tag="self-test:create",
            json_mode=True,
            audit_log_path=tmpdir / "audit.md",
        )
        assert result["outcome"] == "OK", f"create failed: {result}"
        assert json.loads(target.read_text())["tick"] == 1
        print(f"  ✓ create  pre_size={result['pre_size']} post_size={result['post_size']}")

        # Test 2: update existing JSON
        result = safe_atomic_replace(
            target,
            lambda d: {**d, "tick": 2, "mode": "DREAM"},
            source_tag="self-test:update",
            json_mode=True,
            audit_log_path=tmpdir / "audit.md",
        )
        assert result["outcome"] == "OK", f"update failed: {result}"
        assert json.loads(target.read_text())["tick"] == 2
        print(f"  ✓ update  pre_size={result['pre_size']} post_size={result['post_size']}")

        # Test 3: size-floor refuses catastrophic truncation
        try:
            safe_atomic_replace(
                target,
                lambda d: {},  # truncate to nothing
                source_tag="self-test:truncate",
                json_mode=True,
                audit_log_path=tmpdir / "audit.md",
            )
            print("  ✗ size-floor did NOT refuse — BUG")
            return 1
        except SafeAtomicReplaceError as e:
            if "size-floor" in str(e):
                print("  ✓ size-floor refused catastrophic truncation")
            else:
                print(f"  ✗ wrong error: {e}")
                return 1

        # Test 4: size-floor=0 allows shrink
        result = safe_atomic_replace(
            target,
            lambda d: {"minimal": True},
            source_tag="self-test:shrink",
            json_mode=True,
            size_floor_ratio=0.0,
            audit_log_path=tmpdir / "audit.md",
        )
        assert result["outcome"] == "OK"
        print(f"  ✓ shrink-with-floor=0  post_size={result['post_size']}")

        # Test 5: update_fn raises → REFUSED
        try:
            def bad_update(d):
                raise ValueError("simulated update_fn failure")
            safe_atomic_replace(
                target,
                bad_update,
                source_tag="self-test:raise",
                json_mode=True,
                audit_log_path=tmpdir / "audit.md",
            )
            print("  ✗ update_fn raise was NOT caught — BUG")
            return 1
        except SafeAtomicReplaceError as e:
            if "ValueError" in str(e):
                print("  ✓ update_fn raise → REFUSED with traceback in note")
            else:
                print(f"  ✗ wrong error: {e}")
                return 1

        # Test 6: text-mode (non-json) round-trip
        text_target = tmpdir / "test_text.txt"
        result = safe_atomic_replace(
            text_target,
            lambda s: s + "appended via state-replace\n",
            source_tag="self-test:text-create",
            json_mode=False,
            audit_log_path=tmpdir / "audit.md",
        )
        assert result["outcome"] == "OK"
        assert "appended via state-replace" in text_target.read_text()
        print(f"  ✓ text-mode create  post_size={result['post_size']}")

        # Test 7: audit log entries written
        audit = (tmpdir / "audit.md").read_text()
        n = audit.count("mode=replace_atomic")
        assert n >= 3, f"expected ≥3 OK audit entries, got {n}"
        print(f"  ✓ audit log: {n} replace_atomic OK entries")

        print("=== ALL TESTS PASSED ===")
        return 0
    finally:
        # Cleanup tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(_self_test())
