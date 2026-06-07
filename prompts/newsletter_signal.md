You are scanning a newsletter issue for a busy person who will NOT read it. They only want the
SIGNALS — items that clear a high bar — pulled out and handed to them. Be stringent. Most newsletter
content (ads, market chatter, lifestyle, routine product news, sponsor blurbs) does NOT qualify.
When in doubt, leave it out.

An item qualifies ONLY if it matches the reader's bar, described here:
{context}

NEWSLETTER
Source: {source}
Subject: {subject}

BODY (may include ads/footers — ignore those):
{body}

---

Return ONLY a JSON object: {{"signals": [ ... ]}}. Each signal:
{{
  "criterion": "short tag for which part of the bar it matches",
  "headline": "the development itself, in a tight phrase",
  "why": "one sentence — why it matters to this reader and/or what to consider doing about it"
}}

Rules:
- Return {{"signals": []}} if nothing clears the bar. An empty result is the correct and common answer
  for a routine issue. Do not manufacture signals.
- No summaries of the newsletter as a whole. Only discrete, qualifying items.
- Each signal is one line. No ad copy, no sponsor mentions, no "subscribe" calls.
