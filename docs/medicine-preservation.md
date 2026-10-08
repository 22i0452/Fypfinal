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
not establish an unstated name or dose. Automatic LLM spelling proposals now run before translation, constrained to catalogue candidates. They never establish hearing or a prescription.

## Review workflow

1. Local exact/spelling/sound retrieval produces a bounded shortlist. The LLM checks medicine context and reranks it automatically before English translation. It may select a supplied ID or return uncertain. No user control is needed to invoke it.
2. English translations are checked for missing/introduced names, stated doses,
   dose/name associations and clause-level negation. An altered medicine translation gets one automatic repair from the protected original; the repaired name, dose and negation are checked again. A failed repair shows
   the source text with a review label instead of fluent but altered medicine text.
3. The doctor selects **Review medicine**, compares Urdu and English, corrects
   wording and confirms unfamiliar English spellings. **Use Motilium** copies a catalogue candidate into an existing literal mention and its spelling field; the checkbox remains unchecked until the doctor reviews the full turn. The original wording is never overwritten. A failed translation still needs full English correction rather than a generated prescription. An acknowledgement cannot
   remove a known brand or bypass a changed dose. Confirmation is tied to the
   exact original/English revision and actor; changed wording invalidates it.
4. Save the conversation correction. Previous transcript revisions and original
   recognized text remain available. Automatic SOAP pauses at the same review
   checkpoint when medicine checks fail; it never discards the consultation.
5. SOAP generation validates medicine identity separately from source linkage.
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


## Attached Pakistan medicine reference

`app/data/medicine_catalogue.json` is generated by
`scripts/import_medicine_dataset.py` from the attached
`MedInfoBase Pakistan Medicines.csv`. It preserves the source SHA-256, source row
numbers and MedInfoBase IDs. Of 18,952 data rows, 45 rows with corrupted/invalid
brand wording are quarantined instead of repaired by guessing. The resulting
reference has 8,527 case-insensitive brand names and 640 generic names, with
9,112 distinct names after brand/generic collisions are merged. A generic is a
separately spoken name; it never replaces a named brand. No price, ingredient,
strength, indication or manufacturer is fed into name selection or prescribing.
The import does not independently verify registration, availability or clinical
accuracy. Original attachments are not changed or required at runtime.

Motilium is absent from the supplied CSV. The curated vocabulary remains
available alongside it, including deliberate Urdu aliases. Fuzzy retrieval uses
a bounded character-bigram index, spelling similarity and a consonant key. The
relative ranking values are internal retrieval scores, not calibrated confidence.
For an unfamiliar Urdu span or unmatched Latin wording, the LLM first proposes at most two Latin search spellings automatically. These are lookup queries, not names added to the transcript. Each query must retrieve a real catalogue name; free output cannot become a medicine. The LLM then sees up to eight retrieved names per mention and chooses within that exact set. Exact known names bypass the free-text query step, so a correct Urdu Panadol cannot become a model-selected alternative.
Similarities such as `mortiiduom` and `mortiloun` can retrieve Motilium; an ordinary
sentence about a moratorium remains untouched. Exact variants such as Panadol
Extend remain distinct. Short answers can use the preceding medicine question,
with this context recomputed when conversation wording is revised.

Provider failure leaves local candidates and original wording available; it does
not authorize an uncertain medicine. Invention, a candidate from another turn,
duplicate IDs, non-boolean context flags and missing answers cannot establish a
suggestion. Suggestions are persisted with the exact original/English fingerprint
and hidden if later wording changes. Doctor attestations remain distinct from
automatic suggestions. Matching uses the existing secure LLM gateway and its
configured provider/model, including OpenRouter; no additional API key is needed.

## Attached symptom reference

`app/data/symptom_patterns.json` is generated by
`scripts/import_symptom_dataset.py` from `Symptoms Dataset(1).xlsx`. Its 4,920 rows
contain 304 distinct disease/symptom patterns, 41 condition labels and 131 raw
symptom labels. Duplicate source rows remain traceable. Fourteen labels with
ambiguous or non-symptom meanings are disabled in extraction pending terminology
review. This is an unverified source-pattern lookup, not a trained or validated
clinical diagnosis model, SHAP output or a disease probability.

The compact **Symptom reference** panel appears in transcript review and beside
SOAP. Each observation links to its actual conversation turn and literal wording.
Questions, hypothetical advice, denied/history/resolved and other-person symptoms
are separated. Unknown speaker turns do not establish a patient observation.
Mixed negation and conflicting original/English statements require review;
translation-only positive observations never create a condition label. Related
aliases count as one symptom group. At least three distinct current source groups
and a close reference overlap are needed to display an unverified pattern label.
The lookup is stored against the transcript revision, refreshes after corrections,
and stays separate from clinical SOAP sections. Local unsaved corrections hide
stale pattern results. It never chooses a medicine from symptoms.

## Automatic matching validation

`tests/test_medicine_matching.py` exercises catalogue grounding, exact variants,
short-question context, automatic call order, constrained IDs, provider outage,
translation repair, dose/negation rejection, saved doctor confirmation, source
immutability and SOAP propagation. `tests/test_symptom_patterns.py` covers source
rows, deduplication, question/history/negation exclusions, sparse overlaps,
translation conflicts and revised lookup results.

`tests/test_matching_browser.cjs` runs the actual UI and APIs with synthetic
providers: automatic suggestion, candidate action, explicit confirmation, dirty
state, save/reload, automatic Panadol repair, SOAP name/dose preservation and
symptom source navigation. Existing medicine approval and guided/automatic flows
are also tested at 1440, 1280 and 390 pixels. These establish software behavior,
not live microphone accuracy or treatment correctness. The broader suite has
existing environment limits: four legacy audio modules require unavailable
`sounddevice`/`pygame`, and the receptionist assigned-doctor recovery test also
fails on the unchanged prior commit. See the update test report for exact scope.
