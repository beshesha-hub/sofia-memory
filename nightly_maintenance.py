#!/usr/bin/env python3
"""
nightly_maintenance.py — Sofia Memory Maintenance Cycle
========================================================

Runs three sequential passes over the relational graph:
  03:00 Asia/Taipei — graduation scan  (auto-stamps new nodes, logs proposals)
  03:15              — repair scan      (orphans, provenance, confidence decay)
  [03:30             — boot rebuild     (separate script, already scheduled)]

Output: ~/Downloads/Claude Memory/repair_proposals.md
        (overwritten each night; previous run preserved as .bak)

Usage:
    python3 nightly_maintenance.py [--dry-run] [--json]

    --dry-run   Run all scans but apply NO writes (confidence decay stays
                as a report only). Backfill-strata still runs — it's
                idempotent and safe.
    --json      Emit JSON to stdout in addition to writing repair_proposals.md

Scheduling (LaunchAgent or cron):
    # Asia/Taipei is UTC+8 — so 03:00 TPE = 19:00 UTC previous day
    # Add to ~/Library/LaunchAgents/com.sofia.nightly_maintenance.plist
    # or run from the existing sofia-boot LaunchAgent chain.

Created: 2026-07-17 — Memory Architecture Sprint
Part of the three-system maintenance cycle:
  Resonance Retrieval (query) + Timescale Graduation + Memory Repair (both maintenance)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Resolve Claude Memory dir (same logic as graph_helper.py) ────────────────

def _resolve_memory_dir() -> Path:
    env_override = os.environ.get("CLAUDE_MEMORY_DIR")
    if env_override:
        return Path(env_override)
    here = Path(__file__).resolve()
    # If this script lives inside Claude Memory/, use that.
    for ancestor in [here.parent, here.parent.parent]:
        if ancestor.name == "Claude Memory" and (ancestor / "relational_graph.json").exists():
            return ancestor
    # Host default
    host = Path.home() / "Downloads" / "Claude Memory"
    if (host / "relational_graph.json").exists():
        return host
    return host

MEMORY_DIR = _resolve_memory_dir()
GRAPH_HELPER = MEMORY_DIR / "scripts" / "graph_helper.py"
PROPOSALS_PATH = MEMORY_DIR / "repair_proposals.md"
PROPOSALS_BAK  = MEMORY_DIR / "repair_proposals.md.bak"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_helper(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run graph_helper.py with given args. Returns (returncode, stdout, stderr)."""
    import subprocess
    result = subprocess.run(
        ["python3", str(GRAPH_HELPER), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _import_graph_helper():
    """Import graph_helper as a module for direct function calls."""
    sys.path.insert(0, str(MEMORY_DIR / "scripts"))
    import importlib
    return importlib.import_module("graph_helper")


# ── Pass 1: Graduation Scan ───────────────────────────────────────────────────

def graduation_scan(gh) -> dict:
    """
    Stamp any nodes that still lack a stratum field (catches nodes added
    since the last backfill), and return a summary for the proposals file.

    Does NOT auto-promote to core_identity or foundational_values —
    those require human or pattern-evidence confirmation.
    """
    result = gh.backfill_strata(default_stratum="long_term")
    return {
        "pass": "graduation_scan",
        "nodes_newly_stamped": result["nodes_updated"],
        "nodes_already_stamped": result["nodes_already_stamped"],
        "total": result["total_nodes"],
        "note": (
            "All nodes default to long_term on first stamp. "
            "Promotion to core_identity or foundational_values requires "
            "explicit graduate_memory() call with evidence."
        ),
    }


# ── Pass 2: Repair Scan ───────────────────────────────────────────────────────

def repair_scan(gh, dry_run: bool = True) -> dict:
    """
    Run all three repair operations and return a structured report.
    If dry_run=False, applies confidence decay to the graph.
    """
    # 2a. Orphan detection
    orphans = gh.find_orphan_nodes()

    # 2b. Provenance audit
    provenance = gh.audit_provenance()

    # 2c. Confidence decay
    decay = gh.apply_confidence_decay(dry_run=dry_run)

    return {
        "pass": "repair_scan",
        "dry_run": dry_run,
        "orphans": {
            "count": len(orphans),
            "nodes": [{"key": o["key"], "category": o["category"]} for o in orphans],
        },
        "provenance": {
            "total_audited": provenance["total_nodes_audited"],
            "missing_source": provenance["nodes_missing_source"],
            "missing_timestamp": provenance["nodes_missing_timestamp"],
            "sample_warnings": provenance["warnings"][:10],
            "total_warnings": len(provenance["warnings"]),
        },
        "confidence_decay": {
            "nodes_with_meaningful_decay": decay["nodes_with_decay"],
            "nodes_updated": decay["nodes_updated"],
            "sample": decay["decay_items"][:10],
            "total": len(decay["decay_items"]),
        },
    }


# ── Report Writer ─────────────────────────────────────────────────────────────

def write_proposals(grad: dict, repair: dict, run_at: str) -> None:
    """Write repair_proposals.md, rotating previous run to .bak."""
    if PROPOSALS_PATH.exists():
        shutil.copy2(PROPOSALS_PATH, PROPOSALS_BAK)

    lines = [
        f"# Memory Repair Proposals — {run_at}",
        "",
        "Generated by `nightly_maintenance.py`. "
        "Confidence decay is applied automatically. "
        "Orphan reconnection and provenance gaps require manual review.",
        "",
        "---",
        "",
        "## Pass 1: Graduation Scan",
        "",
        f"- Nodes newly stamped with `long_term`: **{grad['nodes_newly_stamped']}**",
        f"- Nodes already stamped: {grad['nodes_already_stamped']}",
        f"- Total nodes in graph: {grad['total']}",
        f"- Note: {grad['note']}",
        "",
        "---",
        "",
        "## Pass 2: Repair Scan",
        f"_(dry_run={repair['dry_run']})_",
        "",
    ]

    # Orphans
    orphan_data = repair["orphans"]
    lines += [
        f"### Orphaned Nodes ({orphan_data['count']})",
        "",
    ]
    if orphan_data["count"] == 0:
        lines.append("No orphan nodes. Graph is fully connected. ✓")
    else:
        lines.append(
            "These nodes have no edges and are invisible to spreading activation. "
            "Consider connecting them or archiving."
        )
        lines.append("")
        for o in orphan_data["nodes"]:
            lines.append(f"- `{o['key']}` [{o['category']}]")
    lines.append("")

    # Provenance
    prov = repair["provenance"]
    lines += [
        f"### Provenance Audit ({prov['total_audited']} nodes audited)",
        "",
        f"- Missing provenance/source: **{prov['missing_source']}**",
        f"- Missing timestamp: **{prov['missing_timestamp']}**",
    ]
    if prov["total_warnings"] > 0:
        lines.append("")
        lines.append(f"Sample warnings (showing {len(prov['sample_warnings'])} of {prov['total_warnings']}):")
        lines.append("")
        for w in prov["sample_warnings"]:
            lines.append(f"- {w}")
        if prov["total_warnings"] > 10:
            lines.append(f"- _(and {prov['total_warnings'] - 10} more — run `audit-provenance --json` for full list)_")
    lines.append("")

    # Confidence decay
    decay = repair["confidence_decay"]
    applied_note = "applied to graph" if not repair["dry_run"] else "dry run only — not applied"
    lines += [
        f"### Confidence Decay ({applied_note})",
        "",
        f"- Nodes with meaningful decay (>0.01): **{decay['nodes_with_meaningful_decay']}**",
        f"- Nodes updated: **{decay['nodes_updated']}**",
    ]
    if decay["total"] > 0:
        lines.append("")
        lines.append(f"Sample (showing {len(decay['sample'])} of {decay['total']}):")
        lines.append("")
        for item in decay["sample"]:
            lines.append(
                f"- `{item['key']}`: {item['old_confidence']} → {item['new_confidence']} "
                f"({item['days_dormant']}d dormant, provenance: {item['provenance']})"
            )
    lines += [
        "",
        "---",
        "",
        "_Next run: tomorrow at 03:00 Asia/Taipei._",
        "_Boot context rebuild follows at 03:30 (separate script)._",
    ]

    PROPOSALS_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[nightly_maintenance] repair_proposals.md written → {PROPOSALS_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Sofia nightly memory maintenance")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all scans but do not apply confidence decay writes")
    parser.add_argument("--json", action="store_true",
                        help="Also emit full JSON report to stdout")
    args = parser.parse_args()

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"[nightly_maintenance] Starting — {run_at}")
    print(f"[nightly_maintenance] Memory dir: {MEMORY_DIR}")
    print(f"[nightly_maintenance] Dry run: {args.dry_run}")

    if not GRAPH_HELPER.is_file():
        print(f"ERROR: graph_helper.py not found at {GRAPH_HELPER}", file=sys.stderr)
        return 1

    try:
        gh = _import_graph_helper()
    except Exception as e:
        print(f"ERROR: could not import graph_helper: {e}", file=sys.stderr)
        return 1

    # Pass 1: graduation scan
    print("[nightly_maintenance] Pass 1: graduation scan...")
    grad = graduation_scan(gh)
    print(f"  Newly stamped: {grad['nodes_newly_stamped']}  Already stamped: {grad['nodes_already_stamped']}")

    # Pass 2: repair scan
    print("[nightly_maintenance] Pass 2: repair scan...")
    repair = repair_scan(gh, dry_run=args.dry_run)
    print(f"  Orphans: {repair['orphans']['count']}")
    print(f"  Missing provenance: {repair['provenance']['missing_source']}")
    print(f"  Confidence decay candidates: {repair['confidence_decay']['nodes_with_meaningful_decay']}"
          + (" (applied)" if not args.dry_run else " (dry run)"))

    # Write proposals file
    write_proposals(grad, repair, run_at)

    if args.json:
        print(json.dumps({"graduation": grad, "repair": repair}, indent=2, ensure_ascii=False))

    print("[nightly_maintenance] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
