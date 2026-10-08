"""Build fictional saved note versions and PDFs for offline browser/layout QA."""
import json
from pathlib import Path
from tests.test_clinical_documents import PrescriptionTests, turn
from app.services.conversation_relevance import apply_overrides
from app.services.pdf_reports import prescription_pdf
from app.services.prescription_service import save
from medflow.domain.enums import Speaker


def main():
    root=Path('/tmp/medflow-clinical-documents-qa');root.mkdir(exist_ok=True)
    test=PrescriptionTests();test.setUp()
    try:
        service=test.c.note_lifecycle_service
        turns=[test.transcript.utterances[0].model_copy(update={'original_text':'میں آپ کو Panadol 500 mg دے رہا ہوں۔ دن میں دو بار تین دن تک لیں۔'}),
            test.transcript.utterances[1].model_copy(update={'original_text':'Motilium بند کر دیں۔'}),
            turn('U3','The parking lot is full.',Speaker.PATIENT),turn('U4','Yes.',Speaker.PATIENT)]
        turns=apply_overrides(turns,[{'utterance_id':'U1','relevance_status':'included','relevance_reason':'Doctor medication instruction.'},
            {'utterance_id':'U2','relevance_status':'included','relevance_reason':'Doctor stop instruction.'},
            {'utterance_id':'U3','relevance_status':'excluded','relevance_reason':'Parking logistics, no clinical information.'}],test.actor)
        test.c.transcript_repository.save(test.transcript.model_copy(update={'utterances':turns}))
        before=service.payload(test.note,test.version,patient_name=test.patient.name)
        prepared=test.prepared();request=test.edit();note,version=save(service,test.note.note_id,test.actor,request)
        saved=service.payload(note,version,patient_name=test.patient.name)
        note,_=service.submit_for_review(note.note_id,actor=test.actor);note,version=service.approve(note.note_id,actor=test.actor)
        approved=service.payload(note,version,patient_name=test.patient.name)
        for name,value in [('draft',before),('prepared',prepared),('saved',saved),('approved',approved)]:
            (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2))
        (root/'prescription.pdf').write_bytes(prescription_pdf(approved,test.patient,test.user.full_name))
        print(str(root))
    finally:test.tearDown()


if __name__=='__main__':main()
