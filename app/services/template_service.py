from __future__ import annotations

from medflow.domain.models import ClinicalTemplate
from medflow.repositories.protocols import TemplateRepository


DEFAULT_TEMPLATES = (
    ClinicalTemplate(
        template_id="TPL-GP-01",
        name="General Practice SOAP",
        sections=["chief_complaint", "subjective", "objective", "assessment", "plan", "follow_up"],
    ),
    ClinicalTemplate(
        template_id="TPL-SHORT-01",
        name="Short Consultation",
        sections=["subjective", "objective", "assessment", "plan"],
    ),
    ClinicalTemplate(
        template_id="TPL-DETAIL-01",
        name="Detailed Consultation",
        sections=[
            "chief_complaint",
            "history_of_present_illness",
            "medical_history",
            "subjective",
            "objective",
            "assessment",
            "plan",
            "follow_up",
        ],
    ),
    ClinicalTemplate(
        template_id="TPL-DM-FU-01",
        name="Diabetes Follow-Up",
        sections=["interval_history", "medications", "observations", "assessment", "plan", "follow_up"],
    ),
    ClinicalTemplate(
        template_id="TPL-CUSTOM-01",
        name="Custom Clinic Template",
        sections=["subjective", "objective", "assessment", "plan"],
        custom=True,
    ),
)


class TemplateService:
    def __init__(self, templates: TemplateRepository) -> None:
        self.templates = templates

    def seed_defaults(self) -> None:
        for template in DEFAULT_TEMPLATES:
            if self.templates.get(template.template_id) is None:
                self.templates.save(template)

    def list_active(self) -> list[ClinicalTemplate]:
        return sorted(self.templates.list(active_only=True), key=lambda item: item.name)

    def require_active(self, template_id: str | None) -> ClinicalTemplate:
        selected_id = str(template_id or "TPL-GP-01").strip()
        template = self.templates.get(selected_id)
        if template is None or not template.active:
            raise ValueError("Selected clinical template is unavailable")
        return template
