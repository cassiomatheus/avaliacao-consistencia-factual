"""Single-worker local jobs with persisted progress and optimistic review locking."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading
import uuid
from .workspace import (PROTOCOL, catalog, fingerprint, now, progress, reference_record,
                        freeze_workspace, write_rows)


class WorkspaceService:
    def __init__(self, store):
        self.store = store
        self.dataset = store.dataset
        self.root = store.path.parent/'integrated_runs'
        self.root.mkdir(exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='factual-workspace')
        self.lock = threading.Lock()
        self.jobs = {}
        self.models = {}
        for path in self.root.glob('*/job.json'):
            job = json.loads(path.read_text())
            if job['status'] in {'QUEUED', 'RUNNING'}:
                job.update(status='INTERRUPTED', error='Service restarted; outputs preserved. Start a new job.')
                store.atomic_write(path, json.dumps(job).encode())
            self.jobs[job['id']] = job

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)

    def current(self):
        data = self.store.read()
        review = data['review'] or {'schema_version':1,'dataset_id':self.store.dataset_id,'claims':{},'reviewer':''}
        return data, review

    def state(self):
        with self.store.mutex:
            data, review = self.current()
            result = {**data, 'progress':progress(self.dataset,review),'catalog':catalog(self.dataset,review)}
        with self.lock:
            result['jobs'] = deepcopy(list(self.jobs.values()))
        return result

    def submit(self, request):
        from .review_server import ConflictError
        action = request['action']
        if action not in {'generate','freeze','materialize','experiment'}:
            raise ValueError('Unknown action')
        with self.store.mutex:
            data, review = self.current()
            if data['version'] != request.get('version'):
                raise ConflictError('Save/reload the current review before starting a job')
            review = deepcopy(review)
        if action == 'generate':
            c = catalog(self.dataset,review).get(request.get('claim_id'))
            if c is None:
                raise ValueError('Unknown claim')
            ref = reference_record(self.dataset,review,c)
            if ref['claim_label'] != 'SUPPORTED':
                raise ValueError('Only supported original claims are eligible')
        if action in {'materialize','experiment'}:
            snapshot_job = self.jobs.get(request.get('snapshot_job'))
            if not snapshot_job or snapshot_job['action'] != 'freeze' or snapshot_job['status'] != 'COMPLETE':
                raise ValueError('Choose a completed frozen snapshot')
        strategies=request.get('strategies',['numeric','negation'])
        if not isinstance(strategies,list) or not strategies or set(strategies)-{'numeric','negation','antonym','entity','coreference'}:
            raise ValueError('Invalid static strategies')
        if type(request.get('seed',42)) is not int:
            raise ValueError('Invalid seed')
        jid=uuid.uuid4().hex
        folder=self.root/jid;folder.mkdir()
        job={'id':jid,'action':action,'status':'QUEUED','created_at':now(),'stage':'Waiting',
             'review_version':data['version']}
        with self.lock:
            self.jobs[jid]=job
            self.persist(job)
        self.executor.submit(self.run,jid,request,review,data['version'])
        return {'job_id':jid}

    def persist(self,job):
        self.store.atomic_write(self.root/job['id']/'job.json',json.dumps(job,ensure_ascii=False,indent=2).encode())

    def update(self,jid,**fields):
        with self.lock:
            self.jobs[jid].update(fields)
            self.persist(self.jobs[jid])

    def run(self,jid,request,review,version):
        folder=self.root/jid
        try:
            self.update(jid,status='RUNNING',stage=request['action'])
            action=request['action']
            if action=='generate':
                from factual_eval.fase2_injecao.controlled.engine import generate_for_reference
                ref=reference_record(self.dataset,review,catalog(self.dataset,review)[request['claim_id']])
                strategies=request.get('strategies',['numeric','negation'])
                automatic=request.get('analyze_types') is True
                errors={}
                if automatic:
                    strategies=['entity','negation','antonym','coreference']
                if {'entity','coreference'} & set(strategies) and 'nlp' not in self.models:
                    try:
                        import spacy
                        from factual_eval.config import load_config
                        self.models['nlp']=spacy.load(load_config()['injection']['spacy_model'])
                    except Exception as exc:
                        if not automatic:raise
                        errors['nlp']=str(exc)
                if 'coreference' in strategies and 'coreference' not in self.models:
                    try:
                        from factual_eval.fase2_injecao.controlled.claim_injections import CoreferenceResolver
                        # Integrated analysis uses installed artifacts; a missing model is reported separately.
                        self.models['coreference']=CoreferenceResolver(device='cpu',cache_root=self.root/'.coreference-cache',
                                                                        local_files_only=automatic)
                    except Exception as exc:
                        if not automatic:raise
                        errors['coreference']=str(exc)
                analysis=None
                if automatic:
                    from factual_eval.fase2_injecao.applicability import analyze_and_suggest
                    proposals,analysis=analyze_and_suggest(ref,self.dataset['integrated_sources'][ref['doc_id']],
                        seed=request.get('seed',42),nlp=self.models.get('nlp'),
                        coref_resolver=self.models.get('coreference'),model_errors=errors)
                    reasons=[]
                else:
                    proposals,reasons=generate_for_reference(ref,self.dataset['integrated_sources'][ref['doc_id']],
                        seed=request.get('seed',42),strategies=strategies,nlp=self.models.get('nlp'),
                        coref_resolver=self.models.get('coreference'),max_per_claim=6)
                for p in proposals:
                    p.update(reference_fingerprint=fingerprint(ref),created_at=now(),validation_provenance='PROVISIONAL',human_review={'status':'PENDING'})
                    p['modified_edit_span']={'start_char':p['edit']['start_char'],'end_char':p['edit']['start_char']+len(p['edit']['replacement'])}
                write_rows(folder/'proposals.jsonl',proposals)
                review.setdefault('integrated',{'protocol_version':PROTOCOL}).setdefault('perturbations',{})
                for p in proposals:
                    review['integrated']['perturbations'].setdefault(p['injection_id'],p)
                # A concurrent human change makes this write fail, preserving both old review and proposals file.
                self.store.save(review,version)
                result={'proposals':len(proposals),'reasons':reasons}
                if analysis is not None:
                    result.update(claim_id=ref['reference_claim_id'],claim_text=ref['claim_en'],
                        sentence_text=ref['summary_sentence_en'],applicability=analysis,
                        evidence_selection=review['claims'][ref['reference_claim_id']]['gold_evidence_sets'],
                        reference_fingerprint=fingerprint(ref))
            elif action=='freeze':
                result={'snapshot':str(freeze_workspace(self.dataset,review,folder/'snapshot'))}
            else:
                snapshot=Path(self.jobs[request['snapshot_job']]['result']['snapshot'])
                if action=='materialize':
                    from factual_eval.fase2_injecao.approved import materialize
                    result={'cases':len(materialize(snapshot,folder/'cases')),'path':str(folder/'cases')}
                else:
                    from factual_eval.avaliacao_automatica.experiments import run_experiments
                    result=run_experiments(snapshot,folder/'experiment',device=request.get('device','auto'),
                        notify=lambda text:self.update(jid,stage=text))
            self.update(jid,status='COMPLETE',stage='Finished',result=result,finished_at=now())
        except Exception as exc:
            self.update(jid,status='FAILED',stage='Failed',error=str(exc),finished_at=now())
