# Static JSON API v1

公开根地址：<https://wildpig622.github.io/hotspot-pulse/api/v1/>。v1保持来源分层兼容，schema 1.5增加官方结构化候选与检查记录。新接入使用 [v2合同](API-v2.md)，避免直接将新闻当作活动。所有筛选在客户端执行。

## hotspots.json：新闻线索

`data` 保留原始候选报道，使用稳定的 `event_id`。同一活动可以对应多条新闻；`activity_id` 仅在存在明确整理的关联时提供，不凭标题相似自动合并。

`meta.generated_at` 是文件构建时间，`meta.normalized_at` 是离线清洗时间，`meta.last_collection_at` 才是最近一次真实采集时间。离线清洗不能更新采集时间。`candidate_count` 是新闻条数，不能当作独立活动数。`successful_feeds` / `failed_feeds` 对应当次查询；新采集器一城一类别一个查询，28城×6类共168个，旧28个组合查询不会冒充新查询已执行。

记录包括名称、类型、城市、城市匹配依据、`content_kind`、`event_date_role`、`start_at/end_at`、日期置信度、开票/报名日期、月份参考期、来源及发现时间。无可靠举办日期时保持空值。

## activities.json：按身份整理的活动日历

`data` 使用稳定的 `act_…` ID，与新闻 ID 分开。包括城市、名称、类型、场馆、`sessions`、适用范围 `scope_note`、明确关联的 `related_lead_ids`、来源及 `last_evidence_check_at`。目前由显式登记的来源正文日期和历史证据构建，不能宣称已经覆盖所有活动。

`sessions` 是公告场次或日期区间。非连续场次应逐项判断日期交集，不能把总的 `start_at/end_at` 边界当作连续演出。学生假期的学校放假日期放在 `sessions`；含周末的出行观察窗口另存 `travel_windows`，不得替换学校放假日期。分区、分批次及学段限制写在 `scope_note`。

每个来源保留 URL、发布方、来源类型、访问结果、发布时间及 `checked_at`。仅有发布日期时用 `source_published_date`，不伪造零点。历史来源重新构建不等于重新访问，其旧检查时间保留。`backlog` 列出缺少当前正文或权威来源的历史线索，不给这些线索编造活动日期。

`meta.activity_count` 与 `meta.future_activity_count` 分别是整理总数和构建时未来90天内的数量，后者会随日期变化；客户端应使用当前北京时间重新计算。

`source_market_signals` 单独存放经营城市以外的客源地假期，包含真实客源城市及观察目的地 `impact_destination_cities`。这些记录不进入本地活动数量，也不能证明住宿需求增量。`backlog_resolutions` 仅记录来源补查处置，不是事实核验通过或 verified 升级。官方账号、媒体转述等限制保存在来源 `authority_note`，有的来源只显示月日，使用 `source_published_display` 原样保留，不编造年份。

## coverage.json：覆盖缺口

`data` 为28城×6类的168格，包含新闻数量、已整理活动数量、上次证据检查时间和检索状态。`not_run`、失败和成功必须区分。RSS检索成功、空结果或人工补录都不代表该格已完整覆盖；目前总体 `coverage_status=partial`。

## cities.json / health.json

`cities.json` 返回28个配置城市及各自新闻、活动数量。`health.json` 描述最近一次真实采集，离线整理不会改成健康或刷新运行时间。真实采集全部失败时保留已有新闻、城市、活动和覆盖快照，仅报告采集失败。

## 核验与执行

自动发现及登记输出为 `review_status=pending`；明确取消/延期证据可更新 `event_status`；没有自动升级 verified 的路径。已有人工 verified 记录会保留。当前没有核验写入界面，也不宣称未确认活动一定举办或带来住宿增量。

按用户授权，每天北京时间08:00、16:00采集，通过质量检查后自动发布。普通代码推送不触发采集或发布；独立手动入口保留。网页刷新只读取已有JSON。

采集成功后、提交快照之前运行 `check_snapshot_quality.py --require-full-scope`，检查完整168条线路、全部新闻/活动/客源地记录、日期、身份、来源和计数。部署还要求 `--max-age-hours 24`，整理时间不能代替真实采集时间。该检查验证数据结构和已定义的排除规则，不宣称全网事实完备。
