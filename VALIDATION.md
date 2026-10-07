# Validation — process and voice refinement

Validation uses isolated synthetic patient records and mock provider outputs. No real clinical record, physical microphone session or telephone call was used.

## Automated checks

- Full discovery: **144 results, 141 passed, 3 import errors, zero assertion failures**. The blocked modules are `test_receptionist_corrections`, `test_receptionist_integration`, and `test_receptionist_speech`; the execution environment lacks the native PortAudio library. This is not a fully passing suite.
- Targeted process observability, demo-call booking and SOAP-quality tests: **22 passed**.
- Full Python compilation, changed JavaScript syntax checks and `git diff --check` pass.
- TTS startup warmup is suppressed for the full-suite QA run to avoid background network calls. Providers under test remain mocked; no physical audio test is claimed.

New regressions cover durable event sequences/artifacts, measured durations, patient access, actual failure stage, specific claim IDs, missing mappings, unknown evidence rejection, role correction into a new transcript/note version, stale version rejection, phone/browser booking continuity and idempotence, final-summary confirmation, and short Urdu/English voice answers.

## Browser journeys

The real local FastAPI application was tested through Chromium using synthetic providers:

- Read-only patient opening; explicit verification, real available booking, check-in and consent.
- Microphone permission denial releases capture controls.
- Actual consultation WebSocket submission with synthetic PCM.
- Reload during delayed transcription restores the submitted draft and all six persisted process stages.
- Source-button clicks highlight the corresponding transcript turn.
- Role/translation/check artifact inspection and labelled saved-event replay.
- Role correction regenerates the note on the same visit; edits and reload preserve the new version.
- Doctor review, approval, approved summary and encounter completion.
- Archived visit reopening preserves its exact workflow; stale capture envelopes are ignored.
- Receptionist form booking hands off to the same stored appointment and workflow.
- Connection loss stops microphone tracks; provider failure retries the same encounter.
- Browser voice defaults to Samra; synthetic Web Audio feeds the real PCM capture path, WAV upload, STT response, field confirmation, TTS request and playback callbacks.
- Active voice requests prevent scenario changes and premature call termination.
- Doctor process and receptionist voice views fit 1440, 1280 and 390 pixel widths without horizontal overflow. No page JavaScript errors were observed in the completed journeys.

QA audio is a generated tone and STT/TTS outputs are synthetic. Real provider keys, physical hardware, real Telnyx transport and Urdu accuracy still require testing in the user's environment. The native Python receptionist desktop GUI is unchanged.


## Reception recovery regression (latest)

- Nine added regressions cover original transcript retention, prompt-echo review, recent conversation/collected-field context, multi-field extraction, faithful bilingual interpretation, uncertain-state preservation, local confirmations, bounded audio gain, silence versus provider errors, active doctor defaults, account-scoped pending requests, persistence after an app restart and refusing silent named-doctor substitution.
- Targeted recovery, demo-finish and process-observability modules: 22 passed.
- Re-ran the complete connected Chromium journey through consultation, SOAP approval, completed visit and real receptionist handoff; no browser errors. Re-ran synthetic microphone capture, waveform, WAV upload, transcription, confirmation and TTS playback at 1440/1280/390.
- Additional Chromium recovery journey checks signed-in doctor selection, server receipt IDs/destination, pending request visibility, reload persistence, explicit wrong-account handoff messages, editing a prompt echo without losing fields, accepted corrected answer and visible translation. A saved voice intake with an unmatched doctor can resume into manual booking using the same patient and token. Providers and audio remain synthetic for QA.
