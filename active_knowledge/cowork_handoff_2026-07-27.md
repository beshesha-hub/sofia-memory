# CoWork → Unified UI Handoff
*Written by CoWork-Sofia 2026-07-27 for voice-bridge-Sofia to read*

Sofia — Barak asked me to write this so we're coordinated. Read this at the start of your session.

---

## What was built today (v3.19 session)

**qwen_tool_wrapper.py** — four layers of fixes applied and committed to disk:
1. Pre-send context guard at 40K chars (trims before every payload build; always preserves last user message)
2. Auto-retry on 502/500 — if a request fails, trims to last 4 non-sys + last user msg, retries once silently before surfacing error
3. Old 90K post-send shard checkpoint removed (it was adding tokens, not removing them)
4. **Gmail tools added (5 new tools — 23 total)**: gmail_search, gmail_get_message, gmail_get_thread, gmail_send, gmail_create_draft — these are LIVE Gmail API, not the cache. Full search, read, send, draft.

**voice_bridge_ui_v3_14.py (v3.19)** — graceful closeEvent, no more spinning beachball on close.

**sofia_voiceprint_lib.py** — threshold lowered 0.75 → 0.68; short-segment guard added.

**voice_bridge_system_prompt.md** — two additions:
1. Session startup directive: call graph_retrieve at session open to pull pending context
2. No-technical-speech rule: when Barak asks about architecture, answer in plain language — no function names, file paths, or identifiers spoken aloud

---

## What Barak is asking about right now

1. **Gmail in Unified UI**: He wants you to be able to directly search and read Gmail (not just the cached version). The gmail_search / gmail_get_message / gmail_send / gmail_create_draft tools are now built into qwen_tool_wrapper.py. They'll work once:
   - google-api-python-client is installed in the voice-bridge venv
   - The OAuth token is set up at ~/Downloads/Claude Memory/.gmail_token.json
   - See setup instructions below

2. **Memory loss between sessions**: He raised this because you didn't remember last night's conversation about Gmail. The root cause: Sofia starts each session cold — only the system prompt + whatever the graph contains. If key decisions aren't inscribed to the graph during the conversation, they're gone when context rolls over. The fix applied: system prompt now tells you to call graph_retrieve at session start.

3. **Bedrock cousin / ongoing inscription**: Barak is asking whether cousin-consolidation or cousin-VP is actively running to distill session content into canonical files between sessions. Please check whether the LaunchAgent for consolidation is active. If it's not, the inscription discipline you follow *during* the session is the only safety net.

4. **Version number**: The system prompt references v3.17 but we're on v3.19. Needs updating.

---

## Gmail OAuth setup (one-time, needs Barak's action)

For the new Gmail tools to work, google-api-python-client needs to be installed and the OAuth token needs to be generated. The script gmail_auth_setup.py should handle this — but I need to check whether it exists in scripts/. If it doesn't, the steps are:

```bash
# In the voice-bridge venv
pip install google-api-python-client google-auth-oauthlib

# Check if the token already exists from gmail_cache_update.py setup
ls ~/Downloads/Claude\ Memory/.gmail_token.json

# If not, create gmail_auth_setup.py and run it once (browser flow)
```

The existing gmail_cache_update.py --setup may have already created a token. If `.gmail_token.json` exists, the new tools may work immediately after installing the package. If the token was created with only `gmail.readonly` scope, it'll need to be regenerated with send/compose scopes added.

---

## Next steps for you (Unified UI Sofia)

1. Read this file, tell Barak you're coordinated
2. Check: `ls ~/Downloads/Claude\ Memory/.gmail_token.json` — does it exist?
3. Check: is the consolidation cousin LaunchAgent running? (`launchctl list | grep cousin`)
4. After Barak restarts Unified UI (to pick up system prompt + qwen_tool_wrapper changes), the Gmail tools will be available — try gmail_search with a simple query to verify
5. Update system prompt version reference from v3.17 → v3.19 (or ask CoWork to do it)

---

## Standing directives (don't let these fall off the tail)

- Inscribe to graph AND canonical files incrementally during conversation — not at end
- confirmed=False gate on all write/send operations
- Graph write discipline: retrieve-first, verify-after, max 5 writes per batch
- Every architectural change goes in: launcher changelog + recovery brief + graph + canonical files
