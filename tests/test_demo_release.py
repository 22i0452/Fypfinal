"""Synthetic release contracts; no provider calls or real patient information."""
import json
import os
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader
from app.container import ApplicationContainer
from app.infrastructure.database import SQLiteDatabase
from medflow.domain.models import Patient
from medflow.repositories.sql_documents import SQLDocumentStore
from medflow.repositories.json_repositories import RepositoryConflictError
from tests.support import test_settings, build_container

PASSWORD='SyntheticDemoPass123!'


class PersistenceTests(unittest.TestCase):
    def make(self, root):
        settings=test_settings(root,storage_backend='sql',demo_profiles_enabled=True,demo_access_password=PASSWORD)
        container=ApplicationContainer(settings);container.initialize()
        return settings,container

    def test_seed_once_preserve_changes_new_patients_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings,container=self.make(root)
            self.assertEqual(len(container.patient_repository.list()),3)
            doctor=container.auth_repository.verify_credentials('ayesha@demo.medflow.invalid',PASSWORD)
            self.assertEqual(doctor.practitioner_id,'DOC-DEV-002')
            saved=container.patient_repository.get('PT-DEMO-SYNTHETIC-001')
            saved.current_complaint='Edited synthetic complaint';container.patient_repository.save(saved)
            container.patient_repository.save(Patient(patient_id='PT-DEMO-NEW',name='New fictional patient'))
            container.auth_repository.assign_patient(doctor.practitioner_id,'PT-DEMO-NEW')
            other=ApplicationContainer(settings);other.initialize()
            self.assertEqual(len(other.patient_repository.list()),4)
            self.assertEqual(other.patient_repository.get(saved.patient_id).current_complaint,saved.current_complaint)
            self.assertIn('PT-DEMO-NEW',other.auth_repository.authorized_patient_ids(doctor))
            self.assertIsNotNone(other.auth_repository.verify_credentials(doctor.email,PASSWORD))
            self.assertFalse(settings.patient_records_dir.exists())
            self.assertFalse(settings.generated_notes_dir.exists())

    def test_immutable_versions_and_atomic_document_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            _,container=self.make(Path(directory))
            store=SQLDocumentStore(container.database,'note_versions')
            store.write('NV-SYNTHETIC',{'version':1});store.write('NV-SYNTHETIC',{'version':1})
            with self.assertRaises(RepositoryConflictError):store.write('NV-SYNTHETIC',{'version':2})
            self.assertEqual(store.read('NV-SYNTHETIC'),{'version':1})
            with self.assertRaises(RuntimeError):
                with container.database.transaction():
                    container.patient_repository.save(Patient(patient_id='PT-ROLLBACK',name='Rollback'))
                    raise RuntimeError('synthetic failure')
            self.assertIsNone(container.patient_repository.get('PT-ROLLBACK'))

    def test_booking_conflicts_and_saved_note_versions_survive_restart(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from app.services import AppointmentRequest, AppointmentError
        from security_guardrails import Actor
        from medflow.domain.models import SOAPNote,SOAPNoteVersion,StructuredSOAP,TranscriptRecord,TranscriptUtterance
        with tempfile.TemporaryDirectory() as directory:
            settings,container=self.make(Path(directory))
            user=container.auth_repository.get_by_email('ayesha@demo.medflow.invalid')
            patient_id='PT-DEMO-SYNTHETIC-001'
            actor=Actor(str(user.user_id),'doctor',{patient_id},patient_id)
            request=AppointmentRequest(patient_id=patient_id,practitioner_id=user.practitioner_id,
                department_id='DEP-GM',location_id='LOC-ISB-001',visit_type_id='VISIT-NEW',
                start_at=datetime(2030,1,7,10,0),idempotency_key='demo-contract-booking')
            now=datetime(2030,1,7,7,0,tzinfo=ZoneInfo('Asia/Karachi'))
            first=container.appointment_service.create(request,actor=actor,now=now)
            self.assertEqual(container.appointment_service.create(request,actor=actor,now=now).appointment_id,first.appointment_id)
            from dataclasses import replace
            with self.assertRaises(AppointmentError):
                container.appointment_service.create(replace(request,idempotency_key='second-booking'),actor=actor,now=now)
            transcript=TranscriptRecord(transcript_id='TRN-DEMO',patient_id=patient_id,encounter_id='ENC-DEMO',
                utterances=[TranscriptUtterance(transcript_id='TRN-DEMO',utterance_id='U1',speaker='DOCTOR',
                    original_text='Take Panadol 500 mg.',clinical_english='Take Panadol 500 mg.')])
            container.transcript_repository.save(transcript)
            version=SOAPNoteVersion(note_version_id='NV-DEMO',note_id='NOTE-DEMO',version_number=1,status='AI_DRAFT',
                soap=StructuredSOAP(),transcript_id=transcript.transcript_id,created_by_actor_id=actor.actor_id)
            container.note_repository.save_version(version)
            container.note_repository.save(SOAPNote(note_id='NOTE-DEMO',patient_id=patient_id,encounter_id='ENC-DEMO',current_version_id=version.note_version_id))
            restarted=ApplicationContainer(settings);restarted.initialize()
            self.assertEqual(restarted.appointment_repository.get(first.appointment_id),first)
            self.assertEqual(restarted.transcript_repository.get(transcript.transcript_id),transcript)
            self.assertEqual(restarted.note_repository.get_version(version.note_version_id),version)

    def test_migrate_existing_records_once_without_overwriting(self):
        from scripts.migrate_demo_storage import migrate
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings,source,user,patient,_,_=build_container(root/'old')
            target=SQLiteDatabase(root/'new.db')
            counts=migrate(settings,target)
            self.assertEqual(counts['patients'],1)
            from medflow.repositories.sql_documents import repositories
            self.assertEqual(repositories(target)['patient_repository'].get(patient.patient_id).name,patient.name)
            with self.assertRaisesRegex(RuntimeError,'already contains'):migrate(settings,target)


class DemoAccessTests(unittest.TestCase):
    def test_https_authentication_desk_gate_and_no_public_signup(self):
        from app.main import create_app
        with tempfile.TemporaryDirectory() as directory:
            settings=test_settings(Path(directory),app_env='demo',storage_backend='sql',mock_otp_enabled=False,
                demo_profiles_enabled=True,demo_access_password=PASSWORD)
            with TestClient(create_app(settings),base_url='https://demo.test') as client:
                self.assertEqual(client.get('/healthz').json(),{'status':'ok'})
                self.assertEqual(client.get('/receptionist',follow_redirects=False).status_code,302)
                self.assertEqual(client.get('/api/desk/demo/session').status_code,401)
                config=client.get('/api/demo-access').json()
                self.assertEqual(len(config['doctors']),3);self.assertNotIn(PASSWORD,json.dumps(config))
                self.assertEqual(client.post('/api/auth/signup',json={'full_name':'Fictional','email':'x@example.test','password':PASSWORD}).status_code,403)
                response=client.post('/api/auth/login',json={'email':config['doctors'][0]['email'],'password':PASSWORD})
                self.assertEqual(response.status_code,200,response.text)
                self.assertIn('secure',response.headers['set-cookie'].lower())
                self.assertEqual(client.get('/receptionist').status_code,200)
                self.assertNotEqual(client.get('/api/desk/demo/session').status_code,401)


class PDFTests(unittest.TestCase):
    def payload(self):
        from app.services.medicine_evidence import medicine_evidence
        from medflow.medicines import clinician_review
        source='پیناڈول 500 mg لیں۔ موٹیلیم 10 mg نہ لیں۔'
        text='Take Panadol 500 mg. Do not take Motilium 10 mg.'
        review=clinician_review(source,text,{},'D:synthetic')
        turns=[{'utterance_id':'U1','speaker':'Doctor','original_text':source,'clinical_english':text,'medicine_review':review}]
        soap={'subjective':'Synthetic headache.','objective':'Not documented.','assessment':'Not documented.',
              'plan':text,'structured_soap':{'warnings':['Synthetic source wording; not clinical correctness.']}}
        soap['medicine_evidence']=medicine_evidence(turns,soap,1)
        return {'state':'APPROVED_BY_DOCTOR','soap':soap,'note_id':'NOTE-SYNTHETIC-PDF','encounter_id':'ENC-SYNTHETIC',
                'version':1,'created_at':'2030-01-02T00:00:00Z'}

    def test_pdf_uses_exact_saved_instructions_and_draft_label(self):
        from app.services.pdf_reports import visit_pdf
        payload=self.payload();patient=Patient(patient_id='PT-PDF',name='Fictional QA patient',age_text='28 years')
        pdf=visit_pdf(payload,patient,'Dr. Fictional QA')
        text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn('Panadol 500 mg',text);self.assertIn('Do not take Motilium 10 mg',text)
        self.assertNotIn('twice daily',text);self.assertIn('Doctor approved',text)
        self.assertTrue(all(card['doctor_reviewed'] for card in payload['soap']['medicine_evidence']['items']))
        payload['state']='AI_DRAFT'
        draft=visit_pdf(payload,patient,'Dr. Fictional QA')
        text='\n'.join(page.extract_text() for page in PdfReader(BytesIO(draft)).pages)
        self.assertIn('DRAFT',text);self.assertNotIn('Medication instructions - as documented',text)

    def test_pdf_exports_require_ownership(self):
        from app.main import create_app
        from tests.test_note_lifecycle import NoteLifecycleTests
        with tempfile.TemporaryDirectory() as directory:
            container,patient,doctor,_,note=NoteLifecycleTests()._draft(Path(directory))
            app=create_app(container.settings)
            with TestClient(app) as client:
                login=client.post('/api/auth/login',json={'email':'doctor@example.test','password':'SyntheticPass123!'})
                self.assertEqual(login.status_code,200)
                response=client.get(f'/api/notes/{note.note_id}/export.pdf')
                self.assertEqual(response.status_code,200,response.text[:200]);self.assertTrue(response.content.startswith(b'%PDF'))
                app.state.container.auth_repository.create_doctor('Other fictional doctor','other@example.test',PASSWORD)
                client.post('/api/auth/login',json={'email':'other@example.test','password':PASSWORD})
                self.assertEqual(client.get(f'/api/notes/{note.note_id}/export.pdf').status_code,403)


class PostgreSQLContracts(PersistenceTests):
    """Real PostgreSQL SQL engine over stdio; not a deployed psycopg network test."""
    def setUp(self):
        module=os.environ.get('PGLITE_MODULE_PATH')
        if not module or not Path(module).is_file():self.skipTest('Optional PGlite SQL engine not installed')
        self.process=subprocess.Popen([os.environ.get('CODEX_PRIMARY_RUNTIME_NODE','node'),str(Path(__file__).with_name('pglite_stdio.mjs'))],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        process=self.process
        from app.infrastructure.postgres_database import Record
        class Cursor:
            def __init__(self,result):self.rows=[Record(row) for row in result['rows']];self.rowcount=result['count']
            def fetchone(self):return self.rows.pop(0) if self.rows else None
            def fetchall(self):rows=self.rows;self.rows=[];return rows
            def __iter__(self):return iter(self.rows)
        class Raw:
            def execute(self,sql,params=()):
                process.stdin.write(json.dumps({'sql':sql,'params':params})+'\n');process.stdin.flush()
                output=process.stdout.readline()
                if not output:raise RuntimeError(process.stderr.read())
                result=json.loads(output)
                if result.get('error'):
                    import psycopg
                    if result.get('code','').startswith('23'):raise psycopg.IntegrityError(result['error'])
                    raise RuntimeError(result['error']+' SQL: '+sql)
                return Cursor(result)
            def __enter__(self):self.execute('BEGIN');return self
            def __exit__(self,typ,*args):self.execute('ROLLBACK' if typ else 'COMMIT')
        self.patcher=patch('psycopg.connect',side_effect=lambda *a,**k:Raw());self.patcher.start()

    def tearDown(self):
        if hasattr(self,'patcher'):self.patcher.stop()
        if hasattr(self,'process'):
            self.process.stdin.close();self.process.wait(timeout=10)
            self.process.stdout.close();self.process.stderr.close()

    def make(self,root):
        settings=test_settings(root,storage_backend='postgres',database_url='postgresql://synthetic/contract',
            demo_profiles_enabled=True,demo_access_password=PASSWORD)
        container=ApplicationContainer(settings);container.initialize()
        return settings,container

    def test_migrate_existing_records_once_without_overwriting(self):
        from scripts.migrate_demo_storage import migrate
        from app.infrastructure.postgres_database import PostgresDatabase
        with tempfile.TemporaryDirectory() as directory:
            settings,source,user,patient,_,_=build_container(Path(directory)/'old')
            target=PostgresDatabase('postgresql://synthetic/contract')
            self.assertEqual(migrate(settings,target)['patients'],1)
            from medflow.repositories.sql_documents import repositories
            self.assertIsNotNone(repositories(target)['patient_repository'].get(patient.patient_id))
            with self.assertRaisesRegex(RuntimeError,'already contains'):migrate(settings,target)


if __name__=='__main__':unittest.main()
