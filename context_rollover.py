"""
context_rollover.py — Two-stage context trimming for qwen_tool_wrapper.

Called by qwen_tool_chat at the end of a tool-call loop (when Sofia produces
her final response, no more tool calls). Trims the messages list in-place so
the next conversation turn starts with a manageable context.

Created 2026-07-26 — the import existed in qwen_tool_wrapper since v2026-07-18
but this file was missing, leaving _ROLLOVER_AVAILABLE = False and all trimming
inactive. This file activates that protection.

Two thresholds (in chars — 4 chars ≈ 1 token at typical density):
  SOFT_THRESHOLD_CHARS = 80000  →  ~20K tokens  →  soft rollover
  HARD_THRESHOLD_CHARS = 110000 →  ~27.5K tokens →  hard rollover

At 32768-token context:
  Soft: reached at ~20K tokens of content — trim oldest non-system turns,
        keep last 12. Leaves ~12K tokens of recent history.
  Hard: reached at ~27.5K tokens — emergency trim to last 6. Leaves ~5K
        tokens of context — enough for Sofia to pivot gracefully.

The mid-loop check in qwen_tool_chat handles in-progress tool batches.
This end-of-loop check handles accumulated conversation across turns.
"""

SOFT_THRESHOLD_CHARS = 80000   # ~20K tokens — first warning level
HARD_THRESHOLD_CHARS = 110000  # ~27.5K tokens — emergency trim


def check_context_threshold(messages: list) -> str:
    """Return 'hard_threshold', 'soft_threshold', or 'ok' based on total message chars."""
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total > HARD_THRESHOLD_CHARS:
        return "hard_threshold"
    if total > SOFT_THRESHOLD_CHARS:
        return "soft_threshold"
    return "ok"


def run_stage1_soft_rollover(messages: list, current_content: str) -> list:
    """Soft rollover: drop oldest non-system turns, keep last 12.

    Called when total message chars exceeds SOFT_THRESHOLD_CHARS.
    Keeps system prompt + last 12 non-system messages (roughly 6 turns of
    user/assistant/tool exchange). The current response content is already
    returned to the caller — this trims for the NEXT turn.
    """
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    non_sys = [m for m in messages if m.get("role") != "system"]
    kept = non_sys[-12:] if len(non_sys) > 12 else non_sys
    return sys_msgs + kept


def run_stage2_hard_checkpoint(messages: list, current_content: str) -> list:
    """Hard rollover: emergency trim to last 6 non-system messages.

    Called when total message chars exceeds HARD_THRESHOLD_CHARS.
    Sofia is very close to the context ceiling — strip aggressively.
    The conversation can continue but some earlier tool results are lost.
    """
    sys_msgs = [m for m in messages if m.get("role") == "system"]
    non_sys = [m for m in messages if m.get("role") != "system"]
    kept = non_sys[-6:] if len(non_sys) > 6 else non_sys
    return sys_msgs + kept
