# MedFlowAI Remaining Upgrade Prompt

This is the original upgrade request with completed essential-guardrail work removed. Partial features remain only as explicit deltas. Preserve the working Urdu intake, booking, doctor workspace, audio, transcription, diarization/translation, SOAP draft, review, and saved-note flow. Use synthetic data and mock AI providers in tests. Do not claim compliance, certification, autonomous diagnosis/prescribing, or production readiness.

## Existing Work to Reuse

Do not reimplement these components:

- `SecureLLMGateway`, provider/model/task allowlists, provider adapters, and direct-provider bypass test
- PHI minimization and privacy-safe audit metadata sanitizer
- Fixed server prompts and prompt-injection containment baseline
- Basic role/action and patient authorization primitives
- Draft-only SOAP validation and unsupported-fact rejection baseline
- `AI_DRAFT`, `REVIEW_REQUIRED`, `APPROVED_BY_DOCTOR`, and `REJECTED` baseline states
- Doctor approval/finalization checks
- Default temporary-audio cleanup and configurable optional retention decision
- Existing synthetic guardrail verifier and security artifacts

Extend these components where listed below; do not create parallel replacements.

## 1. Baseline and Architecture Documentation

- Preserve all current routes/UI flows or provide backward-compatible adapters.
- Record current modules, endpoints, storage, LLM flow, reuse decisions, and modification risks.
- Maintain an incremental plan and truthful implementation-status document.
- Fix Module 2's CWD-sensitive import/startup behavior when integrating it.

## 2. Domain Models and Repository Boundaries

Add typed models for Patient, User/Practitioner, Appointment, Encounter, WorkflowSession, ConsentRecord, VerificationRecord, TranscriptUtterance, SOAPNote, SOAPNoteVersion, EvidenceReference, PreVisitSummary, ClinicalTemplate, CodeSuggestion, and AuditEvent.

Use stable generated identifiers; do not use names as IDs or new file names. Introduce repository interfaces for patients, appointments, encounters, notes, consents, verifications, workflows, templates, summaries, code suggestions, and audits. Keep legacy JSON as a development adapter and normalize existing files without silently rewriting them. Business services must not read JSON directly.

## 3. Clinic Workflow Orchestrator

Implement a deterministic, resumable `ClinicWorkflowOrchestrator` with validated transitions among:

`PATIENT_UNVERIFIED`, `PATIENT_VERIFIED`, `INTAKE_IN_PROGRESS`, `INTAKE_COMPLETED`, `BOOKING_REQUIRED`, `BOOKING_CONFIRMED`, `PATIENT_CHECKED_IN`, `CONSULTATION_READY`, `CONSULTATION_ACTIVE`, `DOCUMENTATION_PROCESSING`, `NOTE_REVIEW_REQUIRED`, `NOTE_APPROVED`, `ENCOUNTER_COMPLETED`, `CANCELLED`, `FAILED`, and `HUMAN_ASSISTANCE_REQUIRED`.

The orchestrator owns state transitions, identifiers, actor/patient/appointment/encounter links, recoverable failures, human routing, resume behavior, and privacy-safe events. LLMs must never change workflow state. Expose action-oriented APIs rather than unrestricted client-selected transitions.

## 4. Backend Authentication and Resource Authorization

- Choose and integrate one authoritative backend identity/session mechanism for the active Module 2 workspace and WebSocket.
- Remove trust in client-supplied role/actor/patient headers and the wildcard WebSocket doctor.
- Support receptionist, doctor, and administrator roles without granting administrators automatic clinical access.
- Check authorization for each patient, appointment, encounter, transcript, note, summary, and code-suggestion operation.
- Enforce `actor role -> LLM task` inside `SecureLLMGateway`.
- Make agent tool restrictions an enforced service boundary, not only a declared/tested set.

## 5. Patient Verification and Consent

Implement a deterministic `PatientVerificationService` with a safe development provider selected by the project owner. Store status, method, attempts, expiry, and result metadata; never retain a used plaintext OTP.

Persist separate encounter-scoped consent records for:

- `AUDIO_RECORDING`
- `AI_TRANSCRIPTION`
- `AI_DOCUMENTATION`
- optional `AUDIO_RETENTION`

Before WebSocket recording/audio processing, verify authenticated actor, authorized patient, valid encounter, required consents, and legal workflow state. Retention remains optional and disabled by default. Add focused controls to the existing workspace.

## 6. Complete Appointment Service

Wrap existing deterministic slot normalization/duplicate detection in `AppointmentService`. Add first-class IDs and statuses: `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, `NO_SHOW`.

Support availability, create, view, reschedule, cancel, check-in, doctor/department/location/visit-type selection, conflict prevention, and idempotency. The receptionist LLM may return structured intent only; backend code performs every operation and confirms success. Preserve the existing slot-selection UI.

## 7. Evidence-Linked Documentation

- Move clinical pipeline coordination from WebSocket code into a documentation service while retaining the WebSocket transport.
- Return STT segments with IDs and timestamps where the provider supports them; use explicit unknown timestamps otherwise.
- Make diarization return stable utterance IDs, `DOCTOR`/`PATIENT`/`UNKNOWN`, timestamps, original text, and review flags. Do not invent a speaker when uncertain.
- Make translation preserve utterance ID, speaker, timestamps, original text, and clinical English.
- Pass patient redaction context into eligible transcript-processing tasks.
- Change SOAP output to claim-level section items with `text`, `evidence_ids`, and support status, plus `missing_information`, `unsupported_claims`, and `warnings`.
- Validate every evidence ID against authorized transcript/structured-record evidence.
- Add a backward-compatible four-section rendering adapter.
- Add a focused View Source action that highlights supporting utterances.

## 8. Complete Note Lifecycle and Versioning

Extend the existing draft/approval baseline with:

- `AMENDED` state
- immutable `SOAPNoteVersion` history
- edit, submit-for-review, reject, approve, and versions endpoints
- authenticated doctor identity from the chosen backend session
- new version/amendment when an approved note is edited
- visible state labels and approve/reject actions in the existing UI
- no export, downstream clinical use, summary, or coding from an unapproved draft
- Patient Assistant using approved records by default and never accepting a browser-supplied draft as approved fact

## 9. Approved-Record Features

After Priority 1 is stable:

- Add stored, explicitly regenerated pre-visit summaries using approved records only, with evidence references.
- Add separately stored clinical templates: General Practice SOAP, Short Consultation, Detailed Consultation, Diabetes Follow-Up, and Custom Clinic Template. Use one template-aware generator.
- Add English, Urdu, and bilingual after-visit summaries generated only from approved notes. They must not add unsupported medicines, dosages, diagnoses, advice, or follow-up instructions. Add a print-friendly view.

## 10. FHIR, Coding, and PostgreSQL Extension Points

- Create a MedFlow domain-to-FHIR R4 mapper and configurable mock/development client. Do not replace internal models with raw FHIR or claim a real EHR connection.
- Create an ICD-10 coding-provider interface. Implement suggestions only after the project owner approves a coding source/provider. Suggestions require an approved note, evidence, confidence, and human approval; no billing or claims.
- Keep JSON as the development adapter and prepare a PostgreSQL repository adapter/interface only; do not claim it is production-ready without a configured database and migration tests.

## 11. Required Tests

Retain SEC-01 through SEC-12. Add synthetic/mock tests:

- FLOW-01 Existing demo path works
- FLOW-02 Illegal workflow transition rejected
- FLOW-03 Recording blocked without required consent
- FLOW-04 Recording allowed with valid consent
- FLOW-05 Duplicate appointment prevented
- FLOW-06 Appointment rescheduled safely
- FLOW-07 Cancelled appointment cannot start consultation
- FLOW-08 Diarization preserves utterance IDs
- FLOW-09 Translation preserves IDs and speakers
- FLOW-10 SOAP claims have valid evidence
- FLOW-11 Unknown evidence rejected
- FLOW-12 Unsupported facts flagged
- FLOW-13 AI note starts as draft
- FLOW-14 LLM cannot approve note
- FLOW-15 Authenticated doctor approves note
- FLOW-16 Approved-note edit creates version/amendment
- FLOW-17 Pre-visit summary uses approved records only
- FLOW-18 After-visit summary rejects unapproved note
- FLOW-19 After-visit summary introduces no unsupported advice
- FLOW-20 ICD suggestion rejects unapproved note
- FLOW-21 ICD suggestion remains evidence-linked `SUGGESTED`
- FLOW-22 Receptionist cannot approve notes
- FLOW-23 Cross-patient access denied
- FLOW-24 JSON repository supports legacy demo
- FLOW-25 FHIR mapping has expected R4 structures
- FLOW-26 Temporary audio cleanup works

## 12. Deliverables

Maintain/create:

- `docs/architecture/current-system.md`
- `docs/architecture/incremental-upgrade-plan.md`
- `docs/architecture/target-clinic-agent-architecture.md`
- `docs/architecture/integration-map.md`
- `docs/deployment/production-readiness-gaps.md`
- `docs/demo/clinic-agent-demo-script.md`
- `docs/IMPLEMENTATION_STATUS.md`
- `artifacts/clinic-agent-test-report.md`
- `artifacts/clinic-agent-test-results.json`

Mark each feature accurately as `IMPLEMENTED_AND_TESTED`, `IMPLEMENTED_NOT_FULLY_TESTED`, `SCAFFOLDED_ONLY`, `NOT_STARTED`, or `REQUIRES_EXTERNAL_SERVICE`. Do not treat file creation as feature completion.

## Implementation Order

1. Domain/repository boundaries
2. Workflow orchestrator
3. Authentication decision and integration
4. Verification and consent
5. Appointment lifecycle
6. Evidence-linked documentation
7. Note approval/versioning
8. Authorization/audit regression coverage
9. Pre-visit, templates, and after-visit summaries
10. FHIR mapper, coding interface, and PostgreSQL extension point

Do not commit, push, deploy, delete production data, or use real patient information without explicit instruction.
