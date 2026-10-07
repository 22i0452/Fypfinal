# MedFlow process and voice studio

This refinement keeps the existing FastAPI application and Replit run configuration. The doctor and receptionist have separate workspaces, with the same patient, appointment and encounter records connecting the handoff.

## What to demonstrate

1. Open `/Receptionist`. The call studio opens with **Voice call** selected. Start Samra, wait for playback, tap Mic, speak, and tap Stop. The waveform comes from actual microphone PCM. Browser voice currently uses recorded turns, rather than continuous duplex audio.
2. Watch the confirmed fields and the current question beside the Urdu/English conversation. A pending answer is labelled as awaiting confirmation. Availability and record creation happen on save; a requested time is not an appointment confirmation.
3. Confirm the final summary. A successful save shows the actual stored booking result and doctor handoff. Other receptionist scenarios are explicitly conversation simulations and do not change records.
4. Open the doctor handoff, verify the patient, check in, and capture the patient's recording/AI choices. Record the consultation and stop.
5. Inspect **Audio → Speech → Roles → Translate → SOAP → Checks**. The server sends real start/completion/failure events. Each stage keeps its artifact, measured duration and, where the gateway provides it, actual provider/model attempts. No accuracy percentage or progress percentage is fabricated.
6. Click a role stage or a statement source to inspect the original turn. Urdu and clinical English share the same utterance ID. Role labels describe text attribution; they do not measure the number of distinct voices. Audio timestamps are not invented when alignment is unavailable.
7. Use **Review speaker roles** to correct a role or attendant relation on an unapproved draft. Translation and SOAP regenerate into a new version of the same note. The old transcript and note version remain stored. This performs real provider calls and requires another doctor review.
8. Review, edit and approve the SOAP note, generate the approved visit summary, and complete the encounter. The original booking and encounter remain the same throughout.

The process inspector expands during processing and becomes compact afterward. Clicking a stage opens its artifact. **Replay** presents saved events at a condensed pace, clearly labelled, without new API calls or record changes. Displayed durations remain the original measurements. Live processing has no artificial delays.

## Source attribution

SOAP providers may return `claim_sources` alongside the existing section narratives. Each entry contains an exact consecutive span of that section and specific transcript IDs. A mapping must cover the unchanged narrative, and every attached ID must exist in that transcript. If mappings are absent or sanitization changes a narrative, its source links are withheld and the draft flags the limitation. The broad note-level evidence array is never copied onto every statement.

All model-provided attributions remain `REVIEW_REQUIRED`. Reference existence and clinical correctness are different checks. Existing schema, unsupported-fact and medication safeguards remain active. The SOAP output budget is 3,200 tokens to accommodate the additional attribution JSON; no extra attribution-only model request is added.

## Durable events

`process_runs` and `process_events` are initialized automatically in the configured SQLite database. Each run is bound to a patient, encounter and capture ID. Events carry `run_id`, `sequence`, `stage`, `status`, `at`, optional measured `duration_ms`, and an artifact. The consultation WebSocket still includes patient/workflow/encounter/capture identifiers. The frontend rejects mismatched envelopes.

The authenticated workflow-context endpoint returns the encounter's latest run, after patient authorization. This restores submitted processing on reload. Run artifacts contain clinical text and follow the same access boundary as the encounter; raw audio and API credentials are not stored in traces. Initial capture artifacts are labelled as the initial draft run, even after later note edits.

Gateway telemetry uses a request context, including thread propagation, to collect only that request's actual model attempts. Receptionist extraction reports the provider that answered or the local extraction fallback. TTS reports the backend returned by synthesis. Token counts are not displayed because the current adapters do not expose them.

## Receptionist continuity and recovery

Browser and telephone new-patient booking now use the same `BookingFlow` and receptionist integration service. The telephone session exposes its real collected state and save result. A confirmed summary can request a stored appointment; slot conflicts remain conflicts and require an available alternative. Telephone transport/playback still needs testing with real Telnyx credentials and calls.

The short-answer speech filter now accepts names, ages and yes/no replies in Urdu or English. Clearly empty/non-language output and repeated nonsense remain rejected. Meaning and clarification belong to the booking state machine. Microphone, transcription and playback actions lock scenario changes while in flight, and failure returns control to the caller.

## Replit update

Pull `main` from `22i0452/Fypfinal`, restart the existing **Run MedFlow** workflow, and refresh the Preview. The original run files and deployment setup are retained. No ZIP import, framework conversion or redesign by Replit Agent is required.

Local database and call recordings shown in the Git panel are runtime data. They do not need to be staged with this source update. The ignore rules prevent new runtime databases/audio from entering future commits; already tracked legacy data is unchanged by this commit.

## Validation and remaining limits

See `VALIDATION.md`. Synthetic browser checks verify the real browser handlers and API/workflow wiring; they do not establish live provider quality, real microphone quality, Urdu transcription accuracy or clinical validity. Incremental consultation STT, acoustic speaker counting, audio alignment and a measured accuracy evaluation remain future capabilities.


## Reception speech recovery and doctor routing

The receptionist STT prompt is now a short vocabulary hint, biased to the current field. It contains no example names, phone numbers or dates. Original WAV duration, RMS and peak are measured before normalization; gain is capped at 4x and near-silence is not amplified. Exact silence is reported separately from provider failure. This is signal measurement, not an acoustic speech-confidence score.

The existing single extraction request also receives collected fields and the last four conversation turns, and returns a faithful interpreted Urdu answer plus English translation. Only fields stated in the current caller turn may be collected; context must not invent a name, digit, symptom or date. Exact short confirmations use a local parser, without an LLM request. Uncertain interpretation does not advance the booking state. Raw recognized text is always retained in the response and shown for editing/retry; prompt echoes are held for review. Text entry remains available in voice mode. This does not claim acoustic diarization or measured live ASR accuracy.

Reception configuration defaults to the active signed-in doctor's practitioner ID, then the configured primary account when available. Name-based prioritization has been removed. Manual intake displays the selected doctor; receipts use the server's saved appointment doctor, status, patient ID and appointment ID. Pending REQUESTED appointments are visible immediately in the assigned doctor's pending reception requests, before identity verification. Verification confirms the existing request; check-in and consultation continue with that same appointment. Workspace lists refresh on return. An inaccessible handoff displays an account/access message rather than silently opening an empty list. Existing assignments are not retroactively changed.

Voice booking with 'any doctor' prefers the initiating signed-in doctor in that department. An unmatched or ambiguous named doctor is not silently substituted. If the intake saves but the appointment cannot be made, **Continue appointment with saved intake** opens the form with the original patient, workflow and intake token, allowing a real slot selection without creating another patient. Available alternatives remain selectable. A saved intake is not labelled as forwarded unless an appointment exists.

Pull the latest GitHub main in Replit, restart Run MedFlow and refresh the preview. Keep API keys in Secrets. Live Urdu recognition, physical microphone quality and actual telephone transport still require a provider-backed test on Replit.


## Brief replies and real doctor choices

The voice demo captures PCM in 1024-sample blocks and accepts clips from 60 ms; the previous 4096-sample buffer could miss very brief replies before Stop. Short WAVs receive 120 ms leading and 240 ms trailing silence during preparation, while displayed duration/RMS/peak remain measurements of the original recording. Confirmation prompts carry no vocabulary bias; department vocabulary is only supplied when collecting a department. This reduces opportunities for unrelated 'General Medicine' prompt echoes; live ASR improvement still requires real audio evaluation.

Clear short confirmations, ages in digits/Urdu/English number words, complete numeric phone answers, first-visit replies, explicit absence of medical history, basic stated symptom words, repeated department names and 'any doctor' use deterministic contextual parsing. Corrections, ambiguous numbers and multi-field sentences still use the existing extractor. Raw recognized words remain visible. First-visit fallback never assumes No from an unknown answer.

At the doctor step, the actual active clinic doctors in the selected department are displayed and the first three names are spoken. Mixed Urdu speech retains the real doctor names rather than stripping Latin names. The optional suggestion is based on the earliest listed opening in the next 14 days, with the opening shown; it makes no clinical judgment. No badge appears without a listed opening. Say a name/number, 'recommended', or choose a card. List numbering retains the displayed order, and numbered/card selections carry the exact practitioner ID through booking, including duplicate doctor names. Slot availability is rechecked when saving. These scheduling queries are local; no additional AI recommendation request is made.


## Optional hands-free receptionist conversation

The real new-patient browser booking has a **Hands-free** switch. It is off by default on a fresh browser; the user's preference is stored locally. Switching it off restores the existing Mic/Stop controls. Chat, consultation recording, phone transport and other simulated scenarios retain their existing inputs. Switching modes preserves the current accepted booking history. Preferences survive a reload, but a reload never starts microphone access automatically.

Hands-free requests the microphone when the user starts a call or enables it during a call. A dedicated local controller uses AudioWorklet PCM frames when supported, with a ScriptProcessor fallback. Signal endpointing uses adaptive energy thresholds and bounded buffers; it is not neural speech recognition, an acoustic confidence score or streaming transcription. A 320 ms rolling prebuffer preserves the beginning of an answer. Sustained silence submits one WAV to the existing STT → contextual extraction → TTS path. Confirmation silence is 850 ms, ordinary fields 1100 ms, and phone/history/complaint/time 1600 ms; these defaults need tuning against live recordings. Continuous recording is capped at 25 seconds and held for explicit Send now or re-recording instead of repeatedly submitting noise. Silence and low input do not make API requests. The waveform and state labels follow actual input/controller/playback events.

Pause disables microphone tracks and clears unsubmitted capture; Resume requires an explicit action. Send now ends a detected answer before silence endpointing. Repeat question replays the latest agent response without a new booking turn. Interrupt / speak now stops and settles playback before collecting the next reply. Listening during playback is gated by default, with a 250 ms margin after playback. **Automatic interruption is a separate, experimental checkbox, off by default**, requiring sustained input; use headphones and evaluate physical echo before enabling it for a demo. It does not interrupt the final, already-confirmed booking acknowledgement.

Uncertain recognized words are retained for editing, and automatic listening pauses for review. Transcription failure, backgrounding, navigation away, offline state, disconnected tracks or stalled capture give an explicit recovery state. Typing remains available. End releases microphone, playback and buffered audio, aborts frontend requests and invalidates the session so late results cannot write into a new call. Aborting a browser request does not guarantee cancellation of a provider request already running on the server. The existing partial-intake save and explicitly confirmed appointment rules remain unchanged; silence, pause and interruption cannot confirm a booking.

No extra API key, speech provider or model download is required. Both modes use the configured existing adapters. This delivers automatic completed-turn conversation, not incremental word-by-word captions or full streaming duplex transport.

Reproducible checks: `node --test tests/test_voice_engine.cjs`; `node tests/test_hands_free_browser.cjs` with Playwright/Chromium and Python app dependencies installed. For an external Chromium binary, set `QA_CHROMIUM_PATH`. The browser fixture runs in a temporary database on localhost:8766 and its audit endpoints exist only in the test fixture. QA uses synthetic microphone signal and provider answers. Physical Android microphone quality, live Urdu ASR accuracy, stationary room noise and loudspeaker echo still require real testing on Replit.


## Shared evidence and technical inspection

Reception, consultation transcript and SOAP use the same small dot/badge palette: ivory for received data, sage for a recorded check/confirmation, amber for review, rose for a failed check and muted grey for missing or unassessed information. Labels and details accompany the colours. Completion of an API stage is distinct from clinical correctness. There are no invented percentages or word-confidence scores.

Reception field cards animate only when their actual value or confirmation changes. Click a field to inspect its original caller wording, accepted interpretation, normalization rule, source turn ID, extraction method/model when reported and separate caller confirmation. Early multi-field answers retain their original source; corrections retain at most two earlier interpretations and clear confirmation. History round-trips preserve the receipt; legacy calls without receipts show source unavailable. An uncertain turn records review without changing accepted fields. Opening the inspector pauses and mutes hands-free capture, including during processing; closing it requires explicit Resume. Manual Mic/Stop stays available. Manual intake labels distinguish locally entered values from server-stored values, and the saved handoff inspector exposes real patient/workflow/appointment/practitioner IDs and REQUESTED vs CONFIRMED state.

SOAP highlights are clickable complete statements, not independently scored words. A report for each saved version checks attached source IDs against that version's saved transcript, and performs an exact substring comparison after whitespace normalization. It retains original wording and paired English. Exact text comparison is unassessed when no verbatim match exists; it does not measure semantic entailment, translation accuracy, or clinical correctness. Source links remain model attributions. Missing placeholders stay grey even after approval. Authenticated doctor approval is a separate receipt with actor/time and current version. Unsupported or unknown-source statements are flagged, never approved by a source-link check alone.

The review overview contains statement, source-linked, review, missing and failed counters with filters. An inspector can locate the actual transcript turn. Technical details expose real claim/note/utterance/run IDs, version, methods and measured timings. Local edits immediately remove stale statement highlights/checks for the edited section; saving refreshes the server's new claim IDs and report. Regeneration and role corrections use the new transcript/version. Capture process artifacts remain explicitly labelled initial-draft artifacts after later edits and approval. Switching visits closes the inspector and clears scoped entries. Motion respects reduced-motion preferences.

These receipts add local structural checks and UI only. No extra provider request, key, model download, artificial API delay or SHAP implementation is added. Calibrated confidence, semantic entailment, acoustic speaker separation/counting, word-level timing and a measured clinical evaluation remain future-phase work. Replay remains labelled saved-event presentation.
