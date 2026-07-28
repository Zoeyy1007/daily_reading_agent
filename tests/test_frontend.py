from fastapi.testclient import TestClient

from app.main import app


def test_frontend_shell_and_assets_are_served() -> None:
    with TestClient(app) as client:
        page = client.get("/")
        styles = client.get("/static/styles.css")
        script = client.get("/static/app.js")

    assert page.status_code == 200
    assert "Daily Reading" in page.text
    assert 'id="navigation-drawer"' in page.text
    assert styles.status_code == 200
    assert ".reading-grid" in styles.text
    assert script.status_code == 200
    assert 'api("/daily-reading/today")' in script.text
    assert "feedback-reason" in script.text
