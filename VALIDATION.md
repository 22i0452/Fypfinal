# Refinement validation — 7 October 2026

## Backend

Command: `python -m unittest discover -s tests`

The final run produced **127 results: 124 passed and 3 module import errors**. The unavailable modules were `test_receptionist_corrections`, `test_receptionist_integration`, and `test_receptionist_speech`; each could not import the native sounddevice recorder because PortAudio was unavailable in the execution environment. No assertion failures occurred in the runnable suite. This is not a claim that the complete suite passed.

The new continuity tests cover read-only visit opening, patient authorization, note-to-encounter reopening, disabled development shortcuts, refusal to complete an unapproved note, idempotent encounter completion, stale-summary suppression after amendment, failed-documentation retry with preserved resources and consent, rejection of invalid/unauthorized retries, and recovery after transcription failure or silence. WebSocket regression coverage verifies patient/workflow/encounter/capture identifiers on processing and SOAP messages.

All five changed JavaScript files passed `node --check`.

## Browser journey

Chromium ran against the actual FastAPI application with a temporary database, synthetic patients, test-only OTP verification, synthetic PCM audio, and the existing mock AI provider. These checks used real application APIs and the consultation WebSocket; they did not validate microphone sound quality or remote provider accuracy.

Verified:

- Login and loading the actual patient list.
- Opening a patient without creating a workflow or encounter.
- Starting a visit, OTP verification, selecting a real available slot, booking, check-in, and saving consent.
- Recovery after simulated microphone permission denial.
- Sending audio through the real consultation pipeline and saving an AI draft.
- Reloading during a deliberately delayed transcription, then retrieving the finished draft through server context polling.
- Editing and cancelling a section, blocking patient switching with unsaved edits, saving a new note version, and reloading that draft.
- Submitting for review, doctor approval, English patient-summary generation, and completion of the same workflow, appointment, and encounter.
- Reopening an archived note in the same completed encounter.
- Ignoring a deliberately mismatched patient/capture SOAP response.
- Reception patient intake, appointment request, doctor handoff, and verification confirming the same workflow and appointment.
- Disconnecting during capture, stopping the synthetic microphone track, resetting controls, and reconnecting.
- A deliberately failed transcription followed by explicit recovery into capture for the same encounter.
- Supplemental checks opened patient insight, clinical coding, records, reception intake, call studio, and live calls. These views had no horizontal overflow at all three tested widths. The patient assistant returned a response through the mock provider. A delayed assistant request also preserved its selected patient when clear/switch actions were attempted.
- No browser JavaScript errors in the complete journey or supplemental views.
- No horizontal page overflow at 1440, 1280, and 390 pixels in the checked workflow views.

## Limits

Live STT/LLM/Urdu translation, physical microphone capture, TTS playback, and telephony require the configured providers and hardware; they were not exercised end to end here. The tested English patient summary used the mock provider. The existing native receptionist GUI was not redesigned, and its blocked tests need a machine with PortAudio.

The final source is a refinement of the uploaded snapshot. It has not been pushed to GitHub or deployed to a public host. Existing clinical review and provider guardrails remain in place; no model training or new clinical capability is claimed.
