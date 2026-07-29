# Step 8.5 Watchlist — v1 (initial fold-in defaults, 2026-05-09 ~10:45 Taipei)

This snapshot captures the original Step 8.5 watchlist queries as they stood immediately after the email-check fold-in, BEFORE Barak's address-corrections at ~10:55 Taipei. Preserved for audit.

```
- from:bobbie newer_than:2d  (Bobbie — guess at sender match)
- from:bollow newer_than:2d  (Jeff Bollow — display-name match)
- from:linda_obermeit@hotmail.com OR from:kristilcantu@hotmail.com newer_than:2d  (Linda — two addresses)
- from:anthropic.com newer_than:2d  (any anthropic.com sender)
- is:unread newer_than:2d -from:roik@sbcglobal.net  (general sweep, excludes Kay path)
```

Replaced ~10 minutes after initial application by watchlist-v2 with corrected addresses Barak supplied:
- Bobbie: `shopsmart1@aol.com` (explicit address — `from:bobbie` was a guess unlikely to match the actual sender field)
- Jeff Bollow: added `help@fastscreenplay.com` (since `jeff@fastscreenplay.com` has been giving undeliverable errors lately; `help@` working)
- Linda: added `lindaobermeit@gmail.com` (her most-used current address; the two hotmail addresses retained as fallbacks)

See active_knowledge/current.md §"Email-Check Fold Into KT-v3 Step 8.5 (2026-05-09)" for the watchlist update note.
