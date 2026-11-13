import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.data.external_summaries import compose,prepare,main


class ExternalSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.source={'doc_id':'d','source_index':7,'report':'The agency approved and funded projects.','summary':'😀 The agency approved 10 projects and funded 20 schools.'}
        text=self.source['summary'];rows=[]
        for id,claim,old,new,category in [('p1','c1','approved','did not approve','predicate'),('p2','c2','funded','did not fund','predicate'),('e1','c1','10','11','entity')]:
            a=text.index(old);b=a+len(old)
            rows.append({'injection_id':id,'claim_id':claim,'document_id':'d','error_category':category,'original_summary_en':text,
                         'modified_summary_en':text[:a]+new+text[b:],'edit':{'start_char':a,'end_char':b,'original':old,'replacement':new},
                         'generator':{'source_sha256':sha256(self.source['report'].encode()).hexdigest()}})
        self.rows=rows;self.proposals=self.root/'proposals.jsonl';self.proposals.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        self.sources=self.root/'sources.jsonl';self.sources.write_text(json.dumps(self.source)+'\n')
        self.selection=self.root/'selection.json';self.write_selection(['p1','p2','e1'])

    def write_selection(self,ids):
        self.selection.write_text(json.dumps({'schema_version':'summary_selection_v1','dataset_id':sha256(self.proposals.read_bytes()).hexdigest(),'document_id':'d','selected_injection_ids':ids}))

    def test_csv_contract_and_separate_metadata_no_marker_or_gold(self):
        row,manifest=prepare(self.selection,self.proposals,self.sources)
        self.assertEqual(row['resumo_original'],self.source['summary'])
        self.assertEqual(row['resumo_predicado'],'😀 The agency did not approve 10 projects and did not fund 20 schools.')
        self.assertEqual(row['resumo_entity'],'😀 The agency approved 11 projects and funded 20 schools.')
        self.assertEqual(row['resumo_corref'],'');self.assertEqual(row['source_index'],7)
        self.assertFalse(manifest['is_gold']);self.assertNotIn('edits',row)
        self.assertTrue(all('[ERROR_' not in v for v in row.values() if isinstance(v,str)))
        self.assertEqual({m['category']:m['inconsistency_count'] for m in manifest['variants']},{'predicate':2,'entity':1})

    def test_modified_proposals_hash_rejected(self):
        self.proposals.write_text(self.proposals.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'SHA-256'):prepare(self.selection,self.proposals,self.sources)

    def test_unknown_duplicate_and_empty_selection_rejected(self):
        for ids in [['unknown'],['p1','p1'],[]]:
            self.write_selection(ids)
            with self.assertRaises(ValueError):prepare(self.selection,self.proposals,self.sources)

    def test_same_claim_or_overlapping_edits_rejected(self):
        repeated={**self.rows[1],'claim_id':'c1'}
        with self.assertRaisesRegex(ValueError,'one edit per claim'):compose([self.rows[0],repeated],self.source,'predicate')
        overlap={**self.rows[0],'injection_id':'o','claim_id':'c3'}
        with self.assertRaisesRegex(ValueError,'Overlapping'):compose([self.rows[0],overlap],self.source,'predicate')

    def test_source_snapshot_change_rejected(self):
        changed={**self.source,'report':self.source['report']+' Additional text.'}
        with self.assertRaisesRegex(ValueError,'report SHA-256'):compose([self.rows[0]],changed,'predicate')
        changed={**self.source,'summary':self.source['summary']+' Additional text.'}
        with self.assertRaisesRegex(ValueError,'summary'):compose([self.rows[0]],changed,'predicate')

    def test_output_is_exclusive_and_unicode_csv_roundtrips(self):
        dest=self.root/'input.csv';args=['--selection',str(self.selection),'--proposals',str(self.proposals),'--source',str(self.sources),'--output',str(dest)]
        main(args);original=dest.read_bytes()
        with dest.open(newline='') as f:row=next(csv.DictReader(f))
        self.assertTrue(row['resumo_original'].startswith('😀'))
        with self.assertRaises(SystemExit):main(args)
        self.assertEqual(dest.read_bytes(),original)
