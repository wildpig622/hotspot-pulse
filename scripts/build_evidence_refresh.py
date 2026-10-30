#!/usr/bin/env python3
"""Summarize recorded source observations offline; never approve an event."""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.audit_snapshot import validate_report_paths
from scripts.build_pilot_review import build_pilot_review
from scripts.build_acceptance_review import build_acceptance
from scripts.build_verification_worksheet import SNAPSHOT, build_worksheet

INPUT = ROOT / "docs/evidence-refresh-input-2026-10-30.json"
JSON_OUTPUT = ROOT / "docs/activity-evidence-2026-10-30.json"
MD_OUTPUT = ROOT / "docs/activity-evidence-2026-10-30.md"
BODY_STATUSES = {"primary_body_read", "government_portal_body_read", "primary_calendar_body_read"}
AUTHORITY_TYPES = {
    "official_event_organizer", "official_exhibition_committee", "government_official_account_primary_post",
    "official_exhibition_site", "association_race_calendar", "government_portal_republication",
    "official_race_site", "official_event_operator", "district_government_portal",
}


def build_refresh(observations=None, worksheet=None, pilot=None, acceptance=None):
    observations = json.loads(INPUT.read_text(encoding="utf-8")) if observations is None else observations
    worksheet = build_worksheet() if worksheet is None else worksheet
    pilot = build_pilot_review(worksheet) if pilot is None else pilot
    acceptance = build_acceptance() if acceptance is None else acceptance
    if observations["snapshot_sha256"] != worksheet["snapshot_sha256"]:
        raise ValueError("observations must refer to the fixed audited snapshot")
    if observations["policy"]["user_per_record_signature_required"] or observations["policy"]["verified_promotion_allowed"]:
        raise ValueError("this report cannot require user signatures or promote review status")
    groups_by_id = {group["group_id"]: group for group in pilot["groups"]}
    rows_by_id = {row["event_id"]: row for row in worksheet["records"]}
    observed = observations["observations"]
    group_ids = [item["group_id"] for item in observed]
    if len(group_ids) != len(set(group_ids)) or set(group_ids) != set(groups_by_id):
        raise ValueError("observations must cover every first-batch group exactly once")
    if any(row["review_status_after"] != "pending" or row["verification_status"] != "not_verified" for row in rows_by_id.values()):
        raise ValueError("this evidence summary cannot consume verified records")
    groups = []
    refresh_by_event = {}
    for observation in observed:
        group = groups_by_id[observation["group_id"]]
        if observation["city_name"] != group["city_name"] or observation["event_name"] != group["proposed_name"]:
            raise ValueError("source observation must match the exact group identity and city")
        if not all(observation.get(key) for key in ("url", "source_type", "issuer", "checked_at", "conclusion")):
            raise ValueError("source observation metadata is incomplete")
        if observation["source_type"] not in AUTHORITY_TYPES:
            raise ValueError("non-authoritative source cannot be counted as primary evidence")
        reopened = observation["access_status"] in BODY_STATUSES
        expected_dates = re.findall(r"\d{4}-\d{2}-\d{2}", group["date_evidence_summary"])
        actual_dates = [observation["start_date"]] + ([observation["end_date"]] if observation["end_date"] else [])
        if reopened and actual_dates != expected_dates:
            raise ValueError("a changed date needs explicit review instead of silent reconciliation")
        if not reopened and any(observation.get(key) for key in ("start_date", "end_date", "local_time")):
            raise ValueError("failed or index-only access cannot create current primary date evidence")
        if observation["source_type"] == "association_race_calendar" and observation["local_time"] is not None:
            raise ValueError("the day-only association observation cannot assert a start time")
        for event_id in group["event_ids"]:
            refresh_by_event[event_id] = observation
        groups.append({
            "group_id": group["group_id"], "event_name": group["proposed_name"], "city_name": group["city_name"],
            "event_ids": group["event_ids"], "candidate_record_count": len(group["event_ids"]),
            "date_evidence_summary": group["date_evidence_summary"],
            "start_date": expected_dates[0], "end_date": expected_dates[1] if len(expected_dates) > 1 else None,
            "current_primary_local_time": observation["local_time"] if reopened else None,
            "source_refresh_result": "PRIMARY_DATE_REOPENED" if reopened else "NOT_REOPENED_PRIOR_EVIDENCE_ONLY",
            "date_evidence_precision": "minute" if reopened and observation["local_time"] else "day",
            "event_status": "scheduled_window_starts_today_not_opening_confirmed" if expected_dates[0] == observations["review_date"] else "scheduled_not_actual_occurrence_confirmed",
            "review_status": "pending", "verification_status": "not_verified",
            "source_refresh_attempted_at": observation["checked_at"],
            "current_observation": copy.deepcopy(observation),
            "prior_source_observations": copy.deepcopy(group["source_observations"]),
            "conclusion": observation["conclusion"],
        })
    records = []
    keys = ("event_id", "sample_group", "city_name", "event_name", "manual_event_date", "event_status",
            "latest_primary_bucket", "strict_authority_result", "review_status_after", "verification_status",
            "checked_at", "sources", "conclusion", "disposition_exception")
    for row in worksheet["records"]:
        item = {key: copy.deepcopy(row[key]) for key in keys}
        observation = refresh_by_event.get(row["event_id"])
        item["current_round_observation"] = copy.deepcopy(observation) if observation else None
        item["source_refresh_result"] = (
            "PRIMARY_DATE_REOPENED" if observation and observation["access_status"] in BODY_STATUSES else
            "NOT_REOPENED_PRIOR_EVIDENCE_ONLY" if observation else "INHERITED_NOT_REOPENED_THIS_ROUND"
        )
        records.append(item)
    reopened_groups = [group for group in groups if group["source_refresh_result"] == "PRIMARY_DATE_REOPENED"]
    return {
        "status": "EVIDENCE_SUMMARY_NOT_VERIFIED", "review_date": observations["review_date"],
        "reviewed_at": observations["reviewed_at"], "reviewed_code_head": observations["reviewed_code_head"],
        "baseline_commit": worksheet["baseline_commit"], "snapshot_sha256": worksheet["snapshot_sha256"],
        "policy": copy.deepcopy(observations["policy"]),
        "candidate_record_count": pilot["candidate_record_count"], "activity_group_count": len(groups),
        "current_primary_reopened_group_count": len(reopened_groups),
        "current_primary_reopened_record_count": sum(group["candidate_record_count"] for group in reopened_groups),
        "prior_evidence_only_group_ids": [group["group_id"] for group in groups if group not in reopened_groups],
        "required_sample_count": 45, "worksheet_record_count": len(records),
        "required_sample_disposition_result": acceptance["candidate_disposition_acceptance"],
        "original_release_gates": copy.deepcopy(acceptance["release_gates"]),
        "strict_release_result": acceptance["strict_release_result"],
        "strict_failure_scope": "Original strict factual completeness remains FAIL; an unconfirmed excluded case is not a candidate-disposition blocker. Blank user signatures are not a release gate.",
        "execution_authorization": "NO_MERGE_DEPLOY_COLLECTION_OR_SCHEDULE_AUTHORIZED",
        "manual_verified_count": 0, "production_snapshot_written": False, "live_collection_run": False,
        "time_policy": "Per-record checked_at and prior source timestamps are preserved. current_round_observation.checked_at records this round; a failed attempt never refreshes prior evidence.",
        "original_audit_retrieval": copy.deepcopy(observations["original_audit_retrieval"]),
        "source_access_limitations": copy.deepcopy(observations["access_limitations"]),
        "scope_notes": copy.deepcopy(observations["scope_notes"]),
        "groups": groups, "records": records,
    }


def markdown_report(report):
    lines = ["# 首批活动证据汇总（2026-10-30）", "",
        "**不要求用户逐条签字。所有记录继续 pending / not_verified；本报告只记录公开证据与限制。**", "",
        f"本轮检查{report['activity_group_count']}组、{report['candidate_record_count']}条候选报道；其中{report['current_primary_reopened_group_count']}组、{report['current_primary_reopened_record_count']}条重新读到权威正文或协会日历。南宁2条仅保留昨天的正文证据，本轮未能重新读取。", "",
        "## 可直接查看的汇总", "",
        "| 活动 | 城市 | 公告举办日 / 展期 | 本轮证据 | 报道条数 |", "|---|---|---|---|---:|"]
    for group in report["groups"]:
        period = group["start_date"] + (" 至 " + group["end_date"] if group["end_date"] else "")
        result = "权威正文已重读" if group["source_refresh_result"] == "PRIMARY_DATE_REOPENED" else "未重读，仅历史依据"
        if group["current_observation"]["source_type"] == "association_race_calendar":
            result = "协会日历已重读，仅日级"
        lines.append(f"| {group['event_name']} | {group['city_name']} | {period} | {result} | {group['candidate_record_count']} |")
    lines += ["", "## 放行判断", "",
        "| 判断 | 结果 | 含义 |", "|---|---|---|",
        "| 原33条日期支持或明确排除并pending | PASS | 沿用原固定样本19条有日期、14条排除的验收 |",
        "| 12条边界分类 | PASS | 沿用逐条分类与浏览器验收，本轮未重新打开全部来源 |",
        "| 已知严重日期 / 城市 / 分类错误回归 | PASS | 限已测试的固定快照与候选集合 |",
        "| 证据记录字段完整 | PASS | 49条含原45条保留event_id、URL/类型、城市/名称、日期或未知、状态、时间与结论 |",
        "| 严格全部事实完备 | FAIL | 保留原严格口径；被排除的刘宇安排仍未知，不因此阻塞候选处置 |",
        "| 不自动升级verified | PASS | 457条生产记录与49条审计记录保持pending |",
        "| 用户逐条签字 | 不要求 | 旧空白模板可作自愿审核工具，不是新增门槛 |",
        "| 合并 / 上线 / 采集 / 定时 | 未授权执行 | 继续遵守用户现有限制 |", "",
        "南宁本轮读取失败只表示证据新鲜度未恢复，不证明赛事取消或改期。金华日历的00:00:00不作为起跑时刻；08:00仍仅有官网检索索引。南宁07:30的辅助来源限制也保留。武汉按公告今天进入展期，未据此宣布已开幕。", "",
        "## 逐组来源与精确编号", ""]
    for group in report["groups"]:
        source = group["current_observation"]
        lines += ["### " + group["event_name"], "",
            "关联event_id：" + "、".join("`" + event_id + "`" for event_id in group["event_ids"]) + "。", "",
            f"来源：[公开页面]({source['url']})；类型：`{source['source_type']}`；发布者：{source['issuer']}。",
            f"访问状态：`{source['access_status']}`；checked_at：`{source['checked_at']}`；事件状态：`{group['event_status']}`。", "",
            source["conclusion"], ""]
    lines += ["## 时间、历史记录与复现", "",
        "同名JSON含49条完整身份记录、原45条分层与12条边界，以及各自历史来源和时间。本轮只刷新首批20条的来源，原记录checked_at没有被批量覆盖。",
        "2026-10-29的审计、验收和空白签核模板作为历史文件保留；它们的FAIL不能解释为必须请用户逐条签字。", "",
        "公开检索工具可能返回缓存页；checked_at表示本轮读取时间，不保证源站在该时刻实时返回，也不保证没有尚未收录的新公告。", "",
        "本轮通过GitHub插件重读了75e83e9下的原审计JSON和报告。原JSON仅列8个未来示例；完整33条及12条边界来自固定快照的既有49条工作表，完整编号在同名JSON中保留。", "",
        "```text", "python scripts/build_evidence_refresh.py", "```", "",
        "重建只读取固定历史快照、既有证据和本轮人工记录，不联网、不采集、不改写site/。输入为docs/evidence-refresh-input-2026-10-30.json。", "",
        "首次20条的活动分组仅供报告阅读；没有执行生产去重、确认酒店需求或签署任何记录。官方公告仍不保证活动实际按期举行。", ""]
    return "\n".join(lines)


def main():
    validate_report_paths(SNAPSHOT, JSON_OUTPUT, MD_OUTPUT)
    report = build_refresh()
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown_report(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("candidate_record_count", "activity_group_count", "current_primary_reopened_group_count", "current_primary_reopened_record_count", "strict_release_result", "manual_verified_count")}))


if __name__ == "__main__":
    main()
