"""
Manages CSS selectors for different ATS platforms.
Combines hardcoded defaults with learned selectors from the DB.
"""


class SelectorRegistry:
    # Default selectors per ATS platform
    DEFAULTS = {
        'boards.greenhouse.io': {
            'job_link': ['a.job-post-link', 'a[data-mapped]', 'div.opening a'],
            'job_title': ['h1.app-title', 'h1', '.job-title'],
            'job_location': ['.location', 'div.location'],
            'job_description': ['#content', '.job-post-content', '#app_body'],
        },
        'jobs.lever.co': {
            'job_link': ['.posting-title', 'a.posting-btn-submit', 'div.posting a'],
            'job_title': ['h2[data-qa="posting-name"]', 'h2', '.posting-headline h2'],
            'job_location': ['.posting-categories .sort-by-time', '.location', '.workplaceTypes'],
            'job_description': ['.posting-page .content', '.posting-description', '.section-wrapper'],
        },
        'icims.com': {
            'job_link': ['a.iCIMS_Anchor', '.iCIMS_JobsTable a', 'a[href*="jobs/"]'],
            'job_title': ['h1.iCIMS_Header', '.iCIMS_Header h1', 'h1'],
            'job_location': ['.iCIMS_JobHeaderField:nth-child(2)', '.header-location'],
            'job_description': ['.iCIMS_InfoMsg_Job', '.iCIMS_Expandable_Text', '#job-description'],
        },
        'myworkdayjobs.com': {
            'job_link': ['a[data-automation-id="jobTitle"]', 'a.css-19uc56f', 'li.css-1q2dra3 a'],
            'job_title': ['h2[data-automation-id="jobPostingHeader"]', 'h2', '.css-1q2dra3 h2'],
            'job_location': ['[data-automation-id="locations"]', '.css-cygeeu dd'],
            'job_description': ['[data-automation-id="jobPostingDescription"]', '.css-b7k2vl'],
        },
        'myworkdaysite.com': {
            'job_link': ['a[data-automation-id="jobTitle"]', 'a.css-19uc56f', 'li a'],
            'job_title': ['h2[data-automation-id="jobPostingHeader"]', 'h2'],
            'job_location': ['[data-automation-id="locations"]'],
            'job_description': ['[data-automation-id="jobPostingDescription"]'],
        },
        'jobs.smartrecruiters.com': {
            'job_link': ['a.link--block', '.opening-job a', 'h4 a'],
            'job_title': ['h1.job-title', 'h2.job-title', 'h1'],
            'job_location': ['.job-location', '.location'],
            'job_description': ['.job-description', '.job-sections', '#st-jobDescription'],
        },
    }

    def __init__(self, db):
        self.db = db

    def get_link_selectors(self, domain):
        return self._get_merged_selectors(domain, 'job_link')

    def get_field_selectors(self, domain, field_type):
        return self._get_merged_selectors(domain, field_type)

    def _get_merged_selectors(self, domain, selector_type):
        """Merge DB-learned selectors with hardcoded defaults, ordered by success rate."""
        # Get learned selectors from DB
        db_selectors = self.db.get_selectors(domain, selector_type)

        # Get defaults for this domain (match partial domain)
        defaults = []
        for key, selectors in self.DEFAULTS.items():
            if key in domain:
                defaults = selectors.get(selector_type, [])
                break

        seen = set()
        merged = []

        # DB selectors first (sorted by success_count - failure_count DESC)
        for s in db_selectors:
            if s['selector'] not in seen:
                merged.append(s)
                seen.add(s['selector'])

        # Add defaults not already present
        for sel in defaults:
            if sel not in seen:
                merged.append({'selector': sel, 'success_count': 0, 'failure_count': 0})
                seen.add(sel)

        # If no selectors at all, add generic fallbacks
        if not merged:
            for sel in self._generic_selectors(selector_type):
                if sel not in seen:
                    merged.append({'selector': sel, 'success_count': 0, 'failure_count': 0})
                    seen.add(sel)

        return merged

    def _generic_selectors(self, selector_type):
        """Universal fallback selectors that work on many sites."""
        generics = {
            'job_link': ['a[href*="job"]', 'a[href*="position"]', 'a[href*="career"]', 'a[href*="opening"]'],
            'job_title': ['h1', 'h2', '.job-title', '[class*="title"]'],
            'job_location': ['.location', '[class*="location"]', '[class*="Location"]'],
            'job_description': ['.description', '[class*="description"]', 'article', 'main'],
        }
        return generics.get(selector_type, [])
