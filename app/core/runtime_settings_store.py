from app.core.runtime_settings_repository import load_runtime_settings, save_runtime_settings
from app.models.runtime_settings import RuntimeSettings
from app.scanner.constraints import is_markers_only_scan_mode, normalize_scanner_settings

_runtime_settings = load_runtime_settings()


def get_runtime_settings() -> RuntimeSettings:
    return _runtime_settings


def _normalize_runtime_settings(new_settings: RuntimeSettings) -> RuntimeSettings:
    scanner = normalize_scanner_settings(new_settings.scanner)
    pipeline = new_settings.pipeline
    if is_markers_only_scan_mode(scanner.scan):
        pipeline = pipeline.model_copy(update={"import_markers": False})
    return new_settings.model_copy(
        deep=True,
        update={"scanner": scanner, "pipeline": pipeline},
    )


def update_runtime_settings(new_settings: RuntimeSettings) -> RuntimeSettings:
    global _runtime_settings
    _runtime_settings = _normalize_runtime_settings(new_settings)
    save_runtime_settings(_runtime_settings)
    return _runtime_settings
