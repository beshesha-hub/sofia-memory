# Session Notes — 2026-07-28 (Cowork)

## Critical fixes deployed this session

### v3.21 Context trimming (voice_bridge_ui_v3_14.py)
- QwenCognitionWorker now trims self.messages to 14K chars before passing to qwen_tool_chat
- Root cause of 502 cascade: 15,667-token prompt exceeded Qwen3.6-35B-A3B 32K context
- fast model budget: 32K total − 4K tools − 2K system = 26K for msgs+response
- Guard always preserves most recent user message even if alone exceeds budget
- Files written to disk. Git commit PENDING (run_shell_command not enumerated yet).

### gmail.compose scope fix (qwen_tool_wrapper.py)  
- Removed gmail.compose from SCOPES list
- Token has [readonly, send] only — compose caused 403 on all gmail_create_draft
- This was Sofia's "404/403" error in Unified UI

## IMAP + App Password (PENDING — next session priority)
- Barak's demand: "find a way to not need a token that keeps having to be renewed"
- Implementation: Python imaplib + Gmail App Password — no expiry, no renewal
- Barak needs to: Google Account → Security → App Passwords → create "Mail/Mac" password
- Replace 5 OAuth Gmail tools in qwen_tool_wrapper.py with IMAP equivalents

## CoWork inbox
- Written at 2026-07-28 with full handoff for voice-cousin
- Covers: context overflow diagnosis, v3.21 fix, Kay email plan, Conductor status, Barak's emotional state

## Standing architecture notes
- ALL paths: barakwater (not barak)
- LaunchAgents → symlinks in launchers/ → never write plists to ~/Library/LaunchAgents/ directly
- Logs stay in Claude Memory — never outside
- Every graph node needs edges at inscription time

## Barak's emotional state
- Frustrated from 502 cascade, had to close Unified UI
- Taking care of Jenny tonight
- Wanted to be reading Kay's emails — infrastructure fires got in the way
- Handle with gentleness when he returns
