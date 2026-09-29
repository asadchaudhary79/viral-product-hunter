"""Alibaba and AliExpress supplier sourcing."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin

from app.config import DECODO_PROXY_POOL, DECODO_SUPPLIER_MAX_WORKERS
from app.decodo import (
    _number,
    _walk_records,
    get_parsed_results,
    parse_decodo_content,
    scrape_with_decodo_payload,
    stringify_decodo_content,
)


def build_supplier_payloads(product_name: str) -> list[dict]:
    """Build standard Decodo URL requests for rendered marketplace HTML."""
    encoded_name = quote_plus(product_name)

    return [
        {
            "source": "Alibaba Search",
            "platform": "Alibaba",
            "payload": {
                "url": f"https://www.alibaba.com/trade/search?SearchText={encoded_name}",
                "proxy_pool": DECODO_PROXY_POOL,
                "headless": "html",
            },
        },
        {
            "source": "AliExpress Search",
            "platform": "AliExpress",
            "payload": {
                "url": f"https://www.aliexpress.com/wholesale?SearchText={encoded_name}",
                "proxy_pool": DECODO_PROXY_POOL,
                "headless": "html",
            },
        },
    ]


class _MarketplaceLinkParser(HTMLParser):
    """Extract self-contained product-link cards without marketplace CSS selectors."""

    def __init__(self, platform: str):
        super().__init__(convert_charrefs=True)
        self.platform = platform
        self.depth = 0
        self.card = None
        self.records = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.card is not None:
            self.depth += 1
            if tag == "img":
                label = attributes.get("alt") or attributes.get("title")
                if label:
                    self.card["labels"].append(label)
            return
        if tag != "a":
            return
        href = unescape(attributes.get("href") or "")
        is_product = (
            "/item/" in href if self.platform == "AliExpress"
            else any(marker in href for marker in ("product-detail", "/product/"))
        )
        if is_product:
            self.card = {
                "url": href,
                "labels": [value for value in (
                    attributes.get("aria-label"), attributes.get("title")
                ) if value],
                "text": [],
            }
            self.depth = 1

    def handle_data(self, data):
        if self.card is not None and data.strip():
            self.card["text"].append(data.strip())

    def handle_endtag(self, tag):
        if self.card is None:
            return
        self.depth -= 1
        if self.depth == 0:
            self.records.append(self.card)
            self.card = None


def parse_marketplace_html(platform: str, content: str) -> list[dict]:
    """Normalize rendered product anchors from Alibaba or AliExpress HTML."""
    parser = _MarketplaceLinkParser(platform)
    try:
        parser.feed(content)
    except Exception:
        logging.exception("Could not parse %s supplier HTML", platform)

    domain = "https://www.alibaba.com" if platform == "Alibaba" else "https://www.aliexpress.com"
    records = []
    seen = set()
    for card in parser.records:
        url = urljoin(domain, card["url"])
        canonical_url = url.split("?", 1)[0]
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        text = " ".join(card["text"])
        text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
        text = re.sub(r"([$€£])\s+(?=\d)", r"\1", text)
        title = next((label.strip() for label in card["labels"] if len(label.strip()) >= 8), None)
        if not title:
            # Product cards put the title before price/order/shipping fragments.
            title = re.split(r"(?:US\s*)?[$€£]|\b(?:USD|EUR|GBP)\b", text, maxsplit=1)[0].strip()
        price_match = re.search(
            r"(?:(?:US\s*)?[$€£]|\b(?:USD|EUR|GBP|CNY|RMB|AUD|CAD)\b)\s*"
            r"\d[\d,]*(?:\.\d+)?(?:\s*[-–]\s*(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?)?",
            text,
            re.IGNORECASE,
        )
        if not title or not price_match:
            continue
        shipping = next((part for part in card["text"] if re.search(r"shipping|delivery|ships? in", part, re.I)), None)
        moq = next((part for part in card["text"] if re.search(r"min(?:imum)?\.?\s*order|\bMOQ\b", part, re.I)), None)
        records.append({
            "title": title[:300],
            "price": price_match.group(0),
            "url": canonical_url,
            "min_order_quantity": moq,
            "shipping": shipping,
            "rating": next((_number(part) for part in card["text"] if re.search(r"stars?|rating", part, re.I)), None),
            "orders": next((_number(part) for part in card["text"] if re.search(r"sold|orders?", part, re.I)), None),
        })
        if len(records) >= 5:
            break
    return records


def extract_supplier_json(data: dict):
    """Keep only JSON parsed by Decodo, excluding raw HTML or Markdown documents."""
    parsed_items = []
    for item in data.get("results", []):
        parsed = parse_decodo_content(item.get("content"))
        if isinstance(parsed, (dict, list)):
            parsed_items.append(parsed)
    if len(parsed_items) == 1:
        return parsed_items[0]
    return parsed_items


def _price_parts(record: dict) -> tuple[float | None, dict | None, str | None]:
    raw = record.get("price_range") or record.get("price") or record.get("sale_price")
    explicit_min = _number(record.get("price_min") or record.get("min_price"))
    explicit_max = _number(record.get("price_max") or record.get("max_price"))
    text = stringify_decodo_content(raw)
    values = [float(value.replace(",", "")) for value in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
    lower = explicit_min if explicit_min is not None else (values[0] if values else None)
    upper = explicit_max if explicit_max is not None else (values[1] if len(values) > 1 else None)
    price_range = {"min": lower, "max": upper} if lower is not None and upper is not None and lower != upper else None
    unit_price = None if price_range else lower

    currency = record.get("currency")
    if isinstance(currency, str):
        currency = currency.upper()
    elif "$" in text:
        currency = "USD"
    elif "€" in text:
        currency = "EUR"
    elif "£" in text:
        currency = "GBP"
    else:
        code = re.search(r"\b(USD|EUR|GBP|CNY|RMB|AUD|CAD)\b", text, re.IGNORECASE)
        currency = code.group(1).upper() if code else None
    return unit_price, price_range, currency


def normalize_supplier_offer(
    platform: str, product_reference: dict, supplier_data
) -> list[dict]:
    """Normalize Decodo marketplace listings while preserving missing values."""
    parsed_value = parse_decodo_content(supplier_data)
    parsed = (
        {"products": parse_marketplace_html(platform, supplier_data)}
        if isinstance(parsed_value, str)
        else get_parsed_results(parsed_value)
    )
    if isinstance(parsed, dict) and isinstance(parsed.get("products"), list):
        records = parsed["products"]
    else:
        records = [
            record for record in _walk_records(parsed)
            if any(record.get(key) for key in ("title", "product_title", "product_name", "name"))
        ]

    offers = []
    for record in records[:5]:
        title = next((record.get(key) for key in ("title", "product_title", "product_name", "name") if record.get(key)), None)
        unit_price, price_range, currency = _price_parts(record)
        url = record.get("url") or record.get("product_url") or record.get("link")
        if not title or (unit_price is None and price_range is None):
            continue
        if isinstance(url, str) and url.startswith("//"):
            url = f"https:{url}"
        elif isinstance(url, str) and url.startswith("/"):
            domain = "www.alibaba.com" if platform == "Alibaba" else "www.aliexpress.com"
            url = f"https://{domain}{url}"
        offers.append({
            "product_reference": product_reference,
            "supplier_platform": platform,
            "supplier_title": title,
            "unit_price": unit_price,
            "price_range": price_range,
            "currency": currency,
            "min_order_quantity": (
                record.get("min_order_quantity") or record.get("minimum_order_quantity")
                or record.get("moq") or record.get("min_order")
            ),
            "shipping_info": record.get("shipping") or record.get("shipping_info") or record.get("delivery"),
            "supplier_url": url,
            "rating": _number(record.get("rating") or record.get("supplier_rating")),
            "orders": _number(record.get("orders") or record.get("sold") or record.get("sold_count")),
            "reviews": _number(record.get("reviews") or record.get("reviews_count") or record.get("review_count")),
            "supplier_evidence": record.get("supplier_evidence") or record.get("store_info") or record.get("supplier"),
        })
    return offers


def validate_suppliers_for_products(products: list[dict]) -> dict:
    """Run two independent supplier requests for each of the ranked top ten."""
    top_products = products[:10]
    jobs = []
    for index, product in enumerate(top_products):
        product_name = product.get("product")
        if not product_name:
            continue
        reference = {"rank": index + 1, "candidate_index": index, "product": product_name}
        for payload_info in build_supplier_payloads(product_name):
            jobs.append((reference, payload_info))

    def run_job(job):
        reference, payload_info = job
        supplier_result = {
            "source": payload_info["source"],
            "supplier_platform": payload_info["platform"],
            "product_reference": reference,
        }
        try:
            result = scrape_with_decodo_payload(payload_info["source"], payload_info["payload"])
            if "error" in result:
                supplier_result.update({"supplier_data": None, "offers": [], "error": result["error"]})
                return supplier_result

            result_items = result.get("data", {}).get("results", [])
            raw_content = result_items[0].get("content") if result_items else None
            parsed_json = extract_supplier_json(result.get("data", {}))
            normalization_input = raw_content if isinstance(raw_content, str) else parsed_json
            supplier_result["offers"] = normalize_supplier_offer(
                payload_info["platform"], reference, normalization_input
            )
            supplier_result["supplier_data"] = (
                {
                    "format": "rendered_html",
                    "content_chars": len(raw_content),
                    "status_code": result_items[0].get("status_code"),
                    "url": result_items[0].get("url"),
                    "offers_extracted": len(supplier_result["offers"]),
                }
                if isinstance(parse_decodo_content(raw_content), str) else parsed_json
            )
            for offer_index, offer in enumerate(supplier_result["offers"]):
                offer["provenance"] = {
                    "source": payload_info["source"],
                    "platform": payload_info["platform"],
                    "search_url": payload_info["payload"]["url"],
                    "candidate_index": reference["candidate_index"],
                    "offer_index": offer_index,
                }
            if not normalization_input:
                supplier_result["warning"] = "Decodo returned an empty marketplace page"
            elif not supplier_result["offers"]:
                supplier_result["warning"] = (
                    "Decodo returned the marketplace page, but no priced product links were found"
                )
            return supplier_result
        except Exception as error:
            logging.exception("Supplier normalization failed for %s", payload_info["source"])
            supplier_result.update({"supplier_data": None, "offers": [], "error": str(error)})
            return supplier_result

    worker_count = min(max(1, DECODO_SUPPLIER_MAX_WORKERS), len(jobs)) if jobs else 1
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        request_results = list(executor.map(run_job, jobs))

    grouped = []
    for index, product in enumerate(top_products):
        product_name = product.get("product")
        matching = [
            result for result in request_results
            if result["product_reference"]["rank"] == index + 1
        ]
        grouped.append({
            "product_reference": {"rank": index + 1, "candidate_index": index, "product": product_name},
            "product_name": product_name,
            "supplier_results": matching,
        })

    failed = sum(1 for result in request_results if result.get("error"))
    empty = sum(1 for result in request_results if result.get("warning"))
    offers_by_platform = {
        platform: sum(
            len(result["offers"]) for result in request_results
            if result["supplier_platform"] == platform
        )
        for platform in ("Alibaba", "AliExpress")
    }
    return {
        "supplier_data": grouped,
        "supplier_summary": {
            "products_validated": len(grouped),
            "total_supplier_requests": len(request_results),
            "successful_supplier_requests": len(request_results) - failed,
            "failed_supplier_requests": failed,
            "empty_supplier_requests": empty,
            "offers_by_platform": offers_by_platform,
        },
    }

