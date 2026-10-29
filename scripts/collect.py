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


def _date_from_parts(year: int | None, month: int, day: int, today: date) -> tuple[date | None, str]:
    try:
        candidate = date(year or today.year, month, day)
    except ValueError:
        return None, "unknown"
    if year is not None:
        return candidate, "explicit_year"
    if candidate < today - timedelta(days=2):
        next_year = date(today.year + 1, month, day)
        if month < today.month and 0 <= (next_year - today).days <= MAX_FUTURE_DAYS:
            return next_year, "inferred_year"
        return None, "unknown"
    return candidate, "inferred_year"


def extract_event_date(title: str, description: str = "", today: date | None = None) -> dict[str, Any]:
    """Extract a likely event date without using the RSS publication date as the event date."""
    today = today or date.today()
    for text in (title or "", description or ""):
        candidates: list[tuple[int, date, date | None, str]] = []
        range_pattern = re.compile(
            r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日\s*(?:至|到|—|－|-|~|～)\s*(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日"
        )
        for match in range_pattern.finditer(text):
            y1, m1, d1, y2, m2, d2 = match.groups()
            start, confidence = _date_from_parts(int(y1) if y1 else None, int(m1), int(d1), today)
            end, end_conf = _date_from_parts(int(y2) if y2 else (int(y1) if y1 else None), int(m2), int(d2), today)
            if start and end and end < start and not y2:
                try:
                    end = date(start.year + 1, int(m2), int(d2))
                except ValueError:
                    end = None
            if start and end and end >= today - timedelta(days=2) and start <= today + timedelta(days=MAX_FUTURE_DAYS):
                confidence_out = "explicit_year" if confidence == "explicit_year" or end_conf == "explicit_year" else "inferred_year"
                candidates.append((match.start(), start, end, confidence_out))

        iso_pattern = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?!\d)")
        for match in iso_pattern.finditer(text):
            dt, confidence = _date_from_parts(int(match.group(1)), int(match.group(2)), int(match.group(3)), today)
            if dt and today - timedelta(days=MAX_PAST_DAYS) <= dt <= today + timedelta(days=MAX_FUTURE_DAYS):
                candidates.append((match.start(), dt, None, confidence))

        cn_pattern = re.compile(r"(?<!\d)(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日")
        for match in cn_pattern.finditer(text):
            dt, confidence = _date_from_parts(int(match.group(1)) if match.group(1) else None, int(match.group(2)), int(match.group(3)), today)
            if dt and today - timedelta(days=MAX_PAST_DAYS) <= dt <= today + timedelta(days=MAX_FUTURE_DAYS):
                candidates.append((match.start(), dt, None, confidence))

        slash_pattern = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?!\d)")
        for match in slash_pattern.finditer(text):
            dt, confidence = _date_from_parts(None, int(match.group(1)), int(match.group(2)), today)
            if dt and today - timedelta(days=MAX_PAST_DAYS) <= dt <= today + timedelta(days=MAX_FUTURE_DAYS):
                candidates.append((match.start(), dt, None, confidence))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            _, start, end, confidence = candidates[0]
            return {
                "start_at": start.isoformat(),
                "end_at": end.isoformat() if end and end != start else None,
                "date_precision": "day",
                "date_confidence": confidence,
            }

        month_pattern = re.compile(r"(?<!\d)(?:(20\d{2})年)?(\d{1,2})月")
        for match in month_pattern.finditer(text):
            year_text, month_text = match.groups()
            month = int(month_text)
            year = int(year_text) if year_text else today.year
            if not 1 <= month <= 12:
                continue
            confidence = "explicit_year" if year_text else "inferred_year"
            start = date(year, month, 1)
            if not year_text and start < today - timedelta(days=MAX_PAST_DAYS) and month < today.month:
                start = date(today.year + 1, month, 1)
            if start <= today + timedelta(days=MAX_FUTURE_DAYS) and start >= today - timedelta(days=MAX_PAST_DAYS):
                end = date(start.year, month + 1, 1) - timedelta(days=1) if month < 12 else date(start.year, 12, 31)
                return {
                    "start_at": start.isoformat(),
                    "end_at": end.isoformat(),
                    "date_precision": "month",
                    "date_confidence": confidence,
                }

    return {"start_at": None, "end_at": None, "date_precision": "tbd", "date_confidence": "unknown"}


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
    event_name = re.sub(r"\s*[-–—|｜]\s*[^-–—|｜]{2,36}$", "", title).strip() or title
    normalized = normalize_title(event_name)
    identity = "|".join((city["city_slug"], normalized, date_info["start_at"] or "tbd"))
    event_id = "evt_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    text_for_city = title + " " + description
    city_match = "text_confirmed" if any(alias and alias in text_for_city for alias in city.get("aliases", [])) else "query_only"
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
    return {
        "event_id": event_id, "event_name": event_name,
        "event_type": classify_event(title + " " + description),
        "city_name": city["city_name"], "city_slug": city["city_slug"], "city_match": city_match,
        "venue_name": None, "venue_location": None,
        "start_at": date_info["start_at"], "end_at": date_info["end_at"],
        "date_precision": date_info["date_precision"], "date_confidence": date_info["date_confidence"],
        "event_status": "unknown", "review_status": "pending", "estimated_attendees": None,
        "first_seen_at": observed_at, "last_seen_at": observed_at, "knowable_at": knowable_at,
        "source_count": 1, "sources": [source],
        "discovery_query": city["aliases"][0] + " + public event keywords",
        "candidate_note": "自动发现候选；未完成人工核验，不作为正式经营结论。",
    }


def merge_candidate(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        return candidate
    merged = dict(existing)
    merged["last_seen_at"] = candidate["last_seen_at"]
    sources = {s.get("source_url"): dict(s) for s in existing.get("sources", []) if s.get("source_url")}
    for new_source in candidate.get("sources", []):
        key = new_source.get("source_url")
        if not key:
            continue
        if key in sources:
            sources[key]["last_observed_at"] = new_source.get("last_observed_at") or candidate["last_seen_at"]
            if new_source.get("source_published_at") and not sources[key].get("source_published_at"):
                sources[key]["source_published_at"] = new_source["source_published_at"]
        else:
            sources[key] = dict(new_source)
    merged["sources"] = sorted(sources.values(), key=lambda s: s.get("source_published_at") or "", reverse=True)
    merged["source_count"] = len(merged["sources"])
    merged["review_status"] = existing.get("review_status", "pending")
    merged["event_status"] = existing.get("event_status", "unknown")
    if candidate.get("date_confidence") == "explicit_year" or not merged.get("start_at"):
        for field in ("start_at", "end_at", "date_precision", "date_confidence", "event_type", "city_match"):
            if candidate.get(field) is not None:
                merged[field] = candidate[field]
    first_seen = existing.get("first_seen_at") or candidate["first_seen_at"]
    merged["first_seen_at"] = first_seen
    published = [s.get("source_published_at") for s in merged["sources"] if s.get("source_published_at")]
    merged["knowable_at"] = max([first_seen] + published)
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
    by_id = {event.get("event_id"): event for event in old_events if event.get("event_id")}
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
                by_id[candidate["event_id"]] = merge_candidate(by_id.get(candidate["event_id"]), candidate)
        except Exception as exc:
            feed_results.append({"city_name": city["city_name"], "status": "failed", "error_type": type(exc).__name__})
        if index < len(cities) - 1:
            time.sleep(0.35)

    cutoff = now - timedelta(days=KEEP_UNSEEN_DAYS)
    lower_date = today - timedelta(days=MAX_PAST_DAYS)
    upper_date = today + timedelta(days=MAX_FUTURE_DAYS)
    kept: list[dict[str, Any]] = []
    for event in by_id.values():
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
    all_failed = successful_feeds == 0
    overall_status = "failed" if all_failed else ("degraded" if successful_feeds < len(cities) else "healthy")
    payload = {
        "meta": {
            "api_version": "v1", "schema_version": "1.0", "generated_at": observed_at,
            "timezone": "Asia/Shanghai", "collection_status": overall_status,
            "source_system": "Google News RSS", "candidate_count": len(kept),
            "dated_candidate_count": sum(1 for e in kept if e.get("start_at")),
            "pending_count": sum(1 for e in kept if e.get("review_status") == "pending"),
            "verified_count": sum(1 for e in kept if e.get("review_status") == "verified"),
            "city_count": len(cities), "successful_feeds": successful_feeds,
            "failed_feeds": len(cities) - successful_feeds, "rss_items_seen": total_items,
            "data_note": "自动发现候选不代表官方核验；只有 review_status=verified 的事件可进入正式经营判断。"
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
    for event in kept:
        if event.get("city_slug") in city_counts:
            city_counts[event["city_slug"]] += 1
    city_payload = {
        "meta": {"api_version": "v1", "generated_at": observed_at, "city_count": len(cities)},
        "data": [{"city_name": c["city_name"], "city_slug": c["city_slug"], "candidate_count": city_counts[c["city_slug"]]} for c in cities]
    }
    write_json(SITE_API / "hotspots.json", payload)
    write_json(SITE_API / "health.json", health)
    write_json(SITE_API / "cities.json", city_payload)
    print(json.dumps({
        "status": overall_status, "cities": len(cities), "successful_feeds": successful_feeds,
        "failed_feeds": len(cities) - successful_feeds, "rss_items_seen": total_items, "candidate_count": len(kept)
    }, ensure_ascii=False))
    return 1 if all_failed else 0


if __name__ == "__main__":
    sys.exit(run_collection())
