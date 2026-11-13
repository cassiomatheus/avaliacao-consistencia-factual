"""Regenerate report presentation from experiment decisions without rerunning models."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase1_referencia.workspace import read_rows
from factual_eval.avaliacao_automatica.reporting import report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experiment',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    manifest=json.loads((a.experiment/'manifest.json').read_text())
    from hashlib import sha256
    expected=manifest.get('files',{}).get('decisions.jsonl')
    if manifest.get('status')!='complete' or not expected or sha256((a.experiment/'decisions.jsonl').read_bytes()).hexdigest()!=expected:
        p.error('Use a complete experiment with verified decisions.jsonl')
    print(json.dumps(report(read_rows(a.experiment/'decisions.jsonl'),a.output,manifest),ensure_ascii=False,indent=2))
