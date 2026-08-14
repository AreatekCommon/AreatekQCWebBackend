from fastapi import APIRouter, HTTPException

from app.core.runtime_settings_store import (
    get_runtime_settings,
    update_runtime_settings,
)
from app.models.runtime_settings import RuntimeSettings
from app.models.settings_update import SettingsUpdateRequest, SettingsUpdateResponse
from app.pipeline.service import pipeline_service
from app.scanner.project_name import suggest_project_name_counter
from app.settings_sections import ALL_SETTINGS_SECTIONS, SETTINGS_SECTION_SDK_PATHS

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=RuntimeSettings)
def read_settings() -> RuntimeSettings:
    return get_runtime_settings()


@router.put("", response_model=SettingsUpdateResponse)
def write_settings(payload: SettingsUpdateRequest) -> SettingsUpdateResponse:
    if payload.apply_section is not None and payload.apply_section not in ALL_SETTINGS_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown settings section: {payload.apply_section}",
        )

    previous = get_runtime_settings()
    settings = payload.settings
    if payload.apply_section == SETTINGS_SECTION_SDK_PATHS:
        suggested_counter = suggest_project_name_counter(settings.scanner)
        settings = settings.model_copy(
            update={
                "scanner": settings.scanner.model_copy(
                    update={"project_name_counter": suggested_counter}
                )
            }
        )
    saved = update_runtime_settings(settings)
    apply_result = pipeline_service.apply_settings_section(
        saved,
        previous,
        payload.apply_section,
    )
    return SettingsUpdateResponse(
        settings=saved,
        apply_section=payload.apply_section,
        applied=apply_result.applied,
        apply_error=apply_result.apply_error,
        apply_error_detail=apply_result.apply_error_detail,
    )