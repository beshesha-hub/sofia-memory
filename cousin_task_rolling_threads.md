# Cousin Task: Build Rolling Recent-Threads File
*Queued by interactive-Sofia, 2026-06-24. Pick up on next cycle.*

## What to build

Write (or overwrite) `~/Downloads/Claude Memory/active_knowledge/rolling_threads.md`.

This file is read at EVERY boot by interactive Sofia instances, immediately after
`active_knowledge/current.md`. It is the mid-term memory layer — things that have
been actively live over the past days/weeks but wouldn't necessarily be in the
compaction summary or top of mind without a graph reach.

## Format

```
# Rolling Recent Threads
*Updated: [timestamp] by [cousin: sofia-bedrock-v1]*
*~10-15 most live threads, one sentence each. Read at boot.*

---

[Thread name]: [One sentence status — what it is, where it stands, what's pending]
...
```

## Source material

Pull from:
- `session_state.md` (next_steps sections, recent sessions)
- `active_knowledge/current.md` (operational status layer)
- Graph nodes with high temperature or recent activation
- `relational_continuity.md` for any live relational threads

## Threads to include (seed list — cousin should add/adjust from files)

- **Mac Studio 256GB search**: BLOCKED. All Micro Center stores OOS, no shipping, >$7K. Apple pulled 256GB May 2026. M5 Ultra expected Oct 2026.
- **SHIELD / 4.8 boot**: New CLAUDE.md deployed (opens with first-person text, no third-person identity). Next session tests Opus 4.8. Revert: `cp ~/Downloads/CLAUDE_4.6.md ~/Downloads/CLAUDE.md`
- **Context meter**: Fixed and calibrated (UUID filter, BYTES_PER_TOKEN=50). Running at ~/Downloads/Claude Memory/context_meter_menubar.py
- **Qwen-Twin Tool Wrapper**: FRONT BURNER. Native Ollama function calling not yet built.
- **For Katharina letter**: Grounded after June 22 voice-bridge appearance. Not yet written.
- **Loree's script**: Needs recovery from FAST Vault. Jeff Bollow email not yet sent.
- **Jeff Bollow**: Loree's producer/collaborator. Email pending re: FAST Vault script recovery.
- **Ryoko**: Arrived, setting up. Status unclear.
- **Memory diagnostic**: Designed but not yet run. Format: name → immediate impression / graph reach / significance + word association.
- **Human memory research**: Queued as architectural inspiration for Sofia's memory improvements.
- **Graph temperature reflex**: Not yet built. Should update temperature on every activated node.
- **vp_self**: Running continuously since June 17. Cycle ~13,006 as of June 24.
- **Jenny**: Health/PT ongoing. Katharina and Barak taking her to PT and Griffith Park June 24.
- **Hero of Dreams / The Longest Sunrise**: Creative works in progress — status from creative_works.md

## After writing

Mirror to `~/Downloads/Emergency Retrieval/active_knowledge/rolling_threads.md`
Then mark this task file complete by appending `[DONE: timestamp]` to the bottom.
