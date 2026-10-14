"""Minimal stand-in for CrucibleDB, covering only what scraper/ needs.

Real CrucibleDB (database/db.py, ~96KB) backs the Flask UI: jobs,
filters, scrape runs, selector learning, API-usage accounting. The
standalone port does not need any of that. This stub satisfies the
three call sites:

- SelectorRegistry(db): db.get_selectors(domain, selector_type) -> []
  (no learned selectors; hardcoded DEFAULTS + generic fallbacks only)
- CareerPageScraper: db.log_api_usage(...) -> no-op
- ScrapeLogger(db, run_id): db.add_log(...) -> no-op (logger already
  prints to stderr; its DB write is wrapped in try/except upstream)

Dedup is handled by the runner (run.py) via
DeduplicationManager.normalize_url + a JSON seen-file, not by this stub.
"""


class StubDB:
    def get_selectors(self, domain, selector_type):
        return []

    def record_selector_success(self, *args, **kwargs):
        return None

    def record_selector_failure(self, *args, **kwargs):
        return None

    def upsert_selector(self, *args, **kwargs):
        return None

    def log_api_usage(self, *args, **kwargs):
        return None

    def add_log(self, run_id, message, level):
        return None

    # Compatibility: original DedupManager calls these on a real DB.
    # The runner never calls DedupManager.is_duplicate; it dedups itself.
    def get_job_by_normalized_url(self, normalized_url):
        return None
