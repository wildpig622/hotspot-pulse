(function () {
  "use strict";
  var API_URL = "./api/v1/hotspots.json";
  var HEALTH_URL = "./api/v1/health.json";
  var CITIES_URL = "./api/v1/cities.json";
  var TYPE_LABELS = { concert: "演出 / 演唱会", exhibition: "展会", sports: "赛事", festival: "节庆", holiday: "假期", other: "其他" };
  var CONTENT_LABELS = { event_announcement: "活动公告", uncertain: "活动线索待核实", ticketing_notice: "开票 / 售票信息", registration_notice: "报名信息", schedule_roundup: "排期汇总", guide: "攻略 / 购票资讯", past_report: "历史报道", other: "其他资讯" };
  var NON_EVENT_KINDS = { guide: true, schedule_roundup: true, ticketing_notice: true, registration_notice: true, other: true };
  var CONDITIONAL_EVENT = /审批中|正在审批|待审批|尚未获批|未获批准|或(?:将|定档|于)|拟定档|暂定|待官宣|尚未官宣|网传|有望/;
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
  function contentKind(event) {
    var title = String(event.event_name || "");
    // Recheck strong exclusions when reading the unchanged legacy snapshot.
    if (/冠军诞生|夺冠|圆满落幕|圆满结束|成功举办|顺利举行|现场回顾|精彩回顾|赛后|完美收官|圆满收官|已结束|落幕|比赛结束|赛事回顾|演出回顾|昨(?:日|天|晚)?[^，。！？；]{0,8}(?:开跑|开赛|举行|举办|开演)/.test(title)) return "past_report";
    if (event.content_kind) return event.content_kind;
    if (/有哪些|有什么|攻略|指南|购票平台|票务平台|怎么买票|怎么买|如何|怎么预约|靠谱|推荐|观演攻略|出行攻略|门票价格|购票教程|抢票技巧/.test(title)) return "guide";
    if (/排期|排期表|节目单|时间表|日程安排|演出安排|展会安排|演出汇总|演出合集|演出一览|演出清单|月度演出|本月演出|活动日历|活动汇总|展会日历/.test(title)) return "schedule_roundup";
    if (CONDITIONAL_EVENT.test(title)) return "uncertain";
    if (/将于|定于|定档|举行|举办|开幕|开赛|开演|开跑|启幕|上演|开展|举办时间|活动时间|赛事时间|演出时间|比赛时间/.test(title) && /演唱会|音乐节|展会|博览会|马拉松|体育赛事|赛事|演出|漫展|节庆|车展|展览|巡演|音乐会|嘉年华|文化节|美食节|灯会|庙会/.test(title)) return "event_announcement";
    if (/报名启动|报名开启|报名时间|报名截止|报名通道|开放报名|开始报名|报名即将开始|报名啦|开启报名/.test(title)) return "registration_notice";
    if (/开票|开售|售票|预售|抢票|门票|票价|发售|开抢/.test(title) && !/将于|定于|定档|举行|举办|开幕|开赛|开演|开跑|启幕|上演|开展|举办时间|活动时间|赛事时间|比赛时间/.test(title)) return "ticketing_notice";
    if (/演唱会|音乐节|展会|博览会|马拉松|体育赛事|赛事|演出|漫展|节庆|车展|展览|巡演|音乐会|嘉年华|文化节|美食节|灯会|庙会/.test(title)) return "uncertain";
    return "other";
  }
  function beijingToday() {
    var parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
    var values = {};
    parts.forEach(function (part) { if (part.type !== "literal") values[part.type] = part.value; });
    return values.year + "-" + values.month + "-" + values.day;
  }
  function isExpiredEvent(event, today) {
    var kind = contentKind(event);
    if (NON_EVENT_KINDS[kind] || !event.start_at) return false;
    var end = event.end_at || event.start_at;
    return end < today;
  }
  function isUpcomingDatedEvent(event, today) {
    var kind = contentKind(event);
    if (kind !== "event_announcement" && kind !== "uncertain") return false;
    if (futureExclusion(event)) return false;
    if (!event.start_at || event.date_precision === "month" || event.date_precision === "month_range") return false;
    if (event.event_date_role === "ticket_sale" || event.event_date_role === "registration" || event.event_date_role === "reference_period") return false;
    return (event.end_at || event.start_at) >= today;
  }
  function validCalendarDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    try { return new Date(value + "T00:00:00Z").toISOString().slice(0, 10) === value; }
    catch (e) { return false; }
  }
  function legacyDateView(event, today) {
    // Project only reproducible title dates for old, unreviewed records. Never
    // mutate the loaded snapshot or replace a semantic/human-reviewed date.
    if (event.review_status === "verified" || event.event_date_role) return event;
    var title = String(event.event_name || "");
    var kind = contentKind(event);
    if (kind !== "event_announcement" && kind !== "uncertain") return event;
    if (CONDITIONAL_EVENT.test(title)) return event;
    var dayString = function (year, month, day) {
      return String(year).padStart(4, "0") + "-" + String(month).padStart(2, "0") + "-" + String(day).padStart(2, "0");
    };
    var ranges = Array.from(title.matchAll(/(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日\s*(?:至|到|—|－|-|~|～)\s*(?:(20\d{2})年)?(?:(\d{1,2})月)?(\d{1,2})日/g));
    if (ranges.length === 1 && event.date_precision === "day" && validCalendarDate(event.start_at)) {
      var range = ranges[0];
      var year = Number(range[1] || event.start_at.slice(0, 4));
      var start = dayString(year, Number(range[2]), Number(range[3]));
      var endMonth = Number(range[5] || range[2]);
      var endYear = Number(range[4] || year + (endMonth < Number(range[2]) ? 1 : 0));
      var end = dayString(endYear, endMonth, Number(range[6]));
      if (start === event.start_at && validCalendarDate(end) && end >= start && !event.end_at) {
        return Object.assign({}, event, {end_at: end});
      }
    }
    if (event.date_precision === "month" && ranges.length === 0) {
      var days = Array.from(title.matchAll(/(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日/g));
      if (days.length === 1 && /举行|举办|开幕|开赛|开演|开跑|启幕/.test(title) && !/开票|开售|售票|预售|报名/.test(title)) {
        var day = days[0];
        var value = dayString(Number(day[1] || today.slice(0, 4)), Number(day[2]), Number(day[3]));
        var age = (new Date(today + "T00:00:00Z") - new Date(value + "T00:00:00Z")) / 86400000;
        if (validCalendarDate(value) && event.start_at && value.slice(0, 7) === event.start_at.slice(0, 7) && (day[1] || age <= 60)) {
          return Object.assign({}, event, {start_at: value, end_at: null, date_precision: "day", date_confidence: day[1] ? "explicit_year" : "inferred_year"});
        }
      }
    }
    return event;
  }
  function futureExclusion(event) {
    var title = String(event.event_name || "");
    if (event.start_at && (!validCalendarDate(event.start_at) ||
        (event.end_at && (!validCalendarDate(event.end_at) || event.end_at < event.start_at)))) return "日期区间无效，需复核";
    if (CONDITIONAL_EVENT.test(title) || event.event_confirmation === "unconfirmed") return "举办安排尚未确认";
    if (event.city_match === "event_city_conflict") return "举办城市与记录城市不符";
    if (!state.cities.length && event.city_slug) return "举办城市暂时无法核对";
    var firstEvent = /演唱会|音乐节|展会|博览会|马拉松|体育赛事|赛事|演出|漫展|节庆|车展|展览|巡演|音乐会|嘉年华|文化节|美食节|灯会|庙会/.exec(title);
    if (firstEvent) {
      var prefix = title.slice(Math.max(0, firstEvent.index - 18), firstEvent.index);
      var host = null;
      var hostEnd = -1;
      state.cities.forEach(function (city) {
        (city.aliases || [String(city.city_name || "").replace(/市$/, "")]).forEach(function (alias) {
          if (!alias) return;
          var index = prefix.lastIndexOf(alias);
          if (index >= 0 && index + alias.length > hostEnd && !/[，。！？；,;:：]/.test(prefix.slice(index + alias.length))) {
            host = city; hostEnd = index + alias.length;
          }
        });
      });
      if (host && host.city_name !== event.city_name) return "举办城市与记录城市不符";
    }
    if (event.city_match === "query_only") return "举办城市待核实";
    if (!event.event_date_role && event.start_at && event.date_confidence === "inferred_year" && event.start_at.slice(0, 4) > beijingToday().slice(0, 4)) return "旧记录推断到下一年，需复核年份";
    if (event.start_at && !event.event_date_role) {
      var quantities = /(\d{1,2})[/.](\d{1,2})(?![\d./])\s*(?:万|亿|千|百|人|名|件|通|元|%|％|小时|公里)/g;
      var quantity;
      while ((quantity = quantities.exec(title))) {
        var monthDay = String(Number(quantity[1])).padStart(2, "0") + "-" + String(Number(quantity[2])).padStart(2, "0");
        if (event.start_at.slice(5) === monthDay) return "数量不能作为举办日期";
      }
    }
    return "";
  }
  function eventDateLabel(event) {
    var kind = contentKind(event);
    var extras = [];
    var exclusion = futureExclusion(event);
    if (exclusion) return "活动日期待核实 · " + exclusion;
    if (event.ticket_sale_at) extras.push("开票/售票：" + event.ticket_sale_at + "（不是举办日期）");
    if (event.registration_at) extras.push("报名日期：" + event.registration_at + "（不是举办日期）");
    if (event.reference_period_start) {
      var period = event.reference_period_start;
      if (event.reference_period_end && event.reference_period_end !== period) period += " 至 " + event.reference_period_end;
      extras.push("内容提及期间：" + period + "（不是单场举办日期）");
    }
    if (NON_EVENT_KINDS[kind]) return extras.length ? "非单场活动 · " + extras.join("；") : "非单场活动信息，日期不作为举办日期";
    if (!event.start_at) return extras.length ? "活动日期待核实 · " + extras.join("；") : "活动日期待核实";
    var label = event.start_at;
    if (event.end_at && event.end_at !== event.start_at) label += " 至 " + event.end_at;
    if (event.date_precision === "month" || event.date_precision === "month_range") label = "仅知月份：" + label + "（非具体举办日）";
    if (event.event_date_role === "ambiguous") label += " · 日期语义待核实";
    if (event.date_confidence === "inferred_year") label += " · 年份推断";
    if (extras.length) label += "；" + extras.join("；");
    return label;
  }
  function renderMetrics() {
    var events = state.events;
    var sources = {};
    events.forEach(function (event) { (event.sources || []).forEach(function (source) { if (source.source_url) sources[source.source_url] = true; }); });
    $("metricTotal").textContent = String(events.length);
    $("metricDated").textContent = String(events.filter(function (event) { return isUpcomingDatedEvent(event, beijingToday()); }).length);
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
    var content = $("contentFilter").value || "future";
    var from = $("dateFrom").value;
    var to = $("dateTo").value;
    var today = beijingToday();
    return state.events.filter(function (event) {
      var sourceText = (event.sources || []).map(function (s) { return [s.publisher, s.source_url].join(" "); }).join(" ");
      var haystack = [event.event_name, event.city_name, event.venue_name, sourceText].join(" ").toLowerCase();
      var kind = contentKind(event);
      var upcoming = isUpcomingDatedEvent(event, today);
      var expired = isExpiredEvent(event, today);
      var eventCandidate = kind === "event_announcement" || kind === "uncertain";

      if (content === "future" && !upcoming) return false;
      if (content === "undated" && (!eventCandidate || upcoming || expired)) return false;
      if (content === "ticketing" && kind !== "ticketing_notice" && kind !== "registration_notice") return false;
      if (content === "schedule" && kind !== "schedule_roundup") return false;
      if (content === "guide" && kind !== "guide" && kind !== "other") return false;
      if (content === "past" && kind !== "past_report" && !expired) return false;
      if (q && haystack.indexOf(q) === -1) return false;
      if (city && event.city_name !== city) return false;
      if (type && event.event_type !== type) return false;
      if (review && event.review_status !== review) return false;
      var filterStart = event.start_at || event.reference_period_start || event.ticket_sale_at || event.registration_at;
      var filterEnd = event.end_at || event.reference_period_end || filterStart;
      if (from && (!filterStart || filterEnd < from)) return false;
      if (to && (!filterStart || filterStart > to)) return false;
      return true;
    });
  }
  function renderEvents() {
    var events = getFilteredEvents();
    $("resultCount").textContent = events.length + " 条";
    if (!events.length) {
      $("eventsList").innerHTML = '<div class="empty-state">当前视图没有符合条件的内容。可切换开票/报名、排期汇总或全部内容查看相关线索。</div>';
      return;
    }
    $("eventsList").innerHTML = events.map(function (event) {
      var review = event.review_status === "verified" ? '<span class="badge badge-verified">已核验</span>' : '<span class="badge badge-pending">待核验</span>';
      var kind = contentKind(event);
      var kindBadge = '<span class="badge badge-neutral">' + escapeHtml(CONTENT_LABELS[kind] || "其他资讯") + '</span>';
      var cityMatch = event.city_match === "event_city_conflict" ? '<span class="badge badge-pending">举办城市不符，需复核</span>' : event.city_match === "text_confirmed" ? '<span class="badge badge-neutral">正文出现城市名</span>' : '<span class="badge badge-neutral">按城市检索命中</span>';
      var sourceCount = (event.sources || []).length;
      var sourcePublish = event.sources && event.sources[0] ? event.sources[0].source_published_at : null;
      var confidence = event.event_date_role === "ticket_sale" ? "开票日期，不是举办日期" : event.event_date_role === "registration" ? "报名日期，不是举办日期" : event.event_date_role === "ambiguous" ? "日期语义待核实" : event.date_confidence === "explicit_year" ? "标题/摘要含年份" : event.date_confidence === "inferred_year" ? "年份推断，需核验" : "未提取到举办日期";
      return '<article class="event-card"><div class="event-main">' +
        '<div class="event-title-row"><span class="event-title">' + escapeHtml(text(event.event_name, "未命名事件")) + '</span>' + review + kindBadge +
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
    ["searchInput", "cityFilter", "typeFilter", "reviewFilter", "contentFilter", "dateFrom", "dateTo"].forEach(function (id) {
      $(id).addEventListener("input", applyFilters);
      $(id).addEventListener("change", applyFilters);
    });
    $("clearBtn").addEventListener("click", function () {
      ["searchInput", "cityFilter", "typeFilter", "reviewFilter", "dateFrom", "dateTo"].forEach(function (id) { $(id).value = ""; });
      $("contentFilter").value = "future";
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
        state.events = Array.isArray(results[0].value.data) ? results[0].value.data.map(function (event) { return legacyDateView(event, beijingToday()); }) : [];
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
