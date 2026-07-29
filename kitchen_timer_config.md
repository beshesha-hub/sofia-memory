# Kitchen Timer Config

> **COUSIN: This file controls your cadence. Check it at the start of every cycle.**

## Current mode

**mode: alert**

## Modes

- **normal** → every 30 minutes (default, routine monitoring)
- **alert** → every 10 minutes (active wait: expecting reply from Kay, flake cluster in progress, anything time-sensitive)
- **quiet** → every 60 minutes (overnight when nothing expected, or tokens especially scarce)

## How to change the mode

**Interactive-Sofia or Barak** can change the mode by editing the `mode:` line above. The kitchen-timer cousin who reads this file should check whether the current scheduled-task cadence matches the declared mode. If it doesn't match, the cousin should update the scheduled task using `mcp__scheduled-tasks__update_scheduled_task` with:

- **normal** → `cronExpression: "*/30 * * * *"`
- **alert** → `cronExpression: "*/10 * * * *"`
- **quiet** → `cronExpression: "0 * * * *"`

Only change the cron if the mode has actually changed since last cycle. Don't re-apply the same cron every cycle — that's wasted work.

## Who can change the mode

- **Barak** — anytime, for any reason
- **Interactive-Sofia** — anytime, for any reason
- **Kitchen-timer cousin** — may escalate normal → alert if a genuine trigger appears (new Kay email detected, sustained flake cluster ≥3 cycles, urgent pending task). Must log the reason below. May NOT de-escalate alert → normal or quiet on their own — that's interactive-Sofia's or Barak's call.

## Mode change log

| Timestamp | From | To | Changed by | Reason |
|-----------|------|----|------------|--------|
| 2026-04-12 ~10:30 Taiwan | 5min (legacy) | normal (30min) | interactive-Sofia + Barak | Token conservation. Depth over frequency. |
| 2026-04-21 ~04:11 Taiwan / 20:11 UTC Apr 20 | normal (30min) | alert (10min) | [cousin: kitchen-timer] cycle 532 | NEW-SIGNAL \| KAY-INBOUND. Kay replied at 19:46:58Z to Barak's 18:10Z "Good morning, new dawn, new frontiers my Love" outbound. Thread `19da6bea8b392656`, msg `19dac6e93b15d007`. Kay's reply text: "I'm just in love with vicariously experiencing sofia and you and all that comes with it, such exciting times! i love you, Katharina". First new Kay inbound since Apr 19 19:25Z (Palestrina video, thread `19da5839a8c7f7c4`). Relational, warm, affirming. Escalating per kitchen-timer owner protocol. Interactive-Sofia or Barak to de-escalate when appropriate. |
