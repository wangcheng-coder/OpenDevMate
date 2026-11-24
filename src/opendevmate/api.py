"""OpenDevMate HTTP API。领域规则在 service，这里只做适配。"""

from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from opendevmate.i18n import current_locale, install, text
from opendevmate.mcp_server import mount
from opendevmate.service import DomainError, Store, scan_directory

BASE = Path(os.environ.get("OPENDEVMATE_WORKSPACE", Path.cwd()))


class ProjectIn(BaseModel):
    name: str
    description: str
    repo_url: str = ""


class ScanIn(BaseModel):
    root: str


class TaskIn(BaseModel):
    title: str
    description: str = ""
    parent_id: str | None = None


class TransitionIn(BaseModel):
    status: str
    reason: str = ""


class SplitIn(BaseModel):
    titles: list[str] = Field(min_length=1)


class ExecutionIn(BaseModel):
    status: str
    log: str = ""


class DiffIn(BaseModel):
    summary: str
    files: list[str] = Field(default_factory=list)


class TestIn(BaseModel):
    passed: int
    failed: int
    summary: str = ""


class ContractIn(BaseModel):
    acceptance: list[str]
    touches: list[str]


class ReviewIn(BaseModel):
    findings: str
    risk: str
    accepted: bool = False


class KnowledgeIn(BaseModel):
    kind: str
    title: str
    body: str
    source: str


def _mount_console(app: FastAPI) -> None:
    web = Path(__file__).resolve().parent / "web"

    @app.get("/", include_in_schema=False)
    def console_page():
        return FileResponse(web / "index.html")

    app.mount("/assets", StaticFiles(directory=web), name="assets")


def create_app(store: Store | None = None, workspace: Path | None = None) -> FastAPI:
    app = FastAPI(title="OpenDevMate", version="0.1.9")
    install(app)
    mount(app)
    _mount_console(app)
    app.state.store = store or Store(os.environ.get("OPENDEVMATE_DB", "opendevmate.sqlite3"))
    app.state.workspace = workspace or BASE

    def run(fn):
        try:
            return fn()
        except DomainError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/projects")
    def create_project(body: ProjectIn):
        return run(lambda: app.state.store.create_project(body.name, body.description, body.repo_url))

    @app.get("/api/projects")
    def list_projects():
        return app.state.store.list_projects()

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        return run(lambda: app.state.store.get_project(project_id))

    @app.post("/api/projects/{project_id}/scan")
    def scan(project_id: str, body: ScanIn):
        def action():
            payload = scan_directory(Path(body.root), app.state.workspace)
            return app.state.store.save_scan(project_id, payload)

        return run(action)

    @app.post("/api/projects/{project_id}/tasks")
    def create_task(project_id: str, body: TaskIn):
        return run(lambda: app.state.store.create_task(project_id, body.title, body.description, body.parent_id))

    @app.get("/api/projects/{project_id}/tasks")
    def list_tasks(project_id: str):
        return run(lambda: app.state.store.list_tasks(project_id))

    @app.post("/api/tasks/{task_id}/transition")
    def transition(task_id: str, body: TransitionIn):
        return run(lambda: app.state.store.transition(task_id, body.status, body.reason))

    @app.post("/api/tasks/{task_id}/split")
    def split(task_id: str, body: SplitIn):
        return run(lambda: app.state.store.split_task(task_id, body.titles))

    @app.get("/api/tasks/{task_id}/instruction")
    def instruction(task_id: str):
        def action():
            from opendevmate.service import build_instruction

            task = app.state.store.get_task(task_id)
            return {"instruction": build_instruction(app.state.store, task)}

        return run(action)

    @app.post("/api/tasks/{task_id}/executions")
    def execution(task_id: str, body: ExecutionIn):
        return run(lambda: app.state.store.add_execution(task_id, body.status, body.log))

    @app.post("/api/tasks/{task_id}/diffs")
    def diff(task_id: str, body: DiffIn):
        return run(lambda: app.state.store.add_diff(task_id, body.summary, body.files))

    @app.post("/api/tasks/{task_id}/tests")
    def tests(task_id: str, body: TestIn):
        return run(lambda: app.state.store.add_test_run(task_id, body.passed, body.failed, body.summary))

    @app.post("/api/tasks/{task_id}/contract")
    def contract(task_id: str, body: ContractIn):
        return run(lambda: app.state.store.set_contract(task_id, body.acceptance, body.touches))

    @app.get("/api/projects/{project_id}/conflicts")
    def conflicts(project_id: str):
        return run(lambda: app.state.store.conflicts(project_id))

    @app.post("/api/tasks/{task_id}/reviews")
    def review(task_id: str, body: ReviewIn):
        return run(lambda: app.state.store.add_review(task_id, body.findings, body.risk, body.accepted))

    @app.post("/api/projects/{project_id}/knowledge")
    def knowledge(project_id: str, body: KnowledgeIn):
        return run(
            lambda: app.state.store.add_knowledge(project_id, body.kind, body.title, body.body, body.source)
        )

    @app.get("/api/dashboard")
    def dashboard():
        return app.state.store.dashboard()

    @app.get("/dashboard")
    def dashboard_page():
        data = app.state.store.dashboard()
        locale = current_locale.get()
        rows = "".join(
            f"<tr><td>{html.escape(status)}</td><td>{count}</td></tr>"
            for status, count in data["tasks_by_status"].items()
        )
        lang = "en" if locale == "en" else "zh-CN"
        page = f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><title>OpenDevMate</title></head>
<body>
<h1>OpenDevMate</h1>
<p>{html.escape(text("dashboard.projects", locale))} {data['project_count']}，{html.escape(text("dashboard.tasks", locale))} {data['task_count']}，{html.escape(text("dashboard.executions", locale))} {data['execution_count']}，{html.escape(text("dashboard.failed", locale))} {data['failed_execution_count']}，{html.escape(text("dashboard.risks", locale))} {data['open_risk_count']}</p>
<table border="1"><tr><th>{html.escape(text("dashboard.status", locale))}</th><th>{html.escape(text("dashboard.count", locale))}</th></tr>{rows}</table>
</body></html>"""
        from fastapi.responses import HTMLResponse

        return HTMLResponse(page)

    return app


app = create_app()
