#!/usr/bin/env python3
"""Compatibility launcher; canonical: scripts/fase3_pipeline/run_pipeline.py."""
from pathlib import Path
import runpy
if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'fase3_pipeline' / 'run_pipeline.py'), run_name='__main__', init_globals={'_LEGACY_LAUNCH':True})
