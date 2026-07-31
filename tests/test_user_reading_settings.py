from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.auth import _reading_settings, update_reading_settings
from app.config import Settings
from app.nodes.load_settings import load_settings_node
from app.schemas.auth import ReadingSettingsUpdate
from app.services.scoring_service import score_article


class FakeSession:
    def __init__(self, user: object) -> None:
        self.user = user
        self.commits = 0
        self.refreshes = 0

    def get(self, _model: object, _identifier: int) -> object:
        return self.user

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _value: object) -> None:
        self.refreshes += 1


def test_reading_setting_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        ReadingSettingsUpdate(
            daily_list_length=0,
            expected_reading_minutes_per_article=6,
        )
    with pytest.raises(ValidationError):
        ReadingSettingsUpdate(
            daily_list_length=11,
            expected_reading_minutes_per_article=6,
        )
    with pytest.raises(ValidationError):
        ReadingSettingsUpdate(
            daily_list_length=5,
            expected_reading_minutes_per_article=1,
        )
    with pytest.raises(ValidationError):
        ReadingSettingsUpdate(
            daily_list_length=5,
            expected_reading_minutes_per_article=26,
        )


def test_reading_settings_update_persists_and_derives_daily_budget() -> None:
    user = SimpleNamespace(
        daily_list_length=5,
        expected_reading_minutes_per_article=6,
    )
    session = FakeSession(user)

    result = update_reading_settings(
        ReadingSettingsUpdate(
            daily_list_length=7,
            expected_reading_minutes_per_article=4,
        ),
        session,  # type: ignore[arg-type]
        user,  # type: ignore[arg-type]
    )

    assert result.daily_list_length == 7
    assert result.expected_reading_minutes_per_article == 4
    assert result.total_daily_reading_minutes == 28
    assert session.commits == 1
    assert session.refreshes == 1
    assert _reading_settings(user).total_daily_reading_minutes == 28


def test_agent_loads_per_user_reading_targets() -> None:
    user = SimpleNamespace(
        daily_list_length=7,
        expected_reading_minutes_per_article=4,
    )
    session = FakeSession(user)

    result = load_settings_node(
        {"user_id": 18},  # type: ignore[arg-type]
        session,  # type: ignore[arg-type]
        Settings(_env_file=None),
    )

    assert result["target_article_count"] == 7
    assert result["target_article_reading_minutes"] == 4
    assert result["target_reading_minutes"] == 28


def test_expected_article_minutes_changes_length_fit() -> None:
    now = datetime.now(UTC)
    article = SimpleNamespace(
        word_count=900,
        source_id=1,
        title="Example",
        summary="",
        content_text="",
        published_at=now,
        discovered_at=now,
    )
    settings = Settings(
        _env_file=None,
        reading_words_per_minute=225,
        preferred_topics="",
        preferred_source_ids="",
    )

    exact = score_article(
        article,
        settings,
        now=now,
        expected_reading_minutes=4,
    )
    longer_target = score_article(
        article,
        settings,
        now=now,
        expected_reading_minutes=10,
    )

    assert exact.length == 10
    assert exact.length > longer_target.length


def test_scheduler_defaults_to_disabled_at_eight_am_pacific() -> None:
    settings = Settings(_env_file=None)

    assert settings.scheduler_enabled is False
    assert settings.daily_list_hour == 8
    assert settings.scheduler_timezone == "America/Los_Angeles"
