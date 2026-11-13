#!/usr/bin/env python3
"""Entry point for pipeline."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from factual_eval.cli import main as legacy_main
from factual_eval.fase3_pipeline.runner import main

if __name__ == '__main__':
    raise SystemExit(legacy_main('pipeline') if globals().get('_LEGACY_LAUNCH') else main())
