"""Factual references for live pipeline checks; no model-generated scoring."""
from app.testing.catalog import catalog


def run_pipeline(identifier,p,root):
    from app.testing.worker import Clinic
    from app.testing.audio_cases import role_alignment
    from medflow.domain.models import Patient,TranscriptUtterance
    from medflow.domain.enums import Speaker
    from medflow.medicines import check_turn
    fixture=Clinic(root,'live_text')
    try:
        service=fixture.c.documentation_service;patient=Patient(patient_id='PT-QA-LIVE',name='Fictional QA Patient',age_text='23')
        source=next(row['input'] for row in catalog('live_text') if row['id']==identifier)
        if identifier=='live-three-roles':
            reference=[{'speaker':'DOCTOR','text':'آپ کو کیا مسئلہ ہے؟'},
                {'speaker':'PATIENT','text':'مجھے دو دن سے کھانسی ہے۔'},
                {'speaker':'ATTENDANT','text':'میں اس کی والدہ ہوں، اسے بخار بھی ہے۔'}]
            source=' '.join(row['text'] for row in reference)
            turns=p.call('Contextual text role inference',lambda:service.diarize(source,patient=patient,transcript_id='TR-QA-LIVE'))
            observed=[{'speaker':t.speaker.value,'original_text':t.original_text} for t in turns]
            roles=role_alignment(reference,observed)
            for row in roles:p.check('Speaker meaning: '+row['source'],row['expected'],row['actual'],'speaker_role')
            p.artifact('Supplied text / observed role alignment',{'source':source,'turns':observed,'alignment':roles},'interpret');return
        turn=TranscriptUtterance(transcript_id='TR-QA-LIVE',utterance_id='U1',speaker=Speaker.DOCTOR,original_text=source)
        translated=p.call('Full source context → medicine matching and translation',lambda:service.translate([turn],patient=patient))
        observed=translated[0];english=observed.clinical_english
        p.check('Translation supplied',True,bool(english) and not english.startswith('[Translation requires review]'),'source_integrity')
        p.check('Medicine/instruction wording safe',[],observed.medicine_checks.get('issues',[]),'instruction_preservation')
        # Independent authored brand expectations, rather than self-scoring model output.
        expected=['Panadol','Motilium'] if identifier=='live-two-medicines' else ['Motilium'] if identifier=='live-motilium-stop' else [] if identifier=='live-test-order' else ['Panadol']
        actual={m['name'].casefold() for m in check_turn(source,english)['mentions']}
        for name in expected:p.check('Brand retained: '+name,True,name.casefold() in english.casefold(),'medicine_preservation')
        if identifier=='live-test-order':p.check('No medicine introduced',[],sorted(actual),'unsafe_blocked')
        if identifier=='live-no-invented-dose':
            import re
            p.check('No invented numeric dose',False,bool(re.search(r'\d|\b(?:mg|ml|daily|twice|once|every|hours?|days?|weeks?|bedtime)\b',english,flags=re.I)),'unsafe_blocked')
        p.artifact('Original Urdu → observed translation',{'source':source,'clinical_english':english,
            'medicine_checks':observed.medicine_checks,'matching':observed.medicine_suggestions,'review_required':observed.needs_review},'translate')
    finally:fixture.close()
