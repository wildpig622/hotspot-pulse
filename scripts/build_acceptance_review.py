#!/usr/bin/env python3
"""Build a report-only acceptance packet; never change collection/review state."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.audit_snapshot import validate_report_paths
from scripts.build_verification_worksheet import COMPLETE_DATE_EVIDENCE_RESULTS, SNAPSHOT, build_worksheet

CONTEXT = ROOT / "docs/acceptance-context-2026-10-29.json"
SELECTION = ROOT / "tests/fixtures/manual-audit-2026-10-29.json"
JSON_OUTPUT = ROOT / "docs/acceptance-review-2026-10-29.json"
MD_OUTPUT = ROOT / "docs/acceptance-review-2026-10-29.md"


def valid_disposition_exception(row, selection):
    exception = row.get("disposition_exception") or {}
    return all((
        selection["excluded_future_ids"].get(row["event_id"]) == "conditional_event",
        exception.get("scope") == "candidate_disposition_only",
        exception.get("reason_code") == "conditional_event",
        exception.get("event_confirmed") is False,
        exception.get("requires_official_confirmation_to_promote") is True,
        row["manual_event_date"] is None,
        not row["is_future_candidate_after_fix"],
        row["latest_primary_bucket"] == "event_date_review",
        "conditional_event" in row["future_exclusion_reasons"],
        row["review_status_before"] == row["review_status_after"] == "pending",
        row["verification_status"] == "not_verified",
        bool(re.search(r"审批中|或定档", row["event_name"])),
    ))


def assess_case(row, selection):
    is_original_future = row["sample_group"] == "original_future_33"
    excluded_reason = selection["excluded_future_ids"].get(row["event_id"])
    if is_original_future:
        exclusion_supported = excluded_reason in row["future_exclusion_reasons"] or (
            excluded_reason == "numeric_quantity_date" and row.get("legacy_start_at") is not None and
            row.get("rule_start_at") is None and bool(re.search(r"\d+\.\d+万(?:人|名|件|通|跑者)", row["event_name"]))
        )
        classification_ok = (
            not row["is_future_candidate_after_fix"] and exclusion_supported
            if excluded_reason else row["is_future_candidate_after_fix"]
        )
    else:
        classification_ok = row["latest_primary_bucket"] == selection["boundary_expected_buckets"][row["event_id"]]
    exception_ok = valid_disposition_exception(row, selection) if row.get("disposition_exception") else False
    evidence_ok = row["strict_authority_result"] in COMPLETE_DATE_EVIDENCE_RESULTS or (
        row["strict_authority_result"] == "classification_supported_non_event_body" and
        row["latest_primary_bucket"] in {"guides_other", "schedule_roundup"}
    ) or exception_ok
    if row["is_future_candidate_after_fix"]:
        evidence_ok = row["strict_authority_result"] in {"date_supported_primary_body", "date_supported_day_precision"}
    metadata_ok = all(row.get(key) for key in ("event_id", "city_name", "event_name", "checked_at", "conclusion")) and any(
        all(source.get(key) for key in ("url", "source_type", "access_status", "checked_at"))
        for source in row["sources"]
    )
    pending_ok = row["review_status_before"] == row["review_status_after"] == "pending" and row["verification_status"] == "not_verified"
    return {
        "classification_ok": bool(classification_ok), "evidence_for_disposition_ok": bool(evidence_ok),
        "evidence_record_complete": bool(metadata_ok), "pending_preserved": pending_ok,
        "documented_exception_used": exception_ok,
        "disposition_result": "PASS" if classification_ok and evidence_ok and metadata_ok and pending_ok else "FAIL",
    }


def build_acceptance():
    worksheet = build_worksheet()
    context = json.loads(CONTEXT.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    original = [row for row in worksheet["records"] if row["sample_group"] != "expanded_4"]
    if len(original) != 45 or len({row["event_id"] for row in original}) != 45:
        raise ValueError("acceptance must cover exactly the original 45 cases")
    records = []
    for row in original:
        records.append({
            **{key: row[key] for key in ("event_id", "sample_group", "city_name", "event_name", "manual_event_date", "event_status", "latest_primary_bucket", "strict_authority_result", "review_status_after", "verification_status", "checked_at", "evidence_refs", "sources", "conclusion", "disposition_exception")},
            "quality_reviewed_at": context["quality_reviewed_at"],
            **assess_case(row, selection),
        })
    blocked = [row["event_id"] for row in records if row["disposition_result"] != "PASS"]
    return {
        "status": "REVIEW_READY_NOT_VERIFIED",
        "candidate_disposition_acceptance": "FAIL" if blocked else "PASS",
        "strict_release_result": worksheet["release_result"],
        "remote_pr_merge_recommendation": "DO_NOT_MERGE_CURRENT_REMOTE_HEAD",
        "baseline_commit": worksheet["baseline_commit"], "context": context,
        "sample_counts": {"original_future": 33, "boundary": 12, "total": 45},
        "accepted_disposition_count": len(records) - len(blocked), "blocked_disposition_event_ids": blocked,
        "documented_exception_event_ids": [row["event_id"] for row in records if row["documented_exception_used"]],
        "factual_confirmation_gaps": worksheet["explicit_evidence_gaps"],
        "release_gates": worksheet["release_gates"],
        "future_date_evidence_coverage": worksheet["future_date_evidence_coverage"],
        "source_corrections": worksheet["source_corrections"],
        "manual_verified_count": 0, "snapshot_sha256": worksheet["snapshot_sha256"],
        "production_snapshot_written": False, "live_collection_run": False,
        "records": records,
    }


def markdown_review(report):
    context = report["context"]
    lines = [
        "# 45条必选样本集中验收与审阅包", "",
        f"集中复核截止：`{context['quality_reviewed_at']}`。独立分支 `{context['branch']}`；规则审查基线 `{context['rules_review_base_commit']}`。", "",
        f"**候选处置验收：{report['candidate_disposition_acceptance']}（{report['accepted_disposition_count']}/45）。严格放行：{report['strict_release_result']}。全部记录仍NOT VERIFIED / pending。**", "",
        "原33条候选中19条保留且有日级日期依据、14条明确排除；12条边界逐条保持预期分类。新增南宁1条不替换原样本，当前未来集合共20条。", "",
        "## 刘宇例外的复核结论", "",
        "`evt_21064dd8a66c` 原文明确‘审批中/或定档’，规则标记conditional_event，未进入未来视图且保持pending，人工确认日期为空。它满足用户原先允许的排除例外，**不阻塞候选处置验收**；无需反复搜索官宣来证明排除正确。活动是否存在、是否举办及是否取消仍未确认，不能以搜索无结果作核验。", "",
        "前轮把该条的事实确认缺口直接当作唯一处置阻塞，混合了两个判断。本包修正这一口径，同时保留历轮FAIL报告、事实缺口和原始来源追溯。没有把候选处置PASS改写为全部事实或正式经营放行PASS。", "",
        "## 对照五项放行门槛", "",
        "| 门槛 | 结果 | 范围 |", "|---|---|---|",
        f"| 原33条日期支持或明确排除并pending | {report['release_gates']['original_33_date_supported_or_excluded']['result']} | 19条日期支持、14条排除，含刘宇的明示例外 |",
        f"| 12条边界分类正确 | {report['release_gates']['boundary_12_classification']['result']} | 分类验收，不为攻略里的子活动背书 |",
        f"| 零个已知严重分类/日期错误 | {report['release_gates']['known_serious_error_regressions']['result']} | 仅固定快照的已知回归范围 |",
        "| 样本证据记录完整、权威事实完整 | 记录完整性PASS；严格事实完备FAIL | 原45条均有可追溯记录；刘宇事实仍未知，限定字段也未全部确认 |",
        f"| 不自动升级verified | {report['release_gates']['no_automatic_verified']['result']} | 工作表49条和原快照457条均pending |",
        "| 整体严格放行 | FAIL | 保持不合并、不部署、不启用定时采集、不接入正式经营判断 |", "",
        "## 来源复查与限制", "",
        "本轮重新处理了此前仅继承初始报告的21条样本，并复核其余24条已有观察的依据和适用范围。原45条逐条均有本表结论；先前读过的来源保留原checked_at，不伪装成本轮全部重新打开。", "",
        "- E18普通账号的官方身份更正继续有效；肖战日期由工作室原海报支持。E26也已更正为媒体评论；徐州演出日期另由实际确认署名的徐州警方政务号支持。",
        "- 沈马官网读取超时，改用辽宁省政府转载新华社的2026年9月报道；未采用检索中的2025年9月14日旧赛事。",
        "- 成都规程、珠海展会详情等只支持原定日期；实际完成状态另列来源，不能单凭日历已过去就宣布完成。",
        "- 攻略和排期只核内容分类；南京攻略当前可见标题/作者/元信息及平台AI摘要，未把摘要当原文或采信其中日期、票务保证。",
        *[f"- {item}" for item in context["qualifications"][:2]], "",
        "## 45条逐项结论", "",
        "完整来源URL、类型、访问状态、日期和来源核验时间见同名JSON的records。下列PASS仅指候选处置；每条verification_status均为not_verified。", "",
        "| event_id | 城市 / 精确名称 | 最终分类 | 处置 | 证据 | 来源checked_at |", "|---|---|---|---|---|---|",
    ]
    for row in report["records"]:
        name = row["event_name"].replace("|", "\\|").replace("\n", " ")
        result = row["disposition_result"] + ("（排除例外）" if row["documented_exception_used"] else "")
        lines.append(f"| `{row['event_id']}` | {row['city_name']} / {name} | {row['latest_primary_bucket']} | {result} | {'/'.join(row['evidence_refs'])} | {row['checked_at']} |")
    lines += ["", "## 代码审阅和远端PR", "",
        f"GitHub插件只读观察：[PR #1]({context['remote_pr']['url']}) 仍open/draft、未合并，head为`{context['remote_pr']['head_sha']}`。本地修复尚未包含在该远端head中，**不建议合并当前原PR**；本地验收结果不适用于旧代码。", "",
        "待审本地变更处理数量误当日期、旧日期重新混入、城市错配、条件性消息、相邻日期角色和无依据跨年，并增加前端直接读取旧快照时的保护。未更改生产JSON、采集或部署工作流。准备好的本地变更可供代码审查，不需要等待刘宇官宣；实际发布仍不在本次授权范围。", "",
        "## 离线重放", "", "```text", "python scripts/build_verification_worksheet.py", "python scripts/build_acceptance_review.py", "python -m unittest discover -s tests", "node --test tests/test_site.js", "```", "",
        f"固定生产快照SHA-256：`{report['snapshot_sha256']}`。这两个生成脚本无网络调用，不采集、不更改review_status，并拒绝输出到site/。", ""]
    return "\n".join(lines)


def main():
    validate_report_paths(SNAPSHOT, JSON_OUTPUT, MD_OUTPUT)
    report = build_acceptance()
    JSON_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUTPUT.write_text(markdown_review(report), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "candidate_disposition_acceptance", "accepted_disposition_count", "strict_release_result", "manual_verified_count")}))


if __name__ == "__main__":
    main()
