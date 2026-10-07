# MedFlow Clinical Studio refinement

This package contains the revised application source from the uploaded project. The main FastAPI application and existing provider configuration remain the entry points. No frontend build or external icon/font CDN is required.

## Run the application

Use Python 3.11 or later in a virtual environment, install `requirements.txt`, and copy `.env.example` to `.env` if you do not already have an environment file. Preserve your existing keys and clinic configuration when replacing an earlier checkout. Set a strong `SESSION_SECRET` and configure the providers used by your project.

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/consultation/login` for the doctor workspace and `http://127.0.0.1:8000/Receptionist` for reception. On a remote host, serve the app over HTTPS for browser microphone access. Configure `MEDFLOW_RECEPTIONIST_SERVICE_TOKEN` for the same-server receptionist APIs. Doctor assignments and existing authentication rules still control which patients appear.

## Visual system

The desktop interface uses obsidian backgrounds, restrained smoked glass, champagne accents, and muted sage status indicators. Cormorant Garamond supplies the editorial headings; Manrope supplies the clinical text and controls. Both are served locally with their licenses. Lucide icons are local assets, and icon-only controls retain accessible names and tooltips. Responsive layouts were checked at 1440, 1280, and 390 pixels.

The new shared styling covers login, today's workspace, patient preparation, capture and processing, SOAP review, completion and summaries, the record archive, patient insight, clinical coding, and web reception. The separate native Python receptionist GUI was not replaced.

## Guided visit

The doctor workspace now presents four stages: **Prepare → Consult → Review → Finish**. A persistent footer presents the next required action. Optional pre-visit briefs and coding are secondary tools rather than mandatory screens.

1. Opening a patient loads their visit without creating a workflow, cancelling appointments, or checking them in.
2. Starting a new visit is an explicit action. Verification, intake confirmation, booking, check-in, and patient recording choices remain explicit.
3. Reception follows Patient → Appointment → Handoff. Its doctor link opens the actual stored patient, workflow, and requested appointment. Doctor verification confirms that same booking.
4. After capture, the SOAP draft and source transcript are reviewed together. Section edits, source links, save, review, approval, rejection, version history, and approved-note export remain available.
5. The finish screen generates a patient summary from the current approved note. Completing the visit closes the same workflow, appointment, and encounter. Repeated completion requests are idempotent.

## Continuity and recovery fixes

- `GET /api/workflows/context/{patient_id}` is read-only and patient-authorized. Its optional `note_id` selects the encounter belonging to an archived note.
- Session storage retains only the selected user/patient/note identifiers and stage; clinical content is reloaded from the server. Saved drafts survive page reloads.
- WebSocket responses carry patient, workflow, encounter, and capture identifiers. The browser ignores a response that does not match its active recording.
- Patient/workspace changes are blocked while recording, processing, saving, or editing an unsaved note. Modal mutations also hold the selected identity while their request runs.
- Recording authorization times out cleanly; microphone errors release pending state. A disconnect stops capture, releases tracks, resets controls, and reconnects.
- Documentation processing is recorded on the server from the beginning of the pipeline. Reloading after submitting audio does not discard processing; context polling retrieves the saved draft when ready.
- Failed documentation or no detected speech has an explicit retry action. A legal workflow action returns the same encounter to capture; it cannot overwrite a saved or approved note. Required consent is checked again by the recording endpoint.
- After-visit summaries from an earlier note version are suppressed after amendment. The UI invalidates its summary cache when a note version changes.
- Coding controls follow the server feature flag. Reception slot conflicts show real alternatives rather than a false success. Scenarios that simulate conversations explicitly say they do not update appointment records.
- The legacy prepare-consultation shortcut is restricted to enabled development mode and preserves workflows already processing or awaiting review.

## Main changed files

| Area | Files |
| --- | --- |
| Doctor workspace | `scribe/index.html`, `scribe/assets/ui.js`, `scribe/assets/ui.css`, new `studio.js`, `studio.css`, `icons.js` |
| Local assets | `scribe/assets/fonts/`, `scribe/assets/vendor/` |
| Authentication | `consultation/login.html` |
| Reception | `receptionist/web/index.html`, `app.js`, `receptionist.css`, new `studio.js` |
| Visit context and completion | `app/routers/workflows.py` |
| Capture and background processing | `app/routers/consultation.py` |
| Failed documentation retry | `medflow/orchestration/workflow_states.py`, `clinic_workflow.py` |
| Current-version summaries | `app/services/after_visit_summary_service.py` |
| Regression coverage | `tests/test_visit_continuity.py`, `tests/test_prepare_consultation.py`, `tests/test_consultation_websocket.py` |

## Validation

See `VALIDATION.md` for the checked flows and remaining environment limits. The redesign does not introduce new models or claim to retrain the existing diarization, STT, translation, or SOAP providers. Provider selection still comes from the application's environment configuration.
