from typing import Any, Literal



from pydantic import BaseModel, Field, model_validator



CycleRunMode = Literal["single_last_scan", "single_full", "repeat_on_success"]





class CalibrationSettings(BaseModel):

    big_range: int = Field(default=0, ge=0, le=1)

    factory_mode: int = Field(default=0, ge=0, le=1)

    read_xml_mode: int = Field(default=0, ge=0, le=1)





class PipelineSettings(BaseModel):

    import_markers: bool = Field(default=False)

    marker_framework_path: str = Field(default="")

    scan_folder_watcher_enabled: bool = Field(default=False)

    scan_import_monitored_folder: str = Field(default="")

    error_turntable_delay_sec: float = Field(default=0.5, ge=0.0)

    cycle_run_mode: CycleRunMode = Field(default="single_full")

    skip_failed_scans: bool = Field(default=False)

    calibration: CalibrationSettings = Field(default_factory=CalibrationSettings)



    @model_validator(mode="before")

    @classmethod

    def migrate_legacy_pipeline_fields(cls, data: Any) -> Any:

        if not isinstance(data, dict):

            return data

        migrated = dict(data)

        migrated.pop("turntable_position_mode", None)

        if "cycle_run_mode" in migrated:

            return migrated

        if migrated.get("stop_after_last_scan"):

            migrated["cycle_run_mode"] = "single_last_scan"

        return migrated



    @property

    def stop_after_last_scan(self) -> bool:

        return self.cycle_run_mode == "single_last_scan"

