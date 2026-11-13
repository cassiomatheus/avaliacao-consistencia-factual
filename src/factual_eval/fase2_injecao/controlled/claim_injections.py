"""Clause-scoped injections: one local edit, with explicit category eligibility.

Clause proposals are syntactic units, not human-validated atomic claims.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import Counter
from hashlib import sha256
import json
import re
from pathlib import Path
from .engine import Change, predicate_changes, numeric_changes, stable_random, _capitalize_change, validate_pair

VERSION='static-v6.2'
CATEGORIES=('predicate','entity','coreference')


@dataclass
class ClaimUnit:
    claim_id: str
    text: str
    predicate_start: int
    spans: list[tuple[int,int]]
    token_ids: set[int]


@dataclass
class EditProposal:
    change: Change
    trace: dict = field(default_factory=dict)


def finite_predicate(token):
    return token.pos_ in {'VERB','AUX'} and (
        token.tag_ in {'VBD','VBP','VBZ','MD'} or
        any(c.dep_ in {'aux','auxpass'} and c.tag_ in {'VBD','VBP','VBZ','MD'} for c in token.children))


def extract_claim_units(doc, sentence_id):
    roots=[t for t in doc if finite_predicate(t) and t.dep_ in {'ROOT','conj','relcl'}]
    root_ids={t.i for t in roots}
    units=[]
    for root in roots:
        tokens=set(t.i for t in root.subtree)
        for sub in roots:
            if sub.i!=root.i and sub.i in tokens:
                tokens.difference_update(t.i for t in sub.subtree)
        subject=next((c for c in root.children if c.dep_ in {'nsubj','nsubjpass','csubj'}),None)
        # Shared subjects are included in text, but edits on them will be rejected
        # later if they also belong to another finite proposition.
        if subject is None and root.dep_=='conj':
            parent=root.head
            subject=next((c for c in parent.children if c.dep_ in {'nsubj','nsubjpass'}),None)
        if subject is None:continue
        tokens.update(t.i for t in subject.subtree if t.i not in root_ids)
        tokens={i for i in tokens if not (doc[i].dep_=='cc' and doc[i].head.i in root_ids)}
        groups=[]
        for i in sorted(tokens):
            if groups and groups[-1][-1]+1==i:groups[-1].append(i)
            else:groups.append([i])
        text=' '.join(doc[g[0]:g[-1]+1].text for g in groups)
        units.append(ClaimUnit(f'{sentence_id}_clause_{root.idx}',text,root.idx,
                               [(doc[i].idx,doc[i].idx+len(doc[i])) for i in sorted(tokens)],tokens))
    return units


def overlaps(a,b,c,d):return a<d and c<b


def eligible_owner(change,units,doc):
    touched={t.i for t in doc if overlaps(change.start,change.end,t.idx,t.idx+len(t)) and not t.is_punct}
    owners=[u for u in units if touched and touched<=u.token_ids]
    if len(owners)!=1:return None
    owner=owners[0]
    if any(touched & u.token_ids for u in units if u is not owner):return None
    return owner


def alias_key(text):
    words=re.findall(r'[A-Za-z]+',text)
    clean=[w for w in words if w.lower() not in {'the','of','and','for'}]
    return ''.join(w[0] for w in clean).upper() if len(clean)>1 else ''.join(clean).upper()


def same_alias(a,b):
    compact=lambda s:re.sub(r'[^A-Za-z0-9]','',s).lower()
    return compact(a)==compact(b) or alias_key(a)==alias_key(b)


def named_entity_edits(sentence_doc,report_doc,evidence_text):
    out=[];seen=set()
    allowed={'ORG','PERSON','GPE','LOC','FAC','PRODUCT','NORP'}
    source_entities=sorted(report_doc.ents,key=lambda e:(e.start_char,e.end_char))
    for ent in sentence_doc.ents:
        if ent.label_ not in allowed:continue
        # Treat a full name plus its parenthesized alias as one entity mention.
        target_start,target_end=ent.start_char,ent.end_char
        suffix=re.match(r'\s*\(([A-Z][A-Z.]{1,11})\)',sentence_doc.text[target_end:])
        if suffix and same_alias(ent.text,suffix.group(1)):target_end+=suffix.end()
        if target_start>0 and sentence_doc.text[target_start-1]=='(' and sentence_doc.text[ent.end_char:ent.end_char+1]==')':
            if any(other.end_char<target_start and same_alias(other.text,ent.text) and sentence_doc.text[other.end_char:target_start].strip()=='(' for other in sentence_doc.ents):continue
        old=sentence_doc.text[target_start:target_end]
        candidates=[]
        for alt in source_entities:
            if alt.label_!=ent.label_ or len(alt.text.strip())<2:continue
            if alt.label_=='ORG' and (alt.root.pos_!='PROPN' or alt.root.dep_=='poss' or alt.root.lemma_.lower() in {'act','media','livestock','poultry','register','collection','agency','food','drug'} or re.search(r'\b(?:act|growth media|livestock|poultry)\b',alt.text,re.I)):continue
            if same_alias(ent.text,alt.text):continue
            if re.search(r'(?<!\w)'+re.escape(alt.text)+r'(?!\w)',sentence_doc.text,re.I):continue
            if re.search(r'(?<!\w)'+re.escape(alt.text)+r'(?!\w)',evidence_text,re.I):continue
            score=float(ent.similarity(alt)) if ent.has_vector and alt.has_vector else 0.
            candidates.append((-score,alt.text.casefold(),alt.start_char,alt))
        for _,_,_,alt in sorted(candidates,key=lambda x:x[:3])[:5]:
            key=(target_start,target_end,alt.text)
            if key in seen:continue
            seen.add(key)
            out.append(EditProposal(Change('entity','named_entity_swap',old,alt.text,
                          target_start,target_end,('same_ner_label','different_alias','replacement_in_source'),
                          ('a troca de entidade requer confirmação factual humana',)),
                          {'entity_type':ent.label_,'original_entity':ent.text,'replacement_entity':alt.text,
                           'replacement_source_span':{'start_char':alt.start_char,'end_char':alt.end_char},
                           'original_entity_span':{'start_char':ent.start_char,'end_char':ent.end_char}}))
    return out


class CoreferenceResolver:
    def __init__(self,device='cpu',model='biu-nlp/f-coref',cache_root=None,revision=None,local_files_only=False):
        import spacy
        from fastcoref import FCoref
        from huggingface_hub import snapshot_download
        revision=revision or ('e91dfff12879495d882ba9460d0c5d5dd44ade59' if model=='biu-nlp/f-coref' else None)
        model_path=snapshot_download(model,revision=revision,local_files_only=local_files_only,allow_patterns=['config.json','pytorch_model.bin','tokenizer.json','tokenizer_config.json','vocab.json','merges.txt','special_tokens_map.json'])
        self.model=FCoref(model_name_or_path=model_path,device=device,nlp=spacy.blank('en'),enable_progress_bar=False)
        self.model_name=model
        self.revision=revision or Path(model_path).name
        self.cache_root=Path(cache_root) if cache_root else None
        self.memory={}
    def clusters(self,text):
        key=sha256((self.model_name+'|'+str(self.revision)+'|'+text).encode()).hexdigest()
        if key in self.memory:return self.memory[key]
        cache=self.cache_root/(key+'.json') if self.cache_root else None
        if cache and cache.exists():rows=json.loads(cache.read_text())
        else:
            result=self.model.predict(texts=[text])[0]
            rows=result.get_clusters(as_strings=False)
            if cache:
                cache.parent.mkdir(parents=True,exist_ok=True)
                cache.write_text(json.dumps(rows))
        # Offsets supplied by the resolver must refer to the exact input bytes/text.
        for cluster in rows:
            if any(not 0<=a<b<=len(text) for a,b in cluster):raise ValueError('Invalid coreference offset')
        self.memory[key]=rows
        return rows


def nominal_info(doc,a,b):
    span=doc.char_span(a,b,alignment_mode='strict')
    if span is None:return None
    root=span.root
    if root.pos_ not in {'NOUN','PROPN'}:return None
    if any(t.pos_=='VERB' for t in span):return None
    plural='Plur' in root.morph.get('Number') or any(t.dep_=='conj' for t in span)
    return span,plural


def referent_kind(span):
    root=span.root
    if root.ent_type_ in {'ORG','PERSON','NORP'}:return 'AGENT'
    if root.ent_type_ in {'GPE','LOC','FAC'}:return 'PLACE'
    if root.ent_type_=='PRODUCT':return 'OBJECT'
    lemma=root.lemma_.lower()
    if lemma in {'official','person','representative','stakeholder','consumer','producer','researcher','member',
                 'agency','company','firm','department','organization','group','committee','administration','institute','office'}:return 'AGENT'
    if lemma in {'agreement','report','guidance','document','recommendation','decision','practice','outcome','term',
                 'principle','plan','policy','process','method','technology','effort','information','phase','research','development','study','work','production'}:return 'ABSTRACT'
    return 'OBJECT'


def coreference_edits(sentence_doc,summary_doc,sentence_start,resolver,evidence_text=""):
    text=summary_doc.text;clusters=resolver.clusters(text);out=[]
    end=sentence_start+len(sentence_doc.text)
    for ci,cluster in enumerate(clusters):
        for a,b in cluster:
            if not sentence_start<=a<b<=end:continue
            mention=summary_doc.char_span(a,b,alignment_mode='strict')
            if mention is None:continue
            # Referential expressions, not arbitrary named-entity replacements.
            if not (mention.root.pos_=='PRON' or mention.root.pos_=='NOUN' and mention[0].lower_ in {'the','these','those','this','that','their','its'}):continue
            prior=[(x,y) for x,y in cluster if y<=a and nominal_info(summary_doc,x,y)]
            if not prior:continue
            ant_a,ant_b=max(prior,key=lambda p:p[1]);ant_span,plural=nominal_info(summary_doc,ant_a,ant_b)
            if any(t.dep_=='conj' for t in mention):plural=True
            elif mention.root.morph.get('Number'):plural='Plur' in mention.root.morph.get('Number')
            referent_type=ant_span.root.ent_type_ or None
            alternatives=[]
            for cj,other in enumerate(clusters):
                if cj==ci:continue
                # Avoid substituting a referent already explicit in the reviewed
                # support (e.g. agency officials -> their own agencies).
                if any(nominal_info(summary_doc,u,v) and len(text[u:v])>=3 and re.search(r'(?<!\w)'+re.escape(text[u:v])+r'(?!\w)',evidence_text,re.I) for u,v in other):continue
                for x,y in other:
                    if y>a:continue
                    info=nominal_info(summary_doc,x,y)
                    if not info:continue
                    alt_span,alt_plural=info
                    if plural!=alt_plural or same_alias(ant_span.text,alt_span.text):continue
                    if referent_kind(ant_span)!=referent_kind(alt_span):continue
                    alt_type=alt_span.root.ent_type_ or None
                    if referent_type and alt_type and referent_type!=alt_type:continue
                    if any(overlaps(x,y,u,v) for u,v in cluster):continue
                    if mention.root.lower_ in {'he','she','him','her','his','hers'}:
                        # Gender is not inferred from names. Require the same pronoun
                        # in the competing model cluster to preserve agreement.
                        if not any(text[u:v].lower()==mention.root.lower_ for u,v in other):continue
                    replacement=alt_span.text
                    # Reuse the competing referent as a definite expression,
                    # not a new indefinite group ('Multiple firms' -> 'these firms').
                    if alt_span.root.pos_=='NOUN':
                        first=0
                        while first<len(alt_span)-1 and (alt_span[first].pos_ in {'DET','NUM'} or alt_span[first].lower_ in {'multiple','several','some','all'}):first+=1
                        replacement=('these ' if alt_plural else 'that ')+alt_span[first:].text
                    if mention.root.dep_=='poss' or any(t.tag_=='POS' for t in mention):
                        replacement=replacement+("'" if replacement.lower().endswith('s') else "'s")
                    if replacement.casefold()==mention.text.casefold():continue
                    alternatives.append((-(y),x,y,replacement,cj))
            seen=set()
            for _,x,y,replacement,cj in sorted(alternatives)[:5]:
                if replacement.casefold() in seen:continue
                seen.add(replacement.casefold())
                local_a,local_b=a-sentence_start,b-sentence_start
                change=Change('coreference','wrong_antecedent',mention.text,replacement,local_a,local_b,
                              ('contextual_coreference_cluster','earlier_original_antecedent','different_competing_cluster',
                               'number_agreement_preserved','compatible_referent_kind','wrong_antecedent_absent_from_reviewed_support'),
                              ('os vínculos de correferência são predições de modelo, não anotações humanas',))
                trace={'resolver':getattr(resolver,'model_name','test'),
                       'resolver_revision':getattr(resolver,'revision',None),
                       'mention_span':{'start_char':a,'end_char':b,'text':text[a:b]},
                       'original_antecedent':{'start_char':ant_a,'end_char':ant_b,'text':text[ant_a:ant_b]},
                       'wrong_antecedent':{'start_char':x,'end_char':y,'text':text[x:y]},
                       'original_cluster':ci,'competing_cluster':cj,'replacement_referring_expression':replacement,
                       'context_sha256':sha256(text.encode()).hexdigest()}
                out.append(EditProposal(change,trace))
    return out


def confirm_wrong_antecedent(proposal,summary,sentence_start,resolver):
    c=proposal.change;a=sentence_start+c.start;b=sentence_start+c.end
    replacement=_capitalize_change(c.old,c.new)
    modified=summary[:a]+replacement+summary[b:]
    clusters=resolver.clusters(modified)
    new_span=(a,a+len(replacement));wrong=proposal.trace['wrong_antecedent'];original=proposal.trace['original_antecedent']
    def has(cluster,start,end):return any(overlaps(start,end,x,y) and (min(end,y)-max(start,x))>=min(end-start,y-x)*.8 for x,y in cluster)
    for cluster in clusters:
        if has(cluster,*new_span) and has(cluster,wrong['start_char'],wrong['end_char']):
            if has(cluster,original['start_char'],original['end_char']):return False
            proposal.trace['modified_cluster_link_confirmed']=True
            return True
    return False


def collect(candidates,sources,nlp,resolver,categories=CATEGORIES):
    jobs=[];audit=[];contexts={}
    for row in sorted(candidates,key=lambda r:(r['doc_id'],r['summary_sentence_id'])):
        source=sources.get(row['doc_id']);sid=row['summary_sentence_id']
        if row.get('reference_granularity')!='SENTENCE_LEVEL' or row.get('claim_level_sufficiency')!='NOT_ASSESSED' or row.get('review_status')!='completed':
            raise ValueError('Use candidatos sentenciais concluídos do prepare_reviews.py; apoio por claim não é presumido.')
        if source is None:audit.append({'id':sid,'reasons':['source_not_found']});continue
        report,summary=source['report'],source['summary'];sentence=row['summary_sentence_en']
        positions=[m.start() for m in re.finditer(re.escape(sentence),summary)]
        if len(positions)!=1:audit.append({'id':sid,'reasons':['sentence_not_unique_in_summary']});continue
        start=positions[0]
        if row['doc_id'] not in contexts:contexts[row['doc_id']]=(nlp(report),nlp(summary))
        report_doc,summary_doc=contexts[row['doc_id']]
        doc=nlp(sentence);units=extract_claim_units(doc,sid)
        if not units:audit.append({'id':sid,'reasons':['no_finite_claim_unit']});continue
        evidence='\n'.join(p['text_en'] for p in row.get('supporting_passages_reviewed',[]))
        if not evidence:audit.append({'id':sid,'reasons':['no_reviewed_support']});continue
        canonical=lambda text:' '.join(text.split())
        if any(canonical(p['text_en']) not in canonical(report) for p in row['supporting_passages_reviewed']):
            audit.append({'id':sid,'reasons':['reviewed_evidence_not_in_source']});continue
        edits=[]
        # Evaluate rules within each claim, keeping absolute sentence offsets.
        # A negation in another clause must not suppress an eligible predicate.
        for unit in units:
            masked=list(' '*len(sentence))
            for a,b in unit.spans:masked[a:b]=sentence[a:b]
            local=''.join(masked)
            if 'predicate' in categories:
                edits.extend(EditProposal(c) for c in predicate_changes(local,local) if sentence[c.start:c.end]==c.old)
            if 'entity' in categories:
                edits.extend(EditProposal(c) for c in numeric_changes(local,local,evidence) if sentence[c.start:c.end]==c.old)
        if 'entity' in categories:
            edits.extend(named_entity_edits(doc,report_doc,evidence))
        if 'coreference' in categories:
            if resolver is None:raise ValueError('Coreferência exige um resolvedor contextual.')
            edits.extend(coreference_edits(doc,summary_doc,start,resolver,evidence))
        owned={u.claim_id:[] for u in units}
        for proposal in edits:
            owner=eligible_owner(proposal.change,units,doc)
            if owner is not None:owned[owner.claim_id].append(proposal)
        for unit in units:
            proposals={cat:[] for cat in categories}
            seen=set()
            for proposal in owned[unit.claim_id]:
                c=proposal.change;key=(c.start,c.end,c.new,c.category)
                if key in seen:continue
                seen.add(key)
                proposals[c.category].append(proposal)
            jobs.append({'unit':unit,'row':row,'source':source,'sentence_start':start,
                         'units':units,'proposals':proposals})
    return jobs,audit


def select_jobs(jobs,seed=42):
    """One category per claim; prioritize feasible rare categories, never fabricate them."""
    assignments={};counts=Counter();available={c:[i for i,j in enumerate(jobs) if j['proposals'].get(c)] for c in CATEGORIES}
    # Reserve at most one feasible claim for each category before balancing.
    for cat in sorted(CATEGORIES,key=lambda c:(len(available[c]),c)):
        choices=[i for i in available[cat] if i not in assignments]
        if choices:
            i=min(choices,key=lambda i:(sum(bool(v) for v in jobs[i]['proposals'].values()),jobs[i]['unit'].claim_id))
            assignments[i]=cat;counts[cat]+=1
    for i in sorted(range(len(jobs)),key=lambda i:jobs[i]['unit'].claim_id):
        if i in assignments:continue
        feasible=[c for c in CATEGORIES if jobs[i]['proposals'].get(c)]
        if not feasible:continue
        rng=stable_random(seed,jobs[i]['unit'].claim_id)
        tie={c:rng.random() for c in feasible}
        cat=min(feasible,key=lambda c:(counts[c],tie[c]));assignments[i]=cat;counts[cat]+=1
    return assignments


def generate_claims(candidates,sources,nlp,resolver,seed=42,categories=CATEGORIES,selection="one_per_type"):
    if selection not in {"one_per_type","one_per_claim"}:raise ValueError("Invalid selection policy")
    jobs,audit=collect(candidates,sources,nlp,resolver,categories)
    # Confirm actual model linkage after a coreferential edit before assignment.
    for job in jobs:
        confirmed=[]
        for proposal in job['proposals'].get('coreference',[]):
            if confirm_wrong_antecedent(proposal,job['source']['summary'],job['sentence_start'],resolver):
                confirmed.append(proposal)
                # One confirmed alternative is enough; don't multiply neural work.
                break
        if 'coreference' in job['proposals']:job['proposals']['coreference']=confirmed
    reason_by_category={'predicate':'no_local_predicate_edit',
                        'entity':'no_compatible_named_entity_or_supported_quantity',
                        'coreference':'no_confirmed_contextual_antecedent_switch'}
    for job in jobs:
        for cat in categories:
            if not job['proposals'].get(cat):
                audit.append({'id':job['unit'].claim_id,'category':cat,'reasons':[reason_by_category[cat]]})
    assignments=select_jobs(jobs,seed) if selection=="one_per_claim" else None
    chosen=[(i,cat) for i,job in enumerate(jobs) for cat in CATEGORIES if job["proposals"].get(cat) and (assignments is None or assignments.get(i)==cat)]
    out=[]
    for i,job in enumerate(jobs):
        if not any(index==i for index,_ in chosen):audit.append({"id":job["unit"].claim_id,"reasons":["no_applicable_category_without_affecting_other_claims"]})
    for i,cat in chosen:
        job=jobs[i]
        unit=job['unit'];row=job['row'];source=job['source'];sentence=row['summary_sentence_en']
        choices=sorted(job['proposals'][cat],key=lambda p:p.change.strategy!='named_entity_swap') if cat=='entity' else job['proposals'][cat] if cat=='coreference' else sorted(job['proposals'][cat],key=lambda p:(p.change.start,p.change.new))
        # Deterministic seed changes the alternative, never adds a second edit.
        proposal=choices[0] if cat in {'entity','coreference'} else choices[stable_random(seed,unit.claim_id,cat).randrange(len(choices))]
        c=proposal.change;new=(c.new if c.strategy=='named_entity_swap' else _capitalize_change(c.old,c.new))
        if c.strategy=='named_entity_swap' and c.start==0:new=new[:1].upper()+new[1:]
        a=job['sentence_start']+c.start;b=job['sentence_start']+c.end
        summary=source['summary'];modified=summary[:a]+new+summary[b:]
        unit_spans=[{'start_char':job['sentence_start']+x,'end_char':job['sentence_start']+y} for x,y in unit.spans]
        other_spans=[{'start_char':job['sentence_start']+x,'end_char':job['sentence_start']+y} for u in job['units'] if u is not unit for x,y in u.spans]
        key=f'{VERSION}|{unit.claim_id}|{cat}|{a}|{new}'
        result={
            'schema_version':'2.1','injection_id':'I_'+sha256(key.encode()).hexdigest()[:16],
            'document_id':row['doc_id'],'summary_sentence_id':row['summary_sentence_id'],
            'claim_id':unit.claim_id,'claim_origin':'SYNTAX_CLAUSE_PROPOSAL',
            'claim_en':unit.text,'applicable_categories':[cat for cat in categories if job['proposals'].get(cat)],'claim_token_spans':unit_spans,'other_claim_token_spans':other_spans,
            'reference_claim_id':None,'original_claim_en':unit.text,
            'reference_granularity':'CLAUSE_LEVEL_PROVISIONAL','selection_policy':selection,
            'original_sentence_en':sentence,'modified_sentence_en':sentence[:c.start]+new+sentence[c.end:],
            'original_summary_en':summary,'modified_summary_en':modified,
            'error_category':cat,'strategy':c.strategy,
            'edit':{'start_char':a,'end_char':b,'original':c.old,'replacement':new},
            'supporting_passages_reviewed':row['supporting_passages_reviewed'],
            'source_review_dataset_sha256':row.get('source_review_dataset_sha256'),
            'review_notes':row.get('notes',''),'evidence_granularity':'SENTENCE_LEVEL','claim_level_sufficiency':'NOT_ASSESSED',
            'known_sufficient_evidence_sets':[],
            'validation_status':'PROPOSAL_CLAUSE_ONLY','gold_eligible':False,
            'hypothesized_modified_relation':'UNKNOWN','human_validated_modified_relation':False,
            'validation_checks':list(c.checks)+['one_local_edit','one_target_claim','other_claim_tokens_unchanged'],
            'transformation_trace':proposal.trace,
            'remaining_caveats':list(c.caveats)+['divisão em claims é sintática e requer revisão humana',
                'apoio à sentença original não comprova suficiência de evidência por claim'],
            'generator':{'version':VERSION,'seed':seed,'spacy_model':nlp.meta.get('name'),
                         'spacy_model_version':nlp.meta.get('version'),
                         'source_sha256':sha256(source['report'].encode()).hexdigest(),
                         'source_summary_sha256':sha256(source['summary'].encode()).hexdigest()}}
        errors=validate_pair(result)
        if errors:raise ValueError(f'Invalid claim injection {unit.claim_id}: {errors}')
        out.append(result)
    assert len(out)==len({(r['claim_id'],r['error_category']) for r in out})
    if selection=='one_per_claim':assert len(out)==len({r['claim_id'] for r in out})
    return out,audit,{'input_sentences':len(candidates),'extracted_claim_units':len(jobs),
                     'claims_with_injection':len({r['claim_id'] for r in out}),'versions':len(out),'claims_without_applicable_edit':len(jobs)-len({r['claim_id'] for r in out}),'by_category':dict(Counter(r['error_category'] for r in out))}
