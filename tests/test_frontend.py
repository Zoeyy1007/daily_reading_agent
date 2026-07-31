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
    assert 'id="logout-button"' in page.text
    assert styles.status_code == 200
    assert ".reading-grid" in styles.text
    assert script.status_code == 200
    assert 'api("/daily-reading/today")' in script.text
    assert 'api("/auth/me")' in script.text
    assert '"/auth/register"' in script.text
    assert "feedback-reason" in script.text
    assert 'href="#/scoring"' in page.text
    assert "Scoring System" in page.text
    assert 'href="#/settings"' in page.text
    assert "User Settings" in page.text
    assert 'api("/preferences/scoring")' in script.text
    assert 'api("/auth/password"' in script.text
    assert 'api("/auth/reading-settings")' in script.text
    assert "Articles per daily list" in script.text
    assert "Expected minutes per article" in script.text
    assert 'fetch("/analytics/events"' in script.text
    assert 'api("/analytics/summary?days=30")' in script.text
    assert "Approx. unique visitors" in script.text
    assert "one-way hash" in script.text
    assert "topic_politics" in script.text
