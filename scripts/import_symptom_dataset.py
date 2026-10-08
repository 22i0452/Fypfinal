"""Read the supplied XLSX into a reproducible compact reference; never modify it."""
import argparse
from collections import Counter
import hashlib,json,re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
EXCLUDED={'acute_liver_failure','coma','extra_marital_contacts','family_history',
          'history_of_alcohol_consumption','receiving_blood_transfusion','receiving_unsterile_injections',
          'obesity','fluid_overload','irregular_sugar_level','enlarged_thyroid','toxic_look_(typhos)',
          'scurring','dischromic _patches'}

def build(source):
    raw=Path(source).read_bytes()
    with zipfile.ZipFile(source) as archive:
        if sum(info.file_size for info in archive.infolist())>40_000_000:raise ValueError('Oversized workbook')
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings=[''.join(t.text or '' for t in si.findall('.//s:t',NS)) for si in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si',NS)]
        rows=[]
        for element in ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).findall('.//s:sheetData/s:row',NS):
            row={}
            for cell in element.findall('s:c',NS):
                node=cell.find('s:v',NS);value=node.text if node is not None else ''.join(t.text or '' for t in cell.findall('.//s:t',NS))
                if cell.get('t')=='s':value=strings[int(value)]
                if value and value.strip():row[re.sub(r'\d','',cell.get('r'))]=value.strip()
            if row:rows.append((int(element.get('r')),row))
    expected={'A':'Disease',**{chr(66+i):f'Symptom_{i+1}' for i in range(17)}}
    if not rows or rows[0][1]!=expected:raise ValueError('Expected Disease and Symptom_1 through Symptom_17')
    patterns={};symptoms=set();labels=Counter()
    for number,row in rows[1:]:
        disease=row.get('A');codes=sorted(set(value for column,value in row.items() if column!='A'))
        if not disease or not codes:raise ValueError(f'Incomplete source row {number}')
        symptoms.update(codes);labels[disease]+=1
        key=json.dumps([disease,codes],ensure_ascii=False,separators=(',',':'))
        entry=patterns.setdefault(key,{'pattern_id':'SP_'+hashlib.sha256(key.encode()).hexdigest()[:16],
            'disease_label':disease,'symptom_ids':codes,'source_rows':[]})
        entry['source_rows'].append(number)
    return {'version':1,'source':{'filename':Path(source).name,'sha256':hashlib.sha256(raw).hexdigest(),
        'sheet':'in','rows':len(rows)-1,'unique_patterns':len(patterns),'diseases':len(labels),
        'symptoms':len(symptoms),'clinical_validation':'Unverified','origin':'User-supplied workbook; source provenance not supplied'},
        'symptoms':[{'id':code,'label':re.sub(r'[_\s]+',' ',code).strip(),'lookup_enabled':code not in EXCLUDED,
                     'exclusion_reason':'Requires clinical terminology review' if code in EXCLUDED else None} for code in sorted(symptoms)],
        'patterns':sorted(patterns.values(),key=lambda row:row['pattern_id'])}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input');parser.add_argument('output');args=parser.parse_args()
    output=build(args.input);Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(output['source']))
