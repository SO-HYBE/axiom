from copy import deepcopy
import unittest

from axiom.model import validate_review, verbatim_quote_guidance
from axiom.research import run, MAX_CONTEXT_CHARS
from axiom.retrieval import explicit_scope_context, search
from test_research import corpus


class ContextModel:
    name = 'synthetic-context'
    provider = 'fixture'
    def __init__(self):
        self.calls = []
        self.received = []
    def draft(self, question, evidence, baseline=False):
        self.received.append(deepcopy(evidence))
        return {'claims': [], 'abstained': True, 'reason': 'The named context does not establish the requested conclusion.'}


class ScopedContextTests(unittest.TestCase):
    def test_global_unrelated_search_is_unchanged(self):
        self.assertEqual(search('banana cryptocurrency valuation', corpus()), [])
        model = ContextModel()
        result = run('banana cryptocurrency valuation', corpus(), model=model)
        self.assertTrue(result['abstained'])
        self.assertEqual(model.received, [])

    def test_explicit_context_is_complete_and_marked_without_relevance_claim(self):
        model = ContextModel()
        result = run('banana cryptocurrency valuation', corpus(), model=model,
                     source_scope='The exact synthetic source, page 2.', explicit_context_ids=['c1'])
        self.assertTrue(result['abstained'])
        self.assertEqual(len(model.received), 1)
        self.assertEqual(model.received[0][0]['selection_role'], 'explicit_source_scope')
        self.assertEqual(result['evidence'][0]['text'], corpus()[0]['text'])
        self.assertIsNone(result['evidence'][0]['score'])
        self.assertEqual(result['evidence_selection']['lexical_hit_count'], 0)
        self.assertTrue(result['evidence_selection']['explicit_scope_complete'])

    def test_missing_scope_or_missing_passage_cannot_trigger_context(self):
        for scope, ids in [(None, ['c1']), ('Named scope', ['missing']), ('Named scope', ['c1', 'missing'])]:
            model = ContextModel()
            result = run('banana cryptocurrency valuation', corpus(), model=model,
                         source_scope=scope, explicit_context_ids=ids)
            self.assertEqual(model.received, [])
            self.assertEqual(result['evidence'], [])

    def test_held_filtered_or_duplicate_passages_do_not_enter_context(self):
        for changes in [{'permission_status':'review_required'}, {'status':'quarantined'}]:
            data = [dict(corpus()[0], **changes)]
            self.assertEqual(explicit_scope_context(data, ['c1']), [])
        self.assertEqual(explicit_scope_context(corpus(), ['c1'], source_ids=['other']), [])
        self.assertEqual(explicit_scope_context(corpus() * 2, ['c1']), [])

    def test_budget_checks_refuse_entire_scope_instead_of_partial_selection(self):
        data = [dict(corpus()[0], text='x' * MAX_CONTEXT_CHARS)]
        model = ContextModel()
        result = run('banana cryptocurrency valuation', data, model=model,
                     source_scope='Exact source', explicit_context_ids=['c1'])
        self.assertEqual(result['evidence'], [])
        self.assertEqual(model.received, [])
        many = [dict(corpus()[0], chunk_id='c'+str(i)) for i in range(7)]
        self.assertEqual(explicit_scope_context(many, [c['chunk_id'] for c in many]), [])

    def test_baseline_receives_no_context_and_invalid_ids_reject(self):
        model = ContextModel()
        run('banana', corpus(), model=model, system='baseline', source_scope='Named scope', explicit_context_ids=['c1'])
        self.assertEqual(model.received, [[]])
        for invalid in ['c1', ['c1','c1'], [None]]:
            with self.assertRaises(ValueError):
                run('banana', corpus(), explicit_context_ids=invalid)

    def test_verbatim_guard_preserves_punctuation_and_contiguous_spans(self):
        text = 'The value is called the LOI . The experiment concerns liquid droplets.'
        chunk = dict(corpus()[0], text=text)
        review = {'verdict':'supported','reason':'Synthetic only.','uncertainty':'Source scope only.',
                  'evidence_checks':[{'source_id':chunk['source_id'],'chunk_id':chunk['chunk_id'],
                                      'quote':'The value is called the LOI .','relation':'supports'}]}
        self.assertEqual(validate_review(review, [chunk])['verdict'], 'supported')
        for quote in ['The value is called the LOI.', 'The value ... concerns liquid droplets.']:
            invalid = deepcopy(review);invalid['evidence_checks'][0]['quote'] = quote
            with self.assertRaisesRegex(ValueError, 'does not match'):
                validate_review(invalid, [chunk])
        self.assertIn('contiguous substring', verbatim_quote_guidance())
        self.assertIn('insert ellipses', verbatim_quote_guidance())


if __name__ == '__main__':
    unittest.main()
