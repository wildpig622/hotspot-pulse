import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_pilot_review import GROUPS_FILE, build_pilot_review
from scripts.build_verification_worksheet import build_worksheet


class PilotReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worksheet = build_worksheet()
        cls.definitions = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))

    def test_packet_keeps_all_twenty_ids_pending_and_leaves_human_decisions_blank(self):
        report = build_pilot_review(self.worksheet, self.definitions)
        self.assertEqual((report["candidate_record_count"], report["proposed_activity_group_count"]), (20, 11))
        self.assertEqual(report["manual_verified_count"], 0)
        self.assertTrue(all(value is None for group in report["groups"] for value in group["human_signoff"].values()))

    def test_duplicate_or_missing_candidate_members_cannot_be_hidden_by_grouping(self):
        for replacement in ([], ["evt_75164357227c", "evt_75164357227c"]):
            definitions = copy.deepcopy(self.definitions)
            definitions["groups"][0]["event_ids"] = replacement
            with self.assertRaises(ValueError):
                build_pilot_review(self.worksheet, definitions)

    def test_grouping_cannot_mix_cities(self):
        definitions = copy.deepcopy(self.definitions)
        definitions["groups"][0]["city_name"] = "成都市"
        with self.assertRaises(ValueError):
            build_pilot_review(self.worksheet, definitions)

    def test_conflicting_dates_require_review_instead_of_a_silent_merge(self):
        worksheet = copy.deepcopy(self.worksheet)
        next(row for row in worksheet["records"] if row["event_id"] == "evt_3be0559d6385")["manual_event_date"] = "2026-11-20"
        with self.assertRaises(ValueError):
            build_pilot_review(worksheet, self.definitions)

    def test_report_generator_cannot_consume_an_automatically_promoted_record(self):
        worksheet = copy.deepcopy(self.worksheet)
        next(row for row in worksheet["records"] if row["is_future_candidate_after_fix"])["review_status_after"] = "verified"
        with self.assertRaises(ValueError):
            build_pilot_review(worksheet, self.definitions)

    def test_historical_review_remains_reproducible_without_reading_the_live_snapshot(self):
        production = GROUPS_FILE.parents[1] / "site/api/v1/hotspots.json"
        read_bytes = Path.read_bytes
        def refuse_live_snapshot(path):
            if path == production:
                raise OSError("live snapshot is unavailable or has been replaced")
            return read_bytes(path)
        with patch.object(Path, "read_bytes", refuse_live_snapshot):
            report = build_pilot_review()
        self.assertEqual(report["candidate_record_count"], 20)
        self.assertEqual(report["proposed_activity_group_count"], 11)


if __name__ == "__main__":
    unittest.main()
