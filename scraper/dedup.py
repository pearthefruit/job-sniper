class DeduplicationManager:
    """Prevents saving duplicate jobs by checking normalized URLs against the DB."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def normalize_url(url):
        """Normalize URL by removing query parameters, fragments, and trailing slashes."""
        return url.split('?')[0].split('#')[0].rstrip('/')

    def is_duplicate(self, url):
        # PORT CHANGE: the runner dedups via normalize_url + a JSON seen-file
        # and never calls this. Keep it safe for a StubDB (no get_connection
        # / _uid / SQL): fall back to False instead of crashing.
        try:
            normalized = self.normalize_url(url)
            existing = self.db.get_job_by_normalized_url(normalized)
            if existing:
                return True
        except Exception:
            return False

        return False
