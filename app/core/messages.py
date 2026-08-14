from __future__ import annotations

AUTO_PARSED_TRAJECTORY_NAMES = {
    "en": "New trajectory.json",
    "ru": "Новая траектория.json",
}

MESSAGES = {
    "ru": {
        "app_started": "Backend-приложение запущено",
        "app_stopped": "Backend-приложение остановлено",
        "app_starting": "Запуск backend-приложения",
        "app_stopping": "Остановка backend-приложения",
        "lifespan_error": "Ошибка во время жизненного цикла backend-приложения",
        "unhandled_lifespan_error": "Необработанная ошибка жизненного цикла приложения",
        "root_message": "Backend работает",
    },
    "en": {
        "app_started": "Backend application started",
        "app_stopped": "Backend application stopped",
        "app_starting": "Starting backend application",
        "app_stopping": "Stopping backend application",
        "lifespan_error": "Backend application lifespan error",
        "unhandled_lifespan_error": "Unhandled application lifespan error",
        "root_message": "Backend is running",
    },
}

DEFAULT_LOCALE = "ru"


def auto_parsed_trajectory_filename(locale: str) -> str:
    return AUTO_PARSED_TRAJECTORY_NAMES.get(locale, AUTO_PARSED_TRAJECTORY_NAMES["ru"])


def tr(key: str, locale: str = DEFAULT_LOCALE) -> str:
    return MESSAGES.get(locale, MESSAGES[DEFAULT_LOCALE]).get(key, key)
