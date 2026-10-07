from __future__ import annotations

import html
import re
from typing import Any

from medflow.domain.enums import AppointmentStatus, EncounterStatus, NoteStatus
from medflow.domain.models import Appointment, Encounter, Patient, PractitionerUser, SOAPNote, SOAPNoteVersion

from .models import AllergyExport, ConditionExport, MedicationRequestExport, ObservationExport


class FHIRMappingError(ValueError):
    pass


_FHIR_ID_RE = re.compile(r"[^A-Za-z0-9\-.]")


def _fhir_id(value: str) -> str:
    normalized = _FHIR_ID_RE.sub("-", str(value or "").strip())[:64].strip("-")
    if not normalized:
        raise FHIRMappingError("FHIR resource identifier is missing")
    return normalized


class FHIRMapper:
    APPOINTMENT_STATUS = {
        AppointmentStatus.REQUESTED: "proposed",
        AppointmentStatus.CONFIRMED: "booked",
        AppointmentStatus.CHECKED_IN: "arrived",
        AppointmentStatus.IN_PROGRESS: "arrived",
        AppointmentStatus.COMPLETED: "fulfilled",
        AppointmentStatus.CANCELLED: "cancelled",
        AppointmentStatus.NO_SHOW: "noshow",
    }
    ENCOUNTER_STATUS = {
        EncounterStatus.PLANNED: "planned",
        EncounterStatus.READY: "arrived",
        EncounterStatus.IN_PROGRESS: "in-progress",
        EncounterStatus.DOCUMENTATION: "in-progress",
        EncounterStatus.COMPLETED: "finished",
        EncounterStatus.CANCELLED: "cancelled",
    }

    @staticmethod
    def patient(patient: Patient) -> dict[str, Any]:
        resource: dict[str, Any] = {
            "resourceType": "Patient",
            "id": _fhir_id(patient.patient_id),
            "active": patient.active,
            "identifier": [{"system": "urn:medflow:patient-id", "value": patient.patient_id}],
        }
        if patient.name:
            resource["name"] = [{"text": patient.name}]
        if patient.phone_number:
            resource["telecom"] = [{"system": "phone", "value": patient.phone_number, "use": "mobile"}]
        if patient.email:
            resource.setdefault("telecom", []).append({"system": "email", "value": patient.email})
        if patient.date_of_birth:
            resource["birthDate"] = patient.date_of_birth
        return resource

    @staticmethod
    def practitioner(practitioner: PractitionerUser) -> dict[str, Any]:
        return {
            "resourceType": "Practitioner",
            "id": _fhir_id(practitioner.practitioner_id),
            "active": practitioner.active,
            "identifier": [
                {"system": "urn:medflow:practitioner-id", "value": practitioner.practitioner_id}
            ],
            "name": [{"text": practitioner.full_name}],
            **(
                {"telecom": [{"system": "email", "value": practitioner.email}]}
                if practitioner.email
                else {}
            ),
        }

    @classmethod
    def appointment(cls, appointment: Appointment) -> dict[str, Any]:
        return {
            "resourceType": "Appointment",
            "id": _fhir_id(appointment.appointment_id),
            "status": cls.APPOINTMENT_STATUS[appointment.status],
            "start": appointment.start_at.isoformat(),
            "end": appointment.end_at.isoformat(),
            "serviceType": [{"text": appointment.visit_type_id}],
            "specialty": [{"text": appointment.department_id}],
            "participant": [
                {
                    "actor": {"reference": f"Patient/{_fhir_id(appointment.patient_id)}"},
                    "status": "accepted",
                },
                {
                    "actor": {"reference": f"Practitioner/{_fhir_id(appointment.practitioner_id)}"},
                    "status": "accepted",
                },
            ],
        }

    @classmethod
    def encounter(cls, encounter: Encounter) -> dict[str, Any]:
        resource: dict[str, Any] = {
            "resourceType": "Encounter",
            "id": _fhir_id(encounter.encounter_id),
            "status": cls.ENCOUNTER_STATUS[encounter.status],
            "class": {
                "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                "code": "AMB",
                "display": "ambulatory",
            },
            "subject": {"reference": f"Patient/{_fhir_id(encounter.patient_id)}"},
            "participant": [
                {"individual": {"reference": f"Practitioner/{_fhir_id(encounter.practitioner_id)}"}}
            ],
            "appointment": [{"reference": f"Appointment/{_fhir_id(encounter.appointment_id)}"}],
        }
        if encounter.started_at or encounter.ended_at:
            resource["period"] = {
                **({"start": encounter.started_at.isoformat()} if encounter.started_at else {}),
                **({"end": encounter.ended_at.isoformat()} if encounter.ended_at else {}),
            }
        return resource

    @staticmethod
    def composition(note: SOAPNote, version: SOAPNoteVersion) -> dict[str, Any]:
        if note.state != NoteStatus.APPROVED_BY_DOCTOR or version.status != NoteStatus.APPROVED_BY_DOCTOR:
            raise FHIRMappingError("Only the current doctor-approved note version can be exported")
        sections = []
        for title, claims in (
            ("Subjective", version.soap.subjective),
            ("Objective", version.soap.objective),
            ("Assessment", version.soap.assessment),
            ("Plan", version.soap.plan),
        ):
            lines = "<br/>".join(html.escape(claim.text) for claim in claims)
            sections.append(
                {
                    "title": title,
                    "text": {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{lines}</div>'},
                    "extension": [
                        {
                            "url": "urn:medflow:evidence-reference",
                            "valueString": evidence_id,
                        }
                        for claim in claims
                        for evidence_id in claim.evidence_ids
                    ],
                }
            )
        return {
            "resourceType": "Composition",
            "id": _fhir_id(version.note_version_id),
            "status": "final",
            "type": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "11506-3",
                        "display": "Progress note",
                    }
                ]
            },
            "subject": {"reference": f"Patient/{_fhir_id(note.patient_id)}"},
            "encounter": {"reference": f"Encounter/{_fhir_id(note.encounter_id)}"},
            "date": (note.approved_at or note.updated_at).isoformat(),
            "author": [
                {"reference": f"Practitioner/{_fhir_id(note.approved_by_doctor_id or 'unknown-doctor')}"}
            ],
            "title": "Doctor-approved SOAP note",
            "section": sections,
        }

    @staticmethod
    def observation(source: ObservationExport) -> dict[str, Any]:
        resource: dict[str, Any] = {
            "resourceType": "Observation",
            "id": _fhir_id(source.observation_id),
            "status": "final",
            "code": {"coding": [source.code.model_dump()]},
            "subject": {"reference": f"Patient/{_fhir_id(source.patient_id)}"},
            "effectiveDateTime": source.effective_at.isoformat(),
        }
        if source.value_number is not None:
            resource["valueQuantity"] = {
                "value": source.value_number,
                **({"unit": source.unit} if source.unit else {}),
                **(
                    {"system": "http://unitsofmeasure.org", "code": source.unit_code}
                    if source.unit_code
                    else {}
                ),
            }
        else:
            resource["valueString"] = source.value_text
        return resource

    @staticmethod
    def condition(source: ConditionExport) -> dict[str, Any]:
        return {
            "resourceType": "Condition",
            "id": _fhir_id(source.condition_id),
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code": source.clinical_status,
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code": source.verification_status,
                    }
                ]
            },
            "code": {"coding": [source.code.model_dump()]},
            "subject": {"reference": f"Patient/{_fhir_id(source.patient_id)}"},
            "recordedDate": source.recorded_at.isoformat(),
        }

    @staticmethod
    def allergy_intolerance(source: AllergyExport) -> dict[str, Any]:
        return {
            "resourceType": "AllergyIntolerance",
            "id": _fhir_id(source.allergy_id),
            "clinicalStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                        "code": source.clinical_status,
                    }
                ]
            },
            "verificationStatus": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                        "code": source.verification_status,
                    }
                ]
            },
            "category": [source.category],
            "criticality": source.criticality,
            "code": {"coding": [source.substance.model_dump()]},
            "patient": {"reference": f"Patient/{_fhir_id(source.patient_id)}"},
            "recordedDate": source.recorded_at.isoformat(),
        }

    @staticmethod
    def medication_request(source: MedicationRequestExport) -> dict[str, Any]:
        return {
            "resourceType": "MedicationRequest",
            "id": _fhir_id(source.medication_request_id),
            "status": source.status,
            "intent": source.intent,
            "medicationCodeableConcept": {"coding": [source.medication.model_dump()]},
            "subject": {"reference": f"Patient/{_fhir_id(source.patient_id)}"},
            "authoredOn": source.authored_at.isoformat(),
            "requester": {"reference": f"Practitioner/{_fhir_id(source.practitioner_id)}"},
            "dosageInstruction": [{"text": source.dosage_text}],
        }
