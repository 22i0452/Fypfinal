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
