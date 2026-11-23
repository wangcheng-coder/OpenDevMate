from pathlib import Path

from fastapi.testclient import TestClient

from opendevmate.api import create_app
from opendevmate.service import Store


def test_console_uses_the_shared_shell(tmp_path: Path):
    client = TestClient(create_app(Store(":memory:"), tmp_path))
    page = client.get("/")
    assert page.status_code == 200
    assert 'data-shell="studio"' in page.text
    assert "OpenDevMate" in page.text
    style = client.get("/assets/console.css")
    assert style.status_code == 200
    assert "--ink" in style.text
