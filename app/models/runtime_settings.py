from typing import Literal

from pydantic import BaseModel, Field

from app.models.pipeline_settings import PipelineSettings
from app.models.scanner_settings import ScannerSettings


class RuntimeSettings(BaseModel):
    receiver_host: str = Field(default="0.0.0.0")
    receiver_port: int = Field(default=54610)
    sender_host: str = Field(default="127.0.0.1")
    sender_port: int = Field(default=54611)
    scanner_host: str = Field(default="127.0.0.1")
    scanner_port: int = Field(default=3001)
    robot_host: str = Field(default="192.168.0.5")
    robot_port: int = Field(default=54603)
    turntable_port: int = Field(default=54601)
    turntable_wire_format: Literal["integer", "decimal_2"] = Field(default="decimal_2")
    paths_folder: str = Field(
        default=r"C:\Users\Areatek\Desktop\AreatekQC\Server\data\Trajectories"
    )
    active_path_file: str = Field(default="sample_movement_path.json")
    log_to_console: bool = Field(default=True)
    log_to_file: bool = Field(default=True)
    log_level: str = Field(default="INFO")
    log_file_path: str = Field(default="logs/application.log")
    sdk_log_enabled: bool = Field(default=True)
    sdk_log_dir: str = Field(default="logs/sdk")
    sdk_native_log_source: str = Field(default="")
    sdk_tcp_log_to_console: bool = Field(default=False)
    camera_stream_enabled: bool = Field(default=True)
    camera_stream_host: str = Field(default="127.0.0.1")
    camera_stream_port: int = Field(default=3002)
    camera_stream_fps: int = Field(default=10, ge=1, le=30)
    poll_interval_ms: int = Field(default=2000)
    axis_forward_enabled: bool = Field(default=True)
    axis_forward_host: str = Field(default="192.168.40.154")
    axis_forward_port: int = Field(default=3400)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    scanner: ScannerSettings = Field(default_factory=ScannerSettings)