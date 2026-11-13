"""Four intervention conditions, using the existing scientific stage runners."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from factual_eval.fase1_referencia.workspace import verify_snapshot,read_rows,write_rows
from factual_eval.fase2_injecao.approved import materialize
from .alignment import align_many,ModelEquivalence,PROTOCOL
from .evidence import evidence_comparison
from .metrics import validate_split
from .reporting import report


def reference_passages(reference):
    evidence={r['evidence_id']:r for r in reference['evidences']}
    return [{'text':' '.join(evidence[eid]['text_en'] for eid in g['evidence_ids']),
             'expanded_text':' '.join(evidence[eid]['text_en'] for eid in g['evidence_ids']),
             'reference_set_id':g.get('set_id'),'unit':'NONCONTIGUOUS_REFERENCE_SET',
             'retrieval_score':1.0,'cross_score':1.0,'sentence_index':-1}
            for g in reference['known_sufficient_evidence_sets'] if g.get('sufficiency_validated')]


def run_experiments(snapshot,output,device='auto',notify=lambda text:None,semantic=False):
    import pandas as pd
    from factual_eval.config import load_config,execution_environment
    from factual_eval.runs import Run
    from factual_eval.cli import execute_stage
    snapshot,output=Path(snapshot),Path(output)
    frozen=verify_snapshot(snapshot)
    references=read_rows(snapshot/'reference_claims.jsonl')
    sources={s['doc_id']:s for s in read_rows(snapshot/'sources.jsonl')}
    assignments=[{'doc_id':d,'source_hash':sha256(s['report'].encode()).hexdigest(),'split':s.get('experimental_split','test')} for d,s in sources.items()]
    validate_split(assignments)
    output.mkdir(parents=True,exist_ok=False)
    config=load_config();config['runtime']['device']=device
    execution_environment(config)
    (output/'config.resolved.json').write_text(json.dumps(config,indent=2))
    cases=materialize(snapshot,output/'cases')
    decisions=[];scorer=None
    if semantic:
        # Independent optional alignment model condition, recorded explicitly.
        scorer=ModelEquivalence(config,device)
    manifest={'schema_version':'factorial-e0-e3-v1','status':'running','snapshot_sha256':sha256((snapshot/'manifest.json').read_bytes()).hexdigest(),
              'reference_dataset_id':frozen['dataset_id'],
              'quality_claims_allowed':not frozen['dataset_id'].startswith('SYNTHETIC_TEST'),
              'conditions':{'E0':'extracted claims / retrieved evidence','E1':'extracted claims / reference evidence',
                            'E2':'reference target claims / retrieved evidence','E3':'reference target claims / reference evidence'},
              'splits':assignments,'alignment_protocol':PROTOCOL,'semantic_confirmation_enabled':semantic,
              'reference_quality_scores':1.0,'reference_evidence_unit':'noncontiguous sufficient set concatenated in reference order',
              'cases':len(cases),'approved_perturbations':frozen['approved_perturbations'],
              'perturbation_decisions':frozen.get('perturbation_decisions',{})}
    manifest_path=output/'manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2))
    try:
        for case in cases:
            cid=case['case_id'];notify(cid+': E0 extraction/retrieval/NLI')
            with Run(output/'runs',config,run_id=cid) as run:
                input_path=output/'cases'/case['input_csv']
                paths={}
                for stage in ('claims','retrieval','nli'):
                    before=input_path
                    input_path=run.stage(stage,before,lambda folder,s=stage,p=before:execute_stage(s,p,folder,config,start=0,num_docs=None,all_docs=True),parameters={'condition':'E0'})
                    paths[stage]=input_path
                predictions=pd.read_parquet(paths['nli']).to_dict('records')
                retrieved=pd.read_parquet(paths['retrieval']).to_dict('records')
                targets=[r for r in references if r['doc_id']==case['doc_id'] and (not case['injection'] or r['reference_claim_id']==case['injection']['reference_claim_id'])]
                aligned=align_many({r['reference_claim_id']:case['injection']['modified_claim_en'] if case['injection'] else r['claim_en'] for r in targets},predictions,scorer,extraction_complete=True)
                interventions=[];pending=[]
                for ref in targets:
                    injection=case['injection'];text=injection['modified_claim_en'] if injection else ref['claim_en']
                    expected=injection['expected_relation'] if injection else ref['claim_label']
                    alignment=aligned[ref['reference_claim_id']]
                    selected=[r for r in retrieved if r['claim_id'] in alignment['claim_ids']]
                    start=min((e.get('source_span',{}).get('start_char',0) for e in ref['evidences']),default=0)
                    relative=start/max(1,len(sources[case['doc_id']]['report']))
                    base={'case_id':cid,'doc_id':case['doc_id'],'reference_claim_id':ref['reference_claim_id'],
                          'error_type':injection['error_category'] if injection else 'CONTROL','is_control':injection is None,
                          'expected_nli':expected,'document_length':len(sources[case['doc_id']]['report']),
                          'evidence_count':min((len(s['evidence_ids']) for s in ref['known_sufficient_evidence_sets']),default=0),
                          'relative_evidence_position':relative,'position_bin':'beginning' if relative<1/3 else 'middle' if relative<2/3 else 'end',
                          'alignment_status':alignment['status'],'alignment_method':alignment['method']}
                    matched=[p for p in predictions if p['claim_id'] in alignment['claim_ids']]
                    label=matched[0]['status_factual_nli'] if alignment['status']=='MATCHED' and len(matched)==1 else None
                    evidence=evidence_comparison(ref,selected) if alignment['status']=='MATCHED' else {'success_at_k':None,'status':'NOT_EVALUABLE'}
                    decisions.append({**base,'condition':'E0','predicted_nli':label,'evaluable':label is not None,
                                      'success_at_k':evidence['success_at_k'],'evidence_status':evidence['status']})
                    # E1 needs a reliable unique alignment. One-to-many is retained but abstains here.
                    if alignment['status']=='MATCHED' and len(selected)==1 and reference_passages(ref):
                        record=deepcopy(selected[0]);record.update(claim_id=cid+':E1:'+ref['reference_claim_id'],
                            top_sentences=[],top_paragraphs=reference_passages(ref))
                        interventions.append(record);pending.append((record['claim_id'],{**base,'condition':'E1','success_at_k':None}))
                    else:
                        decisions.append({**base,'condition':'E1','predicted_nli':None,'evaluable':False,'success_at_k':None,
                                          'reason':'ALIGNMENT_OR_POSITIVE_REFERENCE_EVIDENCE_UNAVAILABLE'})
                    # E2 supplies only the reference target claim to the normal retriever.
                    source=sources[case['doc_id']]
                    target_folder=run.path/('target_'+sha256(ref['reference_claim_id'].encode()).hexdigest()[:12]);target_folder.mkdir()
                    target=target_folder/'claims.parquet'
                    pd.DataFrame([{'doc_idx':source['source_index'],'doc_id':case['doc_id'],'tipo_resumo':case['variant'],
                        'documento_fonte':source['report'],'resumo_texto':None,'claims':[{'claim_original':text,'texto':text,
                        'claim_id':cid+':E2:'+ref['reference_claim_id'],'sentence_index':0,'summary_sentence_id':ref['summary_sentence_id'],
                        'sentence_source':injection['modified_sentence_en'] if injection else ref['summary_sentence_en'],
                        'gabarito_injetado':'none'}]}]).to_parquet(target,index=False)
                    notify(cid+': E2 reference target retrieval')
                    retrieval_folder=target_folder/'retrieval';retrieval_folder.mkdir()
                    target_retrieval=execute_stage('retrieval',target,retrieval_folder,config)
                    target_rows=pd.read_parquet(target_retrieval).to_dict('records')
                    record=target_rows[0];interventions.append(record)
                    e2=evidence_comparison(ref,target_rows)
                    pending.append((record['claim_id'],{**base,'condition':'E2','alignment_status':'REFERENCE_TARGET',
                        'success_at_k':e2['success_at_k'],'evidence_status':e2['status']}))
                    if reference_passages(ref):
                        record=deepcopy(record);record.update(claim_id=cid+':E3:'+ref['reference_claim_id'],
                            top_sentences=[],top_paragraphs=reference_passages(ref))
                        interventions.append(record);pending.append((record['claim_id'],{**base,'condition':'E3',
                            'alignment_status':'REFERENCE_TARGET','success_at_k':None}))
                    else:
                        decisions.append({**base,'condition':'E3','predicted_nli':None,'evaluable':False,'success_at_k':None,
                                          'reason':'NO_POSITIVE_REFERENCE_EVIDENCE'})
                # All intervention conditions share one NLI batch per case, same model and thresholds.
                if interventions:
                    notify(cid+': E1/E2/E3 NLI')
                    combined=run.path/'interventions.parquet';pd.DataFrame(interventions).to_parquet(combined,index=False)
                    folder=run.path/'intervention_nli';folder.mkdir()
                    result=execute_stage('nli',combined,folder,config)
                    lookup={r['claim_id']:r for r in pd.read_parquet(result).to_dict('records')}
                    for pid,base in pending:
                        label=lookup[pid]['status_factual_nli']
                        decisions.append({**base,'predicted_nli':label,'evaluable':True})
        notify('Consolidating report')
        for decision in decisions:
            decision['diagnosis']=('ALIGNMENT_OR_EVIDENCE_INTERVENTION_ABSTENTION' if not decision['evaluable']
                else 'REFERENCE_AGREEMENT' if decision['predicted_nli']==decision['expected_nli']
                else 'NLI_DISAGREEMENT_WITH_KNOWN_SET_RECOVERED' if decision.get('success_at_k') is True
                else 'NLI_DISAGREEMENT_REFERENCE_EVIDENCE' if decision['condition'] in {'E1','E3'}
                else 'NLI_DISAGREEMENT_AND_KNOWN_SET_NOT_ESTABLISHED')
        write_rows(output/'decisions.jsonl',decisions)
        result=report(decisions,output/'report',metadata={**manifest,'status':'complete'})
        manifest.update(status='complete',report=str(output/'report'/'report.md'))
        manifest['files']={str(p.relative_to(output)):sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file() and p!=manifest_path}
        manifest_path.write_text(json.dumps(manifest,indent=2))
        return {'report':str(output/'report'/'report.md'),'documents':result['documents'],'cases':len(cases)}
    except BaseException as exc:
        manifest.update(status='failed',error=str(exc));manifest_path.write_text(json.dumps(manifest,indent=2));raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--device',default='auto',choices=['auto','cpu','cuda','cuda:0'])
    p.add_argument('--semantic-alignment',action='store_true',help='Optional embeddings + bidirectional NLI confirmation; report model-based provenance')
    a=p.parse_args();print(json.dumps(run_experiments(a.snapshot,a.output,a.device,semantic=a.semantic_alignment),indent=2))
