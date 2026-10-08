"""Gold is used for scoring only, never as an ASR/translation prompt."""
import base64
import difflib
import io
import wave
from app.testing.evaluation import normalized,transcription_metrics


def role_alignment(reference,observed):
    unused=set(range(len(observed)));rows=[]
    for ref in reference:
        candidates=[(difflib.SequenceMatcher(None,normalized(ref['text']),normalized(observed[i]['original_text'])).ratio(),i) for i in unused]
        ratio,index=max(candidates,default=(0,None))
        matched=index is not None and ratio>=.35
        actual=observed[index]['speaker'].upper() if matched else 'UNMATCHED'
        if matched:unused.remove(index)
        rows.append({'source':ref['text'],'expected':ref['speaker'],'actual':actual,'text_similarity':round(ratio,3),
                     'correct':ref['speaker']==actual,'alignment':'Greedy distinct text match ≥ 0.35; not acoustic diarization'})
    return rows


def run_audio(clip,p,root):
    import numpy as np
    from medflow.medicines import check_turn
    from app.testing.worker import Clinic
    fixture=Clinic(root,'audio')
    try:
        with wave.open(io.BytesIO(base64.b64decode(clip['wav_base64'])),'rb') as wav:
            sample_rate=wav.getframerate();samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
        fixture.ready();service=fixture.c.documentation_service;patient=fixture.patient
        text=p.call('Audio → raw ASR and cleanup',lambda:service.transcribe(samples,input_sample_rate=sample_rate,patient_id=patient.patient_id))
        raw=str(getattr(text,'raw_asr_text',text))
        p.audio_metrics=transcription_metrics(clip['script']['reference'],raw)
        p.artifact('Original recording / observed ASR',{'reference':clip['script']['reference'],'raw_asr':raw,'cleaned':str(text),
            'word_errors':p.audio_metrics['word_errors'],'reference_words':p.audio_metrics['words'],'normalization':p.audio_metrics['normalization']},'transcribe')
        p.check('ASR returned nonempty text',True,bool(raw.strip()),'source_integrity')
        # WER is a measurement, not an arbitrary accuracy pass threshold.
        p.check('Raw reference wording matches exactly after normalization',0,p.audio_metrics['word_errors'])
        gold={name.casefold() for name in clip['script']['medicine_names']}
        heard={m['name'].casefold() for m in check_turn(raw,raw)['mentions']}
        p.audio_metrics.update(medicine_tp=len(gold&heard),medicine_fp=len(heard-gold),medicine_fn=len(gold-heard))
        p.artifact('Medicine name counts in raw ASR',{'reference_names':sorted(gold),'heard_names':sorted(heard),
            'matched':sorted(gold&heard),'missing':sorted(gold-heard),'extra':sorted(heard-gold)},'validate')
        turns=p.call('Observed text → speaker roles',lambda:service.diarize(text,patient=patient,transcript_id='TR-QA-AUDIO'))
        translated=p.call('Observed turns → clinical translation',lambda:service.translate(turns,patient=patient))
        observed=[{'utterance_id':t.utterance_id,'speaker':t.speaker.value,'original_text':t.original_text,
            'translation':t.clinical_english,'needs_review':t.needs_review,'medicine_checks':t.medicine_checks} for t in translated]
        roles=role_alignment(clip['script']['turns'],observed)
        p.audio_metrics.update(roles_expected=len(roles),roles_correct=sum(row['correct'] for row in roles))
        for row in roles:p.check('Role: '+row['source'],row['expected'],row['actual'],'speaker_role')
        for t in translated:
            p.check('Source medicine/instruction checks: '+t.utterance_id,[],t.medicine_checks.get('issues',[]),'instruction_preservation')
            p.check('Translation available: '+t.utterance_id,True,bool(t.clinical_english) and not t.clinical_english.startswith('[Translation requires review]'),'source_integrity')
        gold_check=check_turn(clip['script']['reference'],' '.join(t.clinical_english for t in translated))
        p.check('Reference medicine, dose and avoid instruction preserved',[],gold_check['issues'],'instruction_preservation')
        p.artifact('Reference wording / final translation check',{'source':clip['script']['reference'],'translation':' '.join(t.clinical_english for t in translated),'medicine_checks':gold_check},'validate')
        p.artifact('Observed turns and aligned roles',{'turns':observed,'role_alignment':roles,'reference_attestation':clip['reference_attestation'],
            'split':clip['script']['split'],'review_required':any(t.needs_review or t.medicine_checks.get('issues') for t in translated)},'translate')
    finally:fixture.close()
