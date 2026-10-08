# Evaluation Studio

Open `/testing` from the existing signed-in doctor workspace. It replaces the long testing page. No extra service, frontend build or dataset is required. The existing deployment dependencies already cover its Python features.

## Five views

| Tab | Compact sections |
| --- | --- |
| Overview | Results, Compare, Coverage |
| Cases | Filtered list; one case with Checks, Evidence, Run |
| Replay | Saved actions and artifacts, selectable step, play/pause/reset and pace |
| Audio | Library, Add recording, Scripts |
| Method | Scoring, Guardrails, Limits |

Only the selected view is displayed. Desktop panels scroll internally; mobile case inspection replaces the list and has a Back button. Existing site-wide display settings support light/dark, zoom and fullscreen. Keyboard arrows, Home and End switch tabs. Motion respects reduced-motion preferences.

## Run workflow

1. Choose **Workflow checks**, then Run checks: 52 fixed scenarios against an isolated clinic. Synthetic providers are controlled and outbound network is blocked. Saved patients/notes in the working clinic are untouched.
2. Optionally enable the existing `DEMO_LIVE_TEXT_ENABLED=true` with the existing `OPENROUTER_API_KEY`. Live text runs 10 authored scenarios through real receptionist, medicine/translation, contextual-role and SOAP paths. Open Run settings and acknowledge provider requests. No new API key is needed.
3. Optional recorded audio: open Scripts, record the fictional words exactly, and upload the WAV under Add recording. Listen and attest that it matches. Use different people for different roles. Select up to six recordings from a single development or held-out split; choose Recorded audio, acknowledge requests, then run.
4. Run settings can repeat a pack 1–3 times. IDs and outcomes remain separate for each repetition. Paid runs have a hard maximum of **80 actual HTTP requests total**, **20 per case**, a 20-second timeout per HTTP attempt and a six-minute worker deadline. Retries count. The request cap bounds attempts, not a dollar price. Remaining cases after a run cap are unassessed.
5. Inspect failures as well as passes, export the panel PDF or full JSON, and replay saved receipts without model calls.

The parent retains only allowlisted import paths, configured public model settings and the OpenRouter key when launching paid workers. Production clinic database paths, identity secrets and service tokens are not inherited. Clinical source text remains intact in the isolated pipeline; gold reference scripts are used only after processing for scoring, never as ASR/translation hints.

## References and storage

`app/testing/catalog.py` is the versioned workflow/live-text pack. `app/testing/references.py` contains 10 development and 2 held-out recording scripts, authored role labels and independent expected medicine names. There are **no supplied recordings** and no invented audio scores. Uploader attestation is not independent annotation. If a held-out clip is used for tuning it must no longer be described as untouched.

Reports and WAV bytes/reference metadata use owned SQL tables on the existing database. On the published PostgreSQL configuration they survive application restarts. PCM WAV limits: mono, 16 bit, one of 16/22.05/24/44.1/48 kHz, 1–90 seconds, under 3 MB. Maximum 20 clips/account and 50 reports/account. Delete clips in the Library tab. Recordings are sent to OpenRouter only in an acknowledged paid run. Use fictional data.

Older saved reports remain inspectable. Reports lacking the new reference hash/protocol cannot produce an improvement percentage. Audio selection stores reference and audio fingerprints, not the audio bytes inside each report export.

## Meaning of the numbers

- Scenario success: passed / (passed + failed + error); skipped/pending are separately shown. Zero denominator means Not tested.
- Assertions: passing / completed checks. A case that errors after some checks never becomes a scenario pass.
- Guardrail percentages are purpose-tagged sample assertions, with unsafe detection and valid-action acceptance separate. They are not a security certification or probability of safety.
- Median/p95: completed case wall times including setup and checks; p95 is nearest rank. Synthetic timings do not measure provider speed. HTTP-attempt receipt times end at response headers; body read is excluded and labelled.
- Raw ASR WER/CER: Levenshtein edit errors / reference words/characters; NFKC, casefold, punctuation/diacritics/format removal. No spelling correction; WER can exceed 100%.
- Audio medicine precision/recall: distinct canonical names detected in raw ASR compared with independently authored names. Translation instruction checks compare both heard source and gold source with final English. These are wording checks, not clinical appropriateness.
- Contextual role agreement: distinct greedy text alignment with a 0.35 minimum similarity, against authored turn roles. Unmatched turns fail. No acoustic clustering, overlap scoring, timed DER or speaker-identity claim.
- Comparisons: two complete executions with matching mode, ordered cases/repetitions, pack version, reference hash, protocol, configured provider settings and observed provider task/model sets. Show percentage-point changes only when compatible. This is an observed sample difference, not statistical significance or causality. Bump the pack/protocol when reference/scoring definitions change.

No UI animation represents hidden model reasoning. Replay shows actual saved actions, outputs and measurements, with disclosed visual pacing. It makes no API/model requests. Word confidence, clinical accuracy and acoustic DER remain unassessed.

## Guardrail regression coverage

The fixed pack checks task-role permission, model allowlists, malformed JSON, forged doctor approval, unknown source IDs, direct-identifier minimization with retained clinical wording, unresolved medicine review, stale review fingerprints, dose/negation changes, draft finalization, unassigned/signed-out access, consent, stale appointment choices, repeated handoff, attendance responses, SQL restart/rollback, immutable note versions, and safe fallback/checkpoint recovery. Valid tasks/access/reviews are exercised separately to detect overly strict rejection.

Unknown SOAP evidence IDs now fail schema validation. Source membership alone does not establish that a clinical statement is correct. Attendance confirmation records the patient's intent; doctor booking approval remains a separate action. Neither a staff-recorded response nor an evaluation receipt claims a delivered notification.

## Repeatable verification

```bash
python -m tests.run_offline_regressions tests.test_evaluation_studio tests.test_demo_reports tests.test_soap_quality
python -m tests.evaluation_fixture
node tests/test_evaluation_browser.cjs
```

The browser suite needs the existing Playwright development dependency and a Chromium installation (`QA_CHROMIUM_PATH` may point to one). Fixture preparation performs a fresh actual isolated synthetic run and writes JSON/PDF under `/tmp/medflow-evaluation-qa`. Browser requests are offline transport fixtures: they test UI behavior, not deployed networking. `QA_REPORT_JSON` and `QA_CONFIG_JSON` together can supply an existing run instead. The legacy demo-report browser entry point now invokes the maintained suite.

Optional PostgreSQL contracts use `PGLITE_MODULE_PATH`; they verify PostgreSQL SQL over stdio, not production psycopg connectivity. Browser microphone capture, real live models, telephone/WebSocket transport on Replit and final published persistence still need deployment smoke tests. No result from those paths should be claimed until it executes.
