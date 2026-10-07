# Target Clinic-Agent Architecture

## Design

MedFlowAI is a modular monolith for the FYP: one FastAPI process, deterministic clinic services, narrowly scoped AI components, and replaceable repositories. It is intentionally not a microservice or autonomous-agent mesh.

```mermaid
flowchart TD
    UI["Doctor workspace / Urdu intake"] --> API["FastAPI routers + signed session"]
    API --> AUTH["Role + patient/resource authorization"]
    AUTH --> ORCH["ClinicWorkflowOrchestrator"]
    ORCH --> APPT["AppointmentService"]
    ORCH --> CONSENT["Verification / Consent / Encounter services"]
    ORCH --> DOC["DocumentationService"]
    DOC --> GATEWAY["SecureLLMGateway"]
    GATEWAY --> STT["Approved STT adapter"]
    GATEWAY --> AGENTS["Diarizer / Translator / SOAP draft"]
    DOC --> NOTES["NoteLifecycleService"]
    NOTES --> APPROVED["Doctor-approved note version"]
    APPROVED --> PREVISIT["PreVisitSummaryService"]
    APPROVED --> AVS["AfterVisitSummaryService"]
    APPROVED --> ASSIST["Patient Assistant"]
    APPROVED --> FHIR["FHIR mapper"]
    APPROVED --> CODING["Coding provider interface"]
    APPT --> REPOS["Repository protocols"]
    CONSENT --> REPOS
    NOTES --> REPOS
    PREVISIT --> REPOS
    AVS --> REPOS
    REPOS --> SQLITE["SQLite operational adapter"]
    REPOS --> JSON["JSON development clinical adapter"]
    REPOS -. future .-> POSTGRES["PostgreSQL adapter"]
```

## Authority Rules

1. LLMs may classify, translate, summarize, or draft; they cannot authenticate, authorize, book, transition workflow state, approve notes, or write records directly.
2. Every route derives the actor from the signed backend session and rechecks the patient/resource association.
3. Agents receive explicit task inputs. They do not share unrestricted memory or call one another directly.
4. The orchestrator validates every state change after a service result.
5. Only the current `APPROVED_BY_DOCTOR` note version can feed patient-facing summaries, FHIR clinical documents, or coding suggestions.
6. Audio retention needs both encounter consent and an enabled server setting; failure cleanup always deletes chunks.

## Replacement Boundaries

- Provider adapters can change without changing clinical services.
- JSON repositories can be replaced with PostgreSQL implementations of the same protocols.
- The FHIR mapper can feed a HealthLake, HAPI FHIR, or other reviewed client.
- Coding providers can be injected only after the clinic approves a source and licensing terms.

## Trust Boundaries

- Browser and all patient/transcript/note text are untrusted.
- Session identity and authorization decisions are server controlled.
- LLM output is untrusted until schema, evidence, clinical, and doctor review gates pass.
- External AI and future EHR/coding endpoints are separate data processors requiring deployment review.
