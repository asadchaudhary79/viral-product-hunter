import json
import os
import unittest
from unittest.mock import Mock, patch

import requests

os.environ.setdefault("DECODO_AUTH_TOKEN", "test-token")

from app import decodo, ranking, suppliers
from app.api import hunt_products
from app.schemas import HuntRequest


class ProductExtractionTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "source": "Amazon Search",
            "data": {
                "results": [{
                    "status_code": 200,
                    "content": json.dumps({
                        "results": {
                            "query": "pet gadgets",
                            "organic": [{
                                "title": "Automatic Rolling Pet Ball",
                                "price": 19.99,
                                "currency": "USD",
                                "rating": 4.6,
                                "reviews_count": 2100,
                                "url": "/dp/example",
                                "image_url": "https://example.com/ball.jpg",
                            }],
                        }
                    }),
                }]
            },
        }

    def test_trim_preserves_parsed_products(self):
        trimmed = decodo.trim_decodo_result(self.result)
        self.assertIsInstance(trimmed["data"]["results"][0]["content"], dict)

        products = decodo.extract_products([trimmed])
        self.assertEqual(products[0]["product"], "Automatic Rolling Pet Ball")
        self.assertEqual(products[0]["price"], 19.99)
        self.assertEqual(products[0]["evidence"]["reviews"], 2100.0)
        self.assertGreater(products[0]["viral_score"], 0)

    def test_summary_counts_products_and_item_status(self):
        summary = decodo.summarize_decodo_result(decodo.trim_decodo_result(self.result))
        self.assertEqual(summary["result_count"], 1)
        self.assertEqual(summary["status_code"], 200)
        self.assertEqual(summary["preview"], "Automatic Rolling Pet Ball")

    def test_unauthorized_ai_falls_back_to_local_scores(self):
        products = decodo.extract_products([decodo.trim_decodo_result(self.result)])
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")

        with patch.dict(os.environ, {"KIMI_API_KEY": "invalid-key"}), patch("app.ranking.requests.post", return_value=response):
            ranked, warning = ranking.analyze_with_ai_model("pet gadgets", products)

        self.assertEqual(ranked, products)
        self.assertIn("evidence-based", warning)
        self.assertIn("authentication failed (401)", warning)

    def test_extracts_tiktok_and_google_product_records(self):
        results = [
            {
                "source": "TikTok Shop Search",
                "data": {"results": [{"content": {
                    "results": [{
                        "product_name": "Interactive Cat Ball",
                        "sale_price": "$12.50",
                        "sold_count": "8,400 sold",
                        "product_link": "https://shop.tiktok.com/cat-ball",
                        "product_image": "https://example.com/cat-ball.webp",
                    }]
                }}]},
            },
            {
                "source": "Google Search 1",
                "data": {"results": [{"content": json.dumps({
                    "results": {
                        "query": "viral pet products",
                        "organic": [],
                        "shopping_results": [{
                            "title": "Pet Grooming Vacuum Tool",
                            "price": "$29.99",
                            "url": "https://example.com/grooming-tool",
                            "image": "https://example.com/grooming-tool.jpg",
                        }],
                    }
                })}]},
            },
        ]

        trimmed = [decodo.trim_decodo_result(result) for result in results]
        products = decodo.extract_products(trimmed)
        sources = {product["source"] for product in products}

        self.assertIn("TikTok Shop Search", sources)
        self.assertIn("Google Search 1", sources)
        self.assertEqual(len(products), 2)

    def test_ai_quota_error_is_explained(self):
        products = decodo.extract_products([decodo.trim_decodo_result(self.result)])
        response = Mock()
        error = requests.HTTPError("429 Too Many Requests")
        error.response = Mock(status_code=429)
        response.raise_for_status.side_effect = error

        with patch.dict(os.environ, {"KIMI_API_KEY": "valid-but-empty-key"}), patch("app.ranking.requests.post", return_value=response):
            ranked, warning = ranking.analyze_with_ai_model("pet gadgets", products)

        self.assertEqual(ranked, products)
        self.assertIn("quota or balance is unavailable (429)", warning)

    def test_current_google_parser_envelope_is_unwrapped(self):
        result = {
            "source": "Google Search 1",
            "data": {"results": [{"status_code": 200, "content": {
                "results": {
                    "parse_status_code": 12000,
                    "results": {
                        "organic": [{
                            "title": "Portable Paw Cleaner",
                            "price_lower": 14.0,
                            "price_upper": 22.0,
                            "currency": "USD",
                            "url": "https://example.com/paw-cleaner",
                        }],
                        "related_questions": [],
                    },
                },
            }}]},
        }

        trimmed = decodo.trim_decodo_result(result)
        content = trimmed["data"]["results"][0]["content"]
        self.assertEqual(content["organic"][0]["title"], "Portable Paw Cleaner")
        self.assertEqual(content["parse_status_code"], 12000)
        self.assertEqual(decodo.extract_products([trimmed])[0]["product"], "Portable Paw Cleaner")
        self.assertEqual(decodo.summarize_decodo_result(trimmed)["parse_status_code"], 12000)

    def test_google_object_sections_are_preserved_without_slicing(self):
        related_questions = {
            "items": [{"question": "What pet gadgets are trending?"}],
        }
        result = {
            "source": "Google Search 1",
            "data": {"results": [{"content": {
                "results": {
                    "organic": [],
                    "related_questions": related_questions,
                },
            }}]},
        }

        trimmed = decodo.trim_decodo_result(result)

        self.assertEqual(
            trimmed["data"]["results"][0]["content"]["related_questions"],
            related_questions,
        )


class SupplierValidationTests(unittest.TestCase):
    def setUp(self):
        self.reference = {"rank": 1, "product": "Portable Paw Cleaner"}

    def test_supplier_payloads_use_standard_premium_html_requests(self):
        payloads = suppliers.build_supplier_payloads("paw cleaner & brush")

        self.assertEqual(len(payloads), 2)
        self.assertEqual({item["platform"] for item in payloads}, {"Alibaba", "AliExpress"})
        for item in payloads:
            self.assertEqual(item["payload"]["proxy_pool"], "premium")
            self.assertEqual(item["payload"]["headless"], "html")
            self.assertNotIn("target", item["payload"])
            self.assertNotIn("parse", item["payload"])
            self.assertNotIn("custom_parsing", item["payload"])
        self.assertIn("paw+cleaner+%26+brush", payloads[0]["payload"]["url"])

    def test_normalizes_price_ranges_currencies_and_evidence(self):
        parsed = {"results": {"products": [{
            "title": "Wholesale Paw Cleaner",
            "price": "US $1.25 - 2.80",
            "min_order_quantity": "50 pieces",
            "shipping": "Ships in 7 days",
            "url": "//www.alibaba.com/product-detail/example.html",
            "rating": "4.8",
            "orders": "1,240 sold",
            "reviews": "318 reviews",
            "supplier_evidence": "Verified supplier",
        }]}}

        offer = suppliers.normalize_supplier_offer("Alibaba", self.reference, parsed)[0]

        self.assertIsNone(offer["unit_price"])
        self.assertEqual(offer["price_range"], {"min": 1.25, "max": 2.8})
        self.assertEqual(offer["currency"], "USD")
        self.assertEqual(offer["min_order_quantity"], "50 pieces")
        self.assertEqual(offer["rating"], 4.8)
        self.assertEqual(offer["orders"], 1240.0)
        self.assertEqual(offer["reviews"], 318.0)
        self.assertTrue(offer["supplier_url"].startswith("https://"))

    def test_normalizes_single_price_and_missing_fields(self):
        parsed = {"results": {"products": [{
            "title": "AliExpress Paw Cleaner",
            "price": "EUR 6.40",
            "url": "/item/100.html",
        }]}}

        offer = suppliers.normalize_supplier_offer("AliExpress", self.reference, parsed)[0]

        self.assertEqual(offer["unit_price"], 6.4)
        self.assertIsNone(offer["price_range"])
        self.assertEqual(offer["currency"], "EUR")
        self.assertIsNone(offer["min_order_quantity"])
        self.assertIsNone(offer["shipping_info"])
        self.assertIsNone(offer["rating"])

    def test_discards_empty_parsed_cards(self):
        parsed = {"results": {"products": [{
            "title": None,
            "price": None,
            "url": "/item/100.html",
        }]}}

        offers = suppliers.normalize_supplier_offer("AliExpress", self.reference, parsed)

        self.assertEqual(offers, [])

    def test_reports_empty_extraction_without_marking_request_failed(self):
        products = [{"product": "Candidate"}]

        def fake_scrape(source, _payload):
            return {"source": source, "data": {"results": [{"content": {
                "results": {"products": [{"title": None, "price": None}]},
            }}]}}

        with patch("app.suppliers.scrape_with_decodo_payload", side_effect=fake_scrape):
            result = suppliers.validate_suppliers_for_products(products)

        supplier_results = result["supplier_data"][0]["supplier_results"]
        self.assertEqual(result["supplier_summary"]["failed_supplier_requests"], 0)
        self.assertEqual(result["supplier_summary"]["empty_supplier_requests"], 2)
        self.assertTrue(all(item["offers"] == [] for item in supplier_results))
        self.assertTrue(all("warning" in item for item in supplier_results))

    def test_parses_rendered_marketplace_html_without_css_selectors(self):
        html = """
        <a class="changed-random-class" href="//www.aliexpress.us/item/123.html">
          <img alt="Portable Dog Paw Cleaner" />
          <span>US $</span><span>6</span><span>.</span><span>49</span>
          <span>327 sold</span><span>Free shipping</span>
        </a>
        """

        offers = suppliers.normalize_supplier_offer("AliExpress", self.reference, html)

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["supplier_title"], "Portable Dog Paw Cleaner")
        self.assertEqual(offers[0]["unit_price"], 6.49)
        self.assertEqual(offers[0]["orders"], 327.0)
        self.assertEqual(offers[0]["shipping_info"], "Free shipping")

    def test_top_ten_make_twenty_requests_and_keep_platforms_separate(self):
        products = [{"product": f"Candidate {index}"} for index in range(12)]

        def fake_scrape(source, payload):
            platform = "Alibaba" if source == "Alibaba Search" else "AliExpress"
            price = "$1.00 - $2.00" if platform == "Alibaba" else "$8.00"
            return {"source": source, "data": {"results": [{"content": {
                "results": {"products": [{
                    "title": f"{platform} listing",
                    "price": price,
                    "url": payload["url"],
                }]},
            }}]}}

        with patch("app.suppliers.scrape_with_decodo_payload", side_effect=fake_scrape) as scrape:
            result = suppliers.validate_suppliers_for_products(products)

        self.assertEqual(scrape.call_count, 20)
        self.assertEqual(result["supplier_summary"]["products_validated"], 10)
        self.assertEqual(result["supplier_summary"]["total_supplier_requests"], 20)
        self.assertEqual(result["supplier_summary"]["offers_by_platform"], {
            "Alibaba": 10,
            "AliExpress": 10,
        })
        first = result["supplier_data"][0]["supplier_results"]
        self.assertEqual([item["supplier_platform"] for item in first], ["Alibaba", "AliExpress"])
        self.assertEqual(first[0]["offers"][0]["price_range"], {"min": 1.0, "max": 2.0})
        self.assertEqual(first[1]["offers"][0]["unit_price"], 8.0)

    def test_partial_failure_preserves_other_source_and_parsed_json(self):
        products = [{"product": "Candidate"}]

        def fake_scrape(source, _payload):
            if source == "Alibaba Search":
                return {"source": source, "error": "marketplace timeout"}
            return {"source": source, "data": {"results": [{"content": json.dumps({
                "results": {"products": [{"title": "Working listing", "price": "GBP 4.50"}]}
            })}]}}

        with patch("app.suppliers.scrape_with_decodo_payload", side_effect=fake_scrape):
            result = suppliers.validate_suppliers_for_products(products)

        supplier_results = result["supplier_data"][0]["supplier_results"]
        self.assertEqual(result["supplier_summary"]["failed_supplier_requests"], 1)
        self.assertEqual(supplier_results[0]["error"], "marketplace timeout")
        self.assertIsNone(supplier_results[0]["supplier_data"])
        self.assertIsInstance(supplier_results[1]["supplier_data"], dict)
        self.assertEqual(supplier_results[1]["offers"][0]["currency"], "GBP")

    def test_hunt_uses_ai_ranked_top_ten_as_initial_products(self):
        ranked = [{"product": f"Ranked {index}", "viral_score": 100 - index} for index in range(12)]
        validation = {"supplier_data": [], "supplier_summary": {"products_validated": 10}}

        with patch("app.discovery.scrape_with_decodo", return_value="[]"), \
                patch("app.discovery.extract_products", return_value=[{"product": "candidate"}]), \
                patch("app.discovery.analyze_with_ai_model", return_value=(ranked, None)), \
                patch("app.api.final_rank_products", return_value=(ranked[:10], None)), \
                patch("app.api.validate_suppliers_for_products", return_value=validation) as validate:
            response = hunt_products(HuntRequest(niche="pets"))

        passed_products = validate.call_args.args[0]
        self.assertEqual(len(passed_products), 10)
        self.assertEqual(response["initial_products"], ranked[:10])


class FinalRankingPipelineTests(unittest.TestCase):
    def product(self, name="Paw Cleaner", viral_score=80):
        return {
            "product": name,
            "viral_score": viral_score,
            "price": 25.0,
            "currency": "USD",
            "source": "Amazon Search",
            "evidence": {"rating": 4.7, "reviews": 500},
        }

    def supplier_group(self, product, results):
        return {
            "product_reference": {"rank": 1, "candidate_index": 0, "product": product["product"]},
            "product_name": product["product"],
            "supplier_results": results,
        }

    def offer(self, platform="Alibaba", price=3.0, currency="USD"):
        return {
            "product_reference": {"rank": 1, "candidate_index": 0, "product": "Paw Cleaner"},
            "supplier_platform": platform,
            "supplier_title": f"{platform} Paw Cleaner",
            "unit_price": price,
            "price_range": None,
            "currency": currency,
            "min_order_quantity": "1 piece",
            "shipping_info": "Free shipping, delivery in 7 days",
            "supplier_url": f"https://example.com/{platform.lower()}",
            "rating": 4.8,
            "orders": 1200,
            "reviews": 300,
            "supplier_evidence": "Verified supplier",
            "provenance": {"search_url": f"https://search.example/{platform.lower()}"},
        }

    def test_discovery_to_final_ranking_end_to_end(self):
        product = self.product()
        validation = {
            "supplier_data": [self.supplier_group(product, [
                {"source": "Alibaba Search", "supplier_platform": "Alibaba", "offers": [self.offer()]},
                {"source": "AliExpress Search", "supplier_platform": "AliExpress", "offers": [self.offer("AliExpress", 5.0)]},
            ])],
            "supplier_summary": {"products_validated": 1},
        }
        with patch("app.discovery.scrape_with_decodo", return_value="[]"), \
                patch("app.discovery.extract_products", return_value=[product]), \
                patch("app.discovery.analyze_with_ai_model", return_value=([product], None)), \
                patch("app.api.validate_suppliers_for_products", return_value=validation), \
                patch("app.ranking.get_ai_providers", return_value=[]):
            response = hunt_products(HuntRequest(niche="pets"))

        self.assertEqual(response["initial_products"][0]["product"], "Paw Cleaner")
        self.assertEqual(response["final_products"][0]["ranking_method"], "deterministic_fallback")
        self.assertEqual(response["final_products"][0]["selected_supplier_offer"]["candidate_index"], 0)
        self.assertEqual(set(response), {
            "niche", "message", "initial_products", "final_products", "supplier_summary",
            "supplier_data", "discovery_summary", "discovery_data", "ranking_warnings",
        })

    def test_missing_offers_has_rejection_reason(self):
        product = self.product()
        with patch("app.ranking.get_ai_providers", return_value=[]):
            ranked, warning = ranking.final_rank_products(
                "pets", [product], [self.supplier_group(product, [])]
            )

        self.assertIsNone(ranked[0]["selected_supplier_offer"])
        self.assertIn("No supplier offer", ranked[0]["rejection_reason"])
        self.assertIn("deterministic", warning)

    def test_one_marketplace_failure_still_ranks_working_offer(self):
        product = self.product()
        group = self.supplier_group(product, [
            {"source": "Alibaba Search", "supplier_platform": "Alibaba", "offers": [], "error": "timeout"},
            {"source": "AliExpress Search", "supplier_platform": "AliExpress", "offers": [self.offer("AliExpress", 4.0)]},
        ])
        with patch("app.ranking.get_ai_providers", return_value=[]):
            ranked, _ = ranking.final_rank_products("pets", [product], [group])

        self.assertEqual(ranked[0]["selected_supplier_offer"]["supplier_platform"], "AliExpress")

    def test_invalid_currency_and_price_are_not_credible(self):
        product = self.product()
        invalid_currency = self.offer(currency="DOGE")
        invalid_price = self.offer("AliExpress", -2.0)
        group = self.supplier_group(product, [
            {"source": "Alibaba Search", "supplier_platform": "Alibaba", "offers": [invalid_currency]},
            {"source": "AliExpress Search", "supplier_platform": "AliExpress", "offers": [invalid_price]},
        ])
        normalized_products, offers = ranking.build_final_ranking_input([product], [group])

        self.assertEqual(normalized_products[0]["candidate_index"], 0)
        self.assertTrue(all(offer["price_usd"] is None for offer in offers))
        with patch("app.ranking.get_ai_providers", return_value=[]):
            ranked, _ = ranking.final_rank_products("pets", [product], [group])
        self.assertIsNotNone(ranked[0]["rejection_reason"])

    def test_ai_failure_uses_deterministic_fallback(self):
        product = self.product()
        group = self.supplier_group(product, [{
            "source": "Alibaba Search", "supplier_platform": "Alibaba", "offers": [self.offer()]
        }])
        response = Mock()
        response.raise_for_status.side_effect = requests.Timeout("AI timeout")
        settings = {"name": "Test AI", "api_key": "key", "api_url": "https://ai.test", "model": "test"}
        with patch("app.ranking.get_ai_providers", return_value=[settings]), \
                patch("app.ranking.requests.post", return_value=response):
            ranked, warning = ranking.final_rank_products("pets", [product], [group])

        self.assertEqual(ranked[0]["ranking_method"], "deterministic_fallback")
        self.assertIn("Test AI final ranking failed", warning)

    def test_selected_offer_preserves_supplier_provenance(self):
        product = self.product()
        group = self.supplier_group(product, [{
            "source": "Alibaba Search", "supplier_platform": "Alibaba", "offers": [self.offer()]
        }])
        with patch("app.ranking.get_ai_providers", return_value=[]):
            ranked, _ = ranking.final_rank_products("pets", [product], [group])

        provenance = ranked[0]["selected_supplier_offer"]["provenance"]
        self.assertEqual(provenance["source"], "Alibaba Search")
        self.assertEqual(provenance["platform"], "Alibaba")
        self.assertEqual(provenance["search_url"], "https://search.example/alibaba")


if __name__ == "__main__":
    unittest.main()
