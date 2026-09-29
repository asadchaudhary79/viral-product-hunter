"""Streamlit frontend for the Viral Product Hunter API."""
import csv
import io
import json
import re

import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT = (10, 600)
EXPORT_COLUMNS = [
    "section",
    "niche",
    "rank",
    "product",
    "viral_score",
    "final_score",
    "retail_price",
    "currency",
    "source",
    "platform",
    "listing",
    "unit_price",
    "price_min",
    "price_max",
    "price_usd",
    "moq",
    "shipping",
    "rating",
    "reviews",
    "orders",
    "sales",
    "best_seller",
    "amazons_choice",
    "image",
    "product_link",
    "supplier_link",
    "supplier_evidence",
    "reason",
    "reasoning",
    "rejection",
    "ranking_method",
    "status",
    "message",
    "result_count",
    "status_code",
    "parse_status_code",
    "content_chars",
    "prices_found",
    "urls_found",
    "images_found",
    "captcha_or_robot_detected",
    "preview",
    "products_validated",
    "supplier_requests",
    "successful_requests",
    "failed_requests",
    "empty_requests",
]


def _text(value):
    """Flatten a cell so nested scraper values still fit in a CSV."""
    if value is None or value is False:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _row(**fields):
    return {column: _text(fields.get(column, "")) for column in EXPORT_COLUMNS}


def build_export_rows(results):
    """Turn one hunt response into rows covering every result section."""
    niche = results.get("niche") or ""
    rows = []

    for index, product in enumerate(results.get("initial_products") or []):
        evidence = product.get("evidence") or {}
        rows.append(_row(
            section="initial_ranking",
            niche=niche,
            rank=index + 1,
            product=product.get("product"),
            viral_score=product.get("viral_score"),
            retail_price=product.get("price"),
            currency=product.get("currency"),
            source=product.get("source"),
            rating=evidence.get("rating"),
            reviews=evidence.get("reviews"),
            sales=evidence.get("sales"),
            best_seller=evidence.get("best_seller"),
            amazons_choice=evidence.get("amazons_choice"),
            image=product.get("image"),
            product_link=product.get("url"),
            reason=product.get("reason"),
        ))

    summary = results.get("supplier_summary") or {}
    offers_by_platform = summary.get("offers_by_platform") or {}
    rows.append(_row(
        section="supplier_summary",
        niche=niche,
        products_validated=summary.get("products_validated"),
        supplier_requests=summary.get("total_supplier_requests"),
        successful_requests=summary.get("successful_supplier_requests"),
        failed_requests=summary.get("failed_supplier_requests"),
        empty_requests=summary.get("empty_supplier_requests"),
        message=json.dumps(offers_by_platform, ensure_ascii=False),
    ))

    for product_data in results.get("supplier_data") or []:
        reference = product_data.get("product_reference") or {}
        product_name = product_data.get("product_name")
        for supplier_result in product_data.get("supplier_results") or []:
            status = "error" if supplier_result.get("error") else (
                "warning" if supplier_result.get("warning") else "ok"
            )
            message = supplier_result.get("error") or supplier_result.get("warning") or ""
            offers = supplier_result.get("offers") or []
            if not offers:
                rows.append(_row(
                    section="supplier_offer",
                    niche=niche,
                    rank=reference.get("rank"),
                    product=product_name,
                    platform=supplier_result.get("supplier_platform"),
                    source=supplier_result.get("source"),
                    status=status,
                    message=message,
                ))
            for offer in offers:
                price_range = offer.get("price_range") or {}
                rows.append(_row(
                    section="supplier_offer",
                    niche=niche,
                    rank=reference.get("rank"),
                    product=product_name,
                    platform=offer.get("supplier_platform") or supplier_result.get("supplier_platform"),
                    source=supplier_result.get("source"),
                    listing=offer.get("supplier_title"),
                    unit_price=offer.get("unit_price"),
                    price_min=price_range.get("min"),
                    price_max=price_range.get("max"),
                    price_usd=offer.get("price_usd"),
                    currency=offer.get("currency"),
                    moq=offer.get("min_order_quantity"),
                    shipping=offer.get("shipping_info"),
                    rating=offer.get("rating"),
                    reviews=offer.get("reviews"),
                    orders=offer.get("orders"),
                    supplier_link=offer.get("supplier_url"),
                    supplier_evidence=offer.get("supplier_evidence"),
                    status=status,
                    message=message,
                ))

    for index, product in enumerate(results.get("final_products") or []):
        offer = product.get("selected_supplier_offer") or {}
        price_range = offer.get("price_range") or {}
        rows.append(_row(
            section="final_ranking",
            niche=niche,
            rank=index + 1,
            product=product.get("product"),
            viral_score=product.get("viral_score"),
            final_score=product.get("final_score"),
            retail_price=product.get("price"),
            currency=product.get("currency") or offer.get("currency"),
            source=product.get("source"),
            platform=offer.get("supplier_platform"),
            listing=offer.get("supplier_title"),
            unit_price=offer.get("unit_price"),
            price_min=price_range.get("min"),
            price_max=price_range.get("max"),
            price_usd=offer.get("price_usd"),
            moq=offer.get("min_order_quantity"),
            shipping=offer.get("shipping_info"),
            rating=offer.get("rating"),
            orders=offer.get("orders"),
            reviews=offer.get("reviews"),
            supplier_link=offer.get("supplier_url"),
            reasoning=product.get("supplier_price_reasoning"),
            rejection=product.get("rejection_reason"),
            ranking_method=product.get("ranking_method"),
        ))

    for source in results.get("discovery_summary") or []:
        rows.append(_row(
            section="discovery_source",
            niche=niche,
            source=source.get("source"),
            status="error" if source.get("error") else "ok",
            message=source.get("error") or "",
            result_count=source.get("result_count"),
            status_code=source.get("status_code"),
            parse_status_code=source.get("parse_status_code"),
            content_chars=source.get("content_chars"),
            prices_found=source.get("prices_found"),
            urls_found=source.get("urls_found"),
            images_found=source.get("images_found"),
            captcha_or_robot_detected=source.get("captcha_or_robot_detected"),
            preview=source.get("preview"),
        ))

    for warning in results.get("ranking_warnings") or []:
        rows.append(_row(section="warning", niche=niche, status="warning", message=warning))

    return rows


def rows_to_csv(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_filename(niche):
    slug = re.sub(r"[^a-z0-9]+", "-", (niche or "hunt").lower()).strip("-") or "hunt"
    return f"{slug}-viral-product-hunter.csv"

st.set_page_config(page_title="Viral Product Hunter AI", layout="wide")
st.title("Viral Product Hunter AI")

if "hunt_results" not in st.session_state:
    st.session_state.hunt_results = None

niche = st.text_input("Enter a product niche:", value="pet gadgets")

if st.button("Hunt Products", type="primary"):
    st.session_state.hunt_results = None
    try:
        with st.status("Discovering products...", expanded=True) as status:
            st.write("Scraping and normalizing discovery sources")
            discovery_response = requests.post(
                f"{API_URL}/discover", json={"niche": niche}, timeout=REQUEST_TIMEOUT
            )
            discovery_response.raise_for_status()
            results = discovery_response.json()
            st.write(f"Initial ranking complete: {len(results.get('initial_products', []))} candidates")
            status.update(label="Sourcing Alibaba and AliExpress offers...", state="running")
            sourcing_response = requests.post(
                f"{API_URL}/source",
                json={"niche": niche, "initial_products": results.get("initial_products", [])},
                timeout=REQUEST_TIMEOUT,
            )
            sourcing_response.raise_for_status()
            sourcing = sourcing_response.json()
            results.update(sourcing)
            results["niche"] = niche
            results["ranking_warnings"] = (
                discovery_response.json().get("ranking_warnings", [])
                + sourcing.get("ranking_warnings", [])
            )
            st.session_state.hunt_results = results
            status.update(label="Discovery, sourcing, and final ranking complete", state="complete")
    except requests.exceptions.RequestException as error:
        st.error(f"Failed to connect to the backend: {error}")
        st.info(f"Make sure the FastAPI backend is running at {API_URL}")

results = st.session_state.hunt_results
if results:
    for warning in results.get("ranking_warnings", []):
        st.warning(warning)

    st.download_button(
        "Export all data (CSV)",
        data=rows_to_csv(build_export_rows(results)).encode("utf-8-sig"),
        file_name=export_filename(results.get("niche")),
        mime="text/csv",
    )

    st.subheader("1. Initial Viral Ranking")
    initial_rows = [{
        "Rank": index + 1,
        "Product": product.get("product"),
        "Viral score": product.get("viral_score"),
        "Retail price": product.get("price"),
        "Currency": product.get("currency"),
        "Source": product.get("source"),
        "Product link": product.get("url"),
    } for index, product in enumerate(results.get("initial_products", []))]
    st.dataframe(initial_rows, hide_index=True, use_container_width=True, column_config={
        "Product link": st.column_config.LinkColumn(),
    })

    st.subheader("2. Supplier Sourcing")
    summary = results.get("supplier_summary", {})
    columns = st.columns(5)
    columns[0].metric("Products", summary.get("products_validated", 0))
    columns[1].metric("Requests", summary.get("total_supplier_requests", 0))
    columns[2].metric("Successful", summary.get("successful_supplier_requests", 0))
    columns[3].metric("Failed", summary.get("failed_supplier_requests", 0))
    columns[4].metric("Empty pages", summary.get("empty_supplier_requests", 0))

    for product_data in results.get("supplier_data", []):
        with st.expander(product_data.get("product_name", "Unknown product")):
            offer_rows = []
            for supplier_result in product_data.get("supplier_results", []):
                if supplier_result.get("error"):
                    st.warning(f"{supplier_result.get('supplier_platform')}: {supplier_result['error']}")
                elif supplier_result.get("warning"):
                    st.warning(f"{supplier_result.get('supplier_platform')}: {supplier_result['warning']}")
                for offer in supplier_result.get("offers", []):
                    price = offer.get("unit_price")
                    if offer.get("price_range"):
                        price = f"{offer['price_range']['min']} - {offer['price_range']['max']}"
                    offer_rows.append({
                        "Platform": offer.get("supplier_platform"),
                        "Listing": offer.get("supplier_title"),
                        "Price": price,
                        "Currency": offer.get("currency"),
                        "MOQ": offer.get("min_order_quantity"),
                        "Shipping": offer.get("shipping_info"),
                        "Rating": offer.get("rating"),
                        "Orders": offer.get("orders"),
                        "Supplier link": offer.get("supplier_url"),
                    })
            if offer_rows:
                st.dataframe(offer_rows, hide_index=True, use_container_width=True, column_config={
                    "Supplier link": st.column_config.LinkColumn(),
                })
            else:
                st.caption("No usable supplier offers found.")

    st.subheader("3. Final Supplier-Aware Ranking")
    final_rows = []
    for index, product in enumerate(results.get("final_products", [])):
        offer = product.get("selected_supplier_offer") or {}
        final_rows.append({
            "Rank": index + 1,
            "Product": product.get("product"),
            "Final score": product.get("final_score"),
            "Supplier": offer.get("supplier_platform"),
            "Supplier cost (USD)": offer.get("price_usd"),
            "MOQ": offer.get("min_order_quantity"),
            "Reasoning": product.get("supplier_price_reasoning"),
            "Rejection": product.get("rejection_reason"),
            "Supplier link": offer.get("supplier_url"),
        })
    st.dataframe(final_rows, hide_index=True, use_container_width=True, column_config={
        "Supplier link": st.column_config.LinkColumn(),
    })

    with st.expander("Discovery source details"):
        st.dataframe(results.get("discovery_summary", []), hide_index=True, use_container_width=True)
        if st.checkbox("Show raw discovery data", key="show_raw_discovery"):
            st.json(results.get("discovery_data", []))
