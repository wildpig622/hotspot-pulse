import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.collect import build_candidate, classify_content, classify_event, enrich_existing_event, extract_event_date, is_upcoming_event, merge_candidate, normalize_title, parse_feed


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
        xml = """<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>2026杭州马拉松11月1日举行</title>
        <link>https://news.google.com/rss/articles/example</link>
        <description>赛事公告</description><pubDate>Wed, 28 Oct 2026 02:00:00 GMT</pubDate>
        <source url="https://example.gov.cn">官方新闻</source></item>
        </channel></rss>""".encode("utf-8")
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


    def test_month_range_is_reference_period_not_a_single_event_date(self):
        title = "沈阳2026年9-12月演唱会、话剧、脱口秀等演出的靠谱购票平台有哪些？"
        result = extract_event_date(title, today=date(2026, 10, 29))
        self.assertIsNone(result["start_at"])
        self.assertEqual(result["date_precision"], "month_range")
        self.assertEqual(result["reference_period_start"], "2026-09-01")
        self.assertEqual(result["reference_period_end"], "2026-12-31")
        self.assertEqual(classify_content(title), "guide")

    def test_ticket_sale_date_is_not_event_date(self):
        title = "肖战出道十周年南京演唱会 10月15日10:05正式开售 100%公开售票"
        result = extract_event_date(title, today=date(2026, 10, 29))
        self.assertIsNone(result["start_at"])
        self.assertEqual(result["ticket_sale_at"], "2026-10-15")
        self.assertEqual(result["event_date_role"], "ticket_sale")
        self.assertEqual(classify_content(title), "ticketing_notice")

    def test_event_date_wins_over_nearby_ticket_sale_date(self):
        title = "南京演唱会将于2026年11月1日举行，门票10月15日开售"
        result = extract_event_date(title, today=date(2026, 10, 29))
        self.assertEqual(result["start_at"], "2026-11-01")
        self.assertEqual(result["ticket_sale_at"], "2026-10-15")
        self.assertEqual(result["event_date_role"], "event")

    def test_schedule_roundup_and_past_report_are_not_future_event_candidates(self):
        self.assertEqual(classify_content("2026年南昌10月演出排期安排来了"), "schedule_roundup")
        self.assertEqual(classify_content("10月18日西安马拉松男子组冠军诞生"), "past_report")
        self.assertFalse(is_upcoming_event({
            "event_name": "2026年南昌10月演出排期安排来了",
            "content_kind": "schedule_roundup", "start_at": "2026-10-01",
            "end_at": "2026-10-31", "date_precision": "month",
        }, date(2026, 10, 29)))

    def test_expired_single_event_is_not_an_upcoming_candidate(self):
        event = {
            "event_name": "杭州马拉松将于2026年10月18日举行",
            "content_kind": "event_announcement", "start_at": "2026-10-18",
            "end_at": "2026-10-18", "date_precision": "day", "event_date_role": "event",
        }
        self.assertFalse(is_upcoming_event(event, date(2026, 10, 29)))

    def test_publication_date_is_not_used_as_event_date(self):
        city = {"city_name": "杭州市", "city_slug": "hangzhou", "aliases": ["杭州"]}
        item = {
            "title": "杭州马拉松报名启动",
            "description": "报名信息公布",
            "url": "https://news.google.com/rss/articles/example",
            "published_at": "2026-10-28T02:00:00Z",
            "publisher": "新闻媒体",
            "publisher_url": "https://example.com",
        }
        candidate = build_candidate(city, item, "2026-10-29T02:00:00Z", date(2026, 10, 29))
        self.assertIsNone(candidate["start_at"])
        self.assertEqual(candidate["registration_at"], None)
        self.assertEqual(candidate["content_kind"], "registration_notice")


    def test_current_public_snapshot_can_be_reclassified_without_losing_records(self):
        repo_root = Path(__file__).resolve().parents[1]
        snapshot_path = repo_root / "site" / "api" / "v1" / "hotspots.json"
        import json
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        events = payload["data"]
        original_count = len(events)
        today = date(2026, 10, 29)
        enriched = [enrich_existing_event(dict(event), today) for event in events]
        self.assertEqual(len(enriched), original_count)
        self.assertTrue(all(event.get("content_kind") for event in enriched))
        self.assertTrue(all(not event.get("start_at") or len(event["start_at"]) == 10 for event in enriched))


if __name__ == "__main__":
    unittest.main()
