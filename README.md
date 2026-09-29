# Viral Product Hunter

A beginner-friendly project for building a viral product research app with a FastAPI backend and Streamlit frontend.

## Layout

```text
app/
  api.py          FastAPI routes
  config.py       Decodo token, Kimi model, scraper limits
  decodo.py       Scraper client, parsing, and product extraction
  discovery.py    Google, Amazon, Reddit, TikTok Shop, and YouTube
  suppliers.py    Alibaba and AliExpress sourcing
  ranking.py      Kimi ranking and the deterministic fallback
  schemas.py      Request models
ui/
  streamlit_app.py
tests/
  test_api.py
```

## Setup

Create and activate the virtual environment:

```bash
uv venv .venv
source .venv/bin/activate
```

On Windows, activate it with:

```powershell
.venv\Scripts\activate
```

Install the dependencies:

```bash
uv pip install -r requirements.txt
```

Create your local environment file:

```bash
cp .env.example .env
```

Then fill in `.env`:

- `DECODO_AUTH_TOKEN` (required): Decodo scraper API token.
- `KIMI_API_KEY` (optional): Kimi ranking key. Without it, the app uses deterministic weighted ranking.

Kimi calls `kimi-k3` at `https://api.moonshot.ai/v1/chat/completions`. Scraper timeouts, worker counts, and the premium proxy pool are set in `app/config.py`.

## Run

Start the FastAPI backend in the first terminal:

```bash
python -m app.api
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `http://127.0.0.1:8000/docs`.

Start Streamlit in a second terminal with the same environment activated:

```bash
python -m streamlit run ui/streamlit_app.py
```

Streamlit opens at `http://localhost:8501` and calls the FastAPI backend at `http://127.0.0.1:8000`.

## Endpoints

- `GET /health`: health check
- `POST /discover`: product discovery and initial ranking
- `POST /source`: supplier sourcing and final ranking for discovered products
- `POST /hunt`: the full pipeline in one request

## Response

`POST /hunt` runs the complete pipeline and returns distinct `initial_products`,
`final_products`, `supplier_summary`, `supplier_data`, `discovery_summary`,
`discovery_data`, and `ranking_warnings` fields. The final ranking receives only
normalized candidates and supplier offers, and falls back to deterministic weighted
ranking when Kimi is unavailable.

The Streamlit UI calls `POST /discover` and `POST /source` separately so it can show
stage progress and avoid one long combined request.

## Tests

Run the test suite with:

```bash
python -m unittest -v tests.test_api
```
