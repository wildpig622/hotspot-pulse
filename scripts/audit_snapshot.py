#!/usr/bin/env python3
"""Audit the checked-in hotspot snapshot without fetching live sources.

The audit deliberately reuses the collector's current classification and date
parsing functions. It never calls ``run_collection`` and never writes to the
published JSON snapshot. The generated JSON/Markdown files are evidence for
review of the data-quality PR, not production data.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.collect import (  # noqa: E402
    classify_content,
    enrich_existing_event,
    extract_event_date,
    future_exclusion_reasons,
    is_upcoming_event,
)

SNAPSHOT = ROOT / "site" / "api" / "v1" / "hotspots.json"
DEFAULT_JSON = ROOT / "docs" / "audit-2026-10-29-followup.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "audit-2026-10-29-followup.md"
EVENT_KINDS = {"event_announcement", "uncertain"}
NON_EVENT_KINDS = {"ticketing_notice", "registration_notice", "schedule_roundup", "guide", "other"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default="2026-10-29", help="Audit date in YYYY-MM-DD form")
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    return parser.parse_args()


def load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError(f"snapshot must contain a data list: {path}")
    return payload


def validate_report_paths(snapshot: Path, *outputs: Path) -> None:
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError("report output paths must be distinct")
    for path in resolved:
        if path == snapshot.resolve() or path.is_relative_to((ROOT / "site").resolve()):
            raise ValueError("offline audit outputs must not overwrite a snapshot or site file")


def date_value(event: dict[str, Any], field: str) -> date | None:
    value = event.get(field)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def is_expired(event: dict[str, Any], today: date) -> bool:
    kind = event.get("content_kind") or classify_content(event.get("event_name", ""))
    if kind not in EVENT_KINDS:
        return False
    end = date_value(event, "end_at") or date_value(event, "start_at")
    if end and end < today:
        return True
    period_end = date_value(event, "reference_period_end")
    return bool(period_end and period_end < today)


def primary_bucket(event: dict[str, Any], today: date) -> str:
    """Return one mutually exclusive disposition for the 457-record total."""
    kind = event.get("content_kind") or classify_content(event.get("event_name", ""))
    if kind in {"ticketing_notice", "registration_notice"}:
        return "ticketing_registration"
    if kind == "schedule_roundup":
        return "schedule_roundup"
    if kind == "guide" or kind == "other":
        return "guides_other"
    if kind == "past_report" or is_expired(event, today):
        return "past_expired"
    if is_upcoming_event(event, today):
        return "future_dated_event"
    if kind in EVENT_KINDS:
        return "event_date_review"
    return "guides_other"


def date_review_reasons(event: dict[str, Any], today: date) -> list[str]:
    """Return review flags for event candidates, including future candidates."""
    kind = event.get("content_kind") or classify_content(event.get("event_name", ""))
    if kind not in EVENT_KINDS or is_expired(event, today):
        return []
    reasons: list[str] = []
    reasons.extend(future_exclusion_reasons(event))
    if not event.get("start_at"):
        reasons.append("missing_event_date")
    if event.get("date_precision") in {"month", "month_range"}:
        reasons.append("month_only_or_range")
    if event.get("event_date_role") != "event":
        reasons.append("date_role_ambiguous")
    if event.get("date_confidence") != "explicit_year":
        reasons.append("year_inferred_or_unknown")
    if event.get("start_at") and not is_upcoming_event(event, today):
        reasons.append("not_current_future_candidate")
    return reasons


def source_url(event: dict[str, Any]) -> str | None:
    sources = event.get("sources") or []
    if sources and isinstance(sources[0], dict):
        return sources[0].get("source_url")
    return None


def concise_event(event: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "event_id": event.get("event_id"),
        "city_name": event.get("city_name"),
        "event_name": event.get("event_name"),
        "content_kind": event.get("content_kind"),
        "primary_bucket": event.get("primary_bucket"),
        "start_at": event.get("start_at"),
        "end_at": event.get("end_at"),
        "date_precision": event.get("date_precision"),
        "date_confidence": event.get("date_confidence"),
        "event_date_role": event.get("event_date_role"),
        "city_match": event.get("city_match"),
        "event_confirmation": event.get("event_confirmation"),
        "future_exclusion_reasons": future_exclusion_reasons(event),
        "date_review_reasons": event.get("date_review_reasons", []),
        "ticket_sale_at": event.get("ticket_sale_at"),
        "registration_at": event.get("registration_at"),
        "reference_period_start": event.get("reference_period_start"),
        "reference_period_end": event.get("reference_period_end"),
        "review_status": event.get("review_status", "missing"),
        "source_url": source_url(event),
    }
    if old is not None:
        result["legacy_start_at"] = old.get("start_at")
        result["legacy_end_at"] = old.get("end_at")
        result["legacy_date_precision"] = old.get("date_precision")
    return result


def changed_date(old: dict[str, Any], new: dict[str, Any]) -> bool:
    return any(
        old.get(field) != new.get(field)
        for field in ("start_at", "end_at", "date_precision", "date_confidence")
    )


def edge_case_results(today: date) -> list[dict[str, Any]]:
    cases = [
        (
            "month range is reference period",
            "沈阳2026年9-12月演唱会、话剧、脱口秀等演出的靠谱购票平台有哪些？",
            "",
        ),
        (
            "ticket sale date is not event date",
            "肖战出道十周年南京演唱会 10月15日10:05正式开售 100%公开售票",
            "",
        ),
        (
            "event date wins over nearby ticket sale",
            "南京演唱会将于2026年11月1日举行，门票10月15日开售",
            "",
        ),
        (
            "cross-month event range",
            "广州马拉松将于2026年11月29日至12月1日举行",
            "",
        ),
        (
            "cross-year shorthand range",
            "跨年音乐节将于12月31日至1月2日举行",
            "",
        ),
        (
            "slash date without year",
            "深圳展会定于11/08开幕",
            "",
        ),
        (
            "compact numeric date remains a review lead",
            "南京演唱会 20261023 肖战巡回演唱会南京站",
            "",
        ),
        (
            "registration date is not event date",
            "杭州马拉松报名启动，报名截止11月5日",
            "",
        ),
        ("participant quantity is not a date", "2026成都马拉松开跑 3.5万名跑者用脚步丈量蓉城", ""),
        ("hotline quantity is not a date", "12345热线收到4.8万件演唱会诉求", ""),
        ("valid dotted event date", "深圳展会定于11.08开幕", ""),
    ]
    results: list[dict[str, Any]] = []
    for name, title, description in cases:
        parsed = extract_event_date(title, description, today)
        results.append({"case": name, "title": title, **parsed})
    return results


def build_report(payload: dict[str, Any], today: date) -> dict[str, Any]:
    original_events = [dict(event) for event in payload["data"]]
    enriched_events: list[dict[str, Any]] = []
    for original in original_events:
        event = enrich_existing_event(dict(original), today)
        event["primary_bucket"] = primary_bucket(event, today)
        event["date_review_reasons"] = date_review_reasons(event, today)
        enriched_events.append(event)

    buckets = Counter(event["primary_bucket"] for event in enriched_events)
    review_status = Counter(event.get("review_status", "missing") for event in enriched_events)
    content_kind = Counter(event.get("content_kind") or "missing" for event in enriched_events)
    date_precision = Counter(event.get("date_precision") or "missing" for event in enriched_events)
    date_role = Counter(event.get("event_date_role") or "missing" for event in enriched_events)
    changed_fields = Counter(
        field
        for original, enriched in zip(original_events, enriched_events)
        for field in ("start_at", "end_at", "date_precision", "date_confidence", "event_date_role")
        if original.get(field) != enriched.get(field)
    )
    legacy_dated_to_no_event_date = sum(
        bool(original.get("start_at")) and not enriched.get("start_at")
        for original, enriched in zip(original_events, enriched_events)
    )
    date_review_flags = Counter(
        reason
        for event in enriched_events
        for reason in event.get("date_review_reasons", [])
        if reason != "not_current_future_candidate"
    )
    all_event_review = sum(bool(event.get("date_review_reasons")) for event in enriched_events)
    future_with_review = sum(
        event["primary_bucket"] == "future_dated_event" and bool(event.get("date_review_reasons"))
        for event in enriched_events
    )
    future_without_review = buckets["future_dated_event"] - future_with_review

    examples: dict[str, list[dict[str, Any]]] = {}
    old_by_id = {event.get("event_id"): event for event in original_events}
    for label, predicate in (
        (
            "month_range_guide_reclassified",
            lambda event: event["content_kind"] == "guide"
            and old_by_id[event.get("event_id")].get("start_at")
            and event.get("start_at") is None,
        ),
        (
            "ticketing_or_registration",
            lambda event: event["content_kind"] in {"ticketing_notice", "registration_notice"},
        ),
        (
            "schedule_roundup",
            lambda event: event["content_kind"] == "schedule_roundup",
        ),
        (
            "past_report_or_expired",
            lambda event: event["primary_bucket"] == "past_expired",
        ),
        (
            "legacy_date_changed",
            lambda event: changed_date(old_by_id[event.get("event_id")], event),
        ),
    ):
        selected = [
            concise_event(event, old_by_id.get(event.get("event_id")))
            for event in enriched_events
            if predicate(event)
        ]
        examples[label] = sorted(selected, key=lambda item: (item.get("event_name") or "", item.get("event_id") or ""))[:5]

    examples["future_dated_event_candidates"] = [
        concise_event(event, old_by_id.get(event.get("event_id")))
        for event in sorted(
            (event for event in enriched_events if event["primary_bucket"] == "future_dated_event"),
            key=lambda item: (item.get("start_at") or "", item.get("city_name") or "", item.get("event_name") or ""),
        )[:8]
    ]
    examples["event_candidates_with_dates_needing_review"] = [
        concise_event(event, old_by_id.get(event.get("event_id")))
        for event in sorted(
            (event for event in enriched_events if event["primary_bucket"] == "event_date_review"),
            key=lambda item: (item.get("event_name") or "", item.get("event_id") or ""),
        )[:8]
    ]

    return {
        "audit": {
            "audit_date": today.isoformat(),
            "snapshot_path": str(SNAPSHOT.relative_to(ROOT)),
            "snapshot_generated_at": payload.get("meta", {}).get("generated_at"),
            "source_snapshot_candidate_count": len(original_events),
            "live_collection_run": False,
            "production_snapshot_written": False,
            "method": "enrich_existing_event + current collector classify_content/is_upcoming_event; no network calls",
        },
        "raw_snapshot": {
            "meta_candidate_count": payload.get("meta", {}).get("candidate_count"),
            "records": len(original_events),
            "legacy_content_kind_missing": sum("content_kind" not in event for event in original_events),
            "legacy_event_date_role_missing": sum("event_date_role" not in event for event in original_events),
            "records_with_start_at": sum(bool(event.get("start_at")) for event in original_events),
            "records_with_date_precision": dict(Counter(event.get("date_precision") or "missing" for event in original_events)),
        },
        "legacy_comparison": {
            "legacy_records_with_start_at": sum(bool(event.get("start_at")) for event in original_events),
            "audited_records_with_start_at": sum(bool(event.get("start_at")) for event in enriched_events),
            "legacy_dated_records_cleared": legacy_dated_to_no_event_date,
            "date_field_change_counts": dict(sorted(changed_fields.items())),
        },
        "primary_disposition_counts": {
            "future_dated_event_candidates": buckets["future_dated_event"],
            "event_candidates_with_dates_needing_review": buckets["event_date_review"],
            "ticketing_or_registration_notices": buckets["ticketing_registration"],
            "schedule_roundups": buckets["schedule_roundup"],
            "guides_or_other_information": buckets["guides_other"],
            "past_reports_or_expired_events": buckets["past_expired"],
            "total": len(enriched_events),
        },
        "classification_counts": dict(sorted(content_kind.items())),
        "review_status_counts": dict(sorted(review_status.items())),
        "date_precision_counts_after_reclassification": dict(sorted(date_precision.items())),
        "date_role_counts_after_reclassification": dict(sorted(date_role.items())),
        "date_review": {
            "event_candidates_with_any_review_flag": all_event_review,
            "future_candidates_with_review_flags": future_with_review,
            "future_candidates_without_review_flags": future_without_review,
            "reason_counts": dict(sorted(date_review_flags.items())),
        },
        "representative_examples": examples,
        "date_parsing_edge_cases": edge_case_results(today),
        "records": [concise_event(event, old_by_id[event["event_id"]]) for event in enriched_events],
    }


def markdown_report(report: dict[str, Any]) -> str:
    audit = report["audit"]
    counts = report["primary_disposition_counts"]
    lines = [
        "# Offline reclassification audit",
        "",
        f"- Audit date: `{audit['audit_date']}` (Asia/Shanghai)",
        f"- Snapshot: `{audit['snapshot_path']}`; generated at `{audit['snapshot_generated_at']}`",
        f"- Records audited: **{audit['source_snapshot_candidate_count']}**",
        "- Method: current branch `enrich_existing_event`, `classify_content`, and `is_upcoming_event`; no network calls.",
        "- Safety: live collection was not run and the production snapshot was not written.",
        "",
        "## Primary disposition",
        "",
        "These buckets are mutually exclusive and sum to the audited snapshot.",
        "",
        "| Category | Count |",
        "|---|---:|",
        f"| Future dated event candidates | {counts['future_dated_event_candidates']} |",
        f"| Event candidates with dates needing review | {counts['event_candidates_with_dates_needing_review']} |",
        f"| Ticketing / registration notices | {counts['ticketing_or_registration_notices']} |",
        f"| Schedule roundups | {counts['schedule_roundups']} |",
        f"| Guides / other information | {counts['guides_or_other_information']} |",
        f"| Past reports / expired events | {counts['past_reports_or_expired_events']} |",
        f"| **Total** | **{counts['total']}** |",
        "",
        "## Legacy-date comparison",
        "",
        f"- Legacy snapshot records with `start_at`: **{report['legacy_comparison']['legacy_records_with_start_at']}**.",
        f"- Records with `start_at` after offline reclassification: **{report['legacy_comparison']['audited_records_with_start_at']}**.",
        f"- Legacy dated records cleared because the date was not an event date: **{report['legacy_comparison']['legacy_dated_records_cleared']}**.",
        "",
        "## Verification status",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in report["review_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "All records retain their existing review status; the audit does not promote any candidate.",
            "",
            "## Date-review flags",
            "",
            f"- Event candidates with at least one date-review flag: **{report['date_review']['event_candidates_with_any_review_flag']}**.",
            f"- Future candidates carrying a review flag (for example inferred year or ambiguous role): **{report['date_review']['future_candidates_with_review_flags']}**.",
            f"- Future candidates without a date-review flag: **{report['date_review']['future_candidates_without_review_flags']}**.",
            "",
            "| Reason | Count |",
            "|---|---:|",
        ]
    )
    for reason, count in report["date_review"]["reason_counts"].items():
        lines.append(f"| {reason} | {count} |")
    lines.extend(["", "## Representative examples", ""])
    for label, examples in report["representative_examples"].items():
        lines.append(f"### {label}")
        lines.append("")
        if not examples:
            lines.append("No matching records.")
            lines.append("")
            continue
        for example in examples:
            lines.append(
                f"- `{example.get('city_name')}` — {example.get('event_name')} "
                f"→ `{example.get('content_kind')}`, `{example.get('primary_bucket')}`; "
                f"legacy `{example.get('legacy_start_at')}` → `{example.get('start_at')}`; "
                f"role `{example.get('event_date_role')}`."
            )
        lines.append("")
    lines.extend(["## Date parsing edge cases", "", "| Case | start_at | end_at | role | precision | ticket_sale_at | registration_at |", "|---|---|---|---|---|---|---|"])
    for case in report["date_parsing_edge_cases"]:
        lines.append(
            f"| {case['case']} | {case.get('start_at') or '—'} | {case.get('end_at') or '—'} | "
            f"{case.get('event_date_role') or '—'} | {case.get('date_precision') or '—'} | "
            f"{case.get('ticket_sale_at') or '—'} | {case.get('registration_at') or '—'} |"
        )
    lines.extend(["", "## Complete future candidate IDs", ""])
    for event in report["records"]:
        if event["primary_bucket"] == "future_dated_event":
            lines.append(f"- `{event['event_id']}` — {event['city_name']} — {event['event_name']} — `{event['start_at']}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The snapshot is a discovery pool, not a verified event calendar. The future bucket is the current collector's default future/ongoing filter; pending status still blocks operational use. Month-only, ambiguous, inferred-year, and undated event leads remain review work.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    validate_report_paths(args.snapshot, args.json_output, args.markdown_output)
    today = date.fromisoformat(args.today)
    payload = load_snapshot(args.snapshot)
    report = build_report(payload, today)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps(report["primary_disposition_counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
