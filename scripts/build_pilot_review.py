#!/usr/bin/env python3
"""Prepare human sign-off packets without approving or changing any event."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.audit_snapshot import validate_report_paths
from scripts.build_verification_worksheet import SNAPSHOT, build_worksheet

GROUPS_FILE = ROOT / "docs/pilot-review-groups-2026-10-29.json"
JSON_OUTPUT = ROOT / "docs/pilot-review-2026-10-29.json"
MD_OUTPUT = ROOT / "docs/pilot-review-2026-10-29.md"


def build_pilot_review(worksheet=None, definitions=None):
    worksheet = build_worksheet() if worksheet is None else worksheet
    definitions = json.loads(GROUPS_FILE.read_text(encoding="utf-8")) if definitions is None else definitions
    candidates = {row["event_id"]: row for row in worksheet["records"] if row["is_future_candidate_after_fix"]}
    members = [event_id for group in definitions["groups"] for event_id in group["event_ids"]]
    if len(members) != len(set(members)) or set(members) != set(candidates):
        raise ValueError("groups must cover each future candidate exactly once")
    group_ids = [group["group_id"] for group in definitions["groups"]]
    if len(group_ids) != len(set(group_ids)):
        raise ValueError("review group identifiers must be distinct")
    groups = []
    for group in definitions["groups"]:
        rows = [candidates[event_id] for event_id in group["event_ids"]]
        if not rows or any(row["city_name"] != group["city_name"] for row in rows):
            raise ValueError("a proposed group cannot mix cities or be empty")
        dates = {tuple(re.findall(r"\d{4}-\d{2}-\d{2}", row["manual_event_date"])) for row in rows}
        if len(dates) != 1 or not next(iter(dates)):
            raise ValueError("conflicting or absent date evidence requires separate review")
        if any(row["review_status_after"] != "pending" or row["verification_status"] != "not_verified" for row in rows):
            raise ValueError("this packet cannot consume or create approved records")
        sources = {}
        for row in rows:
            for source in row["sources"]:
                sources[(source["url"], source["source_type"], source["checked_at"])] = dict(source)
        groups.append({
            **group, "status": "awaiting_human_signoff", "verification_status": "not_verified",
            "date_evidence_summary": rows[0]["manual_event_date"],
            "date_evidence_start": next(iter(dates))[0],
            "evidence_refs": sorted({ref for row in rows for ref in row["evidence_refs"]}),
            "source_observations": list(sources.values()),
            "records": [{key: row[key] for key in ("event_id", "event_name", "city_name", "rule_start_at", "rule_end_at", "manual_event_date", "event_status", "strict_authority_result", "checked_at", "conclusion", "review_status_after", "verification_status")} for row in rows],
            "human_signoff": {"decision": None, "reviewer": None, "signed_at": None, "identity_and_city_confirmed": None,
                              "confirmed_date_or_range": None, "source_status_rechecked_at": None, "notes": None},
        })
    groups.sort(key=lambda group: (group["date_evidence_start"], group["group_id"]))
    return {
        "status": "NOT_VERIFIED_AWAITING_HUMAN_SIGNOFF", "grouping_scope": "report_only_proposal_not_production_deduplication",
        "audit_date": worksheet["audit_date"], "snapshot_sha256": worksheet["snapshot_sha256"],
        "candidate_record_count": len(members), "proposed_activity_group_count": len(groups),
        "manual_verified_count": 0, "release_result": "FAIL_NOT_VERIFIED", "production_snapshot_written": False,
        "source_time_policy": "Preserve original checked_at; sources have not been reopened by this generator.",
        "groups": groups,
    }


def markdown_report(report):
    lines = ["# 首批人工签核清单 — NOT VERIFIED", "",
             f"当前 {report['candidate_record_count']} 条未来候选报道整理为 **{report['proposed_activity_group_count']} 组拟签核活动**。分组仅供审阅，不是已确认活动数，没有合并生产记录，也没有自动升级 verified。", "",
             "签核前应核对活动身份、城市、举办日期/区间、来源身份及最新状态。所有签核栏留空；是否同一场活动也需人工确认。人数、消费券、票务保证及酒店需求影响未随日期证据一并确认。", "",
             "- 金华仅有协会日级日期依据，不能把索引中的08:00当作官方正文已确认。",
             "- 南宁日期有正文支持；07:30仍只有认证账号镜像佐证，不扩写为完整官方确认。",
             "- 武汉、南昌航博、昆明、郑州和长沙银发展会按证据中的完整展期审核，不能只签新闻标题的开幕日。",
             "- 刘宇等已排除候选不混入此首批清单，继续 pending；原45条和49条工作表仍保留。", "",
             "| 拟签核活动 | 城市 | 日期证据（未签核） | 报道条数 | 人工决定 |", "|---|---|---|---:|---|"]
    for group in report["groups"]:
        lines.append(f"| {group['proposed_name']} | {group['city_name']} | {group['date_evidence_summary']} | {len(group['event_ids'])} | 待签核 |")
    for group in report["groups"]:
        lines += ["", "## " + group["proposed_name"], "", f"分组ID：`{group['group_id']}`；城市：{group['city_name']}；日期证据：{group['date_evidence_summary']}。", "",
                  "人工决定：________；审核人：________；签核时间：________；确认身份/城市：________；确认日期区间：________；来源状态复查时间：________。", "",
                  "### 关联记录", ""]
        for row in group["records"]:
            lines.append(f"- `{row['event_id']}` — {row['event_name']}；规则日期 `{row['rule_start_at']}` 至 `{row['rule_end_at']}`；仍 pending / not_verified。")
        lines += ["", "### 来源及原核验时间", ""]
        for source in group["source_observations"]:
            lines.append(f"- <{source['url']}> — {source['source_type']}；访问状态 `{source['access_status']}`；checked_at `{source['checked_at']}`；支持范围：{source.get('supports', '见原工作表')}。")
    lines += ["", "## 重建与限制", "", "```text", "python scripts/build_pilot_review.py", "```", "",
              "输入为固定分组提案和原49条证据工作表的可重建来源。程序检查20条覆盖、编号唯一、同组城市与日期一致，拒绝消费已签核状态；无网络访问，禁止输出到site/。", "",
              "生成器每次产生空白签核栏。人工填写的版本应另存签核副本并保留来源，不要用重新生成覆盖已填写的副本。完成本清单不自动修改生产数据或改变正式放行结果。", ""]
    return "\n".join(lines)


def main():
    validate_report_paths(SNAPSHOT, JSON_OUTPUT, MD_OUTPUT)
    report = build_pilot_review()
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "candidate_record_count", "proposed_activity_group_count", "manual_verified_count")}))


if __name__ == "__main__":
    main()
