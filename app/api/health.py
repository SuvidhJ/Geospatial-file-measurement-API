from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_settings
from app.config import Settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {"status": "ok", "queue": "redis" if settings.redis_url else "in-process"}
