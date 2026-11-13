#!/usr/bin/env python3
"""Entry point for review-html."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from factual_eval.cli import main

if __name__ == '__main__':
    if '--output-root' not in sys.argv:sys.argv+=['--output-root','outputs/fase1_referencia']
    raise SystemExit(main('review-html'))
