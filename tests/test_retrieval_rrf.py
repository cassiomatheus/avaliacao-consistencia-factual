"""Rank-fusion contracts without downloading models or running neural inference."""
from _support import ROOT
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

from factual_eval.config import load_config
from factual_eval.fase3_pipeline.retrieval import pipeline as retrieval


class RRFTests(unittest.TestCase):
    def test_formula_one_based_ranks_and_missing_candidates(self):
        ranks=[{0:1,1:2},{1:1,2:2}]
        self.assertAlmostEqual(retrieval.reciprocal_rank_score(ranks,1),1/62+1/61)
        self.assertAlmostEqual(retrieval.reciprocal_rank_score(ranks,0),1/61)
        self.assertAlmostEqual(retrieval.reciprocal_rank_score(ranks,2,10),1/12)
        self.assertEqual(retrieval.reciprocal_rank_score(ranks,3),0)
        self.assertEqual(retrieval.reciprocal_rank_score([],0),0)

    def test_candidate_order_uses_ranks_and_retains_all_channels(self):
        class Lexical:
            def __init__(self, scale=1):self.scale=scale
            def candidates(self,query,top_k):return [(1,100*self.scale),(2,self.scale)]
        passages=['irrelevant','claim','claim']
        with patch.object(retrieval,'semantic_candidates',return_value=([0,1],[.99,.1])) as dense:
            rows=retrieval.retrieve_candidates([('literal','claim'),('contextual',' CLAIM ')],
                passages,{},Lexical(),[set()]*3,set())
            self.assertEqual(dense.call_count,1)  # Identical queries do not get extra votes.
            scaled=retrieval.retrieve_candidates([('literal','claim')],passages,{},Lexical(1000),[set()]*3,set())
        self.assertEqual([r['idx'] for r in rows],[1,0,2])
        self.assertEqual([r['rrf_score'] for r in rows],[r['rrf_score'] for r in scaled])
        by_id={r['idx']:r for r in rows}
        self.assertGreater(by_id[0]['retrieval_score'],by_id[1]['retrieval_score'])
        self.assertGreater(by_id[1]['rrf_score'],by_id[0]['rrf_score'])
        self.assertEqual(by_id[1]['rrf_ranks'],{'semantic:literal':2,'lexical:literal':1})
        self.assertEqual(by_id[2]['retrieval_sources'],['lexical:literal'])
        self.assertTrue(all(r['fusion_method']=='rrf' and r['rrf_k']==60 for r in rows))

    def test_empty_channels_ties_and_configured_k(self):
        class Lexical:
            def candidates(self,query,top_k):return []
        with patch.object(retrieval,'semantic_candidates',return_value=([],[])):
            self.assertEqual(retrieval.retrieve_candidates([('literal','claim')],[],{},Lexical(),[],set()),[])
        with patch.object(retrieval,'semantic_candidates',side_effect=[([1],[.4]),([0],[.4])]),patch.object(retrieval,'RRF_K',10):
            rows=retrieval.retrieve_candidates([('literal','first'),('contextual','second')],['a','b'],{},Lexical(),[set()]*2,set())
        self.assertEqual([r['idx'] for r in rows],[0,1])
        self.assertTrue(all(r['rrf_score']==1/11 for r in rows))

    def test_cross_encoder_remains_primary_with_rrf_tie_break(self):
        class Cross:
            def predict(self,pairs,**kwargs):return np.array([1.,1.,2.])
        candidates=[{'idx':0,'rrf_score':.02},{'idx':1,'rrf_score':.03},{'idx':2,'rrf_score':.01}]
        rows=retrieval.rerank_cross('claim',candidates,['a','b','c'],Cross())
        self.assertEqual([r['idx'] for r in rows],[2,1,0])

    def test_rrf_k_configuration_rejects_invalid_values(self):
        self.assertEqual(load_config()['retrieval']['rrf_k'],60)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.yaml'
            for value in ('0','-1','true','1.5'):
                path.write_text('retrieval:\n  rrf_k: '+value+'\n')
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'rrf_k'):
                    load_config(path)
        for value in (0,-1,True,1.5):
            with self.assertRaises(ValueError):retrieval.reciprocal_rank_score([],0,value)


if __name__=='__main__':unittest.main()
