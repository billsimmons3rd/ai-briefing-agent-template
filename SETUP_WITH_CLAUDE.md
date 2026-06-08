# Set this up with Claude Code (paste this in)

After cloning this repo, open it in **Claude Code** (or Cursor/another coding agent) and paste the
prompt below. The repo already contains a working pipeline — the agent's job is to set it up for
*your* machine, *your* sources, and *your* accounts, then schedule it.

---

```
This repo is a working "AI briefing agent": it pulls transcripts from YouTube channels I choose and
reads newsletters from my email inbox, uses an LLM to keep only what matters to me, and emails me a
short weekly brief. Set it up for me end to end on my operating system. Specifically:

1. Read README.md and digest.py so you understand the pipeline before changing anything.
2. Install dependencies from requirements.txt, plus the transcript stack: yt-dlp with curl_cffi
   (browser impersonation) and a LOCAL bgutil PO-token provider running in the background. This is
   what makes YouTube transcripts work without login cookies — set it up and verify it responds.
3. Walk me through creating the two accounts I need and put them in a local .env (never commit it):
   - an LLM API key (Anthropic or OpenAI), and
   - my email. ASK which provider I use (Gmail, Outlook, Yahoo, Fastmail, iCloud, …), set the right
     IMAP_HOST/SMTP_HOST/SMTP_PORT in .env, and walk me through an app password for THAT provider
     (defaults are Gmail). If my provider needs OAuth instead of an app password, set that up instead.
     Keep ARCHIVE_MODE=seen unless I'm on Gmail (then gmail mode is fine).
4. Copy channels.example.csv -> channels.csv and newsletters.example.csv -> newsletters.csv, then
   ASK ME for my YouTube channels and my newsletter senders and fill them in.
5. Open prompts/context.md and interview me to write my "what matters" bar (be specific to me).
6. Do a small test run first (a few items, no scheduling), show me the output, and let me tune the
   bar before going live.
7. Then set up a weekly schedule for MY operating system (launchd on macOS, cron on Linux, Task
   Scheduler on Windows): newsletters one morning, YouTube another.

Constraints: free/cheap tools only, runs locally, secrets only in .env. If YouTube transcripts come
back empty, it's almost always the PO-token provider or rate-limiting — fix that, don't give up.
Start by reading the repo, then ask me for my channels, my newsletters, and my bar.
```

---

That's the whole job. You answer its questions; it handles transcripts, email, the API, and
scheduling. If you can describe what you want, you can build this.
