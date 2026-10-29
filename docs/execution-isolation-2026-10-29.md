# 采集与部署执行隔离提案

基线：草稿 PR #2 的 `ac21af5fe1ce9b820d9feca40abd29732454e323`。本提案只修改独立分支的工作流与预检代码，不合并、不配置仓库设置、不执行采集或部署，也不写生产 JSON。main 和 PR #1 保持原提交。

**隔离代码已完成离线验证；保护尚未进入 main。正式放行仍为 FAIL / NOT VERIFIED。** 推送后的实际提交及远端验证结果见 PR #2 的当前 Checks 和本轮交付记录，不能套用前轮提交的 CI。

## 实现

采集和部署的 `on` 入口均只保留 `workflow_dispatch`；采集移除 `push` 和 `schedule`，部署移除 `push`。验证工作流新增 main 的 push 分支条件，普通合并/推送 main 只匹配只读验证。

两个生产工作流先运行只读 `check-request` 任务，再允许具有写权限的任务启动。预检必须同时满足：

- 事件是手动 `workflow_dispatch`。
- 分支精确为 `refs/heads/main`，不能使用同名标签或 fix 分支。
- 操作者填写完整 40 位小写提交 SHA，与触发工作流的 `GITHUB_SHA` 完全一致；拒绝短提交、分支名、旧提交和空值。
- 采集输入确认词 `COLLECT_PENDING_ONLY`；部署输入 `DEPLOY_REVIEWED_SITE`，两者不能互用。

`scripts/check_manual_execution.py` 只校验输入，拒绝时明确以失败退出并输出理由；即使全部通过也只报告 `REQUEST_VALIDATED` / `execution_performed: false`。采集/部署任务依赖预检成功，并在任务级再次检查事件、分支、提交与确认词。表单值经环境变量传入 Python，没有拼入 shell 命令。

所有 checkout 固定在触发工作流的提交。预检和部署 checkout 不保存 Git 凭据；采集仅在其通过门槛的任务中获得 `contents: write`，部署仅在对应任务中获得 Pages 和身份令牌写权限。默认工作流权限为 `contents: read`。

采集从固定提交产生数据提交，用普通非强制推送写入 main；main 如已经被其他提交推进，推送会因非快进而拒绝，不能覆盖他人更新。取消的任务不会进入提交步骤。全部来源失败时保留原热点/城市文件，只允许记录失败健康状态；已有离线回归继续覆盖这一行为。

部署不再自动开启 Pages。部署并发设置不取消已在运行的任务，避免另一份未通过预检的手动请求取消已批准运行。采集、部署保持彼此独立；手动采集不是发布网站。

## 触发与拒绝矩阵

本表按提案定义静态检查；拒绝逻辑在本地离线运行，不触发真实生产工作流。

| 情况 | 验证 | 采集 / 部署 |
|---|---|---|
| 推送 fix 分支 | 匹配 push 验证 | 不触发 |
| 打开/更新目标 main 的 PR | 匹配 PR 验证 | 不触发 |
| 普通合并/推送 main | 匹配 push 验证 | 不触发 |
| 每日时钟到点 | 无计划入口 | 无计划入口 |
| 手动请求缺少确认或完整 SHA | 可独立运行只读验证 | 预检失败，写权限任务不运行 |
| 手动选择 fix 分支、标签或不匹配的 SHA | 可独立运行只读验证 | 预检失败，写权限任务不运行 |
| main、完整匹配 SHA、正确动作确认词 | 可独立运行只读验证 | 预检允许后续任务；仍需实际执行授权和发布门槛 |
| 机器人使用 GITHUB_TOKEN 推送采集结果 | 不保证产生新的工作流运行 | 不会自动部署，需另行获准手动发布 |

main 当前仍使用旧定义，含每日采集和 main push 的采集/部署入口。本次没有更改其工作流启用状态。上表只有在将来获准合并本提案后才适用；不能据此宣布当前生产自动任务已被关闭。

## 验证

- 53 项 Python 测试、7 项网页测试全部通过；没有改变原 45 条样本的处置结果或当前 20 条未来候选集合。
- 新增 7 项预检测试覆盖两个动作的正常请求、自动事件拒绝、非 main 分支/标签拒绝、空/短/过期/装饰 SHA 拒绝、动作确认混用、命令行失败码及成功检查不执行生产操作。
- `actionlint v1.7.12` 静态检查三个工作流通过。检查器来自官方发行版，Windows 文件 SHA-256 已验证为 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9`。CI 使用同版 Linux 检查器，并校验发行资产 SHA-256。
- Python 编译和差异格式检查通过。真实采集、部署及其手动入口从未被调用；预检测试在本地替代环境变量，不产生 GitHub 运行、部署记录或 API 数据更改。

复查命令：

```text
python -m unittest discover -s tests -v
node --test tests/test_site.js
python -m py_compile scripts/collect.py scripts/check_manual_execution.py
actionlint .github/workflows/collect.yml .github/workflows/pages.yml .github/workflows/validate.yml
git diff --check
```

## 放行和剩余条件

| 门槛 | 结果 |
|---|---|
| 原 33 条日期支持或明确排除/pending | PASS，结果未变 |
| 12 条边界分类正确 | PASS，结果未变 |
| 已知严重错误回归 | PASS，限原样本和测试输入 |
| 不自动升级 verified | PASS；457 条原快照、49 条工作表仍全部 pending |
| 严格事实核验和正式发布 | FAIL / NOT VERIFIED；没有改写为已放行 |
| 合并前执行隔离 | 提案完成并通过离线检查，尚未在 main 生效 |

确认词是防误操作校验，不能代替人类的实际发布授权，也不是 GitHub `required reviewers`。本轮没有配置或确认仓库环境审批规则。管理员或具有写权限的人仍可改工作流，直接运行采集脚本也不受此工作流门槛控制；这是工作流隔离，不是新的仓库访问控制体系。

后续需要审阅本提案和逐条事实工作表，再取得合并或实际运行的明确授权；本轮不执行这些动作。刘宇条件性消息继续排除/pending，无需用搜索无结果证明不存在；它不阻塞候选处置验收。

## 依据

手动事件及其提交/分支语义依据 [GitHub 的工作流事件文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch)；任务依赖、输入和权限依据 [GitHub 工作流语法](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)。机器人令牌的触发限制见 [触发工作流说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。静态检查器为 [actionlint 官方发行版 v1.7.12](https://github.com/rhysd/actionlint/releases/tag/v1.7.12)。这些文档解释机制，不证明仓库的人工审批已经配置。
