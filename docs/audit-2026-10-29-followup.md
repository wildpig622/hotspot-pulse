# Offline reclassification audit

- Audit date: `2026-10-29` (Asia/Shanghai)
- Snapshot: `site\api\v1\hotspots.json`; generated at `2026-10-29T03:08:58Z`
- Records audited: **457**
- Method: current branch `enrich_existing_event`, `classify_content`, and `is_upcoming_event`; no network calls.
- Safety: live collection was not run and the production snapshot was not written.

## Primary disposition

These buckets are mutually exclusive and sum to the audited snapshot.

| Category | Count |
|---|---:|
| Future dated event candidates | 20 |
| Event candidates with dates needing review | 351 |
| Ticketing / registration notices | 22 |
| Schedule roundups | 11 |
| Guides / other information | 17 |
| Past reports / expired events | 36 |
| **Total** | **457** |

## Legacy-date comparison

- Legacy snapshot records with `start_at`: **64**.
- Records with `start_at` after offline reclassification: **38**.
- Legacy dated records cleared because the date was not an event date: **26**.

## Verification status

| Status | Count |
|---|---:|
| pending | 457 |

All records retain their existing review status; the audit does not promote any candidate.

## Date-review flags

- Event candidates with at least one date-review flag: **371**.
- Future candidates carrying a review flag (for example inferred year or ambiguous role): **20**.
- Future candidates without a date-review flag: **0**.

| Reason | Count |
|---|---:|
| city_not_confirmed | 48 |
| conditional_event | 3 |
| date_role_ambiguous | 351 |
| event_city_conflict | 6 |
| missing_event_date | 349 |
| month_only_or_range | 5 |
| year_inferred_or_unknown | 369 |

## Representative examples

### month_range_guide_reclassified

- `成都市` — 2026成都演唱会门票怎么买？这份10—12月购票攻略，帮你省心高效拿下门票 → `guide`, `guides_other`; legacy `2026-12-01` → `None`; role `reference_period`.
- `福州市` — 推荐 2027中国（福州）跨境电商展览会-电商展览会-3月18举办 → `guide`, `guides_other`; legacy `2027-03-01` → `None`; role `unknown`.
- `沈阳市` — 沈阳2026年9-12月演唱会、话剧、脱口秀等演出的靠谱购票平台有哪些？ → `guide`, `guides_other`; legacy `2026-09-12` → `None`; role `reference_period`.
- `南京市` — 靠谱高效！2026南京10-12月演唱会、话剧、音乐剧等演出靠谱购票指南 → `guide`, `guides_other`; legacy `2026-12-01` → `None`; role `reference_period`.

### ticketing_or_registration

- `金华市` — #潘玮柏[超话]#❤‍🔥#潘玮柏狂爱终极巡回演唱会#狂爱新地图✅【金华】初相见！潘玮柏「狂爱：终极」巡回演唱会金华站现已开启售票点击🔗即刻购买>>http://t.cn/AXjoMqF6第一次相约八婺大地，当然要「金」情狂欢，「华」丽开唱，和@潘瑋柏一起共同续写狂爱的火热终极篇 → `ticketing_notice`, `ticketing_registration`; legacy `None` → `None`; role `unknown`.
- `南宁市` — 2026南宁马拉松明日开始报名！报名方式、日程表速收藏 → `registration_notice`, `ticketing_registration`; legacy `None` → `None`; role `unknown`.
- `南宁市` — 2026年南宁马拉松报名时间今日公布 → `registration_notice`, `ticketing_registration`; legacy `None` → `None`; role `unknown`.
- `南宁市` — 2026年南宁马拉松比赛路线！报名时间+入口 → `registration_notice`, `ticketing_registration`; legacy `None` → `None`; role `unknown`.
- `深圳市` — 2026深圳马拉松报名开启 → `registration_notice`, `ticketing_registration`; legacy `None` → `None`; role `unknown`.

### schedule_roundup

- `南昌市` — 2026南昌国庆演出排期安排来了！ → `schedule_roundup`, `schedule_roundup`; legacy `None` → `None`; role `unknown`.
- `南宁市` — 2026年南宁国庆展览/展会活动汇总！漫展+车展+灯展+智能机器人大会…… → `schedule_roundup`, `schedule_roundup`; legacy `None` → `None`; role `unknown`.
- `南昌市` — 2026年南昌10月演出排期安排来了 → `schedule_roundup`, `schedule_roundup`; legacy `2026-10-01` → `None`; role `reference_period`.
- `沈阳市` — 2026沈阳中秋国庆假期户外音乐会阵容及节目单！民乐、交响乐、乐队演出 → `schedule_roundup`, `schedule_roundup`; legacy `None` → `None`; role `unknown`.
- `郑州市` — 2026郑州演唱会排期表（10月23日更新） → `schedule_roundup`, `schedule_roundup`; legacy `2026-10-01` → `None`; role `ambiguous`.

### past_report_or_expired

- `西安市` — #媒体原创 10月18日 陕西西安。2026西安马拉松赛 男子组冠军诞生！陕西选手武明瑶以2小时10分16秒夺冠#2026西安马拉松赛 → `past_report`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `ambiguous`.
- `西安市` — #媒体原创 10月18日 陕西西安。2026西安马拉松赛参赛跑者在太华路立交补给点取水，选手们加油！#2026西安马拉松赛 → `uncertain`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `ambiguous`.
- `西安市` — 10月18日上午7时30分2026西安马拉松赛 在永宁门鸣枪开跑。#2026西安马拉松 → `event_announcement`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `event`.
- `兰州市` — 2026兰州马拉松“跑遍兰州”系列活动——“九九重阳·福寿安宁”登高（安宁站）10月18日开赛 → `event_announcement`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `event`.
- `深圳市` — 2026声动南山 蓝心羽「爱是Love is...」巡回演唱会深圳站圆满落幕 → `past_report`, `past_expired`; legacy `None` → `None`; role `unknown`.

### legacy_date_changed

- `成都市` — #其它# 刘宇成都演唱会正在审批中，或定档2027年1月1日-2日凤凰山体育公园 → `uncertain`, `event_date_review`; legacy `2027-01-01` → `2027-01-01`; role `event`.
- `西安市` — #媒体原创 10月18日 陕西西安。2026西安马拉松赛 男子组冠军诞生！陕西选手武明瑶以2小时10分16秒夺冠#2026西安马拉松赛 → `past_report`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `ambiguous`.
- `西安市` — #媒体原创 10月18日 陕西西安。2026西安马拉松赛参赛跑者在太华路立交补给点取水，选手们加油！#2026西安马拉松赛 → `uncertain`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `ambiguous`.
- `西安市` — 10月18日上午7时30分2026西安马拉松赛 在永宁门鸣枪开跑。#2026西安马拉松 → `event_announcement`, `past_expired`; legacy `2026-10-01` → `2026-10-18`; role `event`.
- `珠海市` — 10月珠海见！ReWork湾区国际AI办公应用及办公空间展览会，解锁AI办公产业新图景！ → `uncertain`, `event_date_review`; legacy `2026-10-01` → `None`; role `reference_period`.

### future_dated_event_candidates

- `武汉市` — 2026武汉国际车展10月30日启幕，2200万元消费券同步发放- 湖北日报新闻客户端 → `event_announcement`, `future_dated_event`; legacy `2026-10-30` → `2026-10-30`; role `event`.
- `南昌市` — 2026南昌航空产业博览会10月31日启幕 低空经济领域多款装备将亮相 → `event_announcement`, `future_dated_event`; legacy `2026-10-31` → `2026-10-31`; role `event`.
- `南昌市` — 2026南昌航空产业博览会10月31日开幕 设置十大展区 → `event_announcement`, `future_dated_event`; legacy `2026-10-31` → `2026-10-31`; role `event`.
- `杭州市` — 11月1日7时，2026杭州马拉松鸣枪开跑 → `event_announcement`, `future_dated_event`; legacy `2026-11-01` → `2026-11-01`; role `ambiguous`.
- `杭州市` — 2026杭州马拉松11月1日开跑 → `event_announcement`, `future_dated_event`; legacy `2026-11-01` → `2026-11-01`; role `event`.
- `杭州市` — 2026杭州马拉松11月1日开跑 全新路线、完赛奖牌公布 → `event_announcement`, `future_dated_event`; legacy `2026-11-01` → `2026-11-01`; role `event`.
- `杭州市` — 【#公交信息#】#杭州# 2026吉利汽车·杭州马拉松主题巴士已上线[哇]2026年11月1日，久违的杭州马拉松将再次拉开帷幕。值得一提的是由于西兴大桥重建影响，今年的“杭马”路线首次改经老彭埠大桥（钱江二桥），比赛当日杭州地铁1/2/3/4/5/10号线各站首班发车时间将 → `uncertain`, `future_dated_event`; legacy `2026-11-01` → `2026-11-01`; role `ambiguous`.
- `昆明市` — 2026昆明国际车展将于11月5日至9日在滇池国际会展中心举办 → `event_announcement`, `future_dated_event`; legacy `2026-11-05` → `2026-11-05`; role `event`.

### event_candidates_with_dates_needing_review

- `西安市` — #其它# 2026西安马拉松参赛跑者通过钟楼盘道。 在奔跑中感受世界人文之都的魅力#2026西安马拉松 → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `成都市` — #其它# 刘宇成都演唱会正在审批中，或定档2027年1月1日-2日凤凰山体育公园 → `uncertain`, `event_date_review`; legacy `2027-01-01` → `2027-01-01`; role `event`.
- `南京市` — #华晨宇[超话]# 💕 爱有多深刻 @华晨宇yu #2026华晨宇火星演唱会# hcy [261024南京] http://t.cn/A6eADqus ​ → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `南京市` — #博君一肖[超话]# 终于 盼到了 20261023 肖战［出口·我们］巡回演唱会南京站 → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `厦门市` — #厦门演唱会又上新##周传雄厦门演唱会#重磅官宣！周传雄2026「念念不忘·再遇见plus」巡演·厦门站这一站很值得等——《黄昏》《青花》《寂寞沙洲冷》唱了三十年的金曲，「念念不忘」系列巡演四年48场场场爆满，这次带着升级版首唱进鹭岛体育场。🗓 演出时间：2026年1 → `event_announcement`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `广州市` — #周笔畅[超话]# 以旧色为幕，借针脚叙序。声动羊城，跟老板@周笔畅 在歌声里相会。 #遇见美好广州巅峰演唱会# ​ → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `杭州市` — #张远[超话]# 🦋#张远远行巡回演唱会# 星芒破晓，铸一节创生之章⛓️ @张远Bird #张远杭州演唱会# ​ → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.
- `杭州市` — #张远[超话]# 🦋#张远远行巡回演唱会# 星芒铺于身后，此刻自成光源✨ @张远Bird #张远杭州演唱会# ​ → `uncertain`, `event_date_review`; legacy `None` → `None`; role `unknown`.

## Date parsing edge cases

| Case | start_at | end_at | role | precision | ticket_sale_at | registration_at |
|---|---|---|---|---|---|---|
| month range is reference period | — | — | reference_period | month_range | — | — |
| ticket sale date is not event date | — | — | ticket_sale | tbd | 2026-10-15 | — |
| event date wins over nearby ticket sale | 2026-11-01 | — | event | day | 2026-10-15 | — |
| cross-month event range | 2026-11-29 | 2026-12-01 | event | day | — | — |
| cross-year shorthand range | 2026-12-31 | 2027-01-02 | event | day | — | — |
| slash date without year | 2026-11-08 | — | event | day | — | — |
| compact numeric date remains a review lead | — | — | unknown | tbd | — | — |
| registration date is not event date | — | — | registration | tbd | — | 2026-11-05 |
| participant quantity is not a date | — | — | unknown | tbd | — | — |
| hotline quantity is not a date | — | — | unknown | tbd | — | — |
| valid dotted event date | 2026-11-08 | — | event | day | — | — |

## Complete future candidate IDs

- `evt_75164357227c` — 武汉市 — 2026武汉国际车展10月30日启幕，2200万元消费券同步发放- 湖北日报新闻客户端 — `2026-10-30`
- `evt_3b05c8d23d3b` — 南昌市 — 2026南昌航空产业博览会10月31日启幕 低空经济领域多款装备将亮相 — `2026-10-31`
- `evt_3be0559d6385` — 南昌市 — 2026南昌航空产业博览会10月31日开幕 设置十大展区 — `2026-10-31`
- `evt_6614d69412a6` — 杭州市 — 11月1日7时，2026杭州马拉松鸣枪开跑 — `2026-11-01`
- `evt_5f79d978ec7c` — 杭州市 — 2026杭州马拉松11月1日开跑 — `2026-11-01`
- `evt_8da43a5d108c` — 杭州市 — 2026杭州马拉松11月1日开跑 全新路线、完赛奖牌公布 — `2026-11-01`
- `evt_4310a7ec1019` — 杭州市 — 【#公交信息#】#杭州# 2026吉利汽车·杭州马拉松主题巴士已上线[哇]2026年11月1日，久违的杭州马拉松将再次拉开帷幕。值得一提的是由于西兴大桥重建影响，今年的“杭马”路线首次改经老彭埠大桥（钱江二桥），比赛当日杭州地铁1/2/3/4/5/10号线各站首班发车时间将 — `2026-11-01`
- `evt_cfd1dabb5e54` — 昆明市 — 2026昆明国际车展将于11月5日至9日在滇池国际会展中心举办 — `2026-11-05`
- `evt_cbf419541499` — 金华市 — 2026金华·金漪湖半程马拉松将于11月8日开赛_地方聚焦 — `2026-11-08`
- `evt_204d62998417` — 郑州市 — 2026郑州国际车展11月12日开幕 江南甜心苏州小汤圆亮相 — `2026-11-12`
- `evt_3d9ba51c1b02` — 南昌市 — 2026南昌马拉松11月15日正式开跑 报名人数创历史新高 — `2026-11-15`
- `evt_92e97e99aec8` — 南昌市 — 2026南昌马拉松赛定档11月15日开跑，已有13.5万人报名参赛 — `2026-11-15`
- `evt_1bcb5302ec11` — 南昌市 — 完赛奖牌、参赛服亮相！2026南昌马拉松11月15日开跑 — `2026-11-15`
- `evt_d0d48c4aa6c3` — 长沙市 — 192052人报名创历史新高！2026长沙马拉松11月15日开跑 — `2026-11-15`
- `evt_dcb3d2d46412` — 长沙市 — 定档11月15日！2026长沙马拉松报名破19万人创历史新高 — `2026-11-15`
- `evt_3ffac103faf3` — 长沙市 — 总报名人数达192052人，2026长沙马拉松11月15日开跑 — `2026-11-15`
- `evt_d52b5f413583` — 长沙市 — 从“养小”到“养老”：2026长沙银发产业博览会11月20日启幕_热点 — `2026-11-20`
- `evt_6c148ae9cbc6` — 南宁市 — 2026南宁马拉松报名开启！将于12月20日鸣枪起跑 — `2026-12-20`
- `evt_bd8e6c831c64` — 南宁市 — 最新消息：2026南宁马拉松将于10月20日10：00开启报名，比赛时间为12月20日 — `2026-12-20`
- `evt_a444c0520dce` — 广州市 — 2026黄埔马拉松将于12月27日在广州举行 — `2026-12-27`

## Interpretation

The snapshot is a discovery pool, not a verified event calendar. The future bucket is the current collector's default future/ongoing filter; pending status still blocks operational use. Month-only, ambiguous, inferred-year, and undated event leads remain review work.
