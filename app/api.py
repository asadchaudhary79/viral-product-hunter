"""FastAPI backend and UI for the Viral Product Hunter app.

Runs on port 8000, serves the web UI, and exposes JSON endpoints.
"""
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.brief import brief_as_dict
from app.config import BACKEND_HOST, BACKEND_PORT
from app.discovery import run_discovery
from app.ranking import final_rank_products
from app.schemas import HuntRequest, SourceRequest
from app.suppliers import validate_suppliers_for_products

UI_DIR = Path(__file__).resolve().parent.parent / "ui"

app = FastAPI(title="Viral Product Hunter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=UI_DIR), name="static")


def run_sourcing_and_final_ranking(niche: str, initial_products: list[dict], brief=None) -> dict:
    """Source the initial top ten and run the independent final ranking stage."""
    brief_data = brief_as_dict(brief)
    supplier_validation = validate_suppliers_for_products(initial_products[:10])
    final_products, final_warning = final_rank_products(
        niche, initial_products[:10], supplier_validation["supplier_data"], brief_data
    )
    warnings = [final_warning] if final_warning else []
    for group in supplier_validation["supplier_data"]:
        for result in group.get("supplier_results", []):
            issue = result.get("error") or result.get("warning")
            if issue:
                warnings.append(
                    f"{group['product_name']} / {result['supplier_platform']}: {issue}"
                )
    return {
        "final_products": final_products,
        "supplier_summary": supplier_validation["supplier_summary"],
        "supplier_data": supplier_validation["supplier_data"],
        "ranking_warnings": warnings,
    }


@app.get("/")
def serve_ui():
    return FileResponse(UI_DIR / "index.html")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/discover")
def discover_products(request: HuntRequest):
    return run_discovery(request.niche, request.brief)


@app.post("/source")
def source_products(request: SourceRequest):
    return run_sourcing_and_final_ranking(
        request.niche, request.initial_products, request.brief
    )


@app.post("/hunt")
def hunt_products(request: HuntRequest):
    """Run discovery, initial ranking, supplier sourcing, and final ranking."""
    discovery = run_discovery(request.niche, request.brief)
    sourcing = run_sourcing_and_final_ranking(
        request.niche, discovery["initial_products"], request.brief
    )
    return {
        "niche": request.niche,
        "brief": brief_as_dict(request.brief),
        "message": f"Discovery, sourcing, and final ranking completed for '{request.niche}'.",
        "initial_products": discovery["initial_products"],
        "final_products": sourcing["final_products"],
        "supplier_summary": sourcing["supplier_summary"],
        "supplier_data": sourcing["supplier_data"],
        "discovery_summary": discovery["discovery_summary"],
        "discovery_data": discovery["discovery_data"],
        "ranking_warnings": discovery["ranking_warnings"] + sourcing["ranking_warnings"],
    }


if __name__ == "__main__":
    uvicorn.run("app.api:app", host=BACKEND_HOST, port=BACKEND_PORT, reload=True)
