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
