"""
Company and job title extraction heuristics.
Ported from JobAgent/job_manager.py with adaptations.
"""

import re


def extract_company_from_url(url):
    """Extract company name from URL using ATS-specific heuristics."""
    clean_url = url.split('//')[-1]
    clean_url = clean_url.split('?')[0]
    parts = clean_url.split('/')

    company = None

    if "greenhouse.io" in clean_url:
        for i, part in enumerate(parts):
            if "greenhouse.io" in part and i + 1 < len(parts):
                company = parts[i + 1]
                break
    elif "lever.co" in clean_url:
        for i, part in enumerate(parts):
            if "lever.co" in part and i + 1 < len(parts):
                company = parts[i + 1]
                break
    elif "linkedin.com" in clean_url:
        return None  # Company comes from job detail, not URL
    elif "myworkdayjobs.com" in clean_url or "myworkdaysite.com" in clean_url:
        # e.g., company.wd5.myworkdaysite.com
        domain = parts[0]
        subdomain = domain.split('.')[0]
        if subdomain not in ('www', 'jobs', 'careers'):
            company = subdomain.capitalize()

    if not company:
        domain_parts = clean_url.split('/')[0].split('.')
        if len(domain_parts) > 1:
            # Get the meaningful domain part
            for part in domain_parts:
                if part not in ('www', 'jobs', 'careers', 'com', 'org', 'io', 'co', 'net'):
                    company = part.capitalize()
                    break

    return company


def extract_company_from_content(content):
    """Extract company name from job description text using regex patterns."""
    if not content:
        return None

    content = re.sub(r'\s+', ' ', content[:3000])

    # Pattern: "About [Company]"
    about_match = re.match(r'^About\s+([A-Z][a-zA-Z0-9&.\s]{2,40}?)(?:\s|$)', content, re.IGNORECASE)
    if about_match:
        company = about_match.group(1).strip()
        if 2 < len(company) < 50:
            return company

    # Pattern: "[Company] is/are/has..."
    start_match = re.match(r'^([A-Z][a-zA-Z0-9&.\s]{2,40}?)(?:\'s|is|are|has|invites|seeks)\s', content)
    if start_match:
        company = start_match.group(1).strip()
        company = re.sub(r'\s+(is|are|has|have|and|the)$', '', company, flags=re.IGNORECASE)
        if 2 < len(company) < 50:
            return company

    # Pattern: "at [Company]", "for [Company]"
    patterns = [
        r'(?:at|for|with|join)\s+([A-Z][a-zA-Z\s&.]{2,40}?)(?:\s+(?:in|as|to|is|and|,))',
        r'Company:\s*([A-Z][a-zA-Z\s&.]+)',
        r'Employer:\s*([A-Z][a-zA-Z\s&.]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, content[:2000])
        if match:
            company = match.group(1).strip()
            company = re.sub(r'\s+(is|are|has|have|and|the|our|your)$', '', company, flags=re.IGNORECASE)
            if 2 < len(company) < 50:
                return company

    return None


def extract_job_title_from_content(content):
    """Extract job title from content for use in filenames."""
    if not content:
        return None

    patterns = [
        r'<title>([^|<]+?)(?:\s*[|<-])',
        r'(?:Position|Role|Job Title):\s*([A-Za-z\s,&-]+)',
        r'^([A-Z][a-zA-Z\s,&-]{5,60})$',
    ]

    for pattern in patterns:
        match = re.search(pattern, content[:500], re.MULTILINE)
        if match:
            title = match.group(1).strip()
            title = re.sub(r'\s+', ' ', title)
            if 5 < len(title) < 80:
                return title

    return None
