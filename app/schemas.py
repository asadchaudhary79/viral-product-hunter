"""Request bodies for the product-hunt API."""
from pydantic import BaseModel


class HuntRequest(BaseModel):
    niche: str


class SourceRequest(BaseModel):
    niche: str
    initial_products: list[dict]
