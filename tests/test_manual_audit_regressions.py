import copy
import json
import unittest
from datetime import date
from pathlib import Path

from scripts.audit_snapshot import build_report, validate_report_paths
from scripts.collect import (
    assess_event_city, build_candidate, classify_content, enrich_existing_event,
    extract_event_date, future_exclusion_reasons, is_upcoming_event, merge_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


class ManualAuditRegressions(unittest.TestCase):
    today = date(2026, 10, 29)

    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads((ROOT / "site/api/v1/hotspots.json").read_text(encoding="utf-8"))
        cls.cases = json.loads((ROOT / "tests/fixtures/manual-audit-2026-10-29.json").read_text(encoding="utf-8"))
        cls.raw = {row["event_id"]: row for row in cls.payload["data"]}
        cls.report = build_report(cls.payload, cls.today)

    def test_exact_45_manual_samples_are_distinct_and_reproducible(self):
        selected = (self.cases["expected_future_ids"] + list(self.cases["excluded_future_ids"])
                    + list(self.cases["boundary_expected_buckets"]))
        self.assertEqual(len(selected), 45)
        self.assertEqual(len(set(selected)), 45)
        self.assertTrue(set(selected) <= self.raw.keys())
        actual = {row["event_id"] for row in self.report["records"] if row["primary_bucket"] == "future_dated_event"}
        self.assertEqual(actual, set(self.cases["expected_future_ids"] + self.cases["additional_supported_future_ids"]))

    def test_all_14_bad_future_candidates_are_blocked_in_raw_and_enriched_data(self):
        for event_id, reason in self.cases["excluded_future_ids"].items():
            with self.subTest(event_id=event_id):
                raw = self.raw[event_id]
                self.assertIn(reason, future_exclusion_reasons(raw))
                self.assertFalse(is_upcoming_event(raw, self.today))
                enriched = enrich_existing_event(dict(raw), self.today)
                self.assertFalse(is_upcoming_event(enriched, self.today))
                self.assertEqual(enriched["review_status"], "pending")
                if reason == "numeric_quantity_date":
                    self.assertIsNone(enriched["start_at"])

    def test_all_12_boundaries_remain_in_the_expected_non_future_bucket(self):
        rows = {row["event_id"]: row for row in self.report["records"]}
        for event_id, expected in self.cases["boundary_expected_buckets"].items():
            with self.subTest(event_id=event_id):
                self.assertEqual(rows[event_id]["primary_bucket"], expected)
                self.assertEqual(rows[event_id]["review_status"], "pending")

    def test_decimal_quantities_do_not_create_dates(self):
        for quantity in ("2.2万人", "2.5万名", "3.5万人", "3.6万名", "4.8万件", "4.8万通", "1.5亿元", "11.08%"):
            with self.subTest(quantity=quantity):
                parsed = extract_event_date("城市演唱会 " + quantity, today=self.today)
                self.assertIsNone(parsed["start_at"])

    def test_calendar_dates_remain_valid_beside_participant_quantities(self):
        for value in ("11.08", "11/08", "2026.11.08", "2026-11-08", "2026年11月8日"):
            with self.subTest(value=value):
                parsed = extract_event_date(f"金华马拉松3.5万人参赛，将于{value}开跑", today=self.today)
                self.assertEqual(parsed["start_at"], "2026-11-08")

    def test_invalid_full_date_cannot_fall_back_to_partial_date(self):
        for value in ("2026.13.08", "2026/02/30"):
            with self.subTest(value=value):
                self.assertIsNone(extract_event_date(f"展会定于{value}开幕", today=self.today)["start_at"])

    def test_stale_legacy_date_is_cleared_even_after_merge(self):
        raw = self.raw["evt_9e0e0a6d2bfd"]
        city = {"city_slug": "chengdu", "city_name": "成都市", "aliases": ["成都"]}
        candidate = build_candidate(city, {"title": raw["event_name"], "url": "https://example.com/event"},
                                    "2026-10-29T08:00:00Z", self.today)
        merged = merge_candidate(raw, candidate)
        self.assertIsNone(merged["start_at"])
        self.assertEqual(merged["event_id"], raw["event_id"])
        self.assertEqual(merged["review_status"], "pending")

    def test_registration_action_wins_over_preceding_will_be_on_cue(self):
        title = self.raw["evt_bd8e6c831c64"]["event_name"]
        parsed = extract_event_date(title, today=self.today)
        self.assertEqual(parsed["registration_at"], "2026-10-20")
        self.assertEqual(parsed["start_at"], "2026-12-20")
        self.assertEqual(parsed["event_date_role"], "event")

    def test_legacy_rollover_records_are_recomputed_as_current_year_past_dates(self):
        for event_id in self.cases["legacy_rollover_ids"]:
            with self.subTest(event_id=event_id):
                self.assertFalse(is_upcoming_event(self.raw[event_id], self.today))
                enriched = enrich_existing_event(dict(self.raw[event_id]), self.today)
                self.assertFalse(is_upcoming_event(enriched, self.today))
                if enriched["start_at"]:
                    self.assertTrue(enriched["start_at"].startswith("2026-"))

    def test_human_reviewed_date_and_identity_survive_automatic_refresh(self):
        reviewed = dict(self.raw["evt_9e0e0a6d2bfd"], review_status="verified", start_at="2026-10-25",
                        event_date_role="event", content_kind="past_report", city_match="text_confirmed")
        before = copy.deepcopy(reviewed)
        self.assertEqual(enrich_existing_event(reviewed, self.today), before)
        merged = merge_candidate(reviewed, {"start_at": None, "event_date_role": "unknown",
                                            "city_match": "query_only", "content_kind": "uncertain"})
        for field in ("start_at", "event_date_role", "city_match", "content_kind", "review_status"):
            self.assertEqual(merged[field], before[field])

    def test_incidental_city_name_cannot_override_event_host(self):
        title = self.raw["evt_a3fea5891c78"]["event_name"]
        self.assertEqual(assess_event_city({"city_slug": "suzhou", "aliases": ["苏州"]}, title), "event_city_conflict")
        self.assertEqual(assess_event_city({"city_slug": "zhengzhou", "aliases": ["郑州"]}, title), "text_confirmed")

    def test_conditional_title_and_summary_are_held_even_with_explicit_dates(self):
        city = {"city_slug": "chengdu", "city_name": "成都市", "aliases": ["成都"]}
        for title, description in (
            ("刘宇成都演唱会或定档2027年1月1日", ""),
            ("成都演唱会将于2027年1月1日举行", "主办方尚未官宣，正在审批"),
        ):
            with self.subTest(title=title):
                candidate = build_candidate(city, {"title": title, "description": description,
                                                   "url": "https://example.com/event"}, "2026-10-29T08:00:00Z", self.today)
                self.assertEqual(candidate["review_status"], "pending")
                self.assertFalse(is_upcoming_event(candidate, self.today))
                self.assertFalse(is_upcoming_event(enrich_existing_event(dict(candidate), self.today), self.today))
                refreshed = merge_candidate(candidate, dict(candidate, event_confirmation="unknown"))
                self.assertEqual(refreshed["event_confirmation"], "unconfirmed")

    def test_past_headlines_cannot_be_saved_by_a_future_legacy_date(self):
        for title in ("2026郑州马拉松落幕 2.5万名跑者", "2026成都马拉松昨鸣枪开跑 3.5万人"):
            with self.subTest(title=title):
                self.assertEqual(classify_content(title), "past_report")
                self.assertFalse(is_upcoming_event({"event_name": title, "content_kind": "event_announcement",
                                                   "start_at": "2027-03-05", "date_precision": "day"}, self.today))

    def test_audit_is_in_memory_only_and_rejects_production_output_paths(self):
        original = copy.deepcopy(self.payload)
        self.assertEqual(len(build_report(self.payload, self.today)["records"]), 457)
        self.assertEqual(self.payload, original)
        snapshot = ROOT / "site/api/v1/hotspots.json"
        for output in (snapshot, ROOT / "site/api/v1/health.json", ROOT / "site/../site/app.js"):
            with self.subTest(output=str(output)), self.assertRaises(ValueError):
                validate_report_paths(snapshot, output)
        with self.assertRaises(ValueError):
            validate_report_paths(snapshot, ROOT / "docs/same.json", ROOT / "docs/same.json")


if __name__ == "__main__":
    unittest.main()
