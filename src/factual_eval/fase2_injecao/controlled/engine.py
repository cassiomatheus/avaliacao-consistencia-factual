"""V6: gerador ESTÁTICO de propostas de inconsistência com proveniência factual.

Não é um juiz de veracidade. Nunca chama LLM/NLI, nunca inventa rótulos humanos.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable

VERSION = "controlled-reference-v1"
ERROR_TAG = re.compile(r"\[ERROR_(?:PREDICATE|ENTITY|COREFERENCE)[^]]*]", re.I)
NUM_RE = re.compile(r"(?<![\w.])(?:\$\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w.])|(?<!\w)(?:\$\s*)?\d+(?:\.\d+)?(?![\w.])")
VERBS = {
    "approved": ("approve", "rejected"), "rejected": ("reject", "approved"),
    "funded": ("fund", None), "reported": ("report", None),
    "supported": ("support", "opposed"), "allocated": ("allocate", None),
    "received": ("receive", None), "provided": ("provide", "withheld"),
    "completed": ("complete", None), "reduced": ("reduce", "increased"),
    "increased": ("increase", "decreased"), "decreased": ("decrease", "increased"),
    "expanded": ("expand", "reduced"), "identified": ("identify", None),
    "covered": ("cover", None),
}
PRONOUN_SWAPS = {"he": "she", "she": "he", "him": "her", "her": "him"}

@dataclass(frozen=True)
class Change:
    category: str
    strategy: str
    old: str
    new: str
    start: int   # start of replacement relative to the ORIGINAL SENTENCE
    end: int
    checks: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


def stable_random(seed: int, *parts: str) -> random.Random:
    digest = hashlib.sha256((str(seed) + "|" + "|".join(parts)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def text_occurrences(text: str, token: str) -> list[tuple[int, int]]:
    if not token or token.isspace():
        return []
    # Tokens can contain $, punctuation. Disallow substring matches inside words.
    pattern = re.compile(r"(?<!\w)" + re.escape(token) + r"(?!\w)", re.I)
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def _evidence_texts(reference: dict[str, Any]) -> str:
    return "\n".join(str(x.get("text_en", "")) for x in reference.get("evidences", []))


def numeric_changes(sentence: str, claim: str, evidence_text: str) -> list[Change]:
    """Only numbers explicitly present in claim + support evidence + sentence.

    Still not a proof of contradiction; it is a defensible candidate generator.
    """
    out = []
    for m in NUM_RE.finditer(claim):
        if _enumeration_at(claim, m.start(), m.end()):
            continue
        raw = m.group().strip()
        digits = raw.replace("$", "").replace(",", "").strip()
        try:
            n = float(digits)
        except ValueError:
            continue
        if not math.isfinite(n) or n <= 0:
            continue
        if not raw.startswith("$") and n.is_integer() and 1850 <= n <= 2100:
            continue  # avoid years, which require a different experimental protocol
        spans = text_occurrences(sentence, raw)
        if len(spans) != 1 or len(text_occurrences(evidence_text, raw)) < 1:
            continue
        # Avoid changing a numeral embedded in a larger quantity (e.g. 20 -> 20,000).
        a, b = spans[0]
        if _enumeration_at(sentence, a, b):
            continue
        if b < len(sentence) and (sentence[b].isdigit() or sentence[b] in ",."):
            continue
        if a > 0 and (sentence[a-1].isdigit() or sentence[a-1] in ",."):
            continue
        if n.is_integer():
            new_number = int(n) + max(1, round(int(n) * 0.25))
            replacement_digits = f"{new_number:,}" if "," in raw else str(new_number)
        else:
            new_number = n * 1.25
            decimals = len(digits.partition(".")[2])
            replacement_digits = f"{new_number:.{decimals}f}"
        new = ("$" if raw.lstrip().startswith("$") else "") + replacement_digits
        if new == raw:
            continue
        out.append(Change("entity", "numeric_change", sentence[a:b], new, a, b,
                          ("value_in_claim", "value_in_supporting_evidence", "single_occurrence_in_sentence"),
                          ("a troca numérica não prova, por si, contradição documental",)))
    # Cardinal words are quantities too; require the same word in reviewed support.
    words = {"one":"two", "two":"three", "three":"four", "four":"five",
             "five":"six", "six":"seven", "seven":"eight", "eight":"nine",
             "nine":"ten", "ten":"eleven", "eleven":"twelve", "twelve":"thirteen"}
    for old,new in words.items():
        spans=text_occurrences(sentence,old)
        if len(spans)!=1 or not text_occurrences(claim,old) or not text_occurrences(evidence_text,old):
            continue
        a,b=spans[0]
        # Count nouns only; skip idioms such as 'one of', and written-out years.
        tail=sentence[b:]
        if not re.match(r"\s+[A-Za-z]+s\b",tail) or re.match(r"\s+(?:hundred|thousand|million|billion|point|of)\b",tail,re.I):
            continue
        out.append(Change("entity","numeric_change",sentence[a:b],new,a,b,
                          ("cardinal_count_word", "value_in_claim", "value_in_supporting_evidence"),
                          ("a troca numérica não prova, por si, contradição documental",)))
        values=list(words)
        if old!="one":
            out.append(Change("entity","numeric_change",sentence[a:b],values[values.index(old)-1],a,b,
                              ("cardinal_count_word", "value_in_claim", "value_in_supporting_evidence"),
                              ("a troca numérica não prova, por si, contradição documental",)))
    return out


def _enumeration_at(text: str, start: int, end: int) -> bool:
    # (1), (2), 1) and sentence/list-initial '1. Item'; never alter these labels.
    before,after=text[:start],text[end:]
    return bool(re.search(r"\(\s*$",before) and re.match(r"\s*\)",after)
                or re.match(r"\s*\)",after)
                or re.match(r"\.\s+[A-Za-z]",after) and not before.strip())


def predicate_changes(sentence: str, claim: str, antonyms: dict[str, str] | None = None) -> list[Change]:
    """Static, local polarity edits: auxiliaries, copulas and finite lexical verbs.

    No parser or model is required. Ambiguous scopes remain proposals for review.
    A pre-existing negative is removed instead of adding a second negation.
    """
    out: list[Change] = []
    antonyms = antonyms or {}
    negative = bool(re.search(r"\b(?:not|never|no|neither|nor|without)\b|n['’]t\b",sentence,re.I))
    checks=("predicate_in_claim", "single_local_polarity_edit")
    caveats=("verificar escopo de negação, coordenação e modalidade",)
    def add(a,b,new,extra=()):
        old=sentence[a:b]
        if text_occurrences(claim,old):
            out.append(Change("predicate","negation",old,new,a,b,checks+extra,caveats))
    # Remove 'not' with its auxiliary, keeping an auditable single replacement.
    aux=r"(?:am|is|are|was|were|has|have|had|can|could|will|would|should|must|may|might|do|does|did)"
    for m in re.finditer(r"\b("+aux+r")\s+not(?:\s+yet)?\b",sentence,re.I):
        # do-support requires conjugation on removal; handled separately below.
        if m.group(1).lower() in {"do","does","did"}:continue
        add(m.start(),m.end(),m.group(1),("explicit_negation_removed",))
    # Minimal grammatical quantifier reversal: 'no company is' -> 'one company is'.
    for m in re.finditer(r"\bno(?=\s+(?:company|firm|agency|producer|product|method|report)\b)",sentence,re.I):
        add(m.start(),m.end(),"one",("negative_quantifier_replaced",))
    # Expand the finite-verb vocabulary, distinguishing inflected present from past.
    verbs={**VERBS, "produced":("produce",None), "signed":("sign",None),
           "created":("create",None), "decided":("decide",None),
           "announced":("announce",None), "documented":("document",None),
           "concurred":("concur",None), "indicated":("indicate",None),
           "expressed":("express",None)}
    present={"appear":("appear","do"), "appears":("appear","does"),
             "contains":("contain","does"), "recommends":("recommend","does"),
             "describes":("describe","does"), "examines":("examine","does")}
    # do/does/did not -> affirmative; conjugate only known verbs, not guessed forms.
    forms={lemma:{"did":past} for past,(lemma,_) in verbs.items()}
    for form,(lemma,helper) in present.items():forms.setdefault(lemma,{})[helper]=form
    for m in re.finditer(r"\b(do|does|did)\s+not\s+(\w+)\b",sentence,re.I):
        helper,lemma=m.group(1).lower(),m.group(2).lower()
        replacement=lemma if helper=="do" else forms.get(lemma,{}).get(helper)
        if replacement:add(m.start(),m.end(),replacement,("do_support_removed_with_inflection",))
    if not negative:
        for m in re.finditer(r"\b("+aux+r")\b",sentence,re.I):
            token=m.group().lower();after=sentence[m.end():];before=sentence[:m.start()]
            clause=re.split(r"[,;.!?]",before)[-1]
            if re.search(r"\b(?:whether|if|what)\b",clause,re.I):continue
            if re.search(r"\b(?:to|can|could|will|would|should|must|may|might)\s+$",before,re.I):continue
            # Do not treat possession ('have clarity') as a perfect auxiliary.
            if token in {"has","have","had"} and not re.match(
                r"\s+(?:\w+ly\s+)*(?:been|begun|known|\w+ed|\w+en)\b",after,re.I):continue
            if token in {"do","does","did"}:continue
            # Avoid weak double negatives such as 'is not unclear'.
            if token in {"am","is","are","was","were"} and re.match(r"\s+(?:unclear|unknown|unlikely|unable)\b",after,re.I):continue
            add(m.start(),m.end(),m.group()+" not",("auxiliary_or_copula",))
        for verb,(lemma,default_antonym) in verbs.items():
            spans=text_occurrences(sentence,verb)
            if len(spans)!=1 or not text_occurrences(claim,verb):continue
            a,b=spans[0]
            # Skip participles, infinitives, coordinated complements and adjectives.
            before=sentence[:a]
            if re.search(r"\b(?:"+aux+r"|not|to)(?:\s+\w+ly)*\s+$",before,re.I):continue
            if re.search(r"\b(?:and|or)\s+$",before,re.I) and re.search(r"\b(?:has|have|had|is|are|was|were)\b",re.split(r"[,;.!?]",before)[-1],re.I):continue
            if re.match(r"\s+(?:meat|products?|methods?|cells?|system)\b",sentence[b:],re.I):continue
            candidate_antonym=antonyms.get(lemma) or default_antonym
            if candidate_antonym and candidate_antonym.lower()!=verb:
                out.append(Change("predicate","antonym",sentence[a:b],candidate_antonym,a,b,
                                  ("predicate_in_claim","lexical_antonym_candidate"),
                                  ("antônimos em contexto não garantem contradição",)))
            adverb=re.search(r"\b(\w+ly)\s+$",sentence[:a],re.I)
            if adverb:
                add(adverb.start(),b,f"did not {adverb.group(1)} {lemma}",("finite_simple_past_candidate",))
            else:
                add(a,b,f"did not {lemma}",("finite_simple_past_candidate",))
        for verb,(lemma,helper) in present.items():
            spans=text_occurrences(sentence,verb)
            if len(spans)!=1:continue
            a,b=spans[0]
            if re.search(r"\b(?:"+aux+r"|not|to|and|or)\s+$",sentence[:a],re.I):continue
            add(a,b,f"{helper} not {lemma}",("finite_present_candidate",))
    # Context-neutral lexical complements; not claimed to establish contradiction.
    for old,new in {"likely":"unlikely", "unclear":"clear", "unknown":"known"}.items():
        spans=text_occurrences(sentence,old)
        if len(spans)==1 and text_occurrences(claim,old):
            a,b=spans[0]
            if re.search(r"\bnot\s+$",sentence[:a],re.I):continue
            out.append(Change("predicate","antonym",sentence[a:b],new,a,b,
                              ("predicate_in_claim","lexical_complement"),
                              ("antônimos em contexto não garantem contradição",)))
    # Never count identical edits twice (for example overlapping rule vocabularies).
    unique={(c.start,c.end,c.new,c.strategy):c for c in out}
    return list(unique.values())


def coreference_changes(sentence: str, claim: str) -> list[Change]:
    # A pilot heuristic only. Do not infer antecedents or claim sufficiency from gender.
    out=[]
    for old, new in (("he", "she"), ("she", "he")):
        spans = text_occurrences(sentence, old)
        if len(spans) != 1 or not text_occurrences(claim, old):
            continue
        a,b=spans[0]
        out.append(Change("coreference", "pronoun_gender_swap", sentence[a:b], new, a,b,
                          ("single_pronoun_occurrence",),
                          ("antecedente não foi verificado", "mudança de pronome não é necessariamente contradição")))
    return out


def entity_changes(sentence: str, claim: str, source_text: str, evidence_text: str,
                   nlp: Any) -> list[Change]:
    """Strict same-NER-label swaps, not ORG/GPE or PERSON/NORP mixed.

    No claim of factual contradiction: the source can support the replacement too.
    """
    if nlp is None or not source_text:
        return []
    valid_types = {"ORG", "GPE", "PERSON", "LOC", "NORP", "FAC", "PRODUCT"}
    src_ents = list(nlp(source_text).ents)
    claim_ents = list(nlp(claim).ents)
    out=[]
    for ent in claim_ents:
        if ent.label_ not in valid_types:
            continue
        spans = text_occurrences(sentence, ent.text)
        if len(spans) != 1:
            continue
        a,b=spans[0]
        substitutions = sorted({x.text for x in src_ents if x.label_ == ent.label_
                               and x.text.casefold() != ent.text.casefold()
                               and not text_occurrences(sentence, x.text)
                               and not text_occurrences(evidence_text, x.text)})
        for sub in substitutions[:3]:
            out.append(Change("entity", "same_ner_label", sentence[a:b], sub, a,b,
                              ("same_ner_label", "replacement_occurs_in_source"),
                              ("a entidade substituta pode também ser factualmente correta",)))
    return out


def eligible_reference(ref: dict[str, Any]) -> tuple[bool, list[str]]:
    """Reject old sentence-level review exports and non-validated claim references."""
    issues=[]
    if ref.get("schema_version") != "1.0": issues.append("unsupported_schema_or_sentence_level")
    if not ref.get("reference_claim_id"): issues.append("missing_reference_claim_id")
    if not ref.get("sentence_coverage_reviewed") and ref.get("claim_validation_status")!="HUMAN_VALIDATED": issues.append("claim_validation_required")
    if ref.get("reference_status") != "VALIDATED": issues.append("reference_not_validated")
    if ref.get("claim_label") != "SUPPORTED": issues.append("original_claim_not_supported")
    evidence_ids = {e.get("evidence_id") for e in ref.get("evidences", [])}
    sets = [s for s in ref.get("known_sufficient_evidence_sets", [])
            if s.get("relation") == "SUPPORTED" and s.get("sufficiency_validated") is True
            and s.get("evidence_ids") and set(s["evidence_ids"]).issubset(evidence_ids)]
    if not sets: issues.append("no_validated_sufficient_support_set")
    if not ref.get("claim_en") or not ref.get("summary_sentence_en"):
        issues.append("missing_claim_or_sentence_text")
    if not ref.get("doc_id") or not ref.get("summary_sentence_id"):
        issues.append("missing_document_or_sentence_id")
    return not issues, issues


def _verify_evidence_spans(ref: dict[str, Any], report: str) -> list[str]:
    errors=[]
    for e in ref.get("evidences", []):
        p = e.get("source_span") or {}
        start, end = p.get("start_char"), p.get("end_char")
        if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(report):
            errors.append("bad_source_span:"+str(e.get("evidence_id")))
        elif " ".join(report[start:end].split()) != " ".join(str(e.get("text_en", "")).split()):
            errors.append("evidence_text_mismatch:"+str(e.get("evidence_id")))
    return errors


def _capitalize_change(old: str, new: str) -> str:
    if old.isupper(): return new.upper()
    if old[:1].isupper(): return new[:1].upper() + new[1:]
    return new


def generate_for_reference(ref: dict[str, Any], source: dict[str, Any], *, seed: int = 42,
                           strategies: Iterable[str] = ("numeric", "negation", "antonym"),
                           nlp: Any = None, antonyms: dict[str,str] | None = None,
                           max_per_claim: int = 3, coref_resolver=None, one_per_type=False) -> tuple[list[dict], list[str]]:
    ok, reasons = eligible_reference(ref)
    if not ok: return [],reasons
    report, summary = source.get("report"), source.get("summary")
    if not isinstance(report,str) or not isinstance(summary,str):
        return [], ["missing_source_report_or_full_summary"]
    if source.get("doc_id") != ref["doc_id"]:
        return [], ["document_id_mismatch"]
    if ref.get("source_document_sha256"):
        if hashlib.sha256(report.encode()).hexdigest() != ref["source_document_sha256"]:
            return [], ["source_document_hash_mismatch"]
    spans_errors = _verify_evidence_spans(ref, report)
    if spans_errors: return [],spans_errors
    original_sentence, claim=ref["summary_sentence_en"],ref["claim_en"]
    positions=[m.start() for m in re.finditer(re.escape(original_sentence),summary)]
    if len(positions)!=1: return [], ["sentence_not_unique_in_full_summary"]
    if ERROR_TAG.search(original_sentence) or ERROR_TAG.search(summary):
        return [], ["original_contains_error_mask"]
    evidence_text = _evidence_texts(ref)
    selected=set(strategies)
    candidates=[]
    if "numeric" in selected: candidates += numeric_changes(original_sentence,claim,evidence_text)
    if "negation" in selected or "antonym" in selected:
        candidates += [c for c in predicate_changes(original_sentence,claim,antonyms)
                       if c.strategy in selected]
    coref_traces={}
    if "coreference" in selected:
        if nlp is None or coref_resolver is None:
            raise ValueError('Coreferência controlada requer parser e resolvedor contextual; o piloto he/she não é usado.')
        from .claim_injections import coreference_edits,confirm_wrong_antecedent
        for proposal in coreference_edits(nlp(original_sentence),nlp(summary),positions[0],coref_resolver,evidence_text):
            if len(text_occurrences(claim,proposal.change.old))==1 and confirm_wrong_antecedent(proposal,summary,positions[0],coref_resolver):
                c=proposal.change;candidates.append(c);coref_traces[(c.start,c.end,c.new)]=proposal.trace
    if "entity" in selected:
        if nlp is None:raise ValueError('Entidades nomeadas requerem parser/NER.')
        from .claim_injections import named_entity_edits
        for proposal in named_entity_edits(nlp(original_sentence),nlp(report),evidence_text):
            if len(text_occurrences(claim,proposal.change.old))==1:
                c=proposal.change;candidates.append(c);coref_traces[(c.start,c.end,c.new)]=proposal.trace
    if not candidates: return [], ["no_safe_candidate_under_enabled_strategies"]
    rng=stable_random(seed,ref["doc_id"],ref["reference_claim_id"])
    # Deterministic per-claim selection independent of input order.
    candidates=sorted(candidates,key=lambda c:(c.category,c.strategy,c.start,c.new))
    rng.shuffle(candidates)
    results=[]
    used_categories=set()
    for c in candidates:
        if len(results)>=max_per_claim: break
        if one_per_type and c.category in used_categories:continue
        if original_sentence[c.start:c.end] != c.old:
            continue
        replacement=c.new if c.strategy=='named_entity_swap' else _capitalize_change(c.old,c.new)
        if c.strategy=='named_entity_swap' and c.start==0:replacement=replacement[:1].upper()+replacement[1:]
        claim_occurrences=text_occurrences(claim,c.old)
        if len(claim_occurrences)!=1:continue
        claim_a,claim_b=claim_occurrences[0]
        modified_claim=claim[:claim_a]+replacement+claim[claim_b:]
        if c.old.casefold()==replacement.casefold(): continue
        a,b=positions[0]+c.start,positions[0]+c.end
        new_summary=summary[:a]+replacement+summary[b:]
        new_sentence=original_sentence[:c.start]+replacement+original_sentence[c.end:]
        if new_summary==summary or ERROR_TAG.search(new_summary): continue
        # The submitted text has ONE localized edit, and includes unchanged other sentences.
        key=f"{VERSION}|{ref['doc_id']}|{ref['reference_claim_id']}|{c.strategy}|{a}|{replacement}"
        pair_id="I_"+hashlib.sha256(key.encode()).hexdigest()[:16]
        results.append({
            "schema_version":"2.0", "injection_id":pair_id,
            "document_id":ref["doc_id"], "summary_sentence_id":ref["summary_sentence_id"],
            "reference_claim_id":ref["reference_claim_id"],"claim_id":ref["reference_claim_id"],
            "claim_en":claim,"claim_origin":"HUMAN_VALIDATED_REFERENCE",
            "original_claim_en":claim,"modified_claim_en":modified_claim,
            "claim_edit":{"start_char":claim_a,"end_char":claim_b,"original":c.old,"replacement":replacement},
            "expected_inconsistency_type":c.category,
            "expected_relation":"CONTRADICTED","expected_label_is_validated":False,
            "expected_relation_status":"HYPOTHESIS_NOT_GOLD",
            "original_sentence_en":original_sentence,"modified_sentence_en":new_sentence,
            "original_summary_en":summary,"modified_summary_en":new_summary,
            "error_category":c.category,"strategy":c.strategy,
            "edit":{"start_char":a,"end_char":b,"original":c.old,"replacement":replacement},
            "known_sufficient_evidence_sets":[s for s in ref["known_sufficient_evidence_sets"]
                        if s["relation"]=="SUPPORTED" and s["sufficiency_validated"]],
            "evidences":ref["evidences"],
            "reference_status":ref["reference_status"],
            "transformation_trace":coref_traces.get((c.start,c.end,c.new),{}),
            "hypothesized_modified_relation":"CONTRADICTED",
            "validation_status":"RULE_CHECKED_PROVISIONAL",
            "human_validated_modified_relation":False,
            "gold_eligible":False,
            "validation_checks":list(c.checks),"remaining_caveats":list(c.caveats),
            "generator":{"version":VERSION,"seed":seed,"source_sha256":hashlib.sha256(report.encode()).hexdigest()},
        })
        used_categories.add(c.category)
    return results, ([] if results else ["all_candidates_rejected"])


def validate_pair(row: dict[str, Any]) -> list[str]:
    errors=[]
    orig=row.get("original_summary_en", "")
    modified=row.get("modified_summary_en", "")
    e=row.get("edit", {})
    start,end=e.get("start_char"),e.get("end_char")
    if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(orig):
        return ["invalid_edit_offsets"]
    if orig[start:end] != e.get("original"): errors.append("original_span_mismatch")
    if orig[:start]+e.get("replacement", "")+orig[end:] != modified:
        errors.append("more_than_one_change_or_edit_mismatch")
    if ERROR_TAG.search(modified):errors.append("error_marker_leaked")
    if row.get("gold_eligible") is True and row.get("human_validated_modified_relation") is not True:
        errors.append("unjustified_gold_status")
    if row.get("reference_granularity") == "CLAUSE_LEVEL_PROVISIONAL":
        if row.get("validation_status")!="PROPOSAL_CLAUSE_ONLY" or row.get("gold_eligible"):
            errors.append("clause_only_must_stay_provisional")
        if row.get("reference_claim_id") is not None or not row.get("claim_id"):
            errors.append("invalid_provisional_claim_identity")
        spans=row.get("claim_token_spans",[])
        if not spans or any(not orig[i].isspace() and not any(s.get("start_char",-1)<=i<s.get("end_char",-1) for s in spans) for i in range(start,end)):
            errors.append("edit_outside_target_claim")
        if row.get("error_category") not in {"predicate","entity","coreference"}:
            errors.append("invalid_inconsistency_category")
        if any(start<s.get("end_char",0) and s.get("start_char",len(orig))<end for s in row.get("other_claim_token_spans",[])):
            errors.append("edit_affects_other_claim")
        if row.get("error_category")=="coreference" and not row.get("transformation_trace",{}).get("modified_cluster_link_confirmed"):
            errors.append("unconfirmed_coreference_change")
    elif row.get("reference_granularity") == "SENTENCE_LEVEL":
        if row.get("validation_status") != "PROPOSAL_SENTENCE_ONLY" or row.get("gold_eligible"):
            errors.append("sentence_only_must_stay_provisional")
        if row.get("reference_claim_id") is not None:
            errors.append("sentence_only_must_not_claim_reference")
    else:
        if not row.get("reference_claim_id"):errors.append("missing_claim_reference")
        ev_ids={v.get("evidence_id") for v in row.get("evidences", [])}
        if not any(s.get("evidence_ids") and set(s["evidence_ids"]).issubset(ev_ids)
                   and s.get("sufficiency_validated") for s in row.get("known_sufficient_evidence_sets", [])):
            errors.append("missing_sufficient_evidence_set")
    return errors


def generate_for_sentence_candidate(candidate: dict[str, Any], source: dict[str, Any], *,
                                    seed: int = 42,
                                    strategies: Iterable[str] = ("numeric", "negation", "antonym"),
                                    nlp: Any = None, antonyms: dict[str,str] | None = None,
                                    max_per_sentence: int = 3) -> tuple[list[dict], list[str]]:
    """Transition aid for the user's EXISTING reviews: proposal only, no claim-level gold.

    Sentence-level evidence links are NOT declared sufficient for a claim. These rows
    are not eligible for claim-retrieval or NLI-reference metrics.
    """
    if candidate.get("reference_granularity") != "SENTENCE_LEVEL" or candidate.get("claim_level_sufficiency") != "NOT_ASSESSED":
        return [], ["unexpected_candidate_schema_or_sufficiency_claim"]
    doc_id, summary_id = candidate.get("doc_id"), candidate.get("summary_sentence_id")
    sentence = candidate.get("summary_sentence_en")
    report,summary=source.get("report"),source.get("summary")
    if not isinstance(sentence,str) or not isinstance(summary,str) or not isinstance(report,str):
        return [], ["missing_original_texts"]
    if source.get("doc_id")!=doc_id: return [], ["document_id_mismatch"]
    if not candidate.get("supporting_passages_reviewed"): return [], ["no_reviewed_support"]
    positions=[m.start() for m in re.finditer(re.escape(sentence),summary)]
    if len(positions)!=1: return [], ["sentence_not_unique_in_full_summary"]
    evidence_text="\n".join(str(e.get("text_en", "")) for e in candidate.get("supporting_passages_reviewed", []))
    choices=[]
    strategies=set(strategies)
    if "numeric" in strategies: choices.extend(numeric_changes(sentence,sentence,evidence_text))
    if "negation" in strategies or "antonym" in strategies:
        choices.extend(x for x in predicate_changes(sentence,sentence,antonyms) if x.strategy in strategies)
    if "coreference" in strategies: choices.extend(coreference_changes(sentence,sentence))
    if "entity" in strategies: choices.extend(entity_changes(sentence,sentence,report,evidence_text,nlp))
    if not choices: return [], ["no_candidate_found"]
    rng=stable_random(seed,str(doc_id),str(summary_id))
    choices=sorted(choices,key=lambda x:(x.category,x.strategy,x.start,x.new))
    rng.shuffle(choices)
    result=[]
    for c in choices[:max_per_sentence]:
        new=_capitalize_change(c.old,c.new)
        a,b=positions[0]+c.start,positions[0]+c.end
        modified=summary[:a]+new+summary[b:]
        if modified==summary or ERROR_TAG.search(modified): continue
        key=f"{VERSION}|{doc_id}|{summary_id}|{c.strategy}|{a}|{new}"
        result.append({
            "schema_version":"2.0", "reference_granularity":"SENTENCE_LEVEL",
            "injection_id":"I_"+hashlib.sha256(key.encode()).hexdigest()[:16],
            "document_id":doc_id,"summary_sentence_id":summary_id,
            "reference_claim_id":None,"original_claim_en":None,
            "original_sentence_en":sentence,
            "modified_sentence_en":sentence[:c.start]+new+sentence[c.end:],
            "original_summary_en":summary,"modified_summary_en":modified,
            "error_category":c.category,"strategy":c.strategy,
            "edit":{"start_char":a,"end_char":b,"original":c.old,"replacement":new},
            "supporting_passages_reviewed":candidate["supporting_passages_reviewed"],
            "known_sufficient_evidence_sets":[],
            "validation_status":"PROPOSAL_SENTENCE_ONLY",
            "validation_checks":list(c.checks),
            "human_validated_modified_relation":False,"hypothesized_modified_relation":"UNKNOWN",
            "gold_eligible":False,
            "remaining_caveats":list(c.caveats)+[
                "referência sentencial não estabelece suficiência para claims",
                "nenhuma contradição factual foi humanamente confirmada nesta proposta"],
            "generator":{"version":VERSION,"seed":seed,"source_sha256":hashlib.sha256(report.encode()).hexdigest()}
        })
    return result, ([] if result else ["all_candidates_rejected"])
