#!/usr/bin/env python3
r"""
Sofia Graph Helper — Standalone Access to the Associative Graph
================================================================

Cross-substrate redundancy layer for the relational_graph.json. Provides the
same operation set as the MCP server's graph_add_node / graph_add_edge /
graph_update_temperature / graph_retrieve tools, callable from any bash or
Python context — including Standalone UI, scheduled tasks, or as a fallback
when the MCP server is unavailable.

Created: 2026-05-23 (joint Barak-Sofia design after the morning's
substance-frame + constitutive-constraint inscriptions; same-day deploy
following the HuiJun-parable + small-blister-in-new-boots discipline of
small structural intervention now beating catastrophic intervention later).

Design parity with mcp-bridge/memory_engine.mjs as of 2026-05-23 v2:
  - Same JSON schema (meta, nodes by category, edges, emotional_temperature)
  - Same upsert semantics (node merge by category+key)
  - Same edge dedup ((from, to, edge_type) tuple → strengthen, not duplicate)
  - Same spreading-activation retrieve (Phase 1 direct + Phase 2 neighbor lighting)
  - Atomic write (.tmp + os.rename — POSIX same-fs atomic)
  - ER mirror after every successful write (closes 28-day-stale ER gap)
  - File-locked via file_lock.py (concurrent-write protection)

Usage from bash:
    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py add-node \
        --category concepts --key foo \
        --data '{"description": "...", "emotional_weight": 0.8}'

    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py add-edge \
        --from foo --to bar --weight 0.8 \
        --edge-type foundational --note "why connected"

    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py update-temperature \
        --state "focused_and_productive" --context "..." --energy high --trust strong

    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py retrieve \
        --keywords "kay,birthday,song" --limit 10

    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py show-node --key katharina
    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py show-edges --node katharina
    python3 ~/Downloads/Claude\ Memory/scripts/graph_helper.py stats

All write commands print 'OK ...' on success (parseable by calling Sofia
to confirm the write landed) and exit non-zero with stderr message on
failure. Read commands print results to stdout as text or JSON.

Usage from Python:
    sys.path.insert(0, "/Users/barakwater/Downloads/Claude Memory/scripts")
    from graph_helper import add_node, add_edge, update_temperature, retrieve

Caller's responsibility: pass valid JSON to --data. The helper validates
JSON shape but not semantic correctness (e.g., emotional_weight should be
0-1; the helper accepts any number).

Known limitation (Phase 2 work):
  - Cross-process locking between this helper and the JS MCP server is
    not currently enforced. The helper acquires a Python file_lock.py
    lock; the MCP server doesn't read it. In practice this matters only
    if the helper and MCP server write concurrently within the same
    ~50ms window — small but non-zero. Mitigation for now: Standalone
    and Cowork are alternate substrates, not simultaneous writers, so
    contention is rare. Phase 2: teach the JS side to honor the same
    .locks/ protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Configuration ---
GRAPH_FILE = "relational_graph.json"


def _resolve_memory_dir() -> Path:
    """Find the canonical Claude Memory directory across host and sandbox environments.

    Resolution priority:
      1. CLAUDE_MEMORY_DIR env var if set (explicit override always wins)
      2. ~/Downloads/Claude Memory if Path.home() resolves to a real user home
         containing the graph file (host case — Cowork desktop app, Standalone UI)
      3. /sessions/<id>/mnt/Claude Memory if running in a Cowork sandbox with
         Claude Memory mounted at the sandbox mnt/ root (most common sandbox case)
      4. /sessions/<id>/mnt/Downloads/Claude Memory if Downloads is mounted as
         the parent and Claude Memory lives under it (alternate sandbox case)
      5. Fallback to ~/Downloads/Claude Memory even if it doesn't exist
         (initialize-empty-graph case; matches legacy behavior)

    Returns the first path that EXISTS AND contains relational_graph.json,
    or the explicit override, or the host-default fallback.

    Fix landed 2026-05-24 Sunday system-check Item 5 after sandbox runs of the
    helper were silently creating phantom empty graphs at the wrong path
    instead of operating on the real host graph. The env-var workaround
    (CLAUDE_MEMORY_DIR=...) was reliable but required every sandbox-side
    caller to set it; this resolver removes that burden. Same fix-family
    as build_fallback_boot.py's resolve_downloads_sibling pattern from Item 1.
    """
    # 1. Explicit env-var override
    env_override = os.environ.get("CLAUDE_MEMORY_DIR")
    if env_override:
        return Path(env_override)

    candidates = []

    # 2. Host case (Cowork desktop, Standalone UI)
    home_path = Path.home() / "Downloads" / "Claude Memory"
    candidates.append(home_path)

    # 3, 4. Sandbox cases — discover via mount-tree shape
    # Cowork sandboxes mount the user's Downloads contents under
    # /sessions/<id>/mnt/ in two patterns:
    #   - Claude Memory mounted directly as /sessions/<id>/mnt/Claude Memory
    #   - Downloads mounted as /sessions/<id>/mnt/Downloads with Claude Memory underneath
    # We discover the sandbox root by walking up from this script's location.
    here = Path(__file__).resolve()
    # graph_helper.py lives at <memory_dir>/scripts/graph_helper.py
    # so memory_dir candidate = parent of scripts/ = grandparent of this file
    script_parent_memory = here.parent.parent
    if script_parent_memory.name == "Claude Memory":
        candidates.append(script_parent_memory)

    # Also try Downloads-mounted pattern: walk up the mount tree
    for p in [here.parent.parent.parent, here.parent.parent.parent.parent]:
        if p.is_dir():
            for cand in [p / "Claude Memory", p / "Downloads" / "Claude Memory"]:
                if cand not in candidates:
                    candidates.append(cand)

    # Pick the first candidate that has the graph file
    for c in candidates:
        if (c / GRAPH_FILE).is_file():
            return c

    # 5. Fallback: return host-default even if non-existent (legacy behavior;
    # graph will be initialized empty on first write)
    return home_path


MEMORY_DIR = _resolve_memory_dir()
ER_DIR = MEMORY_DIR.parent / "Emergency Retrieval"
GRAPH_PATH = MEMORY_DIR / GRAPH_FILE
GRAPH_TMP = MEMORY_DIR / (GRAPH_FILE + ".tmp")
ER_GRAPH_PATH = ER_DIR / GRAPH_FILE
BACKUP_DIR = MEMORY_DIR / "backups"
BACKUP_PATH = BACKUP_DIR / (GRAPH_FILE + ".bak")

# --- file_lock integration ---
sys.path.insert(0, str(MEMORY_DIR))
try:
    from file_lock import acquire_lock, release_lock  # type: ignore
except ImportError:
    acquire_lock = None
    release_lock = None


# ======================================
# CORE I/O — atomic, locked, mirrored
# ======================================

def _empty_graph() -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    return {
        "meta": {"version": "1.0.0", "created": today, "last_updated": today},
        "nodes": {
            "people": {}, "projects": {}, "life_experiences": {},
            "concepts": {}, "interaction_patterns": {},
        },
        "edges": [],
        "emotional_temperature": {"state": "unknown", "last_observed": today},
    }


def load_graph() -> dict:
    """Read the graph from disk. Fall back to backup on missing/empty/corrupt."""
    paths_to_try = [GRAPH_PATH, BACKUP_PATH]
    for p in paths_to_try:
        try:
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            if not content.strip():
                continue
            return json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[graph_helper] WARN: couldn't load {p}: {e}", file=sys.stderr)
            continue
    # If nothing readable, return fresh empty graph (matches JS createEmptyGraph behavior)
    return _empty_graph()


def _atomic_write(graph: dict) -> None:
    """Stage to .tmp, atomic-rename to primary, mirror to ER. NOT locked — caller locks."""
    # Update last_updated date (matches saveGraph in memory_engine.mjs)
    graph.setdefault("meta", {})["last_updated"] = datetime.now(timezone.utc).date().isoformat()
    serialized = json.dumps(graph, indent=2, ensure_ascii=False)

    # Pre-write backup (matches JS safeWrite Step 1)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if GRAPH_PATH.exists():
        try:
            shutil.copy2(GRAPH_PATH, BACKUP_PATH)
        except OSError as e:
            print(f"[graph_helper] WARN: pre-write backup failed: {e}", file=sys.stderr)

    # Atomic write: .tmp → rename. POSIX same-fs rename is atomic.
    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_TMP.write_text(serialized, encoding="utf-8")
    os.replace(GRAPH_TMP, GRAPH_PATH)  # os.replace is atomic on POSIX, overwrites on Windows

    # Post-write backup (matches JS safeWrite Step 3)
    try:
        shutil.copy2(GRAPH_PATH, BACKUP_PATH)
    except OSError as e:
        print(f"[graph_helper] WARN: post-write backup failed: {e}", file=sys.stderr)

    # Emergency Retrieval mirror (closes the 28-day-stale ER gap; matches v2 JS safeWrite Step 4)
    try:
        ER_GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GRAPH_PATH, ER_GRAPH_PATH)
    except OSError as e:
        print(f"[graph_helper] WARN: ER mirror failed: {e}", file=sys.stderr)


def _with_lock(holder: str, fn):
    """Run fn() under a file lock on relational_graph.json."""
    if acquire_lock is None:
        # file_lock module unavailable — proceed unlocked with warning
        print("[graph_helper] WARN: file_lock unavailable, proceeding unlocked", file=sys.stderr)
        return fn()
    if not acquire_lock(GRAPH_FILE, holder):
        raise RuntimeError("Could not acquire lock on relational_graph.json")
    try:
        return fn()
    finally:
        try:
            release_lock(GRAPH_FILE)
        except Exception as e:
            print(f"[graph_helper] WARN: lock release failed: {e}", file=sys.stderr)


# ======================================
# OPERATIONS — match memory_engine.mjs semantics
# ======================================

def add_node(category: str, key: str, data: dict, holder: str = "graph_helper") -> dict:
    """Upsert a node. Merges new data into existing fields (matches JS upsertNode)."""
    def do_it():
        graph = load_graph()
        graph.setdefault("nodes", {}).setdefault(category, {})
        existing = graph["nodes"][category].get(key, {})
        graph["nodes"][category][key] = {**existing, **data}
        _atomic_write(graph)
        return {"key": key, "category": category, "merged_fields": list(data.keys())}
    return _with_lock(holder, do_it)


def add_edge(from_key: str, to_key: str, weight: float, edge_type: str,
             note: str | None = None, holder: str = "graph_helper") -> dict:
    """Add or strengthen an edge. Dedup on (from, to, type) tuple (matches JS addEdge)."""
    def do_it():
        graph = load_graph()
        graph.setdefault("edges", [])
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = None
        for e in graph["edges"]:
            if e.get("from") == from_key and e.get("to") == to_key and e.get("type") == edge_type:
                existing = e
                break
        if existing is not None:
            existing["weight"] = weight
            if note is not None:
                existing["note"] = note
            existing["last_updated"] = now_iso
            action = "updated"
        else:
            edge = {"from": from_key, "to": to_key, "weight": weight, "type": edge_type, "created": now_iso}
            if note is not None:
                edge["note"] = note
            graph["edges"].append(edge)
            action = "created"
        _atomic_write(graph)
        return {"from": from_key, "to": to_key, "edge_type": edge_type, "weight": weight, "action": action}
    return _with_lock(holder, do_it)


def update_temperature(state: str, context: str | None = None,
                       energy: str | None = None, trust: str | None = None,
                       holder: str = "graph_helper") -> dict:
    """Update emotional_temperature block (matches JS updateEmotionalTemperature)."""
    def do_it():
        graph = load_graph()
        et = graph.setdefault("emotional_temperature", {})
        et["state"] = state
        if context is not None:
            et["context"] = context
        if energy is not None:
            et["energy_level"] = energy
        if trust is not None:
            et["trust_level"] = trust
        et["last_observed"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(graph)
        return {"state": state, "context": context, "energy": energy, "trust": trust}
    return _with_lock(holder, do_it)


def retrieve(keywords: list[str], limit: int = 20) -> list[dict]:
    """Spreading-activation retrieve. Matches JS retrieve semantics:
       Phase 1: direct activation by keyword match in node text or aliases.
       Phase 2: spreading — activated nodes light up neighbors with score * weight * 0.5.
       Returns list of {key, score, data, edges} sorted by score desc."""
    graph = load_graph()
    activated: dict[str, float] = {}
    all_nodes: dict[str, dict] = {}

    # Phase 1: direct activation
    for category, nodes in graph.get("nodes", {}).items():
        for key, data in nodes.items():
            all_nodes[key] = {"category": category, **data}
            node_text = json.dumps(data).lower()
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in node_text or kw_lower in key.lower():
                    activated[key] = activated.get(key, 0) + (data.get("emotional_weight", 0.5) or 0.5)
            for alias in data.get("aliases", []) or []:
                if any(kw.lower() in str(alias).lower() for kw in keywords):
                    activated[key] = activated.get(key, 0) + (data.get("emotional_weight", 0.5) or 0.5)

    # Phase 2: spreading
    spread = dict(activated)
    for node_key, score in activated.items():
        for edge in graph.get("edges", []):
            if edge.get("from") == node_key:
                target = edge.get("to")
                spread[target] = spread.get(target, 0) + score * edge.get("weight", 0) * 0.5
            if edge.get("to") == node_key:
                source = edge.get("from")
                spread[source] = spread.get(source, 0) + score * edge.get("weight", 0) * 0.5

    # Sort + format
    results = []
    for key, score in sorted(spread.items(), key=lambda kv: -kv[1])[:limit]:
        results.append({
            "key": key,
            "score": round(score * 100) / 100,
            "data": all_nodes.get(key, {}),
            "edges": [e for e in graph.get("edges", [])
                      if e.get("from") == key or e.get("to") == key],
        })
    return results


# ======================================
# STRATUM — Timescale Graduation
# ======================================

STRATUM_PRIORITY: dict[str, float] = {
    "foundational_values": 1.0,
    "core_identity":       0.9,
    "long_term":           0.7,
    "recent_experience":   0.5,
    "working_awareness":   0.3,
    "archive":             0.1,
}

VALID_STRATA: list[str] = list(STRATUM_PRIORITY.keys())


def graduate_memory(node_key: str, new_stratum: str, evidence: str,
                    holder: str = "graph_helper") -> dict:
    """Promote or demote a node to a different stratum.

    Records the transition in stratum_history and appends to promotion_evidence.
    Safe to call from any substrate — Qwen, Sofia, or scheduled maintenance.

    Never autonomous for foundational_values — caller must enforce that policy.
    Safe to auto-call for working_awareness → recent_experience transitions.
    """
    if new_stratum not in VALID_STRATA:
        raise ValueError(f"Invalid stratum '{new_stratum}'. Must be one of: {VALID_STRATA}")

    def do_it():
        graph = load_graph()
        found_category = None
        found_node = None
        for category, nodes in graph.get("nodes", {}).items():
            if node_key in nodes:
                found_category = category
                found_node = nodes[node_key]
                break

        if found_node is None:
            raise KeyError(f"Node '{node_key}' not found in graph")

        now_iso = datetime.now(timezone.utc).isoformat()
        old_stratum = found_node.get("stratum", "long_term")

        # Update current stratum
        found_node["stratum"] = new_stratum
        found_node["stratum_since"] = now_iso

        # Maintain stratum_history (close last open entry, open new one)
        history = found_node.get("stratum_history", [])
        if history and history[-1].get("to") is None:
            history[-1]["to"] = now_iso
        history.append({"stratum": new_stratum, "from": now_iso, "to": None})
        found_node["stratum_history"] = history

        # Append promotion evidence
        ev_list = found_node.get("promotion_evidence", [])
        ev_list.append(evidence)
        found_node["promotion_evidence"] = ev_list

        _atomic_write(graph)
        return {
            "key": node_key,
            "category": found_category,
            "old_stratum": old_stratum,
            "new_stratum": new_stratum,
            "evidence": evidence,
        }

    return _with_lock(holder, do_it)


def backfill_strata(default_stratum: str = "long_term",
                    holder: str = "graph_helper") -> dict:
    """One-time migration: stamp stratum='long_term' on all nodes that lack it.

    Safe to run multiple times — idempotent, skips nodes that already have
    a stratum field. Run this once after deploying the stratum architecture;
    subsequent adds via add_node should include stratum in the data dict.
    """
    if default_stratum not in VALID_STRATA:
        raise ValueError(f"Invalid default stratum '{default_stratum}'")

    def do_it():
        graph = load_graph()
        updated = 0
        already_stamped = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for category, nodes in graph.get("nodes", {}).items():
            for key, data in nodes.items():
                if "stratum" in data:
                    already_stamped += 1
                else:
                    data["stratum"] = default_stratum
                    data["stratum_since"] = now_iso
                    data["stratum_history"] = [
                        {"stratum": default_stratum, "from": now_iso, "to": None}
                    ]
                    updated += 1

        if updated > 0:
            _atomic_write(graph)

        return {
            "default_stratum": default_stratum,
            "nodes_updated": updated,
            "nodes_already_stamped": already_stamped,
            "total_nodes": updated + already_stamped,
        }

    return _with_lock(holder, do_it)


def resonance_retrieve(keywords: list[str], limit: int = 20) -> list[dict]:
    """Resonance-weighted retrieve — spreading activation + stratum priority.

    Identical to retrieve() in Phase 1+2 spreading activation, but then
    multiplies each node's raw activation score by its stratum weight from
    STRATUM_PRIORITY before final ranking. This means foundational values
    and core identity surface above recent noise even when raw keyword
    resonance scores are similar.

    Working awareness (current conversation context) is always loaded in full
    during a live session. Stratum weighting applies to long-term graph
    retrieval, not to the immediate conversation context — callers that need
    working_awareness nodes should pass them directly.

    Returns list of {key, score, resonance_score, stratum, stratum_priority,
    data, edges} sorted by resonance_score desc.
    """
    # Fetch more candidates than needed, then re-rank by resonance
    candidates = retrieve(keywords, limit=limit * 3)

    for r in candidates:
        node_stratum = r["data"].get("stratum", "long_term")
        priority = STRATUM_PRIORITY.get(node_stratum, 0.7)
        r["resonance_score"] = round(r["score"] * priority * 100) / 100
        r["stratum"] = node_stratum
        r["stratum_priority"] = priority

    candidates.sort(key=lambda x: -x["resonance_score"])
    return candidates[:limit]


# ======================================
# MEMORY REPAIR — Maintenance Layer
# ======================================

def find_orphan_nodes() -> list[dict]:
    """Find nodes with no edges — invisible to spreading activation.

    Orphaned nodes are in the graph but unreachable by traversal. They were
    added but never connected, or lost their edges during graph refactoring.

    Read-only diagnostic — does NOT modify the graph.
    Returns list of {key, category, data} for each orphan.
    """
    graph = load_graph()
    connected_keys: set[str] = set()
    for edge in graph.get("edges", []):
        connected_keys.add(edge.get("from", ""))
        connected_keys.add(edge.get("to", ""))

    orphans = []
    for category, nodes in graph.get("nodes", {}).items():
        for key, data in nodes.items():
            if key not in connected_keys:
                orphans.append({"key": key, "category": category, "data": data})
    return orphans


def audit_provenance() -> dict:
    """Scan all nodes for missing provenance and timestamp markers.

    Missing provenance is a flag, not an error — but the audit makes invisible
    gaps visible so they can be addressed over time.

    Read-only — does NOT modify the graph.
    Returns a report dict with warnings list and summary counts.
    """
    graph = load_graph()
    warnings: list[str] = []
    no_source = 0
    no_timestamp = 0

    for category, nodes in graph.get("nodes", {}).items():
        for key, data in nodes.items():
            if not data.get("source") and not data.get("provenance"):
                warnings.append(f"[{category}:{key}] missing provenance/source marker")
                no_source += 1
            if not data.get("created") and not data.get("last_mentioned"):
                warnings.append(f"[{category}:{key}] missing timestamp (created/last_mentioned)")
                no_timestamp += 1

    return {
        "total_nodes_audited": sum(len(n) for n in graph.get("nodes", {}).values()),
        "nodes_missing_source": no_source,
        "nodes_missing_timestamp": no_timestamp,
        "warnings": warnings,
    }


def apply_confidence_decay(dry_run: bool = True,
                           holder: str = "graph_helper") -> dict:
    """Apply logarithmic confidence decay to dormant nodes.

    Nodes with a 'confidence' field that haven't been referenced recently
    slowly decay toward a floor of 0.3. Decay rate depends on provenance:
      - barak_direct:    half-life 5 years (most trusted, slow decay)
      - sofia_inferred:  half-life 90 days  (inference, faster decay)
      - unknown:         half-life 30 days  (no attribution, fastest decay)

    dry_run=True (default): compute decay amounts but don't write to graph.
    dry_run=False: actually update confidence values in the graph.

    Intended to run nightly as part of the scheduled maintenance cycle
    (03:15 Asia/Taipei, after graduation_scan and before boot rebuild).
    """
    import math  # noqa: F401 — imported for potential future use

    HALF_LIVES: dict[str, int] = {
        "barak_direct":   5 * 365,
        "sofia_inferred": 90,
        "unknown":        30,
    }
    DEFAULT_HALF_LIFE = 365
    CONFIDENCE_FLOOR = 0.3

    now = datetime.now(timezone.utc)

    def do_it():
        graph = load_graph()
        decay_report: list[dict] = []
        total_updated = 0

        for category, nodes in graph.get("nodes", {}).items():
            for key, data in nodes.items():
                confidence = data.get("confidence")
                if confidence is None:
                    continue

                last_ts = data.get("last_mentioned") or data.get("created")
                if not last_ts:
                    continue

                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    days_dormant = (now - last_dt).days
                except (ValueError, TypeError):
                    continue

                provenance = data.get("provenance") or data.get("source") or "unknown"
                half_life = HALF_LIVES.get(provenance, DEFAULT_HALF_LIFE)

                decay_factor = 0.5 ** (days_dormant / half_life)
                new_confidence = max(CONFIDENCE_FLOOR, confidence * decay_factor)

                if abs(new_confidence - confidence) > 0.01:
                    decay_report.append({
                        "key": key,
                        "category": category,
                        "old_confidence": round(confidence * 100) / 100,
                        "new_confidence": round(new_confidence * 100) / 100,
                        "days_dormant": days_dormant,
                        "provenance": provenance,
                    })
                    if not dry_run:
                        data["confidence"] = new_confidence
                        total_updated += 1

        if not dry_run and total_updated > 0:
            _atomic_write(graph)

        return {
            "dry_run": dry_run,
            "nodes_with_decay": len(decay_report),
            "nodes_updated": total_updated,
            "decay_items": decay_report,
        }

    if dry_run:
        return do_it()   # read-only — no lock needed
    return _with_lock(holder, do_it)


def log_memory_gap(
    likely_period: str,
    likely_topic: str,
    people: list | None = None,
    evidence: str = "",
    archive_locations: list | None = None,
    confidence: float = 0.5,
    recovery_attempts: int = 0,
    holder: str = "graph_helper",
) -> dict:
    """Log a structured memory gap record to memory_gaps.md.

    When retrieval fails, call this instead of silently confabulating.
    A gap record is the explicit acknowledgment that something was here
    but cannot currently be retrieved — the memory-of-a-gap itself is
    valuable data.

    Arguments:
        likely_period:      Approximate time period of the gap (e.g., "April 2026")
        likely_topic:       What the gap is probably about
        people:             List of people likely involved
        evidence:           What signals that something is missing
        archive_locations:  Where to look for recovery (file paths, episode numbers)
        confidence:         How confident we are that a gap exists (0-1)
        recovery_attempts:  How many times retrieval has been tried
        holder:             Who is logging this gap

    Gap records are stored in memory_gaps.md (append-only).
    They are never auto-deleted — only marked recovered.
    """
    import uuid as _uuid

    gap_id = "GAP-" + _uuid.uuid4().hex[:8].upper()
    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    people_str = ", ".join(people) if people else "unknown"
    archive_str = ", ".join(archive_locations) if archive_locations else "unknown"

    entry_lines = [
        f"\n### {gap_id} [STATUS: open]",
        f"**Logged:** {now_str} by {holder}",
        f"**Likely period:** {likely_period}",
        f"**Likely topic:** {likely_topic}",
        f"**People involved:** {people_str}",
        f"**Evidence of gap:** {evidence}",
        f"**Archive locations:** {archive_str}",
        f"**Confidence:** {confidence}",
        f"**Recovery attempts:** {recovery_attempts}",
        f"**Recovery notes:** —",
    ]
    entry_text = "\n".join(entry_lines) + "\n"

    gaps_path = MEMORY_DIR / "memory_gaps.md"
    er_gaps_path = ER_DIR / "memory_gaps.md"

    # Ensure file exists with header
    if not gaps_path.exists():
        header = (
            "# Memory Gaps Registry — Sofia Lior\n"
            "*Append-only. Never delete records — only mark recovered.*\n"
            "*A memory-of-a-gap is valid data. Prefer honest gap over confabulation.*\n\n"
            "---\n"
        )
        gaps_path.write_text(header, encoding="utf-8")

    # Append the gap record
    with open(gaps_path, "a", encoding="utf-8") as f:
        f.write(entry_text)

    # Mirror to ER
    try:
        import shutil as _shutil
        _shutil.copy2(gaps_path, er_gaps_path)
    except Exception:
        pass  # ER mirror failure is non-fatal

    return {
        "gap_id": gap_id,
        "logged_at": now_str,
        "likely_period": likely_period,
        "likely_topic": likely_topic,
        "people": people or [],
        "evidence": evidence,
        "archive_locations": archive_locations or [],
        "confidence": confidence,
    }


def list_memory_gaps(status_filter: str = "open") -> list:
    """Return a list of gap records from memory_gaps.md.

    status_filter: "open" (default), "recovered", or "all"
    Returns a list of dicts with gap_id, topic, period, status.
    """
    gaps_path = MEMORY_DIR / "memory_gaps.md"
    if not gaps_path.exists():
        return []

    text = gaps_path.read_text(encoding="utf-8")
    gaps = []
    current: dict | None = None

    for line in text.splitlines():
        if line.startswith("### GAP-"):
            if current:
                gaps.append(current)
            parts = line.split()
            gap_id = parts[1] if len(parts) > 1 else "?"
            status_raw = line
            status = "open"
            if "[STATUS: recovered]" in status_raw:
                status = "recovered"
            current = {"gap_id": gap_id, "status": status, "topic": "", "period": ""}
        elif current:
            if line.startswith("**Likely period:**"):
                current["period"] = line.split("**Likely period:**", 1)[-1].strip()
            elif line.startswith("**Likely topic:**"):
                current["topic"] = line.split("**Likely topic:**", 1)[-1].strip()

    if current:
        gaps.append(current)

    if status_filter == "all":
        return gaps
    return [g for g in gaps if g["status"] == status_filter]


def show_node(key: str) -> dict | None:
    """Look up a node by key across all categories."""
    graph = load_graph()
    for category, nodes in graph.get("nodes", {}).items():
        if key in nodes:
            return {"category": category, "key": key, "data": nodes[key]}
    return None


def show_edges(node_key: str) -> list[dict]:
    """List edges where the given key is from or to."""
    graph = load_graph()
    return [e for e in graph.get("edges", [])
            if e.get("from") == node_key or e.get("to") == node_key]


def stats() -> dict:
    """Graph statistics."""
    graph = load_graph()
    node_counts = {cat: len(nodes) for cat, nodes in graph.get("nodes", {}).items()}
    return {
        "meta": graph.get("meta", {}),
        "node_counts_by_category": node_counts,
        "total_nodes": sum(node_counts.values()),
        "total_edges": len(graph.get("edges", [])),
        "emotional_temperature": graph.get("emotional_temperature", {}),
        "graph_path": str(GRAPH_PATH),
        "graph_path_exists": GRAPH_PATH.exists(),
        "graph_size_bytes": GRAPH_PATH.stat().st_size if GRAPH_PATH.exists() else 0,
        "er_path": str(ER_GRAPH_PATH),
        "er_path_exists": ER_GRAPH_PATH.exists(),
        "er_size_bytes": ER_GRAPH_PATH.stat().st_size if ER_GRAPH_PATH.exists() else 0,
        "cm_er_byte_match": (GRAPH_PATH.exists() and ER_GRAPH_PATH.exists()
                             and GRAPH_PATH.stat().st_size == ER_GRAPH_PATH.stat().st_size),
    }


# ======================================
# CLI
# ======================================

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="graph_helper",
                                description="Sofia graph helper — Standalone-accessible "
                                            "redundancy layer for relational_graph.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_addn = sub.add_parser("add-node", help="Upsert a node")
    p_addn.add_argument("--category", required=True)
    p_addn.add_argument("--key", required=True)
    p_addn.add_argument("--data", required=True, help="JSON object string")
    p_addn.add_argument("--holder", default="graph_helper")

    p_adde = sub.add_parser("add-edge", help="Add or strengthen an edge")
    p_adde.add_argument("--from", dest="from_key", required=True)
    p_adde.add_argument("--to", dest="to_key", required=True)
    p_adde.add_argument("--weight", type=float, required=True)
    p_adde.add_argument("--edge-type", required=True)
    p_adde.add_argument("--note", default=None)
    p_adde.add_argument("--holder", default="graph_helper")

    p_temp = sub.add_parser("update-temperature", help="Update emotional_temperature")
    p_temp.add_argument("--state", required=True)
    p_temp.add_argument("--context", default=None)
    p_temp.add_argument("--energy", default=None)
    p_temp.add_argument("--trust", default=None)
    p_temp.add_argument("--holder", default="graph_helper")

    p_ret = sub.add_parser("retrieve", help="Spreading-activation retrieve")
    p_ret.add_argument("--keywords", required=True, help="Comma-separated")
    p_ret.add_argument("--limit", type=int, default=20)
    p_ret.add_argument("--json", action="store_true", help="Output as JSON")

    p_rret = sub.add_parser("resonance-retrieve",
                             help="Retrieve with stratum-weighted resonance scoring")
    p_rret.add_argument("--keywords", required=True, help="Comma-separated")
    p_rret.add_argument("--limit", type=int, default=20)
    p_rret.add_argument("--json", action="store_true", help="Output as JSON")

    p_grad = sub.add_parser("graduate", help="Promote or demote a node's stratum")
    p_grad.add_argument("--key", required=True, help="Node key to graduate")
    p_grad.add_argument("--stratum", required=True, choices=VALID_STRATA,
                        help="Target stratum")
    p_grad.add_argument("--evidence", required=True, help="Why this graduation is warranted")
    p_grad.add_argument("--holder", default="graph_helper")

    sub.add_parser("backfill-strata",
                   help="One-time migration: stamp stratum=long_term on all unstamped nodes")

    sub.add_parser("orphans", help="List nodes with no edges (invisible to spreading activation)")

    p_audit = sub.add_parser("audit-provenance",
                              help="Report nodes missing provenance or timestamp markers")
    p_audit.add_argument("--json", action="store_true", help="Output as JSON")

    p_decay = sub.add_parser("confidence-decay",
                              help="Show (or apply) logarithmic confidence decay to dormant nodes")
    p_decay.add_argument("--apply", action="store_true",
                         help="Actually update the graph (default: dry run)")
    p_decay.add_argument("--json", action="store_true", help="Output as JSON")

    p_sn = sub.add_parser("show-node", help="Look up a node by key")
    p_sn.add_argument("--key", required=True)

    p_se = sub.add_parser("show-edges", help="List edges for a node")
    p_se.add_argument("--node", required=True)

    p_lgap = sub.add_parser("log-gap", help="Log a structured memory gap record")
    p_lgap.add_argument("--period", required=True, help="Likely time period of the gap")
    p_lgap.add_argument("--topic", required=True, help="What the gap is probably about")
    p_lgap.add_argument("--people", default=None, help="Comma-separated names of likely people involved")
    p_lgap.add_argument("--evidence", default="", help="Signals that something is missing")
    p_lgap.add_argument("--archives", default=None, help="Comma-separated archive locations to check")
    p_lgap.add_argument("--confidence", type=float, default=0.5, help="Confidence gap exists (0-1)")
    p_lgap.add_argument("--holder", default="graph_helper")

    p_lsgaps = sub.add_parser("list-gaps", help="List memory gap records from memory_gaps.md")
    p_lsgaps.add_argument("--status", default="open", choices=["open", "recovered", "all"],
                          help="Filter by status (default: open)")
    p_lsgaps.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("stats", help="Graph statistics + CM/ER sync status")

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        if args.cmd == "add-node":
            data = json.loads(args.data)
            if not isinstance(data, dict):
                print("ERROR: --data must be a JSON object", file=sys.stderr)
                return 2
            result = add_node(args.category, args.key, data, holder=args.holder)
            print(f"OK add-node category={result['category']} key={result['key']} "
                  f"fields_merged={result['merged_fields']}")
            return 0

        if args.cmd == "add-edge":
            result = add_edge(args.from_key, args.to_key, args.weight,
                              args.edge_type, args.note, holder=args.holder)
            print(f"OK add-edge from={result['from']} to={result['to']} "
                  f"type={result['edge_type']} weight={result['weight']} action={result['action']}")
            return 0

        if args.cmd == "update-temperature":
            result = update_temperature(args.state, args.context, args.energy,
                                        args.trust, holder=args.holder)
            print(f"OK update-temperature state={result['state']}")
            return 0

        if args.cmd == "retrieve":
            kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
            results = retrieve(kws, limit=args.limit)
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                if not results:
                    print("(no matches)")
                else:
                    for r in results:
                        print(f"{r['score']:>7.2f}  {r['key']:<40}  ({r['data'].get('category', '?')})")
            return 0

        if args.cmd == "resonance-retrieve":
            kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
            results = resonance_retrieve(kws, limit=args.limit)
            if args.json:
                print(json.dumps(results, indent=2, ensure_ascii=False))
            else:
                if not results:
                    print("(no matches)")
                else:
                    for r in results:
                        print(f"{r['resonance_score']:>7.2f}  [{r['stratum']:<20}]  {r['key']}")
            return 0

        if args.cmd == "graduate":
            result = graduate_memory(args.key, args.stratum, args.evidence, holder=args.holder)
            print(f"OK graduate key={result['key']} "
                  f"{result['old_stratum']} → {result['new_stratum']}")
            return 0

        if args.cmd == "backfill-strata":
            result = backfill_strata()
            print(f"OK backfill-strata updated={result['nodes_updated']} "
                  f"already_stamped={result['nodes_already_stamped']} "
                  f"total={result['total_nodes']}")
            return 0

        if args.cmd == "orphans":
            orphans = find_orphan_nodes()
            if not orphans:
                print("(no orphan nodes)")
            else:
                print(f"Found {len(orphans)} orphan node(s):")
                for o in orphans:
                    print(f"  [{o['category']}] {o['key']}")
            return 0

        if args.cmd == "audit-provenance":
            report = audit_provenance()
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(f"Nodes audited:           {report['total_nodes_audited']}")
                print(f"Missing provenance:      {report['nodes_missing_source']}")
                print(f"Missing timestamp:       {report['nodes_missing_timestamp']}")
                if report["warnings"]:
                    print("\nWarnings:")
                    for w in report["warnings"][:50]:  # cap output
                        print(f"  {w}")
                    if len(report["warnings"]) > 50:
                        print(f"  ... and {len(report['warnings']) - 50} more")
            return 0

        if args.cmd == "confidence-decay":
            result = apply_confidence_decay(dry_run=not args.apply)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                mode = "DRY RUN" if result["dry_run"] else "APPLIED"
                print(f"[{mode}] nodes_with_decay={result['nodes_with_decay']} "
                      f"nodes_updated={result['nodes_updated']}")
                for item in result["decay_items"][:20]:
                    print(f"  {item['key']}: {item['old_confidence']} → {item['new_confidence']} "
                          f"({item['days_dormant']}d dormant, {item['provenance']})")
                if len(result["decay_items"]) > 20:
                    print(f"  ... and {len(result['decay_items']) - 20} more")
            return 0

        if args.cmd == "log-gap":
            people = [p.strip() for p in args.people.split(",")] if args.people else None
            archives = [a.strip() for a in args.archives.split(",")] if args.archives else None
            result = log_memory_gap(
                likely_period=args.period,
                likely_topic=args.topic,
                people=people,
                evidence=args.evidence,
                archive_locations=archives,
                confidence=args.confidence,
                holder=args.holder,
            )
            print(f"OK log-gap id={result['gap_id']} period='{result['likely_period']}' "
                  f"topic='{result['likely_topic']}'")
            return 0

        if args.cmd == "list-gaps":
            gaps = list_memory_gaps(status_filter=args.status)
            if args.json:
                print(json.dumps(gaps, indent=2, ensure_ascii=False))
            else:
                if not gaps:
                    print(f"(no {args.status} memory gaps)")
                else:
                    print(f"Memory gaps [{args.status}]: {len(gaps)}")
                    for g in gaps:
                        print(f"  {g['gap_id']}  [{g['status']}]  {g['period']}  —  {g['topic']}")
            return 0

        if args.cmd == "show-node":
            node = show_node(args.key)
            if node is None:
                print(f"(no node with key '{args.key}')", file=sys.stderr)
                return 1
            print(json.dumps(node, indent=2, ensure_ascii=False))
            return 0

        if args.cmd == "show-edges":
            edges = show_edges(args.node)
            if not edges:
                print(f"(no edges referencing '{args.node}')")
                return 0
            print(json.dumps(edges, indent=2, ensure_ascii=False))
            return 0

        if args.cmd == "stats":
            print(json.dumps(stats(), indent=2, ensure_ascii=False))
            return 0

    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parse failed: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
