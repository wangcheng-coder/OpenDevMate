from pathlib import Path

import pytest

from opendevmate.service import DomainError, Store, import_github_issues, run_agent


def test_github_import_keeps_local_tasks_and_drops_token(tmp_path):
    store = Store(str(tmp_path / "app.sqlite3"))
    project = store.create_project("demo", "说明")
    local = store.create_task(project["id"], "本地任务", "不要覆盖")
    with pytest.raises(DomainError):
        import_github_issues(store, project["id"], [{"number": 7, "title": "远程"}], False)
    assert store.get_task(local["id"])["title"] == "本地任务"
    token = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    created = import_github_issues(store, project["id"], [{"number": 7, "title": "远程", "body": token}], True)
    again = import_github_issues(store, project["id"], [{"number": 7, "title": "远程改名"}], True)
    assert again == []
    assert created[0]["title"].startswith("[GitHub #7]")
    saved = store.list_tasks(project["id"])
    assert all(token not in (task["title"] + task["description"]) for task in saved)
    assert len(saved) == 2
    imported = import_github_issues(
        store,
        project["id"],
        [{"number": 12, "title": "十二"}, {"number": 1, "title": "一"}],
        True,
    )
    assert [item["title"] for item in imported] == ["[GitHub #12] 十二", "[GitHub #1] 一"]
    assert len(store.list_tasks(project["id"])) == 4


def test_agent_only_runs_inside_isolated_workspace(tmp_path):
    store = Store(str(tmp_path / "app.sqlite3"))
    project = store.create_project("demo", "说明")
    task = store.create_task(project["id"], "执行", "记录结果")
    store.transition(task["id"], "ready")
    base = tmp_path / "repo"
    workspace = base / "worktrees" / "agent"
    workspace.mkdir(parents=True)
    seen = []

    def runner(path):
        seen.append(path)
        return "完成"

    with pytest.raises(DomainError):
        run_agent(store, task["id"], base, base, runner)
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(DomainError):
        run_agent(store, task["id"], outside, base, runner)
    assert seen == []
    recorded = run_agent(store, task["id"], workspace, base, runner)
    assert seen == [workspace.resolve()]
    assert recorded["status"] == "recorded"
    assert store.get_task(task["id"])["status"] == "running"

    def fail(path):
        raise RuntimeError("执行失败")

    failed = run_agent(store, task["id"], workspace, base, fail)
    assert failed["status"] == "failed"
