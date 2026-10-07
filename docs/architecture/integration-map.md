# Integration Map

| Existing component | Architectural change | Integration point | Proof |
| --- | --- | --- | --- |
| `web_server.py` | Compatibility import | `app.main:app` | Login/dashboard regression |
| `scribe/soap_server.py` | Compatibility import | `app.main:app` | Workspace/WebSocket regression |
| SQLite doctor login | Central account and practitioner repository | Session dependency on every router/WebSocket | Auth tests |
| Patient JSON | `PatientRepository` adapter with opaque IDs/legacy aliases | Container and patient routes | FLOW-24 |
| Booking logic/UI | Deterministic `AppointmentService` and clinic seed | Appointment router + workflow confirmation | FLOW-05..07 |
| Audio WebSocket | Transport-only authenticated router | Consent/lifecycle/documentation services | FLOW-03/04/26 |
| `llm_diarizer.py` | Structured utterances with stable IDs | `DocumentationService.diarize` | FLOW-08 |
| `translator.py` | Preserve IDs, speaker, timestamps, and source | `DocumentationService.translate` | FLOW-09 |
| `soap_generator.py` | Template-aware draft through gateway | Evidence validator and note repository | FLOW-10..14 |
| Saved note JSON | Note/version repository | `NoteLifecycleService` | FLOW-13..16 |
| Patient Assistant | Approved-note-only context | Authorized assistant router | SEC-04/06 and route checks |
| Existing patient detail | Stored pre-visit brief | Summary router and focused workspace panel | FLOW-17 |
| Existing notes detail | Bilingual after-visit summary | Approved note route and print view | FLOW-18/19 |
| Security guardrails | Durable actor/task/resource enforcement | All AI calls and server actions | SEC-01..12 |
| New FHIR mapper | Isolated R4 export | Authorized `/api/fhir/*` routes | FLOW-25 |
| New coding boundary | Injectable provider and review state | Disabled runtime route until approval | FLOW-20/21 |
| Future PostgreSQL | Repository bundle factory | Not wired into current runtime | Scaffold only |

## Agent Inputs

| Component | May see | Must not receive |
| --- | --- | --- |
| Receptionist | Minimum intake and booking preference | SOAP archive, all patients, database tools |
| Diarizer | Current transcript and redaction context | SOAP, appointments, filesystem, database, shell |
| Translator | Current structured utterances | SOAP, bookings, repositories, arbitrary tools |
| SOAP generator | Minimized intake and current translated utterances | Other patients, approval capability, record writes |
| Patient Assistant | Authorized intake and latest approved note | Draft/rejected notes, other patients, write/approval tools |

Isolation is enforced by method signatures, actor/task gateway policy, and backend authorization. It is not an operating-system sandbox.
