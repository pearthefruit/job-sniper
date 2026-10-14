"""
ATS JSON API scrapers for Greenhouse, Lever, and Ashby.
Each scraper hits the platform's public unauthenticated JSON API
and returns a list of standard job dicts.
"""

import re
import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REQUEST_TIMEOUT_SECONDS, USER_AGENT, MAX_JOBS_PER_SOURCE


# =================== Shared Helpers ===================

def _matches_keywords(title, keywords):
    if not keywords:
        return True
    title_lower = (title or '').lower()
    return any(kw.lower() in title_lower for kw in keywords)


def _matches_exclude(title, exclude_keywords):
    if not exclude_keywords:
        return False
    title_lower = (title or '').lower()
    return any(kw.lower() in title_lower for kw in exclude_keywords)


SALARY_PATTERNS = [
    r'\$[\d,]+(?:\.\d{2})?\s+to\s+\$[\d,]+(?:\.\d{2})?',
    r'\$[\d,]+(?:\.\d{2})?\s*[-\u2013]\s*\$[\d,]+(?:\.\d{2})?(?:\s*/\s*(?:yr|year|annually|hr|hour))?',
    r'\$[\d,]+(?:\.\d{2})?\s*/\s*(?:yr|year|annually|hr|hour)',
    r'(?:base\s+)?(?:salary|pay|compensation)\s+(?:range|scale)?[:\s]+\$[\d,]+[^\n]{0,60}',
]


def _extract_salary_from_text(text):
    if not text:
        return None
    for pattern in SALARY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result = match.group(0).strip()
            result = re.split(r'(?<!\d)[.;]', result)[0].strip()
            if len(result) > 120:
                result = result[:120] + '...'
            return result
    return None


# =================== Greenhouse ===================

class GreenhouseScraper:
    """Scrapes Greenhouse job boards via their public JSON API."""

    API_BASE = "https://boards-api.greenhouse.io/v1/boards"

    def __init__(self, log=None):
        self.log = log
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def _info(self, msg):
        if self.log:
            self.log.info(msg)

    def _warn(self, msg):
        if self.log:
            self.log.warn(msg)

    def _extract_token(self, url):
        parsed = urlparse(url)
        parts = parsed.path.strip('/').split('/')
        # boards.greenhouse.io/{token} or boards.greenhouse.io/{token}/jobs/...
        # boards-api.greenhouse.io/v1/boards/{token}/...
        for i, part in enumerate(parts):
            if part == 'boards' and i + 1 < len(parts):
                return parts[i + 1]
        # Simple case: boards.greenhouse.io/{token}
        if parts and parts[0] not in ('v1', 'boards', ''):
            return parts[0]
        return None

    def scrape(self, source, keywords, exclude_keywords=None):
        exclude_keywords = exclude_keywords or []
        token = self._extract_token(source['url'])
        if not token:
            self._warn(f"Could not extract Greenhouse board token from {source['url']}")
            return [], []

        api_url = f"{self.API_BASE}/{token}/jobs?content=true"
        self._info(f"Greenhouse API: {api_url}")

        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                self._warn(f"Greenhouse API returned {response.status_code}")
                return [], []
            data = response.json()
        except Exception as e:
            self._warn(f"Greenhouse API failed: {e}")
            return [], []

        jobs_list = data.get('jobs', [])
        self._info(f"Greenhouse returned {len(jobs_list)} job(s)")

        discovered = []
        filtered_out = []
        for job in jobs_list:
            title = job.get('title', '')
            if _matches_exclude(title, exclude_keywords):
                continue

            location = ''
            loc_obj = job.get('location')
            if loc_obj and isinstance(loc_obj, dict):
                location = loc_obj.get('name', '')

            if not _matches_keywords(title, keywords):
                filtered_out.append({
                    'url': job.get('absolute_url', ''),
                    'title': title,
                    'company': source.get('company_name', ''),
                    'location': location,
                    'salary': None,
                    'description': '',
                    '_extraction_method': 'ats-api',
                    '_source_scraper': 'greenhouse',
                    '_got_title': bool(title),
                    '_got_company': True,
                    '_got_description': False,
                })
                continue

            # Strip HTML from content to get plain text description
            content_html = job.get('content', '')
            description = ''
            if content_html:
                soup = BeautifulSoup(content_html, 'html.parser')
                description = soup.get_text(separator='\n\n', strip=True)

            salary = _extract_salary_from_text(description)

            discovered.append({
                'url': job.get('absolute_url', ''),
                'title': title,
                'company': source.get('company_name', ''),
                'location': location,
                'salary': salary,
                'description': description,
                '_extraction_method': 'ats-api',
                '_source_scraper': 'greenhouse',
                '_got_title': bool(title),
                '_got_company': True,
                '_got_description': bool(description),
            })

            if len(discovered) >= MAX_JOBS_PER_SOURCE:
                break

        return discovered, filtered_out

    def close(self):
        self.http.close()


# =================== Lever ===================

class LeverScraper:
    """Scrapes Lever job boards via their public JSON API."""

    def __init__(self, log=None):
        self.log = log
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def _info(self, msg):
        if self.log:
            self.log.info(msg)

    def _warn(self, msg):
        if self.log:
            self.log.warn(msg)

    def _extract_slug(self, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]

        # jobs.lever.co/company or jobs.eu.lever.co/company
        if host in ('jobs.lever.co', 'jobs.eu.lever.co'):
            return path_parts[0] if path_parts else None

        # company.lever.co
        if host.endswith('.lever.co'):
            subdomain = host.split('.')[0]
            if subdomain not in ('jobs', 'api', 'www'):
                return subdomain

        return path_parts[0] if path_parts else None

    def _is_eu(self, url):
        return '.eu.lever.co' in url.lower()

    def scrape(self, source, keywords, exclude_keywords=None):
        exclude_keywords = exclude_keywords or []
        slug = self._extract_slug(source['url'])
        if not slug:
            self._warn(f"Could not extract Lever slug from {source['url']}")
            return [], []

        api_host = 'api.eu.lever.co' if self._is_eu(source['url']) else 'api.lever.co'
        api_url = f"https://{api_host}/v0/postings/{slug}?mode=json"
        self._info(f"Lever API: {api_url}")

        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                self._warn(f"Lever API returned {response.status_code}")
                return [], []
            postings = response.json()
        except Exception as e:
            self._warn(f"Lever API failed: {e}")
            return [], []

        if not isinstance(postings, list):
            self._warn("Lever API returned unexpected format")
            return [], []

        self._info(f"Lever returned {len(postings)} posting(s)")

        discovered = []
        filtered_out = []
        for posting in postings:
            title = posting.get('text', '')
            if _matches_exclude(title, exclude_keywords):
                continue

            categories = posting.get('categories', {}) or {}
            location = categories.get('location', '')

            if not _matches_keywords(title, keywords):
                filtered_out.append({
                    'url': posting.get('hostedUrl', '') or posting.get('applyUrl', ''),
                    'title': title,
                    'company': source.get('company_name', ''),
                    'location': location,
                    'salary': None,
                    'description': '',
                    '_extraction_method': 'ats-api',
                    '_source_scraper': 'lever',
                    '_got_title': bool(title),
                    '_got_company': True,
                    '_got_description': False,
                })
                continue

            # Build salary string from salaryRange object
            salary = None
            salary_range = posting.get('salaryRange')
            if salary_range and isinstance(salary_range, dict):
                sr_min = salary_range.get('min')
                sr_max = salary_range.get('max')
                currency = salary_range.get('currency', 'USD')
                interval = salary_range.get('interval', 'per-year')
                if sr_min and sr_max:
                    salary = f"${sr_min:,.0f} - ${sr_max:,.0f}/{interval}"
                elif sr_min:
                    salary = f"${sr_min:,.0f}/{interval}"

            description = posting.get('descriptionPlain', '') or ''

            if not salary:
                salary = _extract_salary_from_text(description)

            discovered.append({
                'url': posting.get('hostedUrl', '') or posting.get('applyUrl', ''),
                'title': title,
                'company': source.get('company_name', ''),
                'location': location,
                'salary': salary,
                'description': description,
                '_extraction_method': 'ats-api',
                '_source_scraper': 'lever',
                '_got_title': bool(title),
                '_got_company': True,
                '_got_description': bool(description),
            })

            if len(discovered) >= MAX_JOBS_PER_SOURCE:
                break

        return discovered, filtered_out

    def close(self):
        self.http.close()


# =================== Ashby ===================

class AshbyScraper:
    """Scrapes Ashby job boards via their public JSON API."""

    API_BASE = "https://api.ashbyhq.com/posting-api/job-board"

    def __init__(self, log=None):
        self.log = log
        self.http = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def _info(self, msg):
        if self.log:
            self.log.info(msg)

    def _warn(self, msg):
        if self.log:
            self.log.warn(msg)

    def _extract_board(self, url):
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        # jobs.ashbyhq.com/{board} or api.ashbyhq.com/posting-api/job-board/{board}
        if 'job-board' in path_parts:
            idx = path_parts.index('job-board')
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
        return path_parts[0] if path_parts else None

    def scrape(self, source, keywords, exclude_keywords=None):
        exclude_keywords = exclude_keywords or []
        board = self._extract_board(source['url'])
        if not board:
            self._warn(f"Could not extract Ashby board from {source['url']}")
            return [], []

        api_url = f"{self.API_BASE}/{board}?includeCompensation=true"
        self._info(f"Ashby API: {api_url}")

        try:
            response = self.http.get(api_url)
            if response.status_code != 200:
                self._warn(f"Ashby API returned {response.status_code}")
                return [], []
            data = response.json()
        except Exception as e:
            self._warn(f"Ashby API failed: {e}")
            return [], []

        jobs_list = data.get('jobs', [])
        self._info(f"Ashby returned {len(jobs_list)} job(s)")

        discovered = []
        filtered_out = []
        for job in jobs_list:
            title = job.get('title', '')
            if _matches_exclude(title, exclude_keywords):
                continue

            location = job.get('location', '')

            if not _matches_keywords(title, keywords):
                filtered_out.append({
                    'url': job.get('jobUrl', ''),
                    'title': title,
                    'company': source.get('company_name', ''),
                    'location': location,
                    'salary': None,
                    'description': '',
                    '_extraction_method': 'ats-api',
                    '_source_scraper': 'ashby',
                    '_got_title': bool(title),
                    '_got_company': True,
                    '_got_description': False,
                })
                continue

            description = job.get('descriptionPlain', '') or ''

            # Build salary from compensation object
            salary = None
            comp = job.get('compensation')
            if comp and isinstance(comp, dict):
                comp_str = comp.get('compensationTierSummary', '')
                if comp_str:
                    salary = comp_str

            if not salary:
                salary = _extract_salary_from_text(description)

            discovered.append({
                'url': job.get('jobUrl', ''),
                'title': title,
                'company': source.get('company_name', ''),
                'location': location,
                'salary': salary,
                'description': description,
                '_extraction_method': 'ats-api',
                '_source_scraper': 'ashby',
                '_got_title': bool(title),
                '_got_company': True,
                '_got_description': bool(description),
            })

            if len(discovered) >= MAX_JOBS_PER_SOURCE:
                break

        return discovered, filtered_out

    def close(self):
        self.http.close()
