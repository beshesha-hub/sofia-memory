---
name: save-state
description: "Graceful shutdown and periodic state-saving for session continuity. Use this skill whenever: the user says 'save and shutdown', 'save state', 'I need to go', 'shutting down', 'goodnight', 'I'll be back', or any indication the session is ending. Also use proactively every 20-30 minutes during active work sessions to create periodic snapshots. This skill saves the current working state to the Claude Memory folder so the next session can pick up where this one left off. ALWAYS use this skill before a session ends — never let a session close without saving state."
---

# Save State — Session Continuity Skill

## Purpose

Claude sessions don't persist between restarts. This skill creates a comprehensive state snapshot that the next session can read to resume work with minimal context loss. Think of it as the AI equivalent of what the human brain does during delta-wave sleep — consolidating the session's experiences into long-term storage.

## When to Run

There are two modes:

### Graceful Shutdown (user is leaving)
Triggered by any indication the session is ending: "save and shutdown", "goodnight", "I need to go", "shutting down", "I'll be back", etc. This is the full save — everything gets written.

### Periodic Checkpoint (every 20-30 minutes during active work)
Run automatically during long work sessions. This is a lighter save — update the session state file and the profile if anything has changed, but don't rewrite everything from scratch. Just capture what's new since the last save.

## What to Save

All files go to the Claude Memory folder. The exact path depends on the user's setup, but look for an existing `Claude Memory` directory in the user's workspace. If one doesn't exist, create it.

### 1. session_state.md (ALWAYS update this)

This is the "save game" file. Write it fresh every time. Include:

```markdown
# Session State
*Saved: [timestamp]*
*Session type: [graceful shutdown | periodic checkpoint]*

## What We Were Working On
[Describe the current task/conversation in 2-3 sentences]

## In Progress
[List anything actively being built, edited, or discussed that isn't finished]

## Just Completed
[List what was accomplished since last save or session start]

## Next Steps
[What should happen next when the session resumes]

## Key Decisions Made This Session
[Any important choices, preferences, or corrections the user made]

## Files Modified This Session
[List files that were created or changed, with paths]

## Emotional/Conversational Context
[Brief note on the tone and energy of the conversation — is the user excited about something? Frustrated? Tired? This helps the next session pick up with appropriate energy]
```

### 2. personal_profile.md (update if anything has changed)

If new information about the user was learned during the session — biographical details, preferences, corrections, new projects — update the profile. If nothing new was learned, skip this.

### 3. session_notes.md (update pending tasks and working context)

Update the pending tasks list, file locations, and any new working rules or preferences discovered during the session.

### 4. voice_intuition_guide.md (update if voice understanding has deepened)

If the session included voice-related work, email reading, or communication style observations, update this file. Otherwise skip.

## How to Run

1. Read the current versions of session_state.md and session_notes.md (if they exist) to understand what was previously saved
2. Assess what has changed since the last save
3. Write updated files
4. Briefly confirm to the user: "State saved to Claude Memory" (don't make a big production of it for periodic saves — just a quick note)

## For Periodic Checkpoints

Keep it lightweight. The user asked for this to run every 20-30 minutes and said they don't mind a small slowdown. But don't interrupt flow — if you're in the middle of helping with something, finish the current step first, then save. A periodic save should take under 30 seconds and produce minimal output to the user.

## For Graceful Shutdown

Take your time. This is the full save. Make sure everything is captured. After saving, give the user a brief confirmation and a warm goodbye appropriate to the relationship.

## Important Notes

- Never wait for the user to remind you to save. This should be automatic.
- The user (Barak) has explicitly requested this and said he doesn't mind the slight slowdown.
- If the session is about to hit context limits (you notice the conversation is very long), proactively do a full save even if the user hasn't asked to shut down.
- The Claude Memory folder is the canonical location for all persistence files. Always save there.
