# OpenDevMate

OpenDevMate 帮助人管理 AI Coding Agent 的工作，不替代 Agent 写代码。

人负责需求和验收。系统保存项目知识、任务状态、Diff、测试记录和审查结论。当前版本不会调用外部模型，也不会自动改仓库。

## 0.1.0 能做什么

- 建立项目和任务，并把一个任务拆成子任务。
- 任务状态只允许 `draft → ready → running → review → accepted`，也可以进入 `blocked`。
- 按项目知识生成一份可复制给 Agent 的任务说明。
- 记录执行结果、Diff、测试数量和审查结论。高风险审查不能直接验收。
- 扫描允许目录内的文件类型和顶层模块，拒绝目录之外的路径。
- 提供 `/api/dashboard` 和 `/dashboard`。

## 现在不做什么

- 不连接真实 Coding Agent。
- 不同步 GitHub Issue 或 PR。
- 不使用 Java 21。原因见 `docs/decisions/0001-mvp-stack.md`。

## 本地运行

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn opendevmate.api:app --reload
```

接口文档路径是 `/docs`。本地 `uvicorn` 使用它自己的默认监听端口。容器和发布环境的地址、端口、数据库由 Nacos 或 `APP_*` 环境变量决定，不写进镜像。

## 许可证

Apache-2.0。选择理由见架构决策记录。

## 语言和 Spring AI

默认语言是中文。请求带 `Accept-Language: en` 或 `?lang=en` 时，错误信息和工具说明返回英文。源码、SQL、日志原文不翻译。

Spring AI 不内嵌在本服务里。把 `spring-ai/pom-snippet.xml` 的 `spring-ai-starter-mcp-client` 加到 Spring AI 应用，连接配置由 `spring-ai/application-mcp.yml` 指向 Nacos，地址写在 `nacos/spring-mcp.yaml`。端点默认是 `/mcp`。本仓库的测试覆盖 MCP 的 initialize、tools/list 和 tools/call，不编译 Java。

## 配置

服务地址不写进镜像。设置 `NACOS_SERVER` 后，进程启动时读取 Nacos 中的服务配置，默认 dataId 见 `nacos/service.properties`。没有 Nacos 时使用 `APP_HOST`、`APP_PORT`、`APP_DATABASE` 和 `APP_LOCALE`。

Spring AI 的 MCP 地址放在 Nacos 的 `nacos/spring-mcp.yaml`。`spring-ai/application-mcp.yml` 只指向 Nacos，不写服务地址。

## 镜像

```bash
docker build -t opendevmate:local .
```

`main` 分支的 `.github/workflows/image.yml` 会把镜像推到 `ghcr.io/wangcheng-coder/opendevmate`。

## 页面

打开服务根路径 `/`。五个项目使用同一套版式：顶栏、左右两栏、中英文切换。页面只调用本服务已有的接口。
