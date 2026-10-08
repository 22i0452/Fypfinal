"""Source-linked symptom pattern lookup, not a diagnosis or validated risk model."""
from __future__ import annotations
from functools import lru_cache
import hashlib,json,re
from pathlib import Path
from medflow.medicines import word_pattern

DATA_PATH=Path(__file__).resolve().parents[1]/'app/data/symptom_patterns.json'
ALIASES={
 'headache':['headache','headaches','سر درد','سر میں درد'],
 'high_fever':['high fever','تیز بخار','شدید بخار'],
 'mild_fever':['mild fever','low-grade fever','ہلکا بخار'],
 'fever_unspecified':['fever','بخار'],
 'nausea':['nausea','nauseous','متلی'],
 'vomiting':['vomiting','vomit','قے','الٹی','الٹیاں'],
 'cough':['cough','coughing','کھانسی'],
 'chest_pain':['chest pain','سینے میں درد','سینے کا درد'],
 'breathlessness':['breathlessness','shortness of breath','سانس کی تکلیف','سانس لینے میں مشکل'],
 'skin_rash':['skin rash','rash','جلد پر دانے'],
 'itching':['itching','itchy','خارش'],
 'fatigue':['fatigue','tiredness','تھکاوٹ'],
 'dizziness':['dizziness','dizzy','چکر'],
 'abdominal_pain':['abdominal pain','پیٹ میں درد','پیٹ کا درد'],
 'stomach_pain':['stomach pain','stomachache'],
 'belly_pain':['belly pain'],
 'back_pain':['back pain','کمر میں درد'],
 'joint_pain':['joint pain','جوڑوں میں درد'],
 'knee_pain':['knee pain','گھٹنے میں درد'],
 'muscle_pain':['muscle pain','پٹھوں میں درد'],
 'loss_of_appetite':['loss of appetite','no appetite','بھوک نہیں لگتی'],
 'diarrhoea':['diarrhoea','diarrhea','دست'],
 'constipation':['constipation','قبض'],
 'burning_micturition':['burning urination','burning when urinating','پیشاب میں جلن'],
 'chills':['chills'], 'shivering':['shivering','کپکپی'],
 'runny_nose':['runny nose','ناک بہنا'],
 'throat_irritation':['throat irritation','گلے میں خراش'],
 'sweating':['sweating','پسینہ'],
 'weight_loss':['weight loss','وزن کم'],
 'weight_gain':['weight gain','وزن بڑھ'],
 'dark_urine':['dark urine','گہرا پیشاب'],
 'yellowing_of_eyes':['yellowing of eyes','yellow eyes','آنکھیں پیلی'],
 'yellowish_skin':['yellowish skin','yellow skin','پیلی جلد'],
}
NEGATIVE=re.compile(r"\b(?:no|not|never|without|deny|denies|denied|don't|doesn't)\b|(?<!\w)(?:نہیں|نہ)(?!\w)",re.I)
HISTORY=re.compile(r'\b(?:previously|past history|history of|last year|years? ago|used to)\b|ماضی|گزشتہ سال|پہلے',re.I)
RESOLVED=re.compile(r'\b(?:resolved|gone|no longer)\b|ختم ہو|ٹھیک ہو',re.I)
OTHER_PERSON=re.compile(r'\b(?:my father|my mother|my husband|my wife|my brother|my sister|family history)\b|میرے (?:والد|والدہ|بھائی|شوہر)|میری (?:ماں|بہن|بیوی)',re.I)
HYPOTHETICAL=re.compile(r'\b(?:if|might|may|could|watch for|return for|look for|should|risk of)\b|اگر|ہو سکتا|خطرہ',re.I)
REPORTING=re.compile(r'\b(?:patient reports|patient has|patient denies|reports|observed|present|complains of)\b|مریض کو|مریض بتا|موجود',re.I)
GROUPS={'high_fever':'fever','mild_fever':'fever','fever_unspecified':'fever',
        'abdominal_pain':'abdominal_pain','stomach_pain':'abdominal_pain','belly_pain':'abdominal_pain',
        'shivering':'chills','chills':'chills'}

@lru_cache(maxsize=1)
def dataset():
    data=json.loads(DATA_PATH.read_text())
    if data.get('version')!=1 or not isinstance(data.get('patterns'),list):raise ValueError('Invalid symptom reference')
    return data

@lru_cache(maxsize=1)
def patterns():
    aliases={row['id']:[row['label']] for row in dataset()['symptoms'] if row['lookup_enabled']}
    for key,values in ALIASES.items():
        if key in aliases or key=='fever_unspecified':aliases.setdefault(key,[]).extend(values)
    return [(key,alias,word_pattern(alias)) for key,values in aliases.items() for alias in set(values)]

def extract(turns):
    observations=[]
    for item in turns:
        row=item if isinstance(item,dict) else item.model_dump(mode='json')
        original=row.get('original_text') or row.get('text') or ''
        english=row.get('clinical_english') or ''
        # Match the original first. Translation-only matches remain proposed and
        # never acquire invented Urdu evidence or verified clinical status.
        views=[('original',original)]
        if english and '[Translation ' not in english and english!=original:views.append(('clinical_english',english))
        speaker=str(row.get('speaker','Unknown')).upper();seen=set()
        for source_kind,text in views:
            for clause_match in re.finditer(r'[^.!?؟\n۔]+',text):
                chunk=clause_match.group()
                for segment in re.split(r'\bbut\b|\bhowever\b|لیکن|مگر',chunk,flags=re.I):
                    is_question=text[clause_match.end():clause_match.end()+1] in {'?','؟'} or 'کیا' in segment or re.match(r'\s*(?:do|does|did|have|has|is|are|any|what|when)\b',segment,re.I)
                    if is_question or HYPOTHETICAL.search(segment):continue
                    if speaker=='DOCTOR' and not REPORTING.search(segment):continue
                    if speaker not in {'PATIENT','NURSE','ATTENDANT','DOCTOR'}:continue
                    status='other_person' if OTHER_PERSON.search(segment) and speaker!='ATTENDANT' else 'resolved' if RESOLVED.search(segment) else 'historical' if HISTORY.search(segment) else 'denied' if NEGATIVE.search(segment) else 'reported'
                    found=[]
                    for key,alias,pattern in patterns():
                        for match in pattern.finditer(segment):found.append((match.start(),match.end(),key,match.group()))
                    kept=[]
                    for start,end,key,quote in sorted(found,key=lambda value:(-(value[1]-value[0]),value[0],value[2])):
                        if any(start<old[1] and old[0]<end for old in kept):continue
                        kept.append((start,end,key,quote))
                    neg=NEGATIVE.search(segment)
                    mixed_negation=bool(neg and any(start<neg.start() for start,_,_,_ in kept) and len(kept)>1)
                    for start,end,key,quote in sorted(kept):
                        # "No appetite" states appetite loss rather than negating it.
                        intrinsic_negative=key=='loss_of_appetite' and bool(NEGATIVE.search(quote))
                        external_negative=NEGATIVE.search(segment[:start]+' '+segment[end:])
                        state='reported' if intrinsic_negative and status=='denied' and not external_negative else status
                        if mixed_negation:state='needs_review'
                        if source_kind=='clinical_english' and state=='reported' and (GROUPS.get(key,key),'reported') in seen:continue
                        if source_kind=='clinical_english':state='translation_only' if state=='reported' else state
                        identity=(GROUPS.get(key,key),state)
                        if identity in seen:continue
                        seen.add(identity)
                        observations.append({'utterance_id':row['utterance_id'],'symptom_id':key,
                            'label':'fever (severity unspecified)' if key=='fever_unspecified' else next(value['label'] for value in dataset()['symptoms'] if value['id']==key),
                            'status':state,'source_kind':source_kind,'quote':quote,'excerpt':segment.strip(),
                            'speaker':speaker,'evidence_status':'source wording; clinical meaning requires review'})
    by_turn={}
    for row in observations:
        by_turn.setdefault((row['utterance_id'],GROUPS.get(row['symptom_id'],row['symptom_id'])),[]).append(row)
    for rows in by_turn.values():
        states={row['status'] for row in rows if row['status']!='translation_only'}
        if len(states)>1:
            for row in rows:row['status']='needs_review'
    return observations

def lookup(turns):
    data=dataset();observations=extract(turns)
    active={GROUPS.get(row['symptom_id'],row['symptom_id']) for row in observations if row['status']=='reported'}
    denied={GROUPS.get(row['symptom_id'],row['symptom_id']) for row in observations if row['status']=='denied'}
    unresolved={GROUPS.get(row['symptom_id'],row['symptom_id']) for row in observations if row['status']=='needs_review'}
    conflicting=(active&denied)|unresolved;active-=conflicting
    results=[]
    if len(active)>=3:
        best={}
        for pattern in data['patterns']:
            available={GROUPS.get(key,key) for key in pattern['symptom_ids']}
            matched=active&available
            # Unknown extra symptoms and denied expected symptoms are explicit;
            # sparse overlap never appears as a confident condition.
            if len(matched)<3 or available&denied or len(available-matched)>1 or len(active-available)>1:continue
            rank=(len(matched),-len(active-available),-len(available-matched))
            disease=pattern['disease_label']
            candidate={'pattern_id':pattern['pattern_id'],'disease_label':disease,
                'matched_symptoms':sorted(matched),'not_in_pattern':sorted(active-available),
                'not_reported':sorted(available-matched),'source_rows':pattern['source_rows'],
                'source_turns':sorted({row['utterance_id'] for row in observations if row['status']=='reported' and GROUPS.get(row['symptom_id'],row['symptom_id']) in matched}),
                'label':'Dataset pattern only; not a diagnosis'}
            if disease not in best or rank>best[disease][0]:best[disease]=(rank,candidate)
        results=[value[1] for _,value in sorted(best.items(),key=lambda item:(tuple(-part for part in item[1][0]),item[0]))[:3]]
    revision=json.dumps([item if isinstance(item,dict) else item.model_dump(mode='json') for item in turns],sort_keys=True,ensure_ascii=False)
    return {'version':1,'source':data['source'],'observations':observations,'matches':results,
        'conflicting_symptoms':sorted(conflicting),'minimum_distinct_symptoms':3,
        'transcript_fingerprint':hashlib.sha256(revision.encode()).hexdigest(),
        'scope':'Lookup in an unverified user-supplied symptom dataset. No disease probabilities, treatment advice or clinical validation.',
        'status':'conflicting_source' if conflicting else 'patterns_found' if results else 'insufficient_or_unmatched'}
