# SOAP content and saved-draft recovery

The reported screen contains the transcript fallback prefixes. This mode is used when the provider fails or the model draft cannot pass validation after a repair attempt. The screenshots alone do not identify the exact provider/validation failure.

The old fallback copied conversational patient statements into Subjective and classified a history question containing “start” as a treatment plan. Generation now explicitly requests a clinical summary with the original source wording alongside the reviewed English and source medicine manifest. A conversational-text check rejects greetings and history questions, including in otherwise salvageable model sections. It allows one repair using the same complete source context.

Fallback extraction omits standalone greetings/courtesies and prevents clinician questions from becoming treatment instructions. Medicine questions remain source statements, not prescriptions. Exact medication names, quantities and stop/avoid wording are retained; missing findings and diagnosis remain missing. An unspecified pill must be documented as needing clarification, never assigned an inferred name. Source extracts are still source extracts, not guaranteed clinical summaries.

Existing unapproved fallback notes show **Rebuild SOAP**. The endpoint uses the saved, reviewed transcript without repeating speech recognition, diarization or translation. Existing medicine confirmations and documentation selections stay source-bound. Success creates another unapproved note version and clears stale prescription output. Failure preserves the current draft. Unsaved UI changes, approved/closed visits, stale versions, unauthorized access and inactive AI permissions block rebuilding; version and permission checks run again before saving.

After updating Replit from main and restarting the app, open the saved note, save any outstanding wording edits, then choose **Rebuild SOAP**. Review the resulting draft before approval. Provider connectivity and model responses require a live smoke test; the automated tests use synthetic offline responses and do not establish clinical accuracy.

Regression coverage: the reported conversational structure, full original context on repair, household quantities, medication questions, stop instructions, salvage rejection, unchanged medicine reviews, version preservation, provider failure, concurrent edits, access/permission gates, and actual desktop/mobile browser controls. Existing medicine, SOAP, role and note lifecycle tests are also run.
