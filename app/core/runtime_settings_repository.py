from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.runtime_settings import RuntimeSettings

logger = logging.getLogger(__name__)

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = SERVER_ROOT / "data" / "runtime_settings.json"


def load_runtime_settings(path: Path = DEFAULT_SETTINGS_PATH) -> RuntimeSettings:
    if not path.exists():
        return RuntimeSettings()

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return RuntimeSettings.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to load runtime settings from %s: %s", path, exc)
        return RuntimeSettings()


def save_runtime_settings(
    settings: RuntimeSettings,
    path: Path = DEFAULT_SETTINGS_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")

    try:
        temp_path.write_text(
            json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
