# Automatic medicine matching update: validation

Date: 8 October 2026. Synthetic fixtures and mock providers; no live ASR or clinical accuracy claim.

## Implemented behavior

- Automatic LLM medicine checking before translation, with no manual invocation control.
- Attached Pakistan brand/generic name reference plus curated Urdu/Latin aliases.
- Automatic transliteration lookup for unfamiliar Urdu medicine spans, followed by catalogue-only candidate selection.
- One automatic retry for medicine translations that drop a source name or alter dose/negation.
- Original recognized text and prior transcript revisions retained. Doctor confirmation remains necessary for uncertain names.
- Compact source-linked symptom lookup, outside SOAP clinical sections; no inferred prescription or diagnosis.

## Executed checks

94 Python tests passed in 7.235 seconds with the following command:

```sh
python -m unittest tests.test_medicine_matching tests.test_symptom_patterns tests.test_medicine_preservation tests.test_guided_consultation tests.test_soap_quality tests.test_note_lifecycle tests.test_consultation_websocket tests.test_preconsolidation_regression tests.test_transcript_identity tests.test_domain_repositories tests.test_evidence_checks tests.test_process_observability
```

The runtime used an existing local dependency directory through PYTHONPATH. Tests exercise actual persistence, revision APIs, WebSocket workflows, secure mock gateway calls, name/dose/negation guards, SOAP retries/fallback and approval rules. Inputs are synthetic written transcript cases, not an acoustic evaluation dataset.

| Browser suite | Measured outcome |
| --- | --- |
| test_matching_browser.cjs | Passed automatic Motilium proposal, automatic Urdu/Panadol repair, candidate action, explicit confirmation, save/reload, unchanged source, SOAP names/doses, separate symptom lookup and source navigation. No page errors. |
| test_medicine_browser.cjs | Passed automatic SOAP pause, unfamiliar spelling confirmation, reload, original ASR display, SOAP name-removal rejection, corrected approval. No page errors. |
| test_guided_browser.cjs | Passed guided capture/review/correction, SOAP failure/retry, reload, sources, approval, completion and the existing automatic microphone handler. No page errors. |

Browser checks cover widths 1440, 1280 and 390 px without horizontal overflow. The matching suite also verifies light mode at all three widths. Screenshots were visually inspected in dark desktop and light mobile views. Browser audio is generated with a synthetic oscillator and transcription is mocked; this checks the microphone workflow, not its recognition accuracy.

Medicine and symptom imports were checked against the attached files and reproduced deterministically. The source workbooks/CSV were not changed. JavaScript syntax, Python compilation and git whitespace checks passed.

## Broader suite limits

An initial discovery run executed 241 tests, including failed module imports. It exposed one new legacy missing-turn-ID regression, which was fixed and is covered by the final passing targeted run. Four legacy audio modules cannot import here because sounddevice or pygame are unavailable. The saved-request assigned-doctor recovery assertion also fails on the unchanged previous commit 0f4e98c, verified in an isolated baseline worktree. That failure belongs to existing receptionist appointment assignment and is outside this medicine update. Full-suite green status is not claimed.

## Live evaluation still required

Use consented synthetic microphone scripts with exact intended medicine names, including Panadol, Motilium, unfamiliar Urdu names, brand variants, doses, stop/avoid wording and patient-reported use. Record the raw recognized transcript, automatic candidate, doctor correction, final English and SOAP. Measure name accuracy, false correction rate, unresolved-name rate and latency against the intended/audio-grounded reference. This update supplies guarded behavior and repeatable software checks; it does not establish zero recognition errors or validated clinical correctness.

## Follow-up: approved medicines in SOAP

- Distinguish the ordinary verb in "to prevent fever/vomiting" from the catalogue brand PREVENT. Explicit brand/form/dose references remain detectable.
- Retain approved spelling metadata and short-turn medicine context when normalizing the transcript for fallback generation. Compare introduced names without case sensitivity.
- Preserve "I'm giving you" and prescribing statements in the fallback plan, including stated doses and stop instructions. Bare names and other speakers' medication statements remain reported history rather than inferred prescriptions.
- Recheck the fallback itself. Historical model validation errors are marked as errors of the rejected model draft, separately from current medicine checks. Provider-request failure has a separate explanation.

66 targeted tests passed in 11.530 seconds:

```sh
python -m unittest tests.test_medicine_preservation tests.test_medicine_matching tests.test_soap_quality tests.test_note_lifecycle tests.test_guided_consultation
```

New regression cases include PREVENT verb/brand separation, lowercase approved spellings, short multi-party name turns, prescriptions/doses/negation in fallback, and API workflows after approval for both provider failure and validation rejection. This follow-up did not rerun the browser suites above and does not measure live model or audio accuracy. After pulling and restarting Replit, test a fresh SOAP draft; already saved notes are not rewritten.

## Follow-up: complete consultation medicine context

The medicine pipeline now sends the complete chronological source consultation,
speaker roles, relationships, addressees and relevant intake context to the LLM
before translation. Entity identification uses one request, without turn chunks,
neighbour windows or source-text truncation. Optional transliteration retrieval
and catalogue candidate selection also receive the complete consultation in one
request per stage. Local candidates are hints, not evidence that a word is a drug.

Decisions must refer to exact original source spans. Explicit non-medicine
decisions remove false catalogue flags consistently from translation, transcript
review and SOAP checks. Known curated brand names and doctor-confirmed wording
cannot be erased by an automatic negative decision. Missing or invalid model
responses keep original wording reviewable and show the contextual check as
unavailable; they never silently fall back to a partial-context LLM request.

Catalogue-validated spelling proposals populate the English translation and
medicine editor automatically while preserving original Urdu. A single explicit
doctor confirmation records that spelling. SOAP receives the source medicine
manifest, complete translated consultation and, on retry, the rejected draft plus
the specific failed checks. Invalid model JSON gets a retry. Fallback drafts
preserve exact medicines and source IDs, separate test orders from observed
findings, and remain subject to clinician review.

96 synthetic Python tests passed in 14.734 seconds:

```sh
python -m tests.run_offline_regressions tests.test_medicine_context tests.test_medicine_preservation tests.test_medicine_matching tests.test_soap_quality tests.test_note_lifecycle tests.test_guided_consultation tests.test_transcript_identity tests.test_evidence_checks tests.test_process_observability tests.test_consultation_websocket
node tests/test_medicine_editor.cjs
```

The runner blocks all outbound IPv4/IPv6 socket connections, including optional
TTS startup warmup. LLM and transcription responses are synthetic mocks; API
tests use in-process clients. The Node check executes the real medicine editor
markup and verifies automatic spelling, unchecked confirmation, doctor override
and empty state. Browser suites from earlier updates were not rerun for this
follow-up because a browser executable is unavailable in this environment.

New cases cover the screenshot's Urdu test wording, long consultations with all
25 turns retained, LLM-discovered names missed by lexical rules, Panadol spelling
proposals, invalid/stale/contradictory decisions, clinician override, saved and
reloaded contextual decisions, fallback source links and SOAP repair payloads.
Python compilation, JavaScript syntax and git whitespace checks also passed.

This adds an automatic context request and increases input size for later name
checks; latency and token usage may increase. The configured LLM/provider is
unchanged. Provider context limits are surfaced as unavailable checks, not
hidden truncation. These software tests do not establish clinical accuracy or
zero medicine recognition errors. Saved notes are not rewritten: test a fresh
transcript and SOAP draft after pulling this branch and restarting Replit.
