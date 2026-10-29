import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import collect


class CollectionPipelineTests(unittest.TestCase):
    """Exercise collection using temporary files and a mocked RSS transport only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.api = Path(self.temp.name)
        self.cities_file = self.api / "config.json"
        self.city = {"city_name": "杭州市", "city_slug": "hangzhou", "aliases": ["杭州"]}
        self.cities_file.write_text(json.dumps([self.city]), encoding="utf-8")
        self.now = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
        self.start_patch("SITE_API", self.api)
        self.start_patch("CITIES_FILE", self.cities_file)
        self.start_patch("now_utc", return_value=self.now)
        self.start_patch("configured_cities", return_value=[self.city])
        self.fetch = self.start_patch("fetch_feed", return_value=b"mock RSS")
        self.parse = self.start_patch("parse_feed", return_value=[])

    def start_patch(self, name, *args, **kwargs):
        patcher = patch.object(collect, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def run_offline(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return collect.run_collection()

    def read_events(self):
        return json.loads((self.api / "hotspots.json").read_text(encoding="utf-8"))["data"]

    def test_summary_date_survives_collection_and_an_unseen_refresh(self):
        self.parse.return_value = [{"title": "杭州马拉松赛事公告", "url": "https://example.com/event",
                                    "description": "比赛时间：2026年11月8日。"}]
        self.assertEqual(self.run_offline(), 0)
        first = self.read_events()[0]
        self.assertEqual(first["start_at"], "2026-11-08")
        self.assertEqual(first["event_date_role"], "event")
        self.parse.return_value = []
        self.assertEqual(self.run_offline(), 0)
        refreshed = self.read_events()[0]
        self.assertEqual(refreshed["event_id"], first["event_id"])
        self.assertEqual(refreshed["start_at"], "2026-11-08")
        self.assertEqual(refreshed["review_status"], "pending")
        self.assertTrue(collect.is_upcoming_event(refreshed, self.now.date()))

    def test_summary_registration_does_not_become_an_event_date(self):
        self.parse.return_value = [{"title": "杭州马拉松最新消息", "url": "https://example.com/registration",
                                    "description": "报名时间：2026年11月8日。"}]
        self.assertEqual(self.run_offline(), 0)
        event = self.read_events()[0]
        self.assertIsNone(event["start_at"])
        self.assertEqual(event["registration_at"], "2026-11-08")

    def test_human_review_fields_survive_a_complete_automatic_refresh(self):
        title = "杭州马拉松赛事公告"
        item = {"title": title, "url": "https://example.com/reviewed", "description": "比赛时间：2026年11月8日。"}
        reviewed = collect.build_candidate(self.city, item, "2026-10-28T08:00:00Z", self.now.date())
        reviewed.update(review_status="verified", event_status="confirmed", start_at="2026-11-09",
                        date_confidence="manual_review", candidate_note="人工复核保留")
        (self.api / "hotspots.json").write_text(json.dumps({"data": [reviewed]}), encoding="utf-8")
        self.parse.return_value = [dict(item, url="https://example.com/new", description="报名时间：2026年11月10日。")]
        self.assertEqual(self.run_offline(), 0)
        refreshed = self.read_events()[0]
        for field in ("event_id", "start_at", "event_date_role", "date_confidence", "content_kind",
                      "review_status", "event_status", "candidate_note", "discovery_summary", "discovery_summary_source_url"):
            self.assertEqual(refreshed[field], reviewed[field], field)
        self.assertEqual(refreshed["source_count"], 2)

    def test_total_source_failure_preserves_snapshot_and_city_bytes(self):
        event = {"event_id": "evt_keep", "city_name": "杭州市", "city_slug": "hangzhou",
                 "event_name": "杭州演唱会", "start_at": "2026-01-01",
                 "last_seen_at": "2026-01-01T00:00:00Z", "review_status": "pending"}
        original = json.dumps({"meta": {"generated_at": "2026-01-01T00:00:00Z"}, "data": [event]},
                              ensure_ascii=False).encode("utf-8")
        (self.api / "hotspots.json").write_bytes(original)
        original_cities = b'{"data":[],"meta":{"retained":true}}\n'
        (self.api / "cities.json").write_bytes(original_cities)
        self.fetch.side_effect = OSError("offline source failure")
        self.assertEqual(self.run_offline(), 1)
        self.assertEqual((self.api / "hotspots.json").read_bytes(), original)
        self.assertEqual((self.api / "cities.json").read_bytes(), original_cities)
        health = json.loads((self.api / "health.json").read_text(encoding="utf-8"))
        self.assertEqual(health["status"], "failed")
        self.assertEqual(health["candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
