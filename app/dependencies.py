from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket, status

from app.container import ApplicationContainer
from app.repositories import AuthUser
from security_guardrails import Actor


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container


def get_current_user(request: Request) -> AuthUser:
    user_id = request.session.get("user_id") or request.session.get("doctor_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = request.app.state.container.auth_repository.get_by_id(int(user_id))
    if user is None or not user.active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def actor_for_user(container: ApplicationContainer, user: AuthUser, current_patient_id: str = "") -> Actor:
    patient_ids = container.auth_repository.authorized_patient_ids(user)
    return Actor(
        actor_id=str(user.user_id),
        role=user.actor_role,
        authorized_patient_ids=patient_ids,
        current_patient_id=current_patient_id if current_patient_id in patient_ids else "",
    )


def websocket_user(websocket: WebSocket) -> AuthUser | None:
    user_id = websocket.session.get("user_id") or websocket.session.get("doctor_id")
    if not user_id:
        return None
    user = websocket.app.state.container.auth_repository.get_by_id(int(user_id))
    return user if user and user.active else None
