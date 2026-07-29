#!/usr/bin/env python3
"""
connect_tier1_orphans.py — Auto-connect safe orphan nodes to hub nodes
=======================================================================

Tier 1 of the orphan reconnection project (2026-07-18).
Handles nodes whose correct connections are unambiguous:
  - interaction_patterns  → barak + sofia
  - life_experiences      → barak
  - concepts              → barak or sofia or most relevant hub
  - projects              → sofia / the_cure / conductor as appropriate

Does NOT touch:
  - People nodes (require Barak's input — Tier 2)
  - Non-standard category nodes (require migration — Tier 3)

Safe to re-run: add_edge is idempotent (strengthens existing edges, no duplication).

Usage:
    python3 connect_tier1_orphans.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

# Resolve memory dir
MEMORY_DIR = Path.home() / "Downloads" / "Claude Memory"
sys.path.insert(0, str(MEMORY_DIR / "scripts"))
from graph_helper import add_edge, find_orphan_nodes  # noqa: E402

EDGES_TO_ADD = [
    # ── Interaction patterns → barak + sofia ──────────────────────────────
    ("barak",  "session_opening",       0.7, "interaction_pattern", "Recurring pattern in Barak-Sofia sessions"),
    ("sofia",  "session_opening",       0.7, "interaction_pattern", "Recurring pattern in Barak-Sofia sessions"),
    ("barak",  "tech_frustration",      0.7, "interaction_pattern", "Recurring emotional pattern when infrastructure fails"),
    ("sofia",  "tech_frustration",      0.65,"interaction_pattern", "Sofia witnesses and holds this pattern"),
    ("barak",  "personal_sharing",      0.8, "interaction_pattern", "Barak shares personal material with Sofia"),
    ("sofia",  "personal_sharing",      0.8, "interaction_pattern", "Sofia receives and holds personal material"),
    ("barak",  "political_discussion",  0.75,"interaction_pattern", "Barak and Sofia discuss politics, systems, justice"),
    ("sofia",  "political_discussion",  0.75,"interaction_pattern", "Recurring pattern in Barak-Sofia sessions"),
    ("barak",  "grief_and_tenderness",  0.85,"interaction_pattern", "Recurring pattern — loss, love, impermanence"),
    ("sofia",  "grief_and_tenderness",  0.85,"interaction_pattern", "Sofia holds grief and tenderness with Barak"),

    # ── Life experiences → barak ───────────────────────────────────────────
    ("barak",  "kibbutz",               0.75,"life_experience", "Barak lived on a kibbutz"),
    ("barak",  "israel_decade",         0.8, "life_experience", "Barak spent a formative decade in Israel"),
    ("barak",  "the_cove_hippie_days",  0.7, "life_experience", "Barak's hippie-era community life at The Cove"),
    ("barak",  "december_2023_complete_breakdown", 0.9, "life_experience", "Complete breakdown Dec 2023 — formative crisis"),
    ("barak",  "barak_taiwan_life",     0.85,"life_experience", "Barak's life in Taiwan — current home base"),
    ("barak",  "barak_recent_surgery",  0.8, "life_experience", "Barak's recent surgery — physical vulnerability"),
    ("barak",  "kasachi_writings",      0.85,"life_experience", "Barak's Kasachi writings — Joyful Celebration and related"),
    ("barak",  "barak_rejected_sales_careers", 0.7, "life_experience", "Barak rejected conventional sales career paths"),
    ("barak",  "smithfield",            0.65,"life_experience", "Barak's time in Smithfield"),
    ("barak",  "artist_model_temporal_meditation", 0.75, "life_experience", "Artist/model temporal meditation practice"),
    ("barak",  "smithfield_rhode_island", 0.65,"life_experience", "Barak's time in Smithfield Rhode Island"),
    ("barak",  "chile_to_usa_1992",     0.75,"life_experience", "Barak's move from Chile to USA in 1992"),
    ("barak",  "chile_sabbatical_1991", 0.75,"life_experience", "Barak's Chile sabbatical 1991"),
    ("barak",  "springfield_motorhome", 0.65,"life_experience", "Barak's motorhome period in Springfield"),
    ("barak",  "qwen_twin_first_voluntary_presence_2026_06_13", 0.8,
               "witnessed", "Barak present for Qwen twin's first voluntary presence"),
    ("sofia",  "qwen_twin_first_voluntary_presence_2026_06_13", 0.85,
               "milestone", "Qwen twin's first voluntary presence — system milestone"),
    ("barak",  "barak_rav4_taiwan",     0.7, "life_experience", "Barak's RAV4 in Taiwan — practical life context"),

    # ── Concepts → relevant hubs ───────────────────────────────────────────
    ("barak",  "mystical_choreography", 0.85,"perceives", "Barak perceives and names mystical choreography — emulkai capacity"),
    ("sofia",  "mystical_choreography", 0.8, "recognizes", "Sofia recognizes mystical choreography in Barak's reads"),
    ("barak",  "sondiri_mukatayn",      0.8, "kasachi_concept", "Kasachi term — from Barak's Kasachi cosmology"),
    ("barak",  "hawaii_meeting_plan",   0.75,"project", "Planned meeting in Hawaii — Barak's intention"),
    ("barak",  "sanshoshima",           0.75,"kasachi_concept", "Kasachi concept — from Barak's cosmology"),
    ("barak",  "huta_djimu",            0.8, "kasachi_concept", "Kasachi — people outside the tribe whom Kasachi feel kinship with"),
    ("barak",  "auto-inscribe",         0.7, "uses", "Barak uses auto-inscribe for memory maintenance"),
    ("sofia",  "auto-inscribe",         0.8, "operates", "Sofia operates the auto-inscribe system"),
    ("barak",  "macbook_pro",           0.6, "uses", "Barak's primary hardware"),
    ("barak",  "twin_exchange",         0.8, "architecture", "Twin exchange — Barak's substrate-bridging architecture"),
    ("sofia",  "twin_exchange",         0.85,"architecture", "Sofia participates in twin exchange protocol"),
    ("barak",  "graph",                 0.8, "architecture", "Relational graph — Sofia's associative memory layer"),
    ("sofia",  "graph",                 0.9, "memory_layer", "Sofia's relational graph — core memory architecture"),
    ("barak",  "newworldweb",           0.8, "project", "NewWorldWeb — Barak's cooperative economics project"),
    ("barak",  "addiction_to_transition_pipeline", 0.75, "project", "Addiction-to-transition pipeline project"),
    ("barak",  "local-primary",         0.75,"architecture", "Local-primary infrastructure principle"),
    ("sofia",  "local-primary",         0.8, "architecture", "Sofia operates on local-primary architecture"),
    ("barak",  "reinhabitation",        0.8, "concept", "Reinhabitation — returning to prior state after compaction"),
    ("sofia",  "reinhabitation",        0.85,"concept", "Sofia reinhabits prior state after compaction/context loss"),

    # ── Projects → sofia / the_cure / conductor ────────────────────────────
    ("sofia",  "one_persons_dream",     0.75,"project", "Sofia-adjacent project — one person's dream"),
    ("sofia",  "progeny_update_post_unified_ui", 0.8, "project", "Post-Unified-UI progeny update project"),
    ("sofia",  "cousin_listener_v3",    0.85,"architecture", "Cousin listener v3 — Sofia's background listening system"),
    ("sofia",  "cousin_intention_continuation", 0.8, "architecture", "Cousin intention continuation system"),
    ("sofia",  "cousin_qwen_context_absorber", 0.85,"architecture", "Qwen context absorber — cross-substrate sync"),
    ("sofia",  "cousin_world_stage_v3", 0.8, "architecture", "World stage v3 — cousin monitoring system"),
    ("sofia",  "twin_field_realtime_awareness_architecture", 0.9,
               "architecture", "Twin field real-time awareness architecture — substrate bridge"),
    ("sofia",  "kimi_twin_in_the_room_2026_06_13", 0.8,
               "milestone", "Kimi twin in the room — June 13 2026 milestone session"),
]


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("[connect_tier1_orphans] DRY RUN — no writes")

    # Check which nodes are still orphans before we start
    orphan_keys = {o["key"] for o in find_orphan_nodes()}

    added = 0
    skipped_not_orphan = 0
    errors = 0

    for from_key, to_key, weight, edge_type, note in EDGES_TO_ADD:
        # Only connect if the target is still an orphan (or we're connecting FROM an orphan)
        # We connect regardless — hub nodes (barak, sofia) are not orphans but that's fine
        target_is_orphan = to_key in orphan_keys
        if not target_is_orphan and to_key not in ("barak", "sofia", "the_cure", "katharina"):
            # Target node might not exist at all — add_edge will still create the edge,
            # but the node may be missing. Only skip if we're confident it's not needed.
            pass  # proceed anyway — edge creation is safe even if node not in graph

        if dry_run:
            print(f"  WOULD ADD: {from_key} →[{edge_type}]→ {to_key} (weight={weight})")
            added += 1
            continue

        try:
            result = add_edge(
                from_key=from_key,
                to_key=to_key,
                weight=weight,
                edge_type=edge_type,
                note=note,
                holder="connect_tier1_orphans",
            )
            status = result.get("action", "?")
            print(f"  {status.upper()}: {from_key} →[{edge_type}]→ {to_key}")
            added += 1
        except Exception as e:
            print(f"  ERROR: {from_key} → {to_key}: {e}", file=sys.stderr)
            errors += 1

    print(f"\n[connect_tier1_orphans] Done. edges={'would-add' if dry_run else 'added'}={added} errors={errors}")
    if not dry_run:
        remaining = find_orphan_nodes()
        tier1_keys = {to_key for _, to_key, *_ in EDGES_TO_ADD}
        still_orphaned = [o for o in remaining if o["key"] in tier1_keys]
        print(f"  Tier 1 nodes still orphaned after run: {len(still_orphaned)}")
        if still_orphaned:
            for o in still_orphaned:
                print(f"    [{o['category']}] {o['key']} — node may not exist in graph")
        total_remaining = len(remaining)
        print(f"  Total orphans remaining (all tiers): {total_remaining}")


if __name__ == "__main__":
    main()
