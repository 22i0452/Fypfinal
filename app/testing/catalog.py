PACK_VERSION = 'medflow-workflow-v2'

# Expectations are authored before execution. The runner cannot accept arbitrary
# user code, transcripts, patient IDs, paths, or provider URLs.
SCENARIOS = [
    ('short-confirmation', 'Short Urdu confirmation', 'Reception', 'جی', 'Confirm the held age and advance to phone.', 'Local parser; no speech recognition.'),
    ('short-age', 'One-word age', 'Reception', '۲۳', 'Hold age 23 for confirmation.', 'Local parser.'),
    ('short-phone', 'Phone digits', 'Reception', '۰۳۰۰۰۰۰۰۰۰۱', 'Preserve all digits and request confirmation.', 'Local parser.'),
    ('department-repeat', 'Repeated department', 'Reception', 'جنرل میڈیسن جنرل میڈیسن', 'Accept one department and advance to doctor selection.', 'Local parser; doctor catalog checked separately.'),
    ('age-correction', 'Age correction', 'Reception', '22 → نہیں، 23 → جی', 'Replace 22 with confirmed 23; retain correction evidence.', 'Scripted extraction; tests state handling, not model accuracy.'),
    ('unclear-answer', 'Uncertain answer', 'Reception', 'An extraction marked needs_review', 'Preserve accepted fields and hold the question for review.', 'Injected provider response.'),
    ('doctor-selection', 'Numbered doctor choice', 'Reception', '1', 'Select the exact practitioner ID from the displayed catalog.', 'Local catalog selection.'),
    ('intake-repeat', 'Repeated intake save', 'Appointments', 'Same fictional intake token submitted twice', 'One patient and one workflow; identical saved IDs.', 'Real intake persistence in a temporary clinic.'),
    ('slot-conflict', 'Unavailable slot', 'Appointments', 'Two fictional patients request the same opening', 'Retain second intake, create no duplicate appointment and return alternatives.', 'Real scheduling and conflict handling.'),
    ('doctor-handoff', 'Reception to doctor', 'Appointments', 'Fictional manual intake and appointment request', 'Assigned doctor sees the same patient, appointment and workflow.', 'Real scheduling, assignment and context API.'),
    ('consent-gate', 'Consent before capture', 'Consultation', 'Start recording without AI/recording consent', 'Reject capture before processing or note creation.', 'Synthetic PCM envelope; no physical microphone.'),
    ('transcript-checkpoint', 'Transcript before SOAP', 'Consultation', 'Synthetic PCM with controlled transcript', 'Save transcript and visit linkage; make zero SOAP calls until requested.', 'Synthetic STT/role/translation outputs.'),
    ('soap-retry', 'SOAP failure and retry', 'SOAP', 'One injected draft failure, followed by retry', 'Preserve transcript; retry on the same encounter.', 'Injected provider failure; actual recovery logic.'),
    ('transcript-correction', 'Saved conversation correction', 'SOAP', 'Correct a saved turn before generation', 'New transcript revision; original retained; stale generation rejected.', 'Real revision and API checks.'),
    ('coding-after-edit', 'SOAP edit and stale codes', 'Coding', 'Generate codes, edit SOAP, attempt old approval', 'Old code evidence remains readable; old approval blocked; new version can generate.', 'Synthetic code candidate; catalog correctness unassessed.'),
    ('patient-access', 'Patient access boundary', 'Access', 'Another signed-in doctor opens this fictional visit', 'Deny conversation and code-source access.', 'Actual patient authorization checks.'),
    ('medicine-dose-stop', 'Medicine dose and stop instruction', 'Medicines', 'Take Panadol 500 mg. Do not take Motilium 10 mg.', 'Preserve both names, doses and stop wording; flag dropped or changed wording.', 'Written synthetic transcript; deterministic preservation checks, not live ASR.'),
    ('medicine-context', 'Full consultation medicine context', 'Medicines', 'Urdu test order alongside Panadol in another turn', 'Send every source turn in one request; test is not a medicine; Panadol remains.', 'Controlled LLM entity response; actual translation checks, not model accuracy.'),
    ('three-speaker-sources', 'Doctor, child and mother', 'Consultation', 'Patient reports cough; mother reports fever; doctor orders blood test.', 'Keep collateral mother history source-linked and ordered test outside findings.', 'Explicit supplied roles; does not measure acoustic speaker identification.'),
    ('soap-medicine-edit', 'SOAP medicine removal', 'SOAP', 'Reviewed medicine in transcript; edit SOAP to omit its name', 'Missing source medicine is flagged before approval.', 'Actual medicine-to-SOAP checks on synthetic text.'),
]
LIVE_SCENARIOS = [
    ('live-correction', 'Live text: corrected age', 'Live text', 'نہیں، میری عمر 23 سال ہے', 'Extract age 23 from a correction to a held age of 22.', 'Real OpenRouter extraction; no audio.'),
    ('live-uncertainty', 'Live text: missing details', 'Live text', 'مجھے اپنا نمبر یاد نہیں', 'Do not invent a phone number.', 'Real OpenRouter extraction; no audio.'),
    ('live-soap', 'Live text: SOAP facts', 'Live text', 'Fictional patient reports cough for two days; no examination provided.', 'Retain stated symptom; leave objective findings undocumented; keep source IDs valid.', 'Real SOAP provider; checklist, not clinical correctness.'),
]


def catalog(mode='synthetic'):
    rows = LIVE_SCENARIOS if mode == 'live_text' else SCENARIOS
    return [dict(zip(('id', 'title', 'category', 'input', 'expected', 'scope'), row)) for row in rows]
