from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class AuthCredentials(BaseModel):
    login_id: str = Field(min_length=2, max_length=64)
    password: SecretStr = Field(min_length=6, max_length=256)

    @field_validator("login_id", mode="before")
    @classmethod
    def validate_login_id(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if any(character.isspace() for character in stripped):
            raise ValueError("User ID cannot contain spaces")
        return stripped


class PasswordChange(BaseModel):
    current_password: SecretStr = Field(min_length=6, max_length=256)
    new_password: SecretStr = Field(min_length=6, max_length=256)


class ReadingSettingsUpdate(BaseModel):
    daily_list_length: int = Field(ge=1, le=10)
    expected_reading_minutes_per_article: int = Field(ge=2, le=25)


class ReadingSettingsRead(ReadingSettingsUpdate):
    total_daily_reading_minutes: int


class AuthUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login_id: str
    display_name: str
    created_at: datetime
