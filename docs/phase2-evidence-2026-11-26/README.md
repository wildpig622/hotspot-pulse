# Phase 2 三城真实采集与验收

> Phase5 归档调整：当前分支仅保留公开最小证据。完整响应压缩包、逐新闻原始数据已退役，报告保留原始漏斗汇总及少量样本；联系方式与冗长正文已精简。原始文件仅在忽略的本地 review 备份中，哈希见 `../phase5-release-2026-11-27/evidence-minimization.json`。以下为当时实验记录，不能将归档精简后的文件当作原始响应重放。

观察日：2026-11-26；窗口首尾包含，截止 2027-11-26。
固定基线 ca514b5；所有新闻重放使用同一观察日。原始页面的 checked_at 是实际获取时间，replayed 不刷新证据时间。

## 真实采集

| 城市 | RSS命中 | 去重新闻 | 明确举办日期 | 有效未来候选 | 官方日期记录 |
|---|---:|---:|---:|---:|---:|
| 天津市 | 354 | 268 | 0 | 0 | 3 |
| 济南市 | 274 | 194 | 1 | 0 | 5 |
| 西安市 | 400 | 311 | 0 | 0 | 2 |

跨查询重复命中 255 条；此数是重复观察次数，不是独立重复活动数。同城同类同日只能进入疑似重复队列，不能据此合并。
全国统一日程 2 项单独列出；不复制到三城，不估计规模/住宿增量。

## 官方事件清单

| 城市/范围 | 名称 | 开始 | 结束 | 来源 |
|---|---|---|---|---|
| 西安市 | 第四届数字赋能外语教师发展研讨会 | 2026-12-19 | 2026-12-19 | [西安交通大学外国语学院](https://sfs.xjtu.edu.cn/info/1243/9348.htm) |
| 西安市 | 第四届智能控制测量与信号系统国际会议FICMSS2027 | 2027-01-08 | 2027-01-10 | [长安大学机械学院（参与单位）](https://cmcs.chd.edu.cn/2026/1010/c8633a262954/page.htm) |
| 全国 | 2027年全国硕士研究生招生考试初试 | 2026-12-19 | 2026-12-20 | [教育部](https://www.moe.gov.cn/srcsite/A15/moe_778/s3261/202609/t20260923_1451734.html) |
| 全国 | 2027年度国考公共科目笔试 | 2026-11-29 | 2026-11-29 | [北京市政府转载新华社](https://www.beijing.gov.cn/cs/gncs/csbmts/202611/t20261116_4948266.html) |
| 天津市 | 2027年全国硕士研究生招生考试天津考区 | 2026-12-19 | 2026-12-20 | [天津市政府转载天津日报](https://www.tj.gov.cn/zmhd/hygqx/202610/t20261009_7390056.html) |
| 天津市 | 天津市2027年度公务员公共科目笔试 | 2026-12-06 | 2026-12-06 | [天津市公务员局/天津政务网](https://www.tj.gov.cn/zwgk/zfxxgkzl/fdzdgknr/zkly/zk/202611/t20261103_7649185.html) |
| 天津市 | 天津市2027年度公务员专业科目笔试 | 2026-12-05 | 2026-12-05 | [天津市公务员局/天津政务网](https://www.tj.gov.cn/zwgk/zfxxgkzl/fdzdgknr/zkly/zk/202611/t20261103_7649185.html) |
| 济南市 | 济南义务教育2027寒假 | 2027-01-23 | 2027-02-21 | [济南市教育局/市政府](https://www.jinan.gov.cn/col/col118356/art/2026/art_2535c06993fc499b856e136e646c243a.html) |
| 济南市 | 济南高中2027寒假 | 2027-01-30 | 2027-02-21 | [济南市教育局/市政府](https://www.jinan.gov.cn/col/col118356/art/2026/art_2535c06993fc499b856e136e646c243a.html) |
| 济南市 | 济南义务教育2027暑假 | 2027-07-07 | 2027-08-31 | [济南市教育局/市政府](https://www.jinan.gov.cn/col/col118356/art/2026/art_2535c06993fc499b856e136e646c243a.html) |
| 济南市 | 济南高中2027暑假 | 2027-07-14 | 2027-08-31 | [济南市教育局/市政府](https://www.jinan.gov.cn/col/col118356/art/2026/art_2535c06993fc499b856e136e646c243a.html) |
| 济南市 | 区域国别研究与国家语言能力建设学术研讨会 | 2026-12-11 | 2026-12-13 | [山东大学外国语学院](https://www.flc.sdu.edu.cn/info/1150/23835.htm) |

## 17079条候选转化漏斗

| 阶段 | 输入 | 留存 | 损失 |
|---|---:|---:|---:|
| event_content | 17079 | 14339 | 2740 |
| explicit_event_date | 14339 | 653 | 13686 |
| confirmed_city | 653 | 417 | 236 |
| future_365 | 417 | 169 | 248 |
| safe_candidate | 169 | 166 | 3 |

重放前后有效未来新闻候选 166 → 166。分类/过滤结果变化 108 条，全部逐条见 report.json。
默认未来API和本验收口径不同：本验收要求明确 event 日期角色；ambiguous 留待复核，不能视为已确认错误。
原活动登记 47 项；严格有效且未显式登记关联的新闻 163 条，仍可经 discovery_candidates 进入日历，不能把未登记等同于丢弃。

合理过滤：无明确日期、历史事件、报名/缴费/成绩节点、城市未证实、条件安排、取消/延期。
确认并修复：成绩查询/证书日期不得充当考试日；宽泛学校词不得覆盖具体会议主题；网页 topic_catalog 的 key 应被消费，不能只识别 topic。
未逐条核实全部新闻真实性；跨城冲突、日期歧义和相似活动保留为复核队列，不把所有过滤记录宣称为合理或错误。

## 同点对照与独立基准

| 城市 | 原v2候选身份 | 原严格新闻 | 新增严格新闻 | 官方补充记录 |
|---|---:|---:|---:|---:|
| 天津市 | 92 | 4 | 0 | 3 |
| 济南市 | 67 | 1 | 0 | 5 |
| 西安市 | 99 | 0 | 0 | 2 |

原v2是全部主题的候选身份；新检索重点为考试、假期和会议，两列不构成完整版本召回率。官方与新闻未完全绑定身份，官方补充仍可能与旧记录重复。
人工基准 14 项：RSS自主命中 0；官方定向提取命中 12。
基准在提取前从独立官方检索人工抄录。大部分网址随后作为显式种子传给适配器，因此官方命中是定向提取成功率，不是无偏自主发现率。ICCLL保留为未接入holdout；小样本不推断全网召回率。

未覆盖的已知事件：
- holdout-iccll：2027-05-21 至 2027-05-23；西安市
- tianjin-regional-conference：2026-11-27 至 2026-11-29；天津市

## 来源失败与限制

- 天津市：https://news.google.com/rss/search?q=%22%E5%A4%A9%E6%B4%A5%22+%28%E5%9B%BD%E8%80%83+OR+%E5%9B%BD%E5%AE%B6%E5%85%AC%E5%8A%A1%E5%91%98%29+%281%E6%9C%88+OR+2%E6%9C%88+OR+3%E6%9C%88+OR+4%E6%9C%88+OR+5%E6%9C%88+OR+6%E6%9C%88+OR+7%E6%9C%88+OR+8%E6%9C%88+OR+9%E6%9C%88+OR+10%E6%9C%88+OR+11%E6%9C%88+OR+12%E6%9C%88%29+after%3A2025-11-26&hl=zh-CN&gl=CN&ceid=CN%3Azh-Hans；HTTP Error 429: Too Many Requests
- cpta：https://www.cpta.com.cn/；<urlopen error [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 alert handshake failure (_ssl.c:1010)>
- scs：https://www.scs.gov.cn/；<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch, certificate is not valid for 'www.scs.gov.cn'. (_ssl.c:1010)>
- tj-education：https://www.zhaokao.net/；<urlopen error [WinError 10054] 远程主机强迫关闭了一个现有的连接。>
- xian-convention：https://www.xaicec.com/；<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1010)>
- tianjin-regional-conference：https://wgy.tust.edu.cn/xwdt/tzgg/cea333cbcc3749e8ade6c12f79da5ee6.htm；HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop.
The last 30x error message was:
Moved Temporarily

失败未关闭TLS验证、未绕过验证码或访问限制。天津考试另读市政府公开公告、国考另读政府转载，明确保留来源层级。HTTP读取成功只证明响应可读，不保证官网内容已遍历或全部规则适配。
三城各考试子类均已检索；没有当前正文与明确举办日期的高考/中考、事业单位、教资、职业资格、省考等仍列来源覆盖缺口，不按年度规律生成日期。校历按学段区分；春秋假未外推统一日期。会议索引相关链接仅列后续检查队列。

## 交付与复现

原始响应：raw/*.gz（解压后的SHA-256与 report.json 对应）；raw-observations.json 是每次RSS命中；rss-candidates.json 是新闻身份去重；official-events.json 是正文规则命中；report.json 包含全部逐条损失、日期/城市原因、对照身份、基准漏项和生产哈希。
生产快照哈希检查：True。PR合并最新main时直接保留main快照，Phase 2没有改写 site/api。事件全部 pending，无经营数据库调用。
命令：python -m scripts.phase2_acceptance --output docs/phase2-evidence-2026-11-26 --as-of 2026-11-26 --reuse-evidence
下一步：补全会议/考试索引翻页与正文下钻；补充独立随机holdout、地方考点、逐事件跨源身份关联和取消/延期复查。当前自主发现指标不足，尚未通过业务完整覆盖验收。
