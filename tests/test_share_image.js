"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const image = require("../site/share-image.js");

function context() {
  return {font: "", measureText(text) {
    const size = Number(this.font.match(/(\d+)px/)[1]);
    return {width: Array.from(text).length * size};
  }};
}
function model(count) {
  return {title: "全国城市热点线索", filters: "全部城市 / 未来活动 / 全部状态", updatedAt: "2026/10/29 11:08:58",
    exportedAt: "2026/10/30 12:00:00", preview: true, publicUrl: "https://wildpig622.github.io/hotspot-pulse/",
    rows: Array.from({length: count}, (_, index) => ({id: "evt_" + index, title: "昆明国际车展将于11月5日至9日举办🙂".repeat(3),
      city: "昆明市", type: "展会", content: "活动公告", date: "2026-11-05 至 2026-11-09 · 年份推断",
      review: "待核验", source: "公开新闻来源 · news.google.com", publishedAt: "2026/10/18 15:00:00"}))};
}

test("large exports paginate every selected record exactly once within safe canvas dimensions", () => {
  const input = model(529);
  const original = JSON.stringify(input);
  const layout = image.plan(context(), input);
  assert.ok(layout.pages.length > 1);
  assert.deepEqual(layout.pages.flatMap(page => page.cards.map(card => card.id)), input.rows.map(row => row.id));
  assert.ok(layout.pages.every(page => page.bodyHeight + layout.startY + layout.footerHeight <= image.maxHeight));
  assert.ok(layout.pages.every(page => page.cards.length <= 24));
  assert.equal(JSON.stringify(input), original, "export cannot mutate source records or review state");
});

test("long Chinese titles and emoji wrap without truncation and retain date and pending labels", () => {
  const input = model(1);
  const layout = image.plan(context(), input);
  const text = layout.pages[0].cards[0].lines.map(line => line.text || "").join("");
  assert.ok(text.includes(input.rows[0].title));
  assert.ok(text.includes("2026-11-05 至 2026-11-09"));
  assert.ok(text.includes("待核验"));
  assert.ok(text.includes("news.google.com"));
  assert.match(layout.warning.map(line => line.text).join(""), /预览版图片/);
});

test("empty results and an oversized individual record fail explicitly instead of exporting an incomplete image", () => {
  assert.throws(() => image.plan(context(), model(0)), /没有可导出/);
  const input = model(1);
  input.rows[0].title = "长".repeat(10000);
  assert.throws(() => image.plan(context(), input), /内容过长/);
});

test("PNG encoding requests image/png and reports a failed browser encoder", async () => {
  const blob = {type: "image/png"};
  assert.equal(await image.toBlob({toBlob(callback, type) {assert.equal(type, "image/png"); callback(blob);}}), blob);
  await assert.rejects(image.toBlob({toBlob(callback) {callback(null);}}), /图片生成失败/);
});
