# Hotspot Pulse

面向酒店收益经营看板的公开活动事件发现服务。范围是28个经营城市未来90天的演出、会展、赛事、节庆、学生假期与放假调整、大型会议。当前采集与发布均为独立手动执行，没有定时更新。

本分支修复采集范围遗漏、组合检索配额挤占和新闻条数被当作活动数的问题；新增活动日历与覆盖缺口表，离线规范化529条旧线索，整理27项活动（按2026-11-04计算25项在未来窗口内）。全部仍待核验，覆盖仍为 partial，尚未部署。详见 [范围与历史依据](docs/monitoring-scope.md)、[本轮修复报告](docs/coverage-repair-2026-11-04.md)。

## 当前版本边界

- 自动采集入口：Google News RSS，按城市和六类主题分别检索，每类最多50条，查询回溯180天；标题和摘要属于发现层。活动日历另用明确登记的正文证据，不等于已完整爬取所有官网。
- 自动发现的事件统一标记为 pending / unknown；不会自动标记 verified，不得仅凭本数据直接做价格决策。
- 活动举办日期与开票/售票、报名日期分字段记录；文章提及的月份或月份范围不写入 start_at/end_at，避免被误读为单场举办日期。
- 内容性质单独分类：event_announcement、uncertain、ticketing_notice、registration_notice、schedule_roundup、guide、past_report。攻略、排期汇总、开票/报名资讯不会被默认展示为未来活动。
- 未标年份的日期会标记 inferred_year，必须人工核对；日期语义不明确时标记 ambiguous，不自动核验。
- 人数、金额、热线件数等数量不作为日期；旧记录无法重现的日期会清空并保留复核。
- 活动名称附近的举办城市优先于嘉宾、商品等附带城市名；城市冲突、仅检索命中及“审批中/或定档”等未确认安排不进入未来视图。
- 同一候选的多来源会合并；来源链接、发布/发现时间与最近出现时间会保留。
- 新发现记录保留 `discovery_summary` 及其 `discovery_summary_source_url`，供下次重放日期、内容分类和城市判断；摘要仍是未核验的发现线索。
- 采集与 Pages 部署已隔离为两次独立手动操作；main 推送只做验证，不自动采集或部署。本修复保留这一边界，不运行生产任务。
- 不使用内部 PMS、经营数据或私人凭据。公开仓库中的数据与 API 均可被互联网访问。

## 图片分享

按城市、日期等条件筛选后，点击顶部「导出 PNG」打开分享预览，再选择「保存 PNG」或「复制图片」发送给同事。浏览器不允许复制时仍可保存图片；长列表自动分张，可逐张保存，空结果不能导出。

图片保留筛选条件、数据更新时间、活动日期、核验状态和来源；同一活动的多条报道不会在导出时被静默合并。图片宽1080像素，单张高度不超过7200像素。导出在浏览器本地完成，不使用外部截图服务，不触发采集，也不修改核验状态。本机预览生成的图片带预览标记。

公开网页地址为 <https://wildpig622.github.io/hotspot-pulse/>，同事可直接在线查看。PNG导出已在旧线上版本提供；本分支对活动日历、假期适用范围和采集时间的改进需另行发布后上线。

实际PNG、浏览器截图及验证范围见 [图片导出验收](docs/png-export-2026-10-30.md)。网页测试包括：

    node --test tests/test_site.js tests/test_share_image.js

## API

启用 GitHub Pages 后，默认 API 根路径为：

https://wildpig622.github.io/hotspot-pulse/api/v1/

- hotspots.json：新闻线索，保留原ID、来源和发现时间，规范化日期角色与内容性质。
- activities.json：按明确活动身份整理的日历；保留场次、适用范围、证据检查时间及相关报道ID。
- coverage.json：28城×6类的168格覆盖情况及缺口，不把零条解释为没有活动。
- cities.json：经营城市及新闻、活动数量。
- health.json：最近一次真实采集的健康状态与时间；离线整理不刷新采集时间。

这是静态 JSON API，不提供服务器端查询参数。默认活动日历只展示未来90天内仍有场次的记录；新闻线索可单独切换查看。非连续场次按 sessions 判断，学校假期和周末出行窗口分开。看板接入时应默认只消费人工核验后的事件；当前采集器不会自动产生 verified 记录。字段详见 [API文档](docs/API.md)。

## 正式放行后的手动执行

以下只适用于取得正式放行和实际执行授权之后；当前不要运行。

1. 审阅并获准合并本分支后，确认 main 上已经采用手动隔离定义，并记录要执行的 main 完整 40 位提交号。工作流不会替你启用 Pages。
2. 若获准采集，在 Actions 中选择 `Collect hotspot candidates (manual)`，分支选 main，填写该完整提交号和确认词 `COLLECT_PENDING_ONLY`。预检通过后才采集并提交 pending 快照。
3. 采集后的数据提交要单独检查并记录新提交号；采集不会自动触发部署，不保证其机器人提交会触发新的验证运行。需要时单独手动运行只读验证。
4. 只有另行获准发布后，才在 `Deploy static site (manual)` 中选择 main，填写要发布的完整提交号和 `DEPLOY_REVIEWED_SITE`。日期证据和核验状态须有明确审核记录，不要求用户逐条签字；采集器仍不得自动升级 verified。

确认词和提交检查用于防止误操作，不代表已经获得发布许可，也不替代 GitHub 环境的独立审批配置。完整触发矩阵、测试范围及限制见 `docs/execution-isolation-2026-10-29.md`。

## 本地运行

需要 Python 3.11+，无需第三方依赖。

运行测试：

    python -m unittest discover -s tests -v

执行一次真实采集：

    python scripts/collect.py

真实采集需要访问 Google News RSS。若所有 RSS 源都失败，程序会保留上一份事件快照、更新 health.json 并以失败退出；不会用空列表覆盖历史数据。

仅重跑离线审计（不联网、不修改 `site/` 快照）：

    python scripts/audit_snapshot.py --today 2026-10-29

报告输出到 `docs/audit-2026-10-29-followup.json` 和 `.md`，原审计文件保留。JSON 中的 `records` 提供全部记录的分类、日期、排除原因与现有核验状态。程序拒绝把审计输出写到输入快照或 `site/`。

验证网页筛选器（需要 Node.js 20+）：

    node --test tests/test_site.js

2026-10-29 修复复查见 `docs/manual-audit-followup-2026-10-29.md`。历史证据报告不因本轮修复而变成当前事实确认；本分支仍为待审阅修复，不启用定时采集或自动经营决策。

前轮完整代码复查见 `docs/code-review-2026-10-29.md`，其中记录的是当时 main 的自动触发边界。手动隔离方案已进入 main，历史设计依据见 `docs/execution-isolation-2026-10-29.md`。

第二轮证据补查和边界复核见 `docs/evidence-round2-2026-10-29.md`。重建包含来源访问状态和待核验结论的 49 条工作表：

    python scripts/build_verification_worksheet.py

输出为 `docs/verification-worksheet-2026-10-29.json` 和 `.md`。该工作表明确标为 `NOT_VERIFIED`，不会自动更改任何候选的人工核验状态。

固定审计和回归测试使用 `tests/fixtures/hotspots-2026-10-29.json`，它逐字节归档当时457条快照，并校验原SHA-256；后续生产更新不会替换历史审计样本。上面的通用离线审计命令默认仍读取当前 `site/` 快照，需要重放原基线时可指定 `--snapshot tests/fixtures/hotspots-2026-10-29.json`。

第三轮的20条未来候选日期覆盖见 `docs/evidence-round3-2026-10-29.md`。工作表保留各轮证据观察历史；`future_date_evidence_coverage` 单独统计官方日期依据覆盖，不代表记录已被升级为 `verified`。

真实浏览器验收见 `docs/browser-acceptance-2026-10-29.md`。旧快照中的可重现标题日期仅在页面读取时保守补充；不会改写JSON或人工已核验字段。页面刷新只读取已有快照，不启动采集。

2026-10-30首批活动证据汇总见 [活动证据汇总](docs/activity-evidence-2026-10-30.md) 和同名JSON：11组、20条候选全部检查，10组、18条有本轮重新读取的权威日期依据；南宁2条本轮读取失败，仅保留原正文依据和原核验时间。保留原45条处置PASS及严格事实完备FAIL，不把用户签字作为新增门槛。所有记录仍pending / not_verified，生产数据未改。

重建本轮证据汇总（离线、只生成报告）：

    python scripts/build_evidence_refresh.py

2026-10-29的 `docs/pilot-review-2026-10-29.md` 和同名JSON保留为历史可选审核模板：20条候选报道按提案整理为11组，不把报道条数当作独立活动数，也不合并生产记录。模板中签核栏留空不代表用户必须逐条确认。重建历史空白模板：

    python scripts/build_pilot_review.py

人工签核副本应另存，保留审核人、确认日期、来源状态复查时间和结论；不要用重新生成覆盖已填写的副本。

## 数据质量与后续扩展

下一阶段按覆盖缺口补齐可合法访问的官方日历、场馆及协会来源，补查待办活动和取消/延期信息，再执行独立授权的真实采集与发布。当前27项登记不等于28城完整活动清单。只有经权威来源核验的事件，才应被看板作为已确认热点使用。
