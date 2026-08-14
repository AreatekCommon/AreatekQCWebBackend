import os

import uvicorn

from app.core.config import get_settings
from app.core.uvicorn_log_config import build_uvicorn_log_config


def main() -> None:
    settings = get_settings()
    reload_enabled = settings.debug and not os.environ.get("AREATEK_NO_RELOAD")

    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=reload_enabled,
        access_log=False,
        log_config=build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main()