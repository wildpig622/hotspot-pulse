import json
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts import collect


ROOT = Path(__file__).resolve().parents[1]


class MarketSensingScopeTests(unittest.TestCase):
    def test_scope_and_routes_are_configured_without_fixed_matrix_counts(self):
        scope = json.loads((ROOT / "config" / "monitoring-scope.json").read_text(encoding="utf-8"))
        topic_keys = [topic["key"] for topic in scope["topics"]]
        route_keys = [route["key"] for route in scope["query_routes"]]
        self.assertEqual(topic_keys, [topic["key"] for topic in collect.FEED_TOPICS])
        self.assertEqual(route_keys, [route["key"] for route in collect.QUERY_ROUTES])
        self.assertEqual(len(topic_keys), len(set(topic_keys)))
        self.assertEqual(len(route_keys), len(set(route_keys)))
        self.assertIn("exam", topic_keys)
        self.assertIn("conference", topic_keys)
        self.assertIn("holiday", topic_keys)

    def test_exam_terms_cover_the_phase_one_demand_signals(self):
        terms = set(next(topic for topic in collect.FEED_TOPICS if topic["key"] == "exam")["terms"])
        for term in ("考研", "国考", "省考", "事业编", "教资", "高考", "中考", "职业资格考试"):
            self.assertIn(term, terms)
            self.assertIn(term, collect.KEYWORDS)

    def test_source_catalog_is_https_and_explicit_about_validation_status(self):
        catalog = json.loads((ROOT / "config" / "official-sources.json").read_text(encoding="utf-8"))
        allowed = {"verified_read_only", "official_reference_only", "direct_read_blocked", "proposed_not_verified"}
        rows = list(catalog["national_sources"])
        for city in ("西安市", "济南市", "天津市"):
            rows.extend(catalog["city_sources"][city])
            self.assertEqual({row["topic"] for row in catalog["city_sources"][city]}, {"exam", "holiday", "conference"})
        for row in rows:
            parsed = urlparse(row["source_url"])
            self.assertEqual(parsed.scheme, "https", row["source_id"])
            self.assertTrue(parsed.hostname, row["source_id"])
            self.assertIn(row["verification_status"], allowed, row["source_id"])
            if row["verification_status"] == "verified_read_only":
                self.assertRegex(row["verified_on"] or "", r"^\d{4}-\d{2}-\d{2}$")

    def test_route_catalog_drives_the_query_shape(self):
        city = {"city_name": "西安市", "city_slug": "xian", "aliases": ["西安"]}
        topic = next(topic for topic in collect.FEED_TOPICS if topic["key"] == "exam")
        urls = [collect.build_feed_url(city, date(2026, 11, 26), topic, route=route) for route in collect.QUERY_ROUTES]
        self.assertEqual(len(urls), len(collect.QUERY_ROUTES))
        queries = [parse_qs(urlparse(url).query)["q"][0] for url in urls]
        self.assertTrue(any("考研" in query for query in queries))
        self.assertTrue(any("after:2026-05-30" in query for query in queries))
        self.assertTrue(any("after:2026-10-27" in query for query in queries))
        self.assertTrue(any("2026 OR 2027" in query for query in queries))


if __name__ == "__main__":
    unittest.main()
