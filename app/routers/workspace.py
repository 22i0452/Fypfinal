from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse


ROOT = Path(__file__).resolve().parents[2]
CONSULTATION_DIR = ROOT / "consultation"
MODULE2_DIR = ROOT / "scribe"

router = APIRouter(tags=["workspace"])


def _authenticated(request: Request) -> bool:
    return bool(request.session.get("user_id") or request.session.get("doctor_id"))


@router.get("/")
async def root(request: Request):
    destination = "/workspace" if _authenticated(request) else "/consultation/login"
    return RedirectResponse(destination, status_code=302)


@router.get("/consultation")
async def consultation_root(request: Request):
    destination = "/workspace" if _authenticated(request) else "/consultation/login"
    return RedirectResponse(destination, status_code=302)


@router.get("/consultation/login")
async def login_page(request: Request):
    if _authenticated(request):
        return RedirectResponse("/workspace", status_code=302)
    return FileResponse(CONSULTATION_DIR / "login.html", media_type="text/html")


@router.get("/consultation/dashboard")
async def legacy_dashboard(request: Request):
    if not _authenticated(request):
        return RedirectResponse("/consultation/login", status_code=302)
    return RedirectResponse("/workspace", status_code=302)


@router.get("/consultation/patient/{patient_ref:path}")
async def legacy_patient_page(patient_ref: str, request: Request):
    if not _authenticated(request):
        return RedirectResponse("/consultation/login", status_code=302)
    return RedirectResponse(f"/workspace?patient_ref={patient_ref}", status_code=302)


@router.get("/workspace")
async def workspace(request: Request):
    if not _authenticated(request):
        return RedirectResponse("/consultation/login", status_code=302)
    return FileResponse(MODULE2_DIR / "index.html", media_type="text/html")


@router.get("/module2")
async def module2_alias(request: Request):
    if not _authenticated(request):
        return RedirectResponse("/consultation/login", status_code=302)
    return RedirectResponse("/workspace", status_code=302)


@router.get("/branding/logo")
async def brand_logo():
    candidates = [
        ROOT / "assets" / "branding" / "MedflowAI_Logo.jpg",
        CONSULTATION_DIR / "assets" / "medflow-logo.svg",
    ]
    for candidate in candidates:
        if candidate.exists():
            return FileResponse(candidate)
    return FileResponse(ROOT / "assets" / "branding" / "MedflowAI_Icon.png")


@router.get("/branding/icon")
async def brand_icon():
    return FileResponse(ROOT / "assets" / "branding" / "MedflowAI_Icon.png")
