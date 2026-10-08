"""Inspectable medicine wording receipts; source linkage is not clinical proof."""
from medflow.medicines import check_turn, expected_name, word_pattern
from medflow.medicine_matching import query_candidates


def medicine_evidence(turns, soap=None, version=None):
    cards = []
    soap = soap or {}
    for value in turns:
        turn = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
        source = turn.get('original_text') or turn.get('text') or ''
        english = turn.get('clinical_english') or turn.get('text') or ''
        review = turn.get('medicine_review') or {}
        check = check_turn(source, english, review, context=turn.get('medicine_context', False),
                           analysis=turn.get('medicine_suggestions'))
        for row in check['mentions']:
            name = expected_name(row)
            # A doctor override is matched to its own exact catalogue wording,
            # never represented as the previously proposed candidate's receipt.
            catalogue = next((item for item in query_candidates(name)
                              if item['name'].casefold() == name.casefold()), None)
            links = [{'section':section, 'text':str(soap.get(section, ''))}
                     for section in ('subjective','objective','assessment','plan')
                     if word_pattern(name).search(str(soap.get(section, '')))]
            cards.append({'utterance_id':turn.get('utterance_id'), 'speaker':turn.get('speaker'),
                'source_span':row['source'], 'original':source, 'translation':english,
                'proposed_name':row.get('suggested_english') or row['name'], 'final_name':name,
                'catalogue':catalogue, 'doctor_reviewed':bool(check.get('reviewed_by')),
                'reviewed_by':check.get('reviewed_by'), 'confirmed_name':row.get('confirmed_english'),
                'soap_links':links, 'note_version':version, 'issues':check['issues'],
                'source_instruction':english,
                'context_status':(turn.get('medicine_suggestions') or {}).get('context_status', 'not_available')})
    return {'items':cards, 'scope':'Exact source wording and catalogue spelling references. '
            'No hearing, clinical correctness or confidence probability is established.'}
