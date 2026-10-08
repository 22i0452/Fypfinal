from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict

from app.dependencies import get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services.demo_report_service import DemoReportError

router=APIRouter(tags=['demo-testing'])
ROOT=Path(__file__).resolve().parents[2]


class StartReport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode: Literal['synthetic','live_text']='synthetic'
    confirm_live: bool=False


def mutation_guard(request):
    origin=request.headers.get('origin')
    if request.headers.get('sec-fetch-site')=='cross-site' or (origin and urlsplit(origin).netloc!=request.url.netloc):
        raise HTTPException(403,'Cross-site test actions are not allowed.')
    if request.headers.get('content-type','').split(';')[0]!='application/json':
        raise HTTPException(415,'Use application/json for test actions.')


def service(request,user):
    if user.actor_role!='doctor':raise HTTPException(403,'Doctor access is required.')
    result=get_container(request).demo_report_service
    if not result.settings.demo_testing_enabled:raise HTTPException(503,'Demo testing is disabled for this deployment.')
    return result


@router.get('/testing')
async def testing_page(request:Request):
    if not (request.session.get('user_id') or request.session.get('doctor_id')):
        return RedirectResponse('/consultation/login?next=/testing',status_code=302)
    return FileResponse(ROOT/'scribe/testing.html',media_type='text/html')


@router.get('/api/demo-testing/configuration')
async def configuration(request:Request,user:AuthUser=Depends(get_current_user)):
    return service(request,user).capabilities()


@router.get('/api/demo-testing/runs')
async def list_runs(request:Request,user:AuthUser=Depends(get_current_user)):
    return {'runs':service(request,user).list(user.user_id)}


@router.post('/api/demo-testing/runs',status_code=202)
async def start_run(payload:StartReport,request:Request,user:AuthUser=Depends(get_current_user)):
    mutation_guard(request)
    try:return service(request,user).start(user.user_id,payload.mode,payload.confirm_live)
    except DemoReportError as exc:raise service_http_error(exc) from exc


@router.get('/api/demo-testing/runs/{run_id}')
async def get_run(run_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    try:return service(request,user).get(run_id,user.user_id)
    except DemoReportError as exc:raise service_http_error(exc) from exc


@router.post('/api/demo-testing/runs/{run_id}/cancel')
async def cancel_run(run_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    mutation_guard(request)
    try:return service(request,user).cancel(run_id,user.user_id)
    except DemoReportError as exc:raise service_http_error(exc) from exc


@router.get('/api/demo-testing/runs/{run_id}/export')
async def export_run(run_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    try:report=service(request,user).get(run_id,user.user_id)
    except DemoReportError as exc:raise service_http_error(exc) from exc
    return JSONResponse(report,headers={'Content-Disposition':f'attachment; filename="medflow-test-{report["run_id"]}.json"','Cache-Control':'no-store'})


@router.get('/api/demo-testing/runs/{run_id}/export.pdf')
async def export_pdf(run_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    try:report=service(request,user).get(run_id,user.user_id)
    except DemoReportError as exc:raise service_http_error(exc) from exc
    from app.services.pdf_reports import testing_pdf
    return Response(testing_pdf(report),media_type='application/pdf',headers={
        'Content-Disposition':f'attachment; filename="medflow-test-{report["run_id"]}.pdf"','Cache-Control':'no-store'})
