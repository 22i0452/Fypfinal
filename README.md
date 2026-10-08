# MedFlowAI — Clinic Agent Platform

**Demo testing report (Batch 5):** open **Demo testing** in the doctor workspace or the home footer, then run 16 repeatable fictional scenarios. No supplied dataset or provider credits are needed in synthetic mode. Results include actual assertions/timings, history, cancellation and JSON export. Optional live text checks use the existing OpenRouter key and require explicit opt-in. See [PROCESS_STUDIO.md](PROCESS_STUDIO.md) for setup and limits.

**Connected product (Batches 2–4):** the public home at `/` opens AI Receptionist and Doctor Workspace. Saved SOAP has a visible **ICD-10 / CPT** action; code suggestions link to their exact SOAP version and original conversation. Patient Portal is marked **Coming soon**. See [PROCESS_STUDIO.md](PROCESS_STUDIO.md) and [VALIDATION.md](VALIDATION.md) for setup and measured checks.

**Process and voice refinement:** see [PROCESS_STUDIO.md](PROCESS_STUDIO.md) for separate agent workspaces, actual stage events, source inspection, role correction, voice recovery and Replit update instructions.

**Refined web workspace:** see [REFINEMENT.md](REFINEMENT.md) for the new clinical studio, guided encounter flow, recovery changes, and validation.


**MedFlowAI** is a Final Year Project (FYP) that builds an AI-assisted clinic workflow for Urdu-speaking patients and doctors. The system covers the full path from front-desk intake to consultation documentation:

1. **Module 1 — AI Receptionist** (`receptionist/`) collects patient intake and books an appointment in Urdu (voice + GUI).
2. **Module 2 — AI Scribe Agent** (`scribe/`) records the consultation, diarizes speakers, translates clinical content, and drafts an evidence-linked SOAP note for doctor review.

Both modules share one canonical FastAPI backend (`app.main:app`) with signed doctor sessions, consent controls, workflow orchestration, and secure LLM/STT guardrails.

> This repository is a development / academic prototype. It does **not** claim HIPAA certification, clinical approval, or production readiness.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Repository Structure](#repository-structure)
- [Module 1 — AI Receptionist](#module-1--ai-receptionist)
- [Module 2 — AI Scribe Agent](#module-2--ai-scribe-agent)
- [End-to-End Clinic Flow](#end-to-end-clinic-flow)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [How to Run](#how-to-run)
- [Environment Variables](#environment-variables)
- [Testing](#testing)
- [Security Notes](#security-notes)

---

## Project Overview

| Layer | Folder | Responsibility |
| --- | --- | --- |
| Desktop receptionist client | `receptionist/` | Voice STT → LLM dialogue → TTS; posts validated intake + booking to the API |
| AI scribe components | `scribe/` | Diarization, translation, SOAP draft generation, patient assistant, doctor workspace UI |
| FastAPI clinic platform | `app/` | Auth, patients, appointments, consents, consultation WebSocket, notes, summaries |
| Domain & intake logic | `medflow/` | Typed entities, workflow orchestration, intake validation |
| Security | `security_guardrails/` | Provider allowlists, PHI minimization, authorization, audit sanitization |

**Demo clinic seed:** MedFlowAI Demo Clinic (Islamabad) with General Medicine, Cardiology, and Pediatrics departments.

---

## Repository Structure

```text
FYP_Repo/
├── main.py                      # Thin root entry → Module 1 receptionist
├── web_server.py                # Compatibility launcher → app.main:app
├── config.py                    # Shared runtime config (.env)
├── requirements.txt
├── .env.example
│
├── receptionist/                # Module 1 — AI Receptionist
│   ├── main.py                  # GUI / CLI entry
│   ├── agent.py                 # STT → LLM → TTS orchestration
│   ├── ui.py                    # CustomTkinter desktop UI
│   ├── audio_recorder.py
│   ├── stt_module.py
│   ├── tts_module.py
│   ├── llm_module.py
│   ├── receptionist_client.py   # Authenticated API client
│   ├── urdu_stt_utils.py
│   └── booking_scheduler.py
│
├── scribe/                      # Module 2 — AI Scribe Agent
│   ├── llm_diarizer.py          # Doctor / Patient / Nurse / Attendant speaker labeling
│   ├── translator.py            # Clinical English translation
│   ├── soap_generator.py        # Evidence-linked SOAP drafts
│   ├── patient_assistant.py     # Approved-note Q&A
│   ├── index.html               # Doctor workspace page
│   ├── assets/                  # Workspace JS / CSS
│   ├── soap_server.py           # Compatibility FastAPI launcher
│   ├── generated_notes/         # Development note artifacts
│   └── tools/                   # Local probe / validation helpers
│
├── app/                         # Canonical FastAPI clinic platform
│   ├── main.py
│   ├── routers/
│   ├── services/
│   ├── repositories/
│   ├── fhir/
│   └── data/clinic_seed.json
│
├── medflow/                     # Domain models, intake, workflows
├── security_guardrails/         # Secure LLM/STT gateway
├── consultation/                # Legacy login HTML + assets
├── assets/branding/             # Logos / icons
├── data/samples/                # SOAP sample datasets
├── patient_records/             # Development patient JSON store
├── scripts/                     # Verification runners + tools
├── tests/
├── docs/
├── artifacts/                   # Test / guardrail reports
└── static/
```

---

## Module 1 — AI Receptionist

An Urdu-speaking medical receptionist agent named **ثمرہ (Samra)** that talks to patients over the microphone, collects intake fields, and hands a booking request to the assigned doctor's dashboard.

### What it does

- Records patient speech with energy-based voice activity detection (VAD)
- Transcribes Urdu audio (Groq Whisper `whisper-large-v3`)
- Runs a step-by-step intake dialogue (Groq LLaMA 3.3-70B)
- Speaks replies in Pakistani Urdu (Edge TTS `ur-PK-UzmaNeural`, with optional cloud TTS)
- Validates name, age, phone, visit history, complaint, department, doctor preference, visit type, and appointment slot
- Creates a **REQUESTED** appointment on the doctor's dashboard via authenticated receptionist API routes
- Provides a CustomTkinter GUI (chat + patient field progress) or a terminal-only mode

### Pipeline

```text
Microphone
  → AudioRecorder (energy VAD)
  → STTEngine (Groq Whisper)
  → LLMBrain (Urdu intake dialogue)
  → TTSEngine (Edge TTS)
  → Speaker
       ↓
ReceptionistAPIClient → FastAPI /api/receptionist/*
```

### Key files

| File | Role |
| --- | --- |
| `receptionist/main.py` | Entry point (GUI / terminal) |
| `receptionist/agent.py` | End-to-end receptionist orchestration |
| `receptionist/ui.py` | CustomTkinter desktop UI |
| `receptionist/audio_recorder.py` | Microphone capture + VAD |
| `receptionist/stt_module.py` | Speech-to-text |
| `receptionist/llm_module.py` | Intake conversation brain |
| `receptionist/tts_module.py` | Text-to-speech |
| `receptionist/receptionist_client.py` | Authenticated client to the clinic API |

### Intake fields collected

1. Full name  
2. Age (numeric)  
3. Contact phone  
4. First visit / returning patient  
5. Past medical history  
6. Today's complaint  
7. Department  
8. Preferred available doctor (or auto-assign)  
9. Visit type  
10. Appointment slot from server-listed availability  

---

## Module 2 — AI Scribe Agent

The doctor-facing clinical documentation module. After check-in and consent, it captures the consultation, labels speakers and translates while preserving clinical identity. The guided default saves a transcript-review checkpoint before generating a **draft-only** SOAP note. The authenticated doctor reviews the conversation, saves corrections, explicitly generates SOAP, then reviews and approves the draft. An optional Automatic SOAP switch retains the faster path.

### What it does

- Authenticated consultation audio over WebSocket
- Speech-to-text for the encounter
- LLM-assisted **Doctor / Patient / Unknown** diarization with stable utterance IDs
- Identity-preserving clinical English translation
- Saved conversation review, versioned wording/role corrections and explicit SOAP generation
- Optional Automatic SOAP mode; refresh/retry recovery on the same encounter
- Template-aware, evidence-grounded **SOAP AI draft** (Subjective, Objective, Assessment, Plan)
- Doctor edit → submit → approve / reject with immutable note versions
- Pre-visit brief and after-visit summary (English / Urdu / bilingual)
- Read-only **Patient Assistant** Q&A from authorized intake + latest **approved** note
- Optional FHIR R4 export and ICD coding boundaries (feature-flagged / disabled by default)

### Pipeline

```text
Doctor workspace (browser)
  → Consent + check-in
  → Authenticated WS /ws (audio)
  → STT
  → llm_diarizer (speaker labels)
  → translator (clinical English)
  → Saved conversation review + corrections (default; optional automatic bypass)
  → Explicit Generate SOAP
  → soap_generator (SOAP AI_DRAFT)
  → Doctor review / approval
  → After-visit summary / Patient Assistant / FHIR (approved-only)
```

### Key files

| File / folder | Role |
| --- | --- |
| `scribe/llm_diarizer.py` | Transcript-only speaker labeling |
| `scribe/translator.py` | Clinical translation (no tools/repos) |
| `scribe/soap_generator.py` | Evidence-linked SOAP draft generation |
| `scribe/patient_assistant.py` | Approved-note Q&A helper |
| `scribe/assets/` | Doctor workspace UI (JS/CSS) |
| `scribe/soap_server.py` | Compatibility launcher for the same FastAPI app |
| `app/services/documentation_service.py` | Documentation orchestration |
| `app/services/note_lifecycle_service.py` | Draft / review / approval lifecycle |
| `security_guardrails/` | Secure LLM gateway and validations |

### Isolation boundaries

- Diarizer receives transcript text only (no SOAP notes, appointments, or repositories)
- Translator receives structured utterances only
- SOAP generator returns a **draft**; it cannot approve, prescribe, or export
- Patient Assistant answers only from the current authorized patient + latest approved note
- Deterministic services alone change appointments, workflow state, consent, and persistence

---

## End-to-End Clinic Flow

```text
Urdu intake (Module 1 / receptionist/)
  → Validated patient fields + server slot
  → REQUESTED appointment on doctor's dashboard
  → Doctor verification (OTP in development)
  → CONFIRMED appointment
  → Check-in encounter
  → Four independent consent decisions
  → Consultation recording (Module 2 / scribe/)
  → Diarization + translation
  → Saved transcript review + corrections
  → Explicit Generate SOAP (or optional automatic mode)
  → SOAP AI_DRAFT
  → Doctor edit / approve
  → After-visit summary / assistant / optional FHIR
```

---

## Tech Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.11+ (3.14 supported via `pygame-ce`) |
| Backend | FastAPI, Uvicorn, Starlette sessions |
| Storage | SQLite (accounts, clinic ops, audit) + JSON adapters (clinical docs in development) |
| Module 1 UI | CustomTkinter desktop app |
| Module 2 UI | Browser workspace (`scribe/assets`) |
| STT | OpenRouter (`openai/gpt-4o-transcribe`, `openai/whisper-large-v3`) with Groq Whisper fallback |
| LLM | Groq LLaMA 3.3-70B (configurable) |
| TTS | Edge TTS (Urdu neural voices); optional ElevenLabs / Hugging Face |
| Audio | sounddevice, soundfile, pygame-ce, NumPy |
| Security | Custom `security_guardrails` (gateway, PHI minimization, authz, audit) |

---

## Prerequisites

- **Python 3.11+** (3.12 also fine)
- **Microphone + speakers** (Module 1 voice mode)
- A modern browser (Module 2 doctor workspace)
- API keys:
  - **Required for AI features:** `GROQ_API_KEY`
  - Optional: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `HF_TTS_API_KEY`, `HF_TOKEN`

---

## Setup

### 1. Clone and enter the repo

```powershell
cd "C:\Nectar Project\FYP\FYP_Repo"
```

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```powershell
pip install -r requirements.txt
```

### 4. Configure environment

```powershell
copy .env.example .env
```

Edit `.env` and set at least:

```env
GROQ_API_KEY=your_groq_api_key_here
APP_ENV=development
MEDFLOW_API_BASE_URL=http://127.0.0.1:8000
SESSION_SECRET=change-me
```

Development already uses a default receptionist service token when `APP_ENV=development`. For production you must set a unique `MEDFLOW_RECEPTIONIST_SERVICE_TOKEN` (32+ characters).

---

## How to Run

Run the **backend first**, then Module 1 and/or Module 2.

### Step A — Start the clinic backend (required)

From the project root, with the virtual environment active:

```powershell
python -m uvicorn app.main:app --reload
```

Equivalent launchers (same app):

```powershell
python web_server.py
# or
python scribe/soap_server.py
```

Open the product home in a browser:

```text
http://127.0.0.1:8000
```

or

```text
http://127.0.0.1:8000/workspace
```

On first use, **register / sign in as a doctor** through the web UI (accounts are created via the auth API; clinic departments and slots are seeded automatically from `app/data/clinic_seed.json`).

### Step B — Run Module 1 (AI Receptionist)

With the backend already running on port `8000`, open the receptionist desk on the **same port, different endpoint**:

```text
http://127.0.0.1:8000/Receptionist
```

It uses the same Medflow theme as the doctor workspace and submits intake/booking through `/api/desk/*`.

Optional desktop / terminal voice agent (still supported):

```powershell
python main.py
python -m receptionist
python -m receptionist --no-ui
python -m receptionist --calibrate
```

| Command / URL | Mode |
| --- | --- |
| `http://127.0.0.1:8000/Receptionist` | Web receptionist desk (same port as clinic API) |
| `python main.py` | Desktop GUI (CustomTkinter) |
| `python main.py --no-ui` | Terminal-only voice agent |
| `python main.py --calibrate` | Terminal mode + microphone calibration |

The receptionist collects intake fields and posts a booking request that appears on the signed-in doctor's dashboard.
### Step C — Run Module 2 (AI Scribe Agent)

Module 2 runs **inside the same web app** — there is no separate scribe server.

1. Start the backend (Step A).
2. Sign in as a doctor at `http://127.0.0.1:8000`.
3. Open / create a patient workflow (or use a receptionist-booked appointment).
4. Complete doctor-side verification (development OTP when enabled).
5. Confirm the appointment and check in.
6. Grant consents (recording, transcription, documentation; retention optional).
7. Select a clinical template and choose guided mode (Automatic SOAP off) or automatic mode before recording.
8. Finish recording. In guided mode, review the saved original/English conversation, edit turns or roles, save corrections, then select **Generate SOAP**.
9. Review, edit, submit and approve the note. Use **View conversation** or a statement source to open the source panel. Generate the approved summary and complete the visit.

A fuller walkthrough lives in [`docs/demo/clinic-agent-demo-script.md`](docs/demo/clinic-agent-demo-script.md).

### Typical local demo order

```text
Terminal 1:  python -m uvicorn app.main:app --reload
Browser:     http://127.0.0.1:8000  (product home; doctor workspace at /workspace)
Terminal 2:  python main.py         (Module 1 AI Receptionist)
```

---

## Environment Variables

Copy from [`.env.example`](.env.example). Important keys:

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Primary LLM + STT fallback provider |
| `OPENROUTER_API_KEY` | Module 2 STT + transcript cleanup provider |
| `MODULE2_STT_PROVIDER` | Consultation STT provider (`openrouter` recommended) |
| `MODULE2_OPENROUTER_STT_MODEL` | Default: `openai/gpt-4o-transcribe` |
| `MODULE2_OPENROUTER_WHISPER_MODEL` | Fallback: `openai/whisper-large-v3` |
| `GROQ_STT_MODEL` / `GROQ_LLM_MODEL` | Groq model overrides |
| `MODULE2_GROQ_STT_MODEL` | Groq consultation STT fallback model |
| `DIARIZATION_PROVIDER` | `auto` or a configured provider |
| `MEDFLOW_API_BASE_URL` | Backend URL for the receptionist client |
| `MEDFLOW_RECEPTIONIST_SERVICE_TOKEN` | Service auth for receptionist → API |
| `SESSION_SECRET` | Signed web session secret |
| `APP_ENV` | `development` / production behavior |
| `MOCK_OTP_ENABLED` | Development patient verification OTP |
| `DEVELOPMENT_QUICK_START_ENABLED` | Local shortcut for synthetic demo patients |
| `FHIR_ENABLED` | Local FHIR export routes (default off) |
| `ICD_CODING_ENABLED` | ICD-10/CPT coding panel and APIs (default on in `.env.example`) |
| `PRIMARY_DOCTOR_EMAIL` | Clinic primary doctor account (full patient authorization) |
| `PRIMARY_DOCTOR_DISPLAY_NAME` | Display name for that doctor (default `Dr. Shahzaib Ali Khan`) |
| `MEDFLOW_AUDIO_RETENTION_ENABLED` | Keep consultation audio only with consent |
| `MEDFLOW_AUDIO_RETENTION_DIR` | Default: `scribe/retained_audio` |

---

## Testing

With the virtual environment active:

```powershell
# Full unit / integration suite
python -m unittest discover -s tests -v

# Security guardrails
python scripts\verify_guardrails.py

# Clinic-agent numbered flows
python scripts\verify_clinic_agent.py

# Frontend syntax check
node --check "scribe\assets\ui.js"
```

Architecture and status docs:

- [`docs/architecture/current-system.md`](docs/architecture/current-system.md)
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)
- [`docs/security/essential-guardrails.md`](docs/security/essential-guardrails.md)
- [`docs/TEST_CASES.md`](docs/TEST_CASES.md)

---

## Security Notes

- LLM/STT calls go through `security_guardrails` (actor/task checks, provider allowlists, PHI minimization).
- Receptionist routes do **not** issue or verify patient OTPs; verification is doctor-side.
- Audio chunks are deleted by default; retention requires explicit consent **and** `MEDFLOW_AUDIO_RETENTION_ENABLED=true`.
- JSON clinical storage is for development only; production needs a hardened database, TLS, encryption at rest, and secret management.
- Use only synthetic / demo patient data during local demos.

---

## License / Academic Use

This project is developed as a Final Year Project (FYP). Use and redistribution terms should follow your university / team agreement.
