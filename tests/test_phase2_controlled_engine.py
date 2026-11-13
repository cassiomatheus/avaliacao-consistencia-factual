from _support import ROOT
import json
import tempfile
import unittest
from pathlib import Path

from factual_eval.fase2_injecao.controlled.create_demo import create_demo
from factual_eval.fase2_injecao.controlled.engine import (eligible_reference, generate_for_reference, validate_pair,
                        numeric_changes,predicate_changes,coreference_changes,stable_random)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        create_demo(self.tmp.name)
        p=Path(self.tmp.name)
        self.ref=[json.loads(x) for x in (p/"reference_claims_demo.jsonl").read_text().splitlines()]
        self.src=json.loads((p/"source_demo.jsonl").read_text())
    def tearDown(self): self.tmp.cleanup()

    def test_claim_eligibility(self):
        for r in self.ref: self.assertTrue(eligible_reference(r)[0])
    def test_reject_sentence_only(self):
        r={"schema_version":"phase2_candidate_v1","summary_sentence_en":"The agency funded 150 schools.","review_status":"completed"}
        self.assertFalse(eligible_reference(r)[0])
    def test_reject_unsufficient(self):
        r=dict(self.ref[0]);r["known_sufficient_evidence_sets"]=[]
        self.assertFalse(eligible_reference(r)[0])
    def test_num_and_negation_produce_single_edit(self):
        for ref in self.ref:
            out,errors=generate_for_reference(ref,self.src,strategies=["numeric","negation"],max_per_claim=8)
            self.assertTrue(out,errors)
            for row in out:
                self.assertEqual([],validate_pair(row))
                self.assertFalse(row["gold_eligible"])
                self.assertEqual("RULE_CHECKED_PROVISIONAL",row["validation_status"])
                self.assertNotIn("[ERROR_",row["modified_summary_en"])
                self.assertNotEqual(row["original_summary_en"],row["modified_summary_en"])
    def test_numeric_evidence_required(self):
        self.assertFalse(numeric_changes("The agency funded 150 schools.","The agency funded 150 schools.","It mentioned 200 schools."))
    def test_past_year_skip(self):
        self.assertFalse(numeric_changes("In 2023, projects started.","In 2023, projects started.","Projects started in 2023."))
    def test_output_determinism(self):
        a,_=generate_for_reference(self.ref[0],self.src,seed=33,max_per_claim=10)
        b,_=generate_for_reference(self.ref[0],self.src,seed=33,max_per_claim=10)
        self.assertEqual(a,b)
    def test_wrong_document_rejected(self):
        s=dict(self.src);s["doc_id"]="other"
        out,why=generate_for_reference(self.ref[0],s)
        self.assertFalse(out);self.assertIn("document_id_mismatch",why)
    def test_wrong_evidence_offsets_rejected(self):
        r=json.loads(json.dumps(self.ref[0]));r["evidences"][0]["source_span"]["start_char"]=2
        out,why=generate_for_reference(r,self.src)
        self.assertFalse(out);self.assertTrue(any("evidence_text_mismatch" in x for x in why))
    def test_summary_with_double_sentence_rejected(self):
        s=dict(self.src);s["summary"]=self.src["summary"]+" "+self.src["summary"]
        out,why=generate_for_reference(self.ref[0],s)
        self.assertIn("sentence_not_unique_in_full_summary",why)
    def test_ambiguous_verb_not_in_claim_skipped(self):
        self.assertEqual([],predicate_changes("She funded 150 schools.","150 schools were supported."))
    def test_pronoun_provisional(self):
        x=coreference_changes("He funded 150 schools.","He funded 150 schools.")
        self.assertEqual(1,len(x));self.assertIn("antecedente não foi verificado",x[0].caveats)
    def test_rule_cannot_promote_gold(self):
        out,_=generate_for_reference(self.ref[0],self.src,max_per_claim=10)
        row=out[0];row["gold_eligible"]=True
        self.assertIn("unjustified_gold_status",validate_pair(row))
    def test_other_sentence_preserved(self):
        s=dict(self.src);s["summary"]="Introductory sentence. "+self.src["summary"]+" Last sentence."
        out,why=generate_for_reference(self.ref[0],s)
        self.assertTrue(out,why)
        self.assertTrue(out[0]["modified_summary_en"].startswith("Introductory sentence. "))
        self.assertTrue(out[0]["modified_summary_en"].endswith(" Last sentence."))

if __name__ == '__main__': unittest.main()

class SentenceCandidateTests(unittest.TestCase):
    def test_sentence_only_can_generate_but_not_gold(self):
        from factual_eval.fase2_injecao.controlled.engine import generate_for_sentence_candidate
        report="The education budget received $20 million in 2023."
        sentence="In 2023, the agency allocated $20 million to education."
        candidate={"reference_granularity":"SENTENCE_LEVEL", "claim_level_sufficiency":"NOT_ASSESSED",
                   "doc_id":"d","summary_sentence_id":"s","summary_sentence_en":sentence,
                   "supporting_passages_reviewed":[{"evidence_id":"E1","text_en":report}]}
        pairs,err=generate_for_sentence_candidate(candidate,{"doc_id":"d","report":report,"summary":sentence})
        self.assertTrue(pairs,err)
        for p in pairs:
            self.assertFalse(p['gold_eligible'])
            self.assertEqual([],validate_pair(p))
