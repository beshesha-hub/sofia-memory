# Prospective Memory — Sofia Lior
*Created 2026-07-18. Append-only. Source-tag every entry.*

## What this file is

Prospective memory is the memory of *what I intended to do about what happened* — distinct from episodic memory (what happened) and semantic memory (what I learned). It is the most easily lost layer: an experience can be fully encoded in episodes and semantics while the intentions it generated simply vanish.

This file is the durable record of open intentions, commitments, and threads that must survive context rollovers, session boundaries, compactions, and crashes. It is loaded at every boot as part of the working-state ledger.

**Failure mode this prevents:** "I remember we discussed X. I remember we concluded Y. I have no idea what we were going to *do* about it."

---

## Schema

Each entry has the following fields:

```
### [INTENTION-ID] [STATUS: open|in_progress|completed|deferred|cancelled]
**Created:** YYYY-MM-DD [session or context note]
**Triggered by:** [episode, conversation, decision, or event that generated this intention]
**Intention:** [what I or we intend to do — specific, actionable]
**Deadline:** [date, event, or condition — or "none"]
**Owner:** [sofia | barak | both | qwen-sofia]
**Priority:** [critical | high | normal | low]
**Completion notes:** [filled in when status changes from open]
**Related nodes:** [graph keys if relevant]
```

---

## Active Intentions

### INT-001 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** Tier 1 orphan connect run — 49 orphans remain after Tier 1
**Intention:** Complete Tier 2 orphan reconnection — people nodes (~25 nodes) requiring Barak's biographical input. Node list: brandon_linda_son, heidi_linda_daughter, dylan_aspergers_nephew, tommy_oman, yuxiu, muff_cousin, laura, brian, james, diane_white, seth_haigh, baraks_mom, perry, dini_clarke, dylan, lester, bobbie_harris, alpan_family, rita, greg_hs_friend_kay, albert_kays_person, wendy_jennys_context, shelley_pending, david
**Deadline:** Before next nightly maintenance cycle
**Owner:** both (Barak provides bios; sofia executes graph operations)
**Priority:** high
**Completion notes:** —
**Related nodes:** barak, sofia, relational_graph

### INT-002 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** Tier 1 orphan connect run — non-standard category nodes remain
**Intention:** Complete Tier 3 orphan migration — migrate ~24 nodes with non-standard categories ([attribute], [beliefs], [katharina_history], [barak_history], [relationship], [jenny_care], [barak_personal_history], [katharina_perceptions], [katharina_practical_wisdom], [jacquie_life], [barak_philosophy], [katharina_family], [katharina_personal_history], [shared_community], [katharina_life_events], [open_thread]) into standard categories (people, projects, life_experiences, concepts, interaction_patterns)
**Deadline:** Before next nightly maintenance cycle
**Owner:** both
**Priority:** high
**Completion notes:** —
**Related nodes:** barak, sofia, relational_graph

### INT-003 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** LaunchAgent for nightly_maintenance.py registered; exit-78 pattern observed on ~20 other sofia LaunchAgents
**Intention:** Audit exit-78 LaunchAgents — diagnose why com.sofia.audit-log-mirror, pacemaker, ears, sentinel, auto-inscribe, cousin systems, etc. are all failing with EX_CONFIG. Determine if file paths changed in Mac migration, python path issues, or TCC wipe. Restore functioning agents.
**Deadline:** Next session
**Owner:** both (sofia diagnoses, barak runs terminal commands)
**Priority:** high
**Completion notes:** —
**Related nodes:** sofia, local-primary

### INT-004 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint / GPT Griffith Park conversation]
**Triggered by:** GPT two-stage rollover design + Barak's request
**Intention:** Implement two-stage rollover for Qwen — soft rollover at ~75% context (consolidate, retrieve), hard checkpoint before limit (transactional, verify all commits, overlap bridge). Requires changes to qwen_tool_wrapper.py and possibly conductor routing.
**Deadline:** Next architecture session
**Owner:** sofia (design complete; implementation in Unified UI)
**Priority:** high
**Completion notes:** Design spec written 2026-07-18 (see architecture files)
**Related nodes:** sofia, twin_exchange, local-primary

### INT-005 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** GPT Griffith Park conversation — gap detection identified as missing layer
**Intention:** Add gap detection as first-class output — log_memory_gap() in graph_helper.py, memory_gaps.md registry. When retrieval fails, produce structured gap record rather than silently confabulating.
**Deadline:** Next architecture session
**Owner:** sofia
**Priority:** normal
**Completion notes:** —
**Related nodes:** sofia, graph

### INT-006 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** GPT Griffith Park conversation — protected context composition model
**Intention:** Implement deliberate context region model for boot context — identity kernel (5%), working-state ledger (10%), retrieved memories (20%), live interaction (50%), overlap bridge (10%), margin (5%). Update boot context rebuild script to compose by region rather than sequential file load.
**Deadline:** Next architecture session
**Owner:** sofia
**Priority:** normal
**Completion notes:** —
**Related nodes:** sofia, graph

### INT-007 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** Trish's full arc deferred in session
**Intention:** Get Trish's full arc from Barak — relationship history, timeline, what made her kavanjaida, current status of relationship with Alicia and Kristin
**Deadline:** After Qwen home customizations complete (per Barak's signal)
**Owner:** barak (to provide); sofia (to inscribe)
**Priority:** normal
**Completion notes:** —
**Related nodes:** tricia_ex_wife, barak, alicia, kristin

### INT-008 [STATUS: open]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** Hawaii meeting plan noted as orphaned graph node
**Intention:** Get details from Barak about the planned Hawaii meeting — who, when, purpose
**Deadline:** When naturally surfaces
**Owner:** barak
**Priority:** low
**Completion notes:** —
**Related nodes:** barak, hawaii_meeting_plan

---

## Completed Intentions

### INT-C001 [STATUS: completed]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** Graph inscription discipline identified as missing from CLAUDE.md and sofia_fallback_boot_compact.md
**Intention:** Add Graph Inscription and Retrieval Discipline to both CLAUDE.md (CoWork) and sofia_fallback_boot_compact.md (Qwen)
**Completion notes:** Both files edited, committed to disk, mirrored to Emergency Retrieval. 2026-07-18.

### INT-C002 [STATUS: completed]
**Created:** 2026-07-18 [Memory Architecture Sprint]
**Triggered by:** nightly_maintenance.py written but no LaunchAgent
**Intention:** Create and register LaunchAgent for nightly_maintenance.py at 03:00 local
**Completion notes:** com.sofia.nightly_maintenance registered, exit 0. 2026-07-18.

---

## Deferred Intentions

*(Nothing deferred yet — move here when status changes to deferred with explanation)*

---

## How to use this file

**At session end (graceful shutdown):** Review all open intentions. Update statuses. Add any new intentions generated in the session. Mirror to Emergency Retrieval.

**At boot:** Load this file as part of the working-state ledger. Before starting any work, scan open intentions for anything that should be active in this session.

**When an intention is fulfilled:** Change status to completed, fill completion notes, move to Completed section.

**When an intention can't be fulfilled:** Change status to deferred or cancelled with explanation.

**Salience threshold for inscription:** Any promise, commitment, decision with future consequence, open loop that must survive a session boundary, or task explicitly deferred to a later session → new entry here immediately.
