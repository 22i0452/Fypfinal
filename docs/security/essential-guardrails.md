# MedFlowAI Essential Guardrails

This document describes the essential security controls implemented for the
MedFlowAI LLM workflow. It does not claim HIPAA compliance or complete
security. All automated verification uses synthetic data and a mock provider.

## Scope

The existing flow is preserved:

Urdu intake -> booking -> doctor workspace -> audio -> transcription ->
diarization/translation -> SOAP draft -> doctor review -> saved note.

## 1. Central Secure LLM Gateway

All LLM and STT operations route through `security_guardrails.gateway`.
Business modules no longer call Groq, OpenAI, or STT providers directly.
Provider SDK and HTTP calls are isolated in
`security_guardrails.provider_adapters`.

The gateway enforces task type, provider/model allowlist, safe errors,
timeouts, JSON parsing, PHI minimization, and privacy-safe audit metadata.

## 2. PHI Minimization

Text payloads are minimized before eligible external LLM calls. Patient names,
phone numbers, CNIC/national IDs, emails, addresses, MRNs, and unnecessary
appointment details are replaced with placeholders such as `[PATIENT_NAME]`,
`[PHONE]`, `[CNIC]`, `[EMAIL]`, `[ADDRESS]`, `[MRN]`, and `[APPOINTMENT]`.

Raw audio cannot be redacted before STT. STT is therefore allowed only through
an explicitly allowlisted STT task route. Calls to unapproved routes are
blocked.

## 3. Authorization And Agent Isolation

`security_guardrails.authz` defines actors, roles, action checks, and tool
restrictions. Backend record operations recheck authorization. Receptionists
cannot read SOAP archives. Translator and diarizer agents have no database,
filesystem, shell, or arbitrary network tools.

Development mode keeps a default doctor actor for local compatibility. Real
deployment must replace this with production authentication and patient
assignment.

## 4. Prompt-Injection Containment

LLM prompts now separate server-controlled instructions from untrusted patient
speech, transcripts, notes, and database content. The backend does not rely
only on malicious-word detection: authorization, tool restrictions, provider
allowlists, and schema validation remain enforced even when an injection is
present in transcript text.

## 5. Clinical Output Validation And Doctor Approval

SOAP outputs are validated with strict Pydantic schemas. Dangerous fields such
as `approved_by_doctor` are rejected. Unsupported objective findings,
diagnoses, medicines, or dosages are rejected or flagged by validation.

When the clinician has not stated an assessment or plan, the model may provide
a symptom-grounded differential and non-prescriptive management considerations
only under explicit `requires doctor confirmation` labels. These inferential
sections are stored as `REVIEW_REQUIRED`. They are not confirmed diagnoses,
orders, or prescriptions. AI-suggested medicine names, doses, routes, and
frequencies remain prohibited.

Objective findings are never inferred. If no measurements, examination
findings, or completed test results were documented, Objective states that
limitation. If model generation fails, the fallback preserves transcript facts
and evidence IDs without inventing a diagnosis or treatment.

Notes use these states:

- `AI_DRAFT`
- `REVIEW_REQUIRED`
- `APPROVED_BY_DOCTOR`
- `REJECTED`

LLMs cannot approve their own output. Only an authenticated doctor endpoint can
approve a note, recording doctor ID, timestamp, and note version.

## 6. Secure Logging, Storage, And Audio Retention

Audit events contain only privacy-safe metadata: event type, actor reference,
patient reference, action, result, request ID, timestamp, and sanitized
metadata. Logs must not contain patient names, phone numbers, CNIC, addresses,
transcripts, SOAP content, audio, API keys, access tokens, or full prompts.

Raw audio chunks are deleted after transcription by default. Optional audio
retention is consent-based and disabled unless
`MEDFLOW_AUDIO_RETENTION_ENABLED=true` is configured. The browser asks whether
the patient consented to retention before starting a recording.

JSON storage is kept for development compatibility only. Production deployment
requires a controlled database, TLS, encryption at rest, secure backups, real
identity/authentication, and operational audit retention.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_guardrails.py
```

Artifacts:

- `artifacts/security/guardrail-report.md`
- `artifacts/security/guardrail-results.json`
