"""
LLM-powered job data extraction with multi-model fallback.
Tier 2 extractor: runs after JSON-LD fails, before CSS selectors.

Fallback chain:
  1. Gemini (key × model rotation, free tier rate limits)
  2. Groq (fast inference, free tier)
  3. Mistral (free tier direct API)
  4. Cerebras (free tier fast inference)
  5. OpenRouter (free-tier community models)
  6. Claude (last resort, paid)
Skip rate-limited combos for a cooldown period.
"""

import json
import re
import time
import httpx
from urllib.parse import urljoin
from bs4 import BeautifulSoup

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEMINI_API_KEY

# Defaults (overridden by config if available)
try:
    from config import LLM_EXTRACTION_ENABLED, LLM_MODEL, LLM_MAX_TEXT_CHARS, LLM_TIMEOUT_SECONDS
except ImportError:
    LLM_EXTRACTION_ENABLED = True
    LLM_MODEL = "gemini-2.0-flash"
    LLM_MAX_TEXT_CHARS = 16000
    LLM_TIMEOUT_SECONDS = 30

try:
    from config import LLM_FALLBACK_MODELS, LLM_RATE_LIMIT_COOLDOWN_SECONDS
except ImportError:
    LLM_FALLBACK_MODELS = [LLM_MODEL]
    LLM_RATE_LIMIT_COOLDOWN_SECONDS = 60

try:
    from config import LLM_API_KEYS
except ImportError:
    LLM_API_KEYS = [GEMINI_API_KEY] if GEMINI_API_KEY else []

try:
    from config import CLAUDE_API_KEY, CLAUDE_MODEL
except ImportError:
    CLAUDE_API_KEY = ""
    CLAUDE_MODEL = "claude-sonnet-4-20250514"

# OpenAI-compatible providers for scraper fallback
try:
    from config import (
        GROQ_API_KEY, GROQ_MODELS,
        MISTRAL_API_KEY, MISTRAL_MODELS,
        CEREBRAS_API_KEY, CEREBRAS_MODELS,
        OPENROUTER_API_KEY, OPENROUTER_MODELS,
    )
except ImportError:
    GROQ_API_KEY = ""
    GROQ_MODELS = []
    MISTRAL_API_KEY = ""
    MISTRAL_MODELS = []
    CEREBRAS_API_KEY = ""
    CEREBRAS_MODELS = []
    OPENROUTER_API_KEY = ""
    OPENROUTER_MODELS = []

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"

OPENAI_COMPAT_URLS = {
    'groq': "https://api.groq.com/openai/v1/chat/completions",
    'mistral': "https://api.mistral.ai/v1/chat/completions",
    'cerebras': "https://api.cerebras.ai/v1/chat/completions",
    'openrouter': "https://openrouter.ai/api/v1/chat/completions",
}


class LLMExtractor:
    """Extracts structured job data from page text using a multi-model fallback chain.

    Fallback chain: Gemini → Groq → Mistral → Cerebras → OpenRouter → Claude
    """

    def __init__(self, log=None, usage_callback=None):
        self.log = log
        self.usage_callback = usage_callback  # fn(call_type, provider, model, key_hint, prompt_tok, comp_tok, total_tok)
        self.api_keys = [k for k in LLM_API_KEYS if k and k != "PLACEHOLDER_API_KEY"]
        self.api_key = self.api_keys[0] if self.api_keys else GEMINI_API_KEY  # backward compat
        self._http = None
        # Track when each key×model combo was rate-limited: {"key[-4:]_model": timestamp}
        self._rate_limited_at = {}

        # Build OpenAI-compatible fallback providers: [(provider, api_key, [models])]
        self._fallback_providers = []
        if GROQ_API_KEY and GROQ_MODELS:
            self._fallback_providers.append(('groq', GROQ_API_KEY, GROQ_MODELS))
        if MISTRAL_API_KEY and MISTRAL_MODELS:
            self._fallback_providers.append(('mistral', MISTRAL_API_KEY, MISTRAL_MODELS))
        if CEREBRAS_API_KEY and CEREBRAS_MODELS:
            self._fallback_providers.append(('cerebras', CEREBRAS_API_KEY, CEREBRAS_MODELS))
        if OPENROUTER_API_KEY and OPENROUTER_MODELS:
            self._fallback_providers.append(('openrouter', OPENROUTER_API_KEY, OPENROUTER_MODELS))

        has_any = bool(self.api_keys or self._fallback_providers or CLAUDE_API_KEY)
        self.enabled = bool(LLM_EXTRACTION_ENABLED and has_any)

    @property
    def http(self):
        if self._http is None:
            self._http = httpx.Client(timeout=LLM_TIMEOUT_SECONDS)
        return self._http

    def set_http_client(self, client):
        """Share the CareerPageScraper's httpx client."""
        self._http = client

    def _info(self, msg):
        if self.log:
            self.log.info(msg)

    def _warn(self, msg):
        if self.log:
            self.log.warn(msg)

    # =================== Public API ===================

    def is_available(self):
        return self.enabled

    def extract_job_data(self, html, job_url, company_hint=None):
        """Extract structured job data from a detail page via LLM.
        Returns dict with title/company/location/salary/description/url, or None.
        """
        if not self.enabled:
            return None

        text = self._prepare_text(html)
        if len(text.strip()) < 100:
            return None

        prompt = self._build_detail_prompt(text, job_url, company_hint)
        raw = self._call_llm(prompt)
        if not raw:
            return None

        parsed = self._parse_json_response(raw)
        if not parsed or not parsed.get('title'):
            return None

        result = {
            'url': job_url,
            'title': parsed.get('title'),
            'company': parsed.get('company') or company_hint,
            'location': parsed.get('location'),
            'salary': parsed.get('salary'),
            'description': parsed.get('description', ''),
        }
        return result

    def extract_job_links(self, html, source_url, domain):
        """Identify job posting links from a listing page via LLM.
        Returns list of absolute URLs, or empty list.
        """
        if not self.enabled:
            return []

        text = self._prepare_links_text(html, source_url)
        if len(text.strip()) < 100:
            self._info("[LLM] Page text too short for link discovery (<100 chars)")
            return []

        prompt = self._build_listing_prompt(text, source_url)
        raw = self._call_llm(prompt)
        if not raw:
            self._warn("[LLM] Link discovery call returned no response")
            return []

        parsed = self._parse_json_response(raw)
        if not parsed or not isinstance(parsed.get('job_links'), list):
            self._warn("[LLM] Link discovery response could not be parsed")
            return []

        links = parsed['job_links']
        self._info(f"[LLM] Found {len(links)} job link(s) on listing page")
        return links

    # =================== Text Preparation ===================

    def _prepare_text(self, html):
        """Convert HTML to clean text for LLM. Smart head/tail truncation."""
        soup = BeautifulSoup(html, 'html.parser')

        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "noscript", "svg", "img", "iframe"]):
            tag.decompose()

        main = soup.find('main') or soup.find('article') or soup.find('body')
        text = main.get_text(separator='\n', strip=True) if main else soup.get_text(separator='\n', strip=True)

        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        max_chars = LLM_MAX_TEXT_CHARS
        if len(text) > max_chars:
            head = int(max_chars * 0.7)
            tail = int(max_chars * 0.25)
            text = text[:head] + "\n\n[...truncated...]\n\n" + text[-tail:]

        return text

    def _prepare_links_text(self, html, source_url):
        """Prepare structured link list for listing page analysis."""
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        lines = [
            f"Page URL: {source_url}",
            f"Page title: {soup.title.get_text(strip=True) if soup.title else 'N/A'}",
            "",
        ]

        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href in ('#', '', 'javascript:void(0)'):
                continue
            abs_href = urljoin(source_url, href)
            if abs_href in seen:
                continue
            seen.add(abs_href)

            link_text = a.get_text(strip=True)[:100]
            parent = a.parent
            parent_text = ''
            if parent:
                pt = parent.get_text(strip=True)[:150]
                if pt != link_text:
                    parent_text = pt

            if parent_text:
                lines.append(f"- [{link_text}]({abs_href}) | context: {parent_text}")
            else:
                lines.append(f"- [{link_text}]({abs_href})")

        text = '\n'.join(lines)
        max_chars = int(LLM_MAX_TEXT_CHARS * 0.75)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[...truncated...]"
        return text

    # =================== Prompts ===================

    def _build_detail_prompt(self, page_text, job_url, company_hint):
        company_ctx = f'\nThe company is likely: {company_hint}' if company_hint else ''
        return f"""You are a job posting data extractor. Extract structured data from this job posting page.
{company_ctx}
Page URL: {job_url}

Return ONLY a JSON object with these exact keys (use null for any field not found):
{{
  "title": "exact job title",
  "company": "hiring company name",
  "location": "city, state or Remote",
  "salary": "salary range if mentioned (e.g. $120,000 - $150,000/year)",
  "description": "the full job description text, preserving paragraphs"
}}

Rules:
- Extract the EXACT job title as written, do not paraphrase
- For salary, include the full range and pay period if available
- For location, normalize to City, State format; include Remote or Hybrid if mentioned
- For description, include responsibilities, qualifications, and benefits sections
- Do NOT invent data. If a field is not present on the page, use null
- If this is NOT a job posting page, return {{"title": null}}

PAGE CONTENT:
{page_text}"""

    def _build_listing_prompt(self, links_text, source_url):
        return f"""You are analyzing a career/jobs listing page to find links to individual job postings.

Below is a list of links found on this page. Identify which links point to INDIVIDUAL JOB POSTINGS (not categories, filters, company info, login, or navigation pages).

Return ONLY a JSON object:
{{
  "job_links": ["https://full-url-1", "https://full-url-2", ...]
}}

Rules:
- Only include links that lead to a SPECIFIC job posting with a title
- Exclude: navigation links, category pages, login/apply portals, social media, company about pages
- Exclude: pagination links, search/filter links, "see all jobs" type links
- Return the FULL absolute URL for each link
- If no job posting links are found, return {{"job_links": []}}

PAGE DATA:
{links_text}"""

    # =================== Multi-Model LLM Call ===================

    def _call_llm(self, prompt):
        """Try Gemini → Groq → Mistral → Cerebras → OpenRouter → Claude.
        For Gemini: rotate through key × model combinations.
        For OpenAI-compat providers: try each model, skip on rate limit.
        Returns raw text response or None.
        """
        # Phase 1: Gemini key × model rotation
        for model in LLM_FALLBACK_MODELS:
            for key in self.api_keys:
                combo = f"{key[-4:]}_{model}"
                if self._is_cooled_down(combo):
                    continue

                result = self._call_gemini(prompt, model, key)
                if result is not None:
                    return result

        # Phase 2: OpenAI-compatible providers (Groq, Mistral, Cerebras, OpenRouter)
        for provider, api_key, models in self._fallback_providers:
            for model in models:
                combo = f"{provider}_{model}"
                if self._is_cooled_down(combo):
                    continue

                self._info(f"[LLM] Trying {provider}/{model}")
                result = self._call_openai_compat(prompt, provider, api_key, model)
                if result is not None:
                    return result

        # Phase 3: Claude as last resort
        if CLAUDE_API_KEY:
            self._info("[LLM] All providers exhausted, trying Claude")
            result = self._call_claude(prompt)
            if result is not None:
                return result

        self._warn("[LLM] All models exhausted — no LLM extraction available")
        return None

    def _is_cooled_down(self, combo_key):
        """Check if a key×model combo is still within its rate-limit cooldown."""
        limited_at = self._rate_limited_at.get(combo_key)
        if limited_at is None:
            return False
        return (time.time() - limited_at) < LLM_RATE_LIMIT_COOLDOWN_SECONDS

    def _call_gemini(self, prompt, model, key):
        """Call a specific Gemini model with a specific key. Returns raw text, or None on failure."""
        url = f"{GEMINI_API_BASE}/{model}:generateContent"
        combo = f"{key[-4:]}_{model}"
        try:
            response = self.http.post(
                url,
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 4096,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                self._rate_limited_at[combo] = time.time()
                self._warn(f"[LLM] {model}/...{key[-4:]} rate-limited (429)")
                return None

            if response.status_code == 503:
                self._warn(f"[LLM] {model} overloaded (503), rotating")
                return None

            if response.status_code != 200:
                self._warn(f"[LLM] {model} returned HTTP {response.status_code}")
                return None

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if text:
                self._info(f"[LLM] {model}/...{key[-4:]} responded successfully")
                if self.usage_callback:
                    try:
                        um = data.get("usageMetadata", {})
                        self.usage_callback('llm_extract', 'gemini', model, f"...{key[-4:]}",
                                            um.get('promptTokenCount', 0), um.get('candidatesTokenCount', 0), um.get('totalTokenCount', 0))
                    except Exception:
                        pass
            return text or None

        except httpx.TimeoutException:
            self._warn(f"[LLM] {model} timed out")
            return None
        except Exception as e:
            self._warn(f"[LLM] {model} error: {e}")
            return None

    def _call_openai_compat(self, prompt, provider, api_key, model):
        """Call an OpenAI-compatible provider (Groq, Mistral, Cerebras, OpenRouter).
        Returns raw text response or None on failure.
        """
        base_url = OPENAI_COMPAT_URLS.get(provider)
        if not base_url:
            return None

        combo = f"{provider}_{model}"
        try:
            response = self.http.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                self._rate_limited_at[combo] = time.time()
                self._warn(f"[LLM] {provider}/{model} rate-limited (429)")
                return None

            if response.status_code == 503:
                self._warn(f"[LLM] {provider}/{model} overloaded (503), rotating")
                return None

            if response.status_code != 200:
                self._warn(f"[LLM] {provider}/{model} returned HTTP {response.status_code}")
                return None

            data = response.json()
            choices = data.get("choices", [])
            if not choices:
                return None

            text = choices[0].get("message", {}).get("content", "") or ""
            if text.strip():
                self._info(f"[LLM] {provider}/{model} responded successfully")
                if self.usage_callback:
                    try:
                        usage = data.get("usage", {})
                        self.usage_callback('llm_extract', provider, model, f"...{api_key[-4:]}",
                                            usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0),
                                            usage.get('total_tokens', 0))
                    except Exception:
                        pass
                return text
            return None

        except httpx.TimeoutException:
            self._warn(f"[LLM] {provider}/{model} timed out")
            return None
        except Exception as e:
            self._warn(f"[LLM] {provider}/{model} error: {e}")
            return None

    def _call_claude(self, prompt):
        """Call Claude as a last-resort fallback. Returns raw text or None."""
        try:
            response = self.http.post(
                CLAUDE_API_URL,
                headers={
                    "x-api-key": CLAUDE_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 4096,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )

            if response.status_code == 429:
                self._warn("[LLM] Claude rate-limited (429)")
                return None

            if response.status_code != 200:
                self._warn(f"[LLM] Claude returned HTTP {response.status_code}")
                return None

            data = response.json()
            content = data.get("content", [])
            if not content:
                return None

            text = content[0].get("text", "")
            if text:
                self._info("[LLM] Claude responded successfully")
                if self.usage_callback:
                    try:
                        cu = data.get("usage", {})
                        self.usage_callback('llm_extract', 'claude', CLAUDE_MODEL, f"...{CLAUDE_API_KEY[-4:]}",
                                            cu.get('input_tokens', 0), cu.get('output_tokens', 0),
                                            cu.get('input_tokens', 0) + cu.get('output_tokens', 0))
                    except Exception:
                        pass
            return text or None

        except httpx.TimeoutException:
            self._warn("[LLM] Claude timed out")
            return None
        except Exception as e:
            self._warn(f"[LLM] Claude error: {e}")
            return None

    # =================== Response Parsing ===================

    def _parse_json_response(self, raw):
        """Parse JSON from LLM response with multiple fallback strategies."""
        if not raw:
            return None

        # Direct parse (most common with responseMimeType=application/json)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Strip markdown code fences
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw.strip())
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Find first JSON object
        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        self._warn("[LLM] Could not parse JSON from response")
        return None

    def close(self):
        pass  # httpx client is shared, closed by CareerPageScraper
