#!/usr/bin/env python3
"""Discover public event candidates from Google News RSS and publish static JSON."""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE_API = ROOT / "site" / "api" / "v1"
CITIES_FILE = ROOT / "config" / "cities.json"
UTC = timezone.utc
BEIJING = timezone(timedelta(hours=8))
KEYWORDS = (
    "演唱会", "音乐节", "展会", "博览会", "马拉松", "体育赛事",
    "赛事", "演出", "漫展", "节庆", "车展", "展览", "巡演",
    "音乐会", "嘉年华", "文化节", "美食节", "灯会", "庙会"
)

GUIDE_TERMS = (
    "有哪些", "有什么", "攻略", "指南", "购票平台", "票务平台", "怎么买票",
    "怎么买", "如何", "怎么预约", "靠谱", "推荐", "观演攻略", "出行攻略",
    "门票价格", "购票教程", "抢票技巧", "有哪些平台"
)
SCHEDULE_ROUNDUP_TERMS = (
    "排期", "排期表", "节目单", "时间表", "日程安排", "演出安排",
    "展会安排", "演出汇总", "演出合集", "演出一览", "演出清单",
    "月度演出", "本月演出", "活动日历", "活动汇总", "展会日历"
)
TICKETING_TERMS = ("开票", "开售", "售票", "预售", "抢票", "门票", "票价", "发售", "开抢")
REGISTRATION_TERMS = (
    "报名启动", "报名开启", "报名时间", "报名截止", "报名通道",
    "开放报名", "开始报名", "报名即将开始", "报名啦", "开启报名"
)
EVENT_DATE_CUES = (
    "将于", "定于", "定档", "举行", "举办", "开幕", "开赛", "开演",
    "开跑", "启幕", "上演", "开展", "举办时间", "活动时间", "赛事时间",
    "演出时间", "比赛时间", "展出时间", "正式举行", "将举行", "将举办"
)
PAST_REPORT_TERMS = (
    "冠军诞生", "夺冠", "圆满落幕", "圆满结束", "成功举办", "顺利举行",
    "现场回顾", "精彩回顾", "赛后", "完美收官", "圆满收官", "已结束",
    "落幕", "比赛结束", "赛事回顾", "演出回顾"
)
CONDITIONAL_EVENT_PATTERN = re.compile(
    r"审批中|正在审批|待审批|尚未获批|未获批准|或(?:将|定档|于)|拟定档|暂定|待官宣|尚未官宣|网传|有望"
)
QUANTITY_SUFFIX = r"\s*(?:万|亿|千|百|人|名|件|通|元|%|％|小时|公里|万人|万名)"
NON_EVENT_CONTENT_KINDS = {"guide", "schedule_roundup", "ticketing_notice", "registration_notice"}

USER_AGENT = "HotspotPulse/0.1 (+https://github.com/wildpig622/hotspot-pulse)"
MAX_FEED_ITEMS = 20
KEEP_UNSEEN_DAYS = 90
MAX_FUTURE_DAYS = 365
MAX_PAST_DAYS = 60


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return iso_utc(parsed)
    except (TypeError, ValueError, OverflowError):
        return None


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_title(value: str) -> str:
    value = clean_html(value).lower()
    value = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{2,36}$", "", value)
    value = re.sub(r"[\s·•：:，,。！？!？【】\[\]()（）]", "", value)
    return value


def classify_event(text: str) -> str:
    value = text or ""
    if any(word in value for word in ("展会", "博览会", "展览", "茶博会", "车展", "漫展", "动漫展", "进博会")):
        return "exhibition"
    if any(word in value for word in ("马拉松", "体育赛事", "赛事", "足球", "篮球", "网球", "运动会", "路跑", "比赛")):
        return "sports"
    if any(word in value for word in ("演唱会", "音乐节", "巡演", "音乐会", "话剧", "歌剧", "演出", "livehouse")):
        return "concert"
    if any(word in value for word in ("节庆", "灯会", "庙会", "烟花", "嘉年华", "文化节", "美食节")):
        return "festival"
    return "other"


def classify_content(title: str, description: str = "") -> str:
    """Classify the information type separately from the event category."""
    title_value = clean_html(title)
    combined = (title_value + " " + clean_html(description)).strip()

    # Strong title signals take priority: a guide or roundup is not one event.
    if any(term in title_value for term in GUIDE_TERMS):
        return "guide"
    if any(term in title_value for term in SCHEDULE_ROUNDUP_TERMS):
        return "schedule_roundup"
    if any(term in title_value for term in PAST_REPORT_TERMS) or re.search(
        r"昨(?:日|天|晚)?[^，。！？；]{0,8}(?:开跑|开赛|举行|举办|开演)", title_value
    ):
        return "past_report"
    if CONDITIONAL_EVENT_PATTERN.search(combined):
        return "uncertain"

    has_event_keyword = any(term in combined for term in KEYWORDS)
    has_event_date_cue = any(term in combined for term in EVENT_DATE_CUES)
    if has_event_keyword and has_event_date_cue:
        return "event_announcement"
    if has_event_keyword and any(term in combined for term in REGISTRATION_TERMS):
        return "registration_notice"
    if any(term in combined for term in GUIDE_TERMS):
        return "guide"
    if any(term in combined for term in SCHEDULE_ROUNDUP_TERMS):
        return "schedule_roundup"
    if any(term in combined for term in PAST_REPORT_TERMS):
        return "past_report"
    if any(term in combined for term in REGISTRATION_TERMS):
        return "registration_notice"
    if any(term in combined for term in TICKETING_TERMS) and not has_event_date_cue:
        return "ticketing_notice"
    if has_event_keyword:
        return "uncertain"
    return "other"


def event_identity(city_slug: str, event_name: str) -> str:
    """Stable identity independent of a possibly misread date."""
    return (city_slug or "") + "|" + normalize_title(event_name or "")


@lru_cache(maxsize=1)
def configured_cities() -> list[dict[str, Any]]:
    return json.loads(CITIES_FILE.read_text(encoding="utf-8"))


def assess_event_city(city: dict[str, Any], title: str, description: str = "") -> str:
    """Prefer the city next to the first event name over incidental city mentions."""
    event_match = re.search("|".join(map(re.escape, KEYWORDS)), title)
    hosts: list[tuple[int, str]] = []
    if event_match:
        prefix = title[max(0, event_match.start() - 18):event_match.start()]
        for configured in configured_cities():
            for alias in configured["aliases"]:
                for match in re.finditer(re.escape(alias), prefix):
                    if not re.search(r"[，。！？；,;:：]", prefix[match.end():]):
                        hosts.append((match.end(), configured["city_slug"]))
    if hosts and max(hosts)[1] != city.get("city_slug"):
        return "event_city_conflict"
    aliases = city.get("aliases") or [str(city.get("city_name", "")).removesuffix("市")]
    return "text_confirmed" if any(alias and alias in title + " " + description for alias in aliases) else "query_only"


def future_exclusion_reasons(event: dict[str, Any]) -> list[str]:
    title = event.get("event_name") or ""
    reasons = []
    if CONDITIONAL_EVENT_PATTERN.search(title) or event.get("event_confirmation") == "unconfirmed":
        reasons.append("conditional_event")
    city_match = event.get("city_match")
    if event.get("city_slug"):
        city_match = assess_event_city(event, title)
    if city_match == "event_city_conflict":
        reasons.append("event_city_conflict")
    elif city_match == "query_only":
        reasons.append("city_not_confirmed")
    # Protect readers of the unchanged legacy snapshot as well as newly parsed data.
    if event.get("start_at") and not event.get("event_date_role"):
        for match in re.finditer(r"(?<![\d./])(\d{1,2})[/.](\d{1,2})(?![\d./])" + QUANTITY_SUFFIX, title):
            if event["start_at"][5:] == f"{int(match[1]):02d}-{int(match[2]):02d}":
                reasons.append("numeric_quantity_date")
                break
    return reasons


def _date_from_parts(year: int | None, month: int, day: int, today: date) -> tuple[date | None, str]:
    try:
        candidate = date(year or today.year, month, day)
    except ValueError:
        return None, "unknown"
    if year is not None:
        return candidate, "explicit_year"
    if candidate < today - timedelta(days=2):
        # A recent past date is likely a report of a real event in the current year.
        if (today - candidate).days <= MAX_PAST_DAYS:
            return candidate, "inferred_year"
        next_year = date(today.year + 1, month, day)
        if month < today.month and 0 <= (next_year - today).days <= MAX_FUTURE_DAYS:
            return next_year, "inferred_year"
        return None, "unknown"
    return candidate, "inferred_year"


def _nearest_term_distance(text: str, start: int, end: int, terms: tuple[str, ...], radius: int = 36) -> int | None:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    window = text[left:right]
    date_center = ((start + end) / 2) - left
    distances: list[int] = []
    for term in terms:
        for match in re.finditer(re.escape(term), window):
            term_center = (match.start() + match.end()) / 2
            distances.append(int(abs(term_center - date_center)))
    return min(distances) if distances else None


def _date_role(text: str, start: int, end: int) -> str:
    # Actions in another clause must not lend their role to this date. In
    # "将于10月20日10:00开启报名，比赛时间为12月20日", the action
    # following the first date is registration, despite the preceding 将于.
    left = max([match.end() for match in re.finditer(r"[，。！？；,;]", text[:start])] or [0])
    boundary = re.search(r"[，。！？；,;]", text[end:])
    right = end + boundary.start() if boundary else len(text)
    clause = text[left:right]
    local_start, local_end = start - left, end - left
    following = clause[local_end:local_end + 24]
    following_actions = []
    for terms, role in ((EVENT_DATE_CUES, "event"), (TICKETING_TERMS, "ticket_sale"), (REGISTRATION_TERMS, "registration")):
        for term in terms:
            index = following.find(term)
            if index >= 0:
                following_actions.append((index, role))
    if following_actions:
        return min(following_actions)[1]
    text, start, end = clause, local_start, local_end
    event_distance = _nearest_term_distance(text, start, end, EVENT_DATE_CUES)
    sale_distance = _nearest_term_distance(text, start, end, TICKETING_TERMS)
    registration_distance = _nearest_term_distance(text, start, end, REGISTRATION_TERMS)

    actions = [
        (distance, role)
        for distance, role in (
            (event_distance, "event"),
            (sale_distance, "ticket_sale"),
            (registration_distance, "registration"),
        )
        if distance is not None
    ]
    if actions:
        actions.sort(key=lambda item: (item[0], 0 if item[1] == "event" else 1))
        return actions[0][1]
    return "ambiguous"


def _date_is_in_window(start: date, end: date, today: date) -> bool:
    return end >= today - timedelta(days=MAX_PAST_DAYS) and start <= today + timedelta(days=MAX_FUTURE_DAYS)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _collect_day_candidates(text: str, today: date) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    candidates: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []

    full_range = re.compile(
        r"(?<!\d)(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日\s*(?:至|到|—|－|-|~|～)\s*(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日"
    )
    short_range = re.compile(
        r"(?<!\d)(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日\s*(?:至|到|—|－|-|~|～)\s*(\d{1,2})日"
    )

    for pattern, range_kind in ((full_range, "full"), (short_range, "short")):
        for match in pattern.finditer(text):
            if any(not (match.end() <= left or match.start() >= right) for left, right in occupied):
                continue
            groups = match.groups()
            year1 = int(groups[0]) if groups[0] else None
            month1 = int(groups[1])
            day1 = int(groups[2])
            start_day, start_conf = _date_from_parts(year1, month1, day1, today)
            if not start_day:
                continue
            if range_kind == "full":
                year2 = int(groups[3]) if groups[3] else (year1 if year1 else start_day.year)
                month2 = int(groups[4])
                day2 = int(groups[5])
            else:
                year2 = year1 if year1 else start_day.year
                month2 = month1
                day2 = int(groups[3])
            try:
                end_day = date(year2, month2, day2)
            except ValueError:
                continue
            if end_day < start_day and not (groups[3] if range_kind == "full" else False):
                try:
                    end_day = date(start_day.year + 1, month2, day2)
                except ValueError:
                    continue
            if not _date_is_in_window(start_day, end_day, today):
                continue
            explicit_year = bool(year1) or (range_kind == "full" and bool(groups[3]))
            confidence = "explicit_year" if explicit_year else "inferred_year"
            candidates.append({
                "start": match.start(), "end": match.end(), "start_at": start_day.isoformat(),
                "end_at": end_day.isoformat() if end_day != start_day else None,
                "date_precision": "day", "date_confidence": confidence,
                "event_date_role": _date_role(text, match.start(), match.end()),
            })
            occupied.append((match.start(), match.end()))

    patterns = [
        re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"),
        re.compile(r"(?<!\d)(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日"),
        re.compile(r"(?<![\d./])(\d{1,2})[/.](\d{1,2})(?![\d./])"),
    ]
    for pattern_index, pattern in enumerate(patterns):
        for match in pattern.finditer(text):
            if any(not (match.end() <= left or match.start() >= right) for left, right in occupied):
                continue
            if pattern_index == 2 and re.match(QUANTITY_SUFFIX, text[match.end():]):
                continue
            if pattern_index == 0:
                year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            elif pattern_index == 1:
                year = int(match.group(1)) if match.group(1) else None
                month, day = int(match.group(2)), int(match.group(3))
            else:
                year = None
                month, day = int(match.group(1)), int(match.group(2))
            parsed, confidence = _date_from_parts(year, month, day, today)
            if not parsed or not _date_is_in_window(parsed, parsed, today):
                continue
            # Explicit ISO/Chinese dates carry the year; slash dates without a year do not.
            candidates.append({
                "start": match.start(), "end": match.end(), "start_at": parsed.isoformat(),
                "end_at": None, "date_precision": "day", "date_confidence": confidence,
                "event_date_role": _date_role(text, match.start(), match.end()),
            })
            occupied.append((match.start(), match.end()))

    # Identical matches can arise from overlapping Chinese/ISO patterns.
    unique: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for item in candidates:
        key = (item["start_at"], item["end_at"], item["event_date_role"])
        if key not in unique or item["start"] < unique[key]["start"]:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: item["start"]), occupied


def _collect_reference_periods(text: str, today: date, occupied: list[tuple[int, int]]) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    range_pattern = re.compile(
        r"(?<!\d)(?:(20\d{2})年)?\s*(\d{1,2})月?\s*(?:至|到|—|－|-|~|～)\s*(?:(20\d{2})年)?\s*(\d{1,2})月"
    )
    for match in range_pattern.finditer(text):
        if any(not (match.end() <= left or match.start() >= right) for left, right in occupied):
            continue
        year1 = int(match.group(1)) if match.group(1) else None
        month1 = int(match.group(2))
        year2 = int(match.group(3)) if match.group(3) else None
        month2 = int(match.group(4))
        if not (1 <= month1 <= 12 and 1 <= month2 <= 12):
            continue
        start_year = year1 or today.year
        if not year1 and month1 < today.month and month2 < today.month and month1 <= month2:
            start_year += 1
        end_year = year2 or start_year
        if month2 < month1 and not year2:
            end_year = start_year + 1
        try:
            start_day, _ = _month_bounds(start_year, month1)
            _, end_day = _month_bounds(end_year, month2)
        except ValueError:
            continue
        if not _date_is_in_window(start_day, end_day, today):
            continue
        periods.append({
            "start": match.start(), "reference_period_start": start_day.isoformat(),
            "reference_period_end": end_day.isoformat(), "date_precision": "month_range",
            "date_confidence": "explicit_year" if year1 or year2 else "inferred_year",
        })
        occupied.append((match.start(), match.end()))

    month_pattern = re.compile(r"(?<!\d)(?:(20\d{2})年)?\s*(\d{1,2})月(?!\d)")
    for match in month_pattern.finditer(text):
        if any(not (match.end() <= left or match.start() >= right) for left, right in occupied):
            continue
        year_text, month_text = match.groups()
        month = int(month_text)
        if not 1 <= month <= 12:
            continue
        year = int(year_text) if year_text else today.year
        if not year_text and month < today.month and (today - date(year, month, 1)).days > MAX_PAST_DAYS:
            year += 1
        try:
            start_day, end_day = _month_bounds(year, month)
        except ValueError:
            continue
        if not _date_is_in_window(start_day, end_day, today):
            continue
        periods.append({
            "start": match.start(), "reference_period_start": start_day.isoformat(),
            "reference_period_end": end_day.isoformat(), "date_precision": "month",
            "date_confidence": "explicit_year" if year_text else "inferred_year",
        })
        occupied.append((match.start(), match.end()))
    return sorted(periods, key=lambda item: item["start"])


def extract_event_date(title: str, description: str = "", today: date | None = None) -> dict[str, Any]:
    """Extract event dates separately from ticketing/registration dates and month references."""
    today = today or date.today()
    day_candidates: list[dict[str, Any]] = []
    ticket_candidates: list[dict[str, Any]] = []
    registration_candidates: list[dict[str, Any]] = []
    reference_candidates: list[dict[str, Any]] = []

    for source_index, text_value in enumerate((title or "", description or "")):
        text_value = clean_html(text_value)
        if not text_value:
            continue
        candidates, occupied = _collect_day_candidates(text_value, today)
        for candidate in candidates:
            candidate["source_index"] = source_index
            if candidate["event_date_role"] == "ticket_sale":
                ticket_candidates.append(candidate)
            elif candidate["event_date_role"] == "registration":
                registration_candidates.append(candidate)
            else:
                day_candidates.append(candidate)
        reference_candidates.extend(
            dict(item, source_index=source_index)
            for item in _collect_reference_periods(text_value, today, occupied)
        )

    day_candidates.sort(key=lambda item: (0 if item["event_date_role"] == "event" else 1, item["source_index"], item["start"]))
    ticket_candidates.sort(key=lambda item: (item["source_index"], item["start"]))
    registration_candidates.sort(key=lambda item: (item["source_index"], item["start"]))
    reference_candidates.sort(key=lambda item: (item["source_index"], item["start"]))

    ticket_sale_at = ticket_candidates[0]["start_at"] if ticket_candidates else None
    registration_at = registration_candidates[0]["start_at"] if registration_candidates else None
    reference = reference_candidates[0] if reference_candidates else None

    if day_candidates:
        chosen = day_candidates[0]
        return {
            "start_at": chosen["start_at"], "end_at": chosen["end_at"],
            "date_precision": "day", "date_confidence": chosen["date_confidence"],
            "event_date_role": chosen["event_date_role"],
            "ticket_sale_at": ticket_sale_at, "ticket_sale_date_confidence": ticket_candidates[0]["date_confidence"] if ticket_candidates else "unknown",
            "registration_at": registration_at, "registration_date_confidence": registration_candidates[0]["date_confidence"] if registration_candidates else "unknown",
            "reference_period_start": reference["reference_period_start"] if reference else None,
            "reference_period_end": reference["reference_period_end"] if reference else None,
        }
    if ticket_candidates:
        return {
            "start_at": None, "end_at": None, "date_precision": "tbd", "date_confidence": "unknown",
            "event_date_role": "ticket_sale", "ticket_sale_at": ticket_sale_at,
            "ticket_sale_date_confidence": ticket_candidates[0]["date_confidence"],
            "registration_at": registration_at, "registration_date_confidence": registration_candidates[0]["date_confidence"] if registration_candidates else "unknown",
            "reference_period_start": reference["reference_period_start"] if reference else None,
            "reference_period_end": reference["reference_period_end"] if reference else None,
        }
    if registration_candidates:
        return {
            "start_at": None, "end_at": None, "date_precision": "tbd", "date_confidence": "unknown",
            "event_date_role": "registration", "ticket_sale_at": None, "ticket_sale_date_confidence": "unknown",
            "registration_at": registration_at, "registration_date_confidence": registration_candidates[0]["date_confidence"],
            "reference_period_start": reference["reference_period_start"] if reference else None,
            "reference_period_end": reference["reference_period_end"] if reference else None,
        }
    if reference:
        return {
            "start_at": None, "end_at": None, "date_precision": reference["date_precision"],
            "date_confidence": reference["date_confidence"], "event_date_role": "reference_period",
            "ticket_sale_at": None, "ticket_sale_date_confidence": "unknown",
            "registration_at": None, "registration_date_confidence": "unknown",
            "reference_period_start": reference["reference_period_start"],
            "reference_period_end": reference["reference_period_end"],
        }
    return {
        "start_at": None, "end_at": None, "date_precision": "tbd", "date_confidence": "unknown",
        "event_date_role": "unknown", "ticket_sale_at": ticket_sale_at,
        "ticket_sale_date_confidence": ticket_candidates[0]["date_confidence"] if ticket_candidates else "unknown",
        "registration_at": registration_at,
        "registration_date_confidence": registration_candidates[0]["date_confidence"] if registration_candidates else "unknown",
        "reference_period_start": None, "reference_period_end": None,
    }


def is_upcoming_event(event: dict[str, Any], today: date) -> bool:
    """Return True only for a dated, future/ongoing single-event candidate."""
    if future_exclusion_reasons(event):
        return False
    title_kind = classify_content(event.get("event_name", ""))
    if title_kind == "past_report":
        return False
    kind = event.get("content_kind") or title_kind
    if kind not in {"event_announcement", "uncertain"}:
        return False
    start_value = event.get("start_at")
    if not start_value or event.get("date_precision") in {"month", "month_range"}:
        return False
    if not event.get("event_date_role") and event.get("date_confidence") == "inferred_year" and start_value[:4] > str(today.year):
        return False
    if event.get("event_date_role") in {"ticket_sale", "registration", "reference_period"}:
        return False
    try:
        end_value = date.fromisoformat(event.get("end_at") or start_value)
    except (TypeError, ValueError):
        return False
    return end_value >= today


def enrich_existing_event(event: dict[str, Any], today: date) -> dict[str, Any]:
    """Backfill classification and correct obvious legacy date-role mistakes."""
    if event.get("review_status") == "verified":
        return event
    title = event.get("event_name") or ""
    kind = classify_content(title)
    parsed = extract_event_date(title, "", today)
    event["content_kind"] = kind
    if event.get("city_slug"):
        event["city_match"] = assess_event_city(event, title)
    event["event_confirmation"] = "unconfirmed" if CONDITIONAL_EVENT_PATTERN.search(title) or event.get("event_confirmation") == "unconfirmed" else "unknown"

    if kind in NON_EVENT_CONTENT_KINDS and parsed.get("event_date_role") != "event":
        event["start_at"] = None
        event["end_at"] = None
        event["date_precision"] = parsed.get("date_precision") if parsed.get("date_precision") in {"month", "month_range"} else "tbd"
        event["date_confidence"] = parsed.get("date_confidence", "unknown")
        event["event_date_role"] = parsed.get("event_date_role", "unknown")
    elif parsed.get("start_at") and parsed.get("event_date_role") in {"event", "ambiguous"}:
        for field in ("start_at", "end_at", "date_precision", "date_confidence", "event_date_role"):
            event[field] = parsed.get(field)
    elif parsed.get("event_date_role") in {"ticket_sale", "registration", "reference_period"}:
        event["start_at"] = None
        event["end_at"] = None
        event["date_precision"] = parsed.get("date_precision", "tbd")
        event["date_confidence"] = parsed.get("date_confidence", "unknown")
        event["event_date_role"] = parsed.get("event_date_role", "unknown")
    else:
        # A legacy date that cannot be reproduced from the title is untrusted.
        # This clears stale dates after a numeric-quantity false match is fixed.
        for field in ("start_at", "end_at", "date_precision", "date_confidence", "event_date_role"):
            event[field] = parsed[field]

    for field in ("ticket_sale_at", "registration_at", "reference_period_start", "reference_period_end"):
        event[field] = parsed.get(field)
    return event


def parse_feed(xml_bytes: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        return []
    parsed: list[dict[str, Any]] = []
    for item in channel.findall("item")[:MAX_FEED_ITEMS]:
        title = clean_html(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = clean_html(item.findtext("description"))
        published = parse_rss_datetime(item.findtext("pubDate"))
        source_el = item.find("source")
        publisher = clean_html(source_el.text if source_el is not None else "") or "Google News RSS"
        publisher_url = source_el.attrib.get("url", "") if source_el is not None else ""
        if title and link:
            parsed.append({
                "title": title, "description": description, "url": link,
                "published_at": published, "publisher": publisher, "publisher_url": publisher_url,
            })
    return parsed


def source_type_for(publisher: str, publisher_url: str) -> str:
    host = urlparse(publisher_url).netloc.lower()
    label = publisher.lower()
    if host.endswith(".gov.cn") or host.endswith(".gov") or "官方" in publisher:
        return "official"
    if any(token in label for token in ("新闻", "日报", "新闻网", "电视台", "融媒体", "news")):
        return "media"
    return "other"


def build_feed_url(city: dict[str, Any], today: date) -> str:
    after = (today - timedelta(days=60)).isoformat()
    query = (
        '"' + city["aliases"][0] + '" '
        + "(演唱会 OR 音乐节 OR 展会 OR 博览会 OR 马拉松 OR 体育赛事 OR 演出 OR 漫展 OR 节庆 OR 车展) "
        + "(2026 OR 2027) after:" + after
    )
    params = urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    return "https://news.google.com/rss/search?" + params


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                if response.status != 200:
                    raise RuntimeError("HTTP " + str(response.status))
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
    raise RuntimeError(type(last_error).__name__ if last_error else "feed_error")


def build_candidate(city: dict[str, Any], item: dict[str, Any], observed_at: str, today: date) -> dict[str, Any]:
    title = item["title"]
    description = item.get("description", "")
    date_info = extract_event_date(title, description, today)
    content_kind = classify_content(title, description)
    event_name = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{2,36}$", "", title).strip() or title
    identity = event_identity(city["city_slug"], event_name)
    event_id = "evt_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    city_match = assess_event_city(city, title, description)
    published_at = item.get("published_at")
    knowable_at = max(value for value in (observed_at, published_at) if value) if published_at else observed_at
    source = {
        "source_url": item["url"],
        "publisher": item.get("publisher") or "Google News RSS",
        "publisher_url": item.get("publisher_url") or None,
        "source_type": source_type_for(item.get("publisher", ""), item.get("publisher_url", "")),
        "source_published_at": published_at,
        "observed_at": observed_at,
        "last_observed_at": observed_at,
        "verification_status": "unverified",
    }
    note_by_kind = {
        "guide": "攻略/购票指南，不代表单场活动；其中出现的日期不直接作为举办日期。",
        "schedule_roundup": "排期汇总可能包含多场活动；需拆分核验，不按单场活动处理。",
        "ticketing_notice": "开票/售票信息；开售日期不等于活动举办日期。",
        "registration_notice": "报名信息；报名日期不等于活动举办日期。",
        "past_report": "历史报道候选，保留供回溯，不作为未来热点。",
    }
    return {
        "event_id": event_id, "event_name": event_name,
        "event_type": classify_event(title + " " + description),
        "content_kind": content_kind,
        "city_name": city["city_name"], "city_slug": city["city_slug"], "city_match": city_match,
        "event_confirmation": "unconfirmed" if CONDITIONAL_EVENT_PATTERN.search(title + " " + description) else "unknown",
        "venue_name": None, "venue_location": None,
        "start_at": date_info["start_at"], "end_at": date_info["end_at"],
        "date_precision": date_info["date_precision"], "date_confidence": date_info["date_confidence"],
        "event_date_role": date_info["event_date_role"],
        "ticket_sale_at": date_info.get("ticket_sale_at"),
        "ticket_sale_date_confidence": date_info.get("ticket_sale_date_confidence", "unknown"),
        "registration_at": date_info.get("registration_at"),
        "registration_date_confidence": date_info.get("registration_date_confidence", "unknown"),
        "reference_period_start": date_info.get("reference_period_start"),
        "reference_period_end": date_info.get("reference_period_end"),
        "event_status": "unknown", "review_status": "pending", "estimated_attendees": None,
        "first_seen_at": observed_at, "last_seen_at": observed_at, "knowable_at": knowable_at,
        "source_count": 1, "sources": [source],
        "discovery_query": city["aliases"][0] + " + public event keywords",
        "candidate_note": note_by_kind.get(content_kind, "自动发现候选；未完成人工核验，不作为正式经营结论。"),
    }


def merge_candidate(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    merged = dict(existing)
    merged["last_seen_at"] = candidate.get("last_seen_at") or existing.get("last_seen_at")
    sources = {s.get("source_url"): dict(s) for s in existing.get("sources", []) if s.get("source_url")}
    for new_source in candidate.get("sources", []):
        key = new_source.get("source_url")
        if not key:
            continue
        if key in sources:
            sources[key]["last_observed_at"] = new_source.get("last_observed_at") or candidate.get("last_seen_at")
            if new_source.get("source_published_at") and not sources[key].get("source_published_at"):
                sources[key]["source_published_at"] = new_source["source_published_at"]
        else:
            sources[key] = dict(new_source)
    merged["sources"] = sorted(sources.values(), key=lambda s: s.get("source_published_at") or "", reverse=True)
    merged["source_count"] = len(merged["sources"])
    merged["review_status"] = existing.get("review_status", "pending")
    merged["event_status"] = existing.get("event_status", "unknown")
    if merged["review_status"] != "verified":
        for field in ("content_kind", "event_type", "city_match", "event_confirmation"):
            if field in candidate:
                merged[field] = candidate[field]
        if existing.get("event_confirmation") == "unconfirmed":
            merged["event_confirmation"] = "unconfirmed"
        # A complete parser result replaces even an obsolete non-empty date.
        # Merely discovering another source must not overwrite human-reviewed fields.
        if "event_date_role" in candidate:
            for field in (
                "start_at", "end_at", "date_precision", "date_confidence", "event_date_role",
                "ticket_sale_at", "ticket_sale_date_confidence", "registration_at",
                "registration_date_confidence", "reference_period_start", "reference_period_end",
            ):
                merged[field] = candidate.get(field)
    first_seen = existing.get("first_seen_at") or candidate.get("first_seen_at")
    merged["first_seen_at"] = first_seen
    published = [s.get("source_published_at") for s in merged["sources"] if s.get("source_published_at")]
    merged["knowable_at"] = max([first_seen] + published) if first_seen else max(published) if published else candidate.get("knowable_at")
    return merged

def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_collection() -> int:
    now = now_utc()
    observed_at = iso_utc(now)
    today = now.astimezone(BEIJING).date()
    cities = json.loads(CITIES_FILE.read_text(encoding="utf-8"))
    current_payload = load_json(SITE_API / "hotspots.json", {"data": []})
    old_events = current_payload.get("data", []) if isinstance(current_payload, dict) else []

    # Build a stable title-based index so a corrected date does not create a duplicate event.
    by_identity: dict[str, dict[str, Any]] = {}
    for event in old_events:
        key = event_identity(event.get("city_slug", ""), event.get("event_name", ""))
        if key not in by_identity:
            by_identity[key] = event
        else:
            primary = by_identity[key]
            merged = merge_candidate(primary, event)
            merged["event_id"] = primary.get("event_id") or event.get("event_id")
            by_identity[key] = merged

    feed_results: list[dict[str, Any]] = []
    successful_feeds = 0
    total_items = 0

    for index, city in enumerate(cities):
        try:
            items = parse_feed(fetch_feed(build_feed_url(city, today)))
            successful_feeds += 1
            total_items += len(items)
            feed_results.append({"city_name": city["city_name"], "status": "ok", "items": len(items)})
            for item in items:
                combined = item["title"] + " " + item.get("description", "")
                if not any(keyword in combined for keyword in KEYWORDS):
                    continue
                candidate = build_candidate(city, item, observed_at, today)
                key = event_identity(candidate.get("city_slug", ""), candidate.get("event_name", ""))
                existing = by_identity.get(key)
                merged = merge_candidate(existing, candidate)
                if existing:
                    merged["event_id"] = existing.get("event_id") or candidate["event_id"]
                by_identity[key] = merged
        except Exception as exc:
            feed_results.append({"city_name": city["city_name"], "status": "failed", "error_type": type(exc).__name__})
        if index < len(cities) - 1:
            time.sleep(0.35)

    all_failed = successful_feeds == 0
    if all_failed:
        # Keep the prior event snapshot unchanged if every feed failed.
        events_to_process = old_events
    else:
        events_to_process = [enrich_existing_event(event, today) for event in by_identity.values()]

    cutoff = now - timedelta(days=KEEP_UNSEEN_DAYS)
    lower_date = today - timedelta(days=MAX_PAST_DAYS)
    upper_date = today + timedelta(days=MAX_FUTURE_DAYS)
    kept: list[dict[str, Any]] = []
    for event in events_to_process:
        try:
            last_seen = datetime.fromisoformat((event.get("last_seen_at") or "").replace("Z", "+00:00"))
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
        except ValueError:
            last_seen = now
        if last_seen < cutoff:
            continue
        start_value = event.get("start_at")
        if start_value:
            try:
                event_day = date.fromisoformat(start_value)
                end_day = date.fromisoformat(event.get("end_at") or start_value)
                if end_day < lower_date or event_day > upper_date:
                    continue
            except ValueError:
                pass
        kept.append(event)

    kept.sort(key=lambda e: (e.get("start_at") or "9999-12-31", e.get("city_name") or "", e.get("event_name") or ""))
    overall_status = "failed" if all_failed else ("degraded" if successful_feeds < len(cities) else "healthy")
    dated_count = sum(
        1 for event in kept
        if event.get("start_at")
        and event.get("date_precision") == "day"
        and event.get("event_date_role") in {"event", "ambiguous"}
        and (event.get("content_kind") or classify_content(event.get("event_name", ""))) in {"event_announcement", "uncertain"}
    )
    future_count = sum(1 for event in kept if is_upcoming_event(event, today))
    content_counts = {
        kind: sum(1 for event in kept if (event.get("content_kind") or classify_content(event.get("event_name", ""))) == kind)
        for kind in ("event_announcement", "uncertain", "ticketing_notice", "registration_notice", "schedule_roundup", "guide", "past_report", "other")
    }
    payload = {
        "meta": {
            "api_version": "v1", "schema_version": "1.1", "generated_at": observed_at,
            "timezone": "Asia/Shanghai", "collection_status": overall_status,
            "source_system": "Google News RSS", "candidate_count": len(kept),
            "dated_candidate_count": dated_count, "future_event_candidate_count": future_count,
            "ticketing_signal_count": content_counts["ticketing_notice"],
            "registration_signal_count": content_counts["registration_notice"],
            "schedule_roundup_count": content_counts["schedule_roundup"],
            "guide_count": content_counts["guide"], "past_report_count": content_counts["past_report"],
            "uncertain_count": content_counts["uncertain"],
            "pending_count": sum(1 for e in kept if e.get("review_status") == "pending"),
            "verified_count": sum(1 for e in kept if e.get("review_status") == "verified"),
            "city_count": len(cities), "successful_feeds": successful_feeds,
            "failed_feeds": len(cities) - successful_feeds, "rss_items_seen": total_items,
            "data_note": "自动发现候选不代表官方核验；content_kind 区分活动、开票/报名、排期与攻略；只有 review_status=verified 的事件可进入正式经营判断。"
        },
        "data": kept,
    }
    health = {
        "api_version": "v1", "last_run_at": observed_at,
        "last_run_local": now.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S +08:00"),
        "status": overall_status, "source_system": "Google News RSS", "city_count": len(cities),
        "successful_feeds": successful_feeds, "failed_feeds": len(cities) - successful_feeds,
        "rss_items_seen": total_items, "candidate_count": len(kept), "feed_results": feed_results,
        "note": "如果 status=failed，上一份事件快照会保留，不会用空数据覆盖。"
    }
    city_counts = {city["city_slug"]: 0 for city in cities}
    city_future_counts = {city["city_slug"]: 0 for city in cities}
    for event in kept:
        slug = event.get("city_slug")
        if slug in city_counts:
            city_counts[slug] += 1
            if is_upcoming_event(event, today):
                city_future_counts[slug] += 1
    city_payload = {
        "meta": {"api_version": "v1", "generated_at": observed_at, "city_count": len(cities)},
        "data": [
            {
                "city_name": city["city_name"], "city_slug": city["city_slug"],
                "candidate_count": city_counts[city["city_slug"]],
                "future_event_candidate_count": city_future_counts[city["city_slug"]],
            }
            for city in cities
        ]
    }
    write_json(SITE_API / "hotspots.json", payload)
    write_json(SITE_API / "health.json", health)
    write_json(SITE_API / "cities.json", city_payload)
    print(json.dumps({
        "status": overall_status, "cities": len(cities), "successful_feeds": successful_feeds,
        "failed_feeds": len(cities) - successful_feeds, "rss_items_seen": total_items,
        "candidate_count": len(kept), "future_event_candidate_count": future_count,
        "dated_candidate_count": dated_count,
    }, ensure_ascii=False))
    return 1 if all_failed else 0


if __name__ == "__main__":
    sys.exit(run_collection())
