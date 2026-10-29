# Static JSON API v1

Base URL after GitHub Pages is enabled:

https://wildpig622.github.io/hotspot-pulse/api/v1/

## GET hotspots.json

Returns the current event-candidate snapshot.

Top-level fields:
- meta.api_version: API version string.
- meta.generated_at: UTC time when the snapshot was generated.
- meta.collection_status: healthy, degraded, failed, or not_run.
- meta.candidate_count: number of retained candidates.
- meta.successful_feeds / failed_feeds: per-city RSS query results.
- data: candidate event records.

Event fields include event_id, event_name, event_type, city_name, city_slug, city_match, start_at, end_at, date_precision, date_confidence, event_status, review_status, first_seen_at, last_seen_at, knowable_at, source_count, and sources.

Every automatically discovered record starts as review_status=pending and event_status=unknown. The collector does not automatically verify event facts or claim that an event is scheduled.

## GET cities.json

Returns the configured collection cities and candidate counts.

## GET health.json

Returns the latest run status and per-city feed result summary. A failed run preserves the previous hotspots.json snapshot.

## Filtering

GitHub Pages is a static host, so this version does not execute server-side query parameters. Consumers download hotspots.json and filter locally. The consumer must explicitly restrict official business use to verified records; this MVP does not yet provide a write path or review UI.

## Update schedule

Daily at 22:15 UTC (06:15 Asia/Shanghai). Also runs on source-code pushes and can be started manually from GitHub Actions.
