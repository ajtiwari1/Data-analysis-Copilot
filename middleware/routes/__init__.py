from fastapi import APIRouter

from chat.routes import router as chat_router
from middleware.routes.analytics import router as analytics_router
from middleware.routes.auth import router as auth_router
from middleware.routes.dashboard import router as dashboard_router

router = APIRouter(prefix="/api")
router.include_router(analytics_router)
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(chat_router)

__all__ = ["router"]
