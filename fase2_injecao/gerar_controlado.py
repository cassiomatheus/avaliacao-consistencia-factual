"""Strict Phase 2: only human-validated original reference claims."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase2_injecao.controlled.cli import main
if __name__=='__main__':
    if len(sys.argv)<2 or sys.argv[1] not in {'generate','validate','-h','--help'}:
        raise SystemExit('Fase 2 canônica: use generate --references reference_claims.jsonl --source sources.jsonl, ou validate. Revisões sentenciais são provisórias.')
    if sys.argv[1]=='generate':
        if '--strategies' not in sys.argv:sys.argv+=['--strategies','numeric','negation','antonym','entity','coreference']
        if '--max-per-claim' not in sys.argv:sys.argv+=['--max-per-claim','3']
        if '--one-per-type' not in sys.argv:sys.argv+=['--one-per-type']
    main()
