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
