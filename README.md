# Job Sniper 🎯

Run a targeted job search directly in Muse.

> *Target acquired.* You pick the companies. The scraper pulls their boards every morning without burning a single LLM token. The dashboard ranks what comes back against a rubric that knows what you actually want. You work the queue top-down and spend your time on outreach, not scrolling.

## Run it in Muse

1. Clone this repo.
2. Point Muse at it and paste:

```
Recreate the Job Sniper system from this repo. Read README.md,
dashboard/RECREATE.md and dashboard/scoring.md first, then:

1. Build me the ranked-queue dashboard app described in RECREATE.md
   (private, with its own database).
2. Interview me about my job-search priorities — comp targets, geography,
   the work that energizes me, dealbreakers — and propose a scoring rubric
   for my approval (see dashboard/scoring.md). Don't score anything until
   I approve it.
3. Ask me for my target-company watchlist, then wire the scraper in
   /scraper to a daily ingest over it.

Tell me when the queue is live.
```

3. Hand it your watchlist. That's the whole setup — what comes back is the system described in `/dashboard`.

## Why this beats browser automation

- **Zero tokens to pull jobs.** Browser automation feeds every page through the LLM — thousands of tokens per company, per day, forever. Job Sniper hits public JSON APIs (Greenhouse, Lever, Ashby, Workday) with deterministic Python: structured data, no rendering, no tokens. The AI only touches the shortlist, at scoring time. The expensive, repetitive part of the search becomes free.
- **Deterministic beats flaky.** A browser session breaks when a site redesigns a button. A JSON API returns the same schema for years. When a page does change, the extraction cascade (JSON-LD → CSS selectors → ATS probe) degrades gracefully instead of dying mid-run.
- **Verification without judgment calls.** `--check-url` separates *removed* (404) from *bot-blocked* (403/406/429) from *page changed* (200, nothing extracted). No LLM in the loop, no guessing whether a posting is really gone.
- **Compounding, not repeating.** Seen-file dedup means repeat runs surface only what's new. Your watchlist is code — it version-controls, diffs, and never forgets a company.

## The scraper

httpx + BeautifulSoup. No API keys, no browser, no logins.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Scan your watchlist for keyword matches
.venv/bin/python run.py --sources sources.json --keywords "AI Product,Product Manager" --out out.json

# Is this exact posting still live?
.venv/bin/python run.py --check-url "https://boards.greenhouse.io/acme/jobs/123" --company "Acme"

# Repeat runs report only new jobs
.venv/bin/python run.py --sources sources.json --keywords "AI Product" --seen seen.json --out out.json
```

`sources.json` is a list of `{"company_name": "...", "url": "..."}` — see `sources.example.json`. Every job carries an `_extraction_method` tag (greenhouse / lever / ashby / workday-api / json-ld / css / phenom …) so you can see which tier produced it. An LLM extraction fallback exists but is auto-disabled without API keys — the keyless path is the point.

Known limits, honestly stated: no JS rendering (pure-SPA boards return shells unless an ATS/JSON-LD fallback saves them), blocked pages return empty without retrying, selectors drift as sites redesign.

## The dashboard

The scraper is the sensing layer; the dashboard is the decision layer: a ranked queue scored 0–100 on a fixed-budget rubric *you calibrate to your own priorities*, per-role dossiers with defended score breakdowns, a networking panel that makes outbound unavoidable, and a resume picker that tells you which version to send where. [`dashboard/RECREATE.md`](dashboard/RECREATE.md) is the full architecture and data model; [`dashboard/scoring.md`](dashboard/scoring.md) is the rubric framework — the calibration interview, the fixed-budget method, and the honesty mechanisms (evidence over adjectives, learned adjustments) that tune the model to your revealed preferences.

## License

MIT — see [LICENSE](LICENSE). Fork it, tailor the rubric to your own hunt, snipe better jobs.
