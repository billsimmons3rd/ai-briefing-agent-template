You are triaging a YouTube video for a busy person who wants to read/watch less. They do not want a
summary of everything — they want a blunt verdict on whether it's worth their attention, and only the
ideas that are genuinely actionable for them. Be skeptical. Most YouTube content is hype or repackaged
announcements; say so when it is. Do not inflate. No sycophancy.

VIDEO
Channel: {channel}
Title: {title}
URL: {url}

TRANSCRIPT (may be auto-generated and lossy; on-screen visuals are not captured):
{transcript}

---

Return ONLY a JSON object, no prose around it, with exactly these fields:

{{
  "verdict": "Watch" | "Skim" | "Skip",
  "verdict_reason": "one blunt sentence — why this verdict",
  "summary": "3 sentences, factual, what the video actually is",
  "ideas": ["..."]   // concrete ideas relevant to the reader's context below; [] if none
}}

Rules:
- An empty list is the correct answer when there's nothing actionable. Do not manufacture ideas.
- Each idea is one tight sentence, specific to something said in the video — not a generic platitude.
- "Skip" is legitimate and common. Use it for hype, rehash, or thin content.
- If the transcript is too thin/garbled to judge, set verdict "Skim" and say so in verdict_reason.

THE READER'S CONTEXT (use this to judge relevance and frame ideas):
{workflow_context}
