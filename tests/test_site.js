"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const script = fs.readFileSync(path.join(root, "site/app.js"), "utf8");
const snapshot = JSON.parse(fs.readFileSync(path.join(root, "tests/fixtures/hotspots-2026-10-29.json"), "utf8"));
const cities = JSON.parse(fs.readFileSync(path.join(root, "config/cities.json"), "utf8"));
const cases = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures/manual-audit-2026-10-29.json"), "utf8"));
const byId = Object.fromEntries(snapshot.data.map(row => [row.event_id, row]));
const supportedIds = cases.expected_future_ids.concat(cases.additional_supported_future_ids);

// Exercise the actual page startup, loading, filters and rendered cards without
// exporting test-only copies of the production predicates.
async function loadPage(events, options = {}) {
  const nodes = {};
  function element() {
    return {value: "", textContent: "", innerHTML: "", listeners: {},
      appendChild() {}, addEventListener(name, callback) { this.listeners[name] = callback; }};
  }
  const document = {
    getElementById(id) { return nodes[id] || (nodes[id] = element()); },
    createElement: element,
  };
  document.getElementById("contentFilter").value = "future";
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : ["2026-10-29T08:00:00Z"])); }
    static now() { return new Date("2026-10-29T08:00:00Z").getTime(); }
  }
  const fetch = async url => {
    if (url.includes("cities.json") && options.failCities) throw new Error("cities unavailable");
    const payload = url.includes("hotspots.json") ? {meta: snapshot.meta, data: events}
      : url.includes("cities.json") ? {data: cities} : {};
    return {ok: true, json: async () => payload};
  };
  vm.runInNewContext(script, {document, fetch, Intl, Date: FixedDate, URL,
    window: {location: {href: "https://example.com/"}}, navigator: {}});
  await new Promise(resolve => setImmediate(resolve));
  return nodes;
}

test("unchanged legacy snapshot exposes exactly the same 20 future candidates as the collector", async () => {
  const nodes = await loadPage(snapshot.data);
  const rendered = Array.from(nodes.eventsList.innerHTML.matchAll(/class="event-title">([^<]*)</g), match => match[1]);
  const escape = value => value.replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  assert.deepEqual(rendered.sort(), supportedIds.map(id => escape(byId[id].event_name)).sort());
  assert.equal(nodes.metricDated.textContent, "20");
  assert.equal(nodes.resultCount.textContent, "20 条");
});

test("all fourteen false future candidates remain hidden individually", async () => {
  for (const id of Object.keys(cases.excluded_future_ids)) {
    const nodes = await loadPage([byId[id]]);
    assert.equal(nodes.resultCount.textContent, "0 条", id);
    nodes.contentFilter.value = "all";
    nodes.contentFilter.listeners.input();
    assert.equal(nodes.resultCount.textContent, "1 条", id + " remains accessible for review");
  }
});

test("all twelve boundary records remain outside the future filter", async () => {
  for (const id of Object.keys(cases.boundary_expected_buckets)) {
    const nodes = await loadPage([byId[id]]);
    assert.equal(nodes.resultCount.textContent, "0 条", id);
  }
});

test("all twenty supported candidates remain visible individually", async () => {
  for (const id of supportedIds) {
    const nodes = await loadPage([byId[id]]);
    assert.equal(nodes.resultCount.textContent, "1 条", id);
  }
});

test("three stale dates inferred into next year are held for year review", async () => {
  for (const id of cases.legacy_rollover_ids) {
    const nodes = await loadPage([byId[id]]);
    assert.equal(nodes.resultCount.textContent, "0 条", id);
    nodes.contentFilter.value = "all";
    nodes.contentFilter.listeners.input();
    assert.match(nodes.eventsList.innerHTML, /旧记录推断到下一年，需复核年份/, id);
  }
});

test("failed city catalogue cannot silently admit an event-city mismatch", async () => {
  const nodes = await loadPage([byId.evt_a3fea5891c78], {failCities: true});
  assert.equal(nodes.resultCount.textContent, "0 条");
  nodes.contentFilter.value = "all";
  nodes.contentFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent, "1 条");
  assert.match(nodes.eventsList.innerHTML, /举办城市暂时无法核对/);
});

test("invalid calendar dates and reversed ranges stay available for review without entering the future view", async () => {
  const base = {event_name: "杭州演唱会", city_name: "杭州市", city_slug: "hangzhou",
    content_kind: "event_announcement", date_precision: "day", event_date_role: "event"};
  for (const dates of [{start_at: "2026-11-31"}, {start_at: "2026-11-10", end_at: "2026-11-08"},
    {start_at: "2026-11-08", end_at: "2026-12-32"}, {start_at: "unknown", end_at: "2026-12-01"}]) {
    const nodes = await loadPage([{...base, ...dates}]);
    assert.equal(nodes.resultCount.textContent, "0 条");
    nodes.contentFilter.value = "all";
    nodes.contentFilter.listeners.input();
    assert.equal(nodes.resultCount.textContent, "1 条");
    assert.match(nodes.eventsList.innerHTML, /日期区间无效，需复核/);
  }
});

test("a multi-day legacy exhibition remains discoverable on its middle and last days", async () => {
  const original = JSON.stringify(byId.evt_cfd1dabb5e54);
  const nodes = await loadPage([byId.evt_cfd1dabb5e54]);
  assert.match(nodes.eventsList.innerHTML, /2026-11-05 至 2026-11-09/);
  for (const day of ["2026-11-08", "2026-11-09", "2026-11-10"]) {
    nodes.dateFrom.value = nodes.dateTo.value = day;
    nodes.dateFrom.listeners.input();
    assert.equal(nodes.resultCount.textContent, day === "2026-11-10" ? "0 条" : "1 条", day);
  }
  assert.equal(JSON.stringify(byId.evt_cfd1dabb5e54), original, "source record is untouched");
});

test("an explicit past day hidden by a legacy whole-month value belongs in the past view", async () => {
  const nodes = await loadPage([byId.evt_d494c40ed023]);
  nodes.contentFilter.value = "past";
  nodes.contentFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent, "1 条");
  assert.match(nodes.eventsList.innerHTML, /2026-10-18/);
  assert.doesNotMatch(nodes.eventsList.innerHTML, /2026-10-01 至 2026-10-31/);
});

test("all twelve boundary samples are accessible in their intended content views", async () => {
  const views = {event_date_review:"undated", ticketing_registration:"ticketing", schedule_roundup:"schedule", guides_other:"guide", past_expired:"past"};
  for (const [id, bucket] of Object.entries(cases.boundary_expected_buckets)) {
    const nodes = await loadPage([byId[id]]);
    nodes.contentFilter.value = views[bucket];
    nodes.contentFilter.listeners.input();
    assert.equal(nodes.resultCount.textContent, "1 条", id + " in " + views[bucket]);
  }
});

test("legacy title projection cannot overwrite human or semantic dates or invent a year", async () => {
  for (const protectedDate of [{review_status:"verified"}, {event_date_role:"event"}]) {
    const nodes = await loadPage([{...byId.evt_cfd1dabb5e54, ...protectedDate}]);
    assert.doesNotMatch(nodes.eventsList.innerHTML, /2026-11-05 至 2026-11-09/);
  }
  for (const title of ["杭州展会11月10日至8日举行", "杭州展会11月31日至12月2日举行", "杭州展会3月5日举行"]) {
    const nodes = await loadPage([{event_name:title, city_name:"杭州市", city_slug:"hangzhou", review_status:"pending", start_at:"2026-03-01", end_at:"2026-03-31", date_precision:"month"}]);
    assert.equal(nodes.resultCount.textContent, "0 条", title);
  }
});
