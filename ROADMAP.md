# 路线

## 远程仓库

- 仓库：https://github.com/wangcheng-coder/OpenDevMate
- `main` 已推送初始提交 `9885451`。
- CI 工作流是 `.github/workflows/ci.yml`，只安装项目并运行 `pytest`。
- 首次推送的运行已成功：https://github.com/wangcheng-coder/OpenDevMate/actions/runs/44689637795
- Milestone「0.2 下一步」跟踪下面三个 Issue：
  - #1 用 PostgreSQL 保存项目和任务
  - #2 只读同步 GitHub Issue
  - #3 外部 Agent 只在独立工作区执行
## 已完成：0.1.0

项目、任务拆分、状态机、执行记录、Diff、测试、审查、知识、目录扫描和仪表盘。

## 下一步

0.1.1 已完成的部分写在变更记录里。仍未完成的是需要真实数据库或仍未替换存储的部分。

1. 把存储换成 PostgreSQL，并保留现有测试所覆盖的规则。
2. 只读同步 GitHub Issue。不同步时不影响本地任务。
3. 接入一个外部 Agent 执行器。执行器必须在独立工作区运行，不能直接改默认分支。

## 暂不做

自动写代码、自动开 PR、多 Agent 调度和 Kubernetes。没有真实使用记录之前，这些只会增加运行面。

## 0.1.2

借鉴 [tickmarkr](https://github.com/alzahrani-khalid/tickmarkr) 的验收标准和 [LaneGate](https://github.com/sudheerdvn/lanegate) 的文件范围：任务可以声明验收条件和允许改动的路径。超出范围或测试仍失败时不能验收。没有这份约定时，原有审查流程不变。

## 0.1.3

进行中的任务会检查已声明的路径是否重叠。没有约定的任务仍按原流程执行。

## 0.1.4

Diff 在写入时检查路径。密钥文件和越出工作区的路径不会进入记录。

## 0.1.5

有子任务时，父任务要等子任务验收后才能验收。

## 0.1.6

中英文切换默认中文。Spring AI 使用 `spring-ai/application-mcp.yml` 里的 Streamable HTTP 连接 `/mcp`。

## 0.1.7

配置从 Nacos 读取。镜像由 GitHub Actions 发布到 GHCR。

## 0.1.8

提供统一控制台 `/`。页面只调用本服务接口。
