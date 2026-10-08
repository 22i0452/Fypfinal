from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware import Middleware

from app.config import Settings
from app.container import ApplicationContainer
from app.routers import (
    appointments,
    assistant,
    audio,
    auth,
    coding,
    consents,
    consultation,
    fhir,
    notes,
    patients,
    summaries,
    templates,
    verification,
    receptionist,
    receptionist_desk,
    workflows,
    workspace,
    demo_reports,
    attendance,
)


ROOT = Path(__file__).resolve().parents[1]


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()
    container = ApplicationContainer(configured)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        container.initialize()
        container.consultation_review.recover_interrupted()
        container.demo_report_service.recover_interrupted()
        yield
        container.demo_report_service.shutdown()

    application = FastAPI(title="MedFlowAI Clinic Platform", lifespan=lifespan)
    application.state.container = container
    application.add_middleware(
        SessionMiddleware,
        secret_key=configured.session_secret,
        session_cookie=configured.session_cookie_name,
        max_age=configured.session_max_age_seconds,
        same_site="lax",
        https_only=configured.secure_cookies,
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    application.mount("/assets", StaticFiles(directory=str(ROOT / "scribe" / "assets")), name="assets")
    application.mount(
        "/consultation/assets",
        StaticFiles(directory=str(ROOT / "consultation" / "assets")),
        name="consultation-assets",
    )
    application.mount(
        "/receptionist-static",
        StaticFiles(directory=str(ROOT / "receptionist" / "web")),
        name="receptionist-static",
    )
    application.include_router(auth.router)
    application.include_router(patients.router)
    application.include_router(workflows.router)
    application.include_router(verification.router)
    application.include_router(receptionist.router)
    application.include_router(receptionist_desk.router)
    application.include_router(appointments.router)
    application.include_router(attendance.router)
    application.include_router(consents.router)
    application.include_router(notes.router)
    application.include_router(summaries.router)
    application.include_router(templates.router)
    application.include_router(coding.router)
    application.include_router(fhir.router)
    application.include_router(consultation.router)
    application.include_router(assistant.router)
    application.include_router(audio.router)
    application.include_router(workspace.router)
    application.include_router(demo_reports.router)
    from app.routers.demo_deployment import router as demo_router
    application.include_router(demo_router)
    from app.services.demo_access import DemoAccessMiddleware
    # Session must be populated before the demo gate handles HTTP/WebSockets.
    # Insert the gate immediately inside SessionMiddleware.
    session_index = next(i for i, middleware in enumerate(application.user_middleware) if middleware.cls is SessionMiddleware)
    application.user_middleware.insert(session_index + 1, Middleware(
        DemoAccessMiddleware, settings=configured))
    return application


app = create_app()
