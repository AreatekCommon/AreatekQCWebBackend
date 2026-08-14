from fastapi import APIRouter

from app.api.camera import router as camera_router
from app.api.axis import router as axis_router
from app.api.health_api import router as health_router
from app.api.logs import router as logs_router
from app.api.markers import router as markers_router
from app.api.paths import router as paths_router
from app.api.pipeline import router as pipeline_router
from app.api.projects import router as projects_router
from app.api.settings import router as settings_router
from app.api.system import router as system_router
from app.api.trajectory import router as trajectory_router
from app.api.trajectory_files import router as trajectory_files_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(settings_router)
api_router.include_router(system_router)
api_router.include_router(logs_router)
api_router.include_router(camera_router)
api_router.include_router(axis_router)
api_router.include_router(trajectory_router)
api_router.include_router(trajectory_files_router)
api_router.include_router(markers_router)
api_router.include_router(paths_router)
api_router.include_router(projects_router)
api_router.include_router(pipeline_router)