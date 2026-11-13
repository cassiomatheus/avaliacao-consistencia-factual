#!/usr/bin/env python3
"""Adapt V6 composer selections to evaluator CSV (no models required)."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from factual_eval.fase2_injecao.external_summaries import main
if __name__=='__main__':main()
