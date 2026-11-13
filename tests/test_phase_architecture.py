from _support import ROOT
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from factual_eval.fase1_referencia.freeze import freeze
from factual_eval.schemas import document_id
from factual_eval.avaliacao_automatica.compare import compare
from factual_eval.fase2_injecao.controlled.engine import generate_for_reference,validate_pair


class PhaseArchitectureTests(unittest.TestCase):
    def reference(self):
        report='The agency funded 20 schools.';summary='The agency funded 20 schools.'
        from hashlib import sha256
        return {'schema_version':'1.0','reference_claim_id':'C1','claim_id':'C1','doc_id':'d',
                'reference_status':'VALIDATED','claim_validation_status':'HUMAN_VALIDATED','claim_label':'SUPPORTED',
                'claim_en':summary,'summary_sentence_en':summary,'summary_sentence_id':'S1',
                'source_document_sha256':sha256(report.encode()).hexdigest(),
                'known_sufficient_evidence_sets':[{'evidence_ids':['E1'],'relation':'SUPPORTED','sufficiency_validated':True}],
                'evidences':[{'evidence_id':'E1','text_en':report,'source_span':{'start_char':0,'end_char':len(report)}}]}

    def test_old_imports_share_canonical_model_state(self):
        for old,new in [('reference.preparation','fase1_referencia.preparation'),('claims.extraction','fase3_pipeline.claims.extraction'),
                        ('data.external_summaries','fase2_injecao.external_summaries'),('nli.evaluation','fase3_pipeline.nli.evaluation')]:
            self.assertIs(importlib.import_module('factual_eval.'+old),importlib.import_module('factual_eval.'+new))

    def test_phase3_never_starts_generator_or_taxonomy(self):
        from factual_eval.fase3_pipeline.runner import main
        with self.assertRaises(SystemExit):main(['--from-stage','generate'])
        with self.assertRaises(SystemExit):main(['--until-stage','taxonomy'])
        with patch('factual_eval.fase3_pipeline.runner.legacy_main') as run:
            main(['--input','modified.csv'])
            self.assertEqual(run.call_args.args[0],'pipeline')
            self.assertIn('nli',run.call_args.args[1])

    def test_controlled_generation_updates_claim_and_sentence_independently(self):
        r=self.reference();source={'doc_id':'d','report':r['claim_en'],'summary':r['claim_en']}
        pairs,errors=generate_for_reference(r,source,strategies=['numeric','negation'],one_per_type=True,max_per_claim=3)
        self.assertFalse(errors);self.assertEqual({'entity','predicate'},{p['error_category'] for p in pairs})
        for pair in pairs:
            self.assertEqual([],validate_pair(pair));self.assertEqual(pair['reference_claim_id'],'C1')
            self.assertNotEqual(pair['modified_claim_en'],pair['original_claim_en'])
            self.assertFalse(pair['expected_label_is_validated']);self.assertFalse(pair['gold_eligible'])
            self.assertEqual(pair['original_summary_en'],source['summary'])

    def test_sentence_links_are_not_promoted_to_validated_claims(self):
        r=self.reference();r.pop('claim_validation_status')
        pairs,errors=generate_for_reference(r,{'doc_id':'d','report':r['claim_en'],'summary':r['claim_en']},strategies=['numeric'])
        self.assertFalse(pairs);self.assertIn('claim_validation_required',errors)

    def test_exact_alignment_evidence_sets_and_hypotheses_separated(self):
        ref=self.reference();pred={'claim_id':'P1','doc_id':'d','tipo_resumo':'predicate','claim':'The agency did not fund 20 schools.','status_factual_nli':'CONTRADICTED'}
        injection={'document_id':'d','reference_claim_id':'C1','error_category':'predicate','modified_claim_en':pred['claim'],'expected_relation':'CONTRADICTED'}
        result=compare([ref],[pred],[injection],[{'claim_id':'P1','top_sentences':[{'text':ref['claim_en']}],'top_paragraphs':[]}])['records'][0]
        self.assertEqual(result['alignment_status'],'ALIGNED');self.assertTrue(result['known_sufficient_set_recovered'])
        self.assertEqual(result['nli_comparison'],'UNSCORABLE_EXPECTED_LABEL_UNVALIDATED')
        original={**pred,'tipo_resumo':'original','claim':ref['claim_en'],'status_factual_nli':'SUPPORTED'}
        self.assertEqual(compare([ref],[original])['records'][0]['nli_comparison'],'MATCH')

    def test_ambiguous_and_unmatched_claims_abstain(self):
        ref=self.reference();p={'claim_id':'P','doc_id':'d','tipo_resumo':'original','claim':ref['claim_en'],'status_factual_nli':'SUPPORTED'}
        result=compare([ref],[p,{**p,'claim_id':'P2'}])
        self.assertEqual(result['records'][0]['alignment_status'],'AMBIGUOUS')
        result=compare([ref],[{**p,'claim':'A paraphrased claim.'}])
        self.assertEqual(result['records'][0]['alignment_status'],'UNMATCHED')

    def test_alignment_preserves_entity_case(self):
        ref=self.reference();ref['claim_en']='US funded 20 schools.'
        prediction={'claim_id':'P','doc_id':'d','tipo_resumo':'original','claim':'us funded 20 schools.','status_factual_nli':'SUPPORTED'}
        self.assertEqual(compare([ref],[prediction])['records'][0]['alignment_status'],'UNMATCHED')

    def test_freeze_requires_original_only_and_exact_evidence_spans(self):
        from hashlib import sha256
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source={'source_index':0,'doc_id':'external','report':'Agency funded 20 schools.','summary':'Agency funded 20 schools.'}
            did=document_id(0,source['report']);frame=root/'frame';frame.mkdir()
            def write(p,rs):p.write_text(''.join(json.dumps(r)+'\n' for r in rs))
            write(root/'source.jsonl',[source]);write(frame/'documentos.jsonl',[{'doc_id':did,'source_sha256':sha256(source['report'].encode()).hexdigest()}])
            write(frame/'claims.jsonl',[{'claim_id':'C','doc_id':did,'variant':'original','origin_sentence':source['summary']}])
            write(frame/'sentencas.jsonl',[{'doc_id':did,'sentence_id':'E','text':source['report'],'char_start':0,'char_end':len(source['report'])}])
            gold={'claim_id':'C','doc_id':did,'variant':'original','claim_original':source['summary'],'factual_label':'SUPPORTED','full_document_checked':True,'search_complete':True,'gold_evidence_sets':[['E']],'dataset_id':'test'}
            write(root/'gold.jsonl',[gold]);path=freeze(root/'gold.jsonl',frame,root/'source.jsonl',root/'frozen')
            exported=json.loads(path.read_text());self.assertEqual(exported['claim_validation_status'],'HUMAN_VALIDATED')
            self.assertFalse(exported['sentence_coverage_reviewed'])
            self.assertEqual(exported['evidences'][0]['source_span']['end_char'],len(source['report']))
            gold['variant']='predicate';write(root/'gold.jsonl',[gold])
            with self.assertRaisesRegex(ValueError,'original'):freeze(root/'gold.jsonl',frame,root/'source.jsonl',root/'bad')
