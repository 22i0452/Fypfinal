"""Prepared attendance requests; recorded staff responses, no claimed delivery."""
import json
from datetime import datetime
from app.services.appointment_service import AppointmentError
from medflow.domain.ids import new_id
from medflow.domain.models import utc_now
from medflow.domain.enums import AppointmentStatus, WorkflowState
from medflow.orchestration import WorkflowAction


class AttendanceService:
    def __init__(self, container):
        self.c=container

    def initialize(self):
        with self.c.database.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attendance_requests (request_id TEXT PRIMARY KEY, appointment_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS attendance_by_appointment ON attendance_requests(appointment_id,created_at)')

    def latest(self, appointment_id):
        with self.c.database.connection() as db:
            row=db.execute('SELECT payload FROM attendance_requests WHERE appointment_id=? ORDER BY created_at DESC LIMIT 1',(appointment_id,)).fetchone()
        if not row:return None
        result=json.loads(row[0])
        appointment=self.c.appointment_repository.get(appointment_id)
        expected_start=result.get('new_start_at') or result['start_at']
        result['stale']=not appointment or (appointment.start_at!=datetime.fromisoformat(expected_start)
            or appointment.practitioner_id!=result.get('practitioner_id')
            or appointment.visit_type_id!=result.get('visit_type_id'))
        return result

    def prepare(self, appointment_id, expected_version, actor):
        with self.c.database.transaction() as db:
            appointment=self.c.appointment_service.get(appointment_id,actor=actor)
            if appointment.status not in {AppointmentStatus.REQUESTED,AppointmentStatus.CONFIRMED}:
                raise AppointmentError('INVALID_STATUS','Attendance can be requested only before check-in')
            if appointment.version!=expected_version:raise AppointmentError('VERSION_CONFLICT','Appointment changed. Refresh and try again.')
            current=self.latest(appointment_id)
            if current and not current['stale'] and current['status']=='AWAITING_RESPONSE':return current
            result={'request_id':new_id('ATTEND'),'appointment_id':appointment_id,
                'patient_id':appointment.patient_id,'appointment_version':appointment.version,
                'practitioner_id':appointment.practitioner_id,'visit_type_id':appointment.visit_type_id,
                'start_at':appointment.start_at.isoformat(),'status':'AWAITING_RESPONSE',
                'delivery':'PREPARED','created_by':actor.ref,'created_at':utc_now().isoformat(),
                'response_source':None,'responded_at':None,'stale':False}
            db.execute('INSERT INTO attendance_requests VALUES (?,?,?,?)',
                (result['request_id'],appointment_id,result['created_at'],json.dumps(result)))
            self.c.audit_service.record('attendance_prepared',actor_ref=actor.ref,action='prepare_confirmation',
                patient_ref=appointment.patient_id,resource_ref=appointment_id,metadata={'delivery':'PREPARED'})
            return result

    def respond(self, appointment_id, request_id, response, new_start_at, actor):
        if response!='CHANGE_TIME' and new_start_at is not None:
            raise AppointmentError('INVALID_RESPONSE','A replacement time is only valid when changing time')
        with self.c.database.transaction() as db:
            appointment=self.c.appointment_service.get(appointment_id,actor=actor)
            record=self.latest(appointment_id)
            if not record or record['request_id']!=request_id:
                raise AppointmentError('REQUEST_NOT_FOUND','This attendance request is unavailable')
            if record['status']!='AWAITING_RESPONSE':
                if record.get('response')==response and record.get('new_start_at')==(new_start_at.isoformat() if new_start_at else None):return record
                raise AppointmentError('VERSION_CONFLICT','This request already has a response. Prepare a new request.')
            if record['stale'] or appointment.status not in {AppointmentStatus.REQUESTED,AppointmentStatus.CONFIRMED}:
                raise AppointmentError('VERSION_CONFLICT','Appointment changed. Prepare a new confirmation request.')
            if response=='CHANGE_TIME':
                if new_start_at is None:raise AppointmentError('TIME_REQUIRED','Choose an available replacement time')
                appointment=self.c.appointment_service.reschedule(appointment_id,new_start_at=new_start_at,
                    idempotency_key=request_id+'-move',actor=actor)
            elif response=='CANCEL':
                appointment=self.c.appointment_service.cancel(appointment_id,reason_code='PATIENT_DECLINED',
                    idempotency_key=request_id+'-cancel',actor=actor)
                for workflow in self.c.workflow_repository.list(patient_id=appointment.patient_id):
                    if workflow.appointment_id==appointment_id and workflow.state not in {WorkflowState.CANCELLED,WorkflowState.ENCOUNTER_COMPLETED}:
                        self.c.workflow_orchestrator.perform_action(workflow.workflow_id,WorkflowAction.CANCEL,
                            actor=actor,expected_version=workflow.version)
            elif response!='ATTEND':raise AppointmentError('INVALID_RESPONSE','Unknown attendance response')
            record.update(status={'ATTEND':'CONFIRMED','CHANGE_TIME':'RESCHEDULED','CANCEL':'CANCELLED'}[response],
                response=response,response_source='STAFF_RECORDED',recorded_by=actor.ref,
                responded_at=utc_now().isoformat(),result_version=appointment.version,
                new_start_at=new_start_at.isoformat() if new_start_at else None,stale=False)
            db.execute('UPDATE attendance_requests SET payload=? WHERE request_id=?',(json.dumps(record),request_id))
            self.c.audit_service.record('attendance_response_recorded',actor_ref=actor.ref,action=response,
                patient_ref=appointment.patient_id,resource_ref=appointment_id,
                metadata={'source':'STAFF_RECORDED','response':response})
            return record
