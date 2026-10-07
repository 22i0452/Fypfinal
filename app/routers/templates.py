from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_container, get_current_user
from app.repositories import AuthUser


router = APIRouter(prefix="/api/templates", tags=["clinical-templates"])


@router.get("")
async def list_templates(
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    if user.actor_role != "doctor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor access required")
    templates = get_container(request).template_service.list_active()
    return {"templates": [item.model_dump(mode="json") for item in templates]}
