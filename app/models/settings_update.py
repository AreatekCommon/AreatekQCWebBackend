from pydantic import BaseModel, Field

from app.models.runtime_settings import RuntimeSettings


class SettingsUpdateRequest(BaseModel):
    settings: RuntimeSettings
    apply_section: str | None = Field(default=None)


class SdkApplyErrorDetail(BaseModel):
    command: str
    ret_code: int | None = None
    error_code_hex: str | None = None
    result: str | None = None
    message: str
    finish_json: str | None = None
    begin_json: str | None = None


class SettingsUpdateResponse(BaseModel):
    settings: RuntimeSettings
    apply_section: str | None = None
    applied: bool = True
    apply_error: str | None = None
    apply_error_detail: SdkApplyErrorDetail | None = None


class SettingsApplyResult(BaseModel):
    applied: bool = True
    apply_error: str | None = None
    apply_error_detail: SdkApplyErrorDetail | None = None

    @classmethod
    def success(cls) -> "SettingsApplyResult":
        return cls(applied=True)

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        detail: SdkApplyErrorDetail | None = None,
    ) -> "SettingsApplyResult":
        return cls(applied=False, apply_error=message, apply_error_detail=detail)

    @classmethod
    def from_sdk_error(cls, exc: Exception) -> "SettingsApplyResult":
        from q12_client import SdkCommandError

        if isinstance(exc, SdkCommandError):
            return cls.failure(str(exc), detail=SdkApplyErrorDetail(**exc.to_detail_dict()))
        return cls.failure(str(exc))
