"""Original source -> original-only claims; no injections or evaluated predictions."""
import argparse
import csv
import json
from pathlib import Path
from factual_eval.config import load_config,project_path
from factual_eval.runs import Run
from factual_eval.cli import execute_stage


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--config');p.add_argument('--device',choices=['auto','cpu','cuda','cuda:0'])
    p.add_argument('--output-root',default='outputs/fase1_referencia');p.add_argument('--run-id')
    a=p.parse_args();source=project_path(a.source);config=load_config(a.config)
    if a.device:config['runtime']['device']=a.device
    def original_input(folder):
        records=[json.loads(l) for l in source.read_text().splitlines() if l.strip()]
        if not records:raise ValueError('Empty original source')
        rows=[];seen=set()
        for i,r in enumerate(records):
            index=r.get('source_index',i)
            if index in seen:raise ValueError('Duplicate source_index')
            seen.add(index)
            rows.append({'source_index':index,'fonte':r['report'],'resumo_original':r['summary'],
                         'resumo_entity':'','resumo_predicado':'','resumo_corref':''})
        dest=folder/'original_only.csv'
        with dest.open('x',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return dest
    with Run(project_path(a.output_root),config,run_id=a.run_id) as run:
        csv_input=run.stage('original-input',source,original_input)
        output=run.stage('claims',csv_input,lambda folder:execute_stage('claims',csv_input,folder,config))
        print('Run:',run.path);print('Output:',output)
