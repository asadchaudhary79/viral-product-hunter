"""Helpers that turn a hunt brief into search queries and ranking context."""


def brief_as_dict(brief) -> dict:
    if brief is None:
        return {}
    if isinstance(brief, dict):
        return brief
    if hasattr(brief, "model_dump"):
        return brief.model_dump()
    return dict(brief)


def price_label(price_max) -> str:
    if price_max is None:
        return "any price"
    try:
        value = float(price_max)
    except (TypeError, ValueError):
        return "any price"
    if value <= 0:
        return "any price"
    return f"under ${int(value) if value == int(value) else value}"


def format_brief_for_prompt(niche: str, brief) -> str:
    data = brief_as_dict(brief)
    preferences = ", ".join(data.get("preferences") or []) or "none specified"
    avoid = ", ".join(data.get("avoid") or []) or "none specified"
    return "\n".join([
        f"Niche: {niche}",
        f"Selling goal: {data.get('goal') or 'dropshipping'}",
        f"Audience: {data.get('audience') or 'general online buyers'}",
        f"Retail budget: {price_label(data.get('price_max'))}",
        f"Problem to solve: {data.get('problem') or 'any useful everyday problem'}",
        f"Prefer: {preferences}",
        f"Avoid: {avoid}",
    ])


def build_discovery_queries(niche: str, brief=None) -> list[str]:
    """Shape marketplace and search queries from the seller brief."""
    data = brief_as_dict(brief)
    goal = (data.get("goal") or "dropshipping").strip().lower()
    problem = (data.get("problem") or "").strip()
    audience = (data.get("audience") or "").strip()
    price = price_label(data.get("price_max"))
    preferences = [item.lower() for item in (data.get("preferences") or [])]

    queries = [
        f"viral {niche} products",
        f"best selling {niche} {price}",
        f"{niche} accessories {price}",
    ]

    if problem:
        queries.append(f"{niche} products that solve {problem}")
    else:
        queries.append(f"problem solving {niche} products")

    if "tiktok" in goal:
        queries.append(f"TikTok Shop viral {niche}")
        queries.append(f"TikTok {niche} gadgets")
    elif "amazon" in goal:
        queries.append(f"Amazon best selling {niche} {price}")
        queries.append(f"Amazon movers {niche} products")
    else:
        queries.append(f"TikTok {niche} gadgets")
        queries.append(f"dropshipping {niche} products {price}")

    if audience:
        queries.append(f"{niche} gifts for {audience}")

    if "lightweight" in preferences or "easy to ship" in preferences:
        queries.append(f"lightweight {niche} products easy to ship")
    if "demo" in " ".join(preferences) or "video" in " ".join(preferences):
        queries.append(f"{niche} products satisfying video demo")

    # Keep a stable short list for the scraper worker pool.
    unique = []
    seen = set()
    for query in queries:
        key = " ".join(query.lower().split())
        if key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique[:6]
