"""Reference matching checks, never measured diagnostic accuracy."""
import unittest
from medflow.symptom_patterns import dataset,lookup
from scripts.import_symptom_dataset import EXCLUDED

def turn(text,uid='U1',speaker='Patient',english=''):
    return {'utterance_id':uid,'speaker':speaker,'original_text':text,'clinical_english':english}

class SymptomPatternsTests(unittest.TestCase):
    def test_dataset_deduplicated_with_source_rows_and_quarantine(self):
        data=dataset();self.assertEqual(data['source']['rows'],4920);self.assertEqual(len(data['patterns']),304)
        self.assertEqual(sum(len(row['source_rows']) for row in data['patterns']),4920)
        self.assertEqual(data['source']['diseases'],41)
        for row in data['symptoms']:
            if row['id'] in EXCLUDED:self.assertFalse(row['lookup_enabled'])

    def test_three_symptom_lookup_preserves_actual_turn_sources(self):
        report=lookup([turn('I have itching, skin rash and nodal skin eruptions.')])
        match=next(row for row in report['matches'] if row['disease_label']=='Fungal infection')
        self.assertEqual(len(match['matched_symptoms']),3);self.assertEqual(match['source_turns'],['U1'])
        self.assertTrue(match['source_rows']);self.assertNotIn('confidence',match)
        self.assertIn('not a diagnosis',match['label'])

    def test_sparse_common_symptoms_never_show_condition_labels(self):
        report=lookup([turn('I have headache and fever.')]);self.assertEqual(report['matches'],[])
        self.assertEqual(len(report['observations']),2)
        fever=next(row for row in report['observations'] if 'fever' in row['symptom_id'])
        self.assertEqual(fever['symptom_id'],'fever_unspecified')

    def test_urdu_wording_is_retained_without_severity_guess(self):
        report=lookup([turn('مجھے سر میں درد اور بخار ہے۔')])
        self.assertEqual({row['quote'] for row in report['observations']},{'سر میں درد','بخار'})
        self.assertEqual(report['matches'],[])

    def test_questions_and_hypothetical_instructions_are_not_symptoms(self):
        for text in ['Do you have itching, skin rash or nodal skin eruptions?','If you develop skin rash, return.','کیا آپ کو بخار ہے؟']:
            self.assertEqual(lookup([turn(text)])['observations'],[])
        self.assertEqual(lookup([turn('Ask about itching and skin rash.',speaker='Doctor')])['observations'],[])

    def test_denied_history_other_person_and_resolved_do_not_match_diagnosis(self):
        for text,state in [('No itching, skin rash or nodal skin eruptions.','denied'),('Last year I had itching and skin rash.','historical'),('My father has itching and skin rash.','other_person'),('My itching and skin rash have resolved.','resolved')]:
            report=lookup([turn(text)]);self.assertTrue(report['observations'])
            self.assertEqual({row['status'] for row in report['observations']},{state})
            self.assertEqual(report['matches'],[])

    def test_appetite_loss_intrinsic_negative_is_not_denial(self):
        for text,state in [('I have no appetite.','reported'),('No loss of appetite.','denied'),('I deny loss of appetite.','denied'),('Patient denies loss of appetite.','denied')]:
            report=lookup([turn(text)])
            self.assertEqual(report['observations'][0]['status'],state)

    def test_mixed_negation_or_translation_conflict_needs_review(self):
        report=lookup([turn('I have nausea and no vomiting.')]);self.assertEqual(report['matches'],[])
        self.assertEqual({row['status'] for row in report['observations']},{'needs_review'})
        report=lookup([turn('مجھے بخار ہے۔',english='I had fever last year.')]);self.assertEqual(report['observations'][0]['status'],'needs_review')

    def test_translation_only_extra_symptoms_do_not_create_disease_labels(self):
        report=lookup([turn('Synthetic unmatched wording.',english='I have itching, skin rash and nodal skin eruptions.')])
        self.assertEqual(report['matches'],[]);self.assertEqual({row['status'] for row in report['observations']},{'translation_only'})

    def test_duplicate_views_and_aliases_do_not_inflate_symptom_count(self):
        report=lookup([turn('I have high fever and shivering.',english='I have high fever and chills.')])
        self.assertEqual(report['matches'],[]);self.assertEqual(len(report['observations']),2)

    def test_source_revision_refreshes_and_conflicting_wording_excluded(self):
        before=lookup([turn('I have itching, skin rash and nodal skin eruptions.')])
        after=lookup([turn('No itching, skin rash or nodal skin eruptions.')])
        self.assertNotEqual(before['transcript_fingerprint'],after['transcript_fingerprint']);self.assertEqual(after['matches'],[])
        report=lookup([turn('I have itching.'),turn('No itching.','U2')]);self.assertIn('itching',report['conflicting_symptoms'])

if __name__=='__main__':unittest.main()
