from fastapi import APIRouter, Request

from jarvis_web.backend.models import StatusResponse

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    adapter = request.app.state.core_adapter
    payload = await adapter.status()
    return StatusResponse(**payload)
