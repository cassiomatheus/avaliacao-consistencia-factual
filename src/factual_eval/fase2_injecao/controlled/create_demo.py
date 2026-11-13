"""Synthetic fixtures for integration testing; NOT real GovReport observations."""
from pathlib import Path
import json, hashlib


def create_demo(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    source = {
        "doc_id":"demo_doc_001",
        "report":"The education budget received $20 million in 2023. Funding was provided to 150 schools in 2023. The Department of Health received $10 million in 2023.",
        "summary":"In 2023, the agency allocated $20 million to education and funded 150 schools."
    }
    ev_texts=["The education budget received $20 million in 2023.","Funding was provided to 150 schools in 2023."]
    claims=["The agency allocated $20 million to education in 2023.","The agency funded 150 schools in 2023."]
    refs=[]
    for i,(e,claim) in enumerate(zip(ev_texts,claims),1):
        p=source["report"].find(e)
        refs.append({
            "schema_version":"1.0", "doc_id":source["doc_id"],
            "source_document_sha256":hashlib.sha256(source["report"].encode()).hexdigest(),
            "summary_sentence_id":"demo_doc_001_sum_0", "summary_sentence_en":source["summary"],
            "sentence_coverage_reviewed":True,
            "reference_claim_id":f"demo_doc_001_sum_0_C0{i}",
            "claim_en":claim,"raw_model_claims":claims,"claim_origin":"MODEL_ACCEPTED",
            "claim_label":"SUPPORTED","reference_status":"VALIDATED",
            "reviewer_id":"SYNTHETIC_EXAMPLE", "reviewed_at":"2026-11-10T13:00:00-03:00",
            "extractor_config":{"model_id":"SYNTHETIC","revision":"v0"},
            "retrieval_config":{"mode":"hybrid","top_k":5},
            "evidences":[{"evidence_id":f"E0{i}","text_en":e,
                         "source_sentence_ids":[f"SRC_00{i}"],"origin":"RETRIEVED",
                         "source_span":{"start_char":p,"end_char":p+len(e)}}],
            "known_sufficient_evidence_sets":[{"set_id":f"SET_0{i}","evidence_ids":[f"E0{i}"],
                                                "relation":"SUPPORTED","sufficiency_validated":True}]
        })
    (root/"source_demo.jsonl").write_text(json.dumps(source,ensure_ascii=False)+"\n",encoding="utf-8")
    (root/"reference_claims_demo.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in refs)+"\n",encoding="utf-8")


if __name__=="__main__":
    create_demo(Path(__file__).resolve().parents[1]/"examples")
