from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.fhir import (
    AllergyExport,
    CodedConcept,
    ConditionExport,
    FHIRMapper,
    MedicationRequestExport,
    MockFHIRClient,
    ObservationExport,
)
from app.services import (
    AfterVisitSummaryService,
    CodingCandidate,
    CodingService,
    GatewayUrduSummaryTranslationProvider,
)
from medflow.domain.enums import (
    AppointmentStatus,
    ClaimSupportStatus,
    EncounterStatus,
    NoteStatus,
    Speaker,
    SummaryLanguage,
    UserRole,
    WorkflowState,
)
from medflow.domain.models import (
    Appointment,
    ClinicalClaim,
    Encounter,
    EvidenceReference,
    PractitionerUser,
    SOAPNote,
    SOAPNoteVersion,
    StructuredSOAP,
    TranscriptRecord,
    TranscriptUtterance,
    WorkflowSession,
    utc_now,
)
from tests.support import build_container
from security_guardrails import SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter


class _SyntheticUrduTranslator:
    def translate(self, items, *, patient_ref, patient_context):
        return {item["item_id"]: f"Synthetic Urdu translation {item['item_id']}" for item in items}


class _SyntheticCodingProvider:
    def __init__(self, evidence_id: str) -> None:
        self.evidence_id = evidence_id
        self.calls = 0

    def suggest(self, version):
        self.calls += 1
        return [
            CodingCandidate(
                code="Z00.0",
                description="Synthetic test suggestion",
                confidence=0.75,
                evidence_ids=[self.evidence_id],
            )
        ]


class ClinicExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        _, self.container, self.user, self.patient, self.doctor, self.receptionist = build_container(
            Path(self.temporary.name)
        )
        setup_start = datetime(2030, 1, 7, 9, 0, tzinfo=timezone(timedelta(hours=5)))
        self.container.appointment_repository.save(
            Appointment(
                appointment_id="APT-SYNTHETIC-EXT-001",
                patient_id=self.patient.patient_id,
                practitioner_id=self.user.practitioner_id,
                department_id="DEP-GM",
                location_id="LOC-ISB-001",
                visit_type_id="VISIT-NEW",
                start_at=setup_start,
                end_at=setup_start + timedelta(minutes=30),
                status=AppointmentStatus.CHECKED_IN,
                idempotency_key="synthetic-extension-appointment",
            )
        )
        self.container.workflow_repository.save(
            WorkflowSession(
                workflow_id="WF-SYNTHETIC-EXT-001",
                patient_id=self.patient.patient_id,
                appointment_id="APT-SYNTHETIC-EXT-001",
                assigned_practitioner_id=self.user.practitioner_id,
                state=WorkflowState.CONSULTATION_READY,
            )
        )
        self.encounter = self.container.encounter_repository.save(
            Encounter(
                encounter_id="ENC-SYNTHETIC-EXT-001",
                patient_id=self.patient.patient_id,
                practitioner_id=self.user.practitioner_id,
                appointment_id="APT-SYNTHETIC-EXT-001",
                workflow_id="WF-SYNTHETIC-EXT-001",
                status=EncounterStatus.READY,
            )
        )

    def tearDown(self) -> None:
        set_gateway(None)
        self.temporary.cleanup()

    def _note(self, note_id: str, state: NoteStatus, marker: str) -> tuple[SOAPNote, SOAPNoteVersion]:
        assessment_id = f"{note_id}-ASSESSMENT-001"
        soap = StructuredSOAP(
            subjective=[
                ClinicalClaim(
                    claim_id=f"{note_id}-SUBJECTIVE-001",
                    text=f"{marker} subjective statement.",
                    evidence_ids=["U1"],
                    status=ClaimSupportStatus.SUPPORTED,
                )
            ],
            objective=[
                ClinicalClaim(
                    claim_id=f"{note_id}-OBJECTIVE-001",
                    text="Not documented.",
                    evidence_ids=["U1"],
                    status=ClaimSupportStatus.SUPPORTED,
                )
            ],
            assessment=[
                ClinicalClaim(
                    claim_id=assessment_id,
                    text=f"{marker} assessment statement.",
                    evidence_ids=["U1"],
                    status=ClaimSupportStatus.SUPPORTED,
                )
            ],
            plan=[
                ClinicalClaim(
                    claim_id=f"{note_id}-PLAN-001",
                    text=f"{marker} doctor-approved instruction.",
                    evidence_ids=["U1"],
                    status=ClaimSupportStatus.SUPPORTED,
                )
            ],
        )
        version = self.container.note_repository.save_version(
            SOAPNoteVersion(
                note_version_id=f"NV-{note_id}",
                note_id=note_id,
                version_number=1,
                status=state,
                soap=soap,
                evidence=[
                    EvidenceReference(
                        evidence_id="U1",
                        source_type="TRANSCRIPT_UTTERANCE",
                        source_id="U1",
                    )
                ],
                created_by_actor_id=self.doctor.actor_id,
            )
        )
        note = self.container.note_repository.save(
            SOAPNote(
                note_id=note_id,
                patient_id=self.patient.patient_id,
                encounter_id=self.encounter.encounter_id,
                current_version_id=version.note_version_id,
                state=state,
                approved_by_doctor_id=self.doctor.actor_id if state == NoteStatus.APPROVED_BY_DOCTOR else None,
                approved_at=utc_now() if state == NoteStatus.APPROVED_BY_DOCTOR else None,
            )
        )
        return note, version

    def test_flow_10_and_11_soap_evidence_must_reference_known_utterances(self) -> None:
        transcript = TranscriptRecord(
            transcript_id="TRN-SYNTHETIC-EVIDENCE-001",
            patient_id=self.patient.patient_id,
            encounter_id=self.encounter.encounter_id,
            utterances=[
                TranscriptUtterance(
                    transcript_id="TRN-SYNTHETIC-EVIDENCE-001",
                    utterance_id="U1",
                    speaker=Speaker.PATIENT,
                    original_text="Synthetic statement.",
                    clinical_english="Synthetic statement.",
                )
            ],
        )
        valid = self.container.documentation_service.build_structured_soap(
            "NOTE-SYN-EVIDENCE",
            {
                "subjective": "Synthetic statement.",
                "objective": "Not documented.",
                "assessment": "Synthetic assessment.",
                "plan": "Synthetic plan.",
                "evidence": [{"utterance_id": "U1"}],
            },
            transcript,
        )
        for claims in (valid.subjective, valid.objective, valid.assessment, valid.plan):
            self.assertEqual(claims[0].evidence_ids, ["U1"])
        with self.assertRaisesRegex(Exception, "unknown transcript evidence"):
            self.container.documentation_service.build_structured_soap(
                "NOTE-SYN-BAD-EVIDENCE",
                {"subjective": "Synthetic statement.", "evidence": [{"utterance_id": "U999"}]},
                transcript,
            )

    def test_flow_17_previsit_summary_uses_approved_records_only(self) -> None:
        self._note("NOTE-SYN-DRAFT", NoteStatus.AI_DRAFT, "DRAFT_ONLY")
        _, approved_version = self._note("NOTE-SYN-APPROVED", NoteStatus.APPROVED_BY_DOCTOR, "APPROVED_ONLY")
        summary = self.container.previsit_summary_service.generate(
            patient_id=self.patient.patient_id,
            encounter_id=self.encounter.encounter_id,
            actor=self.doctor,
        )
        rendered = " ".join(item.text for section in summary.sections for item in section.items)
        self.assertIn("APPROVED_ONLY", rendered)
        self.assertNotIn("DRAFT_ONLY", rendered)
        self.assertEqual(summary.source_note_version_ids, [approved_version.note_version_id])

    def test_flow_18_and_19_after_visit_requires_approval_and_preserves_source(self) -> None:
        draft, _ = self._note("NOTE-SYN-UNAPPROVED", NoteStatus.AI_DRAFT, "UNAPPROVED")
        with self.assertRaisesRegex(Exception, "doctor-approved"):
            self.container.after_visit_summary_service.generate(
                note_id=draft.note_id,
                language=SummaryLanguage.ENGLISH,
                actor=self.doctor,
            )

        approved, approved_version = self._note(
            "NOTE-SYN-AFTER-VISIT", NoteStatus.APPROVED_BY_DOCTOR, "APPROVED_SOURCE"
        )
        summary = self.container.after_visit_summary_service.generate(
            note_id=approved.note_id,
            language=SummaryLanguage.ENGLISH,
            actor=self.doctor,
        )
        source_texts = {
            claim.text
            for claims in (
                approved_version.soap.subjective,
                approved_version.soap.objective,
                approved_version.soap.assessment,
                approved_version.soap.plan,
            )
            for claim in claims
            if claim.text.lower() != "not documented."
        }
        self.assertEqual(
            {item.text for section in summary.sections for item in section.items},
            source_texts,
        )
        bilingual_service = AfterVisitSummaryService(
            patients=self.container.patient_repository,
            notes=self.container.note_repository,
            summaries=self.container.after_visit_summary_repository,
            audit=self.container.audit_service,
            translator=_SyntheticUrduTranslator(),
        )
        bilingual = bilingual_service.generate(
            note_id=approved.note_id,
            language=SummaryLanguage.BILINGUAL,
            actor=self.doctor,
        )
        self.assertEqual(bilingual.language, SummaryLanguage.BILINGUAL)
        self.assertTrue(all(item.evidence_ids for section in bilingual.sections for item in section.items))

    def test_flow_20_and_21_coding_requires_note_evidence_and_human_review(self) -> None:
        draft, draft_version = self._note("NOTE-SYN-CODE-DRAFT", NoteStatus.AI_DRAFT, "CODE_DRAFT")
        draft_provider = _SyntheticCodingProvider(draft_version.soap.assessment[0].claim_id)
        draft_service = CodingService(
            notes=self.container.note_repository,
            suggestions=self.container.code_suggestion_repository,
            audit=self.container.audit_service,
            provider=draft_provider,
        )
        draft_suggestions = draft_service.generate(note_id=draft.note_id, actor=self.doctor)
        self.assertEqual(len(draft_suggestions), 1)
        self.assertEqual(draft_provider.calls, 1)

        approved, version = self._note("NOTE-SYN-CODE-APPROVED", NoteStatus.APPROVED_BY_DOCTOR, "CODE_APPROVED")
        provider = _SyntheticCodingProvider(version.soap.assessment[0].claim_id)
        service = CodingService(
            notes=self.container.note_repository,
            suggestions=self.container.code_suggestion_repository,
            audit=self.container.audit_service,
            provider=provider,
        )
        suggestions = service.generate(note_id=approved.note_id, actor=self.doctor)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].status.value, "SUGGESTED")
        self.assertEqual(suggestions[0].system, "ICD-10")
        self.assertEqual(suggestions[0].evidence_ids, [version.soap.assessment[0].claim_id])
        reviewed = service.review(
            suggestion_id=suggestions[0].code_suggestion_id,
            approve=True,
            actor=self.doctor,
        )
        self.assertEqual(reviewed.status.value, "APPROVED")

    def test_flow_25_fhir_mapping_produces_expected_r4_resource_shapes(self) -> None:
        approved, version = self._note("NOTE-SYN-FHIR", NoteStatus.APPROVED_BY_DOCTOR, "FHIR_SOURCE")
        start = datetime(2030, 1, 7, 9, 0, tzinfo=timezone(timedelta(hours=5)))
        appointment = Appointment(
            appointment_id="APT-SYNTHETIC-FHIR-001",
            patient_id=self.patient.patient_id,
            practitioner_id=self.user.practitioner_id,
            department_id="DEP-GM",
            location_id="LOC-ISB-001",
            visit_type_id="VISIT-NEW",
            start_at=start,
            end_at=start + timedelta(minutes=30),
            status=AppointmentStatus.CONFIRMED,
            idempotency_key="synthetic-fhir-appointment",
        )
        resources = [
            FHIRMapper.patient(self.patient),
            FHIRMapper.practitioner(
                PractitionerUser(
                    practitioner_id=self.user.practitioner_id,
                    role=UserRole.DOCTOR,
                    full_name="Dr. Synthetic FHIR",
                    email="synthetic-fhir@example.test",
                )
            ),
            FHIRMapper.appointment(appointment),
            FHIRMapper.encounter(self.encounter),
            FHIRMapper.observation(
                ObservationExport(
                    observation_id="OBS-SYNTHETIC-001",
                    patient_id=self.patient.patient_id,
                    code=CodedConcept(system="urn:synthetic", code="OBS", display="Synthetic observation"),
                    effective_at=start,
                    value_number=1.0,
                    unit="synthetic unit",
                    unit_code="1",
                )
            ),
            FHIRMapper.condition(
                ConditionExport(
                    condition_id="COND-SYNTHETIC-001",
                    patient_id=self.patient.patient_id,
                    code=CodedConcept(system="urn:synthetic", code="COND", display="Synthetic condition"),
                    recorded_at=start,
                )
            ),
            FHIRMapper.allergy_intolerance(
                AllergyExport(
                    allergy_id="ALG-SYNTHETIC-001",
                    patient_id=self.patient.patient_id,
                    substance=CodedConcept(system="urn:synthetic", code="ALG", display="Synthetic substance"),
                    recorded_at=start,
                )
            ),
            FHIRMapper.medication_request(
                MedicationRequestExport(
                    medication_request_id="MEDREQ-SYNTHETIC-001",
                    patient_id=self.patient.patient_id,
                    practitioner_id=self.user.practitioner_id,
                    medication=CodedConcept(
                        system="urn:synthetic",
                        code="MED",
                        display="Synthetic medication",
                    ),
                    authored_at=start,
                    dosage_text="Synthetic doctor-approved dosage instruction.",
                )
            ),
            FHIRMapper.composition(approved, version),
        ]
        self.assertEqual(
            [resource["resourceType"] for resource in resources],
            [
                "Patient",
                "Practitioner",
                "Appointment",
                "Encounter",
                "Observation",
                "Condition",
                "AllergyIntolerance",
                "MedicationRequest",
                "Composition",
            ],
        )
        client = MockFHIRClient()
        for resource in resources:
            client.put(resource)
            self.assertEqual(client.get(resource["resourceType"], resource["id"]), resource)

    def test_default_clinical_templates_are_idempotently_seeded(self) -> None:
        self.container.template_service.seed_defaults()
        templates = self.container.template_service.list_active()
        self.assertEqual(len(templates), 5)
        self.assertEqual(len({template.template_id for template in templates}), 5)

    def test_after_visit_translation_uses_gateway_and_minimizes_identifiers(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "after_visit_translation",
            {"translations": [{"item_id": "AVS-ITEM-001", "urdu": "Synthetic Urdu text"}]},
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        result = GatewayUrduSummaryTranslationProvider().translate(
            [
                {
                    "item_id": "AVS-ITEM-001",
                    "english": f"{self.patient.name} can be called at {self.patient.phone_number}.",
                }
            ],
            patient_ref=self.patient.patient_id,
            patient_context=self.patient.model_dump(mode="json"),
        )
        self.assertEqual(result["AVS-ITEM-001"], "Synthetic Urdu text")
        outbound = str(adapter.calls[-1]["messages"])
        self.assertNotIn(self.patient.name, outbound)
        self.assertNotIn(self.patient.phone_number, outbound)


if __name__ == "__main__":
    unittest.main()
