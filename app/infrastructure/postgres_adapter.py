from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from medflow.repositories.protocols import (
    AfterVisitSummaryRepository,
    AppointmentRepository,
    AuditRepository,
    CodeSuggestionRepository,
    ConsentRepository,
    EncounterRepository,
    NoteRepository,
    PatientRepository,
    PreVisitSummaryRepository,
    TemplateRepository,
    TranscriptRepository,
    VerificationRepository,
    WorkflowRepository,
)


class PostgresAdapterNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryBundle:
    patients: PatientRepository
    appointments: AppointmentRepository
    encounters: EncounterRepository
    workflows: WorkflowRepository
    verifications: VerificationRepository
    consents: ConsentRepository
    notes: NoteRepository
    transcripts: TranscriptRepository
    previsit_summaries: PreVisitSummaryRepository
    after_visit_summaries: AfterVisitSummaryRepository
    templates: TemplateRepository
    code_suggestions: CodeSuggestionRepository
    audits: AuditRepository


class PostgresRepositoryFactory:
    """Extension point only; no PostgreSQL migration is performed in the FYP build."""

    def __init__(self, dsn: str, builder: Callable[[str], RepositoryBundle] | None = None) -> None:
        self.dsn = str(dsn or "").strip()
        self.builder = builder

    def build(self) -> RepositoryBundle:
        if not self.dsn or self.builder is None:
            raise PostgresAdapterNotConfigured(
                "A reviewed PostgreSQL schema, migration plan, driver, and repository builder are required"
            )
        return self.builder(self.dsn)
