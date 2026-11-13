"""CLI da V6: geração de propostas e validação sem LLM."""
import argparse
import collections
import json
import sys
from pathlib import Path
from .engine import VERSION, generate_for_reference, generate_for_sentence_candidate, validate_pair


def read_jsonl(p):
    for n,line in enumerate(Path(p).read_text(encoding="utf-8").splitlines(),1):
        if line.strip():
            try: yield json.loads(line)
            except json.JSONDecodeError as exc: raise ValueError(f"{p}:{n}: {exc}") from exc


def write_new(p, records):
    dest=Path(p)
    dest.parent.mkdir(parents=True,exist_ok=True)
    # 'x' prevents accidental loss of previous experiments.
    with dest.open("x", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record,ensure_ascii=False,sort_keys=True)+"\n")


def run_generate(args):
    refs=list(read_jsonl(args.references))
    sources={}
    for row in read_jsonl(args.source):
        k=row.get("doc_id",row.get("id"))
        if not k or k in sources: raise ValueError(f"Missing/duplicate doc_id: {k}")
        row["doc_id"]=k
        sources[k]=row
    nlp=None
    if "entity" in args.strategies or "coreference" in args.strategies:
        try:
            import spacy
            nlp=spacy.load(args.spacy_model)
        except Exception as exc:
            raise RuntimeError(f"Named entity replacement requires spaCy model '{args.spacy_model}': {exc}") from exc
    resolver=None
    if 'coreference' in args.strategies:
        from .claim_injections import CoreferenceResolver
        resolver=CoreferenceResolver(device=args.coref_device,cache_root=args.output.parent/'.coreference-cache')
    antonyms={}
    if args.antonyms:
        data=json.loads(Path(args.antonyms).read_text(encoding="utf-8"))
        for k,v in data.items():
            if isinstance(v,str): antonyms[k]=v
            elif isinstance(v,list) and v and isinstance(v[0],str): antonyms[k]=v[0]
    result=[]
    rejected=[]
    for ref in refs:
        sid=ref.get("reference_claim_id",ref.get("summary_sentence_id", "unknown"))
        src=sources.get(ref.get("doc_id"))
        if src is None:
            rejected.append({"id":sid,"reasons":["source_document_not_found"]})
            continue
        pairs,reasons=generate_for_reference(ref,src,seed=args.seed,
                strategies=args.strategies,nlp=nlp,antonyms=antonyms,max_per_claim=args.max_per_claim,
                coref_resolver=resolver,one_per_type=args.one_per_type)
        for p in pairs:
            issue=validate_pair(p)
            if issue: raise ValueError(f"Internal validation failure for {sid}: {issue}")
        result.extend(pairs)
        if reasons: rejected.append({"id":sid,"reasons":reasons})
    write_new(args.output,result)
    write_new(args.rejected,rejected)
    print(json.dumps({"version":VERSION,"references":len(refs),"pairs":len(result),
                      "rejected_references":len(rejected),
                      "by_strategy":dict(collections.Counter(x["strategy"] for x in result)),
                      "gold_eligible":sum(bool(x.get("gold_eligible")) for x in result)},ensure_ascii=False,indent=2))


def run_provisional(args):
    sources={}
    for row in read_jsonl(args.source):
        k=row.get("doc_id",row.get("id"))
        if not k or k in sources: raise ValueError(f"Missing/duplicate doc_id: {k}")
        row["doc_id"]=k
        sources[k]=row
    nlp=None
    if "entity" in args.strategies:
        try:
            import spacy
            nlp=spacy.load(args.spacy_model)
        except Exception as exc:
            raise RuntimeError(f"spaCy model required: {exc}") from exc
    rows=[];rejections=[]
    candidates=list(read_jsonl(args.candidates))
    for c in candidates:
        source=sources.get(c.get("doc_id"))
        if source is None:
            rejections.append({"id":c.get("summary_sentence_id"),"reasons":["source_not_found"]})
            continue
        pairs,reasons=generate_for_sentence_candidate(c,source,seed=args.seed,nlp=nlp,
                         strategies=args.strategies,max_per_sentence=args.max_per_sentence)
        for pair in pairs:
            errs=validate_pair(pair)
            if errs: raise ValueError(f"Invalid provisional pair: {errs}")
        rows.extend(pairs)
        if reasons:rejections.append({"id":c.get("summary_sentence_id"),"reasons":reasons})
    write_new(args.output,rows);write_new(args.rejected,rejections)
    print(json.dumps({"version":VERSION,"input_sentences":len(candidates),
                      "sentences_with_proposals":len({(r["document_id"],r["summary_sentence_id"]) for r in rows}),
                      "pairs_provisional":len(rows),"rejected":len(rejections),
                      "by_strategy":dict(collections.Counter(r["strategy"] for r in rows)),
                      "rejection_reasons":dict(collections.Counter(reason for r in rejections for reason in r["reasons"])),
                      "gold_eligible":0},indent=2))


def run_claims(args):
    if args.output.resolve()==args.rejected.resolve() or args.output.exists() or args.rejected.exists():raise FileExistsError('Escolha dois novos destinos de saída distintos.')
    import spacy
    from .claim_injections import generate_claims,CoreferenceResolver
    nlp=spacy.load(args.spacy_model)
    sources={}
    for row in read_jsonl(args.source):
        if row['doc_id'] in sources:raise ValueError('Duplicate source doc_id')
        sources[row['doc_id']]=row
    candidates=list(read_jsonl(args.candidates))
    if len({(r['doc_id'],r['summary_sentence_id']) for r in candidates})!=len(candidates):
        raise ValueError('Duplicate reviewed sentence')
    resolver=CoreferenceResolver(args.coref_device,args.coref_model,args.coref_cache,args.coref_revision) if 'coreference' in args.categories else None
    rows,audit,stats=generate_claims(candidates,sources,nlp,resolver,args.seed,args.categories,args.selection)
    # Preflight both paths before publishing either output.
    if args.output.exists() or args.rejected.exists():raise FileExistsError('Escolha novos destinos de saída.')
    write_new(args.output,rows);write_new(args.rejected,audit)
    print(json.dumps(stats,ensure_ascii=False,indent=2))


def run_validate(args):
    counts=collections.Counter()
    bad=[]
    seen_claim_categories=set()
    for row in read_jsonl(args.input):
        counts["total"]+=1
        errs=validate_pair(row)
        if row.get('reference_granularity')=='CLAUSE_LEVEL_PROVISIONAL':
            key=(row.get('document_id'),row.get('claim_id'),row.get('error_category') if row.get('selection_policy')=='one_per_type' else None)
            if key in seen_claim_categories:errs.append('duplicate_version_for_claim_and_type')
            seen_claim_categories.add(key)
        if errs: bad.append({"id":row.get("injection_id"),"errors":errs})
    print(json.dumps({"checked":counts["total"],"errors":bad},ensure_ascii=False,indent=2))
    if bad: sys.exit(1)


def main():
    p=argparse.ArgumentParser(description="V6: injeções estáticas rastreáveis, SEM gold automático")
    sp=p.add_subparsers(dest="command",required=True)
    g=sp.add_parser("generate",help="Gerar pares mínimos a partir de claims humanamente validadas")
    g.add_argument("--references",type=Path,required=True)
    g.add_argument("--source",type=Path,required=True,help="JSONL com doc_id, report e summary original COMPLETO")
    g.add_argument("--output",type=Path,required=True)
    g.add_argument("--rejected",type=Path,required=True)
    g.add_argument("--seed",type=int,default=42)
    g.add_argument("--max-per-claim",type=int,default=2)
    g.add_argument("--strategies",nargs="+",choices=["numeric","negation","antonym","entity","coreference"],
                   default=["numeric","negation","antonym"])
    g.add_argument("--spacy-model",default="en_core_web_md")
    g.add_argument("--antonyms",type=Path)
    g.add_argument("--one-per-type",action="store_true")
    g.add_argument("--coref-device",default="cpu")
    g.set_defaults(func=run_generate)
    s=sp.add_parser("generate-provisional", help="Usar revisões antigas por SENTENÇA, sem produzir gold de claims")
    s.add_argument("--candidates",type=Path,required=True)
    s.add_argument("--source",type=Path,required=True)
    s.add_argument("--output",type=Path,required=True)
    s.add_argument("--rejected",type=Path,required=True)
    s.add_argument("--seed",type=int,default=42)
    s.add_argument("--max-per-sentence",type=int,default=2)
    s.add_argument("--strategies",nargs="+",choices=["numeric","negation","antonym","entity","coreference"],default=["numeric","negation","antonym"])
    s.add_argument("--spacy-model",default="en_core_web_md")
    s.set_defaults(func=run_provisional)
    c=sp.add_parser('generate-claims',help='Uma edição por claim sintática, em versões independentes por tipo aplicável')
    c.add_argument('--candidates',type=Path,required=True)
    c.add_argument('--source',type=Path,required=True)
    c.add_argument('--output',type=Path,required=True)
    c.add_argument('--rejected',type=Path,required=True)
    c.add_argument('--seed',type=int,default=42)
    c.add_argument('--categories',nargs='+',choices=['predicate','entity','coreference'],default=['predicate','entity','coreference'])
    c.add_argument('--selection',choices=['one_per_type','one_per_claim'],default='one_per_type')
    c.add_argument('--spacy-model',default='en_core_web_md')
    c.add_argument('--coref-model',default='biu-nlp/f-coref')
    c.add_argument('--coref-device',default='cpu')
    c.add_argument('--coref-revision',help='Snapshot do resolvedor; o padrão f-coref já é fixado por hash')
    c.add_argument('--coref-cache',type=Path,default=Path('.cache/coreference'))
    c.set_defaults(func=run_claims)
    v=sp.add_parser("validate",help="Verificar as propriedades estruturais dos pares")
    v.add_argument("--input",type=Path,required=True)
    v.set_defaults(func=run_validate)
    a=p.parse_args()
    if hasattr(a,"max_per_sentence") and a.max_per_sentence<1:p.error("--max-per-sentence deve ser positivo")
    a.func(a)

if __name__ == "__main__":
    main()
