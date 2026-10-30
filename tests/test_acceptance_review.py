import copy
import json
import unittest

from scripts.build_acceptance_review import SELECTION, assess_case, build_acceptance, valid_disposition_exception


class AcceptanceExceptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_acceptance()
        cls.selection = json.loads(SELECTION.read_text(encoding="utf-8"))
        from scripts.build_verification_worksheet import build_worksheet
        rows = build_worksheet()["records"]
        cls.liu = next(row for row in rows if row["event_id"] == "evt_21064dd8a66c")
        cls.quantity = next(row for row in rows if row["event_id"] == "evt_5ed7a3f7e80b")

    def test_only_fixed_45_original_cases_are_accepted_without_status_promotion(self):
        self.assertEqual(self.report["accepted_disposition_count"], 45)
        self.assertEqual(self.report["documented_exception_event_ids"], ["evt_21064dd8a66c"])
        self.assertEqual(self.report["strict_release_result"], "FAIL")
        self.assertTrue(all(row["verification_status"] == "not_verified" for row in self.report["records"]))

    def test_future_leak_cannot_use_the_withheld_exception(self):
        row = copy.deepcopy(self.liu)
        row["is_future_candidate_after_fix"] = True
        row["latest_primary_bucket"] = "future_dated_event"
        self.assertFalse(valid_disposition_exception(row, self.selection))
        self.assertEqual(assess_case(row, self.selection)["disposition_result"], "FAIL")

    def test_confirmation_or_verified_promotion_invalidates_the_exception(self):
        for field, value in (("review_status_after", "verified"), ("manual_event_date", "2027-01-01")):
            row = copy.deepcopy(self.liu)
            row[field] = value
            self.assertFalse(valid_disposition_exception(row, self.selection))
            self.assertEqual(assess_case(row, self.selection)["disposition_result"], "FAIL")

    def test_exception_cannot_be_copied_to_an_unreviewed_identity(self):
        row = copy.deepcopy(self.liu)
        row["event_id"] = "evt_000000000000"
        self.assertFalse(valid_disposition_exception(row, self.selection))

    def test_stale_quantity_date_cannot_pass_merely_because_the_row_is_hidden(self):
        row = copy.deepcopy(self.quantity)
        row["rule_start_at"] = row["legacy_start_at"]
        self.assertEqual(assess_case(row, self.selection)["disposition_result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
