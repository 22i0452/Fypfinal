# Publish the Medflow FYP demo on Replit

This is a password-protected synthetic-data demo. The remaining patient portal,
real SMS delivery and clinical production release stay in the next phase.
No Replit Agent coding is required for this release.

## One-time setup

1. Pull **22i0452/Fypfinal → main** into your existing Repl. Preserve your
   existing provider secrets; do not commit them to GitHub.
2. In Replit's Database tool, create/connect a SQL database. Replit supplies
   `DATABASE_URL`. In Publishing, create/connect the **production database** too;
   development and published databases are separate. Keep that same production
   database when republishing. Do not paste the development URL over its binding.
3. Add these Replit Secrets and include them in the published deployment:

   | Secret | Value |
   | --- | --- |
   | `SESSION_SECRET` | Random secret of at least 32 characters. Keep it stable across restarts. |
   | `DEMO_ACCESS_PASSWORD` | Your private demo login password, at least 12 characters. |
   | `OPENROUTER_API_KEY` | Your existing working OpenRouter key. |
   | `MEDFLOW_LLM_PROVIDER` | `openrouter`, if using OpenRouter for the existing doctor pipeline. |

   Keep any existing STT/TTS model and provider settings that already work.
   `GROQ_API_KEY` remains necessary if you deliberately keep Groq selected for a
   task. Creating new keys is unnecessary. No SMS key is needed for this demo.
   `OTP_SECRET` is optional here; it defaults to the session secret and SMS OTP is
   unavailable in demo mode. Never use the public login emails as the password.

4. Click Run. Open `/healthz` (expect `{"status":"ok"}`), then sign in at
   `/consultation/login`. The login screen offers the three fictional accounts:

   | Doctor | Login | Reusable patient |
   | --- | --- | --- |
   | Dr. Ayesha Khan / General Medicine | `ayesha@demo.medflow.invalid` | Hamza |
   | Dr. Bilal Ahmed / Cardiology | `bilal@demo.medflow.invalid` | Maryam |
   | Dr. Sara Malik / Pediatrics | `sara@demo.medflow.invalid` | Ali, accompanied by mother |

   All three use your `DEMO_ACCESS_PASSWORD` when first created. Seeding does not
   reset existing passwords or overwrite patient edits. Changing the secret
   later does not reset these saved accounts. Use these accounts for reception
   too; manual and voice intake assign the selected doctor.

## Publish

Use Autoscale with **maximum servers = 1**. The configured process runs a single
FastAPI worker for the HTML, APIs, audio and WebSockets on one port. Its call
sessions and test subprocesses are intentionally in memory: multiple replicas
would require shared session/event infrastructure and are outside this demo.
Browser voice calls require HTTPS, which the published Replit URL provides.

The repository already sets:

```
Build: python -m pip install -r requirements-deploy.txt
Run:   python scripts/run_demo.py --published
```

The publish command enforces `APP_ENV=demo`, PostgreSQL storage, seeded fictional
profiles, disabled mock OTP and enabled authenticated demo testing. It stops
with an actionable error if the database or required secrets are missing.
The old static Vite preview and `/__api-template` service are not the release.
Keep the PostgreSQL URL's own SSL settings; do not force SSL on/off separately.

## What stays saved

Doctor accounts, patients (including new intake), assignments, appointments,
attendance requests, workflow state, encounters, consent, audit history,
transcripts, SOAP versions, summaries, code suggestions, templates, consultation
review checkpoints and demo testing reports are in PostgreSQL.

Restarting or republishing against the same database preserves those records.
The app never automatically deletes or resets them. Active audio conversations
must be restarted after a deployment. Raw audio files and temporary TTS playback
are not durable recordings; transcripts and visit records remain saved.
Make database backups before any deliberate reset or migration.

## Optional: keep old local JSON/SQLite records

A new production database starts with the fictional profiles above. It does not
silently upload old workspace patients. If the old records are fictional and you
want to import them, stop the app and run this **before starting it against an
empty target database**:

```
python scripts/migrate_demo_storage.py
```

Set `DATABASE_URL` to that empty target, and leave the source paths at their old
values (`MEDFLOW_DATABASE_PATH`, `MEDFLOW_PATIENT_RECORDS_DIR`,
`MEDFLOW_GENERATED_NOTES_DIR` if customized).
The importer validates JSON models, copies clinic records in one transaction,
retains source files and refuses to overwrite a used target. If startup already
seeded the target, do not delete its records: use a new empty database for import.
Run this separately for production only if you intend to copy those synthetic
records; workspace files are not automatically production data.

## Five-minute release check

- Sign in with each seeded doctor; verify each has their reusable patient.
- Create a new **fictional** patient through reception, choose doctor/time, open
  their doctor's pending handoff, review details and record attendance manually.
- Complete a voice encounter; review transcript medicines; generate, edit,
  submit and approve SOAP. Open Medicine evidence and both PDF downloads.
- On `/testing`, run the synthetic pack and export its report PDF. Live text
  testing is off by default; optionally enable `DEMO_LIVE_TEXT_ENABLED=true`.
- Restart and verify the new patient, appointment and saved note still appear.
  After publishing, repeat the microphone/WebSocket check on the published URL.

Synthetic checks measure software behavior with fixed inputs and controlled
provider responses; they do not measure microphone accuracy, acoustic third
speaker identification or clinical correctness. The PDF Visit Summary copies
the saved Plan exactly and adds no dose, frequency or treatment. Unapproved
notes export as DRAFT. Evidence and test PDFs do not make model claims proven.

Official Replit references:
[Database](https://docs.replit.com/features/data-and-storage/sql-database),
[Development vs production](https://docs.replit.com/features/data-and-storage/development-and-production),
[Publishing types](https://docs.replit.com/features/publishing/deployment-types),
[Ports](https://docs.replit.com/features/project-setup/ports).

## Validation for this release

118 synthetic Python tests passed: 90 existing clinic/consultation/medicine
regressions and 28 release/report checks. This includes the PostgreSQL schema,
bound queries, seeding, rollback, booking conflicts, record reload and migration
using a real PostgreSQL SQL engine (PGlite over offline stdio). The live psycopg
network transport and Replit deployment were not exercised here; verify them
with the release check above. The in-app 20-case synthetic pack also passed.
PDF pages were rendered and inspected; frontend syntax and real evidence markup
were checked. No live LLM/audio accuracy or full browser end-to-end result is
claimed. The desktop recorder suite requires hardware-related packages excluded
from this web deployment.
