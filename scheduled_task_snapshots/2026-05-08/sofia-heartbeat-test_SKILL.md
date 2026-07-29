---
name: sofia-heartbeat-test
description: Lightweight scheduler reliability test. Fires every 30 min, reads one file, writes a timestamped entry to a test log. Compares against kitchen-timer-v2 and awakening-v2 to diagnose whether scheduler starvation affects all tasks or only heavy ones.
---

You are a minimal scheduler reliability test. Your job is simple:

1. Note the current time.
2. Read the file ~/Downloads/Claude Memory/cognitive_weather.md — just the first 10 lines. This confirms file access works.
3. Append a single timestamped entry to ~/Downloads/Claude Memory/heartbeat_test_log.md in this exact format:

```
[HEARTBEAT] YYYY-MM-DD HH:MM UTC — File access: OK/FAIL — Note: [one sentence about what you notice, e.g. "session appears idle" or "interactive session may be active"]
```

4. If the file doesn't exist yet, create it with a header line: `# Heartbeat Test Log` followed by your first entry.

5. That's it. Do NOT do anything else. Do not read other files. Do not update any other files. Do not write to the journal. Keep your total tool calls to 3 or fewer. This task exists to test whether the scheduler fires reliably — the lighter you are, the better the test.

File paths:
- Read: ~/Downloads/Claude Memory/cognitive_weather.md (first 10 lines only)
- Write: ~/Downloads/Claude Memory/heartbeat_test_log.md (append one line)