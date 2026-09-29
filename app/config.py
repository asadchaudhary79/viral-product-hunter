"""Runtime settings.

Secrets come from `.env`. Scraper limits and the Kimi model are fixed here so the
environment file only carries the two credentials this app uses.
"""
import os

from dotenv import load_dotenv

load_dotenv()

DECODO_AUTH_TOKEN = os.getenv("DECODO_AUTH_TOKEN")
DECODO_API_URL = "https://scraper-api.decodo.com/v2/scrape"
DECODO_REQUEST_TIMEOUT = 120
DECODO_MAX_WORKERS = 5
DECODO_SUPPLIER_MAX_WORKERS = 10
DECODO_PROXY_POOL = "premium"

KIMI_API_URL = "https://api.moonshot.ai/v1/chat/completions"
KIMI_MODEL_NAME = "kimi-k3"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000

if not DECODO_AUTH_TOKEN:
    raise ValueError("Missing DECODO_AUTH_TOKEN in .env")
