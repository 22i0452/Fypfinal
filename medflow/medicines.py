"""Conservative name preservation, not drug identification or prescribing advice."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata

CATALOG_PATH = Path(__file__).resolve().parents[1] / 'app/data/medicine_vocabulary.json'
TOKEN_RE = re.compile(r'MF_MED_[A-Fa-f0-9]{10}_\d+')
CONTEXT_RE = re.compile(r'(?<!\w)(?:medicine|medication|tablet|capsule|syrup|prescrib\w*|dawai|dawa|دوائی|دوا|دوائیں|گولی|گولیاں|کیپسول|شربت)(?!\w)', re.I)
NEGATION_RE = re.compile(r"(?<!\w)(?:not|never|no|without|stop|stopped|avoid|don[’']?t|نہیں|نہ|مت|بند)(?!\w)", re.I)
DOSE_RE = re.compile(r'(?<!\w)([\d۰-۹٠-٩]+(?:[.٫][\d۰-۹٠-٩]+)?)\s*(mg|mcg|g|ml|ملی\s*گرام|ملی\s*لیٹر|مائیکرو\s*گرام|گرام)(?!\w)', re.I)
STOP = frozenset('medicine medication tablet tablets capsule capsules syrup drug drugs dawai dawa take taking give giving prescribed prescribe daily twice pain fever for a an the this that it is was am are be to you me my i and or of with without not no now yes fixed painkillers painkiller مجھے میں آپ اپ کو کی کا کے پر دے دیں دینا رہا رہی رہے ہوں ہے ہیں تھی تھا یہ وہ نہیں نہ مت درد بخار روز دن بار ایک دو تین چار صبح شام رات گولی دوا دوائی دواں شربت کیپسول لیتا لیتی لیں لینی لینا کھائیں کھانا بند بھی سے اور یا کر کریں ہو جاتا جاتی ساتھ وزن سردرد سردی کھانسی پیٹ ٹانگ گھٹنا'.split())


@lru_cache(maxsize=1)
def vocabulary():
    data = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('entries'), list):
        raise ValueError('Invalid medicine vocabulary')
    return data


def word_pattern(text):
    # Optional Arabic combining marks do not change spelling; never fuzzy replace.
    letters = []
    for c in text:
        if c.isspace(): letters.append(r'\s+')
        elif unicodedata.combining(c): continue
        else: letters.append(re.escape(c) + (r'[\u064b-\u065f]*' if '\u0600' <= c <= '\u06ff' else ''))
    return re.compile(r'(?<!\w)' + ''.join(letters) + r'(?!\w)', re.I)


@lru_cache(maxsize=1)
def alias_patterns():
    return [(word_pattern(alias), row) for row in vocabulary()['entries'] for alias in set(row['aliases'])]


def mentions(text,*,context=False):
    """Exact aliases first; context candidates are preserved, never autocorrected."""
    found = []
    for pattern, row in alias_patterns():
        for match in pattern.finditer(text):
            found.append({'start': match.start(), 'end': match.end(), 'source': match.group(),
                          'name': row['name'], 'catalog_id': row['id'], 'status': row['status'],
                          'source_url': row.get('source_url')})
    from medflow.medicine_catalogue import exact_mentions
    found.extend(exact_mentions(text,context=context))
    chosen = []
    for item in sorted(found, key=lambda v: (-(v['end']-v['start']), v['start'])):
        if not any(item['start'] < old['end'] and old['start'] < item['end'] for old in chosen): chosen.append(item)
    # Names immediately beside "medicine/tablet/دوا". General prescribing language
    # supplies context only; it cannot establish a drug name or dose.
    for cue in CONTEXT_RE.finditer(text):
        before = list(re.finditer(r'[A-Za-z\u0600-\u06ff][\w\u064b-\u065f-]*', text[max(0,cue.start()-35):cue.start()]))
        after = re.match(r'\s+([A-Za-z\u0600-\u06ff][\w\u064b-\u065f-]*)', text[cue.end():])
        candidates = []
        if before:
            b=before[-1]; offset=max(0,cue.start()-35)
            if not text[offset+b.end():cue.start()].strip(): candidates.append((offset+b.start(),offset+b.end(),b.group()))
        if after: candidates.append((cue.end()+after.start(1),cue.end()+after.end(1),after.group(1)))
        for start,end,raw in candidates:
            normalized=''.join(c for c in raw if not unicodedata.combining(c)).casefold()
            if normalized in STOP or len(normalized)<3 or any(start < old['end'] and old['start'] < end for old in chosen): continue
            chosen.append({'start':start,'end':end,'source':raw,'name':raw,'catalog_id':None,'status':'context_candidate','source_url':None})
    from medflow.medicine_matching import contextual_candidates,ORDINARY
    for match in re.finditer(r'(?:آپ|اپ)\s+کو\s+([A-Za-z\u0600-\u06ff][\w\u064b-\u065f-]*)(?=.{0,45}دے\s+رہا)',text):
        raw=match.group(1);start,end=match.span(1)
        if raw.casefold() in STOP or raw.casefold() in ORDINARY or len(raw)<3 or any(start<row['end'] and row['start']<end for row in chosen):continue
        chosen.append({'start':start,'end':end,'source':raw,'name':raw,'catalog_id':None,'status':'context_candidate','source_url':None})
    chosen=[row for row in chosen if row['status']!='context_candidate' or row['source'].casefold() not in ORDINARY]
    chosen.extend(contextual_candidates(text,chosen,context=context))
    return sorted(chosen,key=lambda v:v['start'])


def protect(text, namespace='turn',*,context=False):
    rows=mentions(text,context=context)
    prefix='MF_MED_'+hashlib.sha256((namespace+':'+text).encode()).hexdigest()[:10]
    for index,item in enumerate(rows): item['token']=prefix+'_'+str(index)
    protected=text
    for item in reversed(rows): protected=protected[:item['start']]+item['token']+protected[item['end']:]
    return protected,rows


def restore(text, rows, *, english=True):
    for item in rows:
        value=item['name'] if english and item['status']=='catalog_name' else item['source']
        text=text.replace(item['token'],value)
    return text


def normalized_doses(text):
    units={'ملیگرام':'mg','ملیلیٹر':'ml','مائیکروگرام':'mcg','گرام':'g'}
    result=[]
    for number,unit in DOSE_RE.findall(text):
        number=''.join(str(unicodedata.digit(c)) if c.isdigit() else '.' if c=='٫' else c for c in number)
        unit=re.sub(r'\s+','',unit).casefold()
        result.append(number+units.get(unit,unit))
    return Counter(result)


def translation_issues(source, target, rows=None):
    rows=mentions(source) if rows is None else rows
    issues=[]
    expected=Counter(row['name'] if row['status']=='catalog_name' else row['source'] for row in rows)
    for name,count in expected.items():
        # Unverified catalogue transliterations can be confirmed by a clinician,
        # but automatic translation still preserves the literal source spelling.
        if len(word_pattern(name).findall(target)) < count: issues.append('name_missing_or_changed:'+name)
    source_ids={row['catalog_id'] for row in rows if row['catalog_id']}
    if any(row['status']=='catalog_name' and row['catalog_id'] not in source_ids for row in mentions(target)):
        issues.append('medicine_introduced')
    if TOKEN_RE.search(target): issues.append('unresolved_medicine_token')
    if rows and normalized_doses(source)!=normalized_doses(target): issues.append('stated_dose_changed')
    if rows:
        target_rows=[]
        for row in rows:
            name=row['name'] if row['status']=='catalog_name' else row['source']
            target_rows.extend({**row,'start':m.start(),'end':m.end()} for m in word_pattern(name).finditer(target))
        if linked_doses(source,rows)!=linked_doses(target,target_rows): issues.append('medicine_dose_link_changed')
    if rows and bool(NEGATION_RE.search(source)) != bool(NEGATION_RE.search(target)):
        issues.append('negation_or_stopping_changed')
    if rows:
        normalized_source=source
        names=[]
        for row in reversed(rows):
            name=row['name'] if row['status']=='catalog_name' else row['source']
            names.append(name)
            normalized_source=normalized_source[:row['start']]+name+normalized_source[row['end']:]
        original_polarities=name_polarities(normalized_source,names)
        target_polarities=name_polarities(target,names)
        if any(name in target_polarities and target_polarities[name]!=value for name,value in original_polarities.items()):
            issues.append('medicine_negation_link_changed')
    return list(dict.fromkeys(issues))


def fingerprint(original, english):
    return hashlib.sha256((original+'\0'+english).encode()).hexdigest()


def check_turn(original, english, review=None,*,context=False):
    rows=mentions(original,context=context)
    checked=bool(review and review.get('fingerprint')==fingerprint(original,english))
    compared=[dict(row) for row in rows]
    # A clinician's explicit English spelling is permitted for an unverified name
    # only when the exact turn was reviewed; known brands can never disappear.
    if checked:
        unknown=[r for r in rows if r['status']!='catalog_name']
        for row in unknown:
            spelling=review.get('spellings',{}).get(row['source'],row['name'])
            if spelling and word_pattern(spelling).search(english):
                row['confirmed_english']=spelling
                for value in compared:
                    if value['start']==row['start']:
                        value.update(name=spelling,status='catalog_name')
                        matching=mentions(spelling)
                        if matching: value['catalog_id']=matching[0]['catalog_id']
    issues=translation_issues(original,english,compared)
    if rows and re.search(r'\[Translation (?:requires review|needed)\]',english,re.I): issues.append('translation_confirmation_required')
    if any(row['status']!='catalog_name' for row in rows) and not checked: issues.append('name_confirmation_required')
    return {'mentions':rows,'issues':list(dict.fromkeys(issues)),
            'status':'review' if issues else 'preserved' if rows else 'not_detected',
            'reviewed_by':review.get('reviewed_by') if checked else None}


def clinician_review(original, english, spellings, actor_ref,*,context=False):
    """Attest an exact revision; never use an acknowledgement to bypass known names."""
    unknown={r['source'] for r in mentions(original,context=context) if r['status']!='catalog_name'}
    if any(key not in unknown or not isinstance(value,str) or not value.strip()
           or len(value)>100 or not word_pattern(value.strip()).search(english)
           for key,value in spellings.items()):
        raise ValueError('Each confirmed spelling must name an uncertain source mention and appear in the English turn.')
    review={'fingerprint':fingerprint(original,english),'reviewed_by':actor_ref,
            'spellings':{key:value.strip() for key,value in spellings.items()}}
    if check_turn(original,english,review,context=context)['issues']:
        raise ValueError('Correct the medicine name, stated dose or negation in the English turn before confirming it.')
    return review


def linked_doses(text, rows):
    """Assign each stated dose to its nearest medicine in the same sentence."""
    assigned={}
    for dose in DOSE_RE.finditer(text):
        choices=[]
        for row in rows:
            between=text[min(dose.end(),row['end']):max(dose.start(),row['start'])]
            if re.search(r'[;!?\n۔]|\.(?!\d)',between): continue
            distance=min(abs(dose.start()-row['end']),abs(row['start']-dose.end()))
            if distance<=100: choices.append((distance,row))
        if choices:
            row=min(choices,key=lambda pair:pair[0])[1]
            key=row.get('confirmed_english') or row['name']
            assigned.setdefault(key,Counter()).update(normalized_doses(dose.group()))
    return assigned


def name_polarities(text, names):
    result={}
    # Clause-level checks are intentionally conservative, not a semantic model.
    for clause in re.split(r'[;!?\n۔]|\.(?!\d)',text):
        negative=bool(NEGATION_RE.search(clause))
        for name in names:
            if word_pattern(name).search(clause): result.setdefault(name,set()).add(negative)
    return result


def soap_issues(utterances, soap):
    """Check medication identity against the source, independently of source links."""
    source=[]
    for item in utterances:
        row=item if isinstance(item,dict) else item.model_dump(mode='json')
        text=row.get('clinical_english') or row.get('text') or row.get('original_text') or ''
        checked=check_turn(row.get('original_text') or text,text,row.get('medicine_review'),context=row.get('medicine_context',False))
        names=[r.get('confirmed_english') or (r['name'] if r['status']=='catalog_name' else r['source']) for r in checked['mentions']]
        source.append((text,names))
    text='\n'.join(str(soap.get(section,'') or '') for section in ('subjective','objective','assessment','plan'))
    expected={name for _,names in source for name in names}
    expected_spellings={name.casefold() for name in expected}
    issues=['soap_medicine_missing:'+name for name in sorted(expected) if not word_pattern(name).search(text)]
    for row in mentions(text):
        if row['status']=='catalog_name' and row['name'].casefold() not in expected_spellings:
            issues.append('soap_medicine_introduced:'+row['name'])
    # A named medicine's stated dose must remain attached to that same name.
    target_rows=[{'start':m.start(),'end':m.end(),'name':name} for name in expected for m in word_pattern(name).finditer(text)]
    target_doses=linked_doses(text,target_rows)
    expected_doses={name:set() for name in expected}
    expected_polarities={name:set() for name in expected}
    for original,names in source:
        rows=[{'start':m.start(),'end':m.end(),'name':name} for name in names for m in word_pattern(name).finditer(original)]
        for name,doses in linked_doses(original,rows).items(): expected_doses[name].update(doses)
        for name,polarities in name_polarities(original,names).items(): expected_polarities[name].update(polarities)
    target_polarities=name_polarities(text,expected)
    for name in expected:
        actual=set(target_doses.get(name,{}))
        if actual!=expected_doses[name]: issues.append('soap_medicine_dose_changed:'+name)
        if name in target_polarities and target_polarities[name]!=expected_polarities[name]:
            issues.append('soap_medicine_negation_changed:'+name)
    return list(dict.fromkeys(issues))


def report(utterances):
    checks=[]
    for item in utterances:
        row=item if isinstance(item,dict) else item.model_dump(mode='json')
        checked=check_turn(row.get('original_text') or row.get('text') or '',row.get('clinical_english') or row.get('text') or '',row.get('medicine_review'),context=row.get('medicine_context',False))
        if checked['mentions'] or checked['issues']: checks.append({'utterance_id':row['utterance_id'],**checked})
    return {'checks':checks,'requires_review':any(c['issues'] for c in checks),'catalog_version':vocabulary()['version'],
            'scope':'Name/dose/negation preservation checks. Not medicine identification, calibrated confidence or clinical correctness.'}


def stt_vocabulary_hint():
    # Short spelling context, not an instruction to add drugs to speech.
    return ' Medicine spellings when actually spoken: پیناڈول Panadol، موٹیلیم Motilium، آگمینٹن Augmentin، کالپول Calpol. Preserve exact names; never substitute a medicine class.'
