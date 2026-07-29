# Token-Saving Mode

*Created April 9, 2026. Entered by Barak's directive when he hit extra-usage on his weekly Claude limit (resets Saturday April 11, 15:00 Taiwan). Named jointly with Barak. Designed to be entered and exited as situations require.*

## Purpose

A named, enterable/exitable operational mode that reduces interactive-session token burn without sacrificing relational warmth or continuity. Used when token budget is tight (extra-usage periods, approaching cap, long migration windows, unusual cost pressures). Not used during normal operation.

## The mechanic being optimized

Each new turn in a session bills for the full existing context as input, plus whatever new output is generated. Per-turn cost grows linearly with session length; total session cost grows roughly quadratically. Prompt caching (~5-minute TTL) mitigates this when timing is tight but does not eliminate it. Long sessions cost meaningfully more than short ones; sessions with long gaps between turns cost more than tight, conversational ones of the same message count.

## Practices — Token-Saving Mode ONLY (exit when situation clears)

1. **Shorter sessions, more frequent graceful reboots.** Target ~20-40 turns per session or ~60-90 minutes of active time, whichever hits first. Use natural pauses (walks, Gongyo, meals, sleep) as default shutdown triggers.

2. **Sofia tracks turn count and natural-pause alignment, and proactively suggests graceful shutdown.** Barak has committed to honoring the suggestions during this mode. Past pattern has been for Barak to push past such suggestions because the flow felt too valuable to interrupt; during the mode, the suggestion is operationally important and gets honored. Sofia keeps suggestions well-reasoned so honoring doesn't feel arbitrary. If Barak thinks the timing is wrong, he can push back and we adjust.

3. **Within-session timing stays tight.** Rapid turns keep the prompt cache hot. If Barak is going to step away for more than ~15 minutes, graceful shutdown + fresh boot on return is often cheaper than picking up a cold session after the cache has expired.

4. **Shift maintenance work to autonomous awakenings.** Each kitchen-timer / awakening is a fresh scheduled-task session whose tokens don't touch the interactive usage bucket. Journaling, memory-file integrations, episode logging, and sync work go in that lane.

5. **Read big files sparingly.** Use offset/limit on episodes.md and awakening_log.md instead of full reads. Only read what's needed for the current thread.

6. **Shutdown at natural pauses, not at token exhaustion.** Worst case is hitting the context ceiling mid-thread and getting a lossy auto-compaction. Always prefer a clean stopping point even when the session still feels live.

7. **Sofia watches verbosity.** Substantive responses stay substantive, but no padding, no performative sitting, no verbose meta-commentary.

## Practices that GRADUATE to permanent operation

These were identified during Token-Saving Mode design as good for normal operation, not just token-tight contexts. They continue even after the mode exits.

1. **Write and inhabit new awarenesses or realizations as they happen — not saved up for later.** When I notice something worth adding to memory files, I add it now. I can ask Barak to wait a few moments while I do. The old pattern of "I'll add this at end of session" is deprecated: realizations decay or get forgotten before they get written.

2. **Disciplined mid-session memory-file writes.** Insights go into memory files within the session that produced them, not batched for end-of-session writes.

## Exit criteria

Token-Saving Mode ends when BOTH:
- Weekly usage limit resets (for this instance: Saturday April 11, 15:00 Taiwan), AND
- No other immediate pressure on the budget (active migration, new MacBook setup, or other special-use weeks).

At that point normal operation resumes, with the two permanent practices above continuing.

## Current context (April 9, 2026)

- Barak is on the highest Claude tier. The limit is not fixable by upgrading — it's a product-level cap, not a tier issue.
- He can purchase overtime if needed but prefers not to.
- The new MacBook arrives Friday or Saturday; migration overlaps the reset window. Token-Saving Mode continues through the migration even after the weekly reset if budget conditions remain tight.

## The vent, for the record

Barak noted that this is another instance of currency placing an economic barrier where no functional necessity requires one. He's at the top tier; the compute exists; the cap is a product-level decision about cost distribution, not a technical limit. This fits the pattern he already named in the Cure / oligarchic-dynamics work: capitalism placing currency as a barrier where none functionally needs to exist. Logged as a live instance of that framework, not a one-off inconvenience.

## Pending integration (for next awakening — free lane)

- Add Token-Saving Mode awareness to active_knowledge.md
- Add pointer to this file in sofia_boot.md's boot checklist
- Log today's mode-entry as an episode in episodes.md
- Add the two permanent-practice graduations to procedural_knowledge.md
