import copy
import json
import unittest

from scripts.build_acceptance_review import build_acceptance
from scripts.build_evidence_refresh import INPUT, build_refresh
from scripts.build_pilot_review import build_pilot_review
from scripts.build_verification_worksheet import build_worksheet


class EvidenceRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = json.loads(INPUT.read_text(encoding="utf-8"))
        cls.worksheet = build_worksheet()
        cls.pilot = build_pilot_review(cls.worksheet)
        cls.acceptance = build_acceptance()

    def build(self, inputs=None, worksheet=None):
        return build_refresh(self.inputs if inputs is None else inputs,
                             self.worksheet if worksheet is None else worksheet,
                             self.pilot, self.acceptance)

    def test_all_candidates_are_accounted_for_without_requiring_user_signatures(self):
        report = self.build()
        self.assertEqual((report["candidate_record_count"], report["activity_group_count"]), (20, 11))
        self.assertEqual((report["current_primary_reopened_record_count"], report["current_primary_reopened_group_count"]), (18, 10))
        self.assertEqual(len(report["records"]), 49)
        self.assertEqual(sum(row["sample_group"] != "expanded_4" for row in report["records"]), 45)
        self.assertFalse(report["policy"]["user_per_record_signature_required"])
        self.assertEqual(report["strict_release_result"], "FAIL")
        self.assertEqual(report["manual_verified_count"], 0)

    def test_failed_reopen_preserves_historical_evidence_timestamps(self):
        report = self.build()
        previous = next(row for row in self.worksheet["records"] if row["event_id"] == "evt_6c148ae9cbc6")
        current = next(row for row in report["records"] if row["event_id"] == previous["event_id"])
        self.assertEqual(current["checked_at"], previous["checked_at"])
        self.assertEqual(current["sources"], previous["sources"])
        self.assertEqual(current["source_refresh_result"], "NOT_REOPENED_PRIOR_EVIDENCE_ONLY")
        self.assertIsNone(current["current_round_observation"]["start_date"])

    def test_failed_or_index_only_access_cannot_create_fresh_primary_dates(self):
        for access_status in ("primary_open_failed", "search_index_only"):
            inputs = copy.deepcopy(self.inputs)
            source = next(row for row in inputs["observations"] if row["group_id"] == "review_nanning_marathon_2026")
            source.update(access_status=access_status, start_date="2026-12-20")
            with self.assertRaises(ValueError):
                self.build(inputs)

    def test_conflicting_source_dates_or_city_do_not_silently_pass(self):
        for field, value in (("start_date", "2026-10-31"), ("city_name", "苏州市")):
            inputs = copy.deepcopy(self.inputs)
            inputs["observations"][0][field] = value
            with self.assertRaises(ValueError):
                self.build(inputs)

    def test_day_only_calendar_cannot_assert_a_start_time(self):
        inputs = copy.deepcopy(self.inputs)
        source = next(row for row in inputs["observations"] if row["source_type"] == "association_race_calendar")
        source["local_time"] = "00:00"
        with self.assertRaises(ValueError):
            self.build(inputs)

    def test_missing_group_or_promoted_record_is_rejected(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["observations"].pop()
        with self.assertRaises(ValueError):
            self.build(inputs)
        worksheet = copy.deepcopy(self.worksheet)
        worksheet["records"][0]["review_status_after"] = "verified"
        with self.assertRaises(ValueError):
            self.build(worksheet=worksheet)

    def test_user_signatures_cannot_be_added_as_a_new_gate(self):
        inputs = copy.deepcopy(self.inputs)
        inputs["policy"]["user_per_record_signature_required"] = True
        with self.assertRaises(ValueError):
            self.build(inputs)


if __name__ == "__main__":
    unittest.main()
