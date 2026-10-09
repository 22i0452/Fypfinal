"""Read-only medicine-name index from the attached Pakistan medicines reference."""
from functools import lru_cache
import hashlib,json,re
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/'app/data/medicine_catalogue.json'

# PREVENT is a real catalogue brand as well as a common verb. Keep explicit
# brand uses ("Take PREVENT 10 mg"), but do not turn treatment purposes into drugs.
_PREVENT_VERB_RE = re.compile(
    r'prevent\s+(?:(?:a|an|the|further|future|another|any|recurrent|serious|severe|possible|potential)\s+)*'
    r'(?:fever|vomiting|nausea|pain|infections?|headaches?|relapse|complications?|'
    r'dehydration|disease|symptoms?|recurrence|diabetes|blood pressure|clots?|stroke|pregnancy|bleeding)\b',
    re.I,
)

def ordinary_brand_use(name, text, start):
    if name.casefold() != 'prevent':
        return False
    if _PREVENT_VERB_RE.match(text, start):
        return True
    # Purpose clauses can have arbitrary objects ("to prevent your symptoms
    # worsening"). Dose/form words still allow explicit brand references.
    return bool(re.search(r'\bto\s+$', text[:start], re.I) and re.match(
        r'\s+(?!(?:tablets?|capsules?|syrup|medicine|medication|drug|mg|mcg|ml|g)\b)[A-Za-z]',
        text[start + len(name):], re.I,
    ))

@lru_cache(maxsize=1)
def catalogue():
    data=json.loads(PATH.read_text(encoding='utf-8'))
    if data.get('version')!=1:raise ValueError('Invalid medicine catalogue')
    return data

@lru_cache(maxsize=1)
def entries():
    # A generic is another name that can be spoken, never a replacement for a
    # source brand. Exact collisions share the name while brand provenance wins.
    data=catalogue();brands={name.casefold() for name,_,_ in data['entries']}
    records=data['entries']+[row for row in data.get('generic_entries',[]) if row[0].casefold() not in brands]
    return [{'id':'PK_'+hashlib.sha256(name.casefold().encode()).hexdigest()[:16],
             'name':name,'aliases':[name],'status':'catalog_name','source_url':None,
             'reference_status':'user_supplied_reference','source_rows':source_rows,'medinfobase_ids':ids,
             'source_filename':catalogue()['source']['filename']}
            for name,source_rows,ids in records]

@lru_cache(maxsize=1)
def exact_index():
    return {row['name'].casefold():row for row in entries()}

def exact_mentions(text,*,context=False):
    from medflow.medicine_matching import FRAME_RE,ORDINARY
    found=[]
    for clause in re.finditer(r'[^;!?؟.\n۔]+',text):
        framed=context or bool(FRAME_RE.search(clause.group()))
        # Retain punctuation and digits within a brand; casefold only. A longest
        # exact phrase prevents Extend/Junior/DS variants collapsing to a family.
        words=list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9'’%+/-]*",clause.group()))
        if not framed and len(words)>6:continue
        for i,word in enumerate(words):
            for j in range(min(i+6,len(words)),i,-1):
                value=clause.group()[word.start():words[j-1].end()]
                row=exact_index().get(value.casefold())
                if row is None or value.casefold() in ORDINARY or len(value)<3:continue
                if ordinary_brand_use(value,clause.group(),word.start()):continue
                if not framed and (len(value)<5 or not re.fullmatch(r'\s*'+re.escape(value)+r'(?:\s+\d+(?:\s*(?:mg|mcg|ml|g))?)?\s*',clause.group(),re.I)):continue
                found.append({'start':clause.start()+word.start(),'end':clause.start()+words[j-1].end(),
                    'source':value,'name':row['name'],'catalog_id':row['id'],'status':'catalog_name',
                    'source_url':None,'reference_status':row['reference_status'],'source_filename':row['source_filename'],
                    'source_rows':row['source_rows']})
                break
    return found
