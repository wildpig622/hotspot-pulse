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
SUPPLEMENTS = (
    ROOT / "docs/evidence-supplement-2026-10-29.json",
    ROOT / "docs/evidence-round3-2026-10-29.json",
    ROOT / "docs/evidence-round4-2026-10-29.json",
    ROOT / "docs/evidence-round5-2026-10-29.json",
    ROOT / "docs/evidence-round6-2026-10-29.json",
)
SUPPORTED_DATE_RESULTS = {"date_supported_primary_body", "date_supported_day_precision"}
COMPLETE_DATE_EVIDENCE_RESULTS = SUPPORTED_DATE_RESULTS | {"date_supported_for_exclusion"}
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
                 "access_status": "inherited_from_initial_report", "checked_at": checked_at}
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
    rounds = [json.loads(path.read_text(encoding="utf-8")) for path in SUPPLEMENTS]
    corrections = {
        correction["url"]: dict(correction, checked_at=evidence_round["checked_at"])
        for evidence_round in rounds for correction in evidence_round.get("source_corrections", [])
    }
    prior = read_manual_report()
    reviewed = build_report(payload, date.fromisoformat(selection["today"]))
    raw_by_id = {event["event_id"]: event for event in payload["data"]}
    audit_by_id = {event["event_id"]: event for event in reviewed["records"]}
    expanded_ids = selection["additional_supported_future_ids"] + selection["legacy_rollover_ids"]
    selected_ids = list(prior) + expanded_ids
    if len(selected_ids) != 49 or len(set(selected_ids)) != 49:
        raise ValueError("worksheet must contain 49 distinct IDs")
    supplements, observations = {}, {}
    for number, evidence_round in enumerate(rounds, start=2):
        seen = set()
        for group in evidence_round["groups"]:
            observed = dict(group, checked_at=evidence_round["checked_at"], round_id=f"round_{number}")
            observed["sources"] = [dict(source, checked_at=evidence_round["checked_at"]) for source in group["sources"]]
            for event_id in group["event_ids"]:
                if event_id not in selected_ids or event_id in seen:
                    raise ValueError(f"invalid or duplicated supplement ID in a round: {event_id}")
                seen.add(event_id)
                supplements[event_id] = observed
                observations.setdefault(event_id, []).append(observed)

    rows = []
    for event_id in selected_ids:
        original, audited = raw_by_id[event_id], audit_by_id[event_id]
        old = prior.get(event_id, {})
        additional = supplements.get(event_id)
        if original["review_status"] != "pending" or audited["review_status"] != "pending":
            raise ValueError("this fixed worksheet is not authorized to alter review status")
        sources = [dict(source) for source in old.get("sources", [])]
        history = observations.get(event_id, [])
        sources.extend(dict(source) for observation in history for source in observation["sources"])
        for source in sources:
            correction = corrections.get(source["url"])
            if correction:
                source["original_source_type"] = source["source_type"]
                source["source_type"] = correction["source_type"]
                source["issuer"] = correction["issuer"]
                source["authority_claim_withdrawn"] = True
                source["source_correction"] = correction
        if additional and additional.get("disposition_exception"):
            next_action = "retain pending and excluded; official confirmation is required before factual promotion, not to justify the documented exclusion"
        elif additional and additional["strict_authority_result"] == "classification_supported_non_event_body":
            next_action = "retain pending; classification only, do not promote advertised sub-events without separate authority evidence"
        elif additional and additional["strict_authority_result"] in COMPLETE_DATE_EVIDENCE_RESULTS:
            next_action = "retain pending; human sign-off still required"
        else:
            next_action = "retain pending; complete primary source/body and identity check before any release"
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
            "checked_at": additional["checked_at"] if additional else old["checked_at"],
            "prior_checked_at": old.get("checked_at"),
            "evidence_refs": old.get("evidence_refs", []) + [observation["id"] for observation in history],
            "evidence_observation_history": [
                {key: observation[key] for key in ("id", "round_id", "checked_at", "evidence_result", "strict_authority_result", "conclusion")}
                for observation in history
            ],
            "sources": sources,
            "evidence_result": additional["evidence_result"] if additional else old["evidence_result"],
            "strict_authority_result": additional["strict_authority_result"] if additional else "not_reassessed_after_initial_report",
            "disposition_exception": additional.get("disposition_exception") if additional else None,
            "conclusion": additional["conclusion"] if additional else old["conclusion"],
            "latest_primary_bucket": audited["primary_bucket"],
            "is_future_candidate_after_fix": audited["primary_bucket"] == "future_dated_event",
            "future_exclusion_reasons": audited["future_exclusion_reasons"],
            "next_action": next_action,
        })
    if SNAPSHOT.read_bytes() != original_bytes:
        raise RuntimeError("input snapshot changed while building the worksheet")
    future_rows = [row for row in rows if row["is_future_candidate_after_fix"]]
    supported_ids = [row["event_id"] for row in future_rows if row["strict_authority_result"] in SUPPORTED_DATE_RESULTS]
    body_ids = [row["event_id"] for row in future_rows if row["strict_authority_result"] == "date_supported_primary_body"]
    by_id = {row["event_id"]: row for row in rows}
    original_future = [row for row in rows if row["sample_group"] == "original_future_33"]
    original_supported = [row["event_id"] for row in original_future if row["is_future_candidate_after_fix"] and row["event_id"] in supported_ids]
    original_excluded = [row["event_id"] for row in original_future if not row["is_future_candidate_after_fix"] and row["event_id"] in selection["excluded_future_ids"]]
    boundary_mismatches = [event_id for event_id, bucket in selection["boundary_expected_buckets"].items() if by_id[event_id]["latest_primary_bucket"] != bucket]
    expected_future_ids = set(selection["expected_future_ids"] + selection["additional_supported_future_ids"])
    actual_future_ids = {row["event_id"] for row in reviewed["records"] if row["primary_bucket"] == "future_dated_event"}
    evidence_gaps = rounds[-1].get("explicit_evidence_gaps", [])
    if any(gap["event_id"] not in by_id for gap in evidence_gaps):
        raise ValueError("evidence gap must reference an exact worksheet record")
    return {
        "status": "NOT_VERIFIED",
        "release_result": "FAIL",
        "baseline_commit": selection["baseline_commit"],
        "audit_date": selection["today"],
        "supplement_checked_at": rounds[-1]["checked_at"],
        "evidence_round_files": [str(path.relative_to(ROOT)).replace("\\", "/") for path in SUPPLEMENTS],
        "source_corrections": list(corrections.values()),
        "explicit_evidence_gaps": evidence_gaps,
        "release_gates": {
            "original_33_date_supported_or_excluded": {
                "result": "PASS" if len(original_supported) + len(original_excluded) == 33 else "FAIL",
                "date_supported_count": len(original_supported), "explicitly_excluded_count": len(original_excluded),
                "excluded_event_ids": original_excluded,
            },
            "boundary_12_classification": {"result": "FAIL" if boundary_mismatches else "PASS", "mismatch_event_ids": boundary_mismatches},
            "known_serious_error_regressions": {
                "result": "PASS" if actual_future_ids == expected_future_ids and not boundary_mismatches else "FAIL",
                "unexpected_future_event_ids": sorted(actual_future_ids - expected_future_ids),
                "missing_expected_future_event_ids": sorted(expected_future_ids - actual_future_ids),
                "scope": "Known fixed-snapshot errors and exact candidate set only; not proof that all factual fields are error-free.",
            },
            "complete_authority_evidence": {"result": "FAIL" if evidence_gaps else "REQUIRES_FINAL_MANUAL_REVIEW", "explicit_gap_event_ids": [gap["event_id"] for gap in evidence_gaps], "scope": "Factual verification gaps; distinct from documented withheld/pending disposition exceptions. No promotion to verified."},
            "no_automatic_verified": {"result": "PASS" if all(row["review_status_after"] == "pending" and row["verification_status"] == "not_verified" for row in rows) else "FAIL"},
        },
        "snapshot_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "sample_count": len(rows),
        "sample_counts": {"original_future": 33, "stratified_boundary": 12, "expanded": 4},
        "supplemented_record_count": len(supplements),
        "manual_verified_count": 0,
        "future_candidate_count": sum(row["is_future_candidate_after_fix"] for row in rows),
        "future_date_evidence_coverage": {
            "supported_count": len(supported_ids),
            "official_body_supported_count": len(body_ids),
            "association_day_only_count": len(supported_ids) - len(body_ids),
            "incomplete_count": len(future_rows) - len(supported_ids),
            "supported_event_ids": supported_ids,
            "incomplete_event_ids": [row["event_id"] for row in future_rows if row["event_id"] not in supported_ids],
        },
        "production_snapshot_written": False,
        "live_collection_run": False,
        "limitations": [
            "Prior source evidence is inherited, not represented as independently re-opened.",
            "Search-index text, authenticated mirrors and inaccessible primary pages are distinguished per source.",
            "No matching search result is not evidence of cancellation or non-existence.",
            "Scheduled dates in past government announcements do not alone prove actual completion.",
            "Date-supported is not a verified review status. All 49 remain not_verified/pending.",
        ],
        "records": rows,
    }


def markdown_worksheet(worksheet):
    lines = [
        "# 49 条证据核验工作表 — NOT VERIFIED / 尚未完成全部核验", "",
        "整体放行：**FAIL**。全部记录保持 `pending`；没有生成任何 `verified` 记录。", "",
        "原 33 条未来候选 + 12 条分层边界 + 4 条扩展记录。每条完整的来源 URL、来源类型、访问状态、",
        "核验时间、举办日期、活动状态和结论见同名 JSON 的 `records`。本表不写回生产快照。", "",
        f"累计补充了 {worksheet['supplemented_record_count']} 条记录的证据观察；其余沿用原报告并保留原核验时间。", "",
        f"当前{worksheet['future_candidate_count']}条未来候选中，{worksheet['future_date_evidence_coverage']['supported_count']}条有累计日级日期支持，其中{worksheet['future_date_evidence_coverage']['official_body_supported_count']}条为官方正文；尚缺日期依据{worksheet['future_date_evidence_coverage']['incomplete_count']}条。日期支持不等于已核验状态。", "",
        "来源身份更正与明确证据缺口见同名 JSON 的 source_corrections 和 explicit_evidence_gaps；初始E18普通账号的官方身份判断已撤回。", "",
        "| event_id | 城市 / 精确名称 | 人工日期证据 | 规则分类 | 核验状态 | 证据 | checked_at |", "|---|---|---|---|---|---|---|",
    ]
    for row in worksheet["records"]:
        title = row["event_name"].replace("|", "\\|").replace("\n", " ")
        manual_date = str(row["manual_event_date"] or "尚未确认").replace("|", "\\|")
        lines.append(f"| `{row['event_id']}` | {row['city_name']} / {title} | {manual_date} | {row['latest_primary_bucket']} | not_verified / pending | {'/'.join(row['evidence_refs'])} | {row['checked_at']} |")
    lines.extend(["", "## 重放", "", "```text", "python scripts/build_verification_worksheet.py", "```", "",
                  "输入是原始快照、原人工报告、固定样本清单和各轮证据补查 JSON；保留历轮证据状态，不覆写旧观察；无网络调用，审计输出禁止写入 `site/`。", ""])
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
