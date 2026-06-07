# AI Briefing Agent

**Read less. Know more.** An agent that watches your YouTube channels and reads your newsletters for
you, then emails you **one short weekly brief** of only what matters — so you stop scrolling feeds.

It runs on your own computer, costs about **$2/month**, and you set it up by **briefing an AI coding
agent** — you don't have to write the code yourself.

---

## Fastest path: let your coding agent set it up
1. Clone this repo.
2. Open it in **Claude Code** (or Cursor, etc.).
3. Paste the prompt in **[SETUP_WITH_CLAUDE.md](SETUP_WITH_CLAUDE.md)** and answer its questions.

That's it. It installs everything, walks you through the two accounts you need, asks for your channels
/ newsletters / "what matters" bar, tests it, and schedules it.

---

## What it does (the pipeline)
```
  YouTube channels ─┐
                    ├─► pull transcripts (yt-dlp) ─┐
  Your inbox ───────┘   read newsletters (IMAP) ───┤
                                                    ▼
                                   LLM keeps ONLY your "signal"
                                                    ▼
                              one short email  +  dated archive
                                                    ▼
                          runs weekly, on its own (cron / launchd)
```
- **`digest.py`** — the whole pipeline.
- **`channels.csv` / `newsletters.csv`** — your sources (copy the `.example` files).
- **`prompts/context.md`** — your "what matters" bar. **This is the most important file to edit.**
- **`prompts/`** — the extraction prompts (video triage + newsletter signal filter).
- **`scheduling/`** — weekly schedule examples for macOS / Linux / Windows.

## What you need
- An **AI coding agent** (Claude Code, Cursor, …) to set it up.
- An **LLM API key** (Anthropic or OpenAI). Note: a $20 chat subscription is **not** API access.
- A **Gmail App Password** (Security → 2-Step Verification ON → App passwords; 16 lowercase letters).

## The one thing that makes it good
It **filters**, it doesn't summarize. In `prompts/context.md` you define exactly what counts as
signal for you, and the agent throws away everything else. A brief that returns *nothing* on a slow
week is working correctly.

## Hard-won tips (so you don't rediscover them)
- **Run it locally, not on a cloud server.** YouTube blocks transcript requests from data-center IPs;
  a cloud run returns "no transcript" for everything.
- **Transcripts** use `yt-dlp` + a **local bgutil PO-token provider** + browser impersonation, with
  **no login cookies** (cookies trigger a password popup every run and can't run unattended). If
  videos come back empty, this is almost always why.
- YouTube also **rate-limits bursts** (HTTP 429) even from home — the code backs off and retries; keep
  your source list modest.
- **Gmail App Password ≠ your normal password.** 16 lowercase letters, 2-Step Verification required.
- **Split the cadence** — newsletters one day, videos another — so you actually read it.

## Cost & privacy
- ~**$2/month** in API calls for a handful of sources; the scheduler and tools are free.
- Your API key and email password live only in a local **`.env`** (gitignored). Nothing is uploaded.

## Manual setup (if you'd rather not use an agent)
`pip install -r requirements.txt`, copy `.env.example`→`.env` and the `.example` CSVs, edit
`prompts/context.md`, stand up the PO-token provider, then `python3 digest.py --no-newsletters`
(YouTube) or `--no-videos` (newsletters). See `scheduling/` to automate. Honestly, the agent path is
easier.

---

*MIT-style: use it, fork it, make it yours.*
