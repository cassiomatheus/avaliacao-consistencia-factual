"""Evaluate alignment on known correspondences, independently of factual accuracy."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.avaliacao_automatica.alignment import ModelEquivalence,evaluate_aligner
from factual_eval.config import load_config

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--semantic',action='store_true')
    a=p.parse_args()
    if a.output.exists():p.error('Use a new output path')
    result=evaluate_aligner(json.loads(a.cases.read_text()),ModelEquivalence(load_config()) if a.semantic else None)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as handle:json.dump(result,handle,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='results'},indent=2))
