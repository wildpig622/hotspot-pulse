# Hotspot Pulse

面向酒店收益经营看板的公开活动事件发现服务。目标是每日发现各经营城市的演唱会、展会、体育赛事、节庆等候选事件，保留来源与发现时间，通过静态 JSON API 供看板读取。

## 当前版本边界

- 采集入口：Google News RSS 搜索结果。它是公开信息发现层，不等于活动主办方的官方核验，也不是对所有票务/场馆网站的完整爬取。
- 自动发现的事件统一标记为 pending / unknown；不会自动标记 verified，不得仅凭本数据直接做价格决策。
- 活动举办日期与开票/售票、报名日期分字段记录；文章提及的月份或月份范围不写入 start_at/end_at，避免被误读为单场举办日期。
- 内容性质单独分类：event_announcement、uncertain、ticketing_notice、registration_notice、schedule_roundup、guide、past_report。攻略、排期汇总、开票/报名资讯不会被默认展示为未来活动。
- 未标年份的日期会标记 inferred_year，必须人工核对；日期语义不明确时标记 ambiguous，不自动核验。
- 同一候选的多来源会合并；来源链接、发布/发现时间与最近出现时间会保留。
- GitHub Actions 每天北京时间 06:15 运行；采集成功后提交 JSON 快照，GitHub Pages 工作流负责发布。
- 不使用内部 PMS、经营数据或私人凭据。公开仓库中的数据与 API 均可被互联网访问。

## API

启用 GitHub Pages 后，默认 API 根路径为：

https://wildpig622.github.io/hotspot-pulse/api/v1/

- hotspots.json：当前候选事件快照，包含 meta 与 data；新增 content_kind、event_date_role、ticket_sale_at、registration_at、reference_period_start/end 等可选字段，保持 v1 API 向后兼容。
- cities.json：采集城市列表及本次候选数量。
- health.json：最近一次采集的健康状态、成功/失败源数量和更新时间。

这是静态 JSON API，不提供服务器端查询参数。消费者下载 hotspots.json 后按 city_name、event_type、start_at、review_status 与 content_kind 本地过滤。未来活动应只消费有具体举办日期、尚未结束且内容性质为 event_announcement/uncertain 的记录。看板接入时应默认只消费人工核验后的事件；当前采集器不会自动产生 verified 记录。

## 首次启用

1. 在仓库 Settings → Pages → Build and deployment 中选择 GitHub Actions。
2. 打开 Actions，确认 Daily hotspot collection 与 Deploy static site 工作流可运行。
3. 手动运行 Daily hotspot collection 完成首轮采集；后续每天北京时间 06:15 自动运行。
4. 等待 Deploy static site 成功后，检查上面的 Pages 地址与 API 地址。

## 本地运行

需要 Python 3.11+，无需第三方依赖。

运行测试：

    python -m unittest discover -s tests -v

执行一次真实采集：

    python scripts/collect.py

真实采集需要访问 Google News RSS。若所有 RSS 源都失败，程序会保留上一份事件快照、更新 health.json 并以失败退出；不会用空列表覆盖历史数据。

## 数据质量与后续扩展

第一阶段验证自动发现、去重、来源追溯和每日发布。下一阶段应增加可合法访问的官方活动日历/RSS/票务公告来源，并建立人工核验入口。只有经权威来源核验的事件，才应被看板作为已确认热点使用。
