# Phase 2 回归与执行边界

基线：ca514b513b3f95de36a4655c7938afeb00e91c34。
兼容合入的main：2f74df4bddf1b57336e63c63487ad7d2d54d805b；该操作仅更新PR分支。

- Windows官方便携CPython 3.12.10：121项unittest全部通过。
- Node 24：网页筛选、图片和消费客户端36项测试通过。
- scripts/*.py 全部编译通过。
- 当前main公开快照普通质量检查PASS；API v2结构校验PASS，3225条身份记录。
- 当前main旧主题快照的require-full-scope检查预期FAIL：不能把旧范围采集冒充新增主题已采集。普通检查允许完整旧矩阵但返回uncollected_configured_topics，严格发布门禁仍要求全部当前配置范围。
- 每份成功抓取的压缩正文解压后SHA-256校验通过。来源失败保留真实错误；离线重放保留原checked_at。
- 真实采集前后全部site/api/*.json哈希相同；本分支site/api与上述main逐字节相同。
- 没有运行collect.py、refresh_service或生产workflow，没有部署或经营数据库调用，没有verified升级。

新增回归覆盖：全国日期不带城市或需求结论；正文规则未命中不能产生日期；考试报名和成绩日期排除；泛学校关键词与具体会议分类；生产路径输出拒绝；动态topic_catalog key的实际消费。

业务验收详见[真实证据报告](phase2-evidence-2026-11-26/README.md)。121项代码测试通过不代表全网覆盖验收通过：自主RSS基准发现率仍为0，官方定向适配存在已知缺口。
