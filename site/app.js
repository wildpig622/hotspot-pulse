(function () {
  "use strict";
  var API_URL = "./api/v1/hotspots.json";
  var HEALTH_URL = "./api/v1/health.json";
  var CITIES_URL = "./api/v1/cities.json";
  var TYPE_LABELS = { concert: "演出 / 演唱会", exhibition: "展会", sports: "赛事", festival: "节庆", holiday: "假期", other: "其他" };
  var state = { events: [], meta: {}, health: {}, cities: [] };
  var $ = function (id) { return document.getElementById(id); };

  function text(value, fallback) { return value === null || value === undefined || value === "" ? (fallback || "待核实") : String(value); }
  function formatTime(value) {
    if (!value) return "尚无记录";
    try { return new Date(value).toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" }); }
    catch (e) { return value; }
  }
  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function sourceLabel(event) {
    var sources = event.sources || [];
    if (!sources.length) return "无来源链接";
    var href = sources[0].source_url || "";
    if (!/^https:\/\//i.test(href)) return "来源链接不可用";
    return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener">查看来源 ↗</a>';
  }
  function eventDateLabel(event) {
    if (!event.start_at) return "日期待核实";
    var label = event.start_at;
    if (event.end_at && event.end_at !== event.start_at) label += " 至 " + event.end_at;
    if (event.date_precision === "month") label += "（月份范围）";
    if (event.date_confidence === "inferred_year") label += " · 年份推断";
    return label;
  }
  function renderMetrics() {
    var events = state.events;
    var sources = {};
    events.forEach(function (event) { (event.sources || []).forEach(function (source) { if (source.source_url) sources[source.source_url] = true; }); });
    $("metricTotal").textContent = String(events.length);
    $("metricDated").textContent = String(events.filter(function (event) { return Boolean(event.start_at); }).length);
    $("metricSources").textContent = String(Object.keys(sources).length);
    $("metricCities").textContent = String(state.cities.length || state.meta.city_count || 0);
    $("updatedAt").textContent = "数据更新于 " + formatTime(state.meta.generated_at || state.health.last_run_at);
    $("sourceInfo").textContent = "数据源：" + text(state.meta.source_system, "Google News RSS") + " · 状态：" + text(state.meta.collection_status || state.health.status, "尚未运行");
    var status = state.health.status || state.meta.collection_status || "not_run";
    var labels = { healthy: "采集正常", degraded: "部分来源失败", failed: "最近采集失败", not_run: "等待首次采集" };
    var details = status === "healthy"
      ? "成功 " + text(state.health.successful_feeds, state.meta.successful_feeds || 0) + " / " + text(state.health.city_count, state.meta.city_count || 0) + " 城市源"
      : status === "degraded"
        ? "成功 " + text(state.health.successful_feeds, 0) + " · 失败 " + text(state.health.failed_feeds, 0) + "；保留已有数据"
        : status === "failed"
          ? "所有来源均失败；上一份事件快照已保留"
          : "尚无采集状态";
    $("healthLabel").textContent = labels[status] || "状态未知";
    $("healthDetail").textContent = details;
    $("healthDot").className = "status-dot " + (status === "healthy" ? "status-healthy" : status === "degraded" ? "status-degraded" : status === "failed" ? "status-failed" : "status-muted");
  }
  function fillCities() {
    var select = $("cityFilter");
    var oldValue = select.value;
    select.innerHTML = '<option value="">全部城市</option>';
    state.cities.forEach(function (city) {
      var option = document.createElement("option");
      option.value = city.city_name;
      option.textContent = city.city_name;
      select.appendChild(option);
    });
    if (oldValue) select.value = oldValue;
  }
  function getFilteredEvents() {
    var q = $("searchInput").value.trim().toLowerCase();
    var city = $("cityFilter").value;
    var type = $("typeFilter").value;
    var review = $("reviewFilter").value;
    var from = $("dateFrom").value;
    var to = $("dateTo").value;
    return state.events.filter(function (event) {
      var sourceText = (event.sources || []).map(function (s) { return [s.publisher, s.source_url].join(" "); }).join(" ");
      var haystack = [event.event_name, event.city_name, event.venue_name, sourceText].join(" ").toLowerCase();
      if (q && haystack.indexOf(q) === -1) return false;
      if (city && event.city_name !== city) return false;
      if (type && event.event_type !== type) return false;
      if (review && event.review_status !== review) return false;
      if (from && (!event.start_at || (event.end_at || event.start_at) < from)) return false;
      if (to && (!event.start_at || event.start_at > to)) return false;
      return true;
    });
  }
  function renderEvents() {
    var events = getFilteredEvents();
    $("resultCount").textContent = events.length + " 条";
    if (!events.length) {
      $("eventsList").innerHTML = '<div class="empty-state">当前筛选没有候选事件。若首次采集尚未运行，请到 GitHub Actions 手动触发 Daily hotspot collection。</div>';
      return;
    }
    $("eventsList").innerHTML = events.map(function (event) {
      var review = event.review_status === "verified" ? '<span class="badge badge-verified">已核验</span>' : '<span class="badge badge-pending">待核验</span>';
      var cityMatch = event.city_match === "text_confirmed" ? '<span class="badge badge-neutral">正文出现城市名</span>' : '<span class="badge badge-neutral">按城市检索命中</span>';
      var sourceCount = (event.sources || []).length;
      var sourcePublish = event.sources && event.sources[0] ? event.sources[0].source_published_at : null;
      var confidence = event.date_confidence === "explicit_year" ? "标题/摘要含年份" : event.date_confidence === "inferred_year" ? "年份推断，需核验" : "未提取到日期";
      return '<article class="event-card"><div class="event-main">' +
        '<div class="event-title-row"><span class="event-title">' + escapeHtml(text(event.event_name, "未命名事件")) + '</span>' + review +
        '<span class="badge badge-neutral">' + escapeHtml(TYPE_LABELS[event.event_type] || "其他") + '</span></div>' +
        '<div class="event-meta"><span>城市：' + escapeHtml(text(event.city_name)) + '</span><span>活动日期：' + escapeHtml(eventDateLabel(event)) + '</span><span>' + escapeHtml(confidence) + '</span></div>' +
        '<div class="event-description">来源：' + escapeHtml(text(event.sources && event.sources[0] && event.sources[0].publisher, "未知发布方")) +
        ' · 来源发布时间：' + escapeHtml(formatTime(sourcePublish)) + ' · 系统首次发现：' + escapeHtml(formatTime(event.first_seen_at)) +
        ' · 来源数：' + sourceCount + '<br>' + cityMatch + '</div></div>' +
        '<div class="event-sources">' + sourceLabel(event) + '<span>最近发现：' + escapeHtml(formatTime(event.last_seen_at)) + '</span></div></article>';
    }).join("");
  }
  function applyFilters() { renderEvents(); }
  function bindEvents() {
    ["searchInput", "cityFilter", "typeFilter", "reviewFilter", "dateFrom", "dateTo"].forEach(function (id) {
      $(id).addEventListener("input", applyFilters);
      $(id).addEventListener("change", applyFilters);
    });
    $("clearBtn").addEventListener("click", function () {
      ["searchInput", "cityFilter", "typeFilter", "reviewFilter", "dateFrom", "dateTo"].forEach(function (id) { $(id).value = ""; });
      renderEvents();
    });
    $("refreshBtn").addEventListener("click", loadData);
    $("copyEndpoint").addEventListener("click", function () {
      var url = new URL(API_URL, window.location.href).href;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(function () { $("copyEndpoint").textContent = "已复制"; }).catch(function () { window.prompt("复制 API 地址", url); });
      } else { window.prompt("复制 API 地址", url); }
    });
    $("endpointUrl").textContent = new URL(API_URL, window.location.href).href;
  }
  function fetchJson(url) {
    return fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status + " for " + url);
      return response.json();
    });
  }
  function loadData() {
    $("refreshBtn").disabled = true;
    $("refreshBtn").textContent = "读取中…";
    $("feedError").hidden = true;
    Promise.allSettled([fetchJson(API_URL), fetchJson(HEALTH_URL), fetchJson(CITIES_URL)]).then(function (results) {
      if (results[0].status === "fulfilled") {
        state.meta = results[0].value.meta || {};
        state.events = Array.isArray(results[0].value.data) ? results[0].value.data : [];
      } else {
        $("feedError").hidden = false;
        $("feedError").textContent = "事件 JSON 读取失败：" + results[0].reason.message + "。请检查 Pages 是否已启用，以及 API 文件是否发布。";
      }
      if (results[1].status === "fulfilled") state.health = results[1].value || {};
      if (results[2].status === "fulfilled") state.cities = results[2].value.data || [];
      fillCities(); renderMetrics(); renderEvents();
    }).catch(function (error) {
      $("feedError").hidden = false;
      $("feedError").textContent = "读取失败：" + error.message;
    }).finally(function () {
      $("refreshBtn").disabled = false;
      $("refreshBtn").textContent = "刷新数据";
    });
  }
  bindEvents();
  loadData();
}());
