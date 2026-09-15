from fastapi import APIRouter, Query, Request

from jarvis_web.backend.models import HistorySearchResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/search", response_model=HistorySearchResponse)
async def search_history(
    request: Request,
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=10, ge=1, le=25),
) -> HistorySearchResponse:
    hits = await request.app.state.history_service.search(q, limit=limit)
    return HistorySearchResponse(query=q, hits=hits)
