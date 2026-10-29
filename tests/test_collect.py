import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect import build_candidate, classify_event, extract_event_date, merge_candidate, normalize_title, parse_feed


class CollectorTests(unittest.TestCase):
    def test_classifies_common_event_types(self):
        self.assertEqual(classify_event("2026杭州马拉松报名启动"), "sports")
        self.assertEqual(classify_event("西安国际茶博会"), "exhibition")
        self.assertEqual(classify_event("某某巡回演唱会西安站"), "concert")
        self.assertEqual(classify_event("城市灯会活动"), "festival")

    def test_extracts_explicit_chinese_date(self):
        result = extract_event_date("杭州马拉松将于2026年11月1日举行", today=date(2026, 10, 29))
        self.assertEqual(result["start_at"], "2026-11-01")
        self.assertEqual(result["date_confidence"], "explicit_year")
        self.assertEqual(result["date_precision"], "day")

    def test_extracts_date_range(self):
        result = extract_event_date("西部茶博会 2026年10月30日至2026年11月2日", today=date(2026, 10, 29))
        self.assertEqual(result["start_at"], "2026-10-30")
        self.assertEqual(result["end_at"], "2026-11-02")

    def test_undated_event_is_not_given_a_fake_date(self):
        result = extract_event_date("大型演唱会官宣，门票即将开售", today=date(2026, 10, 29))
        self.assertIsNone(result["start_at"])
        self.assertEqual(result["date_precision"], "tbd")

    def test_rss_parser_keeps_source_and_link(self):
        xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>2026杭州马拉松11月1日举行</title>
        <link>https://news.google.com/rss/articles/example</link>
        <description>赛事公告</description><pubDate>Wed, 28 Oct 2026 02:00:00 GMT</pubDate>
        <source url="https://example.gov.cn">官方新闻</source></item>
        </channel></rss>"""
        rows = parse_feed(xml)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["publisher"], "官方新闻")
        self.assertEqual(rows[0]["url"], "https://news.google.com/rss/articles/example")
        self.assertEqual(rows[0]["published_at"], "2026-10-28T02:00:00Z")

    def test_stable_normalization(self):
        self.assertEqual(normalize_title("杭州马拉松 - 杭州网"), normalize_title(" 杭州马拉松 "))

    def test_candidate_stays_pending(self):
        city = {"city_name": "杭州市", "city_slug": "hangzhou", "aliases": ["杭州"]}
        item = {
            "title": "2026杭州马拉松将于2026年11月1日举行 - 官方新闻",
            "description": "赛事公告",
            "url": "https://news.google.com/rss/articles/example",
            "published_at": "2026-10-28T02:00:00Z",
            "publisher": "官方新闻",
            "publisher_url": "https://example.gov.cn",
        }
        candidate = build_candidate(city, item, "2026-10-29T02:00:00Z", date(2026, 10, 29))
        self.assertEqual(candidate["review_status"], "pending")
        self.assertEqual(candidate["event_status"], "unknown")
        self.assertEqual(candidate["city_match"], "text_confirmed")
        self.assertEqual(candidate["start_at"], "2026-11-01")

    def test_merge_deduplicates_source_url_and_preserves_first_seen(self):
        first = {
            "event_id": "evt_same", "first_seen_at": "2026-10-28T00:00:00Z",
            "last_seen_at": "2026-10-28T00:00:00Z", "review_status": "pending",
            "event_status": "unknown",
            "sources": [{"source_url": "https://example.com/a", "observed_at": "2026-10-28T00:00:00Z"}],
            "start_at": "2026-11-01", "date_confidence": "inferred_year",
        }
        next_candidate = {
            "event_id": "evt_same", "first_seen_at": "2026-10-29T00:00:00Z",
            "last_seen_at": "2026-10-29T00:00:00Z", "review_status": "pending",
            "event_status": "unknown",
            "sources": [{"source_url": "https://example.com/a", "observed_at": "2026-10-29T00:00:00Z", "last_observed_at": "2026-10-29T00:00:00Z"}],
            "start_at": "2026-11-01", "date_confidence": "inferred_year",
        }
        merged = merge_candidate(first, next_candidate)
        self.assertEqual(merged["first_seen_at"], "2026-10-28T00:00:00Z")
        self.assertEqual(merged["last_seen_at"], "2026-10-29T00:00:00Z")
        self.assertEqual(len(merged["sources"]), 1)
        self.assertEqual(merged["review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
