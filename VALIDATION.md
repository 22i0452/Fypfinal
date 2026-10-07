# Validation — process and voice refinement

Validation uses isolated synthetic patient records and mock provider outputs. No real clinical record, physical microphone session or telephone call was used.

## Automated checks

- Full discovery: **150 results, 147 passed, 3 import errors, zero assertion failures**. The blocked modules are `test_receptionist_corrections`, `test_receptionist_integration`, and `test_receptionist_speech`; the execution environment lacks the native PortAudio library. This is not a fully passing suite.
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


## Brief replies and doctor choices regression (latest)

- Targeted recovery, demo-finish and process-observability modules: 28 passed, including six additional regression methods for short local answers, repeated confirmations/corrections, actual active doctor lists and spoken names, earliest-slot suggestions with no-slot handling, stable numbering/exact IDs for duplicate names, and silent short-clip margins preserving original measurements.
- Chromium submitted a brief real WAV capture with synthetic Urdu transcription, then completed short history/complaint replies and a repeated department answer. It checked actual doctor choices in the response/UI/TTS request, the earliest-opening badge, selection by exact practitioner ID, no browser errors, and 1440/1280/390 layouts.
- Re-ran the connected reception recovery browser journey: signed-in doctor default, receipt, pending queue, wrong-account explanation, editable prompt echo and continuation of a saved intake without a duplicate patient.
- Full discovery: 150 results, 147 passes, zero assertion failures and the same three native PortAudio import blocks. Physical microphone, live provider recognition accuracy and real telephone transport remain unmeasured.


## Optional hands-free conversation regression

- Local JavaScript endpointing/controller suite: **18 passed**, covering bounded silence/background buffers, 80 ms answers, internal number pauses, impulse/DC rejection, explicit send, recording caps, playback gating, sustained experimental interruption, muted pause, review, stale asynchronous work, pending-audio invalidation and late microphone permission cleanup.
- Existing Python recovery/booking/process modules: **28 passed**. No backend booking or provider adapter is replaced by the feature.
- New reproducible Chromium journey exercises real AudioWorklet capture, WAV upload, existing STT/extraction/TTS routes, all new-patient booking fields, explicit final confirmation, real slot selection, exact doctor and stored handoff. It also covers manual Mic/Stop, switching with history preservation, Pause/Resume, explicit interruption and playback settlement, synthetic playback-signal gating, opt-in automatic interruption, editable prompt echoes, provider failures, Send now, stopping during delayed STT, wrong-session response rejection, microphone permission recovery, navigation/offline muting, saved on/off preferences and no automatic microphone activation after reload.
- Browser audio and provider results are synthetic. Signal gating checks do not establish physical speaker echo cancellation or actual Urdu recognition accuracy. Real Android hardware and live providers remain unmeasured. The historical full Python discovery above still has three native PortAudio import blocks.

- Re-ran existing short-reply/doctor-choice and reception-recovery browser journeys: actual doctor selection, pending requests, account-scoped handoff notices and saved-intake continuation passed.

- Additional Chromium checks passed for the older-browser capture fallback, TTS failure recovery, context suspension, background-page muting and microphone disconnection/reconnect. Hands-free uses a non-sticky text composer so it cannot cover the live controls.


## Evidence visualization refinement (7 October 2026)

Final results: full discovery **158 results, 155 passed, 3 PortAudio import errors, zero assertion failures**; targeted backend group **61 passed**; shared evidence UI plus voice-controller tests **22 passed**. Both complete Chromium browser journeys passed with no page errors. Compilation, JavaScript syntax and whitespace checks passed.

New backend regressions exercise separate original/confirmation IDs, early-answer provenance, correction revisions, removal of stale receipts, history restoration, invalid-value rejection, unavailable legacy provenance, exact text vs paraphrase, unknown/absent references, unsupported statements, unmeasured confidence, actual approval versions and amendment source clearing. Existing role-correction tests also check the revised evidence report and speaker source. The browser shared-library tests exercise HTML escaping, exact-only marks, overlapping spans and unavailable status handling.

Reproducible commands (Python app dependencies and Playwright/Chromium required):

```sh
python -m unittest tests.test_evidence_checks tests.test_process_observability tests.test_note_lifecycle tests.test_booking_flow tests.test_reception_recovery tests.test_demo_call_finish -q
node --test tests/test_evidence_ui.cjs tests/test_voice_engine.cjs
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_evidence_browser.cjs
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_hands_free_browser.cjs
```

`tests/evidence_fixture.py` and the existing hands-free fixture use temporary databases and synthetic providers, never real patient records or audio. Audit endpoints exist only in those test fixtures. The clinical browser test covers real verification, booking, consent, WebSocket capture, reload during processing, statement/turn/capture inspectors, source navigation, filters, three modal widths (1440/1280/390), cancelled and saved edits, fresh report/version, approval, summary, completion, archive continuity, stale-patient events, manual saved-handoff IDs, same-appointment verification, disconnect/reconnect and failure recovery. The hands-free test additionally checks field receipts, separate confirmation IDs and microphone muting while inspecting, then resumes the real synthetic booking and existing recovery checks.

Synthetic QA establishes workflow wiring and evidence scope, not physical microphone quality, live Urdu speech accuracy, acoustic diarization, clinical correctness or calibrated confidence. The full Python discovery remains blocked in three legacy receptionist audio modules by missing native PortAudio; these import errors must not be described as a fully passing suite.
