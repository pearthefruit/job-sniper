# Job Sniper 🎯

An AI job-search command center: a keyless job-board scraper plus the complete spec for the ranked dashboard it feeds.

> *Target acquired.* Stop scrolling job boards like a meatbag. Point the scraper at the companies you want, score what comes back against a rubric that reflects your actual priorities, and work the ranked queue.

## What this is

This repo is proof of work for building with AI. It has two parts:

- **`/scraper`** — real, runnable code. A Python job scraper (httpx + BeautifulSoup, zero API keys, zero browser automation) that pulls postings from public ATS JSON APIs (Greenhouse, Lever, Ashby), Workday APIs, and generic career pages via a JSON-LD → CSS-selector → ATS-probe extraction cascade. Originally built for my private job-discovery project; cleaned up for public release.
- **`/dashboard`** — a recreation guide, not a code dump. The ranked dashboard is a private hosted app and hosted apps can't be exported, so this folder documents the full architecture, data model, and scoring rubric — everything you need to rebuild it yourself (ideally by handing the spec to your own AI agent).

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Discovery: scan boards for keyword matches
.venv/bin/python run.py --sources sources.json --keywords "AI Product,Product Manager" --out out.json

# Verify a single posting: live, removed, or bot-blocked?
.venv/bin/python run.py --check-url "https://boards.greenhouse.io/acme/jobs/123" --company "Acme"

# Repeat runs only report new jobs
.venv/bin/python run.py --sources sources.json --keywords "AI Product" --seen seen.json --out out.json
```

`sources.json` is a list of `{"company_name": "...", "url": "..."}` — see `sources.example.json`. Point it at the career pages and ATS boards of companies you actually want to work for.

## How the scraper works

Each source is routed by URL to the right extractor, and every job carries an `_extraction_method` tag so you can see which tier produced it:

| Tier | What it does |
|---|---|
| ATS APIs | Greenhouse / Lever / Ashby public JSON endpoints — the highest-signal source |
| Workday API | Direct Workday job-search API probing (with locale-segment handling) |
| JSON-LD | Schema.org `JobPosting` structured data, when the page embeds it |
| CSS selectors | Snapshot-based selectors for common career-page layouts |
| Phenom | Embedded-JSON extraction for Phenom-powered boards |
| LLM fallback | Optional; auto-disabled when no API keys are set |

`--check-url` verification mode distinguishes what scrapers usually lump together: `live` (200 + job extracted), `gone_404`, `blocked` (403/406/429 — bot-blocked, *not* proof of removal), `unconfirmed` (200 but no job extracted — SPA shell or changed layout), and `error`.

Known limits: no JS rendering (pure-SPA boards return shells unless an ATS/JSON-LD fallback saves them), blocked pages return empty without retrying, and selectors drift as sites redesign.

## What's deliberately not here

**No LinkedIn module.** The original project had a LinkedIn guest-API scraper. It was removed for this release: scraping LinkedIn violates their Terms of Service and risks takedowns. LinkedIn source URLs are rejected with a clear error instead of silently misbehaving. The ATS + career-page scrapers are the defensible core.

## The dashboard (`/dashboard`)

The scraper is the sensing layer. The dashboard is the decision layer: a ranked queue of roles scored 0–100 against a fixed-budget rubric (AI substance is the defining dimension), per-role dossiers, a networking panel with outreach targets, and a daily ingest that keeps it fresh. Read [`/dashboard/RECREATE.md`](dashboard/RECREATE.md) for the architecture and [`/dashboard/scoring.md`](dashboard/scoring.md) for the rubric.

## License

MIT — see [LICENSE](LICENSE). Use it, tailor it, snipe better jobs.
