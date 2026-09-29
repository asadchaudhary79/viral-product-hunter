"""Decodo client plus parsing, trimming, and product extraction."""
import json
import math
import re

import requests

from app.config import DECODO_API_URL, DECODO_AUTH_TOKEN, DECODO_REQUEST_TIMEOUT


def stringify_decodo_content(content):
    """Convert Decodo content to a string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content)


def parse_decodo_content(content):
    """Parse JSON content returned as text while preserving normal page text."""
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except ValueError:
        return content


def get_parsed_results(content):
    """Return the listing section from old and current Decodo parser envelopes."""
    content = parse_decodo_content(content)
    if not isinstance(content, dict):
        return content

    parsed = content.get("results", content)
    if not isinstance(parsed, dict):
        return parsed

    # Current templates put parser metadata and the actual listings in a second
    # results object. Older responses put listings in the first one.
    nested = parsed.get("results")
    if isinstance(nested, dict):
        return nested
    return parsed


def compact_parsed_content(source_name: str, content: dict) -> dict:
    """Compact parsed content for Amazon and Google results."""
    content = parse_decodo_content(content)
    if not isinstance(content, dict):
        return content
    
    parser_envelope = content.get("results", {})
    parse_status_code = parser_envelope.get("parse_status_code") if isinstance(parser_envelope, dict) else None
    parsed = get_parsed_results(content)
    if not isinstance(parsed, dict):
        return content
    
    # Amazon results
    if source_name == "Amazon Search" and "organic" in parsed:
        compact_organic = []
        for product in parsed.get("organic", [])[:25]:  # Keep up to 25 products
            compact_product = {
                "pos": product.get("pos"),
                "title": product.get("title"),
                "price": product.get("price"),
                "currency": product.get("currency"),
                "rating": product.get("rating"),
                "reviews_count": product.get("reviews_count"),
                "sales_volume": product.get("sales_volume"),
                "best_seller": product.get("best_seller"),
                "is_amazons_choice": product.get("is_amazons_choice"),
                "asin": product.get("asin"),
                "url": f"https://www.amazon.com{product.get('url')}" if product.get("url", "").startswith("/") else product.get("url"),
                "image_url": product.get("image_url"),
            }
            compact_organic.append(compact_product)
        
        return {
            "query": parsed.get("query"),
            "url": parsed.get("url"),
            "total_result_count": parsed.get("total_result_count"),
            "page": parsed.get("page"),
            "organic": compact_organic,
            "parse_status_code": parse_status_code or parsed.get("parse_status_code"),
        }
    
    # Google results
    elif source_name.startswith("Google Search"):
        compacted = {
            "query": parsed.get("query"),
            "page": parsed.get("page"),
            "parse_status_code": parse_status_code or parsed.get("parse_status_code"),
        }
        section_limits = {
            "ai_overviews": 3,
            "organic": 10,
            "related_questions": 10,
            "pla": 25,
            "shopping": 25,
            "shopping_results": 25,
            "products": 25,
            "product_results": 25,
            "popular_products": 25,
        }
        for section, limit in section_limits.items():
            always_include = section in {"ai_overviews", "organic", "related_questions"}
            section_data = parsed.get(section, [] if always_include else None)
            if always_include or section_data:
                compacted[section] = section_data[:limit] if isinstance(section_data, list) else section_data
        return compacted
    
    # Other sources (Reddit, TikTok, YouTube)
    return content


def trim_decodo_result(result: dict, max_content_chars: int = 3500) -> dict:
    """Trim Decodo result to reduce size."""
    # Deep copy to avoid modifying the original
    trimmed = json.loads(json.dumps(result))
    
    if "data" not in trimmed or "results" not in trimmed["data"]:
        return trimmed
    
    for item in trimmed["data"]["results"]:
        if "content" in item:
            # Keep parsed records structured; only raw page text needs truncating.
            compacted = compact_parsed_content(trimmed.get("source", ""), item["content"])
            if isinstance(compacted, str):
                compacted = compacted[:max_content_chars]
            item["content"] = compacted
    
    return trimmed


def summarize_decodo_result(result: dict) -> dict:
    """Summarize key metrics from a Decodo result."""
    if "data" not in result or "results" not in result["data"]:
        return {
            "result_count": 0,
            "status_code": result.get("data", {}).get("status_code", "N/A"),
            "content_chars": 0,
            "prices_found": 0,
            "urls_found": 0,
            "images_found": 0,
            "captcha_or_robot_detected": False,
            "preview": "",
        }
    
    content_text = "".join(
        stringify_decodo_content(item.get("content", ""))
        for item in result["data"]["results"]
    )
    
    # Regex patterns
    price_pattern = re.compile(r"\$\d+\.\d{2}|\d+\s*(USD|EUR|GBP|\$|€|£)")
    url_pattern = re.compile(r"https?://[^\s]+|www\.[^\s]+|amazon\.com/[^\s]+")
    image_pattern = re.compile(r"https?://[^\s]+\.(jpg|jpeg|png|gif|webp)")
    captcha_pattern = re.compile(
        r"captcha|verify you are human|unusual traffic|access denied",
        re.IGNORECASE,
    )
    products = extract_products([result])
    result_items = result["data"]["results"]
    parse_status_code = next(
        (
            record.get("parse_status_code")
            for item in result_items
            for record in _walk_records(parse_decodo_content(item.get("content")))
            if record.get("parse_status_code") is not None
        ),
        "N/A",
    )
    status_code = result.get("data", {}).get("status_code")
    if status_code is None:
        status_code = next(
            (item.get("status_code") for item in result_items if item.get("status_code") is not None),
            "N/A",
        )
    
    return {
        "result_count": len(products),
        "response_count": len(result_items),
        "status_code": status_code,
        "parse_status_code": parse_status_code,
        "content_chars": len(content_text),
        "prices_found": len(price_pattern.findall(content_text)),
        "urls_found": len(url_pattern.findall(content_text)),
        "images_found": len(image_pattern.findall(content_text)),
        "captcha_or_robot_detected": bool(captcha_pattern.search(content_text)),
        "preview": ", ".join(product["product"] for product in products[:5]) or content_text[:200],
    }


def _number(value):
    """Return the first numeric value from common scraper field formats."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        value = value.get("value") or value.get("current") or value.get("amount")
    if not isinstance(value, str):
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    return float(match.group().replace(",", "")) if match else None


def _walk_records(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_records(child)


def _image_url(value):
    """Extract one image URL from common scalar and nested thumbnail formats."""
    if isinstance(value, str):
        return value if value.startswith(("http://", "https://", "//", "data:image/")) else None
    if isinstance(value, list):
        for item in value:
            image = _image_url(item)
            if image:
                return image
        return None
    if isinstance(value, dict):
        direct = value.get("url") or value.get("src")
        return direct or _image_url(value.get("thumbnails") or value.get("images"))
    return None


def _product_score(product):
    evidence = product["evidence"]
    score = 35
    price = product.get("price")
    if price is not None and 5 <= price <= 50:
        score += 12
    rating = evidence.get("rating")
    if rating:
        score += min(15, round(rating * 3))
    reviews = evidence.get("reviews") or evidence.get("sales") or 0
    if reviews:
        score += min(18, round(math.log10(max(1, reviews)) * 5))
    if product.get("image"):
        score += 5
    if product.get("url"):
        score += 5
    if evidence.get("best_seller") or evidence.get("amazons_choice"):
        score += 10
    return min(100, score)


def extract_products(discovery_results: list[dict], limit: int = 25) -> list[dict]:
    """Normalize product-like records from parsed Decodo responses."""
    products = {}
    title_keys = ("product_title", "product_name", "title", "name")
    price_keys = (
        "price", "current_price", "sale_price", "original_price", "price_lower", "price_min"
    )

    for result in discovery_results:
        source = result.get("source", "Unknown")
        for item in result.get("data", {}).get("results", []):
            content = parse_decodo_content(item.get("content"))
            for record in _walk_records(content):
                title = next((record.get(key) for key in title_keys if record.get(key)), None)
                price = next((_number(record.get(key)) for key in price_keys if _number(record.get(key)) is not None), None)
                rating = _number(record.get("rating") or record.get("product_rating"))
                reviews = _number(
                    record.get("reviews_count") or record.get("review_count") or record.get("reviews")
                )
                sales = _number(
                    record.get("sales_volume") or record.get("sold_count")
                    or record.get("sales") or record.get("sold")
                )
                url = (
                    record.get("product_url") or record.get("product_link")
                    or record.get("url") or record.get("link")
                )
                image = (
                    record.get("image_url") or record.get("product_image")
                    or record.get("image") or record.get("thumbnail")
                    or record.get("images") or record.get("thumbnails")
                )

                # Navigation and article links often have titles but no product evidence.
                if not isinstance(title, str) or not title.strip():
                    continue
                image = _image_url(image)
                if price is None and not any((rating, reviews, sales, image)):
                    continue
                if isinstance(url, str) and url.startswith("/") and source == "Amazon Search":
                    url = f"https://www.amazon.com{url}"

                key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
                if not key:
                    continue
                evidence = {
                    name: value
                    for name, value in {
                        "rating": rating,
                        "reviews": reviews,
                        "sales": sales,
                        "best_seller": record.get("best_seller"),
                        "amazons_choice": record.get("is_amazons_choice"),
                    }.items()
                    if value not in (None, False, "")
                }
                candidate = {
                    "product": title.strip(),
                    "source": source,
                    "price": price,
                    "currency": record.get("currency") or ("USD" if price is not None else None),
                    "url": url,
                    "image": image,
                    "evidence": evidence,
                }
                existing = products.get(key)
                if existing:
                    existing["source"] = ", ".join(dict.fromkeys((existing["source"] + ", " + source).split(", ")))
                    existing["evidence"].update(evidence)
                    for field in ("price", "currency", "url", "image"):
                        existing[field] = existing.get(field) or candidate.get(field)
                else:
                    products[key] = candidate

    ranked = list(products.values())
    for product in ranked:
        product["viral_score"] = _product_score(product)
    return sorted(ranked, key=lambda product: product["viral_score"], reverse=True)[:limit]


def scrape_with_decodo_payload(source_name: str, payload: dict) -> dict:
    """Scrape a single source using Decodo."""
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Basic {DECODO_AUTH_TOKEN}",
    }
    
    try:
        response = requests.post(
            DECODO_API_URL,
            headers=headers,
            json=payload,  # Send payload directly, not nested
            timeout=(10, DECODO_REQUEST_TIMEOUT),
        )
        if not response.ok:
            try:
                detail = response.json().get("message") or response.text
            except (ValueError, AttributeError):
                detail = response.text
            detail = str(detail).strip()[:500]
            raise requests.HTTPError(
                f"Decodo returned HTTP {response.status_code}: {detail or response.reason}",
                response=response,
            )
        result = {
            "source": source_name,
            "request": payload,
            "data": response.json(),
        }
        if source_name in {"Alibaba Search", "AliExpress Search"}:
            return result
        return trim_decodo_result(result, max_content_chars=12000)
    except requests.Timeout:
        return {
            "source": source_name,
            "request": payload,
            "error": f"Decodo timed out after {DECODO_REQUEST_TIMEOUT} seconds",
        }
    except (requests.RequestException, ValueError) as error:
        return {
            "source": source_name,
            "request": payload,
            "error": str(error),
        }

