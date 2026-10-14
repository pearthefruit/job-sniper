"""
ScrapeLogger — writes log entries to both the DB (for the frontend) and console.
Passed into scrapers so they can report progress to the UI.
"""

import sys


class ScrapeLogger:
    def __init__(self, db, run_id):
        self.db = db
        self.run_id = run_id

    def info(self, message):
        self._log("info", message)

    def success(self, message):
        self._log("success", message)

    def warn(self, message):
        self._log("warn", message)

    def error(self, message):
        self._log("error", message)

    def step(self, message):
        """A notable step in the process (e.g., starting a new source)."""
        self._log("step", message)

    def _log(self, level, message):
        print(f"[{level.upper()}] {message}", file=sys.stderr, flush=True)
        try:
            self.db.add_log(self.run_id, message, level)
        except Exception:
            pass  # Don't let logging failures break the scraper
