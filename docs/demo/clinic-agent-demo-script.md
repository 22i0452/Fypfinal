# Clinic-Agent Demo Script

Use only the synthetic demo records. Start the canonical app:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

1. Sign in with a synthetic doctor account and open a synthetic patient.
2. Start the patient workflow and request the development phone OTP. Show the development code only when the three development flags are enabled.
3. Verify the patient and complete the existing Urdu intake.
4. Select department, doctor, visit type, and a server-calculated appointment slot. Confirm that the persisted appointment advances the workflow.
5. Check in to create the encounter.
6. Open the single consent dialog. Leave all controls initially unchecked; grant recording, transcription, and documentation. Leave retention off to demonstrate default cleanup.
7. Generate the stored pre-visit brief. Point out that it contains intake plus previous approved records, never drafts.
8. Select a clinical note template before recording.
9. Record a short synthetic Urdu/mixed-language consultation and stop. Show stable utterance IDs and Doctor/Patient/Unknown labels in the transcript.
10. Review the SOAP AI draft. Use **View source** to highlight supporting utterances and show any unsupported-content warning.
11. Edit, save, submit for review, and approve as the authenticated doctor. Show immutable versions and the approved status.
12. Generate an English, Urdu, or bilingual after-visit summary from the approved note and use its print view.
13. Show the ICD-10 panel disabled because no clinic-approved coding provider is configured. Then run FLOW-20/21 to demonstrate, with a synthetic injected provider, that unapproved notes are blocked and suggestions remain evidence-linked `SUGGESTED` records.
14. For the local mapping demo only, restart with `FHIR_ENABLED=true`. Export the approved synthetic patient/appointment/encounter/note mappings; the adapter also has explicit typed Observation, Condition, AllergyIntolerance, and MedicationRequest mappings. State clearly that this is not a live EHR integration.
15. Inspect privacy-safe audit events: verification, booking, consent, consultation, note approval, and summaries appear without names, transcript text, SOAP content, audio, prompts, or secrets.
16. Confirm the audio result is `AUDIO_DELETED`. Repeat only if needed with explicit retention consent plus the server retention flag to demonstrate authorized playback.

Verification commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\verify_guardrails.py
.\.venv\Scripts\python.exe scripts\verify_clinic_agent.py
node --check "scribe\assets\ui.js"
```
