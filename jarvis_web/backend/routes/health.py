from fastapi import APIRouter

from jarvis_web.backend.models import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # Public endpoint is service liveness only. Real Core state/version belongs
    # behind authenticated /api/status and future protected control surfaces.
    return HealthResponse(status="ok")
