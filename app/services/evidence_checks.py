"""Observable structural checks. These are not calibrated model confidence."""
from __future__ import annotations


def check(code, label, status, detail):
    return {"code": code, "label": label, "status": status, "detail": detail}


def note_evidence_report(soap, transcript, *, state="AI_DRAFT", version=1, note_id="", approval=None):
    turns = transcript.utterances if transcript else []
    by_id = {item.utterance_id: item for item in turns}
    approved = str(getattr(state, "value", state)) == "APPROVED_BY_DOCTOR"
    rows = []
    normal = lambda text: " ".join(str(text or "").split())
    for section in ("subjective", "objective", "assessment", "plan"):
        for claim in getattr(soap, section):
            refs = list(claim.evidence_ids)
            known = bool(refs) and all(ref in by_id for ref in refs)
            sources = [{"utterance_id": ref, "speaker": by_id[ref].speaker.value,
                        "original": by_id[ref].original_text, "translation": by_id[ref].clinical_english,
                        "needs_review": by_id[ref].needs_review} for ref in refs if ref in by_id]
            exact = bool(normal(claim.text)) and known and any(normal(claim.text) in normal(source["original"]) or
                                     normal(claim.text) in normal(source["translation"]) for source in sources)
            unsupported = claim.status.value == "UNSUPPORTED"
            missing = any(marker in claim.text.lower() for marker in ("not documented", "requires review", "was removed")) or normal(claim.text).lower() == "no vital signs, examination findings, or completed diagnostic results were documented in the supplied encounter."
            checks = [
                check("reference_integrity", "Attached source IDs", "passed" if known else "failed" if refs else "unassessed",
                      "Every attached ID exists in this transcript." if known else "An attached ID is unknown." if refs else "No claim-level source IDs were supplied."),
                check("exact_text_match", "Exact text comparison", "passed" if exact else "unassessed",
                      "The statement occurs verbatim, ignoring whitespace, in an attached source." if exact else "No exact text match established. Semantic support has not been measured."),
                check("clinical_support", "Clinical meaning", "failed" if unsupported else "review",
                      "Statement marked unsupported." if unsupported else "Source attribution and lexical matching do not establish clinical correctness."),
                check("doctor_approval", "Current note approval", "passed" if approved else "review",
                      "This note version was approved by a doctor." if approved else "An authenticated doctor must review this draft."),
            ]
            status = "failed" if unsupported or refs and not known else "missing" if missing else "checked" if approved else "review"
            rows.append({"claim_id": claim.claim_id, "section": section, "text": claim.text,
                         "status": status, "label": "Unsupported" if unsupported else "Unknown source ID" if refs and not known else "Missing detail" if missing else "Doctor approved" if approved else "Doctor review",
                         "source_ids": refs, "sources": sources, "checks": checks,
                         "exact_text_match": bool(exact), "has_source": known})
    return {"schema": "EVIDENCE-CHECKS-V1", "scope": "Current note version", "note_id": note_id,
            "version": version, "state": str(getattr(state, "value", state)), "approval": approval,
            "confidence": None, "confidence_status": "Not calibrated or measured",
            "claims": rows, "counts": {"statements": len(rows), "linked": sum(row["has_source"] for row in rows),
            "exact_matches": sum(row["exact_text_match"] for row in rows),
            "review": sum(row["status"] == "review" for row in rows), "missing": sum(row["status"] == "missing" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows)},
            "warnings": list(soap.warnings), "missing_information": list(soap.missing_information)}
