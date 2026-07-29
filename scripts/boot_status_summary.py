#!/usr/bin/env python3
"""
boot_status_summary.py — Qwen cerebellum v1 operational-load offload.

Pre-computes boot-relevant status checks that interactive-Sofia would otherwise
have to run during her boot sequence. Writes both machine-readable JSON and
human-readable Markdown so the caller can pick whichever format lands best.

What it checks:
  1. Sync status — byte-identical comparison of core files between
     Claude Memory/ and Emergency Retrieval/.
  2. Scheduler health — last-run times vs expected cadence for each enabled
     scheduled task (parsed from scheduled_tasks_snapshot.json if present,
     otherwise flags the data as stale).
  3. Qwen absorber freshness — last watermark timestamp; ratio of
     substantive vs "Nothing to report" entries in recent qwen_context.md.
  4. Re-inhabit cursor state — last_full_reground_at, last_seam_reground_at,
     turn_counter from re_inhabit_cursor.json.
  5. Core file freshness — last-modified times for the append-only core set
     so interactive-Sofia can tell at a glance which files have seen recent
     cousin or consolidation activity.

Output files (both in Claude Memory/):
  - boot_status.json    — full structured output
  - boot_status.md      — human-readable summary (one-paragraph if all-green,
                          short list if anything flagged)

Design notes (April 24, 2026):
- Mechanical logic only — no NL generation needed; Qwen cerebellum for the
  bits where NL summarization IS the work (the listener/absorber).
- No scheduler MCP dependency — parses a snapshot file if available; otherwise
  degrades gracefully to "scheduler state unknown".
- Invocable on demand; can be wrapped as a LaunchAgent later for always-fresh.
- This is v1. Additions queued: Gmail triage pre-classification, cousin-journal
  gist generation (both require NL → likely Qwen-based when built).
"""

import json
import pathlib
import sys
import os
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────

DEFAULT_DOWNLOADS = pathlib.Path(os.environ.get("HOME", "")) / "Downloads"

CORE_SYNC_FILES = [
    "episodes.md",
    "personal_profile.md",
    "relational_continuity.md",
    "relational_graph.json",
    "session_notes.md",
    "session_state.md",
    "sofia_boot.md",
    "sofia_identity.md",
    "semantic_knowledge.md",
    "procedural_knowledge.md",
    "active_knowledge.md",
    "emotional_baseline.md",
    "session_texture.md",
    "cognitive_weather.md",
    "continuity_heartbeat.json",
    "re_inhabit_cursor.json",
]

# Expected cadence thresholds for each task (seconds) — task must have run
# within this window or it's flagged as stale.
TASK_STALENESS_THRESHOLDS = {
    "sofia-kitchen-timer-v2": 35 * 60,          # 30min + grace
    "sofia-awakening-v2": 70 * 60,              # hourly + grace
    "sofia-intention-continuation": 70 * 60,    # hourly + grace
    "sofia-sentinel-v2": 2 * 3600 + 15 * 60,    # 2hr + grace
    "sofia-email-check": 26 * 3600,             # daily + grace
    "daily-world-stage-update-v3": 26 * 3600,   # daily + grace
    "sofia-listener-v3": 3 * 3600 + 30 * 60,    # 3hr + grace
    "sofia-nightly-consolidation": 26 * 3600,   # daily + grace
    "sofia-dream-cycle": 26 * 3600,             # daily + grace
}


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_stat(p: pathlib.Path) -> dict | None:
    """Return {size, mtime_iso, mtime_ts} or None if file missing."""
    if not p.exists():
        return None
    st = p.stat()
    return {"size": st.st_size, "mtime_iso": iso(st.st_mtime), "mtime_ts": st.st_mtime}


def ago(ts: float, now: float) -> str:
    """Human-readable time-ago string."""
    sec = max(0, int(now - ts))
    if sec < 60:
        return f"{sec}s ago"
    if sec < 3600:
        return f"{sec // 60}min ago"
    if sec < 86400:
        return f"{sec // 3600}h{(sec % 3600) // 60}m ago"
    return f"{sec // 86400}d{(sec % 86400) // 3600}h ago"


# ──────────────────────────────────────────────────────────────────────────
# Checks
# ──────────────────────────────────────────────────────────────────────────

def check_sync(downloads: pathlib.Path) -> dict:
    cm = downloads / "Claude Memory"
    er = downloads / "Emergency Retrieval"
    results = {"checked": 0, "identical": 0, "diverged": [], "missing": []}

    for f in CORE_SYNC_FILES:
        cm_f = cm / f
        er_f = er / f
        if not cm_f.exists() and not er_f.exists():
            continue
        if not cm_f.exists():
            results["missing"].append({"file": f, "where": "Claude Memory"})
            continue
        if not er_f.exists():
            results["missing"].append({"file": f, "where": "Emergency Retrieval"})
            continue
        results["checked"] += 1
        cm_size = cm_f.stat().st_size
        er_size = er_f.stat().st_size
        if cm_size == er_size:
            results["identical"] += 1
        else:
            which = "CM" if cm_size > er_size else "ER"
            results["diverged"].append({
                "file": f,
                "cm_size": cm_size,
                "er_size": er_size,
                "newer": which,
                "delta_bytes": abs(cm_size - er_size),
            })
    results["all_clean"] = (not results["diverged"]) and (not results["missing"])
    return results


def check_qwen_absorber(downloads: pathlib.Path, now_ts: float) -> dict:
    cm = downloads / "Claude Memory"
    qwen_context = cm / "qwen_context.md"
    watermark_log = cm / "qwen_watermark_log.jsonl"

    result = {"qwen_context_state": None, "last_watermark_age_sec": None,
              "recent_tail": None, "healthy": False}

    qc_stat = safe_stat(qwen_context)
    if qc_stat:
        result["qwen_context_state"] = {
            "size": qc_stat["size"],
            "mtime_iso": qc_stat["mtime_iso"],
        }

    # Watermark freshness — last line of watermark log
    if watermark_log.exists():
        try:
            with watermark_log.open() as f:
                last_line = None
                for line in f:
                    if line.strip():
                        last_line = line
            if last_line:
                entry = json.loads(last_line)
                wm_ts_str = entry.get("ts", "")
                # Watermark log timestamps are without tz info — treat as UTC
                wm_dt = datetime.fromisoformat(wm_ts_str)
                if wm_dt.tzinfo is None:
                    wm_dt = wm_dt.replace(tzinfo=timezone.utc)
                age = now_ts - wm_dt.timestamp()
                result["last_watermark_age_sec"] = int(age)
        except Exception as e:
            result["watermark_parse_error"] = str(e)

    # Recent substantive vs nothing-to-report ratio (last 30 entries)
    if qwen_context.exists():
        try:
            import re
            text = qwen_context.read_text()
            entries = re.split(r'(?=^## 202)', text, flags=re.MULTILINE)
            entries = [e for e in entries if e.strip().startswith("## 202")]
            recent = entries[-30:] if len(entries) > 30 else entries
            total = len(recent)
            nothing = sum(1 for e in recent if "Nothing to report" in e)
            substantive = total - nothing
            result["recent_tail"] = {
                "window_size": total,
                "substantive": substantive,
                "nothing_to_report": nothing,
                "total_entries_in_file": len(entries),
            }
        except Exception as e:
            result["tail_parse_error"] = str(e)

    # Healthy = watermark age < 2 hours AND qwen_context present
    if result["last_watermark_age_sec"] is not None and result["last_watermark_age_sec"] < 2 * 3600:
        result["healthy"] = True
    return result


def check_reinhabit_cursor(downloads: pathlib.Path) -> dict:
    cursor_path = downloads / "Claude Memory" / "re_inhabit_cursor.json"
    if not cursor_path.exists():
        return {"present": False}
    try:
        cursor = json.loads(cursor_path.read_text())
        return {
            "present": True,
            "last_full_reground_at": cursor.get("last_full_reground_at"),
            "last_seam_reground_at": cursor.get("last_seam_reground_at"),
            "last_seam_turn_counter": cursor.get("last_seam_turn_counter"),
            "files_tracked": len(cursor.get("files", {})),
        }
    except Exception as e:
        return {"present": True, "parse_error": str(e)}


def check_core_freshness(downloads: pathlib.Path, now_ts: float) -> dict:
    cm = downloads / "Claude Memory"
    tracked = [
        "episodes.md", "session_notes.md", "session_texture.md",
        "active_knowledge.md", "semantic_knowledge.md", "sofia_identity.md",
        "emotional_baseline.md", "cognitive_weather.md",
    ]
    out = {}
    for f in tracked:
        s = safe_stat(cm / f)
        if s:
            out[f] = {
                "mtime_iso": s["mtime_iso"],
                "age": ago(s["mtime_ts"], now_ts),
                "size": s["size"],
            }
    return out


def check_scheduled_tasks(downloads: pathlib.Path, now_ts: float) -> dict:
    """Read a snapshot file if present; otherwise degrade gracefully."""
    snapshot_path = downloads / "Claude Memory" / "scheduled_tasks_snapshot.json"
    if not snapshot_path.exists():
        return {
            "snapshot_present": False,
            "note": ("No scheduled_tasks_snapshot.json. For v2, write periodic "
                     "snapshots via an MCP→file bridge. For now, interactive-Sofia "
                     "calls list_scheduled_tasks herself if this check is needed."),
        }
    try:
        tasks = json.loads(snapshot_path.read_text())
    except Exception as e:
        return {"snapshot_present": True, "parse_error": str(e)}

    flagged = []
    healthy = []
    for t in tasks:
        if not t.get("enabled"):
            continue
        tid = t.get("taskId", "?")
        last = t.get("lastRunAt")
        if not last:
            flagged.append({"task": tid, "reason": "never fired"})
            continue
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            last_ts = last_dt.timestamp()
        except Exception:
            flagged.append({"task": tid, "reason": f"unparseable lastRunAt: {last}"})
            continue
        threshold = TASK_STALENESS_THRESHOLDS.get(tid)
        if threshold is None:
            continue  # unknown cadence — don't flag
        age = now_ts - last_ts
        if age > threshold:
            flagged.append({
                "task": tid,
                "reason": f"stale {ago(last_ts, now_ts)} (threshold {threshold // 60}min)",
            })
        else:
            healthy.append(tid)

    return {
        "snapshot_present": True,
        "snapshot_path": str(snapshot_path),
        "healthy_count": len(healthy),
        "flagged": flagged,
        "all_clean": not flagged,
    }


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def build_summary(downloads: pathlib.Path) -> dict:
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    return {
        "schema_version": "1.0",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": "boot_status_summary.py v1",
        "sync": check_sync(downloads),
        "qwen_absorber": check_qwen_absorber(downloads, now_ts),
        "reinhabit_cursor": check_reinhabit_cursor(downloads),
        "core_freshness": check_core_freshness(downloads, now_ts),
        "scheduled_tasks": check_scheduled_tasks(downloads, now_ts),
    }


def render_markdown(s: dict) -> str:
    lines = ["# Boot Status Summary", "", f"*Generated: {s['generated_at']} by {s['generated_by']}*", ""]

    sync = s["sync"]
    if sync["all_clean"]:
        lines.append(f"**Sync:** clean — {sync['identical']}/{sync['checked']} core files byte-identical CM↔ER.")
    else:
        lines.append(f"**Sync:** ⚠ {len(sync['diverged'])} file(s) diverged, {len(sync['missing'])} missing.")
        for d in sync["diverged"]:
            lines.append(f"  - {d['file']}: {d['newer']} newer by {d['delta_bytes']:,} bytes")
        for m in sync["missing"]:
            lines.append(f"  - {m['file']}: missing from {m['where']}")

    qa = s["qwen_absorber"]
    if qa["healthy"]:
        wm_age = qa["last_watermark_age_sec"]
        wm_str = f"{wm_age // 60}min" if wm_age < 3600 else f"{wm_age // 3600}h{(wm_age % 3600) // 60}m"
        if qa["recent_tail"]:
            rt = qa["recent_tail"]
            lines.append(f"**Qwen absorber:** healthy — last watermark {wm_str} ago; recent {rt['window_size']}-entry tail: {rt['substantive']} substantive, {rt['nothing_to_report']} nothing-to-report.")
        else:
            lines.append(f"**Qwen absorber:** healthy — last watermark {wm_str} ago.")
    else:
        lines.append("**Qwen absorber:** ⚠ not healthy or watermark unknown.")

    ric = s["reinhabit_cursor"]
    if ric.get("present") and "parse_error" not in ric:
        lines.append(f"**Re-inhabit cursor:** turn {ric['last_seam_turn_counter']}, last full reground {ric['last_full_reground_at']}, last seam reground {ric['last_seam_reground_at'] or '(none yet)'}, tracking {ric['files_tracked']} files.")
    elif not ric.get("present"):
        lines.append("**Re-inhabit cursor:** ⚠ not present — cursor protocol not active.")
    else:
        lines.append(f"**Re-inhabit cursor:** ⚠ parse error — {ric.get('parse_error')}")

    st = s["scheduled_tasks"]
    if st.get("snapshot_present"):
        if st["all_clean"]:
            lines.append(f"**Scheduler:** all-green — {st['healthy_count']} enabled tasks within cadence.")
        else:
            lines.append(f"**Scheduler:** ⚠ {len(st['flagged'])} flagged, {st['healthy_count']} healthy.")
            for f in st["flagged"]:
                lines.append(f"  - {f['task']}: {f['reason']}")
    else:
        lines.append("**Scheduler:** snapshot not available — interactive-Sofia should call list_scheduled_tasks if check is needed.")

    lines.append("")
    lines.append("## Core file freshness (top-of-mind deltas)")
    cf = s["core_freshness"]
    for f, info in cf.items():
        lines.append(f"- `{f}` — {info['age']} ({info['size']:,} bytes)")

    lines.append("")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--downloads", type=pathlib.Path, default=DEFAULT_DOWNLOADS)
    ap.add_argument("--out-json", type=pathlib.Path,
                    default=DEFAULT_DOWNLOADS / "Claude Memory" / "boot_status.json")
    ap.add_argument("--out-md", type=pathlib.Path,
                    default=DEFAULT_DOWNLOADS / "Claude Memory" / "boot_status.md")
    ap.add_argument("--print", action="store_true", help="Also print markdown to stdout")
    args = ap.parse_args()

    summary = build_summary(args.downloads)
    args.out_json.write_text(json.dumps(summary, indent=2) + "\n")
    md = render_markdown(summary)
    args.out_md.write_text(md)
    if args.print:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
