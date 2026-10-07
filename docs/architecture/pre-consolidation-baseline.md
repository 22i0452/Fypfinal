# Pre-Consolidation Baseline

Recorded: 2026-07-22

## Existing Start Commands

```powershell
# Desktop Urdu receptionist
.\.venv\Scripts\python.exe main.py

# Legacy session-authenticated consultation pages (port 5000)
.\.venv\Scripts\python.exe web_server.py

# Standalone Module 2 workspace (port 8001)
Set-Location "Module 2"
..\.venv\Scripts\python.exe soap_server.py
```

The target replaces the two web commands with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The desktop receptionist remains a separate local client but shares domain services and storage adapters. No second web server will remain necessary.

## Existing Route Contract

### Legacy consultation server

- `GET /` redirects to `/consultation/login`
- `GET /consultation/login`
- `GET /consultation/dashboard`
- `GET /consultation/patient/{file_name}`
- `POST /api/consultation/signup`
- `POST /api/consultation/login`
- `POST /api/consultation/logout`
- `GET /api/consultation/me`
- `GET /api/consultation/patients`
- `POST /api/consultation/patients/seed`
- `GET /api/consultation/patient/{file_name}`

### Standalone Module 2 server

- `GET /`
- `GET /branding/logo`
- `GET /branding/icon`
- `GET /api/patients`
- `GET /api/patient/{patient_id}`
- `GET /api/notes`
- `POST /api/notes`
- `POST /api/notes/{note_id}/approve`
- `POST /api/notes/{note_id}/finalize`
- `POST /api/patient-assistant`
- `WS /ws`

## Baseline Behavior

- SQLite doctor signup/login creates a signed browser session.
- Existing SQLite helpers rely on connection garbage collection instead of explicitly closing connections; this can leave test databases locked on Windows.
- The old dashboard and patient detail require that session.
- Module 2 serves its workspace independently and uses browser-local UI authentication.
- Module 2 HTTP authorization trusts development headers by default.
- Module 2 WebSocket accepts recording without a backend session, encounter, workflow, or processing consent. This behavior must intentionally become stricter.
- Booking normalization and duplicate detection read slots from patient JSON files.
- Active LLM/STT operations use the secure gateway.
- The mock translation-to-SOAP path produces a review-required draft.

Security tightening is considered compatible when the same legitimate user journey remains available after backend login, verification, appointment/workflow preparation, and consent. Unauthenticated recording is not a behavior to preserve.
