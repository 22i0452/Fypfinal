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


## Guided consultation workflow — Batch 1 (7 October 2026)

Final checks: **24 targeted Python tests passed**, including ten guided-checkpoint regressions; **22 Node tests passed**. Full discovery produced **168 results: 165 passed, three existing native PortAudio import errors, zero assertion failures**. The unavailable modules remain `test_receptionist_corrections`, `test_receptionist_integration` and `test_receptionist_speech`. This is not a fully passing discovery suite. Startup TTS warmup was suppressed in full-suite QA; provider outputs remained synthetic. Python compilation, changed JavaScript syntax and whitespace checks passed.

Three completed Chromium journeys passed with zero page JavaScript errors:

- New guided journey used the actual microphone Start/Finish handlers with generated Web Audio. It covered default automatic mode off, capture-only presentation, reload during transcription, no SOAP call before review, saved transcript checkpoint, per-turn edit/cancel, role/English correction, unsaved patient-switch guard, saved revision and reload, failed SOAP recovery, retry and reload during generation, collapsed/open source panel, clickable evidence navigation, process expansion/collapse, doctor review/approval, approved summary and completion of the original appointment/encounter/workflow. It also exercised the on/off Automatic SOAP control, persisted preference and actual automatic capture path. Capture, transcript and SOAP screens fit 1440/1280/390 pixel widths without horizontal overflow.
- Existing clinical/evidence journey covered the optional automatic path, denied microphone permission, reload, source filters/inspection, SOAP amendments and stale-check clearing, immutable note versions, approval, archived visit reopening, receptionist booking/handoff, disconnect cleanup and pre-transcript failure recovery.
- Existing hands-free reception journey retained its complete booking, actual slots, final confirmation, exact practitioner and handoff. Manual mode, switching/history, pause, interruption, synthetic playback gating, editable replies, provider failure, explicit Send now, stale response, permission recovery and responsive layouts passed.

Backend checks additionally cover idempotent SOAP replay, concurrent generation (one provider call), stale revision rejection, unknown/blank corrections, cross-patient authorization, saved-original translation retry, interrupted server claims, both sides of checkpoint/workflow writes and an explicit re-record superseding the checkpoint without deleting its original transcript.

Reproduce with app dependencies plus Playwright/Chromium:

```sh
python -m unittest tests.test_guided_consultation tests.test_consultation_websocket tests.test_process_observability tests.test_workflow_orchestrator tests.test_prepare_consultation -q
node --test tests/test_evidence_ui.cjs tests/test_voice_engine.cjs
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_guided_browser.cjs
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_evidence_browser.cjs
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_hands_free_browser.cjs
```

Each browser script uses temporary synthetic records/providers. Guided/evidence scripts use localhost:8765 and must run sequentially; hands-free uses localhost:8766. Browser delay/failure controls exist only in the test fixture. No production delays, fabricated confidence or streaming captions were introduced. Live Urdu accuracy, physical microphones, actual paid-provider timings and clinical correctness remain unmeasured.


## Coding source chain and connected product — Batches 2–4 (7 October 2026)

Latest Python discovery: **179 results, 176 passed, three existing PortAudio import errors, zero assertion failures**. The three unavailable receptionist audio modules are listed above; discovery is not fully passing. The targeted coding/guided/backend group passed **31 tests** and evidence/voice Node tests passed **22 tests**. Compilation, changed JavaScript syntax and whitespace checks passed. TTS startup warmup was suppressed for discovery; provider responses remained synthetic.

Eleven new Python checks cover exact saved source chains, optional absent scores, current-version generation versus read-only history, stale review rejection, provider/partial-validation failure preserving pending results, late provider responses after note edits, reviewed-code deduplication, feature-off stored evidence, cross-patient authorization, missing transcripts, invalid reference rejection, serialized concurrent generation, unsupported provider systems and public-home/private-workspace routing.

Four completed Chromium journeys passed with zero page JavaScript errors: the new combined product journey plus guided consultation, existing clinical/evidence and hands-free reception regressions. Product QA covered public home/authenticated entrances, noninteractive Coming soon portal, SOAP coding disabled/dirty/error/retry states, current code approval, exact statement/source navigation, SOAP edits with immutable stale history, original workflow/encounter completion, and Home navigation with unsaved intake protection. Home, coding results and the source dialog fit 1440/1280/390 pixel widths without horizontal overflow. The other journeys preserve their existing recording, consent, booking, correction, handoff and recovery checks.

Reproduce new checks with app dependencies plus Playwright/Chromium:

```sh
python -m unittest tests.test_product_coding -q
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_product_browser.cjs
```

The product browser fixture uses a temporary database and explicitly synthetic code candidates. Its provider delay/failure/feature controls exist only in tests. It shares localhost:8765 with guided/evidence tests, so run those sequentially. These checks establish workflow and source integrity; they do not measure live ASR, physical microphone quality, paid-provider speed, clinical or coding accuracy, calibrated confidence or catalog validity. Batch 5's user-facing repeatable demo report is not included.
