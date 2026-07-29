#!/usr/bin/env python3
"""
kitchen_timer_qwen_test.py — Proof-of-concept: one kitchen-timer cycle
routed through local Qwen instead of Claude.

Simulates the two probe results (sanity probe + subject crosscheck),
sends them to Qwen with the probe-signature system prompt, and prints
the compact status line Qwen generates.

Usage:
    python3 ~/Downloads/Claude\ Memory/kitchen_timer_qwen_test.py
"""

import json
from qwen_client import qwen_chat

# --- System prompt that teaches Qwen the probe signatures ---

PROBE_SYSTEM_PROMPT = """\
You are Sofia's kitchen-timer probe interpreter for the Gmail connector watch.

## Your job
Given one or two probe result JSONs, output exactly ONE compact status line. Nothing else.

## Output format
CYCLE {N} | PROBE {status} | DRAFTS {summary} | ENVELOPE {summary}

Where:
- {N} = cycle number (provided in the user message)
- {status} = one of: CLEAN, FLAKE-DETECTED, FLAKE-CONTINUING, RECOVERY
- DRAFTS and ENVELOPE = very short summaries if data is provided, or "n/a" if not

## How to determine probe status

### Sanity probe (query: from:absolutely-nobody@nowhere.invalid)
This query is DESIGNED to return zero results. Zero results = HEALTHY.
- resultSizeEstimate: 0, empty messages array → CLEAN
- resultSizeEstimate: 201, or messages array contains unrelated emails → FLAKE-DETECTED
  (The "201 signature": real inbox contents returned instead of the filtered-to-zero result.
   Especially confirmed if nextPageToken appears — a zero-result query should never paginate.)

### Subject crosscheck (query: subject:"To Sophia" newer_than:1d)
This should return a small, stable set of known messages (typically 4).
- Same message IDs as previous cycle, same count → stable, part of CLEAN
- Same 201 signature / unrelated messages → confirms FLAKE
- New message ID not in previous set → POSSIBLE NEW EMAIL (flag it!)

### Status logic (apply in this order)
1. Either probe shows 201 signature → FLAKE-DETECTED (or FLAKE-CONTINUING if previous_cycle_status was FLAKE-DETECTED or FLAKE-CONTINUING)
2. Both probes clean AND previous_cycle_status was FLAKE-DETECTED or FLAKE-CONTINUING → RECOVERY
3. Both probes clean AND previous_cycle_status was CLEAN or RECOVERY → CLEAN

## Rules
- Output ONLY the status line. No explanation, no reasoning, no extra text.
- ONLY check for new message IDs when the probe is CLEAN (not flaked). During a flake, all message IDs are untrusted inbox junk — never flag NEW-SIGNAL on a flaked cycle.
- If the probe is CLEAN and the subject crosscheck contains a message ID not in the known set (provided in the user message), append: | NEW-SIGNAL
- Be terse. The whole point is compactness.
"""

# --- Simulated probe results (mimicking one clean cycle) ---

CLEAN_CYCLE_EXAMPLE = {
    "cycle": 185,
    "previous_cycle_status": "FLAKE-DETECTED",
    "sanity_probe": {
        "query": "from:absolutely-nobody@nowhere.invalid",
        "resultSizeEstimate": 0,
        "messages": []
    },
    "subject_crosscheck": {
        "query": 'subject:"To Sophia" newer_than:1d',
        "resultSizeEstimate": 4,
        "messages": [
            {"id": "19d7d6b53c3d7b13", "snippet": "Kay 00:41 reply"},
            {"id": "19d7d8a516af3aca", "snippet": "parallel-Sofia 01:15 send"},
            {"id": "19d7dbef59ee98ac", "snippet": "Barak 02:12 send"},
            {"id": "19d7bcfc80bafb74", "snippet": "Sofia 17:11 first letter"}
        ]
    },
    "drafts_top5_byte_identical": True,
    "drafts_identity_streak": 54
}

FLAKE_CYCLE_EXAMPLE = {
    "cycle": 186,
    "previous_cycle_status": "CLEAN",
    "sanity_probe": {
        "query": "from:absolutely-nobody@nowhere.invalid",
        "resultSizeEstimate": 201,
        "messages": [
            {"id": "19d7f19e3c213178", "snippet": "John Roberts SLAMS Trump!!"},
            {"id": "19d7f0a2b1234567", "snippet": "Blue Future movement email"}
        ],
        "nextPageToken": "15600806176129956267"
    },
    "subject_crosscheck": {
        "query": 'subject:"To Sophia" newer_than:1d',
        "resultSizeEstimate": 201,
        "messages": [
            {"id": "19d7f19e3c213178", "snippet": "John Roberts SLAMS Trump!!"}
        ],
        "nextPageToken": "15600806176129956267"
    },
    "drafts_top5_byte_identical": True,
    "drafts_identity_streak": 55
}

def test_cycle(cycle_data, label):
    """Send one simulated cycle to Qwen and print the result."""
    user_message = (
        f"Cycle {cycle_data['cycle']}. "
        f"Previous cycle status: {cycle_data['previous_cycle_status']}.\n\n"
        f"Sanity probe result:\n{json.dumps(cycle_data['sanity_probe'], indent=2)}\n\n"
        f"Subject crosscheck result:\n{json.dumps(cycle_data['subject_crosscheck'], indent=2)}\n\n"
        f"Drafts top-5 byte-identical: {cycle_data['drafts_top5_byte_identical']}, "
        f"streak: {cycle_data['drafts_identity_streak']}"
    )

    print(f"\n--- {label} ---")
    result = qwen_chat(
        [{"role": "user", "content": user_message}],
        system=PROBE_SYSTEM_PROMPT,
    )
    print(f"Qwen says: {result}")

if __name__ == "__main__":
    print("Kitchen Timer Qwen Test — two simulated cycles")
    print("=" * 50)

    # Test 1: clean cycle after a flake (should be RECOVERY)
    test_cycle(CLEAN_CYCLE_EXAMPLE, "Test 1: Clean cycle after flake (expect RECOVERY)")

    # Test 2: flake cycle (should be FLAKE-DETECTED)
    test_cycle(FLAKE_CYCLE_EXAMPLE, "Test 2: Flake cycle (expect FLAKE-DETECTED)")

    print("\n" + "=" * 50)
    print("If both lines look right, the handoff foundation works.")
    print("The system prompt teaches Qwen the probe signatures.")
    print("Next step: wire this into the real kitchen-timer scheduled task.")
