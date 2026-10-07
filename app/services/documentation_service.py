from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.services.audit_service import AuditService
from app.services.clinic_lifecycle_service import ClinicLifecycleService
from app.services.template_service import TemplateService
from medflow.domain.enums import ClaimSupportStatus, NoteStatus, Speaker
from medflow.domain.ids import new_id
from medflow.domain.models import (
    ClinicalClaim,
    EvidenceReference,
    Patient,
    SOAPNote,
    SOAPNoteVersion,
    StructuredSOAP,
    TranscriptRecord,
    TranscriptUtterance,
    utc_now,
)
from medflow.repositories.protocols import NoteRepository, TranscriptRepository
from security_guardrails import (
    Actor,
    get_gateway,
    has_ai_differential_label,
    has_ai_management_label,
    require_authorized,
)
from receptionist.urdu_stt_utils import normalize_text, prepare_audio_for_stt, resample_audio


ROOT = Path(__file__).resolve().parents[2]
MODULE2_DIR = ROOT / "scribe"
SAMPLE_RATE = 16_000
MIN_AUDIO_SECONDS = 1.0
URDU_STT_PROMPT = (
    "Pakistani Urdu medical consultation between doctor and patient. "
    "Common words: موٹر بائیک، بائیک، حادثہ، پتھر، گر گیا، گھٹنا، ٹانگ، درد، "
    "سوجن، وزن، پین کلرز، دوا، احتیاط، فزیوتھراپی، گارڈ. "
    "Do not invent metal pipe when the patient means motorbike/bike. "
    "Transcribe only the exact spoken words in natural Urdu."
)
_REVIEW_WARNING_MESSAGES = {
    "ai_differential_requires_doctor_confirmation": (
        "AI-suggested differential requires doctor confirmation."
    ),
    "ai_management_requires_doctor_confirmation": (
        "AI-suggested management considerations require doctor confirmation."
    ),
    "fallback_draft_requires_clinician_review": (
        "The model draft was unavailable; a transcript-grounded fallback requires clinician review."
    ),
    "provider_error": (
        "The model provider was unavailable; a transcript-grounded fallback was created."
    ),
    "unknown_evidence_removed": "An unknown transcript evidence reference was removed.",
    "unsupported_clinical_fact:objective": (
        "An unsupported objective finding was removed from the AI draft."
    ),
    "unsupported_clinical_fact:assessment": (
        "An unsupported assessment was removed from the AI draft."
    ),
    "unsupported_clinical_fact:plan": "An unsupported plan was removed from the AI draft.",
    "unsupported_clinical_fact:medication_or_dosage": (
        "Unsupported medication or dosage content was removed from the AI draft."
    ),
}


class DocumentationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DocumentationDraft:
    note: SOAPNote
    version: SOAPNoteVersion
    transcript: TranscriptRecord
    legacy_soap: dict[str, Any]


class DocumentationService:
    def __init__(
        self,
        *,
        notes: NoteRepository,
        transcripts: TranscriptRepository,
        lifecycle: ClinicLifecycleService,
        audit: AuditService,
        templates: TemplateService,
    ) -> None:
        self.notes = notes
        self.transcripts = transcripts
        self.lifecycle = lifecycle
        self.audit = audit
        self.templates = templates
        self._diarizer = None
        self._translator = None
        self._soap_generator = None
        self._transcript_cleaner = None

    def transcribe(self, audio: np.ndarray, *, input_sample_rate: int, patient_id: str) -> str:
        if len(audio) < int(max(1, input_sample_rate) * MIN_AUDIO_SECONDS):
            return ""
        normalized_audio = np.asarray(audio, dtype=np.float32)
        if input_sample_rate != SAMPLE_RATE:
            normalized_audio = resample_audio(normalized_audio, input_sample_rate, SAMPLE_RATE)
        normalized_audio = prepare_audio_for_stt(normalized_audio)
        audio_bytes = self._to_wav_bytes(normalized_audio)
        transcript = get_gateway().transcribe_audio(
            task_type="module2_stt",
            audio_bytes=audio_bytes,
            actor=Actor.system("system_agent", patient_id),
            patient_ref=patient_id,
            language="ur",
            prompt=URDU_STT_PROMPT,
            response_format="text",
        )
        cleaned = normalize_text(transcript)
        if len(cleaned) >= 20:
            cleaned = self._cleaner().clean(cleaned, patient_ref=patient_id)
        return normalize_text(cleaned)

    def diarize(
        self,
        transcript_text: str,
        *,
        patient: Patient,
        transcript_id: str,
    ) -> list[TranscriptUtterance]:
        patient_context = self._patient_context(patient)
        entries = self._components()[0].diarize_transcript(
            transcript_text,
            patient_context=patient_context,
            patient_ref=patient.patient_id,
        )
        if not entries:
            entries = [
                {
                    "utterance_id": "U1",
                    "speaker": "Unknown",
                    "original_text": transcript_text,
                    "text": transcript_text,
                    "needs_review": True,
                }
            ]
        return [self._utterance(transcript_id, entry, index) for index, entry in enumerate(entries, start=1)]

    def translate(self, utterances: list[TranscriptUtterance], *, patient: Patient) -> list[TranscriptUtterance]:
        source = [self.utterance_payload(item) for item in utterances]
        entries = self._components()[1].translate_conversation(
            source,
            patient_context=self._patient_context(patient),
            patient_ref=patient.patient_id,
        )
        translated_by_id = {str(item.get("utterance_id")): item for item in entries}
        translated: list[TranscriptUtterance] = []
        for utterance in utterances:
            item = translated_by_id.get(utterance.utterance_id, {})
            translated.append(
                utterance.model_copy(
                    update={
                        "clinical_english": str(item.get("clinical_english") or item.get("text") or "").strip(),
                        "needs_review": utterance.needs_review or bool(item.get("needs_review")),
                    }
                )
            )
        return translated

    def save_transcript(
        self,
        *,
        transcript_id: str,
        patient_id: str,
        encounter_id: str,
        utterances: list[TranscriptUtterance],
    ) -> TranscriptRecord:
        return self.transcripts.save(
            TranscriptRecord(
                transcript_id=transcript_id,
                patient_id=patient_id,
                encounter_id=encounter_id,
                utterances=utterances,
            )
        )

    def generate_draft(
        self,
        *,
        workflow_id: str,
        patient: Patient,
        encounter_id: str,
        transcript: TranscriptRecord,
        actor: Actor,
        template_id: str | None = None,
    ) -> DocumentationDraft:
        require_authorized(actor, "create_note_draft", patient.patient_id)
        try:
            template = self.templates.require_active(template_id)
        except ValueError as exc:
            raise DocumentationError("TEMPLATE_NOT_FOUND", str(exc)) from exc
        context = self.lifecycle.start_documentation(workflow_id, actor=actor)
        if context.encounter.encounter_id != encounter_id or context.encounter.patient_id != patient.patient_id:
            raise DocumentationError("ENCOUNTER_MISMATCH", "Transcript encounter does not match the workflow")
        conversation = [self.utterance_payload(item, translated=True) for item in transcript.utterances]
        legacy_soap = self._components()[2].generate(
            self._patient_context(patient),
            conversation,
            template={"template_id": template.template_id, "name": template.name, "sections": template.sections},
        )
        note_id = new_id("NOTE")
        structured = self.build_structured_soap(note_id, legacy_soap, transcript)
        version = SOAPNoteVersion(
            note_version_id=new_id("NV"),
            note_id=note_id,
            version_number=1,
            status=NoteStatus.AI_DRAFT,
            soap=structured,
            evidence=[
                EvidenceReference(
                    evidence_id=item.utterance_id,
                    source_type="TRANSCRIPT_UTTERANCE",
                    source_id=item.utterance_id,
                    excerpt=item.clinical_english or item.original_text,
                )
                for item in transcript.utterances
            ],
            transcript_id=transcript.transcript_id,
            template_id=template.template_id,
            created_by_actor_id="soap-generator-agent",
            change_reason="AI-generated draft",
        )
        note = SOAPNote(
            note_id=note_id,
            patient_id=patient.patient_id,
            encounter_id=encounter_id,
            current_version_id=version.note_version_id,
            state=NoteStatus.AI_DRAFT,
        )
        self.notes.save_version(version)
        self.notes.save(note)
        self.lifecycle.documentation_ready(workflow_id, note_id=note_id, actor=actor)
        self.audit.record(
            "note_draft_generated",
            actor_ref=actor.ref,
            action="create_note_draft",
            patient_ref=patient.patient_id,
            resource_ref=note_id,
            metadata={
                "version": 1,
                "state": NoteStatus.AI_DRAFT.value,
                "template_ref": template.template_id,
            },
        )
        legacy_soap = {
            **legacy_soap,
            "state": NoteStatus.AI_DRAFT.value,
            "structured_soap": structured.model_dump(mode="json"),
        }
        return DocumentationDraft(note, version, transcript, legacy_soap)

    @staticmethod
    def utterance_payload(utterance: TranscriptUtterance, *, translated: bool = False) -> dict[str, Any]:
        text = utterance.clinical_english if translated and utterance.clinical_english else utterance.original_text
        return {
            "utterance_id": utterance.utterance_id,
            "segment_id": utterance.segment_id,
            "speaker": utterance.speaker.value.title(),
            "speaker_relation": utterance.speaker_relation,
            "addressed_to": utterance.addressed_to.value.title() if utterance.addressed_to else None,
            "start_ms": utterance.start_ms,
            "end_ms": utterance.end_ms,
            "original_text": utterance.original_text,
            "clinical_english": utterance.clinical_english,
            "text": text,
            "needs_review": utterance.needs_review,
        }

    @staticmethod
    def legacy_soap(structured: StructuredSOAP) -> dict[str, str]:
        def render(claims: list[ClinicalClaim]) -> str:
            return "\n".join(item.text for item in claims).strip() or "Not documented."

        return {
            "subjective": render(structured.subjective),
            "objective": render(structured.objective),
            "assessment": render(structured.assessment),
            "plan": render(structured.plan),
        }

    def build_structured_soap(
        self,
        note_id: str,
        soap: dict[str, Any],
        transcript: TranscriptRecord,
    ) -> StructuredSOAP:
        valid_ids = {item.utterance_id for item in transcript.utterances}
        requested_ids = [
            str(item.get("utterance_id"))
            for item in soap.get("evidence", [])
            if isinstance(item, dict) and item.get("utterance_id")
        ]
        unknown = sorted(set(requested_ids) - valid_ids)
        if unknown:
            raise DocumentationError("UNKNOWN_EVIDENCE", "SOAP draft referenced unknown transcript evidence")
        evidence_ids = list(dict.fromkeys(requested_ids))
        evidence_status = (
            ClaimSupportStatus.SUPPORTED
            if evidence_ids
            else ClaimSupportStatus.REVIEW_REQUIRED
        )
        generation_mode = str(soap.get("generation_mode") or "MODEL_VALIDATED")

        def claim(section: str) -> list[ClinicalClaim]:
            text = str(soap.get(section) or "Not documented.").strip()
            lowered = text.lower()
            requires_review = (
                generation_mode == "TRANSCRIPT_FALLBACK"
                or "not documented" in lowered
                or "requires review" in lowered
                or "was removed" in lowered
                or (section == "assessment" and has_ai_differential_label(text))
                or (section == "plan" and has_ai_management_label(text))
            )
            return [
                ClinicalClaim(
                    claim_id=f"{note_id}-{section.upper()}-001",
                    text=text,
                    evidence_ids=evidence_ids,
                    status=(
                        ClaimSupportStatus.REVIEW_REQUIRED
                        if requires_review
                        else evidence_status
                    ),
                )
            ]

        issues = [str(item) for item in soap.get("validation_issues", [])]
        review_flags = [str(item) for item in soap.get("review_flags", [])]
        warning_codes = list(dict.fromkeys([*review_flags, *issues]))
        warnings = [
            _REVIEW_WARNING_MESSAGES.get(
                code,
                code.replace("_", " ").replace(":", ": ").capitalize(),
            )
            for code in warning_codes
        ]
        missing_sections = [
            f"{section.title()} requires clinician input"
            for section in ("subjective", "objective", "assessment", "plan")
            if any(
                marker in str(soap.get(section) or "").lower()
                for marker in ("not documented", "was removed", "requires review")
            )
        ]
        return StructuredSOAP(
            subjective=claim("subjective"),
            objective=claim("objective"),
            assessment=claim("assessment"),
            plan=claim("plan"),
            missing_information=(
                missing_sections
                or (["Clinician review is required"] if not evidence_ids else [])
            ),
            warnings=warnings,
        )

    @staticmethod
    def _patient_context(patient: Patient) -> dict[str, Any]:
        return {
            "_id": patient.patient_id,
            "patient_id": patient.patient_id,
            "name": patient.name,
            "phone_number": patient.phone_number,
            "email": patient.email,
            "medical_record_number": patient.medical_record_number,
            "age": patient.age_text,
            "first_visit": patient.first_visit,
            "past_medical_history": patient.past_medical_history,
            "current_complaint": patient.current_complaint,
        }

    @staticmethod
    def _utterance(transcript_id: str, entry: dict, index: int) -> TranscriptUtterance:
        speaker = str(entry.get("speaker") or "UNKNOWN").upper()
        if speaker not in {item.value for item in Speaker}:
            speaker = Speaker.UNKNOWN.value
        original_text = str(entry.get("original_text") or entry.get("text") or "").strip()
        relation = str(entry.get("speaker_relation") or "").strip()[:40] or None
        addressed_to = str(entry.get("addressed_to") or "").upper()
        return TranscriptUtterance(
            transcript_id=transcript_id,
            utterance_id=str(entry.get("utterance_id") or f"U{index}"),
            segment_id=entry.get("segment_id"),
            speaker=Speaker(speaker),
            speaker_relation=relation if speaker == Speaker.ATTENDANT.value else None,
            addressed_to=(
                Speaker(addressed_to)
                if addressed_to in {item.value for item in Speaker}
                and addressed_to not in {speaker, Speaker.UNKNOWN.value}
                else None
            ),
            start_ms=entry.get("start_ms"),
            end_ms=entry.get("end_ms"),
            original_text=original_text,
            needs_review=bool(entry.get("needs_review")) or speaker == Speaker.UNKNOWN.value,
        )

    @staticmethod
    def _to_wav_bytes(audio: np.ndarray) -> bytes:
        import soundfile as sf

        with io.BytesIO() as buffer:
            sf.write(buffer, audio, SAMPLE_RATE, format="WAV")
            return buffer.getvalue()

    def _cleaner(self):
        if str(MODULE2_DIR) not in sys.path:
            sys.path.insert(0, str(MODULE2_DIR))
        if self._transcript_cleaner is None:
            from transcript_cleaner import TranscriptCleaner

            self._transcript_cleaner = TranscriptCleaner()
        return self._transcript_cleaner

    def _components(self):
        if str(MODULE2_DIR) not in sys.path:
            sys.path.insert(0, str(MODULE2_DIR))
        if self._diarizer is None:
            from llm_diarizer import LLMDiarizer

            self._diarizer = LLMDiarizer()
        if self._translator is None:
            from translator import MedicalTranslator

            self._translator = MedicalTranslator()
        if self._soap_generator is None:
            from soap_generator import SOAPGenerator

            self._soap_generator = SOAPGenerator()
        return self._diarizer, self._translator, self._soap_generator
