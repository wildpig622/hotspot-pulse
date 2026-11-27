(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var feed = 'focus', cache = {}, legacy = false;
  var labels = { observed: '来源记录', announced: '官宣', ticket_on_sale: '开票', sold_out: '售罄', extra_show: '加场', postponed: '延期', cancelled: '取消' };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function source(url) { try { var u = new URL(url); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; } catch (_) { return ''; } }
  function today() { return new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' }); }
  function time(s) { return s ? new Date(s).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hourCycle: 'h23' }) : '未知'; }
  function visible(row, city, days, kind) {
    if (city && row.city_name !== city) return false;
    if (kind === 'changes' || kind === 'intelligence') return true;
    var start = row.start_at, end = row.end_at || start, limit = new Date(today() + 'T00:00:00+08:00');
    limit.setUTCDate(limit.getUTCDate() + Number(days));
    return !!start && end >= today() && start <= limit.toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' });
  }
  function render() {
    var payload = cache[feed]; if (!payload) return;
    var rows = payload.data.filter(function (r) { return visible(r, $('businessCity').value, $('businessDays').value, feed); });
    $('businessCount').textContent = rows.length + ' 条';
    var meta = payload.meta, stamp = meta.last_observed_at;
    var stale = !stamp || Date.now() - Date.parse(stamp) > 48 * 3600000;
    $('businessFreshness').textContent = (stale ? '数据已过期，需复查。' : '') + (!meta.collection_ok ? '本轮更新失败，保留上次有效数据。' : '') + ' 最近观察：' + time(stamp) + '；页面数据生成：' + time(meta.generated_at) + '（北京时间）。情报与变化按观察时间保留。';
    $('businessGaps').textContent = meta.gaps.join('；');
    $('updatedAt').textContent = '最近观察 ' + time(stamp);
    $('healthLabel').textContent = stale ? '数据待刷新' : '发布候选 · 待核验';
    $('healthDetail').textContent = '人工触发搜索导入；自动官方采集仍需上线决定';
    $('businessList').innerHTML = rows.map(function (r) {
      var url = source(r.source_url), review = r.review_status === 'verified' ? '已核验' : r.review_status === 'rejected' ? '已拒绝' : '待核验候选';
      var scope = r.city_name || ((r.scope_level === 'national' ? '全国公告' : '适用地区待确认') + ' · 不代表本地考点');
      var dates = r.date_review_required ? '日期冲突，待复核' : r.start_at ? r.start_at + (r.end_at && r.end_at !== r.start_at ? ' — ' + r.end_at : '') : '未定档 / 持续信号';
      if (Date.now() - Date.parse(r.observed_at || r.last_observed_at) > 48 * 3600000) dates += ' · 来源超过48小时未复查，记录继续保留';
      return '<article class="business-event"><div class="business-event-top"><span class="result-count">' + esc(review) + '</span><span>' + esc(scope) + '</span></div><h3>' + esc(r.event_name) + '</h3><p>' + esc(dates) + ' · ' + esc(r.venue_name || '场地未确认') + '</p><p>' + esc(r.change_kind === 'new_record' ? '新增线索' : labels[r.observation_type] || '观察') + ' · 观察时间 ' + esc(time(r.observed_at || r.last_observed_at)) + (r.first_seen_at ? ' · 首次发现 ' + esc(time(r.first_seen_at)) : '') + '</p><p class="coverage-summary">' + esc((r.short_evidence || []).join(' / ')) + '</p>' + (url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">查看来源证据 ↗</a>' : '') + '<small>住宿增量与实际规模未知；状态观察仍需核验</small></article>';
    }).join('') || '<div class="empty-state">此视图暂无记录。覆盖不完整，不代表没有事件；可切换城市、365天或市场情报。</div>';
  }
  async function load() {
    if (!cache[feed]) {
      try {
        var response = await fetch('./api/business/' + feed + '.json', { cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        var payload = await response.json();
        if (!payload.meta || payload.meta.schema_version !== 'business-1' || !Array.isArray(payload.data)) throw new Error('数据格式不兼容');
        cache[feed] = payload;
      } catch (error) {
        $('businessFreshness').textContent = '业务数据尚不可用：' + error.message + '。可展开原有日历；不可据此认定没有事件。';
        return;
      }
    }
    render();
  }
  $('businessCity').addEventListener('change', render);
  $('businessDays').addEventListener('change', render);
  $('businessTabs').addEventListener('click', function (event) {
    var button = event.target.closest('[data-feed]'); if (!button) return;
    feed = button.dataset.feed;
    $('businessTabs').querySelectorAll('button').forEach(function (b) { b.className = 'button ' + (b === button ? 'button-primary' : 'button-quiet'); });
    load();
  });
  $('refreshBtn').addEventListener('click', function () { if (!legacy) { cache = {}; load(); } });
  $('openLegacy').addEventListener('click', async function () {
    $('legacyContent').hidden = false;
    if (legacy) return;
    legacy = true;
    try {
      for (var id of ['legacyShareScript', 'legacyAppScript']) {
        await new Promise(function (resolve, reject) { var s = document.createElement('script'); s.src = $(id).src; s.onload = resolve; s.onerror = reject; document.body.appendChild(s); });
      }
      $('openLegacy').textContent = '已展开完整数据';
    } catch (_) { legacy = false; $('openLegacy').textContent = '读取失败，点击重试'; }
  });
  var city = new URLSearchParams(location.search).get('city');
  if (['西安市', '济南市', '天津市'].includes(city)) $('businessCity').value = city;
  load();
}());
