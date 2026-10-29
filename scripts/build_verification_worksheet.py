#!/usr/bin/env python3
"""Rebuild the report-only 49-record worksheet from the reviewed evidence files.

No network access, collection, or promotion to verified occurs here. Evidence
is transcribed with its access limitations; prior source links are not silently
represented as having been opened again.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.audit_snapshot import build_report, validate_report_paths

SNAPSHOT = ROOT / "site/api/v1/hotspots.json"
MANUAL = ROOT / "docs/manual-verification-2026-10-29.md"
SUPPLEMENT = ROOT / "docs/evidence-supplement-2026-10-29.json"
SELECTION = ROOT / "tests/fixtures/manual-audit-2026-10-29.json"
JSON_OUTPUT = ROOT / "docs/verification-worksheet-2026-10-29.json"
MD_OUTPUT = ROOT / "docs/verification-worksheet-2026-10-29.md"


def read_manual_report():
    text = MANUAL.read_text(encoding="utf-8")
    checked_at = re.search(r"核验时间：`([^`]+)`", text).group(1)
    catalogue, rows = {}, {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if re.fullmatch(r"E\d{2}", cells[0]):
            catalogue[cells[0]] = [
                {"url": url, "source_type": cells[2], "supports": cells[3],
                 "access_status": "inherited_from_prior_report_not_reopened_in_round_2"}
                for url in re.findall(r"<([^>]+)>", cells[1])
            ]
        for index in (1, 2):
            if len(cells) > index and re.fullmatch(r"`evt_[0-9a-f]{12}`", cells[index]):
                event_id = cells[index].strip("`")
                if event_id in rows:
                    raise ValueError(f"duplicate manual row: {event_id}")
                refs = re.findall(r"E\d{2}", cells[index + 5])
                rows[event_id] = {
                    "sample_group": "original_future_33" if index == 1 else "stratified_boundary_12",
                    "manual_event_date": cells[index + 4],
                    "conclusion": cells[index + 4],
                    "evidence_refs": refs,
                    "evidence_result": cells[index + 6].split(";")[0].strip("` "),
                    "checked_at": checked_at,
                }
    if len(rows) != 45:
        raise ValueError(f"expected 45 exact manual rows, found {len(rows)}")
    for row in rows.values():
        row["sources"] = [source for ref in row["evidence_refs"] for source in catalogue[ref]]
    return rows


def build_worksheet():
    original_bytes = SNAPSHOT.read_bytes()
    payload = json.loads(original_bytes)
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    supplement = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
    prior = read_manual_report()
    reviewed = build_report(payload, date.fromisoformat(selection["today"]))
    raw_by_id = {event["event_id"]: event for event in payload["data"]}
    audit_by_id = {event["event_id"]: event for event in reviewed["records"]}
    expanded_ids = selection["additional_supported_future_ids"] + selection["legacy_rollover_ids"]
    selected_ids = list(prior) + expanded_ids
    if len(selected_ids) != 49 or len(set(selected_ids)) != 49:
        raise ValueError("worksheet must contain 49 distinct IDs")
    supplements = {}
    for group in supplement["groups"]:
        for event_id in group["event_ids"]:
            if event_id not in selected_ids or event_id in supplements:
                raise ValueError(f"invalid or duplicated supplement ID: {event_id}")
            supplements[event_id] = group

    rows = []
    for event_id in selected_ids:
        original, audited = raw_by_id[event_id], audit_by_id[event_id]
        old = prior.get(event_id, {})
        additional = supplements.get(event_id)
        if original["review_status"] != "pending" or audited["review_status"] != "pending":
            raise ValueError("this fixed worksheet is not authorized to alter review status")
        sources = list(old.get("sources", []))
        if additional:
            sources.extend(additional["sources"])
        rows.append({
            "event_id": event_id,
            "sample_group": old.get("sample_group", "expanded_4"),
            "city_name": original["city_name"],
            "event_name": original["event_name"],
            "discovery_source_urls": [source["source_url"] for source in original.get("sources", [])],
            "legacy_start_at": original.get("start_at"),
            "rule_start_at": audited.get("start_at"),
            "rule_end_at": audited.get("end_at"),
            "rule_event_date_role": audited.get("event_date_role"),
            "manual_event_date": additional["manual_event_date"] if additional else old["manual_event_date"],
            "event_status": additional["event_status"] if additional else "unknown_pending",
            "snapshot_event_status": original.get("event_status", "unknown"),
            "review_status_before": "pending",
            "review_status_after": "pending",
            "verification_status": "not_verified",
            "checked_at": supplement["checked_at"] if additional else old["checked_at"],
            "prior_checked_at": old.get("checked_at"),
            "evidence_refs": old.get("evidence_refs", []) + ([additional["id"]] if additional else []),
            "sources": sources,
            "evidence_result": additional["evidence_result"] if additional else old["evidence_result"],
            "strict_authority_result": additional["strict_authority_result"] if additional else "not_reassessed_in_round_2",
            "conclusion": additional["conclusion"] if additional else old["conclusion"],
            "latest_primary_bucket": audited["primary_bucket"],
            "is_future_candidate_after_fix": audited["primary_bucket"] == "future_dated_event",
            "future_exclusion_reasons": audited["future_exclusion_reasons"],
            "next_action": "retain pending; complete primary source/body and identity check before any release",
        })
    if SNAPSHOT.read_bytes() != original_bytes:
        raise RuntimeError("input snapshot changed while building the worksheet")
    return {
        "status": "NOT_VERIFIED",
        "release_result": "FAIL",
        "baseline_commit": selection["baseline_commit"],
        "audit_date": selection["today"],
        "supplement_checked_at": supplement["checked_at"],
        "snapshot_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "sample_count": len(rows),
        "sample_counts": {"original_future": 33, "stratified_boundary": 12, "expanded": 4},
        "supplemented_record_count": len(supplements),
        "manual_verified_count": 0,
        "future_candidate_count": sum(row["is_future_candidate_after_fix"] for row in rows),
        "production_snapshot_written": False,
        "live_collection_run": False,
        "limitations": [
            "Prior source evidence is inherited, not represented as independently re-opened.",
            "Search-index text, authenticated mirrors and inaccessible primary pages are distinguished per source.",
            "No matching search result is not evidence of cancellation or non-existence.",
            "Scheduled dates in past government announcements do not alone prove actual completion.",
            "All 49 remain not_verified; candidate review_status stays pending.",
        ],
        "records": rows,
    }


def markdown_worksheet(worksheet):
    lines = [
        "# 49 条证据核验工作表 — NOT VERIFIED / 尚未完成全部核验", "",
        "整体放行：**FAIL**。全部记录保持 `pending`；没有生成任何 `verified` 记录。", "",
        "原 33 条未来候选 + 12 条分层边界 + 4 条扩展记录。每条完整的来源 URL、来源类型、访问状态、",
        "核验时间、举办日期、活动状态和结论见同名 JSON 的 `records`。本表不写回生产快照。", "",
        f"本轮补充了 {worksheet['supplemented_record_count']} 条记录的证据观察；其余沿用原报告并保留原核验时间。", "",
        "| event_id | 城市 / 精确名称 | 人工日期证据 | 规则分类 | 核验状态 | 证据 | checked_at |", "|---|---|---|---|---|---|---|",
    ]
    for row in worksheet["records"]:
        title = row["event_name"].replace("|", "\\|").replace("\n", " ")
        manual_date = str(row["manual_event_date"] or "尚未确认").replace("|", "\\|")
        lines.append(f"| `{row['event_id']}` | {row['city_name']} / {title} | {manual_date} | {row['latest_primary_bucket']} | not_verified / pending | {'/'.join(row['evidence_refs'])} | {row['checked_at']} |")
    lines.extend(["", "## 重放", "", "```text", "python scripts/build_verification_worksheet.py", "```", "",
                  "输入是原始快照、原人工报告、固定样本清单和证据补查 JSON；无网络调用，审计输出禁止写入 `site/`。", ""])
    return "\n".join(lines)


def main():
    validate_report_paths(SNAPSHOT, JSON_OUTPUT, MD_OUTPUT)
    worksheet = build_worksheet()
    JSON_OUTPUT.write_text(json.dumps(worksheet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown_worksheet(worksheet), encoding="utf-8")
    print(json.dumps({key: worksheet[key] for key in (
        "status", "release_result", "sample_count", "supplemented_record_count", "future_candidate_count",
        "manual_verified_count", "production_snapshot_written",
    )}))


if __name__ == "__main__":
    main()
