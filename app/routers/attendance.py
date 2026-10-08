from datetime import datetime
from typing import Literal
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from app.dependencies import get_container,get_current_user,actor_for_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services.appointment_service import AppointmentError

router=APIRouter(prefix='/api/appointments',tags=['attendance'])

class Prepare(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_version:int=Field(ge=1)

class Response(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:str
    response:Literal['ATTEND','CHANGE_TIME','CANCEL']
    new_start_at:datetime|None=None

def context(request,user,appointment_id):
    c=get_container(request)
    a=c.appointment_repository.get(appointment_id)
    if not a or user.actor_role!='doctor' or user.practitioner_id!=a.practitioner_id:
        raise HTTPException(404,'Appointment unavailable for this doctor')
    return c,actor_for_user(c,user,a.patient_id)

@router.get('/{appointment_id}/attendance')
async def latest(appointment_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    c,_=context(request,user,appointment_id)
    return {'request':c.attendance_service.latest(appointment_id)}

@router.post('/{appointment_id}/attendance')
async def prepare(appointment_id:str,payload:Prepare,request:Request,user:AuthUser=Depends(get_current_user)):
    c,actor=context(request,user,appointment_id)
    try:return c.attendance_service.prepare(appointment_id,payload.expected_version,actor)
    except AppointmentError as exc:raise service_http_error(exc) from exc

@router.post('/{appointment_id}/attendance/respond')
async def respond(appointment_id:str,payload:Response,request:Request,user:AuthUser=Depends(get_current_user)):
    c,actor=context(request,user,appointment_id)
    try:return c.attendance_service.respond(appointment_id,payload.request_id,payload.response,payload.new_start_at,actor)
    except AppointmentError as exc:raise service_http_error(exc) from exc
