"""Standalone config for the Job-Discovery scraper port.

Deliberately decoupled from Crucible's Flask app:
- No settings.py / ~/.jobdiscovery/settings.json
- No Flask, no SQLite, no licensing, no Obsidian output
- LLM keys default to EMPTY (keyless). The scraper then runs on
  JSON-LD + CSS + ATS JSON APIs + Workday API only, and
  LLMExtractor.is_available() returns False so the LLM tier is skipped.
  To enable the LLM fallback, export LLM_API_KEYS (comma-separated)
  or GEMINI_API_KEY. Keys are read from the environment only, never
  from Crucible's stored settings.
"""
import os

# --- HTTP ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
REQUEST_TIMEOUT_SECONDS = 10
SCRAPE_RUN_TIMEOUT_SECONDS = 300
WORKDAY_PROBE_TIMEOUT_SECONDS = 4

# --- Limits ---
MAX_JOBS_PER_SOURCE = 25
EMPTY_JOB_THRESHOLD = 3

# --- Output (standalone port writes JSON, not Obsidian markdown) ---
OUTPUT_DIR = None

# --- LLM extraction (Tier 2 fallback, OPTIONAL) ---
# Empty by default -> LLM tier disabled. Set env vars to enable.
LLM_EXTRACTION_ENABLED = True
LLM_MODEL = "gemini-2.5-flash"
LLM_MAX_TEXT_CHARS = 16000
LLM_TIMEOUT_SECONDS = 30
LLM_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
]
LLM_RATE_LIMIT_COOLDOWN_SECONDS = 60

_gemini_raw = os.environ.get("GEMINI_API_KEYS", "") or os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = _gemini_raw.split(",")[0].strip() if _gemini_raw else ""
_llm_raw = os.environ.get("LLM_API_KEYS", "")
LLM_API_KEYS = [k.strip() for k in _llm_raw.split(",") if k.strip()] or (
    [k.strip() for k in _gemini_raw.split(",") if k.strip()]
)

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODELS = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"] if GROQ_API_KEY else []
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODELS = ["mistral-small-latest"] if MISTRAL_API_KEY else []
CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY", "")
CEREBRAS_MODELS = ["llama3.1-8b"] if CEREBRAS_API_KEY else []
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODELS = [] if not OPENROUTER_API_KEY else [
    "meta-llama/llama-3.3-70b-instruct:free",
]
