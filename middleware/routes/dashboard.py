from fastapi import APIRouter

from middleware.dependencies import CurrentUser
from middleware.schemas import DashboardResponse

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(user: CurrentUser) -> DashboardResponse:
    return DashboardResponse(message="You are signed in.", user=user)
