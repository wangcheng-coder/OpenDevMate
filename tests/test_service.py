from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opendevmate.api import create_app
from opendevmate.service import DomainError, Store, scan_directory


def test_task_flow_review_and_dashboard(tmp_path: Path):
    store = Store(str(tmp_path / "app.sqlite3"))
    project = store.create_project("demo", "管理一个示例仓库", "https://example.com/demo")
    store.add_knowledge(project["id"], "constraint", "不改无关模块", "只改任务点名的目录", "docs/decisions/0001")
    task = store.create_task(project["id"], "补扫描", "统计语言和顶层目录")
    children = store.split_task(task["id"], ["识别语言", "拒绝工作区外路径"])
    assert len(children) == 2
    assert children[0]["parent_id"] == task["id"]
    with pytest.raises(DomainError):
        store.transition(task["id"], "accepted")
    store.transition(task["id"], "ready")
    store.transition(task["id"], "running")
    execution = store.add_execution(task["id"], "recorded", "本地扫描完成")
    assert "不改无关模块" in execution["instruction"]
    store.add_diff(task["id"], "新增扫描", ["src/opendevmate/service.py"])
    store.add_test_run(task["id"], 3, 0, "pytest 通过")
    store.transition(task["id"], "review")
    with pytest.raises(DomainError):
        store.add_review(task["id"], "还有高风险", "high", True)
    with pytest.raises(DomainError):
        store.add_review(task["id"], "子任务还没完成", "low", True)
    for child in children:
        store.transition(child["id"], "ready")
        store.transition(child["id"], "running")
        store.transition(child["id"], "review")
        store.add_review(child["id"], "子任务完成", "low", True)
    store.add_review(task["id"], "范围正确，测试通过", "low", True)
    assert store.get_task(task["id"])["status"] == "accepted"
    board = store.dashboard()
    assert board["project_count"] == 1
    assert board["tasks_by_status"]["accepted"] == 3
    assert board["tasks_by_status"]["draft"] == 0


def test_scan_stays_inside_workspace(tmp_path: Path):
    base = tmp_path / "workspace"
    project = base / "sample"
    (project / "src").mkdir(parents=True)
    (project / "src" / "App.java").write_text("class App {}", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("secret", encoding="utf-8")
    report = scan_directory(project, base)
    assert report["languages"] == {"Java": 1}
    assert report["file_count"] == 1
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(DomainError):
        scan_directory(outside, base)
    nested = tmp_path / "target" / "workspace" / "sample"
    (nested / "src").mkdir(parents=True)
    (nested / "src" / "App.java").write_text("class App {}", encoding="utf-8")
    (nested / "target").mkdir()
    (nested / "target" / "Gen.java").write_text("class Gen {}", encoding="utf-8")
    nested_report = scan_directory(nested, tmp_path / "target" / "workspace")
    assert nested_report["file_count"] == 1


def test_api_project_and_dashboard(tmp_path: Path):
    app = create_app(Store(":memory:"), tmp_path)
    client = TestClient(app)
    created = client.post("/api/projects", json={"name": "demo", "description": "说明"}).json()
    denied = client.post("/api/projects", json={"name": " ", "description": " "})
    assert denied.status_code == 400
    task = client.post(f"/api/projects/{created['id']}/tasks", json={"title": "第一项"}).json()
    moved = client.post(f"/api/tasks/{task['id']}/transition", json={"status": "ready"})
    assert moved.status_code == 200
    assert client.get("/api/dashboard").json()["task_count"] == 1
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "OpenDevMate" in page.text
    blocked = client.post(
        f"/api/tasks/{task['id']}/transition",
        json={"status": "blocked"},
    )
    assert blocked.status_code == 400
    with_reason = client.post(
        f"/api/tasks/{task['id']}/transition",
        json={"status": "blocked", "reason": "等待接口说明"},
    )
    assert with_reason.status_code == 200
    assert with_reason.json()["block_reason"] == "等待接口说明"
