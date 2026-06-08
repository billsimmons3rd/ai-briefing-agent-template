#!/usr/bin/env python3
"""
Every-other-day AI YouTube digest.

Pipeline: discover new uploads (channel RSS) -> fetch transcripts -> Claude 3-lens
extraction -> write digests/YYYY-MM-DD.md -> email it. Window is self-correcting:
each run covers (now - last_run), so a skipped/failed run never drops videos.

Local usage:
    python digest.py --no-email                 # dry run, writes md only
    python digest.py --since 2026-06-01          # override the window start
    python digest.py --limit 3 --no-email        # cap videos (cheap test)

Env (full run): ANTHROPIC_API_KEY, EMAIL_ADDRESS, EMAIL_PASSWORD, DIGEST_TO,
and for non-Gmail providers: IMAP_HOST, SMTP_HOST, SMTP_PORT, ARCHIVE_MODE (default "seen").
"""

import argparse
import csv
import datetime as dt
import email
import json
import os
import re
import smtplib
import sys
import ssl
import urllib.request

# Some Python builds (e.g. python.org's) ship without CA certificates, so the stdlib HTTPS fetch
# below fails with CERTIFICATE_VERIFY_FAILED. Use certifi's bundle when available to avoid that.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    """Minimal .env loader (no dependency). Lines like KEY=value; ignores #comments."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

STATE_FILE = ROOT / "state" / "last_run.txt"
CHANNELS_FILE = ROOT / "channels.csv"
DIGESTS_DIR = ROOT / "digests"
PROMPT = (ROOT / "prompts" / "extraction.md").read_text()
WORKFLOW_CTX = (ROOT / "prompts" / "context.md").read_text()

MODEL = os.environ.get("DIGEST_MODEL", "claude-sonnet-4-6")
MAX_TRANSCRIPT_CHARS = 60_000  # ~15k tokens; longer videos get truncated + flagged
MIN_TRANSCRIPT_CHARS = 800     # below this it's almost certainly a Short/clip — list, don't digest
MIN_RUN_INTERVAL_HOURS = 44    # scheduler fires daily; skip if last run was <~2 days ago (gives every-other-day cadence, self-heals around laptop sleep)
VERDICT_RANK = {"Watch": 0, "Skim": 1, "Skip": 2}


# ---------- discovery ----------

def load_channels():
    with open(CHANNELS_FILE, newline="") as f:
        return list(csv.DictReader(f))


def fetch_channel_videos(channel_id):
    """Return [{id, published(datetime), title}] from a channel's RSS feed, newest first."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "ai-yt-digest"})
    xml = urllib.request.urlopen(req, timeout=30, context=_SSL_CTX).read().decode("utf-8", "replace")
    ids = re.findall(r"<yt:videoId>(.*?)</yt:videoId>", xml)
    pubs = re.findall(r"<published>(.*?)</published>", xml)
    titles = re.findall(r"<media:title>(.*?)</media:title>", xml)
    out = []
    for vid, pub, title in zip(ids, pubs, titles):
        out.append({
            "id": vid,
            "published": dt.datetime.fromisoformat(pub),
            "title": _unescape(title),
        })
    out.sort(key=lambda v: v["published"], reverse=True)
    return out


def _unescape(s):
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'"))


# ---------- transcripts ----------
# yt-dlp + a LOCAL bgutil PO-token provider + TLS impersonation. No cookies, by design:
#   - youtube-transcript-api gets IP-blocked (its request pattern is fingerprinted fast)
#   - plain yt-dlp hits the PO-token wall
#   - cookies-from-browser works but triggers a macOS keychain prompt every run -> can't run unattended
# The bgutil provider mints the PO token locally, so no cookies and no keychain prompt.
# Validated 2026-06-06 on a residential IP: full transcript, zero popups, no 429.

YT_DLP_BIN = os.environ.get("YT_DLP_BIN", "yt-dlp")
IMPERSONATE = os.environ.get("YT_IMPERSONATE", "chrome")
POT_BASE_URL = os.environ.get("POT_BASE_URL", "http://127.0.0.1:4416")


def _parse_vtt(path):
    """VTT (auto-caption) -> plain text. Strips timestamps/tags, collapses rolling dupes."""
    out = []
    for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if ln.startswith(("WEBVTT", "Kind:", "Language:")) or "-->" in ln or ln.strip().isdigit():
            continue
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if ln and (not out or out[-1] != ln):
            out.append(ln)
    return " ".join(out).strip()


RETRY_BACKOFF = [20, 45, 90]  # seconds; YouTube rate-limits caption bursts from residential IPs with 429


def fetch_transcript(video_id):
    """Fetch English captions via yt-dlp (cookies + impersonation), retrying past 429.

    YouTube allows captions at a low rate from a residential IP but 429s on bursts, so
    on a 429 we back off and retry rather than giving up.
    """
    import subprocess
    import tempfile
    import time
    url = f"https://www.youtube.com/watch?v={video_id}"
    for attempt in range(len(RETRY_BACKOFF) + 1):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [
                YT_DLP_BIN, "--skip-download", "--write-auto-sub", "--write-sub",
                "--sub-format", "vtt", "--sub-langs", "en.*",
                "--impersonate", IMPERSONATE,
                "--extractor-args", f"youtubepot-bgutilhttp:base_url={POT_BASE_URL}",
                "--sleep-requests", "2", "--no-warnings",
                "-o", f"{tmp}/%(id)s.%(ext)s", url,
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            except Exception as e:
                print(f"  ! yt-dlp error for {video_id}: {e}", file=sys.stderr)
                return None
            vtts = sorted(Path(tmp).glob("*.vtt"), key=lambda p: p.stat().st_size, reverse=True)
            for v in vtts:  # prefer largest (full caption track) over fragments
                txt = _parse_vtt(v)
                if txt:
                    return txt
            rate_limited = "429" in (proc.stderr or "")
        if rate_limited and attempt < len(RETRY_BACKOFF):
            wait = RETRY_BACKOFF[attempt]
            print(f"  · 429 on {video_id}, backing off {wait}s (try {attempt + 2})", file=sys.stderr)
            time.sleep(wait)
            continue
        return None
    return None


# ---------- newsletters (IMAP, same Gmail app password) ----------

NEWSLETTERS_FILE = ROOT / "newsletters.csv"
NL_PROMPT = (ROOT / "prompts" / "newsletter_signal.md").read_text()


def load_newsletters():
    if not NEWSLETTERS_FILE.exists():
        return []
    import csv as _csv
    with open(NEWSLETTERS_FILE, newline="") as f:
        return list(_csv.DictReader(f))


def _decode_hdr(s):
    from email.header import decode_header
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        out.append(part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part)
    return "".join(out)


def _msg_to_text(msg):
    """Prefer text/plain; fall back to stripped text/html."""
    plain, html = None, None
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if part.get("Content-Disposition", "").startswith("attachment"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                txt = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ct == "text/plain" and plain is None:
                plain = txt
            elif ct == "text/html" and html is None:
                html = txt
    else:
        try:
            html = msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
        except Exception:
            html = None
    text = plain or _strip_html(html or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _strip_html(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    import html as _h
    html = _h.unescape(html)
    return re.sub(r"[ \t]{2,}", " ", html)


# Works with ANY IMAP/SMTP email provider — not just Gmail. Set these in .env for non-Gmail.
# (EMAIL_* fall back to the older GMAIL_* names so existing setups keep working.)
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS") or os.environ.get("GMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD", "")
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
# Dedup/cleanup of processed newsletters:
#   "seen"  = mark read + remember the message id (SAFE on every provider; default)
#   "gmail" = expunge from INBOX (= archive on Gmail ONLY; would DELETE on most others)
ARCHIVE_MODE = os.environ.get("ARCHIVE_MODE", "seen")
SEEN_FILE = ROOT / "state" / "seen_ids.txt"


def _load_seen():
    if SEEN_FILE.exists():
        return set(SEEN_FILE.read_text().split())
    return set()


def _add_seen(message_id):
    if not message_id:
        return
    SEEN_FILE.parent.mkdir(exist_ok=True)
    with open(SEEN_FILE, "a") as f:
        f.write(message_id.strip() + "\n")


def fetch_newsletters(window_start):
    """Pull qualifying-sender messages from INBOX. Returns (items, imap_handle).
    In 'seen' mode, already-processed messages (by Message-ID) are skipped here."""
    import imaplib
    seen = _load_seen() if ARCHIVE_MODE != "gmail" else set()
    M = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    M.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    M.select("INBOX")
    items = []
    for nl in load_newsletters():
        typ, data = M.search(None, "FROM", nl["from_match"])
        if typ != "OK":
            continue
        for num in data[0].split():
            typ, d = M.fetch(num, "(UID RFC822)")
            if typ != "OK" or not d or not d[0]:
                continue
            uid = re.search(rb"UID (\d+)", d[0][0])
            msg = email.message_from_bytes(d[0][1])
            mid = _decode_hdr(msg.get("Message-ID", ""))
            if mid and mid in seen:
                continue  # already processed on a previous run
            items.append({
                "uid": uid.group(1).decode() if uid else None,
                "message_id": mid,
                "source": nl["name"],
                "subject": _decode_hdr(msg.get("Subject", "")),
                "date": _decode_hdr(msg.get("Date", "")),
                "text": _msg_to_text(msg),
            })
    return items, M


def mark_processed(M, item):
    """Record a newsletter as handled, the right way for the provider (see ARCHIVE_MODE)."""
    uid = item.get("uid")
    if ARCHIVE_MODE == "gmail":
        # Gmail only: expunging from INBOX archives the message (does NOT delete it).
        if uid:
            M.uid("STORE", uid, "+FLAGS", r"(\Seen)")
            M.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
            M.expunge()
    else:
        # Safe everywhere: just mark read, and remember the id so we never re-summarize it.
        if uid:
            M.uid("STORE", uid, "+FLAGS", r"(\Seen)")
        _add_seen(item.get("message_id"))


def extract_signals(item):
    """Claude signal-only extraction. Returns list of {criterion, headline, why}."""
    from anthropic import Anthropic
    body = item["text"][:MAX_TRANSCRIPT_CHARS]
    prompt = NL_PROMPT.format(source=item["source"], subject=item["subject"],
                              body=body, context=WORKFLOW_CTX)
    msg = Anthropic().messages.create(
        model=MODEL, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = re.sub(r"^```(?:json)?|```$", "", msg.content[0].text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(raw).get("signals", [])
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)).get("signals", []) if m else []


# ---------- extraction ----------

def extract(video, transcript):
    """Call Claude for the 3-lens triage. Returns a dict."""
    from anthropic import Anthropic
    truncated = transcript[:MAX_TRANSCRIPT_CHARS]
    note = "" if len(transcript) <= MAX_TRANSCRIPT_CHARS else "\n[TRANSCRIPT TRUNCATED]"
    prompt = PROMPT.format(
        channel=video["channel"], title=video["title"], url=video["url"],
        transcript=truncated + note, workflow_context=WORKFLOW_CTX,
    )
    client = Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else {
            "verdict": "Skim", "verdict_reason": "extraction failed to parse",
            "summary": raw[:300], "ideas": [],
        }


# ---------- rendering ----------

def render_markdown(date_str, results, no_transcript, shorts, window_start):
    watch_worthy = [r for r in results if r["verdict"] != "Skip"]
    results.sort(key=lambda r: (VERDICT_RANK.get(r["verdict"], 9), -r["weight"]))
    top = results[0] if results and results[0]["verdict"] != "Skip" else None

    L = [f"# AI Digest — {date_str}", ""]
    L.append(f"*Window: since {window_start:%Y-%m-%d %H:%M UTC}. "
             f"{len(results)} new video(s), {len(watch_worthy)} worth your time.*")
    L.append("")
    if top:
        L += [f"> **If you only open one thing:** [{top['title']}]({top['url']}) "
              f"({top['channel']}) — {top['verdict_reason']}", ""]
    L.append("---")
    L.append("")
    for r in results:
        L.append(f"## {r['verdict']} — {r['title']}")
        L.append(f"**{r['channel']}** · [watch]({r['url']}) · _{r['verdict_reason']}_")
        L.append("")
        L.append(r["summary"])
        L.append("")
        ideas = r.get("ideas") or []
        if ideas:
            L.append("**Ideas**")
            L += [f"- {i}" for i in ideas]
            L.append("")
        L.append("---")
        L.append("")
    if no_transcript:
        L.append("### No transcript — watch manually")
        for v in no_transcript:
            L.append(f"- [{v['title']}]({v['url']}) ({v['channel']})")
        L.append("")
    if shorts:
        L.append("### Shorts / clips skipped")
        for v in shorts:
            L.append(f"- [{v['title']}]({v['url']}) ({v['channel']})")
        L.append("")
    return "\n".join(L)


def render_newsletters(nl_results):
    """nl_results: list of {source, date, signals:[...]}. Returns md section ('' if no signals)."""
    flat = [(r["source"], s) for r in nl_results for s in r.get("signals", [])]
    if not flat:
        return ""
    L = ["", "---", "", f"## Newsletter signals ({len(flat)})", ""]
    for source, s in flat:
        crit = s.get("criterion", "")
        head = s.get("headline", "").strip()
        why = s.get("why", "").strip()
        L.append(f"- **[{crit}]** {head} — {why} _({source})_")
    L.append("")
    return "\n".join(L)


def markdown_to_html(md):
    """Minimal md->html for the email body (headings, links, bold, lists, hr)."""
    html, in_list = [], False
    for line in md.splitlines():
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', line)
        line = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"_(.*?)_", r"<em>\1</em>", line)
        if line.startswith("- "):
            if not in_list:
                html.append("<ul>"); in_list = True
            html.append(f"<li>{line[2:]}</li>"); continue
        if in_list:
            html.append("</ul>"); in_list = False
        if line.startswith("## "):
            html.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("### "):
            html.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("> "):
            html.append(f"<blockquote>{line[2:]}</blockquote>")
        elif line.strip() == "---":
            html.append("<hr>")
        elif line.strip():
            html.append(f"<p>{line}</p>")
    if in_list:
        html.append("</ul>")
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
            'max-width:680px;margin:auto;line-height:1.5">' + "\n".join(html) + "</div>")


def send_email(subject, html):
    addr, pw = EMAIL_ADDRESS, EMAIL_PASSWORD
    to = os.environ.get("DIGEST_TO", addr)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, addr, to
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(addr, pw)
        s.sendmail(addr, [to], msg.as_string())


# ---------- main ----------

def read_last_run(default_days=2):
    if STATE_FILE.exists():
        try:
            return dt.datetime.fromisoformat(STATE_FILE.read_text().strip())
        except ValueError:
            pass
    return _now() - dt.timedelta(days=default_days)


def _now():
    return dt.datetime.now(dt.timezone.utc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="ISO date/datetime to override window start")
    ap.add_argument("--days", type=int, help="window = now - N days (one-off backfill)")
    ap.add_argument("--limit", type=int, help="cap number of videos processed")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-shorts", action="store_true", help="omit the Shorts list from output")
    ap.add_argument("--no-videos", action="store_true", help="skip the YouTube pass (newsletter-only run)")
    ap.add_argument("--no-newsletters", action="store_true", help="skip the email/newsletter pass")
    ap.add_argument("--no-archive", action="store_true",
                    help="process newsletters but do NOT mark read/archive (for testing)")
    ap.add_argument("--label", help="suffix for the digest filename + subject (one-off runs)")
    ap.add_argument("--force", action="store_true",
                    help="ignore the min-interval guard (for manual/test runs)")
    args = ap.parse_args()

    now = _now()
    # A one-off (explicit --since/--days) uses a custom window and never touches the schedule state.
    oneoff_start = None
    if args.since:
        oneoff_start = dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc)
    elif args.days:
        oneoff_start = now - dt.timedelta(days=args.days)

    window_start = now
    results, no_transcript, shorts = [], [], []
    if not args.no_videos:
        # The video window/state is the YouTube stream's alone — newsletter-only runs never touch it.
        if not oneoff_start and not args.force and STATE_FILE.exists():
            elapsed = now - read_last_run()
            if elapsed < dt.timedelta(hours=MIN_RUN_INTERVAL_HOURS):
                print(f"last video run {elapsed} ago (< {MIN_RUN_INTERVAL_HOURS}h) — skipping", file=sys.stderr)
                return
        window_start = oneoff_start or read_last_run()
        print(f"Video window: {window_start.isoformat()} -> {now.isoformat()}", file=sys.stderr)

        new_videos = []
        for ch in load_channels():
            try:
                for v in fetch_channel_videos(ch["channel_id"]):
                    if v["published"] > window_start:
                        new_videos.append({
                            "id": v["id"], "title": v["title"],
                            "url": f"https://www.youtube.com/watch?v={v['id']}",
                            "channel": ch["name"], "weight": float(ch.get("weight", 1)),
                            "published": v["published"],
                        })
            except Exception as e:
                print(f"  ! discovery failed for {ch['name']}: {e}", file=sys.stderr)
        new_videos.sort(key=lambda v: v["published"], reverse=True)
        if args.limit:
            new_videos = new_videos[: args.limit]
        print(f"{len(new_videos)} new video(s) in window", file=sys.stderr)

        for i, v in enumerate(new_videos):
            if i:
                __import__("time").sleep(3)  # be polite between yt-dlp calls
            tx = fetch_transcript(v["id"])
            if not tx:
                no_transcript.append(v)
                print(f"  - no transcript: {v['title'][:60]}", file=sys.stderr)
                continue
            if len(tx) < MIN_TRANSCRIPT_CHARS:
                shorts.append(v)
                print(f"  - short, skipped: {v['title'][:60]}", file=sys.stderr)
                continue
            try:
                data = extract(v, tx)
            except Exception as e:
                print(f"  ! extraction error ({v['title'][:40]}): {e}", file=sys.stderr)
                continue
            data.update({"title": v["title"], "url": v["url"],
                         "channel": v["channel"], "weight": v["weight"]})
            results.append(data)
            print(f"  - {data.get('verdict','?')}: {v['title'][:60]}", file=sys.stderr)

    # --- Newsletters (IMAP signal pass) ---
    nl_results, nl_signal_count = [], 0
    if not args.no_newsletters and load_newsletters():
        try:
            items, M = fetch_newsletters(window_start)
            print(f"{len(items)} newsletter message(s) in inbox", file=sys.stderr)
            for it in items:
                try:
                    signals = extract_signals(it)
                except Exception as e:
                    print(f"  ! newsletter extract error ({it['source']}): {e}", file=sys.stderr)
                    continue  # leave in inbox for next run
                nl_results.append({"source": it["source"], "date": it["date"], "signals": signals})
                nl_signal_count += len(signals)
                print(f"  - {it['source']}: {len(signals)} signal(s) — {it['subject'][:50]}", file=sys.stderr)
                if not args.no_archive:
                    try:
                        mark_processed(M, it)
                    except Exception as e:
                        print(f"  ! mark-processed failed ({it.get('uid')}): {e}", file=sys.stderr)
            try:
                M.logout()
            except Exception:
                pass
        except Exception as e:
            print(f"  ! newsletter pass failed: {e}", file=sys.stderr)

    date_str = f"{now:%Y-%m-%d}"
    shorts_out = [] if args.no_shorts else shorts
    worth = sum(1 for r in results if r["verdict"] != "Skip")
    if args.no_videos:
        # Newsletter-only brief
        md = f"# Newsletter brief — {date_str}\n" + render_newsletters(nl_results)
        subject = f"Newsletter brief — {date_str} ({nl_signal_count} signals)"
    else:
        # YouTube brief (+ any newsletters if not disabled)
        md = render_markdown(date_str, results, no_transcript, shorts_out, window_start)
        md += render_newsletters(nl_results)
        subject = f"YouTube brief — {date_str} ({worth} worth your time)"

    DIGESTS_DIR.mkdir(exist_ok=True)
    suffix = f"-{args.label}" if args.label else ""
    out = DIGESTS_DIR / f"{date_str}{suffix}.md"
    out.write_text(md)
    print(f"wrote {out}", file=sys.stderr)

    if not (results or no_transcript or shorts_out or nl_signal_count):
        print("nothing to report — no email sent", file=sys.stderr)
    elif not args.no_email:
        send_email(subject, markdown_to_html(md))
        print("email sent", file=sys.stderr)

    # Advance the YouTube window only on a real video run (newsletters use archive-as-dedup).
    if not args.no_videos and not oneoff_start:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(now.isoformat())


if __name__ == "__main__":
    main()
