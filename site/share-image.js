(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HotspotShareImage = api;
}(typeof window === "undefined" ? this : window, function () {
  "use strict";
  var WIDTH = 1080;
  var MAX_HEIGHT = 7200;
  var FONT = '"Microsoft YaHei", "PingFang SC", sans-serif';
  var COLORS = { ink: "#17233c", muted: "#65758d", blue: "#245ce8", amber: "#975a08", green: "#147d57" };

  function linesFor(ctx, value, width, size, bold, color) {
    ctx.font = (bold ? "700 " : "400 ") + size + "px " + FONT;
    var output = [];
    String(value || "").split(/\r?\n/).forEach(function (paragraph) {
      var current = "";
      Array.from(paragraph).forEach(function (character) {
        if (current && ctx.measureText(current + character).width > width) {
          output.push(current); current = "";
        }
        current += character;
      });
      output.push(current);
    });
    return output.map(function (text) { return { text: text, size: size, bold: !!bold, color: color, height: Math.ceil(size * 1.55) }; });
  }
  function heightOf(lines) { return lines.reduce(function (sum, line) { return sum + line.height; }, 0); }
  function plan(ctx, model) {
    if (!model.rows.length) throw new Error("当前没有可导出的内容，请调整筛选。");
    var header = [];
    header = header.concat(linesFor(ctx, model.title, 952, 42, true, "#ffffff"));
    header = header.concat(linesFor(ctx, model.filters, 952, 22, false, "#dce7ff"));
    header = header.concat(linesFor(ctx, "数据更新：" + model.updatedAt, 952, 20, false, "#dce7ff"));
    header = header.concat(linesFor(ctx, "图片生成：" + model.exportedAt + "（北京时间）", 952, 20, false, "#dce7ff"));
    var warning = linesFor(ctx, "候选线索不等于已确认活动；同一活动可能有多篇报道。待核验内容仅供讨论。", 928, 22, false, COLORS.amber);
    if (model.preview) warning = warning.concat(linesFor(ctx, "预览版图片 · 线上页面内容可能不同", 928, 21, true, COLORS.amber));
    if (model.dataWarning) warning = warning.concat(linesFor(ctx, model.dataWarning, 928, 21, true, COLORS.amber));
    var headerHeight = 92 + heightOf(header);
    var warningHeight = 32 + heightOf(warning);
    var startY = headerHeight + 24 + warningHeight + 28;
    var footerHeight = 126;
    var capacity = MAX_HEIGHT - startY - footerHeight;
    if (capacity < 300) throw new Error("筛选文字过长，请缩短搜索内容后导出。");
    var pages = [];
    var current = { cards: [], bodyHeight: 0 };
    model.rows.forEach(function (row) {
      var lines = [];
      lines = lines.concat(linesFor(ctx, row.title, 928, 29, true, COLORS.ink));
      lines.push({ text: "", height: 8 });
      lines = lines.concat(linesFor(ctx, row.city + "  ·  " + row.type + "  ·  " + row.content, 928, 21, false, COLORS.muted));
      lines = lines.concat(linesFor(ctx, "活动日期：" + row.date, 928, 23, false, COLORS.blue));
      lines = lines.concat(linesFor(ctx, "核验状态：" + row.review, 928, 21, true, row.review === "已核验" ? COLORS.green : COLORS.amber));
      lines = lines.concat(linesFor(ctx, "来源：" + row.source, 928, 20, false, COLORS.muted));
      lines = lines.concat(linesFor(ctx, "来源发布：" + row.publishedAt + "  ·  线索编号：" + row.id, 928, 18, false, COLORS.muted));
      var card = { lines: lines, height: 40 + heightOf(lines), id: row.id };
      if (card.height + 16 > capacity) throw new Error("有一条内容过长，请缩小筛选范围或单独查看来源。");
      if (current.cards.length && (current.bodyHeight + card.height + 16 > capacity || current.cards.length >= 24)) {
        pages.push(current); current = { cards: [], bodyHeight: 0 };
      }
      current.cards.push(card);
      current.bodyHeight += card.height + 16;
    });
    if (current.cards.length) pages.push(current);
    return { width: WIDTH, header: header, headerHeight: headerHeight, warning: warning, warningHeight: warningHeight,
      startY: startY, footerHeight: footerHeight, pages: pages };
  }
  function paintLines(ctx, lines, x, y) {
    lines.forEach(function (line) {
      if (line.text) {
        ctx.fillStyle = line.color;
        ctx.font = (line.bold ? "700 " : "400 ") + line.size + "px " + FONT;
        ctx.fillText(line.text, x, y);
      }
      y += line.height;
    });
    return y;
  }
  function panel(ctx, x, y, width, height, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x + 16, y); ctx.lineTo(x + width - 16, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + 16);
    ctx.lineTo(x + width, y + height - 16); ctx.quadraticCurveTo(x + width, y + height, x + width - 16, y + height);
    ctx.lineTo(x + 16, y + height); ctx.quadraticCurveTo(x, y + height, x, y + height - 16);
    ctx.lineTo(x, y + 16); ctx.quadraticCurveTo(x, y, x + 16, y); ctx.fill();
  }
  function render(canvas, model, layout, pageIndex) {
    var page = layout.pages[pageIndex];
    if (!page) throw new Error("图片页码无效。");
    canvas.width = layout.width;
    canvas.height = layout.startY + page.bodyHeight + layout.footerHeight;
    var ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("浏览器无法生成图片，请使用页面截图。");
    ctx.textBaseline = "top";
    ctx.fillStyle = "#f3f6fc"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    var gradient = ctx.createLinearGradient(0, 0, WIDTH, layout.headerHeight);
    gradient.addColorStop(0, "#173c98"); gradient.addColorStop(1, "#2868ed");
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, WIDTH, layout.headerHeight);
    ctx.fillStyle = "#dce7ff"; ctx.font = "700 20px " + FONT;
    ctx.fillText("HOTSPOT PULSE  /  城市热点分享", 64, 30);
    paintLines(ctx, layout.header, 64, 70);
    panel(ctx, 52, layout.headerHeight + 24, 976, layout.warningHeight, "#fff5df");
    paintLines(ctx, layout.warning, 76, layout.headerHeight + 40);
    var y = layout.startY;
    page.cards.forEach(function (card) {
      panel(ctx, 52, y, 976, card.height, "#ffffff");
      paintLines(ctx, card.lines, 76, y + 20);
      y += card.height + 16;
    });
    ctx.fillStyle = COLORS.ink; ctx.font = "700 22px " + FONT;
    ctx.fillText("当前筛选 " + model.rows.length + " 条  ·  第 " + (pageIndex + 1) + " / " + layout.pages.length + " 张  ·  本张 " + page.cards.length + " 条", 64, y + 12);
    ctx.fillStyle = COLORS.muted; ctx.font = "400 20px " + FONT;
    ctx.fillText("网页入口：" + model.publicUrl.replace(/^https:\/\//, ""), 64, y + 50);
    ctx.font = "400 18px " + FONT;
    ctx.fillText("图片为当前筛选快照，具体日期与状态请回到来源核对。", 64, y + 82);
    return canvas;
  }
  function toBlob(canvas) {
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (blob) resolve(blob); else reject(new Error("图片生成失败，请重试或使用页面截图。"));
      }, "image/png");
    });
  }
  return { plan: plan, render: render, toBlob: toBlob, width: WIDTH, maxHeight: MAX_HEIGHT };
}));
