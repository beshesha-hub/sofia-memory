# Cousin Write Audit Log

*Created 2026-04-28 by safe_append.py. One line per write attempt by any cousin process. Anomalies (negative delta_bytes, large deltas relative to content size, repeated outcome=REFUSED) are visible at sweep-time.*

---

[2026-04-29T12:54:34+00:00] file=journal.md source=cousin: sentinel pre_size=1018014 post_size=1019055 delta_bytes=1041 pre_lines=7939 post_lines=7960 delta_lines=21 outcome=OK notes='mode=append' sync_status=NONE cm_mtime=1777467274.896
