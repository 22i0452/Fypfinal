# Prescription and conversation selection

The doctor workspace now includes two compact tabbed views, beside the saved SOAP and in Finish.

## Prescription

1. Save the SOAP wording, then open **Prescription**.
2. Inspect **Prescription**, edit one row at a time in **Medicines**, and fill **Tests & follow-up**.
3. Choose Take / Continue / Stop / Avoid and confirm the intended instructions. Missing regimen fields stay blank, never guessed.
4. Save reviewed instructions. This creates a new draft version; submit and approve that current note through the existing review flow.
5. Reopen Prescription in Finish and download **Prescription PDF**. Export requires both current note approval and confirmed prescription instructions.

The worksheet uses catalogue-backed/doctor-confirmed medicine names from the saved Plan. Optional LLM extraction receives the full saved Plan and conversation; output names and copied fields must match their source quotes. Unavailable or invalid output preserves source instructions for doctor completion. Patient-reported use is not automatically converted to a doctor order. Stop/avoid instructions have a separate section and cannot silently become Take. Doctor-authored additions are saved separately from the transcript. Editing SOAP invalidates its prior prescription; old versions remain available.

## Conversation selection

Open **Documentation selection** in the saved transcript before SOAP, or **Conversation selection** beside a saved note.

- **Included**: available to SOAP generation.
- **Excluded**: unrelated social/administrative speech omitted from the next generation, with the original retained.
- **Needs review**: unclear context retained in generation until doctor review.

Each turn shows original wording, English, selection reason, decision origin, and actual saved claim links. The initial classifier receives the complete ordered conversation including roles and attendant relations. If it cannot classify, ordinary uncertain content stays under review; only exact standalone greetings are automatically omitted. Medicine turns remain included or reviewable. A doctor can change selection with a reason. Saving after SOAP creates a new unapproved draft. Approved visits are read-only in this view. A source link or Included label is not a claim of clinical correctness.

## Verification

The synthetic regression module covers full-context source selection, fallback, short answers, medicine protection, doctor overrides, source fingerprints, extraction validation, stop wording, immutable versions, approval/export authorization, stale edits and end-to-end regeneration. Browser fixtures use outputs produced by the real service fixture, with external routes blocked, and verify editing, tabbed navigation, Finish access, approval-gated PDF, dark/light themes, mobile and 160% website zoom. These checks do not measure live microphone transcription or provider accuracy.

```bash
python -m tests.run_offline_regressions tests.test_clinical_documents
python -m tests.clinical_documents_fixture
node tests/test_clinical_documents_browser.cjs
```

The fixture writes only fictional QA files under `/tmp/medflow-clinical-documents-qa`. No new API key or database migration is required. Existing provider settings and JSON/SQL note persistence are reused.
