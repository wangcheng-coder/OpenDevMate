"""中英文切换。默认中文，已有调用不传语言时行为不变。"""

from __future__ import annotations

import os

import re
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

current_locale: ContextVar[str] = ContextVar("locale", default="zh")
LOCALES = ("zh", "en")
TEXT_FIELDS = {
    "name", "summary", "message", "detail", "reason", "impact", "direction",
    "risk", "verification", "answer", "error", "prompt",
}

def negotiate(header: str | None, query: str | None = None) -> str:
    if query in LOCALES:
        return query
    if header:
        for part in header.split(","):
            token = part.split(";", 1)[0].strip().lower().replace("_", "-")
            if token.startswith("en"):
                return "en"
            if token.startswith("zh"):
                return "zh"
    fallback = os.environ.get("APP_LOCALE", "zh").strip().lower()
    return fallback if fallback in LOCALES else "zh"


def localize_error(message: str, locale: str) -> str:
    if locale != "en":
        return message
    if message in EN:
        return EN[message]
    for pattern, template in PATTERNS:
        matched = pattern.fullmatch(message)
        if matched:
            return template.format(*matched.groups())
    return message


def text(key: str, locale: str) -> str:
    table = TEXT.get(locale) or TEXT["zh"]
    return table.get(key) or TEXT["zh"][key]


def translate_payload(value, locale: str):
    if locale != "en":
        return value
    if isinstance(value, dict):
        translated = {}
        for key, item in value.items():
            if key == "suggestions" and isinstance(item, list):
                translated[key] = [
                    localize_error(piece, "en") if isinstance(piece, str) else translate_payload(piece, "en")
                    for piece in item
                ]
            elif key in TEXT_FIELDS and isinstance(item, str):
                translated[key] = localize_error(item, "en")
            else:
                translated[key] = translate_payload(item, "en")
        return translated
    if isinstance(value, list):
        return [translate_payload(item, "en") for item in value]
    return value


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def bind_locale(request: Request, call_next):
        token = current_locale.set(negotiate(request.headers.get("accept-language"), request.query_params.get("lang")))
        try:
            return await call_next(request)
        finally:
            current_locale.reset(token)

    @app.exception_handler(HTTPException)
    async def translate_http(request: Request, exc: HTTPException):
        locale = negotiate(request.headers.get("accept-language"), request.query_params.get("lang"))
        detail = exc.detail
        if isinstance(detail, str):
            detail = localize_error(detail, locale)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @app.get("/api/meta")
    def meta(request: Request):
        locale = negotiate(request.headers.get("accept-language"), request.query_params.get("lang"))
        return {
            "locale": locale,
            "locales": list(LOCALES),
            "mcp": "/mcp",
            "springAi": "streamable-http",
            "message": text("meta.ready", locale),
        }


EN = {
    "项目名称和说明都不能为空": "Project name and description are both required",
    "项目不存在": "Project does not exist",
    "任务标题不能为空": "Task title is required",
    "子任务必须属于同一个项目": "A child task must belong to the same project",
    "任务不存在": "Task does not exist",
    "已验收的任务不能再拆分": "An accepted task cannot be split",
    "至少要有一个子任务标题": "At least one child task title is required",
    "知识类型必须是 spec、decision、constraint 或 note": "Knowledge kind must be spec, decision, constraint, or note",
    "知识要有标题、正文和来源": "Knowledge needs a title, body, and source",
    "只有 ready、running 或 review 的任务可以记执行记录": "Execution records are allowed only for ready, running, or review tasks",
    "执行状态只能是 recorded 或 failed": "Execution status must be recorded or failed",
    "只有执行中或审查中的任务可以记 Diff": "Diffs are allowed only while a task is running or in review",
    "Diff 摘要不能为空": "Diff summary is required",
    "Diff 路径必须是工作区内的相对路径": "A diff path must be a relative path inside the workspace",
    "Diff 不能记录密钥或 Git 文件": "A diff cannot record secret or Git files",
    "只有执行中或审查中的任务可以记测试": "Test results are allowed only while a task is running or in review",
    "测试数量不能为负": "Test counts cannot be negative",
    "只有审查中的任务可以记审查结论": "Reviews are allowed only while a task is in review",
    "风险必须是 info、low、medium 或 high": "Risk must be info, low, medium, or high",
    "审查结论不能为空": "Review findings are required",
    "高风险审查不能直接验收": "A high-risk review cannot be accepted directly",
    "还有子任务没有验收": "Child tasks are still awaiting acceptance",
    "改动范围必须是相对路径，不能包含 ..": "The allowed path must be relative and cannot contain ..",
    "改动范围不能包含密钥文件或 Git 目录": "The allowed path cannot include secret files or a Git directory",
    "验收需要至少一条标准和一个改动范围": "Acceptance needs at least one criterion and one allowed path",
    "改动范围与正在执行的任务重叠": "The allowed path overlaps a task that is already running",
    "写了验收范围时，必须先记录 Diff": "A diff is required before acceptance when an allowed path is set",
    "Diff 包含密钥或 Git 文件，不能验收": "Acceptance is blocked because the diff contains secret or Git files",
    "Diff 超出声明的改动范围": "The diff is outside the declared path",
    "最近一次测试还有失败，不能验收": "The latest test run still has failures",
    "扫描路径必须位于允许的工作区之内": "The scan path must stay inside the allowed workspace",
    "扫描路径不是目录": "The scan path is not a directory",
    "没有 Token，本地任务仍可使用": "No token is available; local tasks still work",
    "执行目录必须是独立工作区，不能使用默认工作区或其外部路径": "The execution directory must be an isolated workspace",
    "未知工具": "Unknown tool",
}

PATTERNS = [
    (re.compile(r"不能从 (.+) 改为 (.+)"), "Cannot change status from {0} to {1}"),
    (re.compile(r"文件数超过 (\d+)，请缩小扫描目录"), "File count exceeds {0}; narrow the scan directory"),
]

TEXT = {
    "zh": {
        "meta.ready": "当前语言是中文。MCP 端点是 /mcp，供 Spring AI Streamable HTTP 客户端连接。",
        "mcp.instructions": "工具只读或只记录，不执行日志命令，不连接生产数据库，也不把推测写成事实。",
        "mcp.invalid": "请求无效",
        "mcp.protocol": "不支持的 MCP 协议版本",
        "mcp.arguments": "工具参数必须是对象",
        "mcp.json": "请求不是 JSON",
        "mcp.method": "不支持的 MCP 方法",
        "tool.dashboard": "查看项目、任务和风险数量。不会修改数据。",
        "tool.dashboard.result": "这是当前记录的数量，不是外部系统的实时状态。",
        "tool.create_project": "创建一个本地项目。不会调用外部 Agent。",
        "tool.create_project.result": "项目已保存在本地。",
        "dashboard.projects": "项目",
        "dashboard.tasks": "任务",
        "dashboard.executions": "执行",
        "dashboard.failed": "失败执行",
        "dashboard.risks": "未关闭风险",
        "dashboard.status": "状态",
        "dashboard.count": "数量",
        "dashboard.blocked": "阻塞任务",
        "dashboard.task": "任务",
        "dashboard.reason": "原因",
    },
    "en": {
        "meta.ready": "The current language is English. The MCP endpoint is /mcp for a Spring AI Streamable HTTP client.",
        "mcp.instructions": "Tools only read or record. They do not run log commands, connect to production databases, or treat inferences as facts.",
        "mcp.invalid": "Invalid request",
        "mcp.protocol": "Unsupported MCP protocol version",
        "mcp.arguments": "Tool arguments must be an object",
        "mcp.json": "Request is not JSON",
        "mcp.method": "Unsupported MCP method",
        "tool.dashboard": "Read project, task, and risk counts. This does not change data.",
        "tool.dashboard.result": "These counts come from local records, not a live external system.",
        "tool.create_project": "Create a local project. No external agent is called.",
        "tool.create_project.result": "The project is stored locally.",
        "dashboard.projects": "Projects",
        "dashboard.tasks": "Tasks",
        "dashboard.executions": "Executions",
        "dashboard.failed": "Failed executions",
        "dashboard.risks": "Open risks",
        "dashboard.status": "Status",
        "dashboard.count": "Count",
        "dashboard.blocked": "Blocked tasks",
        "dashboard.task": "Task",
        "dashboard.reason": "Reason",
    },
}
