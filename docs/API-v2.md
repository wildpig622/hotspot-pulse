# 活动数据服务合同 v2 / schema 2.0

公开地址：<https://wildpig622.github.io/hotspot-pulse/api/v2/events.json>。这是静态快照，URL查询参数不执行服务端筛选。不要把 `v1/hotspots.json` 的新闻行直接作为活动导入。

## 身份、日期、证据

`data[]` 的 `event_id` / `canonical_id` 为稳定 `hp_` 身份；`record_id` 是首选来源记录，`member_record_ids` 保留全部关联记录。仅明确的来源编号、相同名称/场馆/城市/场次或 `config/event-links.json` 的逐组身份依据允许合并。相似标题、同城同日、共享列表网址都不能单独证明同一活动。未明确关联的重复仍可能存在，覆盖为partial。

`sessions[]` 保存真实不连续场次，每项含 `occurrence_id,start_at,end_at`，日期为举办地日历日期YYYY-MM-DD、首尾包含。不要把最早至最晚日期填成连续活动。单场改期沿用场次ID并增加revision，多场新增不会重编号既有场次；多场删除/改期无法明确对应时需人工绑定，不自动推断取消。`date_changes` 保留来源明确日期变化。

`review_status` 仍为pending/verified/rejected。机器发现、分组合并、重新读取来源都不产生人工verified。原始来源、检查时间、来源类型和证据说明在 `sources`；票务列表、新闻摘要与正文证据必须区分。明确取消/延期进入 `event_status`；未读取到、下架或网络失败不等于取消。

`availability` 为candidate/cancelled/postponed/needs_date_review/expired/not_recently_observed/rejected。默认未来视图排除后六类；保留记录供消费端追溯、修订及撤下旧展示。日期冲突不静默选择某一来源。

## 更新、失败和增量

每天北京时间08:00、16:00由GitHub Actions运行（UTC 00:00/08:00），平台可能排队延迟。`meta.last_successful_collection_at` 才是真实成功采集时间，`generated_at` 只是构建时间。`expires_at` 是成功采集后18小时，读取时必须重新比较当前时间；不能只信构建时的 `is_stale`。失败保留快照，`using_cached_data=true`，公开health记录失败原因，运行以失败状态提示维护者。失败不能推进消费端导入游标。

`changes.json` 是最多10000条变化日志，含严格递增cursor、event_id、revision、change_type、changed_fields、observed_at。按 `cursor > 已保存游标` 读取；低于 `meta.cursor_floor` 或高于最新cursor须重新拉全量。created/updated后从events读取当前完整对象；merged含canonical_id，消费端需迁移原绑定，无法迁移则停在待处理队列。`state.json` 是服务身份状态，不是经营导入数据，不供客户端修改。

## 前端读取

```js
import {loadSnapshot, selectEvents, loadChanges} from './hotspot-client.mjs';
const snapshot = await loadSnapshot(); // 默认拒绝过期和本轮失败保留快照
const candidates = selectEvents(snapshot, {cityName:'重庆市', from:'2026-11-04', to:'2027-02-02'});
// 经营展示额外使用 reviewStatus:'verified'；当前发现层可能返回0项。
const delta = await loadChanges({since: snapshot.meta.cursor});
```

## 现有导入器适配

`integrations/import_batch.py:build_import_batch` 生成 `{p_batch:{batch,events}}`，消费环境另传导入密钥；公共仓库不包含目标经营系统信息或凭据。每次以完整快照和消费端已有事件检查，输出批次全部pending。原文无日期、推断年份、来源失联、日期冲突、已拒绝/过期、已有verified身份、未绑定改期都不直接写入。

稳定活动及场次身份写入 `seed_record_id`、`series_key` 和首个来源evidence_summary。首个source_url为稳定公开场次URI；其余证据URL加独立场次片段，未经改动的原URL保存在evidence_summary。原因是既有导入器会索引所有source_url：共享城市列表不能成为不同活动的相同身份。链接仍打开原证据页。

消费者应保存每批结果中的 `seed_record_id → 本地event_id`，下次作为bound_occurrences传入；已有绑定的改期沿用场次URI，不使用new_session。首次明确新场次使用new_session，防止加场被当成改期。批次成功且逐条无错误后再推进游标；响应丢失须按同一身份重放，禁止把HTTP200当作逐条成功。

先只读联调、再小批量pending导入。经营页面保持原有人工verified过滤，不在本服务中增加门店影响评分、定价或内部经营数据。取消/延期更新已审核事件前同样需消费端既有审核流程；本适配器不会覆盖既有verified身份。

## 可复现校验

```text
python -m unittest discover -s tests -q
node --test tests/test_site.js tests/test_share_image.js tests/test_client.mjs
python -m scripts.event_feed
python -m scripts.validate_event_feed
```

本合同检查结构、身份保留和已知排除规则，不代表全国活动完整，也不代表酒店住宿需求已确认。


## 2026-11-09：按完整自然月规划

默认窗口改为本月剩余时间加未来3个完整自然月，首尾包含。例如北京时间2026-11-09查询，应覆盖到2027-02-28，而不是90天后的2027-02-07。`meta.monitoring_window`给出start_at/end_at/policy；`monitoring_complete_months=3`优先于旧rolling-days设置，兼容字段monitoring_horizon_days输出本次实际跨度。

RSS每个城市/主题为未来各月单独查询、各有最多50条配额，避免近期新闻挤掉2月；28城×6类×5路线=840次查询。检索、票务日期解析、官方结构化日期、日历统计和网站窗口共用同一边界。糖酒会/春糖/秋糖/广交会加入明确检索与会展分类。明确未来日期超出默认窗口的已有记录继续保留，不把布展、开票或招商日期当作正式展会日期。

`monthly_coverage`按未来3个月报告日期候选数和城市数。no_dated_candidates表示该月尚未采集到安全日期候选，需要补查，不代表没有活动；partial也不代表完整覆盖或已审核。

消费日历切换城市/月份时，应按所选完整月的首尾查询，而不是固定今天+90天后再前端裁剪。查询日期与事件sessions任一场次有交集即匹配。原有verified业务过滤继续保留，待核验候选若用于规划参考，必须另作明确标识，不能静默当成已确认需求。
