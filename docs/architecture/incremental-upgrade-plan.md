# MedFlowAI Incremental Upgrade Plan

Updated: 2026-07-22

## Completed Safely

| Capability | Existing component reused | Change | Compatibility proof |
| --- | --- | --- | --- |
| Canonical web app | `web_server.py`, Module 2 workspace | One FastAPI app with routers/services and compatibility imports | Login/workspace regression tests |
| Central persistence | Existing SQLite doctor DB and patient/note JSON | One SQLite layer plus repository interfaces and JSON adapters | Repository and API tests |
| Secure AI pipeline | Existing gateway and Module 2 agents | Actor/task enforcement, patient context minimization, evidence identities | SEC-01..12, FLOW-08..12 |
| Workflow control | Existing sequential server flow | Deterministic action-based orchestrator and lifecycle service | FLOW-02, FLOW-07 |
| Verification/consent | Existing patient/workspace flow | HMAC mock OTP and four encounter-scoped decisions | Verification/consent/WebSocket tests |
| Scheduling | `booking_scheduler.py` concepts and slot UI | First-class idempotent AppointmentService and clinic seed | FLOW-05..07 |
| Documentation | diarizer, translator, SOAP generator | Structured utterances, template-aware evidence draft, source viewer | FLOW-08..14 |
| Doctor control | Existing note save/approve behavior | Immutable versions, submit/reject/approve/amend, finalization gate | FLOW-13..16, FLOW-22 |
| Approved-record features | Existing patient detail and note UI | Stored pre-visit brief, approved-only assistant, bilingual after-visit summary | FLOW-17..19, authorization tests |
| Interoperability boundary | New isolated adapter | FHIR R4 mapper and mock client | FLOW-25 |
| Coding boundary | New provider protocol | Approved-note/evidence/human-review service; provider disabled | FLOW-20/21 |

## Remaining Work

| Priority | Work | Why it remains |
| --- | --- | --- |
| Next | Provider-level STT timestamps | Current provider adapter returns plain text |
| Next | Select and validate an ICD-10 coding source/provider | Clinical governance decision required |
| Next | Decide whether Urdu after-visit text needs a second doctor approval state | Product/clinical policy decision required |
| Deployment | Replace JSON clinical storage and development audio storage | Production database/encryption/retention design required |
| Deployment | Add CSRF strategy, reverse-proxy TLS, secret manager, backup/restore and monitoring | Environment controls cannot be proven by repository tests |
| Integration | Configure and test a real FHIR R4 endpoint | External EHR credentials and conformance environment required |
| Later | Implement PostgreSQL schema and migrations | Explicitly excluded from this safe FYP consolidation |

## Compatibility Rules Preserved

- Legacy patient file names resolve as aliases; new writes use opaque patient IDs.
- Legacy notes normalize as version 1 without silent rewrites.
- The current four-section SOAP display remains while structured claims/evidence are retained.
- Existing URLs and startup imports remain available.
- JSON remains the development default.
- Unauthenticated or unconsented recording is intentionally no longer preserved.
