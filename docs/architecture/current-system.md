# MedFlowAI Current System

## Canonical Application

The deployable web application is `app.main:app` and runs with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

`web_server.py` and `scribe/soap_server.py` are compatibility imports of the same FastAPI app. They no longer define independently running servers. The desktop Urdu receptionist remains a separate local client.

## Request Path

```text
request or WebSocket message
  -> signed-session authentication
  -> role authorization
  -> patient/resource authorization
  -> workflow/lifecycle service
  -> deterministic domain service
  -> repository
  -> privacy-safe audit event
  -> response
```

LLM/STT work follows a separate controlled path:

```text
documentation service
  -> minimum task input
  -> SecureLLMGateway
  -> actor/task authorization + provider/model allowlist + PHI minimization
  -> approved provider adapter
  -> schema/clinical validation
  -> draft only
```

## Module Map

| Component | Current responsibility |
| --- | --- |
| `app/main.py` | FastAPI composition, sessions, request IDs, static mounts, all routers |
| `app/routers/` | Thin authenticated HTTP and WebSocket boundaries |
| `app/services/` | Verification, consent, appointments, lifecycle, documentation, note versioning, summaries, templates, and coding controls |
| `app/infrastructure/database.py` | One configured SQLite connection/schema/seed layer |
| `app/repositories/` | SQLite account/clinic/operational repositories |
| `medflow/domain/` | Typed clinic entities, enums, and opaque IDs |
| `medflow/orchestration/` | Deterministic workflow actions and legal transitions |
| `medflow/repositories/` | Protocols and atomic JSON development adapters |
| `security_guardrails/` | LLM gateway, provider adapters, PHI minimization, authorization, audit sanitization, SOAP validation, audio retention |
| `scribe/llm_diarizer.py` | Transcript-only structured speaker labeling; no repositories/tools |
| `scribe/translator.py` | Identity-preserving clinical English translation; no repositories/tools |
| `scribe/soap_generator.py` | Template-aware SOAP draft generation through the gateway |
| `scribe/patient_assistant.py` | Read-only Q&A from the authorized intake and latest approved note |
| `scribe/assets/` | Existing doctor workspace extended with verification, booking, consent, summaries, templates, evidence, and note controls |
| `app/fhir/` | Typed domain-to-FHIR R4 mapper for core patient/visit/clinical resources and an in-memory development client |

## Active Route Groups

- Authentication: `/api/auth/*` and backward-compatible `/api/consultation/*` aliases.
- Workspace and assets: `/`, `/workspace`, `/consultation/*`, `/assets/*`.
- Patients/workflows: `/api/patients`, `/api/workflows/*`.
- Verification/consent: `/api/verification/*`, `/api/consents/*`.
- Receptionist intake/schedule: `/api/receptionist/configuration`, `/api/receptionist/availability`, `/api/receptionist/intakes`, and `/api/receptionist/bookings`. Receptionist routes do not issue or verify OTPs.
- Scheduling: `/api/appointments/*`.
- Consultation: authenticated `WS /ws` and authorized `/api/audio/{audio_ref}`.
- Notes: `/api/notes/*`, including edit, submit, approve, reject, versions, and finalize compatibility.
- Summaries/templates: pre-visit, after-visit, and `/api/templates`.
- Assistant/coding/FHIR: `/api/patient-assistant`, disabled-by-default coding generation, and feature-flagged local `/api/fhir/*` export routes.

## Data Flow

```text
Urdu intake
  -> deterministic field validation, including numeric age and blood pressure
  -> opaque patient record
  -> server-listed slot selected
  -> REQUESTED appointment on assigned doctor's dashboard
  -> doctor-side verification challenge
  -> CONFIRMED appointment
  -> check-in encounter
  -> four independent consent decisions
  -> authenticated audio WebSocket
  -> approved-route STT
  -> stable-ID diarization
  -> identity-preserving translation
  -> evidence-validated SOAP AI_DRAFT
  -> immutable review versions
  -> authenticated doctor approval
  -> approved-only assistant / after-visit summary / FHIR / coding boundary
```

## Storage

- SQLite: users, sessions' backing identities, practitioner profiles, assignments, clinic seed data, appointments, workflows, encounters, verification challenges, consents, and durable privacy-safe audit events.
- JSON development adapters: patients, transcripts, notes/versions, templates, pre-visit summaries, after-visit summaries, and code suggestions.
- Audio: temporary chunks are cleared by default. Retained WAV files require both explicit encounter consent and `MEDFLOW_AUDIO_RETENTION_ENABLED=true`.

JSON remains compatible with the prototype but is not suitable for a large production clinic. Production requires a controlled database, TLS, encryption at rest, encrypted backups, secret management, monitoring, and tested recovery.

## Isolation Boundaries

- The diarizer receives transcript text plus minimum redaction context. It does not receive SOAP notes, appointments, or repositories.
- The translator receives structured utterances only. It does not receive booking, files, shell, databases, or arbitrary-network tools.
- The SOAP generator receives minimized intake fields and translated utterances, and can only return a draft.
- The Patient Assistant receives one authorized patient plus the latest approved note.
- Deterministic services alone modify appointments, workflow state, consent, approval, and persistence.

These are application capability boundaries, not OS process sandboxes.

## Known Gaps

- The STT adapter does not yet return provider-level timestamped segments.
- JSON clinical storage and retained development audio are not encrypted stores.
- Urdu after-visit translation needs an approved/configured gateway provider at runtime.
- No live FHIR endpoint or EHR conformance test exists.
- No clinic-approved ICD-10 source/provider exists, so runtime coding remains disabled.
- PostgreSQL is only an extension boundary; no migration was performed.
