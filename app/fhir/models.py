from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FHIRExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CodedConcept(FHIRExportModel):
    system: str
    code: str
    display: str


class ObservationExport(FHIRExportModel):
    observation_id: str
    patient_id: str
    code: CodedConcept
    effective_at: datetime
    value_number: float | None = None
    value_text: str | None = None
    unit: str = ""
    unit_code: str = ""

    @model_validator(mode="after")
    def one_value(self) -> "ObservationExport":
        if (self.value_number is None) == (self.value_text is None):
            raise ValueError("Observation requires exactly one numeric or text value")
        return self


class ConditionExport(FHIRExportModel):
    condition_id: str
    patient_id: str
    code: CodedConcept
    recorded_at: datetime
    clinical_status: str = "active"
    verification_status: str = "confirmed"


class AllergyExport(FHIRExportModel):
    allergy_id: str
    patient_id: str
    substance: CodedConcept
    recorded_at: datetime
    category: str = "medication"
    criticality: str = "unable-to-assess"
    clinical_status: str = "active"
    verification_status: str = "confirmed"


class MedicationRequestExport(FHIRExportModel):
    medication_request_id: str
    patient_id: str
    practitioner_id: str
    medication: CodedConcept
    authored_at: datetime
    dosage_text: str = Field(min_length=1)
    status: str = "active"
    intent: str = "order"
