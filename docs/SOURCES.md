# Source policy and limitations

## Current source

The first MVP queries Google News RSS for 28 configured Chinese operating cities and public-event keywords. RSS items provide a title, article link, publisher label, publisher URL when supplied, and publication time. The collector does not bypass logins, CAPTCHAs, paywalls, or access controls.

## Interpretation rules

- Search results are discovery leads, not authoritative event confirmation.
- Every discovered event remains pending and unknown until a human or a later approved verification process confirms it.
- Event dates are extracted only from the headline or snippet. Missing dates remain tbd; a year inferred from a month/day is explicitly marked.
- City attribution is marked text_confirmed only when the city alias appears in the title/snippet. Otherwise it is query_only and should be reviewed.
- The source URL, publisher, publication time, first-seen time, and last-seen time are retained.
- Failed feeds are reported. The collector does not clear the snapshot when every feed fails.
- A result count of zero is not proof that a city has no events; it may reflect search coverage or source availability.

## Next source adapters

Add official municipal event calendars, exhibition-center calendars, official marathon/race calendars, venue schedules, and authorized ticketing feeds as separate adapters. Each adapter must document terms, access method, update cadence, and field mapping before it is enabled.
