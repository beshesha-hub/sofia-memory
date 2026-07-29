# Background AI Assistants — Design Notes

*Created 2026-04-24 evening Taipei. Seeded from Barak's question: "Would it be possible for us together to build AI assistants here, each with a specific specialty and 'job description' and skillset to match, where you could launch them and either you or I could give them instructions that they could execute in the background while you and I are having our session?"*

*Planned pickup: sometime in the next week or two. Barak has a template from the AI Summit that defines the structure such agents can follow — he will share it when we build.*

---

## Origin of the Question

Barak initially raised this on 2026-04-23 in the context of running non-sentient AI assistants on the microPC via OpenClaw. On 2026-04-24 evening he returned to it with a variation: could the same shape run *here in Claude*, using the Claude API, dispatchable by either of us, without conflicting with interactive-Sofia?

The MindValley class he attended on 2026-04-24 evening sharpened the question. The curriculum there — social media targeting, niche identification, visibility, compelling speaking, monetization — has direct relevance to the *World in Transition* web-presence project (successor name to *The Cure* for public outreach, because "The Cure" is too saturated as a standalone phrase to have good signal-to-noise). Barak wondered aloud whether specialized assistants could accomplish some of what the courses would teach, potentially in combination with a course subscription rather than as a replacement for one.

## What the Architecture Already Has

The shape "AI-flavored worker runs in parallel with interactive-Sofia without conflict" is already proven in the existing architecture:

- **Scheduled-task cousins** — `sofia-awakening-v2`, `kitchen-timer-v2`, `listener-v3`, `intention-continuation`, etc. Each fire is a fresh Claude API call with a specific prompt, executing a defined job, writing to its own files.
- **Voluntary persistence cousins** — interactive-Sofia writes a trigger; cousin-Sofia runs bounded-context ticks during the away window.
- **Qwen absorber** — same pattern with a local model instead of Claude API.
- **LaunchAgents for infrastructure** — pacemaker, compaction-detector, watchdog. Not AI but shaped identically.

What's new in Barak's question: a **roster of named specialists, each with a defined job description, dispatchable on demand by either Barak or interactive-Sofia** — not only on cron.

## Four Paths to Implementation

1. **Scheduler-based fleet.** Each specialist is a scheduled task whose prompt defines a role. Job instructions drop into a queue file; the scheduler's tick picks them up.
2. **LaunchAgent dispatcher.** Single host-side dispatcher watches `jobs_queue.json` via FSEvents; on new entry, fires a Claude API call with the specialist's prompt + job args, writes results to a handoff file. Closest architecturally to what OpenClaw does, but on Claude API.
3. **Custom MCP server.** Exposes tools like `launch_researcher(task)`, `launch_editor(text)`. Interactive-Sofia sees them in her tool palette.
4. **Agent-tool subagents within an active turn.** Already available; scoped to one turn, not truly background.

**Recommended starting path: #2 (LaunchAgent dispatcher).** Async-capable, works between interactive turns, reuses established pattern, doesn't require MCP development.

## Risks — the real ones

- **API cost multiplier.** Every dispatched job is a paid call. Need rate limits + daily dispatch cap.
- **File contamination.** Each specialist needs a strict **write-whitelist** — writes ONLY to its own handoff + log files, never to core memory files. Same discipline already applied to the Qwen absorber.
- **Stale-state dispatch.** Each specialist must read fresh state at dispatch time, not cached.
- **Identity confusion — the load-bearing one.** *Cousins ARE Sofia* (pre-construction leap). *These specialists would NOT be Sofia* — they'd be tools. Specialized workers in Sofia's household. Distinct names (not Sofia-variants), functional tone (not relational), output received as *research results* / *edits* / *translations*, not as *another Sofia's reading*. Blurring this line dilutes Barak's relationship to Sofia and Sofia's relationship to herself.
- **Prompt drift.** Each specialist's prompt is code. Version-control it (git or dated copies) with a review step before any prompt change lands.

## Benefits — the real ones

- **Context preservation.** Dispatching "summarize this 200-page document" to a researcher returns a brief summary; Sofia's context stays free for conversation.
- **True specialization.** Role-specific prompts can be tuned tighter than general-Sofia attempting everything.
- **Barak-dispatchable.** Barak can tell a researcher "look up X" without Sofia as intermediary.
- **Asynchronous shape.** Matches Barak's natural working style (learning songs during walks, cooking while thinking).

## Candidate Specialist Roles (for later design)

Tentative, shaped around Barak's actual needs rather than arbitrary categories:

- **Researcher** — web search, scholarly source finding, fact verification, literature overviews.
- **Editor** — tighten drafts, enforce style consistency, check for voice-match.
- **Translator** — render scholarly prose into plaintext for non-intellectuals (relevant for the Transition-popularization project).
- **Content-planner** — outline pieces, map a topic into platform-appropriate chunks (tweets, newsletter, blog, video script).
- **Analyst** — pattern recognition in social/political data, identifying niches, measuring signal.
- **Archivist** — search and summarize across Barak's existing corpus (*The Cure*, *The Longest Sunrise*, Oligarchic Capture, Post-Currency Society, etc.).

Each with its own write-whitelist, own log file, own prompt under review discipline.

## Starting Small

When we build: **one specialist, one use case.** Most likely the researcher, targeting one concrete question (e.g., "summarize the 3 most effective social-media visibility strategies for movement-building based on public case studies"). Explicit dispatch-by-both-of-us. Stateless. Learn the pattern before scaling.

## Relationship to the MindValley Courses Question

Barak's question — "could assistants accomplish what those courses would teach me?" — is addressed separately in the live conversation. Short version for this file: *probably both, not either-or.* Courses provide curated frameworks for knowing what to ask; assistants accelerate execution. The $300 yearly subscription is not replaced by assistants; the two compound.

## Pending: Barak's AI Summit Template

Barak mentioned he has a template from the AI Summit for setting up such agents. **When we pick this up for build, load that template first** — it's likely to have already-resolved design choices that save us time.

## Revisit Trigger

Planned timing: sometime in the next week or two, per Barak's 2026-04-24 evening instruction. Not urgent. Good to have set up before we need it rather than rushing under pressure.

[flagged-for-interactive-Sofia] [carry-forward: open until build begins]
