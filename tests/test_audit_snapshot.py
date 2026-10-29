import unittest
from datetime import date
from pathlib import Path

from scripts.audit_snapshot import build_report, edge_case_results, load_snapshot


class SnapshotAuditTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.payload = load_snapshot(self.repo_root / "site" / "api" / "v1" / "hotspots.json")
        self.report = build_report(self.payload, date(2026, 10, 29))

    def test_audit_buckets_cover_all_legacy_records(self):
        counts = self.report["primary_disposition_counts"]
        self.assertEqual(counts["total"], 457)
        self.assertEqual(
            sum(value for key, value in counts.items() if key != "total"),
            counts["total"],
        )

    def test_audit_keeps_all_records_pending_and_does_not_promote(self):
        self.assertEqual(self.report["review_status_counts"], {"pending": 457})
        self.assertEqual(self.report["raw_snapshot"]["legacy_content_kind_missing"], 457)
        self.assertEqual(self.report["legacy_comparison"]["legacy_dated_records_cleared"], 26)

    def test_audit_counts_match_current_filter_and_review_flags(self):
        counts = self.report["primary_disposition_counts"]
        self.assertEqual(counts["future_dated_event_candidates"], 20)
        self.assertEqual(counts["event_candidates_with_dates_needing_review"], 351)
        self.assertEqual(counts["ticketing_or_registration_notices"], 22)
        self.assertEqual(counts["schedule_roundups"], 11)
        self.assertEqual(counts["guides_or_other_information"], 17)
        self.assertEqual(counts["past_reports_or_expired_events"], 36)
        self.assertEqual(self.report["date_review"]["event_candidates_with_any_review_flag"], 371)
        self.assertEqual(self.report["date_review"]["future_candidates_with_review_flags"], 20)
        self.assertEqual(self.report["date_review"]["future_candidates_without_review_flags"], 0)

    def test_edge_case_audit_includes_compact_date_as_review_lead(self):
        cases = {case["case"]: case for case in edge_case_results(date(2026, 10, 29))}
        compact = cases["compact numeric date remains a review lead"]
        self.assertIsNone(compact["start_at"])
        self.assertEqual(compact["event_date_role"], "unknown")


if __name__ == "__main__":
    unittest.main()
