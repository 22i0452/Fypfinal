"""Reproducible, name-only import. Source metadata never supplies a prescription."""
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata


def build(path):
    raw=Path(path).read_bytes()
    grouped={};generic_names={};quarantined=[];count=0
    with Path(path).open(encoding='utf-8-sig',newline='') as handle:
        reader=csv.DictReader(handle)
        if not {'brand_name','medinfobase_id','medinfobase_url','drap_source_url'} <= set(reader.fieldnames or []):
            raise ValueError('Required medicine source columns are missing')
        for row_number,row in enumerate(reader,2):
            count+=1
            name=unicodedata.normalize('NFKC',row['brand_name']).strip()
            # Do not guess repairs for corrupted encoding or non-name records.
            if not name or len(name)>100 or re.search(r'[\x00-\x1f\x7f-\x9f]|â|Ã|�',name) or not re.search('[A-Za-z]',name):
                quarantined.append(row_number);continue
            key=name.casefold()
            entry=grouped.setdefault(key,[name,[],[]])
            entry[1].append(row_number)
            entry[2].append(row['medinfobase_id'])
            generic=unicodedata.normalize('NFKC',row.get('generic_name','')).strip()
            if generic and len(generic)<=100 and re.search('[A-Za-z]',generic) and not re.search(r'[\x00-\x1f\x7f-\x9f]|â|Ã|�',generic) and generic.casefold() not in {'unknown','not assigned','n/a','none'}:
                value=generic_names.setdefault(generic.casefold(),[generic,[],[]])
                value[1].append(row_number);value[2].append(row['medinfobase_id'])
    return {'version':1,'source':{'filename':Path(path).name,'sha256':hashlib.sha256(raw).hexdigest(),
        'data_rows':count,'brand_names':len(grouped),'generic_names':len(generic_names),'quarantined_rows':quarantined,
        'status':'user_supplied_reference','scope':'Names only. Registration, availability and clinical correctness are not verified by this import.'},
        'columns':['name','source_rows','medinfobase_ids'],
        'entries':[grouped[key] for key in sorted(grouped)],
        'generic_entries':[generic_names[key] for key in sorted(generic_names)]}


if __name__=='__main__':
    result=build(sys.argv[1]);Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    print(json.dumps(result['source']))
