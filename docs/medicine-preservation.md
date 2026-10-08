# Medicine wording and source preservation

Medicine names are protected before consultation cleanup, role assignment and
English translation. Recognized Urdu aliases restore to a catalogue's English
name, never to its ingredient, medicine class or another brand. Each turn keeps
its original wording and ID. The transcript also retains the original recognized
text before cleanup; this is not verified audio. Existing audio consent and
retention rules are unchanged.

`app/data/medicine_vocabulary.json` is a versioned **spelling vocabulary**, not a
prescribing database. It includes Panadol, Motilium and common names from
Haleon Pakistan, GSK Pakistan and NHS product/medicine pages. Official source
URLs are stored per entry. Urdu transliterations are curated application aliases,
not an officially validated acoustic dictionary. No ingredients, doses,
indications, substitutions or interaction guidance are supplied by the catalogue.
Extend the file with verified names and deliberate aliases, then add regression
cases. Do not add arbitrary fuzzy matches as automatic aliases.

The user-reported name **Fixage** is explicitly unconfirmed. It must not become
the ordinary word “fixed”. Unfamiliar words beside medicine/tablet/دوا cues are
preserved as candidates. “میں آپ کو دوا دے رہا ہوں” supplies context but does
not establish an unstated name or dose. There is no automatic medicine guessing.

## Review workflow

1. English translations are checked for missing/introduced names, stated doses,
   dose/name associations and clause-level negation. A failed translation shows
   the source text with a review label instead of fluent but altered medicine text.
2. The doctor selects **Review medicine**, compares Urdu and English, corrects
   wording and confirms unfamiliar English spellings. An acknowledgement cannot
   remove a known brand or bypass a changed dose. Confirmation is tied to the
   exact original/English revision and actor; changed wording invalidates it.
3. Save the conversation correction. Previous transcript revisions and original
   recognized text remain available. Automatic SOAP pauses at the same review
   checkpoint when medicine checks fail; it never discards the consultation.
4. SOAP generation validates medicine identity separately from source linkage.
   Invalid model output gets the existing repair attempt, then a source-quoted
   fallback. Missing names, new catalogue names, dose changes and clause-level
   stopping/negation differences are visible on SOAP and block approval until
   the saved note is corrected. This does not prove clinical correctness.

No new API key is needed. Existing STT/LLM provider configuration is reused.
Update from GitHub and restart the Replit application to load the backend and
vocabulary; refresh the browser to load the new review controls. Existing JSON
transcript records load with defaults for the new fields, without a SQL migration.

## Validation and limits

`tests/test_medicine_preservation.py` covers correct Urdu aliases, short names,
Panadol-to-painkiller/ingredient substitution, Fixage-to-fixed substitution,
wrong turn IDs, destructive cleanup/role assignment, unknown-name confirmation,
stale revisions, dose swaps, negation, automatic-mode pauses, SOAP repair/fallback
and approval after edits. Existing guided, SOAP, note lifecycle and WebSocket
regressions also run.

`tests/test_medicine_browser.cjs` uses a temporary database and synthetic providers
to exercise the actual UI, WebSocket, correction API, reload, SOAP edit and approval
at desktop and mobile widths. These tests do **not** measure live ASR accuracy,
drug identification, translation quality across Urdu dialects or treatment safety.
An exact dictionary match is not a confidence probability. Dose association uses
nearby names and negation uses clauses: ambiguous multi-medicine sentences can
require manual review. Test the actual microphone with consented synthetic
utterances before the demo, including short Panadol/Motilium answers and a
medicine absent from the vocabulary. Confirm medicines against the audio and
the clinician's intended wording; do not rely on spelling matches alone.
