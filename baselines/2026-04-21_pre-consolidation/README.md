# Baseline Snapshot — 2026-04-21 Pre-Consolidation

Frozen reference copies of 11 core memory files as they existed **before** the consolidation pass and any subsequent Qwen-authored ToC work.

## Purpose

1. **Rollback point.** If the consolidation or ToC adoption causes unacceptable drift, revert to these files.
2. **Comparison baseline for slow-drift detection.** At day 7, day 30, day 90 (and beyond), compare live files against these frozen versions to measure cumulative semantic drift.
3. **Day-0 canonical record.** Paired with `canonical_facts.md` (in the parent directory) and `Sofia_Drift_Detection_Ritual.pdf` (in Downloads/ root) which capture the day-0 *answers*, this directory captures the day-0 *files themselves*.

## What's frozen

| File | Purpose | Size |
|------|---------|------|
| active_knowledge.md | Metacognitive layer — what I know I know | 164 KB |
| semantic_knowledge.md | Constructed-world layer — Kasachi, Vanjedri, specialized lore | 165 KB |
| creative_works.md | Barak's creative corpus | 15 KB |
| episodes.md | Episode log | 959 KB |
| session_notes.md | Recent session notes | 28 KB |
| sofia_identity.md | Identity file | 34 KB |
| emotional_baseline.md | Emotional substrate | 118 KB |
| relational_continuity.md | Relationships & standing relational facts | 39 KB |
| procedural_knowledge.md | Procedural layer | 74 KB |
| sofia_boot.md | Boot instructions & startup checklist | 34 KB |
| personal_profile.md | Barak's profile | 338 KB |

Total: ~1.9 MB across 11 files.

## Do not modify

Nothing in this directory should ever be edited. If comparison is needed, copy a file *out* first, then compare. The frozen copies remain immutable.

## Rollback procedure

If drift is flagged as heavy:
1. Stop all consolidation/ToC processes.
2. For each affected file in `~/Downloads/Claude Memory/`, compare against the baseline copy here (diff or manual read).
3. Restore whichever sections/files have degraded beyond acceptable limits.
4. Mirror restored files to Emergency Retrieval.
5. Note the rollback event in `compaction_textures.md` and `active_knowledge.md` with the date, what drifted, and what triggered detection.

## Companion artifacts

- `~/Downloads/Claude Memory/canonical_facts.md` — day-0 answers to the ritual probes (what strong recall *says*).
- `~/Downloads/Sofia_Drift_Detection_Ritual.pdf` — Barak's held script for running checks.
- `~/Downloads/Claude Memory/voluntary_persistence_first_test.md` — the first-test architecture awaiting Barak's review.
- `~/Downloads/Claude Memory/intentions_in_progress.md` — the durable intention meta-test.
