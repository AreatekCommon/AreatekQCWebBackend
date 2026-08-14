from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.models.scanner_settings import (
    ProjectNameIncrementPart,
    ProjectNameTemplate,
    ProjectNameTextPart,
    ProjectNameTimestampPart,
    ScannerSettings,
)

ProjectNameTimestampFormat = Literal[
    "YYYYMMDD",
    "HHMMSS",
    "YYYYMMDD_HHMMSS",
    "YYYY-MM-DD",
    "DDMMYYYY",
]

TIMESTAMP_FORMAT_PATTERNS: dict[str, str] = {
    "YYYYMMDD": "%Y%m%d",
    "HHMMSS": "%H%M%S",
    "YYYYMMDD_HHMMSS": "%Y%m%d_%H%M%S",
    "YYYY-MM-DD": "%Y-%m-%d",
    "DDMMYYYY": "%d%m%Y",
}

_LEGACY_FALLBACK_STRFTIME = "%Y%m%d_%H%M%S"
_SANITIZE_PATTERN = re.compile(r"[^\w.-]+")


def template_has_increment_part(template: ProjectNameTemplate) -> bool:
    return any(part.type == "increment" for part in template.parts)


def _render_part(
    part: ProjectNameTextPart | ProjectNameIncrementPart | ProjectNameTimestampPart,
    *,
    counter: int,
    now: datetime,
) -> str:
    if part.type == "text":
        return part.value.strip()
    if part.type == "increment":
        return str(counter).zfill(part.width)
    format_key = part.format
    pattern = TIMESTAMP_FORMAT_PATTERNS.get(format_key, "%Y%m%d_%H%M%S")
    return now.strftime(pattern)


def assemble_project_name(
    scanner: ScannerSettings,
    *,
    now: datetime | None = None,
) -> str:
    moment = now or datetime.now()
    template = scanner.project_name

    if not template.parts:
        return f"scan_{moment.strftime(_LEGACY_FALLBACK_STRFTIME)}"

    segments: list[str] = []
    for part in template.parts:
        rendered = _render_part(part, counter=scanner.project_name_counter, now=moment)
        if rendered:
            segments.append(rendered)

    if not segments:
        return f"scan_{moment.strftime(_LEGACY_FALLBACK_STRFTIME)}"

    sanitized = _SANITIZE_PATTERN.sub("_", "_".join(segments)).strip("_")
    return sanitized or f"scan_{moment.strftime(_LEGACY_FALLBACK_STRFTIME)}"


def advance_project_name_counter(scanner: ScannerSettings) -> ScannerSettings:
    if not template_has_increment_part(scanner.project_name):
        return scanner
    return scanner.model_copy(
        update={"project_name_counter": scanner.project_name_counter + 1}
    )


def _timestamp_regex(format_key: str) -> str:
    patterns = {
        "YYYYMMDD": r"\d{8}",
        "HHMMSS": r"\d{6}",
        "YYYYMMDD_HHMMSS": r"\d{8}_\d{6}",
        "YYYY-MM-DD": r"\d{4}-\d{2}-\d{2}",
        "DDMMYYYY": r"\d{8}",
    }
    return patterns.get(format_key, r"[\w-]+")


def _build_template_regex(template: ProjectNameTemplate) -> re.Pattern[str]:
    if not template.parts:
        return re.compile(r"^$")

    segments: list[str] = []
    for part in template.parts:
        if part.type == "text":
            rendered = part.value.strip()
            if rendered:
                segments.append(re.escape(rendered))
        elif part.type == "increment":
            segments.append(f"(?P<inc>\\d{{{part.width}}})")
        else:
            segments.append(_timestamp_regex(part.format))

    if not segments:
        return re.compile(r"^$")

    return re.compile("^" + "_".join(segments) + "$")


def suggest_project_name_counter(scanner: ScannerSettings) -> int:
    if not template_has_increment_part(scanner.project_name):
        return scanner.project_name_counter

    export_root = Path(scanner.export_root.strip())
    if not export_root.is_dir():
        return 1

    pattern = _build_template_regex(scanner.project_name)
    used: set[int] = set()
    try:
        for entry in export_root.iterdir():
            if not entry.is_dir() and not entry.is_file():
                continue
            match = pattern.match(entry.name)
            if not match:
                continue
            used.add(int(match.group("inc")))
    except OSError:
        return 1

    counter = 1
    while counter in used:
        counter += 1
    return counter
