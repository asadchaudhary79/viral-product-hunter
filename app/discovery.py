"""Discovery sources and the initial ranking stage."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

from app.brief import brief_as_dict, build_discovery_queries, price_label
from app.config import DECODO_MAX_WORKERS
from app.decodo import (
    extract_products,
    scrape_with_decodo_payload,
    summarize_decodo_result,
)
from app.ranking import analyze_with_ai_model, score_products_for_brief


def build_source_urls(niche: str, brief=None) -> list[dict]:
    """Build discovery source URLs shaped by the seller brief."""
    data = brief_as_dict(brief)
    queries = build_discovery_queries(niche, data)
    price = price_label(data.get("price_max"))
    goal = (data.get("goal") or "dropshipping").lower()
    sources = []

    for idx, query in enumerate(queries, 1):
        sources.append({
            "source": f"Google Search {idx}",
            "payload": {
                "target": "google_search",
                "query": query,
                "headless": "html",
                "parse": True,
                "page_count": 1,
                "google_results_language": "en",
            },
        })

    amazon_query = f"{niche} {price}" if price != "any price" else niche
    if "amazon" in goal:
        amazon_query = f"best selling {niche} {price}"
    sources.append({
        "source": "Amazon Search",
        "payload": {
            "target": "amazon_search",
            "query": amazon_query,
            "page_from": "1",
            "parse": True,
        },
    })

    first_google_query = queries[0]
    sources.append({
        "source": "Reddit Search",
        "payload": {
            # Dedicated Reddit targets accept posts/subreddits, not global search.
            # The JSON endpoint avoids Reddit's logged-out navigation shell.
            "target": "universal",
            "url": (
                "https://www.reddit.com/search.json?"
                f"q={quote_plus(first_google_query)}&sort=relevance&t=year&limit=25"
            ),
        },
    })

    tiktok_query = niche
    if "tiktok" in goal:
        tiktok_query = f"viral {niche}"
    sources.append({
        "source": "TikTok Shop Search",
        "payload": {
            "target": "tiktok_shop_search",
            "query": tiktok_query,
            "parse": True,
        },
    })

    youtube_query = f"viral {niche} products TikTok"
    if data.get("problem"):
        youtube_query = f"{niche} {data['problem']} product review"
    sources.append({
        "source": "YouTube Search",
        "payload": {
            "target": "youtube_search",
            "query": youtube_query,
        },
    })

    return sources


def scrape_with_decodo(niche: str, brief=None, logger=None) -> str:
    """Scrape all discovery sources for a niche using Decodo."""
    sources = build_source_urls(niche, brief)

    def scrape_source(source: dict) -> dict:
        source_name = source.get("source", "Untitled Source")
        payload = source.get("payload", {})

        if logger:
            logger.info(f"discovery:start:{source_name}:{json.dumps(payload)}")

        result = scrape_with_decodo_payload(source_name, payload)

        if logger:
            if "error" in result:
                logger.error(f"discovery:fail:{source_name}:{json.dumps(payload)}")
            else:
                summary = summarize_decodo_result(result)
                logger.info(f"discovery:ok:{source_name}:{json.dumps(summary)}")

        return result

    # Sources are independent. Running a small batch concurrently prevents one
    # slow target from making the entire frontend request time out.
    worker_count = min(max(1, DECODO_MAX_WORKERS), len(sources))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(scrape_source, sources))

    return json.dumps(results, indent=2)


def run_discovery(niche: str, brief=None) -> dict:
    """Run discovery and the initial ranking stage using the seller brief."""
    brief_data = brief_as_dict(brief)
    discovery_data = scrape_with_decodo(niche, brief_data)
    discovery_results = json.loads(discovery_data)
    candidates = score_products_for_brief(extract_products(discovery_results), brief_data)
    ranked_products, ai_warning = analyze_with_ai_model(niche, candidates, brief_data)
    initial_products = ranked_products[:10]
    discovery_summary = []
    for result in discovery_results:
        summary = summarize_decodo_result(result)
        summary["source"] = result.get("source", "Unknown")
        summary["error"] = result.get("error")
        discovery_summary.append(summary)
    return {
        "niche": niche,
        "brief": brief_data,
        "initial_products": initial_products,
        "discovery_summary": discovery_summary,
        "discovery_data": discovery_results,
        "ranking_warnings": [ai_warning] if ai_warning else [],
    }
