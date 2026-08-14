from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.exposure_migration import migrate_legacy_exposure_settings, strip_legacy_device_exposure


class ScannerDeviceParams(BaseModel):
    rgb_level: int = Field(default=14, ge=0)
    laser_switch: bool = Field(default=True)
    left_gain: float = Field(default=0.1, ge=0)
    right_gain: float = Field(default=0.1, ge=0)
    mask_enable: bool = Field(default=False)
    mask_val: int = Field(default=30, ge=0)
    pre_marker: bool = Field(default=True)


class ScannerExposureSettings(BaseModel):
    mode: Literal["auto", "first", "second", "third", "customized"] = "auto"
    customized_slots: Literal["first", "first_second", "all"] = "first"
    marker_exp: int = Field(default=8, ge=1, le=25)
    val1: int = Field(default=22, ge=1, le=60)
    val2: int = Field(default=1, ge=1, le=60)
    val3: int = Field(default=1, ge=1, le=60)


class ScannerScanParams(BaseModel):
    align_mod: int = Field(default=4, ge=0)
    scan_markers: bool = Field(default=True)
    scan_point_cloud: bool = Field(default=False)
    add_global_markers: bool = Field(default=True)
    monocular_scan: bool = Field(default=False)
    resolution: int = Field(default=2, ge=1, le=3)
    marker_radius: int = Field(default=7, ge=0)
    scan_obj: int = Field(default=2, ge=1, le=2)
    auto_cut_face: bool = Field(default=False)


class ScannerExposureRange(BaseModel):
    center_x: int = Field(default=1024, ge=0)
    center_y: int = Field(default=750, ge=0)
    radius: int = Field(default=100, ge=0)


class ScannerMeshParams(BaseModel):
    mesh_type: int = Field(default=0, ge=0)
    unwatertight_detail: int = Field(default=0, ge=0)
    depth: int = Field(default=0, ge=0)
    filter_level: int = Field(default=1, ge=0)
    smooth_level: int = Field(default=1, ge=0)
    remove_small: int = Field(default=1, ge=0)
    max_face: bool = Field(default=True)
    face_limit: int = Field(default=20_000_000, ge=0)
    fill_small_hole: bool = Field(default=True)
    small_hole_perimeter: int = Field(default=10, ge=0)
    neighbourhood: int = Field(default=3, ge=0)
    spike_sensitivity: bool = Field(default=True)
    fill_marker_hole: bool = Field(default=True)
    border_opt: bool = Field(default=True)
    need_thin_obj_mesh: bool = Field(default=False)


def _strip_legacy_device_exposure(device: dict[str, Any]) -> dict[str, Any]:
    return strip_legacy_device_exposure(device)


class ProjectNameTextPart(BaseModel):
    type: Literal["text"] = "text"
    value: str = ""


class ProjectNameIncrementPart(BaseModel):
    type: Literal["increment"] = "increment"
    width: int = Field(default=1, ge=1, le=8)


class ProjectNameTimestampPart(BaseModel):
    type: Literal["timestamp"] = "timestamp"
    format: Literal[
        "YYYYMMDD",
        "HHMMSS",
        "YYYYMMDD_HHMMSS",
        "YYYY-MM-DD",
        "DDMMYYYY",
    ] = "YYYYMMDD_HHMMSS"


ProjectNamePart = ProjectNameTextPart | ProjectNameIncrementPart | ProjectNameTimestampPart


class ProjectNameTemplate(BaseModel):
    parts: list[ProjectNamePart] = Field(default_factory=list)


class ScannerSettings(BaseModel):
    process_path: str = Field(
        default=r"C:\Program Files\OptimScan Q\Sn3DProcessManager.exe"
    )
    project_root: str = Field(default=r"C:\Shining Projects")
    export_root: str = Field(default=r"C:\Users\Areatek\Desktop\scans")
    project_name: ProjectNameTemplate = Field(default_factory=ProjectNameTemplate)
    project_name_counter: int = Field(default=1, ge=1)
    work_range: int = Field(default=1, ge=0)
    need_limit: int = Field(default=2, ge=0)
    save_type: str = Field(default="stl")
    run_global_opt: bool = Field(default=False)
    reapply_params_each_cycle: bool = Field(default=True)
    device: ScannerDeviceParams = Field(default_factory=ScannerDeviceParams)
    exposure_settings: ScannerExposureSettings = Field(
        default_factory=ScannerExposureSettings
    )
    scan: ScannerScanParams = Field(default_factory=ScannerScanParams)
    exposure_range: ScannerExposureRange = Field(default_factory=ScannerExposureRange)
    mesh: ScannerMeshParams = Field(default_factory=ScannerMeshParams)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_exposure(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        device = data.get("device")
        if not isinstance(device, dict):
            return data

        if data.get("exposure_settings") is None:
            data["exposure_settings"] = migrate_legacy_exposure_settings(
                exp_type=int(device.get("exp_type", 1)),
                marker_exp=int(device.get("marker_exp", 8)),
                val1=int(device.get("val1", 22)),
                val2=int(device.get("val2", 1)),
                val3=int(device.get("val3", 1)),
            )

        data["device"] = _strip_legacy_device_exposure(device)
        return data
