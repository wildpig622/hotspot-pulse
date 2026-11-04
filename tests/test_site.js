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
      appendChild() {}, addEventListener(name, callback) { this.listeners[name] = callback; },
      getContext() { return {}; }, showModal() { this.open = true; },
      close() { this.open = false; if (this.listeners.close) this.listeners.close(); },
      removeAttribute(name) { delete this[name]; }, focus() {}};
  }
  const document = {
    getElementById(id) { return nodes[id] || (nodes[id] = element()); },
    createElement: element,
  };
  document.getElementById("contentFilter").value = "future";
  if (options.recordLayer) document.getElementById("recordFilter").value = options.recordLayer;
  const clockAt = options.clockAt || "2026-10-29T08:00:00Z";
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clockAt])); }
    static now() { return new Date(clockAt).getTime(); }
  }
  const fetch = async url => {
    if (url.includes("cities.json") && options.failCities) throw new Error("cities unavailable");
    const payload = url.includes("hotspots.json") ? {meta: options.meta || snapshot.meta, data: events}
      : url.includes("cities.json") ? {data: cities}
      : url.includes("activities.json") ? options.activities || {}
      : url.includes("health.json") ? options.health || {}
      : url.includes("/v2/events.json") ? options.eventFeed || {} : {};
    return {ok: true, json: async () => payload};
  };
  class TestURL extends URL {
    static createObjectURL() { return "blob:test-image"; }
    static revokeObjectURL() {}
  }
  vm.runInNewContext(script, {document, fetch, Intl, Date: FixedDate, URL: TestURL,
    window: {location: {href: "https://example.com/"}, HotspotShareImage: options.shareApi, ClipboardItem: options.ClipboardItem}, navigator: options.navigator || {}});
  await new Promise(resolve => setImmediate(resolve));
  return nodes;
}

function calendarRow(extra = {}) {
  return {event_id:"act_school", record_kind:"activity", event_name:"杭州部分学校秋假", city_name:"杭州市", city_slug:"hangzhou",
    city_match:"text_confirmed", event_type:"holiday", content_kind:"event_announcement", event_date_role:"event",
    date_precision:"day", date_confidence:"source_body", start_at:"2026-11-11", end_at:"2026-11-13", review_status:"pending",
    sessions:[{start_at:"2026-11-11",end_at:"2026-11-13"}], scope_note:"部分学校，高三除外", sources:[], ...extra};
}

test('v2 canonical records replace duplicate member rows and keep raw leads accessible',async()=>{
  const event=calendarRow({event_id:'hp_1234567890abcdef',availability:'candidate'});
  const nodes=await loadPage(snapshot.data,{recordLayer:'activities',activities:{data:[calendarRow(),calendarRow({event_id:'duplicate'})]},eventFeed:{meta:{schema_version:'2.0',expires_at:'2026-11-05T00:00:00Z'},data:[event]}});
  assert.equal((nodes.eventsList.innerHTML.match(/杭州部分学校秋假/g)||[]).length,1);
  nodes.recordFilter.value='leads';nodes.recordFilter.listeners.change();
  nodes.contentFilter.value='all';nodes.contentFilter.listeners.change();
  assert.ok(nodes.eventsList.innerHTML.includes(snapshot.data[0].event_name));
});

test('v2 stale or cached feed visibly reports its actual collection time',async()=>{
  const nodes=await loadPage([],{recordLayer:'activities',eventFeed:{meta:{schema_version:'2.0',expires_at:'2026-10-28T00:00:00Z',last_successful_collection_at:'2026-10-27T00:00:00Z',using_cached_data:true},data:[calendarRow()]}});
  assert.equal(nodes.feedError.hidden,false);
  assert.ok(nodes.feedError.textContent.includes('已过期'));
  assert.ok(nodes.feedError.textContent.includes('上次成功采集'));
});

test("dated ticketing listings fill a previously empty city and keep their evidence label in PNG", async () => {
  const listing=calendarRow({event_id:'src_ly',record_kind:'source_candidate',evidence_level:'ticketing_listing',date_confidence:'source_listing',event_name:'洛阳话剧',city_name:'洛阳市',city_slug:'luoyang',scope_note:'仅列此场开始日，详情尚未读取'});
  let exported;
  const nodes=await loadPage([],{activities:{data:[],source_candidates:[listing],source_checks:[{city_name:'洛阳市',status:'ok'}]},shareApi:{plan(ctx,model){exported=model;return {pages:[{}]};},render(){},toBlob:async()=>({type:'image/png'})}});
  nodes.cityFilter.value='洛阳市';nodes.cityFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'1 条');
  assert.match(nodes.citySummary.textContent,/票务日期候选 1 条/);
  assert.match(nodes.eventsList.innerHTML,/票务日期候选 · 待核验/);
  assert.match(nodes.eventsList.innerHTML,/票务卡片列明举办城市/);
  assert.doesNotMatch(nodes.eventsList.innerHTML,/未提取到举办日期|标题\/摘要出现城市名/);
  await nodes.exportPngBtn.listeners.click();
  assert.match(exported.rows[0].content,/详情与主办方待补查/);
  assert.equal(exported.rows[0].review,'待核验');
  nodes.reviewFilter.value='verified';nodes.reviewFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'0 条');
});

test("rejected source listings stay outside the future view and failed refresh is visible", async () => {
  const row=calendarRow({event_id:'src_rejected',record_kind:'source_candidate',review_status:'rejected'});
  const nodes=await loadPage([],{activities:{data:[],source_candidates:[row],source_checks:[{city_name:'杭州市',status:'failed'}]}});
  assert.equal(nodes.resultCount.textContent,'0 条');
  assert.match(nodes.coverageBacklog.textContent,/读取失败，历史候选已保留/);
  nodes.contentFilter.value='all';nodes.contentFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'1 条');
});

test("Chongqing news candidates enter the default calendar with distinct evidence labels and PNG provenance", async () => {
  const raw = calendarRow({event_id:'evt_cq',record_kind:undefined,city_name:'重庆市',city_slug:'chongqing',event_name:'重庆音乐会',date_confidence:'explicit_year',sessions:undefined});
  const candidate = {...raw,record_kind:'discovery_candidate',evidence_level:'title_or_rss_summary'};
  let exported;
  const nodes = await loadPage([raw], {activities:{data:[],discovery_candidates:[candidate]},shareApi:{plan(ctx,model){exported=model;return {pages:[{}]};},render(){},toBlob:async()=>({type:'image/png'})}});
  nodes.cityFilter.value='重庆市';nodes.cityFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'1 条');
  assert.match(nodes.eventsList.innerHTML,/新闻候选 · 正文待核对/);
  assert.doesNotMatch(nodes.eventsList.innerHTML,/来源日期已整理/);
  assert.match(nodes.citySummary.textContent,/重庆市：已采 1 条新闻线索/);
  await nodes.exportPngBtn.listeners.click();
  assert.match(exported.rows[0].content,/正文待核对，可能重复/);
  assert.equal(exported.rows[0].review,'待核验');
});

test("a city with no safe calendar dates exposes all its leads without retaining contradictory filters", async () => {
  const raw=calendarRow({event_id:'evt_undated_cq',record_kind:undefined,city_name:'重庆市',city_slug:'chongqing',start_at:null,end_at:null,sessions:undefined,event_date_role:'unknown'});
  const nodes=await loadPage([raw],{activities:{data:[],discovery_candidates:[]}});
  nodes.cityFilter.value='重庆市';nodes.searchInput.value='not matching';nodes.dateFrom.value='2026-11-20';nodes.cityFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'0 条');
  assert.match(nodes.eventsList.innerHTML,/已采 1 条新闻线索/);
  nodes.showCityLeadsBtn.listeners.click();
  assert.equal(nodes.cityFilter.value,'重庆市');
  assert.equal(nodes.dateFrom.value,'');
  assert.equal(nodes.searchInput.value,'');
  assert.equal(nodes.recordFilter.value,'leads');
  assert.equal(nodes.resultCount.textContent,'1 条');
});

test("activity calendar and news leads remain distinct, with clear totals and scoped holiday dates", async () => {
  const row = calendarRow({travel_windows:[{start_at:"2026-11-11",end_at:"2026-11-15"}]});
  const nodes = await loadPage(snapshot.data, {activities:{meta:{generated_at:"2026-11-04T01:00:00Z"},data:[row]},recordLayer:"activities"});
  assert.equal(nodes.metricTotal.textContent, "457");
  assert.equal(nodes.resultCount.textContent, "1 条");
  assert.match(nodes.viewExplanation.textContent, /活动日历/);
  assert.match(nodes.eventsList.innerHTML, /部分学校，高三除外/);
  assert.match(nodes.eventsList.innerHTML, /连休观察窗口：2026-11-11 至 2026-11-15/);
  nodes.recordFilter.value = "leads"; nodes.recordFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent, "20 条");
  assert.match(nodes.viewExplanation.textContent, /新闻线索总计 457 条/);
});

test("a disputed holiday report cannot enter the future view, and origin signals stay outside local activities", async () => {
  const disputed = calendarRow({event_id:'rumour',event_name:'杭州秋假11月11日—13日定了？相关部门回应'});
  const signal = calendarRow({event_id:'sig_origin',record_kind:'source_market_signal',city_name:'汉中市',city_slug:'hanzhong',event_name:'汉中秋假',impact_destination_cities:['西安市'],scope_note:'客源地，不代表西安本地活动或住宿增量'});
  const nodes = await loadPage([disputed], {activities:{data:[],source_market_signals:[signal]},recordLayer:'leads'});
  assert.equal(nodes.resultCount.textContent, '0 条');
  assert.equal(nodes.sourceMarketDetails.hidden, false);
  assert.match(nodes.sourceMarketSignals.innerHTML, /客源地：汉中市/);
  nodes.cityFilter.value='西安市'; nodes.cityFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent, '0 条');
  assert.equal(nodes.sourceMarketDetails.hidden, false);
  nodes.cityFilter.value='成都市'; nodes.cityFilter.listeners.input();
  assert.equal(nodes.sourceMarketDetails.hidden, true);
});

test("the news-candidate shortcut changes the data layer without losing the selected city", async () => {
  const lead=calendarRow({event_id:'news_date'});
  const nodes=await loadPage([lead], {activities:{data:[]},recordLayer:'activities'});
  nodes.cityFilter.value='杭州市'; nodes.cityFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent,'0 条');
  nodes.showLeadCandidatesBtn.listeners.click();
  assert.equal(nodes.recordFilter.value,'leads');
  assert.equal(nodes.cityFilter.value,'杭州市');
  assert.equal(nodes.resultCount.textContent,'1 条');
});

test("large lists render in batches while PNG export keeps every filtered row", async () => {
  const rows=Array.from({length:350},(_,i)=>calendarRow({event_id:'batch_'+i,event_name:'杭州音乐会'+i}));
  let exported;
  const nodes=await loadPage(rows,{recordLayer:'leads',shareApi:{plan(ctx,model){exported=model;return {pages:[{cards:model.rows}]};},render(){},toBlob:async()=>({type:'image/png'})}});
  assert.equal(nodes.resultCount.textContent,'350 条');
  assert.equal((nodes.eventsList.innerHTML.match(/<article /g)||[]).length,100);
  assert.match(nodes.listProgress.textContent,/350 条，已展示 100 条/);
  nodes.showMoreBtn.listeners.click();
  assert.equal((nodes.eventsList.innerHTML.match(/<article /g)||[]).length,200);
  await nodes.exportPngBtn.listeners.click();
  assert.equal(exported.rows.length,350);
  nodes.cityFilter.value='杭州市';nodes.cityFilter.listeners.input();
  assert.equal((nodes.eventsList.innerHTML.match(/<article /g)||[]).length,100);
});

test("disjoint performance sessions do not match gap days or render a continuous interval", async () => {
  const row = calendarRow({event_type:"concert",event_name:"杭州演唱会",start_at:"2026-11-06",end_at:"2026-11-08",
    sessions:[{start_at:"2026-11-06",end_at:"2026-11-06"},{start_at:"2026-11-08",end_at:"2026-11-08"}]});
  const nodes = await loadPage([], {activities:{data:[row]}});
  assert.match(nodes.eventsList.innerHTML, /2026-11-06、2026-11-08/);
  assert.doesNotMatch(nodes.eventsList.innerHTML, /2026-11-06 至 2026-11-08/);
  nodes.dateFrom.value = nodes.dateTo.value = "2026-11-07"; nodes.dateFrom.listeners.input();
  assert.equal(nodes.resultCount.textContent, "0 条");
  nodes.dateFrom.value = nodes.dateTo.value = "2026-11-08"; nodes.dateFrom.listeners.input();
  assert.equal(nodes.resultCount.textContent, "1 条");
});

test("a fresh rebuild cannot disguise stale collection, and the 90-day window retains later records in all content", async () => {
  const row = calendarRow({start_at:"2027-05-14",end_at:"2027-05-14",sessions:[{start_at:"2027-05-14",end_at:"2027-05-14"}]});
  const nodes = await loadPage([], {clockAt:"2026-11-04T01:00:00Z", meta:{generated_at:"2026-11-04T01:00:00Z",last_collection_at:"2026-10-30T01:55:55Z",monitoring_horizon_days:90},
    health:{status:"healthy",successful_feeds:28,city_count:28},activities:{meta:{generated_at:"2026-11-04T01:00:00Z"},data:[row]}});
  assert.match(nodes.updatedAt.textContent, /2026\/10\/30/);
  assert.equal(nodes.healthLabel.textContent, "快照待更新");
  assert.equal(nodes.resultCount.textContent, "0 条");
  nodes.contentFilter.value = "all"; nodes.contentFilter.listeners.input();
  assert.equal(nodes.resultCount.textContent, "1 条");
  assert.match(nodes.coverageSummary.textContent, /覆盖|补齐/);
});

test("missing calendar data falls back explicitly to leads, without claiming a city has no events", async () => {
  const nodes = await loadPage(snapshot.data, {recordLayer:"activities"});
  assert.equal(nodes.recordFilter.value, "leads");
  assert.equal(nodes.resultCount.textContent, "20 条");
  assert.match(nodes.coverageSummary.textContent, /活动日历暂不可用/);
  assert.match(nodes.coverageTable.innerHTML, /零条不代表该城市没有活动/);
});

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

test("PNG export uses the exact current filtered set and freezes labels without promoting records", async () => {
  let exported;
  const original = JSON.stringify(snapshot.data);
  const nodes = await loadPage(snapshot.data, {shareApi: {
    plan(ctx, model) { exported = model; return {pages: [{cards: model.rows}]}; },
    render() {}, toBlob: async () => ({type: "image/png"}),
  }});
  nodes.cityFilter.value = "杭州市";
  nodes.typeFilter.value = "sports";
  nodes.dateFrom.value = nodes.dateTo.value = "2026-11-01";
  nodes.searchInput.value = "马拉松";
  nodes.searchInput.listeners.input();
  assert.equal(nodes.resultCount.textContent, "4 条");
  await nodes.exportPngBtn.listeners.click();
  assert.equal(exported.rows.length, 4);
  assert.ok(exported.rows.every(row => row.city === "杭州市" && row.review === "待核验" && row.date.includes("2026-11-01")));
  assert.match(exported.filters, /杭州市/);
  assert.match(exported.filters, /2026-11-01/);
  assert.equal(exported.preview, true);
  assert.equal(exported.publicUrl, "https://wildpig622.github.io/hotspot-pulse/");
  assert.equal(nodes.sharePreview.src, "blob:test-image");
  nodes.searchInput.value = "no matching event";
  nodes.searchInput.listeners.input();
  assert.equal(exported.rows.length, 4, "an open image remains a snapshot of the exported selection");
  assert.equal(JSON.stringify(snapshot.data), original);
});

test("an empty selection disables PNG export and does not produce a misleading blank calendar", async () => {
  const nodes = await loadPage([]);
  assert.equal(nodes.exportPngBtn.disabled, true);
  await nodes.exportPngBtn.listeners.click();
  assert.match(nodes.exportMessage.textContent, /没有可导出/);
});

test("denied clipboard access gives a save-PNG fallback without losing the generated image", async () => {
  let attemptedType;
  const nodes = await loadPage([byId.evt_cfd1dabb5e54], {
    shareApi: {plan(ctx, model) {return {pages: [{cards:model.rows}]};}, render() {}, toBlob: async () => ({type:"image/png"})},
    ClipboardItem: class { constructor(values) {attemptedType = Object.keys(values)[0];} },
    navigator: {clipboard: {write: async () => {throw new Error("permission denied");}}},
  });
  await nodes.exportPngBtn.listeners.click();
  assert.equal(nodes.copyPngBtn.hidden, false);
  await nodes.copyPngBtn.listeners.click();
  assert.equal(attemptedType, "image/png");
  assert.match(nodes.shareStatus.textContent, /保存 PNG/);
  assert.equal(nodes.downloadPngBtn.disabled, false);
  assert.equal(nodes.sharePreview.src, "blob:test-image");
});
