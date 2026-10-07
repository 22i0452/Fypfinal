# Bilingual receptionist corrections

## Conversation behavior

The receptionist uses one explicit intake record instead of reconstructing active
values from previous assistant questions. Each mutation increments a revision and
invalidates the displayed summary and its confirmation.

- English, Urdu script and Roman Urdu correction phrases share the same states.
- A patient may interrupt any question to correct earlier information.
- An unspecified retraction asks which fields need correcting.
- Named fields are marked as needing correction and excluded from active output.
- A proposed replacement is validated and read back. An affirmative reply applies
  it to the draft. "No more corrections" also includes already supplied, validated
  replacements in a fresh full summary, but never approves or forwards that summary.
- Multiple corrected fields are collected individually and confirmed together.
- Rejecting a proposal does not silently restore the withdrawn answer.
- An explicit restart requires confirmation before clearing the intake.
- Correcting first-visit status invalidates visit type and slot; correcting the
  department invalidates doctor and slot; changing doctor or visit type invalidates
  the slot. Availability is refreshed and checked again by the booking server.
- Every correction requires confirmation of a fresh, complete summary.
- A forwarded conversation is frozen. Existing records are corrected by the
  assigned doctor through the workspace's Correct intake action.

The spoken language can switch with the patient's English, Urdu or mixed response.
English speech uses an English TTS voice; Urdu speech uses the existing Urdu
voice. Names and phone numbers remain local values and are never synthesized by
the intake model.

## Finishing corrections

"I don't want to correct any more information", "Nothing else needs changing",
"مزید تبدیلی نہیں کرنی", and "Ab aur koi tabdeeli nahi karni" end correction mode.
The controller recognizes these as whole control replies before looking for
correction keywords. "No more pain", unfinished replies, and exceptions such as
"no more changes except my age" do not finish corrections.

The full current record is read back, including the corrected values. In the
desktop UI the microphone then pauses at Ready to forward, and Save & Forward
submits the reviewed revision. The conversation does not keep asking for speech.
The session ends only when the existing forwarding operation succeeds; a booking
conflict still requires another available slot. Voice-only mode retains explicit
spoken summary confirmation because it has no button.

An unresolved withdrawn field cannot be skipped by saying "done". Valid pending
replacements are retained, and only missing fields are requested. The full summary
is presented after those fields are resolved. Contextual replies such as
"Actually, I am 36" update the age already being corrected; "not 35" and "maybe 35"
are not extracted as the new age. A second correction does not erase a different
pending replacement.

## Accuracy boundaries

Speech recognition uses the current conversation language for short age, phone,
first-visit and confirmation replies. A rejected attempt is retried once without
the language constraint or vocabulary prompt. Longer answers retain automatic
language detection first, with the conversation language available on retry.
Vocabulary hints match the preferred language and contain no example patient
values or sample ages. This follows the provider's distinction between STT
context hints and chat instructions:
https://console.groq.com/docs/speech-to-text

Age turns reject unrelated short words such as "Tentacle" or "Cheers" before
displaying them as patient answers. Numbers, correction requests, negation,
uncertainty and longer replies still reach the dialogue controller. This is a
plausibility check, not a claim that the transcription is correct, and does not
guess a number from a similar-sounding word. Known prompt echoes, music, and
repetitive hallucinated transcript candidates are rejected.

Short replies use the existing lower speech-start threshold and retain the audio
pre-roll. Waiting for speech is bounded; input overflows discard the incomplete
clip. Empty, non-finite and digitally silent audio is not sent to STT. Synthetic
tests cover these control paths, not real microphone quality, pronunciation, or
provider accuracy on live Urdu audio.

Structured demographics are normalized and validated. Conflicting ages, multiple
phone numbers, ambiguous yes/no answers and negated schedule choices require
clarification. Dates and times are not interpreted as option numbers.

Free-text medical answers and unfamiliar control replies can use a restricted
intent classifier through SecureLLMGateway. It receives the current turn,
dialogue state, expected field and pending field names, with known identifiers
minimized, not the complete conversation or stored patient values.
Its strict schema permits only an intent and
allowlisted field names. It cannot supply patient values, approve a summary,
choose a model, book an appointment or access records. Invalid model output
cannot change stored fields or grant permissions; deterministic validation
continues to apply. Novel phrasing and live STT errors still require evaluation
with consented synthetic spoken demonstrations.

Common bilingual confirmations and completion replies are recognized locally,
including when the provider is unavailable. A model-classified confirmation
requests explicit confirmation or the trusted button; it cannot finalize a note
or booking. Uncertain classification preserves the current question and offers
concrete response choices. These are state-aware rules and bounded prompt examples,
not a newly trained or fine-tuned model.

The confirmed source wording is stored for medical history and complaint. An
unreviewed model translation cannot overwrite these fields during forwarding.
Missing fields are never filled from a model-generated extraction.

## Save and update contracts

The desktop client creates a random intake token for each session. The server
stores only its SHA-256 digest, bound to one patient and workflow.

POST /api/receptionist/intakes requires the intake fields, intake_token,
revision and matching confirmed_revision. Replaying a creation reuses the
existing record. When that record needs updating the response directs the client
to the update operation.

PATCH /api/receptionist/intakes/{patient_id} also requires workflow_id and
expected_revision. The session capability must match both patient and workflow.
Only an unverified, not-yet-forwarded intake may be changed this way. Exact retry
payloads are idempotent; different stale payloads are rejected.

POST /api/receptionist/bookings requires the same capability and current
persisted revision. The desktop's Save & Forward control also carries the
revision of the summary actually displayed. Corrections invalidate queued clicks.

PATCH /api/patients/{patient_id}/intake requires a logged-in doctor assigned to
that patient, expected_updated_at, a changes object containing only allowed intake
fields, and confirmed=true. Once an encounter starts, amendments belong in clinical
documentation review. Phone changes are blocked once OTP verification has begun,
so an earlier challenge cannot verify a different number.

Corrections and denied access produce audit metadata without patient values.
Existing JSON development storage remains a limitation: the service lock and
SQLite revision checks cover a single application process, but JSON plus SQLite
is not one transactional production store. Do not run concurrent application
workers against these development files; use a transactional database for that
deployment model.

## Verification

Run from the repository root:

    .venv\Scripts\python.exe scripts\verify_receptionist.py
    .venv\Scripts\python.exe -m unittest discover -s tests -q
    .venv\Scripts\python.exe scripts\verify_guardrails.py

The receptionist verifier uses only synthetic records and mock model responses.
Evidence is written to artifacts/receptionist/receptionist-results.json and
artifacts/receptionist/receptionist-report.md.

The optional browser check requires Playwright and an installed browser:

    node scripts/check_receptionist_ui.cjs

Set PLAYWRIGHT_CHANNEL=msedge to use installed Edge. The browser check intercepts
every request and uses local assets and synthetic patient data. It checks the
correction form, save behavior, JavaScript errors and desktop/mobile bounds;
screenshots and browser-results.json are written under artifacts/receptionist.

Restart both the FastAPI server and receptionist after upgrading because the
intake API now requires capability and revision fields. API schema errors from
an older desktop process should not be worked around by weakening these checks.

Automated tests establish the covered behavior, not perfect language recognition,
truthfulness of a patient's statements, complete security, or clinical compliance.
