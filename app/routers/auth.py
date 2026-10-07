from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_current_user


router = APIRouter(tags=["authentication"])


class SignupRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)

    model_config = ConfigDict(extra="forbid")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    model_config = ConfigDict(extra="forbid")


def _public_user(user) -> dict:
    return {
        "id": user.user_id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role,
        "practitioner_id": user.practitioner_id,
    }


async def signup(payload: SignupRequest, request: Request):
    container = request.app.state.container
    try:
        user = container.auth_repository.create_doctor(payload.full_name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    container.audit_service.record(
        "user_created",
        actor_ref=f"doctor:{user.user_id}",
        action="signup",
        result="allow",
        request_id=getattr(request.state, "request_id", ""),
    )
    return {"doctor": _public_user(user), "user": _public_user(user)}


async def login(payload: LoginRequest, request: Request):
    container = request.app.state.container
    user = container.auth_repository.verify_credentials(payload.email, payload.password)
    if user is None:
        container.audit_service.record(
            "login_attempt",
            actor_ref="anonymous",
            action="login",
            result="deny",
            request_id=getattr(request.state, "request_id", ""),
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    request.session.clear()
    request.session["user_id"] = user.user_id
    request.session["doctor_id"] = user.user_id
    container.audit_service.record(
        "login_attempt",
        actor_ref=f"{user.actor_role}:{user.user_id}",
        action="login",
        result="allow",
        request_id=getattr(request.state, "request_id", ""),
    )
    return {"doctor": _public_user(user), "user": _public_user(user)}


async def logout(request: Request):
    user_id = request.session.get("user_id") or request.session.get("doctor_id")
    request.session.clear()
    if user_id:
        request.app.state.container.audit_service.record(
            "logout",
            actor_ref=f"user:{user_id}",
            action="logout",
            request_id=getattr(request.state, "request_id", ""),
        )
    return {"ok": True}


async def me(request: Request):
    return _public_user(get_current_user(request))


router.add_api_route("/api/auth/signup", signup, methods=["POST"])
router.add_api_route("/api/auth/login", login, methods=["POST"])
router.add_api_route("/api/auth/logout", logout, methods=["POST"])
router.add_api_route("/api/auth/me", me, methods=["GET"])

# Backward-compatible consultation API paths.
router.add_api_route("/api/consultation/signup", signup, methods=["POST"])
router.add_api_route("/api/consultation/login", login, methods=["POST"])
router.add_api_route("/api/consultation/logout", logout, methods=["POST"])
router.add_api_route("/api/consultation/me", me, methods=["GET"])
