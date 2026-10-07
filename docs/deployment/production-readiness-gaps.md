# Production Readiness Gaps

MedFlowAI is an FYP/development system. Passing repository tests does not make it HIPAA compliant, clinically certified, or production ready.

## Blocking Deployment Controls

1. Replace JSON clinical storage with a controlled transactional database and reviewed migrations.
2. Encrypt the database, retained audio, backups, and temporary storage at rest; test key rotation and restore procedures.
3. Terminate TLS at a reviewed reverse proxy and enforce secure headers, trusted hosts, request-size limits, and WebSocket limits.
4. Move API/session/OTP secrets to a secret manager; rotate any development credentials before deployment.
5. Add CSRF protection for state-changing cookie-authenticated HTTP routes and a documented CORS policy.
6. Select approved LLM/STT processors, contractual data-handling terms, regions, retention settings, and outage behavior.
7. Add real user provisioning, role administration, assignment governance, deactivation, and break-glass policy.
8. Define retention/deletion policy for notes, transcripts, audits, and optional audio; add scheduled enforcement.
9. Add centralized privacy-safe monitoring, alerts, dependency/container scanning, and incident response.
10. Perform independent threat modeling, penetration testing, clinical safety review, accessibility testing, and load testing.
11. Validate a real FHIR server and interoperability profile before claiming EHR integration.
12. Approve and license an ICD-10 source/provider before enabling runtime coding suggestions.

## Current Development-Only Areas

- SQLite is suitable for the FYP, not a large multi-user clinic.
- Patient/note/summary JSON adapters are explicitly development storage.
- Retained WAV files are access controlled by the app but are not encrypted.
- Development mock OTP is not SMS delivery; `SHOW_DEV_OTP` must remain false outside explicit local development.
- Generic provider timeouts do not guarantee transport-level cancellation for every SDK.
- STT does not currently preserve provider-native segment timestamps.
- Urdu after-visit translations should receive a defined doctor/patient release policy before use.

## Environment Checks Already Present

- Startup refuses `APP_ENV=production` with `SHOW_DEV_OTP=true`.
- Production requires stronger session and OTP secrets.
- Production with JSON clinical storage emits a clear warning.
- Unapproved STT/provider/model routes are blocked without fallback.
- Runtime ICD coding is disabled by default.
- Audio retention is disabled by default.
