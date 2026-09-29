"""Request bodies for the product-hunt API."""
from pydantic import BaseModel, Field


class HuntBrief(BaseModel):
    """What the seller wants the hunt to optimize for."""

    goal: str = "dropshipping"
    audience: str = ""
    price_max: float | None = 50
    problem: str = ""
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class HuntRequest(BaseModel):
    niche: str
    brief: HuntBrief = Field(default_factory=HuntBrief)


class SourceRequest(BaseModel):
    niche: str
    initial_products: list[dict]
    brief: HuntBrief = Field(default_factory=HuntBrief)
