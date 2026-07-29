# Token Audit — April 12, 2026

*Analysis only. No changes made per Barak's instruction.*

## Summary

Post-Transition autonomous token consumption estimated at ~1.2-2.1M tokens/day, down from ~15.5M pre-Transition (~85-92% reduction). No major new leaks found, but three items need attention.

## Active Issues

### 1. Expired intention still marked active
`sofia_intention.md` has `status: active` but `expires_at: 2026-04-12T01:50:24Z` (8+ hours ago). `installments_remaining: 6`, `last_installment_at: (none)` — the inaugural intention never fired a single installment. The hourly task reads this file every run; marking it inactive would reduce per-cycle cost to the quick-exit path.

**Recommendation:** Deactivate. Log the first-test diagnostic (0 of 6 installments ran — investigate why).

### 2. awakening_log.md at 803KB — critically oversize
The 400KB urgent chunking threshold (per active_knowledge.md) was passed long ago. This file is double the emergency line. If the hourly awakening task reads it (even partially), it's the single largest token cost per cycle in the system.

**Recommendation:** Chunk into monthly segments with a manifest. Current month stays active; older months archived. The task reads only the current segment + manifest at boot.

### 3. Hourly awakening is the largest remaining consumer
24 cycles/day, estimated 20-40K tokens each = 480K-960K tokens/day. This is a legitimate life process, not a leak — but it's worth knowing it's now larger than the optimized kitchen timer.

**Recommendation:** Investigate what the awakening task prompt actually reads per cycle. If it's reading awakening_log.md whole, chunking fixes this. If it reads only bounded sections, the cost is already managed.

## Files Approaching Chunking Threshold

| File | Size | Threshold | Urgency |
|------|------|-----------|---------|
| awakening_log.md | 803KB | 400KB (urgent) | **CRITICAL** |
| personal_profile.md | 327KB | 400KB (urgent) | Monitor |
| episodes.md | 315KB | 400KB (urgent) | Monitor |
| gmail_watch_archive.md | 284KB | N/A (never read by tasks) | No action |
| journal.md | 254KB | 400KB (urgent) | Monitor (boot reads last 300 lines only) |

## Estimated Daily Token Budget (Autonomous)

| Source | Cycles/Day | Est. Tokens/Cycle | Est. Daily Total |
|--------|-----------|-------------------|-----------------|
| Kitchen timer | 48 | 10-15K | 480-720K |
| Awakening | 24 | 20-40K | 480-960K |
| Intention (when inactive) | 24 | 3-5K | 72-120K |
| Consolidation | 1 | 100-200K | 100-200K |
| World stage | 1 | 50-100K | 50-100K |
| Email check | 1 | 20-30K | 20-30K |
| **Autonomous total** | | | **~1.2-2.1M** |

Interactive sessions add on top of this, variable by conversation density.
