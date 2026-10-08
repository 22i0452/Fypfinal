"""Fictional, fixed audio scripts. References are never passed to STT as hints."""
VERSION='medflow-recordings-v1'

SCRIPTS=[
 ('audio-short-yes','Short Urdu confirmation','development', [('PATIENT','جی ہاں۔')]),
 ('audio-short-age','Short Urdu age','development',[('PATIENT','میری عمر تئیس سال ہے۔')]),
 ('audio-correction','Corrected age','development',[('PATIENT','نہیں، میری عمر بائیس نہیں، تئیس سال ہے۔')]),
 ('audio-panadol','Panadol and dose','development',[('DOCTOR','پیناڈول 500 mg لیں۔')]),
 ('audio-motilium','Motilium stop instruction','development',[('DOCTOR','موٹیلیم 10 mg نہ لیں۔')]),
 ('audio-two-medicines','Two medicines, different instructions','development',[('DOCTOR','پیناڈول 500 mg لیں۔ موٹیلیم 10 mg نہ لیں۔')]),
 ('audio-tests','Test order, not a medicine','development',[('DOCTOR','میں آپ کو خون کا ٹیسٹ لکھ کے دے رہا ہوں۔')]),
 ('audio-two-speakers','Doctor and patient','development',[('DOCTOR','آپ کو کیا مسئلہ ہے؟'),('PATIENT','مجھے دو دن سے کھانسی ہے۔')]),
 ('audio-mixed','Mixed Urdu and English','development',[('PATIENT','مجھے headache ہے اور fever بھی ہے۔'),('DOCTOR','Take Panadol 500 mg.')]),
 ('audio-three-speakers','Doctor, child and mother','development',[('DOCTOR','آپ کو کیا مسئلہ ہے؟'),('PATIENT','مجھے کھانسی ہے۔'),('ATTENDANT','میں اس کی والدہ ہوں، اسے دو دن سے بخار ہے۔'),('DOCTOR','خون کا ٹیسٹ کروائیں۔')]),
 ('audio-heldout-dose','Held-out: changed dose and avoidance','held_out',[('DOCTOR','Panadol 250 mg لیں۔ Motilium نہ لیں۔')]),
 ('audio-heldout-mother','Held-out: mother answers first','held_out',[('ATTENDANT','میں بچے کی والدہ ہوں۔ اسے کھانسی ہے۔'),('DOCTOR','کب سے کھانسی ہے؟'),('PATIENT','دو دن سے۔')]),
]


def scripts():
    return [{'id':identifier,'title':title,'split':split,'version':VERSION,
        'turns':[{'utterance_id':f'U{i+1}','speaker':speaker,'text':text} for i,(speaker,text) in enumerate(turns)],
        'reference':' '.join(text for _,text in turns),
        'medicine_names':(['Panadol','Motilium'] if identifier in {'audio-two-medicines','audio-heldout-dose'} else ['Panadol'] if identifier in {'audio-panadol','audio-mixed'} else ['Motilium'] if identifier=='audio-motilium' else []),
        'instructions':'Record exactly these fictional words. Use a different person for each role. '
            'Leave a short pause between turns. Upload an uncompressed PCM WAV, 1–90 seconds. '
            'This tests a recording through the pipeline, not browser microphone capture.'}
        for identifier,title,split,turns in SCRIPTS]


def script(identifier):return next((row for row in scripts() if row['id']==identifier),None)
