import pytest

from opendevmate.service import DomainError, Store


def _ready(store, task_id):
    store.transition(task_id, "ready")
    store.transition(task_id, "running")


def test_contract_blocks_out_of_scope_and_failed_tests():
    store = Store(":memory:")
    project = store.create_project("demo", "管理一个示例仓库")
    task = store.create_task(project["id"], "改扫描", "只改 src")
    with pytest.raises(DomainError):
        store.set_contract(task["id"], [], ["src"])
    with pytest.raises(DomainError):
        store.set_contract(task["id"], ["pytest 通过"], ["../secret"])
    store.set_contract(task["id"], ["pytest 通过"], ["src"])
    _ready(store, task["id"])
    store.add_diff(task["id"], "越界", ["README.md"])
    store.add_test_run(task["id"], 1, 0, "通过")
    store.transition(task["id"], "review")
    with pytest.raises(DomainError):
        store.add_review(task["id"], "范围看起来没问题", "low", True)
    store.transition(task["id"], "blocked", "diff 超出约定范围")

    other = store.create_task(project["id"], "补测试", "只改 src")
    store.set_contract(other["id"], ["pytest 通过"], ["src"])
    _ready(store, other["id"])
    store.add_diff(other["id"], "范围内", ["src/app.py"])
    store.add_test_run(other["id"], 1, 1, "还有失败")
    store.transition(other["id"], "review")
    with pytest.raises(DomainError):
        store.add_review(other["id"], "测试还没绿", "low", True)
    store.transition(other["id"], "blocked", "测试还没有通过")

    third = store.create_task(project["id"], "收尾", "只改 src")
    store.set_contract(third["id"], ["pytest 通过"], ["src"])
    _ready(store, third["id"])
    recorded = store.add_execution(third["id"], "recorded", "完成")
    assert "pytest 通过" in recorded["instruction"]
    assert "src" in recorded["instruction"]
    store.add_diff(third["id"], "范围内", ["src/app.py"])
    store.add_test_run(third["id"], 2, 0, "通过")
    store.transition(third["id"], "review")
    store.add_review(third["id"], "范围和测试都符合约定", "low", True)
    assert store.get_task(third["id"])["status"] == "accepted"


def test_overlapping_running_tasks_are_rejected():
    from fastapi.testclient import TestClient
    from opendevmate.api import create_app

    store = Store(":memory:")
    project = store.create_project("demo", "管理一个示例仓库")
    left = store.create_task(project["id"], "改服务", "src")
    right = store.create_task(project["id"], "改接口", "src/api")
    store.set_contract(left["id"], ["测试通过"], ["src"])
    store.set_contract(right["id"], ["测试通过"], ["src/api"])
    assert store.conflicts(project["id"]) == []
    store.transition(left["id"], "ready")
    store.transition(right["id"], "ready")
    assert len(store.conflicts(project["id"])) == 1
    store.transition(left["id"], "running")
    with pytest.raises(DomainError):
        store.transition(right["id"], "running")
    other = store.create_task(project["id"], "改文档", "docs")
    store.set_contract(other["id"], ["文档更新"], ["docs"])
    store.transition(other["id"], "ready")
    assert store.transition(other["id"], "running")["status"] == "running"

    client = TestClient(create_app(store, workspace=None))
    listed = client.get(f"/api/projects/{project['id']}/conflicts")
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "overlap"


def test_diff_rejects_secret_and_parent_paths():
    store = Store(":memory:")
    project = store.create_project("demo", "管理一个示例仓库")
    task = store.create_task(project["id"], "改代码", "src")
    store.transition(task["id"], "ready")
    store.transition(task["id"], "running")
    with pytest.raises(DomainError):
        store.add_diff(task["id"], "密钥", [".env"])
    with pytest.raises(DomainError):
        store.add_diff(task["id"], "越界", ["../outside.py"])
    saved = store.add_diff(task["id"], "范围内", ["src/app.py"])
    assert saved["files"] == ["src/app.py"]


def test_dot_directory_matches_only_the_declared_prefix():
    store = Store(":memory:")
    project = store.create_project("demo", "管理一个示例仓库")
    task = store.create_task(project["id"], "改工作流", ".github")
    store.set_contract(task["id"], ["ci 通过"], [".github"])
    _ready(store, task["id"])
    store.add_diff(task["id"], "工作流", [".github/workflows/ci.yml"])
    store.add_test_run(task["id"], 1, 0, "通过")
    store.transition(task["id"], "review")
    store.add_review(task["id"], "范围符合", "low", True)
    assert store.get_task(task["id"])["status"] == "accepted"

    other = store.create_task(project["id"], "误匹配", "github")
    store.set_contract(other["id"], ["ci 通过"], ["github"])
    _ready(store, other["id"])
    store.add_diff(other["id"], "工作流", [".github/workflows/ci.yml"])
    store.add_test_run(other["id"], 1, 0, "通过")
    store.transition(other["id"], "review")
    with pytest.raises(DomainError):
        store.add_review(other["id"], "范围不符合", "low", True)
