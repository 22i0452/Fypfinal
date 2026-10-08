"""Versioned, denominator-first evaluation. No model confidence or LLM judging."""
import hashlib
import json
import math
import re
import statistics
import unicodedata

PROTOCOL='medflow-evaluation-v1'
METRICS={'medicine_preservation','instruction_preservation','unsafe_blocked','valid_allowed','source_integrity','speaker_role'}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def rate(numerator,denominator):
    return {'numerator':numerator,'denominator':denominator,
            'percent':round(100*numerator/denominator,2) if denominator else None}


def scores(report):
    rows=report.get('cases',[]);attempted=[r for r in rows if r['status'] in {'PASSED','FAILED','ERROR'}]
    checks=[c for r in rows for c in r.get('checks',[]) if c.get('status') in {'PASSED','FAILED'}]
    categories=[]
    for name in dict.fromkeys(r['category'] for r in rows):
        group=[r for r in rows if r['category']==name];done=[r for r in group if r['status'] in {'PASSED','FAILED','ERROR'}]
        categories.append({'name':name,**rate(sum(r['status']=='PASSED' for r in done),len(done)),
            'planned':len(group),'failed':sum(r['status']=='FAILED' for r in group),
            'errors':sum(r['status']=='ERROR' for r in group),'unassessed':len(group)-len(done)})
    metrics={}
    for name in sorted(METRICS):
        group=[c for c in checks if c.get('metric')==name]
        metrics[name]=rate(sum(c['status']=='PASSED' for c in group),len(group))
    times=sorted(r['duration_ms'] for r in attempted if isinstance(r.get('duration_ms'),(int,float)) and math.isfinite(r['duration_ms']) and r['duration_ms']>=0)
    audio=[r['audio_metrics'] for r in rows if r.get('audio_metrics')]
    words=sum(r['words'] for r in audio);errors=sum(r['word_errors'] for r in audio)
    characters=sum(r['characters'] for r in audio);char_errors=sum(r['character_errors'] for r in audio)
    tp=sum(r.get('medicine_tp',0) for r in audio);fp=sum(r.get('medicine_fp',0) for r in audio);fn=sum(r.get('medicine_fn',0) for r in audio)
    return {'protocol':PROTOCOL,'success':rate(sum(r['status']=='PASSED' for r in attempted),len(attempted)),
        'completion':rate(len(attempted),len(rows)),'checks':rate(sum(c['status']=='PASSED' for c in checks),len(checks)),
        'categories':categories,'metrics':metrics,
        'timings':{'n':len(times),'median_ms':round(statistics.median(times),2) if times else None,
                   'p95_ms':round(times[max(0,math.ceil(.95*len(times))-1)],2) if times else None,
                   'scope':report.get('timing_scope')},
        'audio':{'clips':len(audio),'word_error_rate':rate(errors,words),'character_error_rate':rate(char_errors,characters),
                 'medicine_precision':rate(tp,tp+fp),'medicine_recall':rate(tp,tp+fn),
                 'roles':rate(sum(r.get('roles_correct',0) for r in audio),sum(r.get('roles_expected',0) for r in audio))}}


def comparison(baseline,current):
    reasons=[]
    for field in ('mode','pack_version','reference_sha256','evaluation_protocol'):
        if not baseline.get(field) or baseline.get(field)!=current.get(field):reasons.append('Different or missing '+field.replace('_',' '))
    if baseline.get('mode')!='synthetic' and baseline.get('environment',{}).get('provider_settings')!=current.get('environment',{}).get('provider_settings'):
        reasons.append('Different provider/model settings')
    if baseline['run_id']==current['run_id']:reasons.append('Select two different runs')
    if any(r['status']=='RUNNING' for r in (baseline,current)):reasons.append('A selected run is unfinished')
    old=scores(baseline);new=scores(current)
    if old['success']['denominator']!=len(baseline['cases']) or new['success']['denominator']!=len(current['cases']):
        reasons.append('Both runs must attempt the complete same pack')
    if [r['id'] for r in baseline['cases']]!=[r['id'] for r in current['cases']]:reasons.append('Different selected cases or repetitions')
    if baseline.get('mode')!='synthetic':
        def used(report):return sorted({(str(row.get('task') or 'unspecified'),str(row.get('provider') or 'unspecified'),str(row.get('model') or 'unspecified')) for case in report['cases'] for row in case.get('provider_calls',[])})
        if used(baseline)!=used(current):reasons.append('Different actual provider tasks/models; inspect fallback receipts')
    delta=None if reasons else round(new['success']['percent']-old['success']['percent'],2)
    categories=[]
    for row in new['categories']:
        previous=next((r for r in old['categories'] if r['name']==row['name']),None)
        categories.append({'name':row['name'],'baseline':previous,'current':row,
            'delta_pp':None if reasons or not previous or row['percent'] is None or previous['percent'] is None else round(row['percent']-previous['percent'],2)})
    return {'compatible':not reasons,'reasons':reasons,'baseline_id':baseline['run_id'],'current_id':current['run_id'],
        'baseline':old,'current':new,'success_delta_pp':delta,'categories':categories,
        'scope':'Same fixed references and configuration; observed sample difference, not a causal or clinical claim.'}


def normalized(text):
    text=unicodedata.normalize('NFKC',str(text)).casefold()
    text=''.join(c for c in text if unicodedata.category(c) not in {'Mn','Cf'})
    # Preserve words/digits; punctuation is excluded identically on both sides.
    return ' '.join(re.findall(r'\w+',text,flags=re.UNICODE))


def edit_distance(reference,prediction):
    row=list(range(len(prediction)+1))
    for i,token in enumerate(reference,1):
        next_row=[i]
        for j,other in enumerate(prediction,1):next_row.append(min(next_row[-1]+1,row[j]+1,row[j-1]+(token!=other)))
        row=next_row
    return row[-1]


def transcription_metrics(reference,prediction):
    ref=normalized(reference);pred=normalized(prediction)
    # WER may exceed 100% when many words are inserted; never clamp it.
    words=ref.split();actual=pred.split()
    chars=ref.replace(' ','');observed=pred.replace(' ','')
    return {'normalization':'NFKC, casefold, diacritic/format/punctuation removal; no spelling correction',
        'words':len(words),'word_errors':edit_distance(words,actual),'characters':len(chars),
        'character_errors':edit_distance(chars,observed),'wer':rate(edit_distance(words,actual),len(words))}
