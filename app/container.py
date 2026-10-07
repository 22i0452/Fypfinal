from __future__ import annotations

import warnings
from pathlib import Path

from app.config import ROOT_DIR, Settings
from app.infrastructure.database import SQLiteDatabase
from app.repositories import (
    SQLiteAppointmentRepository,
    SQLiteAuditRepository,
    SQLiteAuthRepository,
    SQLiteClinicRepository,
    SQLiteConsentRepository,
    SQLiteEncounterRepository,
    SQLiteVerificationRepository,
    SQLiteWorkflowRepository,
)
from app.services import (
    AppointmentService,
    AfterVisitSummaryService,
    AuditService,
    ClinicLifecycleService,
    ConsentService,
    CodingService,
    DocumentationService,
    MockOTPProvider,
    DevelopmentQuickStartService,
    PatientVerificationService,
    PreVisitSummaryService,
    NoteLifecycleService,
    ReceptionistIntegrationService,
    SMSOTPProvider,
    TemplateService,
)
from app.services.confirmation_call_service import ConfirmationCallService
from app.services.demo_call_service import DemoCallService
from app.services.process_trace import ProcessTraceStore
from app.services.inbound_call_service import CallMediaStore, InboundCallService
from medflow.orchestration import ClinicWorkflowOrchestrator
from medflow.repositories import (
    JsonAfterVisitSummaryRepository,
    JsonCodeSuggestionRepository,
    JsonNoteRepository,
    JsonPatientRepository,
    JsonPreVisitSummaryRepository,
    JsonTemplateRepository,
    JsonTranscriptRepository,
)


class ApplicationContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = SQLiteDatabase(settings.database_path)
        self.process_trace = ProcessTraceStore(self.database)
        self.auth_repository = SQLiteAuthRepository(
            self.database,
            primary_doctor_email=settings.primary_doctor_email,
        )
        self.clinic_repository = SQLiteClinicRepository(self.database)
        self.appointment_repository = SQLiteAppointmentRepository(self.database)
        self.workflow_repository = SQLiteWorkflowRepository(self.database)
        self.encounter_repository = SQLiteEncounterRepository(self.database)
        self.verification_repository = SQLiteVerificationRepository(self.database)
        self.consent_repository = SQLiteConsentRepository(self.database)
        self.audit_repository = SQLiteAuditRepository(self.database)
        self.patient_repository = JsonPatientRepository(settings.patient_records_dir)
        self.note_repository = JsonNoteRepository(settings.generated_notes_dir)
        self.transcript_repository = JsonTranscriptRepository(settings.generated_notes_dir / "_transcripts")
        self.previsit_summary_repository = JsonPreVisitSummaryRepository(
            settings.generated_notes_dir / "_previsit_summaries"
        )
        self.after_visit_summary_repository = JsonAfterVisitSummaryRepository(
            settings.generated_notes_dir / "_after_visit_summaries"
        )
        self.template_repository = JsonTemplateRepository(settings.generated_notes_dir / "_templates")
        self.code_suggestion_repository = JsonCodeSuggestionRepository(
            settings.generated_notes_dir / "_code_suggestions"
        )
        self.audit_service = AuditService(self.audit_repository)
        self.workflow_orchestrator = ClinicWorkflowOrchestrator(self.workflow_repository)
        otp_provider = MockOTPProvider(settings) if settings.mock_otp_enabled else SMSOTPProvider()
        self.verification_service = PatientVerificationService(
            settings=settings,
            provider=otp_provider,
            patients=self.patient_repository,
            verifications=self.verification_repository,
            workflows=self.workflow_repository,
            orchestrator=self.workflow_orchestrator,
            audit=self.audit_service,
        )
        self.consent_service = ConsentService(
            consents=self.consent_repository,
            encounters=self.encounter_repository,
            workflows=self.workflow_repository,
            audit=self.audit_service,
        )
        self.appointment_service = AppointmentService(
            appointments=self.appointment_repository,
            clinic=self.clinic_repository,
            audit=self.audit_service,
        )
        self.lifecycle_service = ClinicLifecycleService(
            workflows=self.workflow_repository,
            encounters=self.encounter_repository,
            orchestrator=self.workflow_orchestrator,
            appointments=self.appointment_service,
            audit=self.audit_service,
        )
        self.development_quick_start_service = DevelopmentQuickStartService(
            settings=settings,
            patients=self.patient_repository,
            workflows=self.workflow_repository,
            encounters=self.encounter_repository,
            orchestrator=self.workflow_orchestrator,
            appointments=self.appointment_service,
            lifecycle=self.lifecycle_service,
            consents=self.consent_service,
            clinic=self.clinic_repository,
            audit=self.audit_service,
        )
        self.receptionist_integration_service = ReceptionistIntegrationService(
            patients=self.patient_repository,
            workflows=self.workflow_repository,
            appointments=self.appointment_service,
            lifecycle=self.lifecycle_service,
            clinic=self.clinic_repository,
            auth=self.auth_repository,
            audit=self.audit_service,
        )
        self.confirmation_call_service = ConfirmationCallService(
            api_key=settings.telnyx_api_key,
            from_number=settings.telnyx_number,
            connection_id=settings.telnyx_connection_id,
            webhook_base_url=settings.telnyx_webhook_base_url,
            appointments=self.appointment_service,
        )
        media_root = ROOT_DIR / "data" / "call_media"
        self.inbound_call_service = InboundCallService(
            api_key=settings.telnyx_api_key,
            clinic_number=settings.telnyx_number,
            webhook_base_url=settings.telnyx_webhook_base_url,
            openrouter_api_key=settings.openrouter_api_key,
            openrouter_stt_model=settings.openrouter_stt_model,
            openrouter_tts_model=settings.openrouter_tts_model,
            openrouter_tts_voice=settings.openrouter_tts_voice,
            groq_api_key=settings.groq_api_key,
            groq_llm_model=settings.groq_llm_model,
            media_store=CallMediaStore(media_root),
        )
        self.demo_call_service = DemoCallService(
            groq_api_key=settings.groq_api_key,
            groq_llm_model=settings.groq_llm_model,
            openrouter_api_key=settings.openrouter_api_key,
        )
        self.inbound_call_service.attach_booking(self.demo_call_service, self.receptionist_integration_service)
        self.template_service = TemplateService(self.template_repository)
        self.documentation_service = DocumentationService(
            notes=self.note_repository,
            transcripts=self.transcript_repository,
            lifecycle=self.lifecycle_service,
            audit=self.audit_service,
            templates=self.template_service,
        )
        self.note_lifecycle_service = NoteLifecycleService(
            notes=self.note_repository,
            transcripts=self.transcript_repository,
            workflows=self.workflow_repository,
            orchestrator=self.workflow_orchestrator,
            audit=self.audit_service,
        )
        self.previsit_summary_service = PreVisitSummaryService(
            patients=self.patient_repository,
            encounters=self.encounter_repository,
            notes=self.note_repository,
            summaries=self.previsit_summary_repository,
            audit=self.audit_service,
        )
        self.after_visit_summary_service = AfterVisitSummaryService(
            patients=self.patient_repository,
            notes=self.note_repository,
            summaries=self.after_visit_summary_repository,
            audit=self.audit_service,
        )
        coding_provider = None
        if self.settings.icd_coding_enabled:
            from app.services.llm_coding_provider import LLMCodingProvider

            coding_provider = LLMCodingProvider()
        self.coding_service = CodingService(
            notes=self.note_repository,
            suggestions=self.code_suggestion_repository,
            audit=self.audit_service,
            provider=coding_provider,
        )

    def initialize(self) -> None:
        if self.settings.is_production and self.settings.storage_backend == "json":
            warnings.warn(
                "JSON clinical storage is a development adapter and is not suitable for production deployment.",
                RuntimeWarning,
                stacklevel=2,
            )
        self.database.initialize()
        self.process_trace.initialize()
        self.database.seed_clinic_configuration(self.settings.clinic_seed_path)
        self.database.connect_existing_doctors_to_profiles()
        self.template_service.seed_defaults()
        self._ensure_primary_doctor()
        self._migrate_legacy_patient_assignments()

    def _ensure_primary_doctor(self) -> None:
        """Normalize the clinic primary doctor and grant full patient coverage."""
        if not self.settings.primary_doctor_email:
            return
        primary = self.auth_repository.ensure_primary_doctor(
            email=self.settings.primary_doctor_email,
            display_name=self.settings.primary_doctor_display_name,
        )
        if primary is None or not primary.practitioner_id:
            return
        for patient in self.patient_repository.list():
            self.auth_repository.assign_patient(primary.practitioner_id, patient.patient_id)

    def _migrate_legacy_patient_assignments(self) -> None:
        """Preserve the single-user prototype without granting future users wildcard access."""
        with self.database.connection() as connection:
            linked_profiles = connection.execute(
                """
                SELECT practitioner_id FROM practitioner_profiles
                WHERE doctor_user_id IS NOT NULL AND active = 1
                ORDER BY doctor_user_id
                """
            ).fetchall()
        if len(linked_profiles) != 1:
            return
        practitioner_id = str(linked_profiles[0]["practitioner_id"])
        for patient in self.patient_repository.list():
            self.auth_repository.assign_patient(practitioner_id, patient.patient_id)
