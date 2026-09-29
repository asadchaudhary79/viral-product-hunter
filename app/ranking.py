"""Kimi ranking, with a deterministic fallback when Kimi is unavailable."""
import json
import logging
import math
import os
import re

import requests

from app.config import KIMI_API_URL, KIMI_MODEL_NAME
from app.decodo import _number

CURRENCY_TO_USD = {
    "USD": 1.0,
    "EUR": 1.09,
    "GBP": 1.28,
    "CNY": 0.14,
    "RMB": 0.14,
    "AUD": 0.66,
    "CAD": 0.73,
}


def get_ai_providers():
    """Return the configured Kimi provider, or nothing when the key is absent."""
    kimi_key = os.getenv("KIMI_API_KEY")
    if not kimi_key or kimi_key.startswith("your_"):
        return []
    return [{
        "name": "Kimi",
        "api_key": kimi_key,
        "api_url": KIMI_API_URL,
        "model": KIMI_MODEL_NAME,
    }]


def get_ai_temperature(api_url: str, temperature: float = 0.7) -> float:
    """Get AI temperature based on API URL."""
    return 1.0 if "kimi.com" in api_url else temperature


def get_ai_timeout(api_url: str) -> int:
    """Get AI timeout based on API URL."""
    return 240 if "kimi.com" in api_url or "moonshot.ai" in api_url else 60


def build_ai_payload(api_url: str, model: str, prompt: str, temperature: float = 0.7) -> dict:
    """Build AI payload for chat completions."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }

    if model in ("k3", "k3-256k", "kimi-k3"):
        payload["reasoning_effort"] = "low"
        payload["max_completion_tokens"] = 4096
    else:
        payload["temperature"] = get_ai_temperature(api_url, temperature)

    if "moonshot.ai" in api_url:
        payload["response_format"] = {"type": "json_object"}

    return payload


def analyze_with_ai_model(niche: str, products: list[dict]) -> tuple[list[dict], str | None]:
    """Optionally refine product scores, falling back to local evidence scores."""
    if not products:
        return [], None

    prompt = f"""
Rank these extracted products for dropshipping without inventing information.

Niche: {niche}
Candidates, indexed from zero:
{json.dumps(products, indent=2)}

Consider problem solving, video demonstration, emotional appeal, shipping ease,
competition, bundling, supplier evidence, and year-round demand. Reject unsafe,
restricted, fragile, edible, medicinal, branded-risk, or difficult-to-ship items.

Return JSON only in this shape:
{{"ranked": [{{"candidate_index": 0, "viral_score": 0, "reason": "short reason"}}]}}
Use only supplied candidate indexes, integer scores from 0-100, and at most 10 items.
"""

    errors = []
    for ai_settings in get_ai_providers():
        payload = build_ai_payload(
            ai_settings["api_url"], ai_settings["model"], prompt, temperature=0.2
        )
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {ai_settings['api_key']}",
        }
        try:
            response = requests.post(
                ai_settings["api_url"],
                headers=headers,
                json=payload,
                timeout=get_ai_timeout(ai_settings["api_url"]),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            ranked_data = json.loads(content).get("ranked", [])
            ranked = []
            for item in ranked_data:
                index = item.get("candidate_index")
                if not isinstance(index, int) or not 0 <= index < len(products):
                    continue
                product = dict(products[index])
                product["viral_score"] = max(0, min(100, int(item.get("viral_score", product["viral_score"]))))
                product["reason"] = str(item.get("reason", ""))[:200]
                ranked.append(product)
            if ranked:
                return sorted(ranked, key=lambda item: item["viral_score"], reverse=True)[:10], None
            raise ValueError("AI returned no valid ranked candidates")
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status == 401 or "401" in str(error):
                errors.append(f"{ai_settings['name']} authentication failed (401)")
            elif status == 429 or "429" in str(error):
                errors.append(f"{ai_settings['name']} quota or balance is unavailable (429)")
            else:
                errors.append(f"{ai_settings['name']} ranking failed")

    if errors:
        warning = f"{'; '.join(errors)}. Showing evidence-based scores."
    else:
        warning = "No AI provider is configured. Showing evidence-based scores."
    if errors:
        logging.warning("AI ranking unavailable: %s", "; ".join(errors))
    return products[:10], warning

def _offer_cost(offer: dict) -> float | None:
    """Return a credible comparable unit cost in USD, or None."""
    currency = offer.get("currency")
    rate = CURRENCY_TO_USD.get(currency) if isinstance(currency, str) else None
    price_range = offer.get("price_range")
    price = price_range.get("min") if isinstance(price_range, dict) else offer.get("unit_price")
    if rate is None or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    return round(price * rate, 2)


def _moq_value(offer: dict) -> float | None:
    return _number(offer.get("min_order_quantity"))


def _evidence_score(offer: dict) -> float:
    score = 0.0
    rating = offer.get("rating")
    if isinstance(rating, (int, float)) and 0 < rating <= 5:
        score += min(35, rating * 7)
    volume = offer.get("orders") or offer.get("reviews")
    if isinstance(volume, (int, float)) and volume > 0:
        score += min(30, math.log10(volume + 1) * 10)
    if offer.get("supplier_evidence"):
        score += 20
    if offer.get("supplier_url"):
        score += 15
    return min(100, score)


def _shipping_score(offer: dict) -> float:
    shipping = str(offer.get("shipping_info") or "").lower()
    if not shipping:
        return 40
    if any(term in shipping for term in ("cannot ship", "pickup only", "freight only")):
        return 10
    if any(term in shipping for term in ("free shipping", "ships in", "delivery", "day")):
        return 85
    return 60


def _moq_score(offer: dict) -> float:
    moq = _moq_value(offer)
    if moq is None:
        return 45
    if moq <= 1:
        return 100
    if moq <= 10:
        return 80
    if moq <= 50:
        return 55
    if moq <= 100:
        return 30
    return 10


def build_final_ranking_input(products: list[dict], supplier_data: list[dict]) -> tuple[list[dict], list[dict]]:
    """Build compact normalized model input with stable candidate and offer indexes."""
    normalized_products = []
    normalized_offers = []
    groups_by_rank = {
        group.get("product_reference", {}).get("rank"): group for group in supplier_data
    }
    for candidate_index, product in enumerate(products):
        normalized_products.append({
            "candidate_index": candidate_index,
            "product": product.get("product"),
            "viral_score": product.get("viral_score", 0),
            "retail_price": product.get("price"),
            "retail_currency": product.get("currency"),
            "source": product.get("source"),
            "evidence": product.get("evidence", {}),
        })
        group = groups_by_rank.get(candidate_index + 1, {})
        offer_index = 0
        for result in group.get("supplier_results", []):
            for offer in result.get("offers", []):
                compact = {
                    key: offer.get(key) for key in (
                        "supplier_platform", "supplier_title", "unit_price", "price_range",
                        "currency", "min_order_quantity", "shipping_info", "supplier_url",
                        "rating", "orders", "reviews", "supplier_evidence",
                    )
                }
                compact.update({
                    "candidate_index": candidate_index,
                    "offer_index": offer_index,
                    "price_usd": _offer_cost(offer),
                    "provenance": {
                        "source": result.get("source"),
                        "platform": result.get("supplier_platform"),
                        "product_rank": candidate_index + 1,
                        "search_url": offer.get("provenance", {}).get("search_url"),
                    },
                })
                normalized_offers.append(compact)
                offer_index += 1
    return normalized_products, normalized_offers


def deterministic_final_ranking(products: list[dict], offers: list[dict]) -> list[dict]:
    """Rank products from normalized evidence when final AI ranking is unavailable."""
    ranked = []
    for candidate_index, product in enumerate(products):
        candidate_offers = [offer for offer in offers if offer["candidate_index"] == candidate_index]
        credible = [offer for offer in candidate_offers if offer.get("price_usd") is not None]
        selected = max(
            credible,
            key=lambda offer: (
                0.35 * (100 - min(100, offer["price_usd"] * 4))
                + 0.30 * _evidence_score(offer)
                + 0.20 * _moq_score(offer)
                + 0.15 * _shipping_score(offer)
            ),
            default=None,
        )
        viral = max(0, min(100, float(product.get("viral_score") or 0)))
        platforms = {offer.get("supplier_platform") for offer in credible}
        availability = 100 if len(platforms) >= 2 else (50 if platforms else 0)
        if selected:
            cost = max(0, 100 - min(100, selected["price_usd"] * 4))
            evidence = _evidence_score(selected)
            moq = _moq_score(selected)
            shipping = _shipping_score(selected)
            retail_currency = product.get("currency")
            retail = product.get("price")
            retail_usd = (
                retail * CURRENCY_TO_USD[retail_currency]
                if isinstance(retail, (int, float)) and retail_currency in CURRENCY_TO_USD
                else None
            )
            margin = max(0, min(100, ((retail_usd - selected["price_usd"]) / retail_usd) * 100)) if retail_usd else 40
            rejection = None
            reasoning = f"Selected credible {selected['supplier_platform']} cost of ${selected['price_usd']:.2f} USD."
        else:
            cost, evidence, moq, shipping, margin = 0, 0, 0, 0, 0
            rejection = "No supplier offer with a valid positive price and supported currency."
            reasoning = "No credible supplier price was available."
        score = round(
            0.30 * viral + 0.18 * cost + 0.15 * evidence + 0.10 * moq
            + 0.08 * shipping + 0.12 * margin + 0.07 * availability,
            1,
        )
        result = dict(product)
        result.update({
            "candidate_index": candidate_index,
            "final_score": score,
            "selected_supplier_offer": selected,
            "supplier_price_reasoning": reasoning,
            "rejection_reason": rejection,
            "ranking_method": "deterministic_fallback",
        })
        ranked.append(result)
    return sorted(ranked, key=lambda item: (-item["final_score"], item["candidate_index"]))


def final_rank_products(
    niche: str, products: list[dict], supplier_data: list[dict]
) -> tuple[list[dict], str | None]:
    """Perform a separate price-aware final ranking, with deterministic fallback."""
    normalized_products, normalized_offers = build_final_ranking_input(products, supplier_data)
    fallback = deterministic_final_ranking(products, normalized_offers)
    if not products:
        return [], None

    prompt = f"""
Rank these normalized dropshipping candidates using viral potential, lowest credible
supplier cost, evidence quality, MOQ, shipping practicality, potential margin, and
supplier availability across Alibaba and AliExpress. Do not invent facts. Unsupported
currencies and offers whose price_usd is null are not credible prices.

Niche: {niche}
Normalized candidates: {json.dumps(normalized_products, separators=(',', ':'))}
Normalized supplier offers: {json.dumps(normalized_offers, separators=(',', ':'))}

Return JSON only:
{{"ranked":[{{"candidate_index":0,"final_score":0,"selected_offer_index":0,
"supplier_price_reasoning":"short reason","rejection_reason":null}}]}}
Include every candidate exactly once. Scores must be 0-100. selected_offer_index must
belong to that candidate and have a non-null price_usd, or be null. Give a rejection
reason whenever no credible supplier offer is selected.
"""
    errors = []
    offer_lookup = {
        (offer["candidate_index"], offer["offer_index"]): offer for offer in normalized_offers
    }
    for settings in get_ai_providers():
        try:
            response = requests.post(
                settings["api_url"],
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "authorization": f"Bearer {settings['api_key']}",
                },
                json=build_ai_payload(settings["api_url"], settings["model"], prompt, temperature=0.2),
                timeout=get_ai_timeout(settings["api_url"]),
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
            items = json.loads(content).get("ranked", [])
            if len(items) != len(products):
                raise ValueError("AI did not return every candidate")
            seen = set()
            ranked = []
            for item in items:
                index = item.get("candidate_index")
                if not isinstance(index, int) or not 0 <= index < len(products) or index in seen:
                    raise ValueError("AI returned an invalid candidate index")
                seen.add(index)
                offer_index = item.get("selected_offer_index")
                selected = offer_lookup.get((index, offer_index)) if isinstance(offer_index, int) else None
                if selected and selected.get("price_usd") is None:
                    selected = None
                rejection = str(item.get("rejection_reason") or "")[:300] or None
                if selected is None and rejection is None:
                    raise ValueError("AI omitted rejection reason for an unselected candidate")
                result = dict(products[index])
                final_score = float(item.get("final_score", 0))
                if not math.isfinite(final_score):
                    raise ValueError("AI returned a non-finite final score")
                result.update({
                    "candidate_index": index,
                    "final_score": max(0, min(100, final_score)),
                    "selected_supplier_offer": selected,
                    "supplier_price_reasoning": str(item.get("supplier_price_reasoning") or "")[:500],
                    "rejection_reason": rejection,
                    "ranking_method": "ai",
                })
                ranked.append(result)
            return sorted(ranked, key=lambda item: item["final_score"], reverse=True), None
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            errors.append(f"{settings['name']} final ranking failed")
            logging.warning("Final AI ranking failed: %s", error)

    warning = (
        f"{'; '.join(errors)}. Used deterministic supplier-aware final ranking."
        if errors else "No AI provider is configured. Used deterministic supplier-aware final ranking."
    )
    return fallback, warning

