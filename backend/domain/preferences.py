"""用户明确编辑的长期偏好；低优先级参考，不自动改写本次旅行条件。"""

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.travel_request import Text, Transport


class PreferenceValues(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    interests: tuple[Text, ...] = Field(default=(), max_length=20)
    soft_constraints: tuple[Text, ...] = Field(default=(), max_length=20)
    transport: Transport | None = None


class Preferences(PreferenceValues):
    revision: int = Field(default=0, strict=True, ge=0)


class PreferenceVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)


class PreferencePatch(PreferenceVersion):
    set_fields: PreferenceValues = Field(alias="set")
