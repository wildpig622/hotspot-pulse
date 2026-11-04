(function () {
  "use strict";
  var API_URL = "./api/v1/hotspots.json";
  var HEALTH_URL = "./api/v1/health.json";
  var CITIES_URL = "./api/v1/cities.json";
  var ACTIVITIES_URL = "./api/v1/activities.json";
  var COVERAGE_URL = "./api/v1/coverage.json";
  var EVENT_FEED_URL = "./api/v2/events.json";
  var TYPE_LABELS = { concert: "演出 / 演唱会", exhibition: "展会", sports: "赛事", festival: "节庆", holiday: "学生假期 / 放假调整", conference: "会议 / 峰会", other: "其他" };
  var CONTENT_LABELS = { event_announcement: "活动公告", uncertain: "活动线索待核实", ticketing_notice: "开票 / 售票信息", registration_notice: "报名信息", schedule_roundup: "排期汇总", guide: "攻略 / 购票资讯", past_report: "历史报道", other: "其他资讯" };
  var NON_EVENT_KINDS = { guide: true, schedule_roundup: true, ticketing_notice: true, registration_notice: true, other: true };
  var CONDITIONAL_EVENT = /审批中|正在审批|待审批|尚未获批|未获批准|或(?:将|定档|于)|拟定档|暂定|待官宣|尚未官宣|网传|有望|辟谣|不属实|不实消息|尚未确定|未确定|相关部门回应|官方回应/;
  var state = { events: [], leads: [], activities: [], discoveryCandidates: [], sourceCandidates: [], sourceChecks: [], backlog: [], sourceMarketSignals: [], visibleLimit: 100, calendarAvailable: false, calendarMeta: {}, coverage: {}, meta: {}, health: {}, cities: [] };
  var shareSession = null;
  var shareRevision = 0;
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
  function beijingDay(value) {
    var parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(value));
    var values = {};
    parts.forEach(function (part) { if (part.type !== "literal") values[part.type] = part.value; });
    return values.year + "-" + values.month + "-" + values.day;
  }
  function beijingToday() { return beijingDay(new Date()); }
  function isExpiredEvent(event, today) {
    var kind = contentKind(event);
    if (NON_EVENT_KINDS[kind] || !event.start_at) return false;
    return eventRanges(event).every(function (range) { return range.end < today; });
  }
  function eventRanges(event) {
    var sessions = Array.isArray(event.sessions) && event.sessions.length ? event.sessions : [{ start_at: event.start_at, end_at: event.end_at || event.start_at }];
    return sessions.map(function (row) { return { start: row.start_at, end: row.end_at || row.start_at }; });
  }
  function monitoringEnd(today) {
    var horizon = Number(state.meta.monitoring_horizon_days || 365);
    var end = new Date(today + "T00:00:00Z");
    end.setUTCDate(end.getUTCDate() + Math.max(1, Math.min(365, horizon)));
    return end.toISOString().slice(0, 10);
  }
  function inMonitoringWindow(event, today) {
    return eventRanges(event).some(function (range) { return range.end >= today && range.start <= monitoringEnd(today); });
  }
  function isUpcomingDatedEvent(event, today) {
    if (event.review_status === "rejected") return false;
    if (["needs_date_review", "not_recently_observed", "expired"].indexOf(event.availability) >= 0) return false;
    var kind = contentKind(event);
    if (kind !== "event_announcement" && kind !== "uncertain") return false;
    if (futureExclusion(event)) return false;
    if (event.event_status === "cancelled" || event.event_status === "postponed") return false;
    if (!event.start_at || event.date_precision === "month" || event.date_precision === "month_range") return false;
    if (event.event_date_role === "ticket_sale" || event.event_date_role === "registration" || event.event_date_role === "reference_period") return false;
    return eventRanges(event).some(function (range) { return range.end >= today; });
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
    if (Array.isArray(event.sessions) && event.sessions.some(function (session) {
      return !validCalendarDate(session.start_at) || !validCalendarDate(session.end_at || session.start_at) || (session.end_at || session.start_at) < session.start_at;
    })) return "日期区间无效，需复核";
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
    var label = eventRanges(event).map(function (range) { return range.start + (range.end !== range.start ? " 至 " + range.end : ""); }).join("、");
    if (event.date_precision === "month" || event.date_precision === "month_range") label = "仅知月份：" + label + "（非具体举办日）";
    if (event.event_date_role === "ambiguous") label += " · 日期语义待核实";
    if (event.date_confidence === "inferred_year") label += " · 年份推断";
    if (event.travel_windows && event.travel_windows.length) label += "；连休观察窗口：" + event.travel_windows.map(function (range) { return range.start_at + " 至 " + range.end_at; }).join("、");
    if (extras.length) label += "；" + extras.join("；");
    return label;
  }
  function renderMetrics() {
    var events = state.events;
    var sources = {};
    events.forEach(function (event) { (event.sources || []).forEach(function (source) { if (source.source_url) sources[source.source_url] = true; }); });
    $("metricTotal").textContent = String(state.leads.length);
    $("metricDated").textContent = String(events.filter(function (event) { return isUpcomingDatedEvent(event, beijingToday()) && inMonitoringWindow(event, beijingToday()); }).length);
    $("metricSources").textContent = String(Object.keys(sources).length);
    $("metricCities").textContent = String(state.cities.length || state.meta.city_count || 0);
    var collectedAt = state.meta.last_collection_at || state.health.last_run_at || state.meta.generated_at;
    $("updatedAt").textContent = "自动采集截至 " + formatTime(collectedAt);
    $("sourceInfo").textContent = "数据源：" + ($("recordFilter").value === "activities" ? "公告正文 + 票务日期候选 + 新闻候选" : text(state.meta.source_system, "Google News RSS")) + " · 覆盖待补齐";
    var status = state.health.status || state.meta.collection_status || "not_run";
    var stale = collectedAt && beijingToday() > beijingDay(collectedAt);
    var labels = { healthy: stale ? "快照待更新" : "上次采集成功", degraded: "上次采集部分失败", failed: "最近采集失败", not_run: "等待首次采集" };
    var details = status === "healthy"
      ? "成功 " + text(state.health.successful_feeds, state.meta.successful_feeds || 0) + " / " + text(state.health.feed_count, state.meta.feed_count || state.health.city_count || state.meta.city_count || 0) + " 个检索源；覆盖仍待补齐"
      : status === "degraded"
        ? "成功 " + text(state.health.successful_feeds, 0) + " · 失败 " + text(state.health.failed_feeds, 0) + "；保留已有数据"
        : status === "failed"
          ? "所有来源均失败；上一份事件快照已保留"
          : "尚无采集状态";
    $("healthLabel").textContent = labels[status] || "状态未知";
    $("healthDetail").textContent = details;
    $("healthDot").className = "status-dot " + (status === "healthy" && !stale ? "status-healthy" : status === "degraded" ? "status-degraded" : status === "failed" ? "status-failed" : "status-muted");
    $("coverageSummary").textContent = "新闻线索 " + state.leads.length + " 条 · 已整理活动 " + state.activities.length + " 项 · 票务日期候选 " + state.sourceCandidates.length + " 条 · 带日期新闻候选 " + state.discoveryCandidates.length + " 条。候选可能重复，仍待核验。假期 " + state.activities.filter(function (event) { return event.event_type === "holiday"; }).length + " 项。" +
      (state.calendarAvailable ? "活动来源与日期仍待核验，28城×6类内容持续补齐。" : "活动日历暂不可用，当前显示新闻线索。") +
      (state.sourceMarketSignals.length ? " 另有 " + state.sourceMarketSignals.length + " 项客源地假期信号，单独观察。" : "") +
      " 每天北京时间08:00、16:00自动更新，平台任务可能排队延迟；网页刷新读取已发布快照。日历整理于 " + formatTime(state.calendarMeta.generated_at) + "。" + (state.canonicalEvents ? " 统一活动记录 " + state.canonicalEvents.length + " 项；已明确关联的重复报道合并展示。" : "");
  }
  function selectRecordLayer() {
    if (!state.calendarAvailable) $("recordFilter").value = "leads";
    else if (!$("recordFilter").value) $("recordFilter").value = "activities";
    state.events = $("recordFilter").value === "activities" && state.calendarAvailable ? (state.canonicalEvents || state.activities.concat(state.discoveryCandidates, state.sourceCandidates)) : state.leads;
  }
  function renderCoverage() {
    var city = $("cityFilter").value;
    var type = $("typeFilter").value;
    var rows = (state.coverage.data || []).filter(function (row) { return (!city || row.city_name === city) && (!type || row.topic === type); });
    var statuses = { ok: "检索成功，内容仍需核对", failed: "检索失败，保留历史", not_run: "尚未按此类别检索" };
    $("coverageTable").innerHTML = rows.length ? '<table><thead><tr><th>城市</th><th>类别</th><th>新闻线索</th><th>已整理活动</th><th>票务日期候选</th><th>带日期新闻候选</th><th>检索状态</th></tr></thead><tbody>' + rows.map(function (row) {
      return '<tr><td>' + escapeHtml(row.city_name) + '</td><td>' + escapeHtml(row.label) + '</td><td>' + Number(row.news_count || 0) + '</td><td>' + Number(row.activity_count || 0) + '（覆盖待补）</td><td>' + Number(row.source_candidate_count || 0) + '</td><td>' + Number(row.dated_news_candidate_count || 0) + '</td><td>' + escapeHtml(statuses[row.discovery_status] || "状态待核对") + '</td></tr>';
    }).join("") + '</tbody></table>' : '覆盖台账暂不可用，零条不代表该城市没有活动。';
    var gaps = state.backlog.filter(function (row) { return (!city || row.city_name === city || row.impact_destination_city === city) && (!type || row.topic === type); });
    $("coverageBacklog").textContent = gaps.length ? "历史清单待补：" + gaps.map(function (row) { return (row.city_name || "") + " · " + (row.event_name || TYPE_LABELS[row.topic] || "活动来源"); }).join("；") + "。来源和适用范围仍需补查。" : "该筛选暂无单列待补项；覆盖仍需继续核对。";
    var checks = state.sourceChecks.filter(function (row) { return !city || row.city_name === city; });
    if (checks.length) $("coverageBacklog").textContent += " 票务列表读取 " + checks.filter(function (row) { return row.status === "ok"; }).length + "/" + checks.length + " 城成功；只覆盖该平台所列内容。" + (checks.some(function (row) { return row.status !== "ok"; }) ? " 存在读取失败，历史候选已保留，请检查来源时间。" : "");
    var signals = state.sourceMarketSignals.filter(function (row) { return (!city || row.city_name === city || (row.impact_destination_cities || []).indexOf(city) >= 0) && (!type || row.event_type === type); });
    $("sourceMarketDetails").hidden = !signals.length;
    $("sourceMarketSignals").innerHTML = signals.map(function (row) {
      return '<article class="source-market-signal"><strong>' + escapeHtml(row.event_name) + '</strong><p>客源地：' + escapeHtml(row.city_name) + ' · 观察目的地：' + escapeHtml((row.impact_destination_cities || []).join('、')) + ' · 待核验</p><p>学校假期：' + escapeHtml(eventDateLabel(row)) + '</p><p>' + escapeHtml(row.scope_note) + '</p><p>来源检查：' + escapeHtml(formatTime(row.last_evidence_check_at)) + ' · ' + sourceLabel(row) + '</p></article>';
    }).join('');
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

      if (content === "future" && (!upcoming || !inMonitoringWindow(event, today))) return false;
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
      if (Array.isArray(event.sessions) && event.sessions.length) {
        if ((from || to) && !eventRanges(event).some(function (range) { return (!from || range.end >= from) && (!to || range.start <= to); })) return false;
      } else {
        if (from && (!filterStart || filterEnd < from)) return false;
        if (to && (!filterStart || filterStart > to)) return false;
      }
      return true;
    });
  }
  function renderEvents() {
    var events = getFilteredEvents();
    var visibleCount = Math.min(events.length, state.visibleLimit);
    $("listProgress").textContent = events.length > 100 ? "当前筛选共 " + events.length + " 条，已展示 " + visibleCount + " 条；PNG导出包含全部筛选结果。" : "";
    $("showMoreBtn").hidden = visibleCount >= events.length;
    $("resultCount").textContent = events.length + " 条";
    $("viewExplanation").textContent = ($("recordFilter").value === "activities" ? "当前查看活动日历" : "当前查看新闻线索") + "，显示 " + events.length + " 条；新闻线索总计 " + state.leads.length + " 条。" +
      ($("contentFilter").value === "future" ? "当前窗口截至 " + monitoringEnd(beijingToday()) + "，零条不代表该城市没有活动。" : "");
    var selectedCity = $("cityFilter").value;
    var selectedType = $("typeFilter").value;
    var inScope = function (row) { return (!selectedCity || row.city_name === selectedCity) && (!selectedType || row.event_type === selectedType); };
    var scopedLeads = state.leads.filter(inScope);
    var future = function (row) { return isUpcomingDatedEvent(row, beijingToday()) && inMonitoringWindow(row, beijingToday()); };
    $("citySummary").textContent = (selectedCity || "全部城市") + (selectedType ? " · " + TYPE_LABELS[selectedType] : "") + "：已采 " + scopedLeads.length + " 条新闻线索；未来窗口内已整理活动 " + state.activities.filter(inScope).filter(future).length + " 项，票务日期候选 " + state.sourceCandidates.filter(inScope).filter(future).length + " 条，带日期新闻候选 " + state.discoveryCandidates.filter(inScope).filter(future).length + " 条。候选可能重复；规模及住宿影响仍需判断。";
    $("exportPngBtn").disabled = !events.length;
    renderCoverage();
    if (!events.length) {
      $("eventsList").innerHTML = '<div class="empty-state">当前筛选没有符合条件的记录；该城市与类别已采 ' + scopedLeads.length + ' 条新闻线索。可点击“查看当前城市全部线索”继续查找，零条不代表没有活动。</div>';
      return;
    }
    $("eventsList").innerHTML = events.slice(0, visibleCount).map(function (event) {
      var review = event.review_status === "verified" ? '<span class="badge badge-verified">已核验</span>' : event.review_status === "rejected" ? '<span class="badge badge-neutral">已排除</span>' : '<span class="badge badge-pending">待核验</span>';
      var kind = contentKind(event);
      var kindBadge = '<span class="badge badge-neutral">' + escapeHtml(CONTENT_LABELS[kind] || "其他资讯") + '</span>';
      var evidenceBadge = event.record_kind === "source_candidate" ? '<span class="badge badge-pending">票务日期候选 · 待核验</span>' : event.record_kind === "discovery_candidate" ? '<span class="badge badge-pending">新闻候选 · 正文待核对</span>' : event.record_kind === "activity" ? '<span class="badge badge-neutral">来源日期已整理</span>' : '';
      var cityMatch = event.city_match === "event_city_conflict" ? '<span class="badge badge-pending">举办城市不符，需复核</span>' : event.city_match === "text_confirmed" ? '<span class="badge badge-neutral">' + (event.record_kind === "source_candidate" ? '票务卡片列明举办城市' : event.record_kind === "activity" ? '来源正文出现城市名' : '标题/摘要出现城市名') + '</span>' : '<span class="badge badge-neutral">按城市检索命中</span>';
      var sourceCount = (event.sources || []).length;
      var sourcePublish = publicationLabel(event.sources && event.sources[0]);
      var confidence = event.date_confidence === "source_listing" ? "票务列表举办日期，详情与主办方公告待补查" : event.date_confidence === "source_body" ? "来源正文日期，仍待核验" : event.event_date_role === "ticket_sale" ? "开票日期，不是举办日期" : event.event_date_role === "registration" ? "报名日期，不是举办日期" : event.event_date_role === "ambiguous" ? "日期语义待核实" : event.date_confidence === "explicit_year" ? "标题/摘要含年份" : event.date_confidence === "inferred_year" ? "年份推断，需核验" : "未提取到举办日期";
      return '<article class="event-card"><div class="event-main">' +
        '<div class="event-title-row"><span class="event-title">' + escapeHtml(text(event.event_name, "未命名事件")) + '</span>' + review + evidenceBadge + kindBadge +
        '<span class="badge badge-neutral">' + escapeHtml(TYPE_LABELS[event.event_type] || "其他") + '</span></div>' +
        '<div class="event-meta"><span>城市：' + escapeHtml(text(event.city_name)) + '</span><span>活动日期：' + escapeHtml(eventDateLabel(event)) + '</span><span>' + escapeHtml(confidence) + '</span></div>' +
        '<div class="event-description">来源：' + escapeHtml(text(event.sources && event.sources[0] && event.sources[0].publisher, "未知发布方")) +
        ' · 来源发布时间：' + escapeHtml(sourcePublish) + ' · 系统首次发现：' + escapeHtml(formatTime(event.first_seen_at)) +
        ' · 来源数：' + sourceCount + '<br>' + cityMatch +
        (event.venue_name ? '<br>场馆：' + escapeHtml(event.venue_name) : '') +
        (event.scope_note ? '<br>适用范围 / 说明：' + escapeHtml(event.scope_note) : '') +
        (event.sources && event.sources[0] && event.sources[0].authority_note ? '<br>证据说明：' + escapeHtml(event.sources[0].authority_note) : '') +
        (event.last_evidence_check_at ? '<br>来源上次检查：' + escapeHtml(formatTime(event.last_evidence_check_at)) : '') + '</div></div>' +
        '<div class="event-sources">' + sourceLabel(event) + '<span>最近发现：' + escapeHtml(formatTime(event.last_seen_at)) + '</span></div></article>';
    }).join("");
  }
  function publicationLabel(source) {
    source = source || {};
    return source.source_published_at ? formatTime(source.source_published_at) : source.source_published_date ? source.source_published_date + '（仅日期）' : source.source_published_display || '尚无记录';
  }
  function selectedLabel(id, fallback) {
    var node = $(id);
    return node.selectedOptions && node.selectedOptions.length ? node.selectedOptions[0].textContent : (node.value || fallback);
  }
  function buildShareModel() {
    var filters = [$("recordFilter").value === "activities" ? "活动日历" : "新闻线索", selectedLabel("cityFilter", "全部城市"), selectedLabel("contentFilter", "未来活动"),
      selectedLabel("typeFilter", "全部类型"), selectedLabel("reviewFilter", "全部状态")];
    if ($("searchInput").value.trim()) filters.push("搜索：" + $("searchInput").value.trim());
    if ($("dateFrom").value || $("dateTo").value) filters.push("筛选日期：" + ($("dateFrom").value || "不限") + " 至 " + ($("dateTo").value || "不限"));
    var location = new URL(window.location.href);
    return {
      title: ($("cityFilter").value || "全国城市") + ($("recordFilter").value === "activities" ? "活动日历" : "热点线索"),
      filters: filters.join("  /  "),
      updatedAt: ($("recordFilter").value === "activities" ? "日历整理 " + formatTime(state.calendarMeta.generated_at) + "；" : "") + "自动采集截至 " + formatTime(state.meta.last_collection_at || state.health.last_run_at || state.meta.generated_at),
      exportedAt: formatTime(new Date().toISOString()),
      preview: location.hostname !== "wildpig622.github.io" || location.pathname.indexOf("/hotspot-pulse/") !== 0,
      publicUrl: "https://wildpig622.github.io/hotspot-pulse/",
      filename: "hotspot-pulse-" + beijingToday() + "-" + ($("cityFilter").value || "all"),
      dataWarning: !$("feedError").hidden ? "最近刷新失败，图片沿用页面已有快照。" :
        state.health.status === "failed" ? "最近采集失败，图片使用保留快照；内容覆盖待补齐。" : "内容覆盖仍在补齐，图片仅包含当前筛选。",
      rows: getFilteredEvents().map(function (event) {
        var source = event.sources && event.sources[0] || {};
        var host = "";
        try { if (/^https?:\/\//i.test(source.source_url || "")) host = new URL(source.source_url).hostname; } catch (e) {}
        return {
          id: text(event.event_id, "未提供"), title: text(event.event_name, "未命名事件"), city: text(event.city_name),
          type: TYPE_LABELS[event.event_type] || "其他", content: (event.record_kind === "source_candidate" ? "票务日期候选 · 详情与主办方待补查，可能重复 · " : event.record_kind === "discovery_candidate" ? "新闻候选 · 正文待核对，可能重复 · " : event.record_kind === "activity" ? "来源日期已整理 · " : "") + (CONTENT_LABELS[contentKind(event)] || "其他资讯") + (event.scope_note ? " · " + event.scope_note : "") + (source.authority_note ? " · 证据说明：" + source.authority_note : ""),
          date: eventDateLabel(event), review: event.review_status === "verified" ? "已核验" : event.review_status === "rejected" ? "已排除" : "待核验",
          source: text(source.publisher, "未知发布方") + (host ? " · " + host : ""), publishedAt: publicationLabel(source) + (event.last_evidence_check_at ? "；来源检查 " + formatTime(event.last_evidence_check_at) : "")
        };
      })
    };
  }
  function exportMessage(message) {
    $("exportMessage").textContent = message;
    $("exportMessage").hidden = !message;
  }
  function closeShare() {
    shareRevision += 1;
    if (shareSession && shareSession.url) URL.revokeObjectURL(shareSession.url);
    shareSession = null;
    $("sharePreview").removeAttribute("src");
    $("exportPngBtn").focus();
  }
  async function showSharePage(index) {
    var session = shareSession;
    if (!session || index < 0 || index >= session.layout.pages.length) return;
    var revision = ++shareRevision;
    session.index = index;
    $("downloadPngBtn").disabled = $("copyPngBtn").disabled = true;
    $("sharePrevBtn").disabled = $("shareNextBtn").disabled = true;
    $("sharePageLabel").textContent = "正在生成图片…";
    try {
      var canvas = document.createElement("canvas");
      window.HotspotShareImage.render(canvas, session.model, session.layout, index);
      var blob = await window.HotspotShareImage.toBlob(canvas);
      if (shareSession !== session || revision !== shareRevision) return;
      var url = URL.createObjectURL(blob);
      if (session.url) URL.revokeObjectURL(session.url);
      session.blob = blob; session.url = url;
      $("sharePreview").src = url;
      $("sharePreview").alt = session.model.title + "，第" + (index + 1) + "张，共" + session.layout.pages.length + "张";
      $("sharePageLabel").textContent = (index + 1) + " / " + session.layout.pages.length + " 张";
      $("downloadPngBtn").disabled = $("copyPngBtn").disabled = false;
      $("sharePrevBtn").disabled = index === 0;
      $("shareNextBtn").disabled = index === session.layout.pages.length - 1;
      $("shareStatus").textContent = session.layout.pages.length > 1
        ? "共 " + session.model.rows.length + " 条，已完整分成 " + session.layout.pages.length + " 张；可逐张保存，当前筛选没有遗漏。"
        : "共 " + session.model.rows.length + " 条，已完整放入这张图片。可保存 PNG，或复制图片后粘贴到聊天。";
    } catch (error) {
      if (shareSession === session && revision === shareRevision) {
        $("sharePageLabel").textContent = "生成失败";
        $("shareStatus").textContent = error.message || "图片生成失败，请重试。";
      }
    }
  }
  async function openShare() {
    exportMessage("");
    if (!getFilteredEvents().length) { exportMessage("当前没有可导出的内容，请调整筛选。"); return; }
    try {
      if (!window.HotspotShareImage) throw new Error("图片导出暂不可用，请刷新页面后重试。");
      if (typeof $("shareDialog").showModal !== "function") throw new Error("浏览器暂不支持图片预览，请更新浏览器或使用页面截图。");
      var model = buildShareModel();
      var canvas = document.createElement("canvas");
      var context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法生成图片，请使用页面截图。");
      var layout = window.HotspotShareImage.plan(context, model);
      shareSession = { model: model, layout: layout, index: 0, blob: null, url: null };
      $("copyPngBtn").hidden = !(navigator.clipboard && navigator.clipboard.write && window.ClipboardItem);
      $("shareDialog").showModal();
      await showSharePage(0);
    } catch (error) {
      exportMessage(error.message || "图片生成失败，请重试。");
    }
  }
  function applyFilters() { state.visibleLimit = 100; selectRecordLayer(); renderMetrics(); renderEvents(); }
  function bindEvents() {
    $("showCityLeadsBtn").addEventListener("click", function () {
      $("recordFilter").value = "leads";
      $("contentFilter").value = "all";
      ["searchInput", "reviewFilter", "dateFrom", "dateTo"].forEach(function (id) { $(id).value = ""; });
      applyFilters();
    });
    $("showMoreBtn").addEventListener("click", function () { state.visibleLimit += 100; renderEvents(); });
    $("showLeadCandidatesBtn").addEventListener("click", function () {
      $("recordFilter").value = "leads";
      $("contentFilter").value = "future";
      applyFilters();
    });
    ["recordFilter", "searchInput", "cityFilter", "typeFilter", "reviewFilter", "contentFilter", "dateFrom", "dateTo"].forEach(function (id) {
      $(id).addEventListener("input", applyFilters);
      $(id).addEventListener("change", applyFilters);
    });
    $("clearBtn").addEventListener("click", function () {
      state.visibleLimit = 100;
      ["searchInput", "cityFilter", "typeFilter", "reviewFilter", "dateFrom", "dateTo"].forEach(function (id) { $(id).value = ""; });
      $("contentFilter").value = "future";
      renderEvents();
    });
    $("refreshBtn").addEventListener("click", loadData);
    $("exportPngBtn").addEventListener("click", openShare);
    $("closeShareBtn").addEventListener("click", function () { $("shareDialog").close(); });
    $("shareDialog").addEventListener("close", closeShare);
    $("sharePrevBtn").addEventListener("click", function () { return showSharePage(shareSession.index - 1); });
    $("shareNextBtn").addEventListener("click", function () { return showSharePage(shareSession.index + 1); });
    $("downloadPngBtn").addEventListener("click", function () {
      if (!shareSession || !shareSession.url || $("downloadPngBtn").disabled) return;
      var link = document.createElement("a");
      link.href = shareSession.url;
      link.download = shareSession.model.filename + "-" + String(shareSession.index + 1).padStart(2, "0") + ".png";
      document.body.appendChild(link); link.click(); link.remove();
      $("shareStatus").textContent = "已开始保存 PNG。保存后可直接作为图片发送给同事。";
    });
    $("copyPngBtn").addEventListener("click", function () {
      if (!shareSession || !shareSession.blob || $("copyPngBtn").disabled) return;
      return navigator.clipboard.write([new window.ClipboardItem({ "image/png": shareSession.blob })]).then(function () {
        $("shareStatus").textContent = "图片已复制，可直接粘贴到聊天中。";
      }).catch(function () {
        $("shareStatus").textContent = "浏览器未允许复制图片，请使用保存 PNG 后发送。";
      });
    });
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
    Promise.allSettled([fetchJson(API_URL), fetchJson(HEALTH_URL), fetchJson(CITIES_URL), fetchJson(ACTIVITIES_URL), fetchJson(COVERAGE_URL), fetchJson(EVENT_FEED_URL)]).then(function (results) {
      if (results[0].status === "fulfilled") {
        state.meta = results[0].value.meta || {};
        state.leads = Array.isArray(results[0].value.data) ? results[0].value.data.map(function (event) { return legacyDateView(event, beijingToday()); }) : [];
      } else {
        $("feedError").hidden = false;
        $("feedError").textContent = "事件 JSON 读取失败：" + results[0].reason.message + "。请检查 Pages 是否已启用，以及 API 文件是否发布。";
      }
      if (results[1].status === "fulfilled") state.health = results[1].value || {};
      if (results[2].status === "fulfilled") state.cities = results[2].value.data || [];
      state.calendarAvailable = results[3].status === "fulfilled" && Array.isArray(results[3].value.data);
      state.activities = state.calendarAvailable ? results[3].value.data : [];
      state.discoveryCandidates = state.calendarAvailable ? (results[3].value.discovery_candidates || []) : [];
      state.sourceCandidates = state.calendarAvailable ? (results[3].value.source_candidates || []) : [];
      state.sourceChecks = state.calendarAvailable ? (results[3].value.source_checks || []) : [];
      state.calendarMeta = state.calendarAvailable ? results[3].value.meta || {} : {};
      state.backlog = state.calendarAvailable ? results[3].value.backlog || [] : [];
      state.sourceMarketSignals = state.calendarAvailable ? results[3].value.source_market_signals || [] : [];
      state.coverage = results[4].status === "fulfilled" ? results[4].value : {};
      state.canonicalEvents = null;
      if (results[5].status === "fulfilled" && results[5].value.meta && results[5].value.meta.schema_version === "2.0" && Array.isArray(results[5].value.data)) {
        state.canonicalEvents = results[5].value.data;
        state.calendarAvailable = true;
        var feedMeta = results[5].value.meta;
        var stale = feedMeta.is_stale || Date.now() > Date.parse(feedMeta.expires_at);
        if (stale || feedMeta.using_cached_data) {
          $("feedError").hidden = false;
          $("feedError").textContent = (stale ? "活动数据已过期。" : "本轮更新未通过，正在展示保留数据。") + "上次成功采集：" + formatTime(feedMeta.last_successful_collection_at) + "；每天北京时间08:00、16:00更新。";
        }
      }
      selectRecordLayer();
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
