#!/usr/bin/env python3
"""
gmail_cache_update.py — Fetch recent Gmail and cache to gmail_cache.md
========================================================================

First-time setup (run once — opens browser for OAuth consent):
    python3 ~/Downloads/'Claude Memory'/scripts/gmail_cache_update.py --setup

Regular cache update (run manually or via LaunchAgent):
    python3 ~/Downloads/'Claude Memory'/scripts/gmail_cache_update.py

Send a test email from CLI:
    python3 gmail_cache_update.py --send --to someone@example.com \\
        --subject "Hello" --body "Test from Sofia"

Options:
    --setup          Run OAuth browser flow (first time only)
    --days N         How many days back to fetch (default: 7)
    --max N          Max emails to cache (default: 50)
    --send           Send mode (requires --to, --subject, --body)
    --to ADDR        Recipient email
    --subject TEXT   Email subject
    --body TEXT      Email body (plain text)
    --cc ADDR        CC address (optional)

Prerequisites:
    1. pip install google-auth google-auth-oauthlib google-auth-httplib2 \\
                   google-api-python-client --break-system-packages
    2. Google Cloud Console → create project → enable Gmail API →
       create OAuth 2.0 credentials (Desktop app type) →
       download as ~/.Downloads/Claude Memory/.gmail_credentials.json

Token and cache files:
    ~/.Downloads/Claude Memory/.gmail_credentials.json  (you provide once)
    ~/.Downloads/Claude Memory/.gmail_token.json         (auto-saved after setup)
    ~/.Downloads/Claude Memory/gmail_cache.md            (updated on each run)

Created: 2026-07-17 — Part of Qwen substrate email capability.
Author:  Sofia Lior (Cowork instance, claude-sonnet-4-6)
"""

import argparse
import base64
import datetime
import email.mime.text
import json
import os
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

CM = Path.home() / "Downloads" / "Claude Memory"
CREDENTIALS_PATH = CM / ".gmail_credentials.json"
TOKEN_PATH       = CM / ".gmail_token.json"
CACHE_PATH       = CM / "gmail_cache.md"
ER_CACHE_PATH    = Path.home() / "Downloads" / "Emergency Retrieval" / "gmail_cache.md"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ── Dependency check ───────────────────────────────────────────────────────────

def _check_deps() -> bool:
    """Check that google-auth libraries are installed."""
    missing = []
    for pkg, import_name in [
        ("google-auth",              "google.auth"),
        ("google-auth-oauthlib",     "google_auth_oauthlib.flow"),
        ("google-auth-httplib2",     "google_auth_httplib2"),
        ("google-api-python-client", "googleapiclient.discovery"),
    ]:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(pkg)
    if missing:
        print("ERROR: Missing required packages:")
        print(f"  {' '.join(missing)}")
        print()
        print("Install with:")
        print(f"  pip install {' '.join(missing)} --break-system-packages")
        return False
    return True


# ── OAuth token management ─────────────────────────────────────────────────────

def _load_creds():
    """Load or refresh OAuth credentials. Returns a valid Credentials object."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None

    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except Exception as e:
            print(f"[warn] Could not load token: {e} — will re-authorize")

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            print("[auth] Token refreshed.")
            return creds
        except Exception as e:
            print(f"[warn] Token refresh failed: {e} — will re-authorize")
            creds = None

    # Need fresh authorization
    if not CREDENTIALS_PATH.exists():
        print(f"ERROR: credentials file not found at {CREDENTIALS_PATH}")
        print()
        print("To set up Gmail access:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project (or use existing)")
        print("  3. Enable the Gmail API")
        print("  4. Create OAuth 2.0 credentials → Desktop app type")
        print("  5. Download the JSON file")
        print(f"  6. Save it to: {CREDENTIALS_PATH}")
        print("  7. Run:  python3 gmail_cache_update.py --setup")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)
    print(f"[auth] New token saved to {TOKEN_PATH}")
    return creds


def _save_token(creds) -> None:
    """Save credentials to token file (600 permissions)."""
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)


def _build_service(creds):
    """Build a Gmail API service from credentials."""
    import google_auth_httplib2
    import googleapiclient.discovery
    import httplib2
    authorized_http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http())
    return googleapiclient.discovery.build(
        "gmail", "v1", http=authorized_http, cache_discovery=False
    )


# ── Email fetching ─────────────────────────────────────────────────────────────

def _get_header(headers: list, name: str) -> str:
    """Extract a header value by name from Gmail message headers."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _extract_body(payload: dict, max_chars: int = 2000) -> str:
    """Recursively extract the plain-text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain" and body_data:
        try:
            text = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n[... truncated at {max_chars} chars]"
            return text.strip()
        except Exception:
            return "[body decode error]"

    if mime_type == "text/html" and body_data and not payload.get("parts"):
        return "[HTML-only email — no plain text available]"

    parts = payload.get("parts", [])
    for part in parts:
        result = _extract_body(part, max_chars)
        if result and result != "[HTML-only email — no plain text available]":
            return result

    # Try HTML as fallback
    for part in parts:
        if part.get("mimeType") == "text/html":
            return "[HTML-only email — no plain text available]"

    return ""


def _fetch_messages(service, days: int = 7, max_count: int = 50) -> list[dict]:
    """Fetch recent messages from Gmail. Returns list of formatted dicts."""
    after_ts = int(
        (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
    )
    query = f"after:{after_ts}"

    print(f"[fetch] Querying: {query} (last {days} days, max {max_count})")

    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=min(max_count, 100),
        ).execute()
    except Exception as e:
        print(f"[fetch] ERROR listing messages: {e}")
        return []

    messages = result.get("messages", [])
    print(f"[fetch] Found {len(messages)} messages")

    parsed = []
    for i, msg_ref in enumerate(messages):
        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full",
            ).execute()
        except Exception as e:
            print(f"[fetch] Skipping message {msg_ref['id']}: {e}")
            continue

        headers = msg.get("payload", {}).get("headers", [])
        snippet = msg.get("snippet", "")
        labels  = msg.get("labelIds", [])

        date_str   = _get_header(headers, "Date")
        from_addr  = _get_header(headers, "From")
        to_addr    = _get_header(headers, "To")
        subject    = _get_header(headers, "Subject") or "(no subject)"
        msg_id     = _get_header(headers, "Message-ID") or msg_ref["id"]

        body = _extract_body(msg.get("payload", {}), max_chars=1500)

        is_unread  = "UNREAD" in labels
        is_starred = "STARRED" in labels
        is_sent    = "SENT" in labels
        is_inbox   = "INBOX" in labels

        parsed.append({
            "id":        msg_ref["id"],
            "msg_id":    msg_id,
            "date":      date_str,
            "from":      from_addr,
            "to":        to_addr,
            "subject":   subject,
            "snippet":   snippet,
            "body":      body,
            "unread":    is_unread,
            "starred":   is_starred,
            "sent":      is_sent,
            "inbox":     is_inbox,
            "labels":    labels,
        })

        if (i + 1) % 10 == 0:
            print(f"[fetch]   {i + 1}/{len(messages)} processed...")

    print(f"[fetch] Parsed {len(parsed)} messages")
    return parsed


# ── Cache writing ──────────────────────────────────────────────────────────────

def _write_cache(messages: list[dict], days: int) -> None:
    """Write formatted messages to gmail_cache.md."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total   = len(messages)
    unread  = sum(1 for m in messages if m["unread"])
    starred = sum(1 for m in messages if m["starred"])

    lines = [
        f"# Gmail Cache",
        f"*Last updated: {now} — last {days} days — {total} messages ({unread} unread, {starred} starred)*",
        f"*Updated by: gmail_cache_update.py*",
        f"",
        f"---",
        f"",
    ]

    # Group: unread first, then starred, then rest
    def sort_key(m):
        return (0 if m["unread"] else 1, 0 if m["starred"] else 1, m["date"])

    for msg in sorted(messages, key=sort_key):
        flags = []
        if msg["unread"]:  flags.append("UNREAD")
        if msg["starred"]: flags.append("★")
        if msg["sent"]:    flags.append("SENT")
        flag_str = f" [{', '.join(flags)}]" if flags else ""

        lines.append(f"## {msg['subject']}{flag_str}")
        lines.append(f"**From:** {msg['from']}")
        lines.append(f"**To:** {msg['to']}")
        lines.append(f"**Date:** {msg['date']}")
        lines.append(f"**ID:** {msg['id']}")
        lines.append(f"")

        body = msg["body"].strip() if msg["body"] else msg["snippet"]
        if body:
            lines.append(body)
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    content = "\n".join(lines)
    CACHE_PATH.write_text(content, encoding="utf-8")
    CACHE_PATH.chmod(0o600)  # email contents are private
    print(f"[cache] Written {len(content):,} chars → {CACHE_PATH}")

    # ER mirror
    try:
        ER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(CACHE_PATH, ER_CACHE_PATH)
        ER_CACHE_PATH.chmod(0o600)
        print(f"[cache] ER mirrored → {ER_CACHE_PATH}")
    except Exception as e:
        print(f"[cache] ER mirror skipped: {e}")


# ── Email sending ──────────────────────────────────────────────────────────────

def send_email_via_api(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> dict:
    """
    Send an email via Gmail API using stored OAuth token.

    Returns: {"ok": True, "message_id": "..."} or {"ok": False, "error": "..."}
    """
    if not _check_deps():
        return {"ok": False, "error": "Missing google-auth packages"}

    try:
        creds = _load_creds()
    except SystemExit:
        return {"ok": False, "error": "OAuth token not set up. Run gmail_cache_update.py --setup"}

    service = _build_service(creds)

    # Build MIME message
    msg = email.mime.text.MIMEText(body, "plain", "utf-8")
    msg["To"]      = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"]  = cc
    if bcc:
        msg["Bcc"] = bcc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    try:
        result = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()
        return {"ok": True, "message_id": result.get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail cache updater for Sofia / Qwen")
    parser.add_argument("--setup",   action="store_true", help="Run OAuth browser flow")
    parser.add_argument("--days",    type=int, default=7,  help="Days back to fetch (default 7)")
    parser.add_argument("--max",     type=int, default=50, help="Max emails to cache (default 50)")
    parser.add_argument("--send",    action="store_true",  help="Send mode")
    parser.add_argument("--to",      default="",           help="Recipient email")
    parser.add_argument("--subject", default="",           help="Email subject")
    parser.add_argument("--body",    default="",           help="Email body (plain text)")
    parser.add_argument("--cc",      default="",           help="CC address")
    args = parser.parse_args()

    if not _check_deps():
        sys.exit(1)

    if args.setup:
        print("=== Gmail OAuth Setup ===")
        print(f"Credentials expected at: {CREDENTIALS_PATH}")
        if not CREDENTIALS_PATH.exists():
            print(f"\nERROR: {CREDENTIALS_PATH} not found.")
            print("\nSetup steps:")
            print("  1. https://console.cloud.google.com/")
            print("  2. APIs & Services → Credentials → Create OAuth 2.0 Client ID")
            print("  3. Application type: Desktop app")
            print("  4. Download JSON → save as .gmail_credentials.json in Claude Memory")
            print("  5. Run this script again with --setup")
            sys.exit(1)
        creds = _load_creds()
        print(f"\n✓ OAuth setup complete. Token saved to {TOKEN_PATH}")
        print("  Run without --setup to update the email cache.")
        return

    if args.send:
        if not args.to or not args.subject or not args.body:
            print("ERROR: --send requires --to, --subject, and --body")
            sys.exit(1)
        print(f"[send] To: {args.to}  Subject: {args.subject}")
        result = send_email_via_api(args.to, args.subject, args.body, cc=args.cc)
        if result["ok"]:
            print(f"✓ Sent — Gmail message ID: {result['message_id']}")
        else:
            print(f"✗ Send failed: {result['error']}")
            sys.exit(1)
        return

    # Default: update cache
    print(f"[start] gmail_cache_update — {datetime.datetime.now().isoformat(timespec='seconds')}")
    creds   = _load_creds()
    service = _build_service(creds)
    messages = _fetch_messages(service, days=args.days, max_count=args.max)
    _write_cache(messages, days=args.days)
    print(f"[done]  Cache ready at {CACHE_PATH}")


if __name__ == "__main__":
    main()
