#!/usr/bin/env python3
"""Standalone runner for the ported Job-Discovery (Crucible) scraper.

No Flask, no SQLite, no API keys required (keyless = JSON-LD + CSS +
ATS JSON APIs + Workday API; LLM tier auto-disabled without keys).

Usage:
  # Discovery: scan career boards / ATS boards for keyword matches
  python run.py --sources sources.json --keywords "AI Product,Product Manager" --out out.json

  # Single-URL verification: is this exact posting still live?
  python run.py --check-url "https://boards.greenhouse.io/..." --company "Acme"

  # With a seen-file so repeat runs only report new jobs
  python run.py --sources sources.json --keywords "AI Product" --seen seen.json --out out.json

Sources file: JSON list of {"company_name": "...", "url": "..."}.
Output: JSON with jobs, filtered-out jobs, errors, and per-source stats.
Each job carries _extraction_method (json-ld / css / greenhouse / lever /
ashby / workday-api / phenom / llm...) so you can see which
tier produced it.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# VM egress-proxy quirk: httpx 0.28 chokes on bracketed IPv6 entries in
# NO_PROXY (e.g. "[::1]") with `InvalidURL: Invalid port: ':1]'` at Client()
# construction time. Strip bracketed entries; keep the proxy itself.
for _k in ("NO_PROXY", "no_proxy"):
    _v = os.environ.get(_k, "")
    if "[" in _v:
        _kept = [p for p in _v.split(",") if "[" not in p]
        os.environ[_k] = ",".join(_kept)

sys.path.insert(0, str(Path(__file__).parent))

from scraper.ats_api import GreenhouseScraper, LeverScraper, AshbyScraper
from scraper.career_page import CareerPageScraper
from scraper.dedup import DeduplicationManager
from scraper.logger import ScrapeLogger
from stub_db import StubDB

import httpx
import config as _config  # noqa: F401  (ensures config is importable)


def detect_scraper_type(url):
    url_lower = url.lower()
    if "boards.greenhouse.io" in url_lower or "boards-api.greenhouse.io" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower:
        return "lever"
    if "ashbyhq.com" in url_lower:
        return "ashby"
    if "linkedin.com/jobs" in url_lower:
        return "linkedin"
    return "generic"  # CareerPageScraper auto-detects Workday/Phenom/ATS-probe


def _matches_location(job, include, exclude):
    loc = (job.get("location") or "").lower()
    if include and any(kw.lower() in loc for kw in include):
        return True
    if exclude and any(kw.lower() in loc for kw in exclude):
        return False
    if include:
        return False
    return True


def _clean_job(job):
    # Keep extraction metadata; drop nothing the caller might need.
    return job


def run_sources(sources, keywords, exclude_keywords, location_include,
                location_exclude, seen, log):
    db = StubDB()
    career_scraper = CareerPageScraper(db, log)
    greenhouse_scraper = GreenhouseScraper(log)
    lever_scraper = LeverScraper(log)
    ashby_scraper = AshbyScraper(log)
    scrapers = [career_scraper, greenhouse_scraper,
                lever_scraper, ashby_scraper]

    jobs, filtered, errors, per_source = [], [], [], []
    seen_in_run = set()
    try:
        for source in sources:
            url = source["url"]
            company = source.get("company_name", "Unknown")
            stype = detect_scraper_type(url)
            log.step(f"Source: {company} [{stype}] {url[:100]}")
            try:
                if stype == "linkedin":
                    # LinkedIn scraping is deliberately not shipped in this
                    # build (see README). Fail loudly instead of silently
                    # running a generic scrape against it.
                    errors.append(f"{company}: LinkedIn sources are not "
                                  f"supported in this build.")
                    per_source.append({"company": company, "url": url,
                                       "type": stype, "found": 0, "new": 0,
                                       "error": "LinkedIn sources not supported"})
                    continue
                elif stype == "greenhouse":
                    discovered, filt = greenhouse_scraper.scrape(
                        source, keywords, exclude_keywords)
                elif stype == "lever":
                    discovered, filt = lever_scraper.scrape(
                        source, keywords, exclude_keywords)
                elif stype == "ashby":
                    discovered, filt = ashby_scraper.scrape(
                        source, keywords, exclude_keywords)
                else:
                    discovered, filt = career_scraper.scrape(
                        source, keywords, exclude_keywords)
            except Exception as e:  # noqa: BLE001 - report per-source, continue
                errors.append(f"{company}: {e}")
                per_source.append({"company": company, "url": url,
                                   "type": stype, "found": 0, "new": 0,
                                   "error": str(e)})
                continue

            # Location filter (same include-beats-exclude rule as Crucible)
            if location_include or location_exclude:
                kept = []
                for job in discovered:
                    if _matches_location(job, location_include, location_exclude):
                        kept.append(job)
                    else:
                        filt.append(job)
                discovered = kept

            new_count = 0
            for job in discovered:
                norm = DeduplicationManager.normalize_url(job.get("url", ""))
                if norm in seen or norm in seen_in_run:
                    continue
                seen_in_run.add(norm)
                seen.add(norm)
                job = _clean_job(job)
                job.setdefault("company", company)
                jobs.append(job)
                new_count += 1
            for job in filt:
                job.setdefault("company", company)
                filtered.append(job)
            per_source.append({"company": company, "url": url, "type": stype,
                               "found": len(discovered), "new": new_count,
                               "filtered": len(filt)})
            log.info(f"{company}: {len(discovered)} matched, {new_count} new")
    finally:
        for s in scrapers:
            try:
                s.close()
            except Exception:
                pass
    return jobs, filtered, errors, per_source


def check_single_url(url, company, log):
    """Verify one posting URL: live / gone / blocked / error.

    Distinguishes what the scraper alone lumps together: a real 404
    (likely removed) vs a 403/406/429 block vs a 200 page with no job
    extracted (SPA shell, changed layout, or not a job page).
    """
    db = StubDB()
    scraper = CareerPageScraper(db, log)
    status = {"url": url, "company": company, "http_status": None,
              "verdict": "unknown", "job": None, "note": ""}
    try:
        # Raw HTTP status first, independent of extraction.
        try:
            with httpx.Client(follow_redirects=True, timeout=15) as client:
                resp = client.get(url, headers={"User-Agent": _config.USER_AGENT})
                status["http_status"] = resp.status_code
                status["final_url"] = str(resp.url)
                if resp.status_code == 404:
                    status["verdict"] = "gone_404"
                    status["note"] = "Server returned 404."
                    return status
                if resp.status_code in (403, 406, 429):
                    status["verdict"] = "blocked"
                    status["note"] = f"Server returned {resp.status_code}; likely bot-blocked, not proof of removal."
                    return status
                if resp.status_code != 200:
                    status["verdict"] = "error"
                    status["note"] = f"Unexpected HTTP {resp.status_code}."
                    return status
        except Exception as e:  # noqa: BLE001
            status["verdict"] = "error"
            status["note"] = f"HTTP fetch failed: {e}"
            return status

        # 200: try extraction. Greenhouse/Lever/Ashby detail URLs need a
        # membership check, NOT the generic CareerPageScraper path: those
        # boards return HTTP 200 with a generic page for dead job IDs
        # (soft 404), and the scraper's ATS-probe fallback used to return
        # a different board's jobs as if they were this job (verified
        # Oct 13: dead Roku ID 0000000 reported "live" as Greenhouse
        # Software's "Commercial Counsel"). So: for ATS detail URLs,
        # fetch the board API and check this exact job is still listed.
        from urllib.parse import urlparse as _urlparse
        _parsed = _urlparse(url)
        _host = _parsed.netloc.lower()
        _parts = [p for p in _parsed.path.strip("/").split("/") if p]
        _ats_detail = None  # (kind, board, job_id)
        if "boards.greenhouse.io" in _host and len(_parts) >= 3 and _parts[1] == "jobs":
            _ats_detail = ("greenhouse", _parts[0], _parts[2].split("?")[0])
        elif "jobs.lever.co" in _host and len(_parts) >= 2:
            _ats_detail = ("lever", _parts[0], _parts[1].split("?")[0])
        elif "jobs.ashbyhq.com" in _host and len(_parts) >= 2:
            _ats_detail = ("ashby", _parts[0], _parts[1].split("?")[0])
        if _ats_detail:
            _kind, _board, _jid = _ats_detail
            _found = _check_ats_membership(_kind, _board, _jid, log)
            if _found is None:
                status["verdict"] = "error"
                status["note"] = f"Board API for {_kind}/{_board} unreachable; cannot verify."
            elif _found:
                status["verdict"] = "live"
                status["job"] = _found
                status["note"] = f"Job ID {_jid} still listed on {_kind}/{_board} board API."
            else:
                status["verdict"] = "gone"
                status["note"] = f"Job ID {_jid} no longer listed on {_kind}/{_board} board API (board returns 200 for dead IDs, so HTTP status alone cannot tell)."
            return status

        # Generic / Workday / JSON-LD detail pages.
        source = {"company_name": company, "url": url}
        discovered, _filt = scraper.scrape(source, keywords=[], exclude_keywords=[])
        # Empty keywords = match-all in the ATS helpers; CareerPageScraper
        # with keywords=[] treats every title as a match (see _matches_keywords).
        if discovered:
            # Guard: the returned job must belong to the requested URL.
            # A fallback that dumps another board's jobs must not count.
            _got_url = (discovered[0].get("url") or "")
            _req_norm = DeduplicationManager.normalize_url(url)
            _got_norm = DeduplicationManager.normalize_url(_got_url)
            if _got_norm == _req_norm or _req_norm in _got_norm or _got_norm in _req_norm:
                status["verdict"] = "live"
                status["job"] = discovered[0]
                status["note"] = f"Extracted via {discovered[0].get('_extraction_method')}."
            else:
                status["verdict"] = "unconfirmed"
                status["note"] = (
                    f"Extractor returned a different job ({_got_url[:100]}) than requested; "
                    "likely a fallback board dump, not this posting. Needs browser check.")
        else:
            status["verdict"] = "unconfirmed"
            status["note"] = "HTTP 200 but no job extracted (SPA shell, changed layout, or not a job page). Needs browser check."
        return status
    finally:
        try:
            scraper.close()
        except Exception:
            pass


def _check_ats_membership(kind, board, job_id, log):
    """Return the matching job dict if job_id is still on the board, else False; None on API failure."""
    try:
        with httpx.Client(follow_redirects=True, timeout=15,
                          headers={"User-Agent": _config.USER_AGENT}) as client:
            if kind == "greenhouse":
                r = client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
                if r.status_code != 200:
                    return None
                for job in r.json().get("jobs", []):
                    abs_url = job.get("absolute_url", "") or ""
                    if job_id in abs_url or str(job.get("id", "")) == job_id or job.get("internal_job_id") == job_id:
                        return {"url": abs_url, "title": job.get("title"),
                                "company": "", "location": (job.get("location") or {}).get("name", "")
                                if isinstance(job.get("location"), dict) else "",
                                "_extraction_method": "ats-api-membership"}
                return False
            if kind == "lever":
                r = client.get(f"https://api.lever.co/v0/postings/{board}?mode=json")
                if r.status_code != 200:
                    return None
                for job in r.json():
                    if job_id in (job.get("id", "") or "") or job_id in (job.get("hostedUrl", "") or ""):
                        return {"url": job.get("hostedUrl"), "title": job.get("text"),
                                "company": "", "location": "",
                                "_extraction_method": "ats-api-membership"}
                return False
            if kind == "ashby":
                r = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true")
                if r.status_code != 200:
                    return None
                for job in r.json().get("jobs", []):
                    if job_id in (job.get("id", "") or "") or job_id in (job.get("jobUrl", "") or ""):
                        return {"url": job.get("jobUrl"), "title": job.get("title"),
                                "company": "", "location": "",
                                "_extraction_method": "ats-api-membership"}
                return False
    except Exception as e:  # noqa: BLE001
        log.error(f"ATS membership check failed: {e}")
        return None
    return None


def main():
    ap = argparse.ArgumentParser(description="Ported Job-Discovery scraper (keyless, no browser)")
    ap.add_argument("--sources", help="JSON file: list of {company_name, url}")
    ap.add_argument("--keywords", default="", help="Comma-separated title keywords (OR). Empty = match all.")
    ap.add_argument("--exclude", default="", help="Comma-separated title exclude keywords.")
    ap.add_argument("--location-include", default="", help="Comma-separated location substrings (include wins).")
    ap.add_argument("--location-exclude", default="", help="Comma-separated location substrings.")
    ap.add_argument("--check-url", help="Single posting URL to verify instead of a sources run.")
    ap.add_argument("--company", default="Unknown", help="Company name for --check-url.")
    ap.add_argument("--seen", help="JSON file of seen normalized URLs (updated in place).")
    ap.add_argument("--out", help="Write result JSON to this file (default: stdout).")
    ap.add_argument("--max-jobs", type=int, default=25, help="Per-source cap (default 25, Crucible default).")
    args = ap.parse_args()

    # Apply per-source cap: vendored modules bind MAX_JOBS_PER_SOURCE via
    # `from config import ...` at import time, so set it on each module.
    import scraper.ats_api as _ats
    import scraper.career_page as _cp
    for _mod in (_ats, _cp):
        _mod.MAX_JOBS_PER_SOURCE = args.max_jobs
    _config.MAX_JOBS_PER_SOURCE = args.max_jobs

    log = ScrapeLogger(StubDB(), run_id=1)
    started = time.time()

    seen = set()
    seen_path = Path(args.seen) if args.seen else None
    if seen_path and seen_path.exists():
        try:
            seen = set(json.loads(seen_path.read_text()))
        except Exception:
            seen = set()

    if args.check_url:
        result = {"mode": "check-url", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "result": check_single_url(args.check_url, args.company, log)}
    else:
        if not args.sources:
            ap.error("--sources is required unless --check-url is given.")
        sources = json.loads(Path(args.sources).read_text())
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
        exclude = [k.strip() for k in args.exclude.split(",") if k.strip()]
        loc_inc = [k.strip() for k in args.location_include.split(",") if k.strip()]
        loc_exc = [k.strip() for k in args.location_exclude.split(",") if k.strip()]
        jobs, filtered, errors, per_source = run_sources(
            sources, keywords, exclude, loc_inc, loc_exc, seen, log)
        result = {
            "mode": "discovery",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "keywords": keywords, "exclude": exclude,
            "stats": {"sources": len(sources), "jobs_new": len(jobs),
                      "filtered": len(filtered), "errors": len(errors),
                      "seconds": round(time.time() - started, 1)},
            "per_source": per_source,
            "jobs": jobs,
            "filtered": filtered,
            "errors": errors,
        }

    if seen_path:
        seen_path.write_text(json.dumps(sorted(seen), indent=2))

    text = json.dumps(result, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text)
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
