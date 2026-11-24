"""项目、任务状态、扫描、执行记录和仪表盘。不调用外部 Agent。"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "target"}
LANGS = {
    ".java": "Java",
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".go": "Go",
    ".sql": "SQL",
    ".yml": "YAML",
    ".yaml": "YAML",
}
TRANSITIONS = {
    "draft": {"ready", "blocked"},
    "ready": {"running", "blocked"},
    "running": {"review", "blocked"},
    "review": {"accepted", "running", "blocked"},
    "blocked": {"ready"},
    "accepted": set(),
}
KNOWLEDGE_KINDS = {"spec", "decision", "constraint", "note"}
RISKS = {"info", "low", "medium", "high"}


class DomainError(ValueError):
    """调用方可以修正的业务错误。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
              repo_url TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT,
              title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, block_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS executions (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, instruction TEXT NOT NULL,
              status TEXT NOT NULL, log TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diffs (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, summary TEXT NOT NULL,
              files_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS test_runs (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, passed INTEGER NOT NULL,
              failed INTEGER NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL, findings TEXT NOT NULL,
              risk TEXT NOT NULL, accepted INTEGER NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL,
              title TEXT NOT NULL, body TEXT NOT NULL, source TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scans (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contracts (
              task_id TEXT PRIMARY KEY, acceptance_json TEXT NOT NULL, touches_json TEXT NOT NULL
            );
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(tasks)")}
        if "block_reason" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN block_reason TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

    def create_project(self, name: str, description: str, repo_url: str = "") -> dict:
        name = name.strip()
        description = description.strip()
        if not name or not description:
            raise DomainError("项目名称和说明都不能为空")
        row = {"id": _id(), "name": name, "description": description, "repo_url": repo_url.strip(), "created_at": _now()}
        self.conn.execute(
            "INSERT INTO projects VALUES (:id,:name,:description,:repo_url,:created_at)", row
        )
        self.conn.commit()
        return row

    def list_projects(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM projects ORDER BY created_at")]

    def get_project(self, project_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise DomainError("项目不存在")
        return dict(row)

    def create_task(self, project_id: str, title: str, description: str, parent_id: str | None = None) -> dict:
        self.get_project(project_id)
        title = title.strip()
        if not title:
            raise DomainError("任务标题不能为空")
        if parent_id:
            parent = self.get_task(parent_id)
            if parent["project_id"] != project_id:
                raise DomainError("子任务必须属于同一个项目")
        row = {
            "id": _id(),
            "project_id": project_id,
            "parent_id": parent_id,
            "title": title,
            "description": description.strip(),
            "status": "draft",
            "created_at": _now(),
        }
        self.conn.execute(
            "INSERT INTO tasks (id,project_id,parent_id,title,description,status,created_at) VALUES (:id,:project_id,:parent_id,:title,:description,:status,:created_at)",
            row,
        )
        self.conn.commit()
        return row

    def list_tasks(self, project_id: str | None = None) -> list[dict]:
        if project_id:
            rows = self.conn.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY created_at", (project_id,))
        else:
            rows = self.conn.execute("SELECT * FROM tasks ORDER BY created_at")
        return [dict(r) for r in rows]

    def get_task(self, task_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("任务不存在")
        return dict(row)

    def transition(self, task_id: str, status: str, reason: str = "") -> dict:
        task = self.get_task(task_id)
        if status not in TRANSITIONS.get(task["status"], set()):
            raise DomainError(f"不能从 {task['status']} 改为 {status}")
        if status == "running":
            self._ensure_no_overlap(task)
        if status == "blocked" and not str(reason).strip():
            raise DomainError("阻塞要写明原因")
        block_reason = str(reason).strip() if status == "blocked" else ""
        self.conn.execute(
            "UPDATE tasks SET status=?, block_reason=? WHERE id=?",
            (status, block_reason, task_id),
        )
        self.conn.commit()
        return self.get_task(task_id)

    def split_task(self, task_id: str, titles: list[str]) -> list[dict]:
        parent = self.get_task(task_id)
        if parent["status"] == "accepted":
            raise DomainError("已验收的任务不能再拆分")
        cleaned = [t.strip() for t in titles if t and t.strip()]
        if not cleaned:
            raise DomainError("至少要有一个子任务标题")
        return [self.create_task(parent["project_id"], title, "", parent["id"]) for title in cleaned]

    def add_knowledge(self, project_id: str, kind: str, title: str, body: str, source: str) -> dict:
        self.get_project(project_id)
        if kind not in KNOWLEDGE_KINDS:
            raise DomainError("知识类型必须是 spec、decision、constraint 或 note")
        if not title.strip() or not body.strip() or not source.strip():
            raise DomainError("知识要有标题、正文和来源")
        row = {
            "id": _id(),
            "project_id": project_id,
            "kind": kind,
            "title": title.strip(),
            "body": body.strip(),
            "source": source.strip(),
            "created_at": _now(),
        }
        self.conn.execute(
            "INSERT INTO knowledge VALUES (:id,:project_id,:kind,:title,:body,:source,:created_at)", row
        )
        self.conn.commit()
        return row

    def list_knowledge(self, project_id: str) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM knowledge WHERE project_id=? ORDER BY created_at", (project_id,))
        return [dict(r) for r in rows]

    def save_scan(self, project_id: str, payload: dict) -> dict:
        self.get_project(project_id)
        row = {"id": _id(), "project_id": project_id, "payload_json": json.dumps(payload, ensure_ascii=False), "created_at": _now()}
        self.conn.execute("INSERT INTO scans VALUES (:id,:project_id,:payload_json,:created_at)", row)
        self.conn.commit()
        row["payload"] = payload
        return row

    def latest_scan(self, project_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM scans WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["payload"] = json.loads(data.pop("payload_json"))
        return data

    def add_execution(self, task_id: str, status: str, log: str) -> dict:
        task = self.get_task(task_id)
        if task["status"] not in {"ready", "running", "review"}:
            raise DomainError("只有 ready、running 或 review 的任务可以记执行记录")
        if status not in {"recorded", "failed"}:
            raise DomainError("执行状态只能是 recorded 或 failed")
        instruction = build_instruction(self, task)
        row = {
            "id": _id(),
            "task_id": task_id,
            "instruction": instruction,
            "status": status,
            "log": log.strip(),
            "created_at": _now(),
        }
        self.conn.execute(
            "INSERT INTO executions VALUES (:id,:task_id,:instruction,:status,:log,:created_at)", row
        )
        self.conn.commit()
        return row

    def add_diff(self, task_id: str, summary: str, files: list[str]) -> dict:
        task = self.get_task(task_id)
        if task["status"] not in {"running", "review"}:
            raise DomainError("只有执行中或审查中的任务可以记 Diff")
        if not summary.strip():
            raise DomainError("Diff 摘要不能为空")
        cleaned = []
        for item in files:
            path = str(item).strip().replace("\\", "/")
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise DomainError("Diff 路径必须是工作区内的相对路径")
            if _sensitive(path):
                raise DomainError("Diff 不能记录密钥或 Git 文件")
            cleaned.append(path)
        row = {
            "id": _id(),
            "task_id": task_id,
            "summary": summary.strip(),
            "files_json": json.dumps(cleaned, ensure_ascii=False),
            "created_at": _now(),
        }
        self.conn.execute("INSERT INTO diffs VALUES (:id,:task_id,:summary,:files_json,:created_at)", row)
        self.conn.commit()
        row["files"] = cleaned
        return row

    def add_test_run(self, task_id: str, passed: int, failed: int, summary: str) -> dict:
        task = self.get_task(task_id)
        if task["status"] not in {"running", "review"}:
            raise DomainError("只有执行中或审查中的任务可以记测试")
        if passed < 0 or failed < 0:
            raise DomainError("测试数量不能为负")
        row = {
            "id": _id(),
            "task_id": task_id,
            "passed": passed,
            "failed": failed,
            "summary": summary.strip(),
            "created_at": _now(),
        }
        self.conn.execute(
            "INSERT INTO test_runs VALUES (:id,:task_id,:passed,:failed,:summary,:created_at)", row
        )
        self.conn.commit()
        return row

    def add_review(self, task_id: str, findings: str, risk: str, accepted: bool) -> dict:
        task = self.get_task(task_id)
        if task["status"] != "review":
            raise DomainError("只有审查中的任务可以记审查结论")
        if risk not in RISKS:
            raise DomainError("风险必须是 info、low、medium 或 high")
        if not findings.strip():
            raise DomainError("审查结论不能为空")
        if accepted and risk == "high":
            raise DomainError("高风险审查不能直接验收")
        if accepted:
            open_children = self.conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE parent_id=? AND status!='accepted'", (task_id,)
            ).fetchone()[0]
            if open_children:
                raise DomainError("还有子任务没有验收")
            self._enforce_contract(task_id)
        row = {
            "id": _id(),
            "task_id": task_id,
            "findings": findings.strip(),
            "risk": risk,
            "accepted": 1 if accepted else 0,
            "created_at": _now(),
        }
        self.conn.execute(
            "INSERT INTO reviews VALUES (:id,:task_id,:findings,:risk,:accepted,:created_at)", row
        )
        if accepted:
            self.conn.execute("UPDATE tasks SET status='accepted' WHERE id=?", (task_id,))
        self.conn.commit()
        return row

    def set_contract(self, task_id: str, acceptance: list[str], touches: list[str]) -> dict:
        """验收标准和允许改动的路径。没有这份约定时，仍按原来的审查流程验收。"""
        self.get_task(task_id)
        criteria = [item.strip() for item in acceptance if item and str(item).strip()]
        paths = []
        for item in touches:
            path = str(item).strip().replace("\\", "/")
            if not path or path.startswith("/") or ".." in path.split("/"):
                raise DomainError("改动范围必须是相对路径，不能包含 ..")
            if _sensitive(path):
                raise DomainError("改动范围不能包含密钥文件或 Git 目录")
            paths.append(path)
        if not criteria or not paths:
            raise DomainError("验收需要至少一条标准和一个改动范围")
        self.conn.execute(
            """
            INSERT INTO contracts (task_id, acceptance_json, touches_json)
            VALUES (?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
              acceptance_json=excluded.acceptance_json,
              touches_json=excluded.touches_json
            """,
            (task_id, json.dumps(criteria, ensure_ascii=False), json.dumps(paths, ensure_ascii=False)),
        )
        self.conn.commit()
        return {"acceptance": criteria, "touches": paths}

    def conflicts(self, project_id: str) -> list[dict]:
        """列出仍在进行、且声明路径重叠的任务。没有约定的任务不参与比较。"""
        self.get_project(project_id)
        active = [
            task
            for task in self.list_tasks(project_id)
            if task["status"] in {"ready", "running", "review"}
        ]
        found = []
        for index, left in enumerate(active):
            left_contract = self.get_contract(left["id"])
            if left_contract is None:
                continue
            for right in active[index + 1 :]:
                right_contract = self.get_contract(right["id"])
                if right_contract and _ranges_overlap(left_contract["touches"], right_contract["touches"]):
                    found.append({"tasks": [left["id"], right["id"]], "status": "overlap"})
        return found

    def _ensure_no_overlap(self, task: dict) -> None:
        contract = self.get_contract(task["id"])
        if contract is None:
            return
        for other in self.list_tasks(task["project_id"]):
            if other["id"] == task["id"] or other["status"] not in {"running", "review"}:
                continue
            other_contract = self.get_contract(other["id"])
            if other_contract and _ranges_overlap(contract["touches"], other_contract["touches"]):
                raise DomainError("改动范围与正在执行的任务重叠")

    def get_contract(self, task_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM contracts WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        return {
            "acceptance": json.loads(row["acceptance_json"]),
            "touches": json.loads(row["touches_json"]),
        }

    def _enforce_contract(self, task_id: str) -> None:
        contract = self.get_contract(task_id)
        if contract is None:
            return
        diffs = self.conn.execute(
            "SELECT files_json FROM diffs WHERE task_id=? ORDER BY created_at", (task_id,)
        ).fetchall()
        files = [path for diff in diffs for path in json.loads(diff["files_json"])]
        if not files:
            raise DomainError("写了验收范围时，必须先记录 Diff")
        sensitive = [path for path in files if _sensitive(path)]
        if sensitive:
            raise DomainError("Diff 包含密钥或 Git 文件，不能验收")
        outside = [path for path in files if not _within(path, contract["touches"])]
        if outside:
            raise DomainError("Diff 超出声明的改动范围")
        tests = self.conn.execute(
            "SELECT failed FROM test_runs WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)
        ).fetchone()
        if tests is None or tests["failed"] != 0:
            raise DomainError("最近一次测试还有失败，不能验收")

    def dashboard(self) -> dict:
        projects = self.list_projects()
        tasks = self.list_tasks()
        by_status = {name: 0 for name in TRANSITIONS}
        for task in tasks:
            by_status[task["status"]] = by_status.get(task["status"], 0) + 1
        executions = self.conn.execute("SELECT COUNT(*) FROM executions").fetchone()[0]
        failed = self.conn.execute("SELECT COUNT(*) FROM executions WHERE status='failed'").fetchone()[0]
        open_risks = self.conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE accepted=0 AND risk IN ('medium','high')"
        ).fetchone()[0]
        blocked = [
            {"id": task["id"], "title": task["title"], "reason": task.get("block_reason") or ""}
            for task in tasks
            if task["status"] == "blocked"
        ]
        return {
            "project_count": len(projects),
            "task_count": len(tasks),
            "tasks_by_status": by_status,
            "execution_count": executions,
            "failed_execution_count": failed,
            "open_risk_count": open_risks,
            "blocked_tasks": blocked,
        }


def scan_directory(root: Path, base: Path, limit: int = 5000) -> dict:
    root = root.resolve()
    base = base.resolve()
    if not root.is_relative_to(base):
        raise DomainError("扫描路径必须位于允许的工作区之内")
    if not root.is_dir():
        raise DomainError("扫描路径不是目录")
    languages: dict[str, int] = {}
    modules: dict[str, int] = {}
    files = 0
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file():
            continue
        files += 1
        if files > limit:
            raise DomainError(f"文件数超过 {limit}，请缩小扫描目录")
        lang = LANGS.get(path.suffix.lower())
        if lang:
            languages[lang] = languages.get(lang, 0) + 1
        relative = path.relative_to(root)
        top = relative.parts[0] if len(relative.parts) > 1 else "(root)"
        modules[top] = modules.get(top, 0) + 1
    return {
        "root": str(root),
        "file_count": files,
        "languages": dict(sorted(languages.items())),
        "modules": dict(sorted(modules.items())),
    }


def build_instruction(store: Store, task: dict) -> str:
    project = store.get_project(task["project_id"])
    knowledge = store.list_knowledge(task["project_id"])
    constraints = [item for item in knowledge if item["kind"] in {"constraint", "decision", "spec"}]
    lines = [
        f"项目：{project['name']}",
        f"说明：{project['description']}",
        f"任务：{task['title']}",
        f"任务说明：{task['description'] or '无'}",
        "要求：人负责验收。不要改无关代码，不要提交密钥。完成后写明改了什么、怎么测试。",
    ]
    if constraints:
        lines.append("项目知识：")
        for item in constraints:
            lines.append(f"- [{item['kind']}] {item['title']}（来源 {item['source']}）：{item['body']}")
    contract = store.get_contract(task["id"])
    if contract:
        lines.append("验收标准：")
        for item in contract["acceptance"]:
            lines.append(f"- {item}")
        lines.append("只允许改动这些路径：" + ", ".join(contract["touches"]))
    return "\n".join(lines)


def _sensitive(path: str) -> bool:
    normal = path.replace("\\", "/")
    name = normal.split("/")[-1]
    return (
        name in {".env", ".git", "id_rsa"}
        or name.endswith((".pem", ".key"))
        or "/.git/" in f"/{normal}/"
        or normal.startswith(".git/")
    )


def _repo_path(path: str) -> str:
    normal = path.replace("\\", "/")
    while normal.startswith("./"):
        normal = normal[2:]
    return normal


def _ranges_overlap(left: list[str], right: list[str]) -> bool:
    for one in left:
        one_path = _repo_path(one).rstrip("/")
        for other in right:
            other_path = _repo_path(other).rstrip("/")
            if one_path == other_path or one_path.startswith(other_path + "/") or other_path.startswith(one_path + "/"):
                return True
    return False


def _within(path: str, touches: list[str]) -> bool:
    normal = _repo_path(path)
    for touch in touches:
        prefix = _repo_path(touch).rstrip("/")
        if normal == prefix or normal.startswith(prefix + "/"):
            return True
    return False


def import_github_issues(store: Store, project_id: str, issues: list[dict], token_present: bool) -> list[dict]:
    """导入 GitHub Issue。没有 Token 时不访问外部服务，也不覆盖本地任务。"""
    if not token_present:
        raise DomainError("没有 Token，本地任务仍可使用")
    existing = store.list_tasks(project_id)
    created = []
    for issue in issues:
        number = int(issue["number"])
        marker = f"github:{number}"
        if any((task["description"] or "").split("\n", 1)[0] == marker for task in existing):
            continue
        title = _redact_secrets(f"[GitHub #{number}] {str(issue.get('title') or '').strip()}")
        body = _redact_secrets(str(issue.get("body") or ""))
        task = store.create_task(project_id, title, f"{marker}\n{body}")
        created.append(task)
        existing.append(task)
    return created


def run_agent(store: Store, task_id: str, workspace: Path, base: Path, runner) -> dict:
    """只允许在独立工作区里调用执行器，不直接使用默认工作区。"""
    workspace = workspace.resolve()
    base = base.resolve()
    if not workspace.is_relative_to(base) or workspace == base:
        raise DomainError("执行目录必须是独立工作区，不能使用默认工作区或其外部路径")
    task = store.get_task(task_id)
    if task["status"] == "ready":
        store.transition(task_id, "running")
    try:
        log = str(runner(workspace))
        status = "recorded"
    except Exception as exc:
        log = str(exc)
        status = "failed"
    return store.add_execution(task_id, status, log)


def _redact_secrets(text: str) -> str:
    text = re.sub(r"ghp_[A-Za-z0-9]{20,}", "[REDACTED_TOKEN]", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]+", "[REDACTED_TOKEN]", text)
    return text
