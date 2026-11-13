"""Critical integrated-review contracts; synthetic examples do not establish model quality."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from _support import ROOT
from factual_eval.schemas import document_id
from factual_eval.fase1_referencia.workspace import (PROTOCOL, catalog, fingerprint, reference_record,
    validate_extension, blockers, freeze_workspace, verify_snapshot, progress)
from factual_eval.fase1_referencia.review_server import ReviewStore, ConflictError
from factual_eval.fase2_injecao.controlled.engine import generate_for_reference
from factual_eval.fase2_injecao.approved import materialize
from factual_eval.avaliacao_automatica.alignment import align,align_many,evaluate_aligner
from factual_eval.avaliacao_automatica.evidence import evidence_comparison
from factual_eval.avaliacao_automatica.metrics import classification,cluster_bootstrap,validate_split


def fixture():
    report=summary='The agency funded 20 schools.'
    did=document_id(0,report);cid=did+':original:C00001';sid=did+':SUMMARY:S00001';eid=did+':S00001'
    d={'doc_id':did,'source_sha256':sha256(report.encode()).hexdigest(),
       'sentences':[{'sentence_id':eid,'text':report,'char_start':0,'char_end':len(report),'sentence_index':0}],
       'summary_sentences':[{'sentence_id':sid,'text':summary,'char_start':0,'char_end':len(summary),'sentence_index':0}]}
    data={'manifest':{'dataset_id':'SYNTHETIC_TEST_FIXTURE','top_k':5},'documents':[d],
        'claims':[{'doc_id':did,'claim_id':cid,'variant':'original','claim_original':summary,'claim_text':summary,
                   'origin_sentence':summary,'integrated_sentence_id':sid}], 'candidates':[], 'selection':[],
        'integrated_sources':{did:{'doc_id':did,'source_index':0,'report':report,'summary':summary}}}
    review={'schema_version':1,'dataset_id':'SYNTHETIC_TEST_FIXTURE','reviewer':'Synthetic test author (not research annotation)',
        'claims':{cid:{'claim_valid':'SIM','review_status':'FINALIZADO','full_document_checked':True,
                       'search_complete':True,'factual_label':'SUPPORTED','gold_evidence_sets':[[eid]]}},
        'integrated':{'protocol_version':PROTOCOL,'claims':{cid:{'reference_claim_id':cid,'doc_id':did,
            'sentence_id':sid,'raw_extracted_claim':summary,'validated_claim':summary,'claim_review_status':'APPROVED'}},
            'sentences':{sid:{'coverage_reviewed':True,'selected':True}},'perturbations':{}}}
    return data,review,cid,sid,eid


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data,self.review,self.cid,self.sid,self.eid=fixture()

    def pair(self):
        ref=reference_record(self.data,self.review,catalog(self.data,self.review)[self.cid])
        pairs,reasons=generate_for_reference(ref,self.data['integrated_sources'][ref['doc_id']],strategies=['numeric'])
        self.assertFalse(reasons)
        p=pairs[0];p['reference_fingerprint']=fingerprint(ref)
        p['human_review']={'status':'APPROVED','expected_relation':'CONTRADICTED',
            'evidence_relation_confirmed':True,'reviewed_by':'Synthetic test author'}
        return p

    def test_correct_add_reject_and_preserve_extractor(self):
        c=self.review['integrated']['claims'][self.cid]
        c.update(validated_claim='The agency provided funding for 20 schools.',claim_review_status='CORRECTED')
        ref=reference_record(self.data,self.review,c)
        self.assertEqual(ref['raw_extracted_claim'],'The agency funded 20 schools.')
        did=c['doc_id'];added=did+':Htest'
        self.review['integrated']['claims'][added]={**c,'reference_claim_id':added,'raw_extracted_claim':None,'claim_review_status':'ADDED'}
        self.review['claims'][added]=copy.deepcopy(self.review['claims'][self.cid])
        validate_extension(self.data,self.review)
        self.assertEqual(len(catalog(self.data,self.review)),2)
        c['raw_extracted_claim']='Changed raw output'
        with self.assertRaisesRegex(ValueError,'Raw extractor'):validate_extension(self.data,self.review)

    def test_incomplete_inconclusive_and_unreviewed_coverage_block_freeze(self):
        draft=copy.deepcopy(self.review);draft['draft_sets']={self.cid:[self.eid]}
        self.assertTrue(blockers(self.data,draft)[0])
        for field,value in [('full_document_checked',False),('factual_label','INCONCLUSIVE'),('gold_evidence_sets',[])]:
            review=copy.deepcopy(self.review);review['claims'][self.cid][field]=value
            with self.subTest(field=field):
                self.assertTrue(blockers(self.data,review)[0])
                with self.assertRaises(ValueError):freeze_workspace(self.data,review,self.root/field)
        self.review['integrated']['sentences'][self.sid]['coverage_reviewed']=False
        self.assertFalse(progress(self.data,self.review)['can_freeze'])

    def test_freeze_approved_materialize_and_hash_integrity(self):
        p=self.pair();self.review['integrated']['perturbations'][p['injection_id']]=p
        path=freeze_workspace(self.data,self.review,self.root/'snapshot')
        approved=json.loads((path/'approved_perturbations.jsonl').read_text())
        self.assertTrue(approved['expected_label_is_validated'])
        self.assertEqual(approved['validation_provenance'],'HUMAN_PREAPPROVED_EDIT')
        cases=materialize(path,self.root/'cases')
        self.assertEqual(len(cases),2)
        text=(self.root/'cases'/cases[1]['input_csv']).read_text()
        self.assertNotIn('CONTRADICTED',text);self.assertNotIn('[ERROR_',text)
        with self.assertRaises(FileExistsError):freeze_workspace(self.data,self.review,path)
        (path/'reference_claims.jsonl').write_text('tampered')
        with self.assertRaises(ValueError):verify_snapshot(path)

    def test_stale_approval_and_fake_validation_never_enter_snapshot(self):
        p=self.pair();self.review['integrated']['perturbations'][p['injection_id']]=p
        p['expected_label_is_validated']=True
        with self.assertRaises(ValueError):validate_extension(self.data,self.review)
        p['expected_label_is_validated']=False
        self.review['integrated']['claims'][self.cid]['validated_claim']='A different proposition.'
        self.assertTrue(any(x['reason']=='STALE_OR_OUT_OF_SCOPE_APPROVAL' for x in blockers(self.data,self.review)[0]))
        self.review['integrated']['perturbations']={'../escape':{**p,'injection_id':'../escape'}}
        with self.assertRaisesRegex(ValueError,'ID'):validate_extension(self.data,self.review)

    def test_missing_foreign_evidence_and_invalid_offsets(self):
        self.review['claims'][self.cid]['gold_evidence_sets']=[['FOREIGN']]
        with self.assertRaises(ValueError):reference_record(self.data,self.review,catalog(self.data,self.review)[self.cid])
        self.review['claims'][self.cid]['gold_evidence_sets']=[[self.eid]]
        self.data['documents'][0]['sentences'][0]['char_end']=1000
        with self.assertRaises(ValueError):reference_record(self.data,self.review,catalog(self.data,self.review)[self.cid])

    def test_atomic_resume_conflict_history_and_added_claim_storage(self):
        store=ReviewStore(self.root/'review.json',self.data)
        try:
            first=store.save(self.review,None)
            edited=copy.deepcopy(self.review);edited['reviewer']='Second test reviewer'
            store.save(edited,first['version'])
            with self.assertRaises(ConflictError):store.save(self.review,first['version'])
            self.assertEqual(len(list((self.root/'review.historico').glob('*.json'))),1)
        finally:store.close()
        reopened=ReviewStore(self.root/'review.json',self.data)
        try:self.assertEqual(reopened.read()['review'],edited)
        finally:reopened.close()

    def test_async_static_generation_preserves_decisions_and_persists_progress(self):
        from factual_eval.fase1_referencia.workspace_service import WorkspaceService
        store=ReviewStore(self.root/'review.json',self.data)
        try:
            first=store.save(self.review,None)
            service=WorkspaceService(store)
            request={'action':'generate','version':first['version'],'claim_id':self.cid,'strategies':['numeric']}
            task=service.submit(request);service.close()
            self.assertEqual(service.jobs[task['job_id']]['status'],'COMPLETE')
            saved=store.read()
            proposals=saved['review']['integrated']['perturbations']
            self.assertEqual(len(proposals),1)
            self.assertEqual(next(iter(proposals.values()))['human_review']['status'],'PENDING')
            with self.assertRaises(ConflictError):service.submit(request)
            restarted=WorkspaceService(store)
            try:self.assertEqual(restarted.state()['jobs'][0]['status'],'COMPLETE')
            finally:restarted.close()
        finally:store.close()

    def test_type_analysis_distinguishes_inapplicable_unavailable_and_safe_suggestions(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from factual_eval.fase2_injecao.applicability import analyze_and_suggest
        ref=reference_record(self.data,self.review,catalog(self.data,self.review)[self.cid])
        source=self.data['integrated_sources'][ref['doc_id']]
        class Doc(list):
            ents=[]
        with patch('factual_eval.fase2_injecao.applicability.generate_for_reference',return_value=([{'injection_id':'test'}],[])) as generate:
            pairs,types=analyze_and_suggest(ref,source,nlp=lambda text:Doc())
            self.assertEqual(types['entity']['status'],'NOT_APPLICABLE')
            self.assertEqual(types['coreference']['status'],'NOT_APPLICABLE')
            self.assertEqual(types['predicate']['status'],'SUGGESTED')
            self.assertEqual(generate.call_count,1)
            self.assertEqual(generate.call_args.kwargs['strategies'],['negation','antonym'])
            self.assertEqual(len(pairs),1)
        doc=Doc([SimpleNamespace(pos_='PRON',text='their',i=0)])
        doc.ents=[SimpleNamespace(label_='ORG',text='agency')]
        with patch('factual_eval.fase2_injecao.applicability.generate_for_reference',return_value=([],['no_candidate'])):
            pairs,types=analyze_and_suggest(ref,source,nlp=lambda text:doc)
            self.assertEqual(types['entity']['status'],'NO_SAFE_SUGGESTION')
            self.assertEqual(types['coreference']['status'],'UNAVAILABLE')

            self.assertEqual(pairs,[])
            _,types=analyze_and_suggest(ref,source,nlp=None)
            self.assertEqual(types['entity']['status'],'UNAVAILABLE')
            self.assertEqual(types['coreference']['status'],'UNAVAILABLE')

    def test_automatic_generation_persists_three_type_analysis_without_forcing_types(self):
        from unittest.mock import patch
        from factual_eval.fase1_referencia.workspace_service import WorkspaceService
        class Doc(list):
            ents=[]
        store=ReviewStore(self.root/'auto-review.json',self.data)
        try:
            first=store.save(self.review,None)
            service=WorkspaceService(store)
            with patch('spacy.load',return_value=lambda text:Doc()), patch(
                'factual_eval.fase2_injecao.controlled.claim_injections.CoreferenceResolver',side_effect=RuntimeError('Unavailable fixture')):
                task=service.submit({'action':'generate','version':first['version'],'claim_id':self.cid,'analyze_types':True})
                service.close()
            job=service.jobs[task['job_id']]
            self.assertEqual(job['status'],'COMPLETE',job.get('error'))
            self.assertEqual(job['result']['applicability']['entity']['status'],'NOT_APPLICABLE')
            self.assertEqual(job['result']['applicability']['predicate']['status'],'SUGGESTED')
            self.assertEqual(job['result']['applicability']['coreference']['status'],'NOT_APPLICABLE')
            saved=store.read()['review']['integrated']['perturbations'].values()
            self.assertTrue(all(p['error_category']=='predicate' and p['human_review']['status']=='PENDING' for p in saved))
        finally:store.close()

    def test_preapproved_relation_is_scored_but_provisional_expectation_is_not(self):
        from factual_eval.avaliacao_automatica.compare import compare
        ref=reference_record(self.data,self.review,catalog(self.data,self.review)[self.cid])
        p=self.pair();self.review['integrated']['perturbations'][p['injection_id']]=p
        path=freeze_workspace(self.data,self.review,self.root/'snapshot')
        approved=json.loads((path/'approved_perturbations.jsonl').read_text())
        prediction={'doc_id':ref['doc_id'],'tipo_resumo':p['error_category'],'claim_id':'prediction',
                    'claim':p['modified_claim_en'],'status_factual_nli':'SUPPORTED'}
        result=compare([ref],[prediction],[approved])
        self.assertEqual(result['records'][0]['nli_comparison'],'MISMATCH')
        self.assertEqual(result['summary']['nli_metrics']['evaluated'],1)
        result=compare([ref],[prediction],[p])
        self.assertEqual(result['summary']['nli_metrics']['evaluated'],0)


class EvaluationTests(unittest.TestCase):
    def test_nullable_parquet_source_anchors(self):
        import pandas as pd
        from factual_eval.schemas import carry_claim_ids
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inp=root/'input.parquet';out=root/'output.parquet'
            rows=[{'doc_idx':0,'tipo_resumo':'original','claim':text,'doc_id':'d','claim_id':str(i),'documento_fonte':'A. B.'} for i,text in enumerate(['A.','B.'])]
            pd.DataFrame(rows).to_parquet(inp,index=False)
            pd.DataFrame([{**r,'status_factual_nli':'SUPPORTED','source_passage':'A.','support_score':.9,
                           'contradiction_score':.01,'source_sentence_index':index} for r,index in zip(rows,[0,None])]).to_parquet(out,index=False)
            carry_claim_ids(inp,out)
            result=pd.read_parquet(out).to_dict('records')
            self.assertEqual(result[0]['source_sentence_id'],'d:S00001')
            self.assertIsNone(result[1]['source_sentence_id'])

    def test_known_alignment_cases_and_abstention(self):
        scorer=lambda target,texts:[(.99,.99,.99) for t in texts]
        self.assertEqual(align('Agency funded 20 schools.',[{'claim_id':'p','claim':'Agency provided funding for 20 schools.'}],scorer)['status'],'MATCHED')
        self.assertNotEqual(align('Agency funded 20 schools.',[{'claim_id':'p','claim':'Agency funded 21 schools.'}],scorer)['status'],'MATCHED')
        self.assertEqual(align('A.',[{'claim_id':'p','claim':'A.'},{'claim_id':'q','claim':'A.'}])['status'],'AMBIGUOUS')
        self.assertEqual(align('A. B.',[{'claim_id':'p','claim':'A.'}])['status'],'PARTIAL_MATCH')
        self.assertEqual(align('A. B.',[{'claim_id':'p','claim':'A.'},{'claim_id':'q','claim':'B.'}])['claim_ids'],['p','q'])
        self.assertEqual(align('A.',[],extraction_complete=True)['status'],'OMITTED')
        summary=evaluate_aligner([{'case_id':'exact','target':'A.','candidates':[{'claim_id':'p','claim':'A.'}],
                                   'expected_status':'MATCHED','expected_claim_ids':['p']}])
        self.assertEqual(summary['coverage'],1);self.assertEqual(summary['validated_matches'],1)
        shared=align_many({'r1':'A.','r2':'A.'},[{'claim_id':'p','claim':'A.'}])
        self.assertEqual([r['status'] for r in shared.values()],['AMBIGUOUS','AMBIGUOUS'])

    def test_multi_evidence_different_segmentation_and_alternative(self):
        source='First evidence. Second evidence.'
        ref={'source_document_sha256':sha256(source.encode()).hexdigest(),
            'evidences':[{'evidence_id':'a','text_en':'First evidence.','source_span':{'start_char':0,'end_char':15}},
                         {'evidence_id':'b','text_en':'Second evidence.','source_span':{'start_char':16,'end_char':32}}],
            'known_sufficient_evidence_sets':[{'set_id':'s','evidence_ids':['a','b'],'sufficiency_validated':True}]}
        row={'documento_fonte':source,'top_sentences':[],'top_paragraphs':[{'text':source,'start_char':0,'end_char':len(source),'window_id':'DIFFERENT_ANCHOR'}]}
        self.assertTrue(evidence_comparison(ref,[row])['success_at_k'])
        combined={**ref,'evidences':[{'evidence_id':'whole','text_en':source,'source_span':{'start_char':0,'end_char':len(source)}}],
                  'known_sufficient_evidence_sets':[{'set_id':'joint','evidence_ids':['whole'],'sufficiency_validated':True}]}
        split={'documento_fonte':source,'top_sentences':[{'text':'First evidence.','start_char':0,'end_char':15},
              {'text':'Second evidence.','start_char':16,'end_char':len(source)}],'top_paragraphs':[]}
        self.assertTrue(evidence_comparison(combined,[split])['success_at_k'])
        row['top_paragraphs']=[{'text':'Another unannotated passage.'}]
        self.assertEqual(evidence_comparison(ref,[row])['status'],'ALTERNATIVE_EVIDENCE_UNVERIFIED')
        row['top_paragraphs']=[{'text':'First evidence.'}]
        self.assertFalse(evidence_comparison(ref,[row])['success_at_k'])
        row['top_paragraphs']=[{'text':'First evidence.','start_char':0,'end_char':1}]
        self.assertIsNone(evidence_comparison(ref,[row])['success_at_k'])

    def test_metric_denominators_unvalidated_labels_and_document_split(self):
        rs=[{'doc_id':'d','expected_nli':'CONTRADICTED','predicted_nli':'SUPPORTED','evaluable':True},
            {'doc_id':'d','expected_nli':'CONTRADICTED','predicted_nli':'SUPPORTED','evaluable':False}]
        result=classification(rs)
        self.assertEqual(result['evaluated'],1);self.assertEqual(result['abstentions'],1)
        self.assertEqual(result['per_class']['CONTRADICTED']['recall'],0)
        self.assertEqual(cluster_bootstrap(rs)['status'],'NOT_EVALUABLE')
        with self.assertRaisesRegex(ValueError,'leakage'):validate_split([{'doc_id':'d','split':'test'},{'doc_id':'d','split':'development'}])
        with self.assertRaisesRegex(ValueError,'leakage'):validate_split([{'doc_id':'d','source_hash':'same','split':'test'},{'doc_id':'alias','source_hash':'same','split':'development'}])


if __name__=='__main__':unittest.main()
