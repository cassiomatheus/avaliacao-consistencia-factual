"""Freeze a saved integrated review without changing the working annotations."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase1_referencia.review_server import read_page
from factual_eval.fase1_referencia.workspace import prepare_dataset,read_rows,freeze_workspace

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--html',required=True,type=Path);p.add_argument('--source',required=True,type=Path)
    p.add_argument('--annotations',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    dataset=prepare_dataset(read_page(a.html)[1],read_rows(a.source))
    print(freeze_workspace(dataset,json.loads(a.annotations.read_text()),a.output))
